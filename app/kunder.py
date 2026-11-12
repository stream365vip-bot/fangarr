"""Kunder og betalinger (Fangarr 1.16.0).

Holder styr på kunder, deres tjenester, opkrævninger, IPTV-linjer og logins.
Plex-brugere hentes fra Tautulli (hver nat og med knappen "Synk fra Tautulli").

Vigtigt:
- Kodeord og IPTV-koder ligger kun i databasen (/config/fangarr.db). De sendes aldrig med i lister,
  i loggen, i Telegram-beskeder eller i Fangarrs eksport – kun når du trykker "Vis".
- Fangarr sender ingen beskeder til kunderne og spærrer ingen. Du får kun besked på Stream365 Drift.
"""
import csv
import datetime
import io
import json
import re
import threading
import unicodedata

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

router = APIRouter(prefix="/api/kunder")
D = {}   # udfyldes af main.py: db, telegram, tautulli, tautulli_enabled, now, kv_get, kv_set, log

SERVICES = [("plex", "Plex"), ("iptv", "IPTV"), ("spotify", "Spotify"), ("youtube", "YouTube"), ("mofibo", "Mofibo"),
            ("hbo", "HBO Max"), ("seerr", "Ekstra ønsker"), ("andet", "Andet")]
SERVICE_DA = dict(SERVICES)
FREQ = {"maaned": 1, "kvartal": 3, "halvaar": 6, "aar": 12}
FREQ_DA = {"maaned": "Månedlig", "kvartal": "Kvartal", "halvaar": "Halvårlig", "aar": "Årlig"}
STATUSES = ("aktiv", "pause", "stoppet")
KINDS = ("kunde", "egen")
MONTHS_DA = ["januar", "februar", "marts", "april", "maj", "juni", "juli", "august", "september", "oktober", "november", "december"]

DEFAULTS = {
    "remind_days": 7,          # dage efter "Anmodet", før du får besked om manglende betaling
    "remind_repeat_days": 7,   # derefter én samlet påmindelse så ofte
    "inactive_days": 60,       # mærket "ikke set længe" på kunden
    "plex_price": 120,         # pris pr. måned for en ny Plex-konto fra Tautulli
    "message_hour": 8,         # klokkeslæt for beskeder på Stream365 Drift
    "sync_hour": 3,            # natlig synk fra Tautulli
    "fixed_costs": "",         # faste udgifter pr. måned, én pr. linje: "Hetzner: 2813"
    "template": ("Hej {fornavn}! 👋\n\nHermed opkrævning for dine tjenester ({tjenester}):\n"
                 "💰 Beløb: {beløb} kr. ({frekvens} • Cyklus: {cyklus})\n💳 Betales via: {metode}\n\n"
                 "Sig endelig til hvis der er noget. Rigtig god fornøjelse! 🍿"),
}
_lock = threading.Lock()


def setup(**deps):
    D.update(deps)


def now():
    return D["now"]()


def iso(dt):
    return dt.isoformat(timespec="seconds")


def period_of(dt):
    return f"{dt.year:04d}-{dt.month:02d}"


def cur_period():
    return period_of(now())


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "").lower().replace("æ", "ae").replace("ø", "oe").replace("å", "aa"))
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip()


def money(v):
    """'1.314 kr.' / '49,50' / 120 -> tal. Tomt -> 0."""
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v or ""))
    if not s or s in "-.,":
        return 0.0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def num(v):
    v = round(float(v or 0), 2)
    return int(v) if v == int(v) else v


# ---------------------------------------------------------------- database

def init():
    con = D["db"]()
    with con:
        con.execute("CREATE TABLE IF NOT EXISTS k_customers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, status TEXT DEFAULT 'aktiv',"
                    " kind TEXT DEFAULT 'kunde', method TEXT DEFAULT '', freq TEXT, cycle INTEGER, due_day INTEGER, phone TEXT DEFAULT '',"
                    " email TEXT DEFAULT '', contact TEXT DEFAULT '', notes TEXT DEFAULT '', created TEXT, updated TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS k_services (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, service TEXT,"
                    " label TEXT DEFAULT '', price REAL DEFAULT 0, plex_user_id INTEGER, username TEXT DEFAULT '', email TEXT DEFAULT '',"
                    " password TEXT DEFAULT '', note TEXT DEFAULT '', active INTEGER DEFAULT 1)")
        con.execute("CREATE TABLE IF NOT EXISTS k_plex (user_id INTEGER PRIMARY KEY, username TEXT, friendly_name TEXT, email TEXT,"
                    " last_seen INTEGER, active INTEGER DEFAULT 1, synced TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS k_iptv (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, label TEXT DEFAULT '',"
                    " username TEXT DEFAULT '', password TEXT DEFAULT '', expires TEXT, cost REAL DEFAULT 0, tivimate TEXT DEFAULT '',"
                    " note TEXT DEFAULT '', renew INTEGER DEFAULT 1)")
        con.execute("CREATE TABLE IF NOT EXISTS k_adjust (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, amount REAL,"
                    " text TEXT DEFAULT '', remaining INTEGER DEFAULT 1, created TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS k_charges (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, period TEXT,"
                    " amount REAL, base REAL, detail TEXT DEFAULT '{}', requested_at TEXT, paid_at TEXT, skipped INTEGER DEFAULT 0,"
                    " method TEXT DEFAULT '', note TEXT DEFAULT '', created TEXT, UNIQUE(customer_id, period))")
        con.execute("CREATE TABLE IF NOT EXISTS k_logins (id INTEGER PRIMARY KEY AUTOINCREMENT, service TEXT DEFAULT '', label TEXT DEFAULT '',"
                    " username TEXT DEFAULT '', password TEXT DEFAULT '', note TEXT DEFAULT '')")
    con.close()


def rows(sql, args=()):
    con = D["db"]()
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def one(sql, args=()):
    r = rows(sql, args)
    return r[0] if r else None


def run(sql, args=()):
    con = D["db"]()
    try:
        with con:
            cur = con.execute(sql, args)
            return cur.lastrowid
    finally:
        con.close()


def settings():
    s = dict(DEFAULTS)
    s.update(D["kv_get"]("kunder_settings", {}) or {})
    return s


# ---------------------------------------------------------------- cyklus og beløb

def due_months(freq, cycle):
    n = FREQ.get(freq)
    if not n:
        return []
    if n == 1:
        return list(range(1, 13))
    start = cycle if cycle and 1 <= cycle <= 12 else 1
    return sorted({((start - 1 + i * n) % 12) + 1 for i in range(12 // n)})


def cycle_text(freq, cycle):
    if freq == "maaned":
        return "Hver måned"
    m = due_months(freq, cycle)
    return "/".join(str(x) for x in m) if m else "mangler"


def service_lines(services):
    return [{"service": s["service"], "label": s["label"] or "", "price": num(s["price"])} for s in services if s["active"]]


def monthly(services):
    return sum(float(s["price"] or 0) for s in services if s["active"])


def service_names(lines):
    out = []
    for l in lines:
        n = SERVICE_DA.get(l["service"], l["service"])
        if n not in out:
            out.append(n)
    return ", ".join(out)


def message_for(c, amount, lines):
    s = settings()
    vals = {"fornavn": (c["name"] or "").split(" ")[0], "navn": c["name"] or "", "tjenester": service_names(lines) or "–",
            "beløb": f"{num(amount):,}".replace(",", "."), "frekvens": FREQ_DA.get(c["freq"], "–"),
            "cyklus": cycle_text(c["freq"], c["cycle"]), "metode": c["method"] or "–"}
    txt = s["template"]
    for k, v in vals.items():
        txt = txt.replace("{" + k + "}", str(v))
    return txt


def _create_charge(con, c, services, period):
    """Opret én opkrævning. Fradrag/tillæg med 'remaining' > 0 regnes med og tælles én ned."""
    lines = service_lines(services)
    n = FREQ.get(c["freq"], 0)
    base = monthly(services) * n
    adj = []
    for a in con.execute("SELECT * FROM k_adjust WHERE customer_id=? AND remaining>0 ORDER BY id", (c["id"],)).fetchall():
        adj.append({"text": a["text"], "amount": num(a["amount"])})
        con.execute("UPDATE k_adjust SET remaining=remaining-1 WHERE id=?", (a["id"],))
    if not base and not adj:
        return False
    amount = max(0.0, base + sum(a["amount"] for a in adj))
    con.execute("INSERT OR IGNORE INTO k_charges (customer_id, period, amount, base, detail, method, created) VALUES (?,?,?,?,?,?,?)",
                (c["id"], period, amount, base, json.dumps({"lines": lines, "months": n, "adjust": adj}, ensure_ascii=False),
                 c["method"] or "", iso(now())))
    return True


def ensure_charges(period):
    """Opret månedens opkrævninger for aktive kunder, der skal betale i den måned. Rører aldrig eksisterende."""
    month = int(period[5:7])
    made = 0
    with _lock:
        con = D["db"]()
        try:
            with con:
                have = {r[0] for r in con.execute("SELECT customer_id FROM k_charges WHERE period=?", (period,)).fetchall()}
                for c in con.execute("SELECT * FROM k_customers WHERE status='aktiv' AND kind='kunde' AND freq IS NOT NULL").fetchall():
                    if c["id"] in have or month not in due_months(c["freq"], c["cycle"]):
                        continue
                    sv = [dict(r) for r in con.execute("SELECT * FROM k_services WHERE customer_id=?", (c["id"],)).fetchall()]
                    if _create_charge(con, dict(c), sv, period):
                        made += 1
        finally:
            con.close()
    return made


def charge_status(ch, remind_days):
    if ch["skipped"]:
        return "sprunget over", False
    if ch["paid_at"]:
        return "betalt", False
    if ch["requested_at"]:
        late = ch["requested_at"] <= iso(now() - datetime.timedelta(days=remind_days))
        return "anmodet", late
    return "ny", False


def overdue_list():
    rd = int(settings()["remind_days"])
    limit = iso(now() - datetime.timedelta(days=rd))
    return rows("SELECT ch.id, ch.amount, ch.period, ch.requested_at, c.name FROM k_charges ch JOIN k_customers c ON c.id=ch.customer_id"
                " WHERE ch.paid_at IS NULL AND ch.skipped=0 AND ch.requested_at IS NOT NULL AND ch.requested_at<=? ORDER BY ch.requested_at", (limit,))


# ---------------------------------------------------------------- kunder

def _plex_map():
    return {r["user_id"]: r for r in rows("SELECT * FROM k_plex")}


def _flags(c, services, plex, s, synced):
    f = []
    if c["kind"] != "kunde" or c["status"] != "aktiv":
        return f
    if not c["freq"]:
        f.append("cyklus")
    if not c["method"]:
        f.append("metode")
    if not monthly(services):
        f.append("pris")
    px = [x for x in services if x["service"] == "plex" and x["active"]]
    if any(x["plex_user_id"] and not (plex.get(x["plex_user_id"]) or {}).get("active") for x in px):
        f.append("plexvaek")
    if synced and any(not x["plex_user_id"] for x in px):
        f.append("ulinket")
    seen = [(plex.get(x["plex_user_id"]) or {}).get("last_seen") or 0 for x in px if x["plex_user_id"]]
    if seen and max(seen) and max(seen) < now().timestamp() - int(s["inactive_days"]) * 86400:
        f.append("inaktiv")
    return f


def _service_out(x, plex):
    p = plex.get(x["plex_user_id"]) if x["plex_user_id"] else None
    return {"id": x["id"], "customer_id": x["customer_id"], "service": x["service"], "label": x["label"], "price": num(x["price"]),
            "plex_user_id": x["plex_user_id"], "username": x["username"], "email": x["email"], "note": x["note"],
            "active": bool(x["active"]), "has_password": bool(x["password"]),
            "plex": ({"username": p["username"], "friendly_name": p["friendly_name"], "last_seen": p["last_seen"],
                      "active": bool(p["active"])} if p else None)}


def customers_out():
    s = settings()
    plex = _plex_map()
    synced = bool(D["kv_get"]("kunder_sync"))
    by = {}
    for x in rows("SELECT * FROM k_services ORDER BY id"):
        by.setdefault(x["customer_id"], []).append(x)
    lines = {}
    for l in rows("SELECT customer_id, COUNT(*) n FROM k_iptv GROUP BY customer_id"):
        lines[l["customer_id"]] = l["n"]
    out = []
    for c in rows("SELECT * FROM k_customers ORDER BY name COLLATE NOCASE"):
        sv = by.get(c["id"], [])
        m = monthly(sv)
        seen = [(plex.get(x["plex_user_id"]) or {}).get("last_seen") or 0 for x in sv if x["plex_user_id"]]
        out.append({**c, "monthly": num(m), "per_charge": num(m * FREQ.get(c["freq"], 0)), "cycle_text": cycle_text(c["freq"], c["cycle"]),
                    "freq_text": FREQ_DA.get(c["freq"], ""), "services": [_service_out(x, plex) for x in sv],
                    "iptv_lines": lines.get(c["id"], 0), "last_seen": max(seen) if seen else None,
                    "flags": _flags(c, sv, plex, s, synced)})
    return out


def clean_customer(b, old=None):
    o = dict(old or {})
    name = str(b.get("name", o.get("name", ""))).strip()
    if not name:
        raise HTTPException(400, "kunden skal have et navn")
    status = b.get("status", o.get("status", "aktiv"))
    kind = b.get("kind", o.get("kind", "kunde"))
    freq = b.get("freq", o.get("freq")) or None
    if status not in STATUSES or kind not in KINDS or (freq and freq not in FREQ):
        raise HTTPException(400, "ugyldig status, type eller frekvens")
    def _int(k, lo, hi):
        v = b.get(k, o.get(k))
        try:
            v = int(v)
        except (TypeError, ValueError):
            return None
        return v if lo <= v <= hi else None
    return {"name": name, "status": status, "kind": kind, "freq": freq, "cycle": _int("cycle", 1, 12), "due_day": _int("due_day", 1, 31),
            "method": str(b.get("method", o.get("method", "")) or "").strip(), "phone": str(b.get("phone", o.get("phone", "")) or "").strip(),
            "email": str(b.get("email", o.get("email", "")) or "").strip(), "contact": str(b.get("contact", o.get("contact", "")) or "").strip(),
            "notes": str(b.get("notes", o.get("notes", "")) or "").strip()}


def add_customer(d):
    return run("INSERT INTO k_customers (name, status, kind, method, freq, cycle, due_day, phone, email, contact, notes, created, updated)"
               " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (d["name"], d["status"], d["kind"], d["method"], d["freq"], d["cycle"], d["due_day"], d["phone"], d["email"], d["contact"],
                d["notes"], iso(now()), iso(now())))


def customer_detail(cid):
    c = one("SELECT * FROM k_customers WHERE id=?", (cid,))
    if not c:
        raise HTTPException(404, "kunden findes ikke")
    plex = _plex_map()
    s = settings()
    sv = rows("SELECT * FROM k_services WHERE customer_id=? ORDER BY id", (cid,))
    m = monthly(sv)
    rd = int(s["remind_days"])
    ch = []
    for r in rows("SELECT * FROM k_charges WHERE customer_id=? ORDER BY period DESC LIMIT 40", (cid,)):
        st, late = charge_status(r, rd)
        ch.append({"id": r["id"], "period": r["period"], "amount": num(r["amount"]), "status": st, "late": late,
                   "requested_at": r["requested_at"], "paid_at": r["paid_at"], "note": r["note"]})
    return {**c, "monthly": num(m), "per_charge": num(m * FREQ.get(c["freq"], 0)), "cycle_text": cycle_text(c["freq"], c["cycle"]),
            "freq_text": FREQ_DA.get(c["freq"], ""), "services": [_service_out(x, plex) for x in sv],
            "flags": _flags(c, sv, plex, s, bool(D["kv_get"]("kunder_sync"))),
            "iptv": [_iptv_out(l) for l in rows("SELECT * FROM k_iptv WHERE customer_id=? ORDER BY expires", (cid,))],
            "adjust": [{**a, "amount": num(a["amount"])} for a in rows("SELECT * FROM k_adjust WHERE customer_id=? ORDER BY id DESC", (cid,))],
            "charges": ch}


@router.get("/state")
def state():
    return {"settings": settings(), "services": SERVICES, "freq": FREQ_DA, "period": cur_period(),
            "tautulli": D["tautulli_enabled"](), "sync": D["kv_get"]("kunder_sync"), "doubts": D["kv_get"]("kunder_doubts", []),
            "plex_free": [p for p in rows("SELECT user_id, username, friendly_name FROM k_plex WHERE active=1 AND user_id NOT IN"
                                          " (SELECT plex_user_id FROM k_services WHERE plex_user_id IS NOT NULL) ORDER BY friendly_name")]}


@router.put("/settings")
async def put_settings(req: Request):
    b = await req.json()
    s = settings()
    for k in ("remind_days", "remind_repeat_days", "inactive_days", "message_hour", "sync_hour"):
        if k in b:
            try:
                s[k] = max(0, int(b[k]))
            except (TypeError, ValueError):
                raise HTTPException(400, f"{k} skal være et helt tal")
    if "plex_price" in b:
        s["plex_price"] = num(money(b["plex_price"]))
    for k in ("fixed_costs", "template"):
        if k in b:
            s[k] = str(b[k])
    if not s["template"].strip():
        s["template"] = DEFAULTS["template"]
    D["kv_set"]("kunder_settings", s)
    return s


@router.get("/customers")
def customers_list():
    return customers_out()


@router.get("/customers/{cid}")
def customers_get(cid: int):
    return customer_detail(cid)


@router.post("/customers")
async def customers_post(req: Request):
    cid = add_customer(clean_customer(await req.json()))
    return customer_detail(cid)


@router.put("/customers/{cid}")
async def customers_put(cid: int, req: Request):
    old = one("SELECT * FROM k_customers WHERE id=?", (cid,))
    if not old:
        raise HTTPException(404, "kunden findes ikke")
    d = clean_customer(await req.json(), old)
    run("UPDATE k_customers SET name=?, status=?, kind=?, method=?, freq=?, cycle=?, due_day=?, phone=?, email=?, contact=?, notes=?, updated=?"
        " WHERE id=?", (d["name"], d["status"], d["kind"], d["method"], d["freq"], d["cycle"], d["due_day"], d["phone"], d["email"],
                        d["contact"], d["notes"], iso(now()), cid))
    return customer_detail(cid)


@router.delete("/customers/{cid}")
def customers_delete(cid: int):
    if not one("SELECT id FROM k_customers WHERE id=?", (cid,)):
        raise HTTPException(404, "kunden findes ikke")
    if one("SELECT id FROM k_charges WHERE customer_id=? AND paid_at IS NOT NULL", (cid,)):
        raise HTTPException(400, "kunden har betalte opkrævninger og kan ikke slettes. Sæt status til Stoppet i stedet, så bevares historikken.")
    con = D["db"]()
    with con:
        con.execute("DELETE FROM k_services WHERE customer_id=?", (cid,))
        con.execute("DELETE FROM k_adjust WHERE customer_id=?", (cid,))
        con.execute("DELETE FROM k_charges WHERE customer_id=?", (cid,))
        con.execute("UPDATE k_iptv SET customer_id=NULL WHERE customer_id=?", (cid,))   # linjerne bevares under "Ingen kunde"
        con.execute("DELETE FROM k_customers WHERE id=?", (cid,))
    con.close()
    return {"ok": True}


@router.post("/customers/{cid}/merge")
async def customers_merge(cid: int, req: Request):
    """Flet denne kunde ind i en anden (fx en Plex-konto fra Tautulli, som en anden kunde betaler for)."""
    into = (await req.json()).get("into")
    if not into or int(into) == cid or not one("SELECT id FROM k_customers WHERE id=?", (into,)) or not one("SELECT id FROM k_customers WHERE id=?", (cid,)):
        raise HTTPException(400, "vælg en anden kunde at flette ind i")
    into = int(into)
    src = one("SELECT name FROM k_customers WHERE id=?", (cid,))
    con = D["db"]()
    with con:
        con.execute("UPDATE k_services SET label=? WHERE customer_id=? AND label=''", (src["name"], cid))
        for t in ("k_services", "k_iptv", "k_adjust"):
            con.execute(f"UPDATE {t} SET customer_id=? WHERE customer_id=?", (into, cid))
        have = {r[0] for r in con.execute("SELECT period FROM k_charges WHERE customer_id=?", (into,)).fetchall()}
        for r in con.execute("SELECT id, period, paid_at FROM k_charges WHERE customer_id=?", (cid,)).fetchall():
            if r["period"] in have and not r["paid_at"]:
                con.execute("DELETE FROM k_charges WHERE id=?", (r["id"],))
            elif r["period"] in have:
                con.execute("UPDATE k_charges SET customer_id=?, period=? WHERE id=?", (into, r["period"] + "b", r["id"]))
            else:
                con.execute("UPDATE k_charges SET customer_id=? WHERE id=?", (into, r["id"]))
        con.execute("DELETE FROM k_customers WHERE id=?", (cid,))
    con.close()
    return customer_detail(into)


# ---------------------------------------------------------------- tjenester, fradrag, logins

def _need_customer(cid):
    if not one("SELECT id FROM k_customers WHERE id=?", (cid,)):
        raise HTTPException(404, "kunden findes ikke")


@router.post("/services")
async def service_save(req: Request):
    b = await req.json()
    sid = b.get("id")
    old = one("SELECT * FROM k_services WHERE id=?", (sid,)) if sid else None
    if sid and not old:
        raise HTTPException(404, "tjenesten findes ikke")
    cid = int(b.get("customer_id") or (old or {}).get("customer_id") or 0)
    _need_customer(cid)
    service = b.get("service") or (old or {}).get("service")
    if service not in SERVICE_DA:
        raise HTTPException(400, "ukendt tjeneste")
    puid = b.get("plex_user_id", (old or {}).get("plex_user_id"))
    puid = int(puid) if puid not in (None, "", 0, "0") else None
    if puid and one("SELECT id FROM k_services WHERE plex_user_id=? AND id!=?", (puid, sid or 0)):
        raise HTTPException(400, "den Plex-bruger er allerede knyttet til en anden tjeneste")
    vals = (cid, service, str(b.get("label", (old or {}).get("label", "")) or "").strip(), money(b.get("price", (old or {}).get("price", 0))),
            puid, str(b.get("username", (old or {}).get("username", "")) or "").strip(),
            str(b.get("email", (old or {}).get("email", "")) or "").strip(), str(b.get("note", (old or {}).get("note", "")) or "").strip(),
            1 if b.get("active", (old or {}).get("active", 1)) else 0)
    if old:
        run("UPDATE k_services SET customer_id=?, service=?, label=?, price=?, plex_user_id=?, username=?, email=?, note=?, active=? WHERE id=?",
            vals + (sid,))
    else:
        sid = run("INSERT INTO k_services (customer_id, service, label, price, plex_user_id, username, email, note, active) VALUES (?,?,?,?,?,?,?,?,?)", vals)
    if b.get("password"):          # tomt felt = uændret
        run("UPDATE k_services SET password=? WHERE id=?", (str(b["password"]), sid))
    if b.get("clear_password"):
        run("UPDATE k_services SET password='' WHERE id=?", (sid,))
    return customer_detail(cid)


@router.delete("/services/{sid}")
def service_delete(sid: int):
    old = one("SELECT customer_id FROM k_services WHERE id=?", (sid,))
    if not old:
        raise HTTPException(404, "tjenesten findes ikke")
    run("DELETE FROM k_services WHERE id=?", (sid,))
    return customer_detail(old["customer_id"])


@router.post("/adjust")
async def adjust_save(req: Request):
    b = await req.json()
    cid = int(b.get("customer_id") or 0)
    _need_customer(cid)
    amount = money(b.get("amount"))
    if not amount:
        raise HTTPException(400, "skriv et beløb (minus for fradrag, fx -49)")
    try:
        remaining = max(1, int(b.get("remaining") or 1))
    except (TypeError, ValueError):
        remaining = 1
    run("INSERT INTO k_adjust (customer_id, amount, text, remaining, created) VALUES (?,?,?,?,?)",
        (cid, amount, str(b.get("text") or "").strip(), remaining, iso(now())))
    return customer_detail(cid)


@router.delete("/adjust/{aid}")
def adjust_delete(aid: int):
    old = one("SELECT customer_id FROM k_adjust WHERE id=?", (aid,))
    if not old:
        raise HTTPException(404, "findes ikke")
    run("DELETE FROM k_adjust WHERE id=?", (aid,))
    return customer_detail(old["customer_id"])


@router.get("/logins")
def logins_list():
    return [{"id": r["id"], "service": r["service"], "label": r["label"], "username": r["username"], "note": r["note"],
             "has_password": bool(r["password"])} for r in rows("SELECT * FROM k_logins ORDER BY service COLLATE NOCASE, label COLLATE NOCASE")]


@router.post("/logins")
async def logins_save(req: Request):
    b = await req.json()
    vals = (str(b.get("service") or "").strip(), str(b.get("label") or "").strip(), str(b.get("username") or "").strip(), str(b.get("note") or "").strip())
    if not (vals[0] or vals[1] or vals[2]):
        raise HTTPException(400, "skriv mindst tjeneste eller brugernavn")
    lid = b.get("id")
    if lid:
        run("UPDATE k_logins SET service=?, label=?, username=?, note=? WHERE id=?", vals + (lid,))
    else:
        lid = run("INSERT INTO k_logins (service, label, username, note) VALUES (?,?,?,?)", vals)
    if b.get("password"):
        run("UPDATE k_logins SET password=? WHERE id=?", (str(b["password"]), lid))
    return logins_list()


@router.delete("/logins/{lid}")
def logins_delete(lid: int):
    run("DELETE FROM k_logins WHERE id=?", (lid,))
    return logins_list()


@router.get("/secret/{kind}/{sid}")
def secret(kind: str, sid: int):
    """Det eneste sted, et kodeord forlader databasen. Kaldes kun, når du trykker Vis."""
    table = {"service": "k_services", "iptv": "k_iptv", "login": "k_logins"}.get(kind)
    if not table:
        raise HTTPException(404, "ukendt type")
    r = one(f"SELECT username, password FROM {table} WHERE id=?", (sid,))
    if not r:
        raise HTTPException(404, "findes ikke")
    return Response(json.dumps({"username": r["username"], "password": r["password"]}), media_type="application/json",
                    headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- opkrævninger

def _prev_next(period, d):
    y, m = int(period[:4]), int(period[5:7]) + d
    while m < 1:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return f"{y:04d}-{m:02d}"


def _valid_period(p):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(p or "")):
        raise HTTPException(400, "ugyldig måned")
    return p


def charges_for(period):
    cur = cur_period()
    rd = int(settings()["remind_days"])
    if period == cur:
        ensure_charges(period)
    cust = {c["id"]: c for c in rows("SELECT * FROM k_customers")}
    out = []
    for r in rows("SELECT * FROM k_charges WHERE period=?", (period,)):
        c = cust.get(r["customer_id"])
        if not c:
            continue
        det = json.loads(r["detail"] or "{}")
        st, late = charge_status(r, rd)
        out.append({"id": r["id"], "customer_id": c["id"], "name": c["name"], "amount": num(r["amount"]), "base": num(r["base"]),
                    "lines": det.get("lines", []), "adjust": det.get("adjust", []), "services": service_names(det.get("lines", [])),
                    "method": c["method"], "status": st, "late": late, "requested_at": r["requested_at"], "paid_at": r["paid_at"],
                    "note": r["note"], "due_day": c["due_day"], "contact": c["contact"], "phone": c["phone"],
                    "message": message_for(c, r["amount"], det.get("lines", []))})
    preview = False
    if period > cur:        # fremtidig måned: vis, hvad der kommer – intet gemmes
        preview = True
        month = int(period[5:7])
        by = {}
        for x in rows("SELECT * FROM k_services"):
            by.setdefault(x["customer_id"], []).append(x)
        for c in cust.values():
            if c["status"] != "aktiv" or c["kind"] != "kunde" or month not in due_months(c["freq"], c["cycle"]):
                continue
            sv = by.get(c["id"], [])
            amt = monthly(sv) * FREQ[c["freq"]]
            if amt:
                out.append({"id": None, "customer_id": c["id"], "name": c["name"], "amount": num(amt), "base": num(amt),
                            "lines": service_lines(sv), "adjust": [], "services": service_names(service_lines(sv)), "method": c["method"],
                            "status": "kommer", "late": False, "requested_at": None, "paid_at": None, "note": "", "due_day": c["due_day"],
                            "contact": c["contact"], "phone": c["phone"], "message": ""})
    out.sort(key=lambda x: norm(x["name"]))
    return {"period": period, "current": cur, "preview": preview, "prev": _prev_next(period, -1), "next": _prev_next(period, 1),
            "label": f"{MONTHS_DA[int(period[5:7]) - 1]} {period[:4]}", "charges": out}


@router.get("/charges")
def charges_get(period: str = ""):
    return charges_for(_valid_period(period or cur_period()))


@router.post("/charges/generate")
async def charges_generate(req: Request):
    period = _valid_period((await req.json()).get("period"))
    if period > cur_period():
        raise HTTPException(400, "opkrævninger for fremtidige måneder oprettes automatisk den 1.")
    ensure_charges(period)
    return charges_for(period)


@router.post("/charges/{chid}")
async def charge_action(chid: int, req: Request):
    b = await req.json()
    ch = one("SELECT * FROM k_charges WHERE id=?", (chid,))
    if not ch:
        raise HTTPException(404, "opkrævningen findes ikke")
    a, t = b.get("action"), iso(now())
    if a == "request":
        run("UPDATE k_charges SET requested_at=COALESCE(requested_at, ?), skipped=0 WHERE id=?", (t, chid))
    elif a == "unrequest":
        run("UPDATE k_charges SET requested_at=NULL WHERE id=?", (chid,))
    elif a == "paid":
        run("UPDATE k_charges SET paid_at=?, requested_at=COALESCE(requested_at, ?), skipped=0 WHERE id=?", (t, t, chid))
    elif a == "unpaid":
        run("UPDATE k_charges SET paid_at=NULL WHERE id=?", (chid,))
    elif a == "skip":
        run("UPDATE k_charges SET skipped=1 WHERE id=?", (chid,))
    elif a == "unskip":
        run("UPDATE k_charges SET skipped=0 WHERE id=?", (chid,))
    elif a == "edit":
        amount = money(b.get("amount"))
        if amount < 0:
            raise HTTPException(400, "beløbet kan ikke være negativt")
        run("UPDATE k_charges SET amount=?, note=? WHERE id=?", (amount, str(b.get("note") or "").strip(), chid))
    elif a == "recalc":       # nye priser på kunden: regn grundbeløbet om, behold fradrag/tillæg
        c = one("SELECT * FROM k_customers WHERE id=?", (ch["customer_id"],))
        sv = rows("SELECT * FROM k_services WHERE customer_id=?", (ch["customer_id"],))
        det = json.loads(ch["detail"] or "{}")
        n = FREQ.get(c["freq"], det.get("months") or 0)
        base = monthly(sv) * n
        det.update({"lines": service_lines(sv), "months": n})
        amount = max(0.0, base + sum(x["amount"] for x in det.get("adjust", [])))
        run("UPDATE k_charges SET amount=?, base=?, detail=? WHERE id=?", (amount, base, json.dumps(det, ensure_ascii=False), chid))
    else:
        raise HTTPException(400, "ukendt handling")
    return charges_for(ch["period"][:7])


# ---------------------------------------------------------------- IPTV-linjer

def _iptv_out(l, names=None):
    today = now().date().isoformat()
    return {"id": l["id"], "customer_id": l["customer_id"], "customer": (names or {}).get(l["customer_id"], ""), "label": l["label"],
            "username": l["username"], "expires": l["expires"], "cost": num(l["cost"]), "tivimate": l["tivimate"], "note": l["note"],
            "renew": bool(l["renew"]), "has_password": bool(l["password"]), "expired": bool(l["expires"] and l["expires"] < today)}


def iptv_due(period):
    """Linjer, der udløber i måneden og skal fornyes."""
    return rows("SELECT * FROM k_iptv WHERE renew=1 AND expires>=? AND expires<? ORDER BY expires", (period + "-01", _prev_next(period, 1) + "-01"))


def iptv_expired():
    """Linjer, der allerede er udløbet (før denne måned) og stadig står til at skulle fornyes."""
    return rows("SELECT * FROM k_iptv WHERE renew=1 AND expires IS NOT NULL AND expires!='' AND expires<? ORDER BY expires", (cur_period() + "-01",))


@router.get("/iptv")
def iptv_list():
    names = {c["id"]: c["name"] for c in rows("SELECT id, name FROM k_customers")}
    return {"period": cur_period(), "next": _prev_next(cur_period(), 1),
            "lines": [_iptv_out(l, names) for l in rows("SELECT * FROM k_iptv ORDER BY (expires IS NULL OR expires=''), expires")]}


@router.post("/iptv")
async def iptv_save(req: Request):
    b = await req.json()
    lid = b.get("id")
    old = one("SELECT * FROM k_iptv WHERE id=?", (lid,)) if lid else None
    if lid and not old:
        raise HTTPException(404, "linjen findes ikke")
    o = old or {}
    cid = b.get("customer_id", o.get("customer_id"))
    cid = int(cid) if cid not in (None, "", 0, "0") else None
    if cid:
        _need_customer(cid)
    exp = str(b.get("expires", o.get("expires") or "") or "").strip()
    if exp and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", exp):
        raise HTTPException(400, "udløbsdatoen skal være en dato")
    vals = (cid, str(b.get("label", o.get("label", "")) or "").strip(), str(b.get("username", o.get("username", "")) or "").strip(),
            exp or None, money(b.get("cost", o.get("cost", 0))), str(b.get("tivimate", o.get("tivimate", "")) or "").strip(),
            str(b.get("note", o.get("note", "")) or "").strip(), 1 if b.get("renew", o.get("renew", 1)) else 0)
    if old:
        run("UPDATE k_iptv SET customer_id=?, label=?, username=?, expires=?, cost=?, tivimate=?, note=?, renew=? WHERE id=?", vals + (lid,))
    else:
        lid = run("INSERT INTO k_iptv (customer_id, label, username, expires, cost, tivimate, note, renew) VALUES (?,?,?,?,?,?,?,?)", vals)
    if b.get("password"):
        run("UPDATE k_iptv SET password=? WHERE id=?", (str(b["password"]), lid))
    return iptv_list()


@router.delete("/iptv/{lid}")
def iptv_delete(lid: int):
    run("DELETE FROM k_iptv WHERE id=?", (lid,))
    return iptv_list()


# ---------------------------------------------------------------- synk fra Tautulli

def sync_tautulli():
    """Hent Plex-brugerne fra Tautulli og knyt dem til kunder. Opretter en kunde for nye Plex-brugere."""
    t = D["tautulli"]
    users = t("get_users") or []
    table = (t("get_users_table", length=5000, order_column="friendly_name", order_dir="asc") or {}).get("data") or []
    seen_at = {}
    for r in table:
        try:
            seen_at[int(r.get("user_id"))] = int(r.get("last_seen") or 0) or None
        except (TypeError, ValueError):
            pass
    s = settings()
    res = {"users": 0, "linked": [], "created": [], "gone": [], "at": iso(now()), "ok": True}
    with _lock:
        con = D["db"]()
        try:
            with con:
                known = {r["user_id"]: dict(r) for r in con.execute("SELECT * FROM k_plex").fetchall()}
                live = set()
                for u in users:
                    try:
                        uid = int(u.get("user_id"))
                    except (TypeError, ValueError):
                        continue
                    if uid <= 0 or str(u.get("username") or "").lower() == "local":
                        continue
                    active = 1 if u.get("is_active", 1) else 0
                    if active:
                        live.add(uid)
                    con.execute("INSERT INTO k_plex (user_id, username, friendly_name, email, last_seen, active, synced) VALUES (?,?,?,?,?,?,?)"
                                " ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, friendly_name=excluded.friendly_name,"
                                " email=excluded.email, last_seen=COALESCE(excluded.last_seen, k_plex.last_seen), active=excluded.active, synced=excluded.synced",
                                (uid, u.get("username") or "", u.get("friendly_name") or u.get("username") or "", u.get("email") or "",
                                 seen_at.get(uid), active, res["at"]))
                res["users"] = len(live)
                for uid, k in known.items():
                    if uid not in live and k["active"]:
                        con.execute("UPDATE k_plex SET active=0, synced=? WHERE user_id=?", (res["at"], uid))
                        res["gone"].append(k["friendly_name"] or k["username"])
                linked = {r[0] for r in con.execute("SELECT plex_user_id FROM k_services WHERE plex_user_id IS NOT NULL").fetchall()}
                for p in [dict(r) for r in con.execute("SELECT * FROM k_plex WHERE active=1 ORDER BY friendly_name").fetchall()]:
                    if p["user_id"] in linked:
                        continue
                    un, em, fn = (p["username"] or "").lower(), (p["email"] or "").lower(), norm(p["friendly_name"])
                    free = [dict(r) for r in con.execute("SELECT s.*, c.name cname FROM k_services s JOIN k_customers c ON c.id=s.customer_id"
                                                         " WHERE s.service='plex' AND s.plex_user_id IS NULL").fetchall()]
                    hit = next((x for x in free if un and (x["username"] or "").lower() in (un, em)), None) \
                        or next((x for x in free if em and em in ((x["email"] or "").lower(), (x["username"] or "").lower())), None)
                    if not hit and fn:
                        same = [x for x in free if norm(x["cname"]) == fn or (x["label"] and norm(x["label"]) == fn)]
                        if len(same) == 1:
                            hit = same[0]
                    if hit:
                        con.execute("UPDATE k_services SET plex_user_id=?, username=CASE WHEN username='' THEN ? ELSE username END,"
                                    " email=CASE WHEN email='' THEN ? ELSE email END WHERE id=?", (p["user_id"], p["username"], p["email"], hit["id"]))
                        res["linked"].append(p["friendly_name"])
                        continue
                    cust = [dict(r) for r in con.execute("SELECT * FROM k_customers").fetchall()]
                    c = next((x for x in cust if fn and norm(x["name"]) == fn), None)
                    if c and not con.execute("SELECT 1 FROM k_services WHERE customer_id=? AND service='plex'", (c["id"],)).fetchone():
                        cid = c["id"]
                        res["linked"].append(p["friendly_name"])
                    else:
                        cur = con.execute("INSERT INTO k_customers (name, status, kind, created, updated) VALUES (?, 'aktiv', 'kunde', ?, ?)",
                                          (p["friendly_name"] or p["username"], res["at"], res["at"]))
                        cid = cur.lastrowid
                        res["created"].append(p["friendly_name"] or p["username"])
                    con.execute("INSERT INTO k_services (customer_id, service, price, plex_user_id, username, email) VALUES (?, 'plex', ?, ?, ?, ?)",
                                (cid, float(s["plex_price"] or 0), p["user_id"], p["username"], p["email"]))
        finally:
            con.close()
    D["kv_set"]("kunder_sync", res)
    return res


@router.post("/sync")
def sync_now():
    try:
        return sync_tautulli()
    except RuntimeError as e:
        raise HTTPException(502, str(e))


# ---------------------------------------------------------------- økonomi

def fixed_costs(text):
    out = []
    for line in str(text or "").splitlines():
        if ":" in line or "=" in line:
            k, v = re.split(r"[:=]", line, maxsplit=1)
            if k.strip() and money(v):
                out.append({"name": k.strip(), "amount": num(money(v))})
    return out


@router.get("/economy")
def economy(year: int = 0):
    year = year or now().year
    cur = cur_period()
    fixed = fixed_costs(settings()["fixed_costs"])
    fixed_sum = sum(f["amount"] for f in fixed)
    cust = rows("SELECT * FROM k_customers WHERE status='aktiv' AND kind='kunde' AND freq IS NOT NULL")
    by = {}
    for x in rows("SELECT * FROM k_services"):
        by.setdefault(x["customer_id"], []).append(x)
    lines = rows("SELECT expires, cost FROM k_iptv WHERE renew=1 AND expires IS NOT NULL AND expires!=''")
    months = []
    for m in range(1, 13):
        p = f"{year:04d}-{m:02d}"
        ch = rows("SELECT ch.amount, ch.paid_at, ch.skipped, c.method FROM k_charges ch JOIN k_customers c ON c.id=ch.customer_id"
                  " WHERE substr(ch.period,1,7)=?", (p,))
        charged = sum(r["amount"] for r in ch if not r["skipped"])
        paid = sum(r["amount"] for r in ch if r["paid_at"] and not r["skipped"])
        forecast = sum(monthly(by.get(c["id"], [])) * FREQ[c["freq"]] for c in cust if m in due_months(c["freq"], c["cycle"]))
        methods = {}
        for r in ch:
            if r["paid_at"] and not r["skipped"]:
                methods[r["method"] or "–"] = methods.get(r["method"] or "–", 0) + r["amount"]
        iptv = sum(float(l["cost"] or 0) for l in lines if int(l["expires"][5:7]) == m)
        income = paid if p < cur else (charged if ch else forecast) if p == cur else forecast
        nodata = p < cur and not ch      # måneder før Fangarr holdt regnskab: vis ingenting i stedet for et forkert minus
        if nodata:
            iptv = 0
        months.append({"period": p, "label": MONTHS_DA[m - 1], "charged": num(charged), "paid": num(paid), "forecast": num(forecast),
                       "has_charges": bool(ch), "state": "past" if p < cur else "now" if p == cur else "future",
                       "methods": {k: num(v) for k, v in methods.items()}, "iptv": num(iptv), "fixed": 0 if nodata else num(fixed_sum),
                       "nodata": nodata, "income": num(income), "result": 0 if nodata else num(income - iptv - fixed_sum)})
    return {"year": year, "months": months, "fixed": fixed,
            "monthly_income": num(sum(monthly(by.get(c["id"], [])) for c in cust)), "customers": len(cust)}


# ---------------------------------------------------------------- forside og beskeder

def brief():
    """Tal til forsiden og menuen."""
    if not one("SELECT id FROM k_customers LIMIT 1"):
        return {"enabled": False}
    cur = cur_period()
    late = overdue_list()
    open_ = rows("SELECT ch.amount, ch.requested_at FROM k_charges ch WHERE ch.period=? AND ch.paid_at IS NULL AND ch.skipped=0", (cur,))
    setup_n = sum(1 for c in customers_out() if {"cyklus", "metode", "pris"} & set(c["flags"]))
    due = iptv_due(cur)
    return {"enabled": True, "overdue": len(late), "overdue_kr": num(sum(r["amount"] for r in late)),
            "unrequested": sum(1 for r in open_ if not r["requested_at"]), "open": len(open_), "open_kr": num(sum(r["amount"] for r in open_)),
            "setup": setup_n, "iptv_due": len(due), "iptv_expired": len(iptv_expired()), "label": MONTHS_DA[int(cur[5:7]) - 1]}


def _kr(v):
    return f"{num(round(v)):,}".replace(",", ".") + " kr."


def month_message(period):
    ch = rows("SELECT ch.amount, c.method FROM k_charges ch JOIN k_customers c ON c.id=ch.customer_id WHERE ch.period=? AND ch.skipped=0", (period,))
    due = iptv_due(period)
    if not ch and not due:
        return ""
    name = MONTHS_DA[int(period[5:7]) - 1]
    out = [f"💳 Stream365 – opkrævning for {name}", ""]
    if ch:
        out.append(f"{len(ch)} kunder skal opkræves: {_kr(sum(r['amount'] for r in ch))}")
        by = {}
        for r in ch:
            k = r["method"] or "uden betalingsmetode"
            by.setdefault(k, [0, 0.0])
            by[k][0] += 1
            by[k][1] += r["amount"]
        out += [f"• {k}: {n} kunder, {_kr(v)}" for k, (n, v) in sorted(by.items())]
    else:
        out.append("Ingen kunder skal opkræves i denne måned.")
    out.append("")
    if due:
        cost = sum(float(l["cost"] or 0) for l in due)
        out.append(f"📺 {len(due)} IPTV-{'linje' if len(due) == 1 else 'linjer'} skal fornyes" + (f" (ca. {_kr(cost)})" if cost else ""))
    else:
        out.append("📺 Ingen IPTV-linjer skal fornyes.")
    old = iptv_expired() if period == cur_period() else []
    if old:
        out.append(f"⚠️ {len(old)} IPTV-{'linje' if len(old) == 1 else 'linjer'} står som allerede udløbet.")
    out += ["", "Se listen i Fangarr › Opkrævning."]
    return "\n".join(out)


def tick():
    """Kaldes hvert minut af Fangarrs baggrundsjob."""
    n = now()
    s = settings()
    st = D["kv_get"]("kunder_jobs", {}) or {}
    changed = False
    today, cur = n.date().isoformat(), period_of(n)
    # natlig synk – først når du selv har synket eller importeret første gang
    if D["tautulli_enabled"]() and D["kv_get"]("kunder_sync") and n.hour >= int(s["sync_hour"]) and st.get("sync_day") != today:
        st["sync_day"] = today
        changed = True
        try:
            sync_tautulli()
            if st.get("sync_failed"):
                st["sync_failed"] = False
                D["telegram"]("✅ Fangarr – Kunder: synk fra Tautulli er i orden igen.")
        except Exception as e:   # må aldrig stoppe baggrundsjobbet
            D["log"].warning("Synk fra Tautulli fejlede: %s", e)
            if not st.get("sync_failed"):
                st["sync_failed"] = True
                D["telegram"](f"🚨 Fangarr – Kunder: natlig synk fra Tautulli fejlede\n\n{str(e)[:200]}")
    if one("SELECT id FROM k_customers LIMIT 1") and n.hour >= int(s["message_hour"]):
        if st.get("month") != cur:
            st["month"] = cur
            changed = True
            ensure_charges(cur)
            if n.day == 1:
                msg = month_message(cur)
                if msg:
                    D["telegram"](msg)
        if st.get("remind_day") != today:
            st["remind_day"] = today
            changed = True
            late = overdue_list()
            ids = [r["id"] for r in late]
            sent = set(st.get("remind_ids") or [])
            last = st.get("remind_sent") or ""
            repeat = max(1, int(s["remind_repeat_days"]))
            old = not last or (n.date() - datetime.date.fromisoformat(last)).days >= repeat
            if late and (old or set(ids) - sent):
                lines = [f"• {r['name']}: {_kr(r['amount'])} (anmodet {r['requested_at'][8:10]}/{r['requested_at'][5:7]})" for r in late[:40]]
                D["telegram"](f"⏰ Stream365 – {len(late)} {'kunde mangler' if len(late) == 1 else 'kunder mangler'} at betale "
                              f"({_kr(sum(r['amount'] for r in late))})\n\n" + "\n".join(lines) + "\n\nMarkér Betalt i Fangarr › Opkrævning.")
                st["remind_sent"], st["remind_ids"] = today, ids
            elif not late and sent:
                D["telegram"]("✅ Stream365 – alle, der var anmodet, har nu betalt.")
                st["remind_ids"], st["remind_sent"] = [], ""
            elif late:
                st["remind_ids"] = [i for i in sent if i in ids]
    if changed:
        D["kv_set"]("kunder_jobs", st)


# ---------------------------------------------------------------- import fra regnearket (CSV)

def _csv(text):
    text = (text or "").lstrip("﻿")
    if not text.strip():
        return []
    head = text[:4000]
    delim = ";" if head.count(";") > head.count(",") else ","
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim)]


def _header(table, need):
    for i, r in enumerate(table):
        low = [norm(c) for c in r]
        if all(any(n == c or c.startswith(n) for c in low) for n in need):
            return i, {c: j for j, c in enumerate(low) if c}
    return None, {}


def _col(r, idx, *names):
    for n in names:
        for k, j in idx.items():
            if (k == n or k.startswith(n)) and j < len(r):
                return r[j]
    return ""


FREQ_IN = {"kvartal": "kvartal", "maanedlig": "maaned", "maaned": "maaned", "halvaarlig": "halvaar", "aarlig": "aar"}
CONTACT_RE = re.compile(r"^(FB(\(P\))?|TG|MB|SMS|Telegram)$", re.I)


def _notes(text):
    """'Dato: 25. | Tlf: 5192 | FB | Træk 49,- fra næste' -> felter."""
    out = {"due_day": None, "phone": "", "contact": "", "notes": [], "adjust": None}
    for tok in [t.strip() for t in str(text or "").split("|") if t.strip()]:
        m = re.match(r"dato:\s*(\d{1,2})", tok, re.I)
        if m:
            out["due_day"] = int(m.group(1))
            continue
        m = re.match(r"tlf:?\s*([\d +]+)", tok, re.I)
        if m:
            out["phone"] = m.group(1).strip()
            continue
        if CONTACT_RE.match(tok):
            out["contact"] = tok
            continue
        m = re.search(r"tr[æa]k\s+(\d+)", tok, re.I)
        if m:
            out["adjust"] = -float(m.group(1))
            continue
        if re.match(r"inkl\.? hbo", tok, re.I):
            continue
        out["notes"].append(tok)
    return out


def parse_subscriptions(text):
    """Fanen 'Abonnementer (Optimeret)'. Rækker med samme navn bliver én kunde med flere konti."""
    table = _csv(text)
    hi, idx = _header(table, ["navn", "frekvens", "opkraevningscyklus"])
    if hi is None:
        raise HTTPException(400, "kan ikke finde kolonnerne Navn, Frekvens og Opkrævningscyklus i abonnement-filen")
    cust, order, doubts = {}, [], []
    for r in table[hi + 1:]:
        name = r[0].strip() if r else ""
        if not name or norm(name).startswith("samlet total"):
            continue
        nt = _notes(_col(r, idx, "noter"))
        key = norm(name)
        first = key not in cust
        if first:
            st = norm(_col(r, idx, "status"))
            freq = FREQ_IN.get(norm(_col(r, idx, "frekvens")))
            cyc = re.match(r"\s*(\d{1,2})", _col(r, idx, "opkraevningscyklus"))
            cust[key] = {"name": name, "status": {"pause": "pause", "blokeret": "stoppet"}.get(st, "aktiv"), "kind": "kunde",
                         "method": _col(r, idx, "betalingsmetode"), "freq": freq, "cycle": int(cyc.group(1)) if cyc and freq != "maaned" else None,
                         "due_day": nt["due_day"], "phone": nt["phone"], "contact": nt["contact"], "email": "", "notes": " | ".join(nt["notes"]),
                         "services": [], "iptv": [], "adjust": []}
            order.append(key)
            if not freq:
                doubts.append(f"{name}: frekvensen kunne ikke læses")
        c = cust[key]
        label = "" if first else (" | ".join(nt["notes"]) or f"Konto {len([s for s in c['services'] if s['service'] == 'plex']) + 1}")
        if first and nt["adjust"]:
            c["adjust"].append({"amount": nt["adjust"], "text": "Fradrag fra regnearket"})
        user, email, code = _col(r, idx, "brugernavn"), _col(r, idx, "email"), _col(r, idx, "plex kode")
        total = money(_col(r, idx, "total"))
        row_sum = 0.0
        for svc, col in (("plex", "plex"), ("iptv", "iptv"), ("spotify", "spotify"), ("youtube", "youtube"), ("mofibo", "mofibo"), ("hbo", "hbo")):
            j = next((j for k, j in idx.items() if k == col), None)
            price = money(r[j]) if j is not None and j < len(r) else 0.0
            if not price:
                continue
            row_sum += price
            s = {"service": svc, "label": label, "price": price, "username": "", "email": "", "password": "", "note": ""}
            if svc == "plex":
                s.update({"username": user, "email": email})
                if code and re.fullmatch(r"\d+", code):
                    s["note"] = f"Feltet 'Plex Kode' i regnearket: {code}"
                elif code:
                    s["password"] = code
                if not user:
                    doubts.append(f"{name}: har Plex, men intet brugernavn i arket")
            c["services"].append(s)
        if first and email and not c["email"]:
            c["email"] = email
        n = FREQ.get(c["freq"], 0)
        if n and total and abs(row_sum * n - total) > 0.5:
            doubts.append(f"{name}: totalen i arket er {num(total)} kr., men tjenesterne giver {num(row_sum * n)} kr.")
        iu = [x.strip() for x in _col(r, idx, "iptv bruger").split("/") if x.strip()]
        ip = [x.strip() for x in _col(r, idx, "iptv kode").split("/")]
        for i, u in enumerate(iu):
            c["iptv"].append({"label": label or (f"Linje {i + 1}" if len(iu) > 1 else ""), "username": u, "password": ip[i].strip() if i < len(ip) else ""})
        if any(s["service"] == "iptv" for s in c["services"]) and not c["iptv"] and first:
            pass   # kan komme fra IPTV-fanen
    users = {}
    for k in order:
        for s in cust[k]["services"]:
            if s["service"] == "plex" and s["username"]:
                users.setdefault(s["username"].lower(), []).append(cust[k]["name"])
    for u, names in users.items():
        if len(set(names)) > 1:
            doubts.append(f"Plex-brugernavnet '{u}' står på flere kunder: {', '.join(sorted(set(names)))}")
    phones = {}
    for k in order:
        if cust[k]["phone"]:
            phones.setdefault(re.sub(r"\D", "", cust[k]["phone"]), []).append(cust[k]["name"])
    for p, names in phones.items():
        if len(names) > 1:
            doubts.append(f"Samme telefonnummer på flere kunder: {', '.join(names)}")
    return [cust[k] for k in order], doubts


def _date(v):
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", str(v or "").strip())
    if m:
        try:
            return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(v or "").strip())
    return m.group(0) if m else None


def parse_iptv(text):
    """Fanen 'IPTV'. Læser kun linjerne frem til rækken TOTAL – alt derunder (andre logins) springes over."""
    table = _csv(text)
    hi, idx = _header(table, ["udloeb", "navn", "user", "pass"])
    if hi is None:
        raise HTTPException(400, "kan ikke finde kolonnerne Udløb, Navn, User og Pass i IPTV-filen")
    out = []
    for r in table[hi + 1:]:
        if r and norm(r[0]) == "total":
            break
        exp = _date(_col(r, idx, "udloeb"))
        if not exp:
            continue
        user, pw, tm = _col(r, idx, "user"), _col(r, idx, "pass"), _col(r, idx, "tivimate")
        m = re.search(r"username=([^&\s]+)&password=([^&\s]+)", tm)
        if m and not user:       # linje gemt som et link med brugernavn og kode i adressen
            user, pw, tm = m.group(1), m.group(2), ""
        first = r[0].strip() if r else ""
        out.append({"label": _col(r, idx, "navn"), "expires": exp, "cost": money(_col(r, idx, "beloeb")), "username": user, "password": pw,
                    "tivimate": tm, "renew": 0 if norm(first) == "forny ikke" else 1,
                    "note": first if first and norm(first) not in MONTHS_DA and norm(first) != "forny ikke" else ""})
    return out


def parse_cockpit(text):
    """Fanen 'Måneds-Cockpit': hvem er anmodet, og hvem har betalt i den valgte måned."""
    table = _csv(text)
    hi, idx = _header(table, ["navn", "betalt"])
    if hi is None:
        raise HTTPException(400, "kan ikke finde kolonnerne Navn og Betalt i cockpit-filen")
    out = []
    for r in table[hi + 1:]:
        name = r[0].strip() if r else ""
        if not name:
            continue
        yes = lambda v: norm(v) in ("true", "sand", "ja", "1", "x")
        out.append({"name": name, "amount": money(_col(r, idx, "beloeb")), "requested": yes(_col(r, idx, "anmodet")), "paid": yes(_col(r, idx, "betalt"))})
    return out


def _match_customer(label, cust):
    """Find kunden til en IPTV-linje ud fra navnet på linjen ('Mikael Andersen Stue')."""
    toks = norm(re.sub(r"\(.*?\)", " ", label)).split()
    best = []
    for c in cust:
        ct = norm(c["name"]).split()
        if not ct or not toks:
            continue
        score = 0
        if toks[0] == ct[0]:
            score = 1 + sum(1 for t in toks[1:] if t in ct[1:])
        if score:
            best.append((score, c))
    if not best:
        return None
    top = max(s for s, _ in best)
    cands = [c for s, c in best if s == top]
    if len(cands) > 1:
        with_iptv = [c for c in cands if any(s["service"] == "iptv" for s in c.get("services", []))]
        cands = with_iptv if len(with_iptv) == 1 else cands
    return cands[0] if len(cands) == 1 else None


def import_plan(b):
    customers, doubts = parse_subscriptions(b.get("abonnementer") or "")
    lines = parse_iptv(b["iptv"]) if (b.get("iptv") or "").strip() else []
    cockpit = parse_cockpit(b["cockpit"]) if (b.get("cockpit") or "").strip() else []
    today = now().date().isoformat()
    by_user = {}
    for c in customers:
        for l in c["iptv"]:
            by_user[l["username"].lower()] = (c, l)
    loose, past = [], []
    for l in lines:
        hit = by_user.get((l["username"] or "").lower()) if l["username"] else None
        if hit:
            c, tgt = hit
            tgt.update({k: l[k] for k in ("expires", "cost", "tivimate", "renew", "note")})
            tgt["label"] = l["label"] or tgt["label"]
            if l["password"] and not tgt["password"]:
                tgt["password"] = l["password"]
        else:
            c = _match_customer(l["label"], customers)
            if c:
                c["iptv"].append(dict(l))
            else:
                loose.append(dict(l))
                doubts.append(f"IPTV-linjen '{l['label']}' kunne ikke knyttes til en kunde – den lægges under 'Ingen kunde'")
        if l["expires"] < today and l["renew"]:
            past.append(l["label"])
    if past:
        doubts.append(f"{len(past)} IPTV-linjer har en udløbsdato i fortiden – ret datoen under IPTV-linjer, når de er fornyet: " + ", ".join(past))
    for c in customers:
        n_lines = len(c["iptv"])
        if any(s["service"] == "iptv" for s in c["services"]) and not n_lines:
            doubts.append(f"{c['name']}: betaler for IPTV, men har ingen linje")
        for l in c["iptv"]:
            if not l.get("expires"):
                doubts.append(f"{c['name']}: IPTV-linjen '{l['username']}' mangler udløbsdato (findes ikke på IPTV-fanen)")
    names = {norm(c["name"]) for c in customers}
    for r in cockpit:
        if norm(r["name"]) not in names:
            doubts.append(f"Cockpit: '{r['name']}' findes ikke på abonnement-fanen")
    return customers, loose, cockpit, doubts


def _plan_summary(customers, loose, cockpit, doubts):
    return {"customers": len(customers), "services": sum(len(c["services"]) for c in customers),
            "iptv": sum(len(c["iptv"]) for c in customers) + len(loose), "loose": len(loose), "cockpit": len(cockpit),
            "monthly": num(sum(sum(s["price"] for s in c["services"]) for c in customers if c["status"] == "aktiv")),
            "passwords": sum(1 for c in customers for s in c["services"] if s["password"]) + sum(1 for c in customers for l in c["iptv"] if l["password"]),
            "doubts": doubts,
            "preview": [{"name": c["name"], "freq": FREQ_DA.get(c["freq"], "?"), "cycle": cycle_text(c["freq"], c["cycle"]), "method": c["method"],
                         "services": service_names(c["services"]), "accounts": sum(1 for s in c["services"] if s["service"] == "plex"),
                         "iptv": len(c["iptv"]), "per_charge": num(sum(s["price"] for s in c["services"]) * FREQ.get(c["freq"], 0))} for c in customers]}


@router.post("/import/preview")
async def import_preview(req: Request):
    return _plan_summary(*import_plan(await req.json()))


@router.post("/import/apply")
async def import_apply(req: Request):
    b = await req.json()
    customers, loose, cockpit, doubts = import_plan(b)
    period = _valid_period(b.get("period") or cur_period())
    t = iso(now())
    made = upd = 0
    with _lock:
        con = D["db"]()
        try:
            with con:
                ids = {}
                existing = {norm(r["name"]): r["id"] for r in con.execute("SELECT id, name FROM k_customers").fetchall()}
                for c in customers:
                    cid = existing.get(norm(c["name"]))
                    vals = (c["name"], c["status"], c["kind"], c["method"], c["freq"], c["cycle"], c["due_day"], c["phone"], c["email"], c["contact"], c["notes"])
                    if cid:
                        con.execute("UPDATE k_customers SET name=?, status=?, kind=?, method=?, freq=?, cycle=?, due_day=?, phone=?, email=?, contact=?,"
                                    " notes=?, updated=? WHERE id=?", vals + (t, cid))
                        upd += 1
                    else:
                        cid = con.execute("INSERT INTO k_customers (name, status, kind, method, freq, cycle, due_day, phone, email, contact, notes, created, updated)"
                                          " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", vals + (t, t)).lastrowid
                        made += 1
                    ids[norm(c["name"])] = cid
                    have = [dict(r) for r in con.execute("SELECT * FROM k_services WHERE customer_id=?", (cid,)).fetchall()]
                    used = set()
                    for s in c["services"]:
                        same = [h for h in have if h["id"] not in used and h["service"] == s["service"]]
                        hit = next((h for h in same if s["username"] and (h["username"] or "").lower() == s["username"].lower()), None) \
                            or next((h for h in same if (h["label"] or "") == s["label"]), None) or (same[0] if len(same) == 1 else None)
                        if hit:
                            used.add(hit["id"])
                            con.execute("UPDATE k_services SET label=?, price=?, username=CASE WHEN ?='' THEN username ELSE ? END,"
                                        " email=CASE WHEN ?='' THEN email ELSE ? END, note=?, password=CASE WHEN ?='' THEN password ELSE ? END, active=1 WHERE id=?",
                                        (s["label"], s["price"], s["username"], s["username"], s["email"], s["email"], s["note"], s["password"], s["password"], hit["id"]))
                        else:
                            con.execute("INSERT INTO k_services (customer_id, service, label, price, username, email, password, note) VALUES (?,?,?,?,?,?,?,?)",
                                        (cid, s["service"], s["label"], s["price"], s["username"], s["email"], s["password"], s["note"]))
                    for l in c["iptv"]:
                        _import_line(con, cid, l)
                    if c["adjust"] and not con.execute("SELECT 1 FROM k_adjust WHERE customer_id=?", (cid,)).fetchone():
                        for a in c["adjust"]:
                            con.execute("INSERT INTO k_adjust (customer_id, amount, text, remaining, created) VALUES (?,?,?,1,?)", (cid, a["amount"], a["text"], t))
                for l in loose:
                    _import_line(con, None, l)
        finally:
            con.close()
    marked = 0
    if cockpit:
        ensure_charges(period)
        con = D["db"]()
        with con:
            for r in cockpit:
                cid = ids.get(norm(r["name"]))
                if not cid:
                    continue
                ch = con.execute("SELECT * FROM k_charges WHERE customer_id=? AND period=?", (cid, period)).fetchone()
                if not ch:
                    con.execute("INSERT INTO k_charges (customer_id, period, amount, base, detail, created) VALUES (?,?,?,?,?,?)",
                                (cid, period, r["amount"], r["amount"], json.dumps({"lines": [], "months": 0, "adjust": []}), t))
                    ch = con.execute("SELECT * FROM k_charges WHERE customer_id=? AND period=?", (cid, period)).fetchone()
                con.execute("UPDATE k_charges SET amount=CASE WHEN ?>0 THEN ? ELSE amount END, requested_at=CASE WHEN ? THEN COALESCE(requested_at, ?) ELSE requested_at END,"
                            " paid_at=CASE WHEN ? THEN COALESCE(paid_at, ?) ELSE paid_at END WHERE id=?",
                            (r["amount"], r["amount"], 1 if (r["requested"] or r["paid"]) else 0, t, 1 if r["paid"] else 0, t, ch["id"]))
                marked += 1
        con.close()
    D["kv_set"]("kunder_doubts", doubts)
    return {"created": made, "updated": upd, "marked": marked, "doubts": doubts}


def _import_line(con, cid, l):
    hit = con.execute("SELECT id FROM k_iptv WHERE username!='' AND lower(username)=?", ((l.get("username") or "").lower(),)).fetchone() if l.get("username") else None
    vals = (cid, l.get("label") or "", l.get("username") or "", l.get("expires"), float(l.get("cost") or 0), l.get("tivimate") or "", l.get("note") or "",
            1 if l.get("renew", 1) else 0)
    if hit:
        con.execute("UPDATE k_iptv SET customer_id=COALESCE(?, customer_id), label=?, username=?, expires=COALESCE(?, expires), cost=?, tivimate=?, note=?, renew=? WHERE id=?",
                    vals + (hit["id"],))
        lid = hit["id"]
    else:
        lid = con.execute("INSERT INTO k_iptv (customer_id, label, username, expires, cost, tivimate, note, renew) VALUES (?,?,?,?,?,?,?,?)", vals).lastrowid
    if l.get("password"):
        con.execute("UPDATE k_iptv SET password=? WHERE id=?", (l["password"], lid))


@router.post("/doubts/clear")
def doubts_clear():
    D["kv_set"]("kunder_doubts", [])
    return {"ok": True}


@router.get("/export.csv")
def export_csv():
    """Kundelisten uden kodeord – til eget overblik eller sikkerhedskopi."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Navn", "Status", "Type", "Betalingsmetode", "Frekvens", "Cyklus", "Fast dato", "Pr. måned", "Pr. opkrævning", "Tjenester",
                "Telefon", "E-mail", "Kontakt", "Noter"])
    for c in customers_out():
        w.writerow([c["name"], c["status"], c["kind"], c["method"], c["freq_text"], c["cycle_text"], c["due_day"] or "", c["monthly"], c["per_charge"],
                    ", ".join(f"{SERVICE_DA.get(s['service'], s['service'])}{' (' + s['label'] + ')' if s['label'] else ''} {s['price']}" for s in c["services"]),
                    c["phone"], c["email"], c["contact"], c["notes"]])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="kunder-{now():%Y-%m-%d}.csv"', "Cache-Control": "no-store"})
