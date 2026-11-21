"""Køb i guiden – "Få flere ønsker" (Fangarr 1.25.0).

Kunden vælger selv pakke, skifter, stopper eller køber enkelte film og sæsoner i guiden (guide.stream365.vip).
Reglerne er de samme som på kundekortet (app/oensker.py): større pakke virker med det samme med tillæg pr. dag til
næste betaling, mindre pakke eller stop fra næste betaling, enkeltkøb lægges på næste betaling. Fangarr retter Seerr selv.

Sådan hænger det sammen:
- Guiden (appen nyt) spørger Fangarr inde i Docker-netværket på /api/kob/... og sender en hemmelig nøgle med
  (NYT_TOKEN i fangarr.env = filen /opt/nyt/data/fangarr_token hos guiden). Uden nøgle findes adresserne ikke (404).
- Guiden sender kun Plex-id og brugernavn på den kunde, der er logget ind. Fangarr finder selv kunden via Plex-kontoen
  på kundekortet. Telefon, e-mail og koder sendes aldrig til guiden – kun kundens egne ønsker, pakke og næste betaling.
- Køb er kun åbent, når det er slået til under Kunder › Seerr-ønsker › Indstillinger, og styringen af Seerr står på Til.
- Hvert valg giver en besked til Stream365 Drift (navn, hvad, beløb – aldrig telefon eller e-mail) og en linje i loggen.
"""
import datetime
import hmac
import os
import threading
import time

from fastapi import APIRouter, HTTPException, Request

from . import oensker

router = APIRouter(prefix="/api/kob")
D = {}   # udfyldes af main.py: telegram, log
TOKEN = (os.environ.get("NYT_TOKEN") or "").strip()
TOKEN_MIN = 32
MAX_UNITS = 30          # højst så mange film og sæsoner pr. køb (kunden kan købe igen)
_rate = {}
_rate_lock = threading.Lock()


def setup(**deps):
    D.update(deps)


def token_ok():
    return len(TOKEN) >= TOKEN_MIN


def is_open():
    s = oensker.settings()
    return bool(token_ok() and s.get("shop") and s.get("mode") == "til" and oensker.enabled())


def info():
    """Til guiden (via nyhedshentningen) og Fangarrs indstillinger."""
    s = oensker.settings()
    return {"open": is_open(), "section": s.get("shop_section") or "", "label": "Få flere ønsker", "token": token_ok(),
            "setting": bool(s.get("shop")), "mode": s.get("mode")}


def _check(req: Request):
    t = req.headers.get("x-nyt-token") or ""
    if not token_ok() or not hmac.compare_digest(t.encode(), TOKEN.encode()):
        raise HTTPException(404, "Not Found")


def _rate_ok(uid, n=8, secs=600):
    now = time.time()
    with _rate_lock:
        ts = [t for t in _rate.get(uid, []) if now - t < secs]
        ok = len(ts) < n
        if ok:
            ts.append(now)
        _rate[uid] = ts
        return ok


def _who(uid):
    """Kunden bag Plex-kontoen: (kunde, konto) – eller (None, None)."""
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return None, None
    r = oensker.one("SELECT customer_id FROM k_services WHERE service='plex' AND active=1 AND plex_user_id=? ORDER BY id LIMIT 1", (uid,))
    if not r:
        return None, None
    c = oensker.one("SELECT * FROM k_customers WHERE id=?", (r["customer_id"],))
    if not c:
        return None, None
    acc = next((a for a in oensker._accounts(c["id"]) if a["plex_user_id"] == uid), None)
    return c, acc


def _cycle_text(n):
    return {1: "hver måned", 3: "hvert kvartal", 6: "hvert halve år", 12: "en gang om året"}.get(n, f"hver {n}. måned")


def _period_word(n):
    return {1: "måned", 3: "kvartal", 6: "halvår", 12: "år"}.get(n, f"{n} måneder")


def _period_phrase(n):
    return {1: "hver måned", 3: "for kvartalet", 6: "for halvåret", 12: "for året"}.get(n, f"for {n} måneder")


def _state(uid):
    c, acc = _who(uid)
    s = oensker.settings()
    pk = oensker.packages()
    out = {"open": is_open(), "status": "kunde", "packages": [{"key": p["key"], "name": p["name"], "price": p["price"], "film": p["film"], "tv": p["tv"]}
                                                              for p in pk.values()],
           "price_film": s["price_film"], "price_tv": s["price_tv"], "max_units": MAX_UNITS, "seerr": "https://seerr.stream365.vip"}
    if not out["open"]:
        out["status"] = "lukket"
        return out, c, acc
    if not c or not acc:
        out["status"] = "ukendt"
        return out, c, acc
    if c["kind"] == "egen":
        out["status"] = "familie"
        return out, c, acc
    if c["status"] != "aktiv":
        out["status"] = "stoppet"
        return out, c, acc
    nxt = oensker.next_payment(c)
    if not nxt:
        out["status"] = "ingen_betaling"
        return out, c, acc
    pid = acc["plex_user_id"]
    row = oensker.one("SELECT * FROM s_pkg WHERE plex_user_id=?", (pid,))
    p = pk.get(row["package"]) if row else None
    cr = oensker.credits(pid)
    st = oensker.D["kv_get"]("oensker_state", {}) or {}
    in_seerr = set(st.get("in_seerr") or [])
    n = oensker._months(c)
    pend = None
    if row and row["pending"] is not None:
        try:
            pdate = oensker._day(datetime.date.fromisoformat(str(row["pending_date"])[:10]))
        except ValueError:
            pdate = str(row["pending_date"] or "")
        pend = {"to": row["pending"], "name": pk[row["pending"]]["name"] if row["pending"] in pk else "", "date": pdate}
    out.update({
        "name": acc["name"], "package": ({"key": p["key"], "name": p["name"], "film": p["film"], "tv": p["tv"], "price": p["price"]} if p else None),
        "pending": pend, "credits": {"film": cr["film"]["unused"], "tv": cr["tv"]["unused"]},
        "in_seerr": (pid in in_seerr) if st.get("at") and not st.get("error") else None,
        "months": n, "cycle": _cycle_text(n), "period_word": _period_word(n),
        "next": {"date": nxt["date"].isoformat(), "text": oensker._day(nxt["date"])},
    })
    return out, c, acc


def _quote(c, acc, b):
    """Kundens udgave af beregningen: korte linjer med beløb, der kan vises i guiden."""
    pk = oensker.packages()
    pid = acc["plex_user_id"]
    if b.get("what") == "buy":
        film, tv = _units(b.get("film")), _units(b.get("tv"))
        if not film and not tv:
            raise HTTPException(400, "Vælg mindst én film eller sæson.")
        q = oensker.quote_buy(c["id"], pid, film, tv)
        lines = [{"text": oensker._units(film, tv) + " – betales én gang", "amount": q["amount"]}]
        return {"kind": "buy", "lines": lines, "next_text": q["next_text"], "next_amount": q["next_amount"], "film": film, "tv": tv,
                "summary": f"Du kan ønske {oensker._units(film, tv)} mere i Seerr. Ønskerne udløber aldrig.",
                "button": f"Køb for {oensker._kr(q['amount'])}", "amount": q["amount"]}
    target = str(b.get("package") or "")
    if target and target not in pk:
        raise HTTPException(400, "Den pakke findes ikke.")
    q = oensker.quote_package(c["id"], pid, target)
    n, nm = q["months"], (pk[target]["name"] if target else "")
    lines, summary, button = [], "", ""
    if q["kind"] == "samme":
        summary = "Det er din pakke nu." if target else "Du har ingen pakke."
    elif q["kind"] == "fortryd":
        summary = f"Det planlagte skift fortrydes – du beholder {pk[q['from']]['name'] if q['from'] else 'ingen pakke'}."
        button = "Fortryd skiftet"
    elif q["kind"] in ("nu", "kobl"):
        if q["add"]:
            lines.append({"text": f"Tillæg for {q['days']} dage indtil næste betaling", "amount": q["add"]})
        lines.append({"text": f"{nm} {_period_phrase(n)} fra {q['next_text']}", "amount": q["period_amount"]})
        p = pk[target]
        summary = f"Virker med det samme: {oensker._units(int(p['film']), int(p['tv']))} pr. 30 dage."
        button = f"Vælg {nm}"
    else:   # senere: mindre pakke eller stop
        cur = pk[q["from"]]["name"] if q["from"] in pk else "din pakke"
        if target:
            lines.append({"text": f"{nm} {_period_phrase(n)} fra {q['next_text']}", "amount": q["period_amount"]})
            summary = f"Du beholder {cur} til {q['next_text']}. Derefter {nm}."
            button = f"Skift til {nm}"
        else:
            summary = f"Du beholder {cur} til {q['next_text']}. Derefter stopper pakken, og du betaler ikke mere for den."
            button = "Stop pakken"
    return {"kind": q["kind"], "lines": lines, "next_text": q["next_text"], "next_amount": q["next_amount"], "package": target,
            "summary": summary, "button": button}


def _units(v):
    try:
        v = int(v or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "Antal skal være et helt tal.") from None
    if v < 0 or v > MAX_UNITS:
        raise HTTPException(400, f"Du kan købe op til {MAX_UNITS} ad gangen.")
    return v


def _ready(b):
    out, c, acc = _state(b.get("uid"))
    if out["status"] != "kunde":
        msg = {"lukket": "Køb i guiden er lukket lige nu.", "ukendt": "Vi kan ikke finde din konto. Skriv til os, så hjælper vi.",
               "familie": "Du kan allerede ønske alt, du vil – gratis.", "stoppet": "Dit abonnement er ikke aktivt. Skriv til os.",
               "ingen_betaling": "Vi kan ikke se din næste betaling. Skriv til os, så hjælper vi."}[out["status"]]
        raise HTTPException(409, msg)
    return out, c, acc


@router.post("/mig")
async def mig(req: Request):
    _check(req)
    b = await req.json()
    out, _, _ = _state(b.get("uid"))
    return out


def _safe_quote(c, acc, b):
    """Beregningen – fejl med intern tekst (til dig) bliver til en venlig besked til kunden."""
    try:
        return _quote(c, acc, b)
    except HTTPException as e:
        own = e.status_code == 400 and str(e.detail)[:1].isupper()   # kob.py's egne beskeder er skrevet til kunden
        if not own:
            D["log"].warning("Køb i guiden: beregning fejlede for %s: %s", acc["name"], e.detail)
        raise HTTPException(400, e.detail if own else "Det kan ikke lade sig gøre lige nu. Skriv til os, så hjælper vi.") from None


@router.post("/tilbud")
async def tilbud(req: Request):
    _check(req)
    b = await req.json()
    _, c, acc = _ready(b)
    return _safe_quote(c, acc, b)


@router.post("/vaelg")
async def vaelg(req: Request):
    _check(req)
    b = await req.json()
    st, c, acc = _ready(b)
    uid = str(b.get("uid"))
    if not _rate_ok(uid):
        raise HTTPException(429, "Du har lavet mange ændringer på kort tid. Prøv igen om lidt.")
    q = _safe_quote(c, acc, b)
    if q["kind"] == "samme":
        raise HTTPException(400, "Det er allerede din pakke.")
    if b.get("expect") is not None and abs(float(b.get("expect") or 0) - float(q["next_amount"])) > 0.5:
        raise HTTPException(409, "Prisen er ændret, siden du åbnede siden. Se den nye pris, og prøv igen.")
    pid = acc["plex_user_id"]
    try:
        if q["kind"] == "buy":
            oensker.buy(c["id"], pid, q["film"], q["tv"], source="guiden")
            what = f"købte {oensker._units(q['film'], q['tv'])} for {oensker._kr(q['amount'])}"
        else:
            oensker.set_package(c["id"], pid, q["package"], source="guiden")
            pk = oensker.packages()
            what = {"nu": f"valgte {pk[q['package']]['name']}" if q["package"] else "", "kobl": f"valgte {pk[q['package']]['name']}" if q["package"] else "",
                    "senere": (f"skifter til {pk[q['package']]['name']} fra {q['next_text']}" if q["package"] else f"stopper pakken fra {q['next_text']}"),
                    "fortryd": "fortrød sit planlagte skift"}.get(q["kind"], "ændrede sin pakke")
            add = sum(float(x["amount"]) for x in q["lines"] if x["text"].startswith("Tillæg"))
            if add:
                what += f" – tillæg {oensker._kr(add)}"
    except HTTPException as e:
        D["log"].warning("Køb i guiden fejlede for %s: %s", acc["name"], e.detail)
        raise HTTPException(400, "Det kan ikke lade sig gøre lige nu. Skriv til os, så hjælper vi.") from None
    msg = f"🛒 Køb i guiden: {c['name']}" + (f" ({acc['name']})" if acc["name"] != c["name"] else "") + \
          f" {what}. Næste betaling {q['next_text']}: {oensker._kr(q['next_amount'])}."
    D["log"].info("Køb i guiden: %s %s", acc["name"], what)
    if D.get("telegram"):
        try:
            D["telegram"](msg)
        except Exception:
            pass
    done = {"buy": "Tak! Ønskerne er lagt på.", "nu": "Tak! Pakken virker nu.", "kobl": "Tak! Pakken virker nu.",
            "senere": "Tak! Ændringen er gemt.", "fortryd": "Skiftet er fortrudt."}.get(q["kind"], "Tak!")
    sub = q["summary"] + (f" Beløbet kommer med på din næste betaling {q['next_text']}." if q["kind"] in ("buy", "nu", "kobl") else "")
    return {"ok": True, "title": done, "text": sub, "state": _state(b.get("uid"))[0]}
