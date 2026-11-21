"""Seerr-ønsker (Fangarr 1.23.0) – se LÆSMIG.md › "Seerr-ønsker (1.23.0)".

Fangarr bestemmer, hvem der må ønske i Seerr, ud fra Kunder:
- Pakke (Lille, Populær, Stor, Maks): en tjeneste "Ekstra ønsker" på kundekortet, som betales med kundens cyklus.
  En ny eller større pakke virker med det samme, og næste opkrævning får et tillæg for dagene indtil da.
  En mindre pakke eller stop gælder fra næste betaling.
- Enkeltkøb (film og sæsoner): et tillæg på næste opkrævning. Købte ønsker udløber aldrig.
- Familie (type "Egen" på kundekortet): ubegrænset og gratis.
- Alle andre må ikke ønske (ingen gratis ønsker fra 21. nov. 2026).

Vigtigt i Seerr: grænsen 0 betyder "ubegrænset". Fangarr giver derfor aldrig en kunde grænsen 0 – en kunde uden ønsker
mister i stedet retten til at ønske. Admin, brugere med "Administrer brugere" og Seerr-brugere under "Rør ikke" røres
aldrig. I prøvetilstand (standard) viser Fangarr kun, hvad den ville ændre i Seerr.
"""
import datetime
import json
import math
import os
import re
import threading
import time

import httpx
from fastapi import APIRouter, HTTPException, Request

from . import kunder

router = APIRouter(prefix="/api/oensker")
D = {}   # udfyldes af main.py: db, telegram, now, kv_get, kv_set, log

REQ, REQ_MOVIE, REQ_TV = 32, 262144, 524288          # Anmod · Anmod film · Anmod serier
REQ_ANY = REQ | REQ_MOVIE | REQ_TV
AUTO = 8388608 | 16777216 | 33554432                  # Auto-anmod (huskelisten i Plex ønsker automatisk)
ADMIN, MANAGE_USERS = 2, 8
WINDOW_DAYS = 30                                     # Seerrs grænser gælder pr. 30 dage
UNLIMITED = 0                                        # Seerr: 0 = ubegrænset – bruges kun til familien

PACKAGES = [
    {"key": "lille", "name": "Lille", "price": 9, "film": 3, "tv": 0},
    {"key": "populaer", "name": "Populær", "price": 19, "film": 5, "tv": 2},
    {"key": "stor", "name": "Stor", "price": 39, "film": 17, "tv": 9},
    {"key": "maks", "name": "Maks", "price": 59, "film": 29, "tv": 13},
]
DEFAULTS = {
    "mode": "prove",        # fra · prove (vis kun, hvad der ville ske) · til (ret Seerr for alvor)
    "untouchable": "",      # Seerr-bruger-id'er, Fangarr aldrig rører (fx dine egne konti), adskilt med komma
    "packages": PACKAGES,
    "price_film": 5,        # enkeltkøb pr. film
    "price_tv": 10,         # enkeltkøb pr. sæson
    "brake": 5,             # mister flere end så mange retten til at ønske på én gang, stopper Fangarr og giver besked
    "shop": False,          # kunderne kan selv vælge pakke og købe ønsker i guiden (1.25.0) – kræver NYT_TOKEN og tilstand Til
    "shop_section": "",     # afsnittet i guiden, hvor knappen "Få flere ønsker" står (tom = find selv afsnittet om Seerr)
}
MODES = ("fra", "prove", "til")

SEERR_URL = (os.environ.get("SEERR_URL") or "").rstrip("/")
SEERR_APIKEY = os.environ.get("SEERR_APIKEY") or ""

_lock = threading.Lock()          # pakker, køb og opkrævninger
_sync_lock = threading.Lock()     # kun én gennemgang af Seerr ad gangen
_last = {"sync": 0.0}


def setup(**deps):
    D.update(deps)


def now():
    return D["now"]()


def iso(dt):
    return dt.isoformat(timespec="seconds")


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def _utc(v):
    """Seerrs tidspunkt ('2026-11-21T09:40:00.000Z') eller Fangarrs lokale tid ('2026-11-21T10:40:00') -> UTC."""
    if not v:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(datetime.timezone.utc)   # uden tidszone = lokal tid (containeren kører med TZ=Europe/Copenhagen)


def enabled():
    return bool(SEERR_URL and SEERR_APIKEY)


def _sx(method, path, **kw):
    r = httpx.request(method, SEERR_URL + "/api/v1" + path, headers={"X-Api-Key": SEERR_APIKEY}, timeout=30, **kw)
    r.raise_for_status()
    return r.json() if r.content else None


rows, one, run = kunder.rows, kunder.one, kunder.run


# ---------------------------------------------------------------- database og indstillinger

def init():
    con = D["db"]()
    with con:
        con.execute("CREATE TABLE IF NOT EXISTS s_pkg (plex_user_id INTEGER PRIMARY KEY, customer_id INTEGER, package TEXT, service_id INTEGER,"
                    " started TEXT, pending TEXT, pending_date TEXT, pending_period TEXT, pending_billed INTEGER DEFAULT 0, updated TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS s_buy (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, plex_user_id INTEGER,"
                    " film INTEGER DEFAULT 0, tv INTEGER DEFAULT 0, amount REAL DEFAULT 0, text TEXT DEFAULT '', adjust_id INTEGER,"
                    " charge_id INTEGER, created TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS s_used (request_id INTEGER PRIMARY KEY, plex_user_id INTEGER, kind TEXT, units INTEGER, created TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS s_seen (request_id INTEGER PRIMARY KEY, plex_user_id INTEGER, ts TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS s_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, customer_id INTEGER, plex_user_id INTEGER, text TEXT)")
    con.close()


def settings():
    s = json.loads(json.dumps(DEFAULTS))
    s.update(D["kv_get"]("oensker_settings", {}) or {})
    return s


def packages():
    return {p["key"]: p for p in settings()["packages"]}


def _untouchable(s=None):
    out = set()
    for x in str((s or settings())["untouchable"] or "").replace(";", ",").split(","):
        x = x.strip()
        if x.isdigit():
            out.add(int(x))
    return out


def _log(text, cid=None, pid=None, con=None):
    sql, args = "INSERT INTO s_log (ts, customer_id, plex_user_id, text) VALUES (?,?,?,?)", (iso(now()), cid, pid, text)
    if con is not None:
        con.execute(sql, args)
    else:
        run(sql, args)
    D["log"].info("Seerr-ønsker: %s", text)


def _kr(v):
    return kunder._amount(v) + " kr."


def _day(d):
    return kunder._day_text(d)


def _units(film, tv):
    parts = []
    if film:
        parts.append(f"{film} film")
    if tv:
        parts.append(f"{tv} {'sæson' if tv == 1 else 'sæsoner'}")
    return " og ".join(parts) or "ingen"


# ---------------------------------------------------------------- kunder, konti og næste betaling

def _customer(cid):
    c = one("SELECT * FROM k_customers WHERE id=?", (cid,))
    if not c:
        raise HTTPException(404, "kunden findes ikke")
    return c


def _accounts(cid):
    """Kundens Plex-konti: aktive Plex-tjenester, der er koblet til en Plex-bruger."""
    plex = {r["user_id"]: r for r in rows("SELECT * FROM k_plex")}
    out = []
    for s in rows("SELECT * FROM k_services WHERE customer_id=? AND service='plex' AND active=1 AND plex_user_id IS NOT NULL ORDER BY id", (cid,)):
        p = plex.get(s["plex_user_id"]) or {}
        out.append({"plex_user_id": s["plex_user_id"], "username": p.get("username") or s["username"] or "",
                    "name": s["label"] or p.get("friendly_name") or p.get("username") or s["username"] or "Plex-konto"})
    return out


def _account(cid, pid):
    acc = _accounts(cid)
    if pid in (None, "", 0, "0") and len(acc) == 1:
        return acc[0]
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        raise HTTPException(400, "vælg hvilken Plex-konto det gælder") from None
    a = next((x for x in acc if x["plex_user_id"] == pid), None)
    if not a:
        raise HTTPException(400, "Plex-kontoen hører ikke til kunden")
    return a


def next_payment(c):
    """Kundens næste betaling: den første opkrævning, der ikke er anmodet, betalt eller sprunget over, og hvis
    betalingsdato er i dag eller senere – ellers den næste måned i kundens cyklus, der ikke har en opkrævning endnu."""
    if c["kind"] != "kunde" or c["status"] != "aktiv" or not kunder.FREQ.get(c["freq"]):
        return None
    today = now().date()
    for ch in rows("SELECT id, period FROM k_charges WHERE customer_id=? AND requested_at IS NULL AND paid_at IS NULL AND skipped=0"
                   " ORDER BY period", (c["id"],)):
        p = ch["period"][:7]
        d = kunder._due_date(c["due_day"], p)
        if d >= today:
            return {"period": p, "date": d, "charge_id": ch["id"]}
    have = {r["period"][:7] for r in rows("SELECT period FROM k_charges WHERE customer_id=?", (c["id"],))}
    months = kunder.due_months(c["freq"], c["cycle"])
    cur = kunder.period_of(now())
    for i in range(0, 25):
        p = kunder._add_months(cur, i)
        if int(p[5:7]) not in months or p in have:
            continue
        d = kunder._due_date(c["due_day"], p)
        if d >= today:
            return {"period": p, "date": d, "charge_id": None}
    return None


def _days_to(nxt):
    return max(0, (nxt["date"] - now().date()).days) if nxt else 0


def _prorata(price, nxt):
    """Pakkens pris for dagene fra i dag til næste betaling: månedspris × dage ÷ 30, rundet til hele kroner."""
    return int(math.floor(float(price) * _days_to(nxt) / 30.0 + 0.5))


def _recalc(con, chid):
    """Regn en opkrævning om ud fra kundens nuværende tjenester. Fradrag og tillæg på opkrævningen bevares."""
    ch = con.execute("SELECT * FROM k_charges WHERE id=?", (chid,)).fetchone()
    c = con.execute("SELECT * FROM k_customers WHERE id=?", (ch["customer_id"],)).fetchone()
    sv = [dict(r) for r in con.execute("SELECT * FROM k_services WHERE customer_id=?", (ch["customer_id"],)).fetchall()]
    det = json.loads(ch["detail"] or "{}")
    n = kunder.FREQ.get(c["freq"], det.get("months") or 0)
    base = kunder.monthly(sv) * n
    det.update({"lines": kunder.service_lines(sv), "months": n})
    amount = max(0.0, base + sum(float(x.get("amount") or 0) for x in det.get("adjust", [])))
    con.execute("UPDATE k_charges SET amount=?, base=?, detail=? WHERE id=?", (amount, base, json.dumps(det, ensure_ascii=False), chid))


def _open_charge(con, chid):
    """Findes opkrævningen stadig, og er den hverken anmodet, betalt eller sprunget over?"""
    if not chid:
        return False
    r = con.execute("SELECT requested_at, paid_at, skipped FROM k_charges WHERE id=?", (chid,)).fetchone()
    return bool(r) and not r["requested_at"] and not r["paid_at"] and not r["skipped"]


def _add_adjust(con, cid, text, amount, nxt):
    """Tillæg på næste betaling. Er næste opkrævning allerede lavet (og ikke anmodet), lægges tillægget direkte på den."""
    amount = kunder.num(float(amount or 0))
    if not amount:
        return None, None
    if nxt and _open_charge(con, nxt["charge_id"]):
        aid = con.execute("INSERT INTO k_adjust (customer_id, amount, text, remaining, created) VALUES (?,?,?,0,?)",
                          (cid, amount, text, iso(now()))).lastrowid
        ch = con.execute("SELECT detail FROM k_charges WHERE id=?", (nxt["charge_id"],)).fetchone()
        det = json.loads(ch["detail"] or "{}")
        det.setdefault("adjust", []).append({"text": text, "amount": amount})
        con.execute("UPDATE k_charges SET detail=? WHERE id=?", (json.dumps(det, ensure_ascii=False), nxt["charge_id"]))
        _recalc(con, nxt["charge_id"])
        return aid, nxt["charge_id"]
    aid = con.execute("INSERT INTO k_adjust (customer_id, amount, text, remaining, created) VALUES (?,?,?,1,?)",
                      (cid, amount, text, iso(now()))).lastrowid
    return aid, None


def _label(p, cid, acc):
    return p["name"] + (f" · {acc['name']}" if len(_accounts(cid)) > 1 else "")


def _set_service(con, row, target, cid, acc):
    """Ret tjenesten "Ekstra ønsker" på kundekortet: ny pris og navn, eller slå den fra (target = '')."""
    pk = packages()
    if not target:
        if row and row["service_id"]:
            con.execute("UPDATE k_services SET active=0 WHERE id=?", (row["service_id"],))
        return row["service_id"] if row else None
    p = pk[target]
    svc = con.execute("SELECT id FROM k_services WHERE id=?", (row["service_id"],)).fetchone() if row and row["service_id"] else None
    if svc:
        con.execute("UPDATE k_services SET label=?, price=?, active=1 WHERE id=?", (_label(p, cid, acc), float(p["price"]), svc["id"]))
        return svc["id"]
    return con.execute("INSERT INTO k_services (customer_id, service, label, price, active) VALUES (?, 'seerr', ?, ?, 1)",
                       (cid, _label(p, cid, acc), float(p["price"]))).lastrowid


# ---------------------------------------------------------------- pakker og enkeltkøb

def _unlinked_service(cid):
    """Kundens tjeneste "Ekstra ønsker", som endnu ikke hører til en pakke (fx fra regnearket), eller None."""
    linked = {r["service_id"] for r in rows("SELECT service_id FROM s_pkg WHERE service_id IS NOT NULL")}
    for r in rows("SELECT * FROM k_services WHERE customer_id=? AND service='seerr' AND active=1 ORDER BY id", (cid,)):
        if r["id"] not in linked:
            return dict(r)
    return None


def _price(key):
    p = packages().get(key or "")
    return float(p["price"]) if p else 0.0


def _months(c):
    return kunder.FREQ.get(c["freq"], 0)


def _expected_next(c, nxt):
    """Det forventede beløb på næste betaling, som det ser ud nu."""
    if not nxt:
        return 0.0
    if nxt["charge_id"]:
        r = one("SELECT amount FROM k_charges WHERE id=?", (nxt["charge_id"],))
        if r:
            return float(r["amount"] or 0)
    return kunder.next_amount(c, _months(c))


def quote_package(cid, pid, target):
    """Hvad sker der, hvis kontoen får pakken target ('' = ingen pakke)? Intet gemmes."""
    c = _customer(cid)
    acc = _account(cid, pid)
    pk = packages()
    target = target or ""
    if target and target not in pk:
        raise HTTPException(400, "ukendt pakke")
    if c["kind"] == "egen":
        raise HTTPException(400, "familie kan allerede ønske ubegrænset – der skal ikke vælges pakke")
    row = one("SELECT * FROM s_pkg WHERE plex_user_id=?", (acc["plex_user_id"],))
    cur = row["package"] if row else ""
    nxt = next_payment(c)
    if not nxt:
        raise HTTPException(400, "kunden har ingen næste betaling – tjek status, type og cyklus på kundekortet")
    n = _months(c)
    exp = _expected_next(c, nxt)
    lines, kind, add = [], "", 0
    pending = row["pending"] if row else None
    old_svc = _unlinked_service(cid) if not row and target else None
    if old_svc:      # kunden betaler allerede for ønsker (gammel tjeneste) – kobl den til kontoen
        kind = "kobl"
        was = float(old_svc["price"] or 0)
        add = _prorata(_price(target) - was, nxt) if _price(target) > was else 0
        lines.append(f"Kunden har allerede tjenesten Ekstra ønsker ({_kr(was)} pr. måned) på kundekortet. "
                     f"Den bliver til pakken {pk[target]['name']} og virker med det samme i Seerr.")
        if add:
            lines.append(f"Tillæg for {_days_to(nxt)} dage indtil næste betaling: {_kr(add)}")
        else:
            lines.append("Intet tillæg – kunden har allerede betalt for perioden.")
        lines.append(f"{pk[target]['name']} fra {_day(nxt['date'])}: {_kr(_price(target) * n)} for {kunder.months_text(n)}")
        exp += add + (_price(target) - was) * n
    elif target == cur:
        kind = "fortryd" if pending is not None else "samme"
        if pending is not None:
            lines.append(f"Det planlagte skift fortrydes – {pk[cur]['name'] if cur else 'ingen pakke'} fortsætter.")
            if row["pending_billed"]:
                exp += (_price(cur) - _price(pending)) * n
    elif _price(target) > _price(cur):
        kind = "nu"
        add = _prorata(_price(target) - _price(cur), nxt)
        lines.append("Virker med det samme i Seerr.")
        if add:
            lines.append(f"Tillæg for {_days_to(nxt)} dage indtil næste betaling: {_kr(add)}")
        lines.append(f"{pk[target]['name']} fra {_day(nxt['date'])}: {_kr(_price(target) * n)} for {kunder.months_text(n)}")
        base_cur = _price(pending if (pending is not None and row["pending_billed"]) else cur)
        exp += add + (_price(target) - base_cur) * n
    else:
        kind = "senere"
        lines.append(f"Gælder fra næste betaling {_day(nxt['date'])}. Indtil da beholder kunden {pk[cur]['name']}.")
        if target:
            lines.append(f"{pk[target]['name']} fra {_day(nxt['date'])}: {_kr(_price(target) * n)} for {kunder.months_text(n)}")
        else:
            lines.append("Pakken stopper – der opkræves ikke for den fra næste betaling.")
        base_cur = _price(pending if (pending is not None and row["pending_billed"]) else cur)
        exp += (_price(target) - base_cur) * n
    return {"kind": kind, "lines": lines, "next_date": nxt["date"].isoformat(), "next_text": _day(nxt["date"]),
            "next_amount": kunder.num(max(0.0, exp)), "from": cur, "to": target, "pending": pending,
            # tallene bag teksten (bruges af Køb i guiden, 1.25.0)
            "add": kunder.num(add), "days": _days_to(nxt), "months": n, "period_amount": kunder.num(_price(target) * n)}


def set_package(cid, pid, target, source="Fangarr"):
    """Giv kontoen pakken target ('' = stop). Større pakke: med det samme + tillæg for dagene til næste betaling.
    Mindre pakke eller stop: fra næste betaling."""
    q = quote_package(cid, pid, target)
    c = _customer(cid)
    acc = _account(cid, pid)
    pk, target = packages(), target or ""
    p_id = acc["plex_user_id"]
    with _lock:
        con = D["db"]()
        try:
            with con:
                row = con.execute("SELECT * FROM s_pkg WHERE plex_user_id=?", (p_id,)).fetchone()
                row = dict(row) if row else None
                cur = row["package"] if row else ""
                nxt = next_payment(c)
                old_svc = _unlinked_service(cid) if q["kind"] == "kobl" else None
                if q["kind"] == "kobl" and old_svc and not row:
                    was = float(old_svc["price"] or 0)
                    sid = _set_service(con, {"service_id": old_svc["id"]}, target, cid, acc)
                    con.execute("INSERT INTO s_pkg (plex_user_id, customer_id, package, service_id, started, updated) VALUES (?,?,?,?,?,?)",
                                (p_id, cid, target, sid, iso(now()), iso(now())))
                    if nxt and _open_charge(con, nxt["charge_id"]):
                        _recalc(con, nxt["charge_id"])
                    add = _prorata(_price(target) - was, nxt) if _price(target) > was else 0
                    if add:
                        end = nxt["date"] - datetime.timedelta(days=1)
                        _add_adjust(con, cid, f"Ekstra Seerr-ønsker – {pk[target]['name']}, {_day(now().date())} – {_day(end)}", add, nxt)
                    _log(f"{acc['name']}: tjenesten Ekstra ønsker ({kunder.num(was)} kr./md.) er koblet til kontoen som pakken "
                         f"{pk[target]['name']}{' – tillæg ' + _kr(add) if add else ''} ({source})", cid, p_id, con)
                    msg = f"{pk[target]['name']} virker nu."
                elif q["kind"] == "kobl":
                    raise HTTPException(409, "kundekortet er ændret imens – prøv igen")
                elif q["kind"] in ("samme", "fortryd"):
                    if row and row["pending"] is not None:
                        _set_service(con, row, cur, cid, acc)
                        con.execute("UPDATE s_pkg SET pending=NULL, pending_date=NULL, pending_period=NULL, pending_billed=0, updated=? WHERE plex_user_id=?",
                                    (iso(now()), p_id))
                        if nxt and _open_charge(con, nxt["charge_id"]):
                            _recalc(con, nxt["charge_id"])
                        _log(f"{acc['name']}: planlagt skift fortrudt – {pk[cur]['name'] if cur else 'ingen pakke'} fortsætter ({source})", cid, p_id, con)
                    msg = "Ingen ændring." if q["kind"] == "samme" else "Det planlagte skift er fortrudt."
                elif q["kind"] == "nu":
                    sid = _set_service(con, row, target, cid, acc)
                    if row:
                        con.execute("UPDATE s_pkg SET package=?, service_id=?, customer_id=?, pending=NULL, pending_date=NULL, pending_period=NULL,"
                                    " pending_billed=0, updated=? WHERE plex_user_id=?", (target, sid, cid, iso(now()), p_id))
                    else:
                        con.execute("INSERT INTO s_pkg (plex_user_id, customer_id, package, service_id, started, updated) VALUES (?,?,?,?,?,?)",
                                    (p_id, cid, target, sid, iso(now()), iso(now())))
                    if nxt and _open_charge(con, nxt["charge_id"]):
                        _recalc(con, nxt["charge_id"])
                    add = _prorata(_price(target) - _price(cur), nxt)
                    if add:
                        end = nxt["date"] - datetime.timedelta(days=1)
                        txt = (f"Ekstra Seerr-ønsker – {pk[target]['name']}" + (f" (skift fra {pk[cur]['name']})" if cur else "")
                               + f", {_day(now().date())} – {_day(end)}")
                        _add_adjust(con, cid, txt, add, nxt)
                    _log(f"{acc['name']}: {('skiftet fra ' + pk[cur]['name'] + ' til ') if cur else 'fik pakken '}{pk[target]['name']}"
                         f"{' – tillæg ' + _kr(add) if add else ''} ({source})", cid, p_id, con)
                    msg = f"{pk[target]['name']} virker nu."
                else:   # mindre pakke eller stop – fra næste betaling
                    con.execute("UPDATE s_pkg SET pending=?, pending_date=?, pending_period=?, pending_billed=0, updated=? WHERE plex_user_id=?",
                                (target, nxt["date"].isoformat(), nxt["period"], iso(now()), p_id))
                    if nxt and _open_charge(con, nxt["charge_id"]):      # næste opkrævning findes allerede: ret den nu
                        _set_service(con, row, target, cid, acc)
                        con.execute("UPDATE s_pkg SET pending_billed=1 WHERE plex_user_id=?", (p_id,))
                        _recalc(con, nxt["charge_id"])
                    what = f"skifter til {pk[target]['name']}" if target else "stopper"
                    _log(f"{acc['name']}: {pk[cur]['name']} {what} fra {_day(nxt['date'])} ({source})", cid, p_id, con)
                    msg = f"Pakken {what} fra {_day(nxt['date'])}."
        finally:
            con.close()
    kick()
    return msg


def quote_buy(cid, pid, film, tv):
    c = _customer(cid)
    _account(cid, pid)
    film, tv = _count(film), _count(tv)
    if not film and not tv:
        raise HTTPException(400, "vælg mindst én film eller sæson")
    s = settings()
    amount = film * float(s["price_film"]) + tv * float(s["price_tv"])
    if c["kind"] == "egen":
        raise HTTPException(400, "familie kan allerede ønske ubegrænset – der skal ikke købes ønsker")
    nxt = next_payment(c)
    if not nxt:
        raise HTTPException(400, "kunden har ingen næste betaling – tjek status, type og cyklus på kundekortet")
    lines = ["Virker med det samme i Seerr, og ønskerne udløber aldrig.",
             f"Enkeltkøb: {_units(film, tv)} – {_kr(amount)} på næste betaling {_day(nxt['date'])}"]
    return {"lines": lines, "amount": kunder.num(amount), "next_date": nxt["date"].isoformat(), "next_text": _day(nxt["date"]),
            "next_amount": kunder.num(_expected_next(c, nxt) + amount), "film": film, "tv": tv}


def _count(v):
    try:
        v = int(v or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "antal skal være et helt tal") from None
    if v < 0 or v > 999:
        raise HTTPException(400, "antal skal være mellem 0 og 999")
    return v


def buy(cid, pid, film, tv, source="Fangarr"):
    q = quote_buy(cid, pid, film, tv)
    acc = _account(cid, pid)
    c = _customer(cid)
    with _lock:
        con = D["db"]()
        try:
            with con:
                nxt = next_payment(c)
                txt = f"Enkeltkøb i Seerr: {_units(q['film'], q['tv'])}"
                aid, chid = _add_adjust(con, cid, txt, q["amount"], nxt)
                con.execute("INSERT INTO s_buy (customer_id, plex_user_id, film, tv, amount, text, adjust_id, charge_id, created) VALUES (?,?,?,?,?,?,?,?,?)",
                            (cid, acc["plex_user_id"], q["film"], q["tv"], q["amount"], txt, aid, chid, iso(now())))
                _log(f"{acc['name']}: købte {_units(q['film'], q['tv'])} – {_kr(q['amount'])} ({source})", cid, acc["plex_user_id"], con)
        finally:
            con.close()
    kick()
    return f"{_units(q['film'], q['tv'])} er lagt på – virker nu."


def undo_buy(bid):
    """Fortryd et enkeltkøb – kun når ønskerne ikke er brugt, og beløbet ikke er anmodet eller betalt."""
    b = one("SELECT * FROM s_buy WHERE id=?", (bid,))
    if not b:
        raise HTTPException(404, "købet findes ikke")
    cr = credits(b["plex_user_id"])
    if cr["film"]["unused"] < b["film"] or cr["tv"]["unused"] < b["tv"]:
        raise HTTPException(400, "nogle af ønskerne er allerede brugt i Seerr – købet kan ikke fortrydes")
    with _lock:
        con = D["db"]()
        try:
            with con:
                if b["charge_id"]:
                    if not _open_charge(con, b["charge_id"]):
                        raise HTTPException(400, "beløbet er allerede anmodet eller betalt – lav i stedet et fradrag på kundekortet")
                    ch = con.execute("SELECT detail FROM k_charges WHERE id=?", (b["charge_id"],)).fetchone()
                    det = json.loads(ch["detail"] or "{}")
                    adj = det.get("adjust", [])
                    i = next((k for k, a in enumerate(adj) if a.get("text") == b["text"] and abs(float(a.get("amount") or 0) - float(b["amount"])) < 0.01), None)
                    if i is not None:
                        adj.pop(i)
                    con.execute("UPDATE k_charges SET detail=? WHERE id=?", (json.dumps(det, ensure_ascii=False), b["charge_id"]))
                    _recalc(con, b["charge_id"])
                    con.execute("DELETE FROM k_adjust WHERE id=?", (b["adjust_id"],))
                else:
                    a = con.execute("SELECT remaining FROM k_adjust WHERE id=?", (b["adjust_id"],)).fetchone()
                    if a and not a["remaining"]:
                        raise HTTPException(400, "beløbet er allerede lagt på en opkrævning – lav i stedet et fradrag på kundekortet")
                    con.execute("DELETE FROM k_adjust WHERE id=?", (b["adjust_id"],))
                con.execute("DELETE FROM s_buy WHERE id=?", (bid,))
                _log(f"Enkeltkøb fortrudt: {_units(b['film'], b['tv'])} ({_kr(b['amount'])})", b["customer_id"], b["plex_user_id"], con)
        finally:
            con.close()
    kick()
    return "Købet er fortrudt."


def before_charge(con, c, period):
    """Kaldes af Kunder, lige før en opkrævning laves: et planlagt skift til en mindre pakke (eller stop) skal med
    på den opkrævning, det gælder fra."""
    for r in con.execute("SELECT * FROM s_pkg WHERE customer_id=? AND pending IS NOT NULL AND pending_billed=0 AND pending_period<=?",
                         (c["id"], period[:7])).fetchall():
        r = dict(r)
        acc = next((a for a in _accounts(c["id"]) if a["plex_user_id"] == r["plex_user_id"]), {"name": "Plex-konto"})
        _set_service(con, r, r["pending"] or "", c["id"], acc)
        con.execute("UPDATE s_pkg SET pending_billed=1 WHERE plex_user_id=?", (r["plex_user_id"],))


# ---------------------------------------------------------------- købte ønsker (credits)

def credits(pid):
    """Købte ønsker for én Plex-konto: købt, brugt, ubrugt – og hvor mange brugte, der stadig er i Seerrs 30-dages vindue."""
    b = one("SELECT COALESCE(SUM(film),0) f, COALESCE(SUM(tv),0) t FROM s_buy WHERE plex_user_id=?", (pid,))
    since = iso(utcnow() - datetime.timedelta(days=WINDOW_DAYS))
    out = {}
    for kind, bought in (("film", b["f"]), ("tv", b["t"])):
        used = one("SELECT COALESCE(SUM(units),0) n FROM s_used WHERE plex_user_id=? AND kind=?", (pid, kind))["n"]
        win = one("SELECT COALESCE(SUM(units),0) n FROM s_used WHERE plex_user_id=? AND kind=? AND created>?", (pid, kind, since))["n"]
        out[kind] = {"bought": int(bought), "used": int(used), "unused": max(0, int(bought) - int(used)), "window": int(win)}
    return out


def _requests(seerr_id):
    out = []
    for r in (_sx("GET", f"/user/{seerr_id}/requests", params={"take": 100, "skip": 0}) or {}).get("results") or []:
        if r.get("status") == 3:          # afviste tæller ikke med i Seerrs grænse
            continue
        t = _utc(r.get("createdAt"))
        if not t or not r.get("id"):
            continue
        tv = r.get("type") == "tv"
        out.append({"id": int(r["id"]), "kind": "tv" if tv else "film", "t": t, "units": max(1, len(r.get("seasons") or [])) if tv else 1})
    out.sort(key=lambda x: (x["t"], x["id"]))
    return out


def _attribute(seerr_id, pid, pkg):
    """Find nye ønsker og se, om de er brugt af pakken eller af købte ønsker. Ønsker fra før første køb bruger aldrig
    købte ønsker. Giver også, hvor meget kontoen har brugt de sidste 30 dage."""
    reqs = _requests(seerr_id)
    first = one("SELECT MIN(created) m FROM s_buy WHERE plex_user_id=?", (pid,))["m"]
    first = _utc(first) if first else None
    seen = {r["request_id"] for r in rows("SELECT request_id FROM s_seen WHERE plex_user_id=?", (pid,))}
    used = {r["request_id"]: r["units"] for r in rows("SELECT request_id, units FROM s_used WHERE plex_user_id=?", (pid,))}
    cr = credits(pid)
    left = {"film": cr["film"]["unused"], "tv": cr["tv"]["unused"]}
    allow = {"film": int(pkg["film"]) if pkg else 0, "tv": int(pkg["tv"]) if pkg else 0}
    con = D["db"]()
    try:
        with con:
            for i, it in enumerate(reqs):
                if it["id"] in seen:
                    continue
                take = 0
                if first and it["t"] >= first and left[it["kind"]] > 0:
                    start = it["t"] - datetime.timedelta(days=WINDOW_DAYS)
                    before = [x for x in reqs[:i] if x["kind"] == it["kind"] and x["t"] > start]
                    by_credits = sum(used.get(x["id"], 0) for x in before)
                    by_pkg = sum(x["units"] for x in before) - by_credits
                    room = max(0, allow[it["kind"]] - by_pkg)
                    take = min(max(0, it["units"] - room), left[it["kind"]])
                if take:
                    con.execute("INSERT OR REPLACE INTO s_used (request_id, plex_user_id, kind, units, created) VALUES (?,?,?,?,?)",
                                (it["id"], pid, it["kind"], take, iso(it["t"])))
                    used[it["id"]] = take
                    left[it["kind"]] -= take
                con.execute("INSERT OR IGNORE INTO s_seen (request_id, plex_user_id, ts) VALUES (?,?,?)", (it["id"], pid, iso(now())))
    finally:
        con.close()
    start = utcnow() - datetime.timedelta(days=WINDOW_DAYS)
    return {"film": sum(x["units"] for x in reqs if x["kind"] == "film" and x["t"] > start),
            "tv": sum(x["units"] for x in reqs if x["kind"] == "tv" and x["t"] > start)}


# ---------------------------------------------------------------- Seerr: hvem må ønske?

def _seerr_users():
    users, skip = [], 0
    while True:
        d = _sx("GET", "/user", params={"take": 100, "skip": skip}) or {}
        res = d.get("results") or []
        users += res
        skip += 100
        if not res or len(users) >= int((d.get("pageInfo") or {}).get("results") or 0) or skip > 5000:
            break
    return users


def _uname(u):
    for k in ("displayName", "plexUsername", "username"):
        v = u.get(k)
        if v and "@" not in str(v):
            return str(v)
    return f"Seerr-bruger {u.get('id')}"


def _lim(v, one_, many):
    if v is None:
        return "fælles grænse"
    if v == UNLIMITED:
        return "ubegrænset"
    return f"{v} {one_ if v == 1 else many}"


def _desc(bits, movie, tv):
    """Kort tekst: hvad kan brugeren ønske i Seerr?"""
    if not bits & REQ_ANY:
        return "kan ikke ønske"
    f, t = _lim(movie, "film", "film"), _lim(tv, "sæson", "sæsoner")
    if movie is None and tv is None:
        return "fælles grænse"
    if bits & REQ:
        return "ubegrænset" if movie == UNLIMITED and tv == UNLIMITED else f"{f} og {t} pr. 30 dage"
    if bits & REQ_MOVIE:
        return f"{f} pr. 30 dage (kun film)"
    return f"{t} pr. 30 dage (kun serier)"


def _apply_due_pending():
    """Planlagte skift, hvis dato er nået: kontoen får den mindre pakke – eller pakken stopper."""
    today = now().date().isoformat()
    pk = packages()
    with _lock:
        con = D["db"]()
        try:
            with con:
                for r in con.execute("SELECT * FROM s_pkg WHERE pending IS NOT NULL AND pending_date<=?", (today,)).fetchall():
                    r = dict(r)
                    acc = next((a for a in _accounts(r["customer_id"]) if a["plex_user_id"] == r["plex_user_id"]), {"name": "Plex-konto"})
                    if not r["pending_billed"]:
                        _set_service(con, r, r["pending"] or "", r["customer_id"], acc)
                    if r["pending"]:
                        con.execute("UPDATE s_pkg SET package=?, pending=NULL, pending_date=NULL, pending_period=NULL, pending_billed=0, updated=?"
                                    " WHERE plex_user_id=?", (r["pending"], iso(now()), r["plex_user_id"]))
                        _log(f"{acc['name']}: har nu {pk.get(r['pending'], {}).get('name', r['pending'])}", r["customer_id"], r["plex_user_id"], con)
                    else:
                        con.execute("DELETE FROM s_pkg WHERE plex_user_id=?", (r["plex_user_id"],))
                        _log(f"{acc['name']}: pakken er stoppet", r["customer_id"], r["plex_user_id"], con)
        finally:
            con.close()


def _check_services():
    """En pakke, hvis tjeneste "Ekstra ønsker" er slettet eller slået fra på kundekortet, er stoppet. Gamle tjenester
    "Ekstra ønsker" uden pakke knyttes til en pakke, når prisen og kontoen er entydige. Giver det, der ikke kunne afgøres."""
    pk = packages()
    unclear = []
    with _lock:
        con = D["db"]()
        try:
            with con:
                for r in [dict(x) for x in con.execute("SELECT * FROM s_pkg").fetchall()]:
                    svc = con.execute("SELECT active FROM k_services WHERE id=?", (r["service_id"],)).fetchone() if r["service_id"] else None
                    stopping = r["pending"] == "" and r["pending_billed"]
                    if (not svc or not svc["active"]) and not stopping:
                        con.execute("DELETE FROM s_pkg WHERE plex_user_id=?", (r["plex_user_id"],))
                        who = (con.execute("SELECT friendly_name FROM k_plex WHERE user_id=?", (r["plex_user_id"],)).fetchone() or {"friendly_name": "Plex-konto"})["friendly_name"]
                        _log(f"{who}: pakken er fjernet, fordi tjenesten Ekstra ønsker er slettet eller slået fra på kundekortet",
                             r["customer_id"], r["plex_user_id"], con)
                linked = {x["service_id"] for x in con.execute("SELECT service_id FROM s_pkg").fetchall()}
                taken = {x["plex_user_id"] for x in con.execute("SELECT plex_user_id FROM s_pkg").fetchall()}
                for s in [dict(x) for x in con.execute("SELECT s.*, c.name cname, c.kind FROM k_services s JOIN k_customers c ON c.id=s.customer_id"
                                                         " WHERE s.service='seerr' AND s.active=1").fetchall()]:
                    if s["id"] in linked or s["kind"] != "kunde":
                        continue
                    cand = [p for p in pk.values() if abs(float(p["price"]) - float(s["price"] or 0)) < 0.01]
                    if len(cand) != 1:
                        cand = [p for p in pk.values() if p["name"].lower() in (s["label"] or "").lower()]
                    free = [a for a in _accounts(s["customer_id"]) if a["plex_user_id"] not in taken]
                    if len(cand) == 1 and len(free) == 1:
                        con.execute("INSERT INTO s_pkg (plex_user_id, customer_id, package, service_id, started, updated) VALUES (?,?,?,?,?,?)",
                                    (free[0]["plex_user_id"], s["customer_id"], cand[0]["key"], s["id"], iso(now()), iso(now())))
                        taken.add(free[0]["plex_user_id"])
                        _log(f"{free[0]['name']}: tjenesten Ekstra ønsker ({kunder.num(s['price'])} kr./md.) er genkendt som pakken {cand[0]['name']}",
                             s["customer_id"], free[0]["plex_user_id"], con)
                    else:
                        why = "prisen passer ikke til en pakke" if len(cand) != 1 else ("kunden har ingen Plex-konto koblet" if not free else "kunden har flere Plex-konti")
                        unclear.append({"customer_id": s["customer_id"], "name": s["cname"], "price": kunder.num(s["price"]), "why": why})
        finally:
            con.close()
    return unclear


def _want(c, pid, pkg_rows, buyers, seerr_id, pk, usage):
    """Hvad kontoen skal kunne i Seerr: (rettigheder, filmgrænse, sæsongrænse, grundlag, rør auto-anmod ikke)."""
    if not c:
        return 0, None, None, "ingen kunde i Fangarr", False
    if c["status"] != "aktiv":
        return 0, None, None, f"kunden står som {'Pause' if c['status'] == 'pause' else 'Stoppet'}", False
    if c["kind"] == "egen":
        return REQ, UNLIMITED, UNLIMITED, "familie", True
    row = pkg_rows.get(pid)
    pkg = pk.get(row["package"]) if row else None
    if pid in buyers or pkg:
        usage[pid] = _attribute(seerr_id, pid, pkg)
    cr = credits(pid) if pid in buyers else {"film": {"unused": 0, "window": 0}, "tv": {"unused": 0, "window": 0}}
    film = (int(pkg["film"]) if pkg else 0) + cr["film"]["unused"] + cr["film"]["window"]
    tv = (int(pkg["tv"]) if pkg else 0) + cr["tv"]["unused"] + cr["tv"]["window"]
    bits = REQ if film and tv else REQ_MOVIE if film else REQ_TV if tv else 0
    why = []
    if pkg:
        why.append(f"pakke {pkg['name']}")
    if cr["film"]["unused"] or cr["tv"]["unused"]:
        why.append(f"købte ønsker ({_units(cr['film']['unused'], cr['tv']['unused'])} tilbage)")
    return bits, (film or None), (tv or None), " + ".join(why) or "ingen pakke eller købte ønsker", False


def _quota_of(u, cache):
    if u["id"] not in cache:
        cache[u["id"]] = _sx("GET", f"/user/{u['id']}/settings/main") or {}
    return cache[u["id"]]


def _sync():
    s = settings()
    mode = s["mode"] if s["mode"] in MODES else "prove"
    st = {"at": iso(now()), "mode": mode, "plan": [], "applied": 0, "errors": [], "braked": False, "can": [], "usage": {},
          "problems": [], "unclear": [], "error": "", "in_seerr": []}
    if mode == "fra":
        D["kv_set"]("oensker_state", st)
        return st
    _apply_due_pending()
    st["unclear"] = _check_services()
    try:
        users = _seerr_users()
        if len(users) < 5:
            raise RuntimeError(f"Seerr gav kun {len(users)} brugere – Fangarr ændrer intet for en sikkerheds skyld")
    except Exception as e:     # Seerr svarer ikke: besked efter 3 gange i træk, og "i orden igen"
        st["error"] = str(e)[:300]
        f = D["kv_get"]("oensker_fail", {}) or {}
        f["n"] = int(f.get("n") or 0) + 1
        if f["n"] >= 3 and not f.get("sent"):
            f["sent"] = True
            D["telegram"](f"🚨 Fangarr – Seerr-ønsker: Seerr svarer ikke, så Fangarr kan ikke styre, hvem der må ønske.\n\n{st['error'][:200]}")
        D["kv_set"]("oensker_fail", f)
        D["kv_set"]("oensker_state", st)
        return st
    f = D["kv_get"]("oensker_fail", {}) or {}
    if f.get("sent"):
        D["telegram"]("✅ Fangarr – Seerr-ønsker: Seerr svarer igen.")
    if f:
        D["kv_set"]("oensker_fail", {})
    untouch = _untouchable(s)
    pk = packages()
    cust = {c["id"]: c for c in rows("SELECT * FROM k_customers")}
    acct = {x["plex_user_id"]: x["customer_id"] for x in
            rows("SELECT customer_id, plex_user_id FROM k_services WHERE service='plex' AND active=1 AND plex_user_id IS NOT NULL")}
    pkg_rows = {r["plex_user_id"]: r for r in rows("SELECT * FROM s_pkg")}
    buyers = {r["plex_user_id"] for r in rows("SELECT DISTINCT plex_user_id FROM s_buy")}
    by_plex = {}
    for u in users:
        try:
            by_plex[int(u.get("plexId"))] = u
        except (TypeError, ValueError):
            pass
    st["in_seerr"] = sorted(by_plex)
    names = {a: (one("SELECT friendly_name FROM k_plex WHERE user_id=?", (a,)) or {}).get("friendly_name") for a in set(pkg_rows) | buyers}
    for pid in sorted(set(pkg_rows) | buyers):
        if pid not in by_plex:
            st["problems"].append(f"{names.get(pid) or pid} har en pakke eller købte ønsker, men findes ikke i Seerr (har aldrig logget ind i Seerr?)")
        if pid in pkg_rows and acct.get(pid) != pkg_rows[pid]["customer_id"]:
            st["problems"].append(f"{names.get(pid) or pid}: Plex-kontoen hører ikke længere til den kunde, der har pakken")
    cache, changes = {}, []
    for u in users:
        perms = int(u.get("permissions") or 0)
        name = _uname(u)
        if u["id"] in untouch or perms & (ADMIN | MANAGE_USERS):
            if perms & (REQ_ANY | ADMIN):
                st["can"].append({"seerr_id": u["id"], "name": name, "basis": "admin" if perms & ADMIN else "rør ikke", "limits": "røres ikke"})
            continue
        try:
            pid = int(u.get("plexId"))
        except (TypeError, ValueError):
            pid = None
        c = cust.get(acct.get(pid)) if pid else None
        try:
            bits, movie, tv, why, keep_auto = _want(c, pid, pkg_rows, buyers, u["id"], pk, st["usage"])
        except Exception as e:
            st["errors"].append(f"{name}: kunne ikke læse ønskerne ({str(e)[:120]})")
            continue
        new = (perms & ~REQ_ANY) | bits
        if not keep_auto:
            new &= ~AUTO
        qchange, cur_q = False, None
        if bits:
            try:
                cur_q = _quota_of(u, cache)
            except Exception as e:
                st["errors"].append(f"{name}: kunne ikke læse grænserne ({str(e)[:120]})")
                continue
            want_m, want_t = (movie if bits & (REQ | REQ_MOVIE) else None), (tv if bits & (REQ | REQ_TV) else None)
            qchange = cur_q.get("movieQuotaLimit") != want_m or cur_q.get("tvQuotaLimit") != want_t or \
                (want_m not in (None, UNLIMITED) and cur_q.get("movieQuotaDays") != WINDOW_DAYS) or \
                (want_t not in (None, UNLIMITED) and cur_q.get("tvQuotaDays") != WINDOW_DAYS)
            st["can"].append({"seerr_id": u["id"], "name": name, "plex_user_id": pid, "customer_id": c["id"] if c else None,
                              "basis": why, "limits": _desc(bits, want_m, want_t), "usage": st["usage"].get(pid)})
        if new != perms or qchange:
            was = _desc(perms, (cur_q or {}).get("movieQuotaLimit"), (cur_q or {}).get("tvQuotaLimit")) if perms & REQ_ANY else "kan ikke ønske"
            changes.append({"seerr_id": u["id"], "name": name, "plex_user_id": pid, "customer_id": c["id"] if c else None, "basis": why,
                            "from": was, "to": _desc(bits, movie, tv), "perms": new, "old_perms": perms, "remove": bool(perms & REQ_ANY) and not bits,
                            "quota": [movie if bits & (REQ | REQ_MOVIE) else None, tv if bits & (REQ | REQ_TV) else None] if qchange else None,
                            "auto_off": bool(perms & AUTO) and not (new & AUTO)})
    st["plan"] = [{k: v for k, v in x.items() if k not in ("perms", "old_perms", "quota")} for x in changes]
    removals = [x for x in changes if x["remove"]]
    brake = int(s.get("brake") or 5)
    bk = D["kv_get"]("oensker_brake", {}) or {}
    if mode == "til" and len(removals) > brake:
        st["braked"] = True
        changes = [x for x in changes if not x["remove"]]
        if not bk.get("sent"):
            D["telegram"](f"🚨 Fangarr – Seerr-ønsker: {len(removals)} brugere ville miste retten til at ønske på én gang (grænsen er {brake}). "
                          "Fangarr har ikke fjernet nogen. Tjek listen i Fangarr › Seerr-ønsker.")
            D["kv_set"]("oensker_brake", {"sent": True})
    elif bk.get("sent"):
        D["telegram"]("✅ Fangarr – Seerr-ønsker: bremsen er slået fra igen – ændringerne er normale.")
        D["kv_set"]("oensker_brake", {})
    if mode == "til":
        for x in changes:
            try:
                if x["perms"] != x["old_perms"]:
                    r = _sx("POST", f"/user/{x['seerr_id']}/settings/permissions", json={"permissions": x["perms"]}) or {}
                    if int(r.get("permissions", -1)) != x["perms"]:
                        raise RuntimeError("Seerr gemte ikke rettighederne")
                if x["quota"] is not None:
                    body = dict(_sx("GET", f"/user/{x['seerr_id']}/settings/main") or {})
                    if "username" not in body:
                        raise RuntimeError("Seerr gav ikke brugerens indstillinger")
                    m, t = x["quota"]
                    body.update({"movieQuotaLimit": m, "movieQuotaDays": WINDOW_DAYS if m is not None else None,
                                 "tvQuotaLimit": t, "tvQuotaDays": WINDOW_DAYS if t is not None else None})
                    _sx("POST", f"/user/{x['seerr_id']}/settings/main", json=body)
                st["applied"] += 1
                _log(f"Seerr: {x['name']} – {x['from']} → {x['to']}" + (" (Auto-anmod slået fra)" if x["auto_off"] else "") + f" · {x['basis']}",
                     x["customer_id"], x["plex_user_id"])
            except Exception as e:
                st["errors"].append(f"{x['name']}: kunne ikke ændres i Seerr ({str(e)[:150]})")
        er = D["kv_get"]("oensker_err", {}) or {}
        if st["errors"] and not er.get("sent"):
            D["telegram"]("🚨 Fangarr – Seerr-ønsker: kunne ikke ændre alt i Seerr.\n\n" + "\n".join("• " + e for e in st["errors"][:10]))
            D["kv_set"]("oensker_err", {"sent": True})
        elif not st["errors"] and er.get("sent"):
            D["telegram"]("✅ Fangarr – Seerr-ønsker: ændringerne i Seerr virker igen.")
            D["kv_set"]("oensker_err", {})
    st["can"].sort(key=lambda x: kunder.norm(x["name"]))
    st["usage"] = {str(k): v for k, v in st["usage"].items()}
    D["kv_set"]("oensker_state", st)
    return st


def sync(wait=False):
    """Gennemgå Seerr nu. Kører én ad gangen. wait=True (knappen og indstillinger): vent på en gennemgang, der allerede
    kører, og lav så en ny, så resultatet passer med de nyeste ændringer. Ellers gives den seneste status."""
    if not enabled():
        return {"error": "Seerr er ikke sat op (SEERR_URL og SEERR_APIKEY i fangarr.env)"}
    if not _sync_lock.acquire(timeout=120) if wait else not _sync_lock.acquire(blocking=False):
        return D["kv_get"]("oensker_state", {}) or {}
    try:
        _last["sync"] = time.time()
        return _sync()
    finally:
        _sync_lock.release()


def kick():
    """Efter en ændring på kundekortet: ret Seerr med det samme (i baggrunden – venter, hvis en gennemgang kører)."""
    if enabled():
        threading.Thread(target=_safe_sync, args=(True,), daemon=True).start()


def _safe_sync(wait=False):
    try:
        sync(wait=wait)
    except Exception as e:   # må aldrig vælte Fangarr
        D["log"].warning("Seerr-ønsker fejlede: %s", e)


def tick():
    """Kaldes hvert minut af Fangarrs baggrundsjob – gennemgår Seerr hvert 5. minut."""
    if enabled() and time.time() - _last["sync"] >= 300:
        _safe_sync()


# ---------------------------------------------------------------- visning

def customer_out(cid):
    c = _customer(cid)
    pk = packages()
    nxt = next_payment(c)
    st = D["kv_get"]("oensker_state", {}) or {}
    can = {x.get("plex_user_id"): x for x in st.get("can") or [] if x.get("plex_user_id")}
    in_seerr = set(st.get("in_seerr") or []) if st.get("at") and not st.get("error") else None
    accts = []
    for a in _accounts(cid):
        pid = a["plex_user_id"]
        row = one("SELECT * FROM s_pkg WHERE plex_user_id=?", (pid,))
        cr = credits(pid)
        buys = []
        for b in rows("SELECT * FROM s_buy WHERE plex_user_id=? ORDER BY id DESC LIMIT 20", (pid,)):
            buys.append({"id": b["id"], "film": b["film"], "tv": b["tv"], "amount": kunder.num(b["amount"]), "created": b["created"]})
        p = pk.get(row["package"]) if row else None
        pend = None
        if row and row["pending"] is not None:
            pend = {"to": row["pending"], "name": pk[row["pending"]]["name"] if row["pending"] in pk else "", "date": row["pending_date"]}
        accts.append({**a, "package": ({"key": p["key"], "name": p["name"], "price": p["price"], "film": p["film"], "tv": p["tv"]} if p else None),
                      "since": row["started"] if row else None, "pending": pend, "credits": cr, "buys": buys,
                      "seerr": can.get(pid), "in_seerr": (pid in in_seerr) if in_seerr is not None else None,
                      "usage": (st.get("usage") or {}).get(str(pid))})
    return {"customer_id": cid, "kind": c["kind"], "status": c["status"], "accounts": accts, "enabled": enabled(),
            "mode": settings()["mode"], "packages": list(pk.values()), "price_film": settings()["price_film"], "price_tv": settings()["price_tv"],
            "next": ({"date": nxt["date"].isoformat(), "text": _day(nxt["date"]), "has_charge": bool(nxt["charge_id"])} if nxt else None),
            "synced": st.get("at")}


def overview():
    pk = packages()
    cust = {c["id"]: c for c in rows("SELECT * FROM k_customers")}
    out = []
    pids = {r["plex_user_id"] for r in rows("SELECT plex_user_id FROM s_pkg")} | {r["plex_user_id"] for r in rows("SELECT DISTINCT plex_user_id FROM s_buy")}
    plex = {r["user_id"]: r for r in rows("SELECT * FROM k_plex")}
    owner = {x["plex_user_id"]: x["customer_id"] for x in rows("SELECT customer_id, plex_user_id FROM k_services WHERE service='plex' AND plex_user_id IS NOT NULL")}
    for pid in pids:
        row = one("SELECT * FROM s_pkg WHERE plex_user_id=?", (pid,))
        cid = row["customer_id"] if row else owner.get(pid) or (one("SELECT customer_id FROM s_buy WHERE plex_user_id=? LIMIT 1", (pid,)) or {}).get("customer_id")
        c = cust.get(cid) or {}
        cr = credits(pid)
        p = pk.get(row["package"]) if row else None
        out.append({"customer_id": cid, "customer": c.get("name") or "?", "account": (plex.get(pid) or {}).get("friendly_name") or str(pid),
                    "plex_user_id": pid, "package": p["name"] if p else "", "price": p["price"] if p else 0,
                    "pending": ({"name": pk.get(row["pending"], {}).get("name", "") if row["pending"] else "", "date": row["pending_date"]}
                                if row and row["pending"] is not None else None),
                    "film_left": cr["film"]["unused"], "tv_left": cr["tv"]["unused"]})
    out.sort(key=lambda x: kunder.norm(x["customer"]))
    fam = []
    for c in cust.values():
        if c["kind"] == "egen" and c["status"] == "aktiv":
            fam.append({"customer_id": c["id"], "name": c["name"], "accounts": [a["name"] for a in _accounts(c["id"])]})
    fam.sort(key=lambda x: kunder.norm(x["name"]))
    return out, fam


def brief():
    """Til forsiden: problemer og ventende ændringer."""
    if not enabled():
        return {"enabled": False}
    st = D["kv_get"]("oensker_state", {}) or {}
    s = settings()
    return {"enabled": True, "mode": s["mode"], "plan": len(st.get("plan") or []) if s["mode"] == "prove" else 0,
            "problems": len(st.get("problems") or []) + len(st.get("unclear") or []) + len(st.get("errors") or [])
            + (1 if st.get("braked") else 0) + (1 if st.get("error") else 0), "braked": bool(st.get("braked")), "error": st.get("error") or ""}


# ---------------------------------------------------------------- web

@router.get("/state")
def state():
    out, fam = overview()
    extra = {}
    for k in ("shop_info", "sections"):   # Køb i guiden (1.25.0) – sat af main.py
        try:
            extra[k.replace("_info", "")] = D[k]() if D.get(k) else None
        except Exception:
            extra[k.replace("_info", "")] = None
    return {"enabled": enabled(), "settings": settings(), "state": D["kv_get"]("oensker_state", {}) or {}, "accounts": out, "family": fam,
            "log": rows("SELECT * FROM s_log ORDER BY id DESC LIMIT 80"), **extra}


@router.get("/customer/{cid}")
def customer_get(cid: int):
    return customer_out(cid)


@router.post("/quote")
async def quote(req: Request):
    b = await req.json()
    if b.get("what") == "buy":
        return quote_buy(int(b.get("customer_id") or 0), b.get("plex_user_id"), b.get("film"), b.get("tv"))
    return quote_package(int(b.get("customer_id") or 0), b.get("plex_user_id"), b.get("package") or "")


@router.post("/package")
async def package_post(req: Request):
    b = await req.json()
    cid = int(b.get("customer_id") or 0)
    msg = set_package(cid, b.get("plex_user_id"), b.get("package") or "")
    return {"message": msg, "customer": customer_out(cid)}


@router.post("/buy")
async def buy_post(req: Request):
    b = await req.json()
    cid = int(b.get("customer_id") or 0)
    msg = buy(cid, b.get("plex_user_id"), b.get("film"), b.get("tv"))
    return {"message": msg, "customer": customer_out(cid)}


@router.delete("/buy/{bid}")
def buy_delete(bid: int):
    b = one("SELECT customer_id FROM s_buy WHERE id=?", (bid,))
    msg = undo_buy(bid)
    return {"message": msg, "customer": customer_out(b["customer_id"]) if b else None}


@router.post("/sync")
def sync_post():
    if not enabled():
        raise HTTPException(400, "Seerr er ikke sat op (SEERR_URL og SEERR_APIKEY i fangarr.env)")
    sync(wait=True)
    return state()


@router.put("/settings")
async def settings_put(req: Request):
    b = await req.json()
    s = settings()
    if "mode" in b:
        if b["mode"] not in MODES:
            raise HTTPException(400, "ugyldig tilstand")
        s["mode"] = b["mode"]
    if "untouchable" in b:
        v = str(b["untouchable"] or "").replace(";", ",")
        bad = [x.strip() for x in v.split(",") if x.strip() and not x.strip().isdigit()]
        if bad:
            raise HTTPException(400, "Rør ikke: skriv Seerr-bruger-id'er (tal) adskilt med komma, fx 30,76")
        s["untouchable"] = ",".join(x.strip() for x in v.split(",") if x.strip())
    for k in ("price_film", "price_tv"):
        if k in b:
            v = kunder.money(b[k])
            if v <= 0:
                raise HTTPException(400, "prisen for enkeltkøb skal være over 0")
            s[k] = kunder.num(v)
    if "shop" in b:
        s["shop"] = bool(b["shop"])
    if "shop_section" in b:
        v = str(b["shop_section"] or "").strip()
        if v and not re.fullmatch(r"[\w\-:.]{1,80}", v):
            raise HTTPException(400, "ugyldigt afsnit")
        s["shop_section"] = v
    if "brake" in b:
        try:
            s["brake"] = max(1, int(b["brake"]))
        except (TypeError, ValueError):
            raise HTTPException(400, "bremsen skal være et helt tal") from None
    if "packages" in b:
        new = []
        for p in b["packages"] or []:
            key = str(p.get("key") or "").strip()
            if key not in {x["key"] for x in PACKAGES}:
                raise HTTPException(400, "ukendt pakke")
            try:
                film, tv, price = int(p.get("film") or 0), int(p.get("tv") or 0), kunder.money(p.get("price"))
            except (TypeError, ValueError):
                raise HTTPException(400, "film og sæsoner skal være hele tal") from None
            if film < 0 or tv < 0 or (not film and not tv) or price <= 0:
                raise HTTPException(400, f"{p.get('name') or key}: skal have en pris og mindst én film eller sæson")
            new.append({"key": key, "name": next(x["name"] for x in PACKAGES if x["key"] == key), "price": kunder.num(price), "film": film, "tv": tv})
        if new:
            s["packages"] = new
    D["kv_set"]("oensker_settings", s)
    kick()
    return settings()
