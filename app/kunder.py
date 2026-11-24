"""Kunder og betalinger (Fangarr 1.16.0).

Holder styr på kunder, deres tjenester, opkrævninger, IPTV-linjer og logins.
Plex-brugere hentes fra Tautulli (hver nat og med knappen "Synk fra Tautulli").

Vigtigt:
- Kodeord og IPTV-koder ligger kun i databasen (/config/fangarr.db). De sendes aldrig med i lister,
  i loggen, i Telegram-beskeder eller i Fangarrs eksport – kun når du trykker "Vis".
- Fangarr sender ingen beskeder til kunderne og spærrer ingen. Du får kun besked på Stream365 Drift.
"""
import calendar
import csv
import datetime
import io
import json
import re
import threading
import uuid
import unicodedata

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

router = APIRouter(prefix="/api/kunder")
D = {}   # udfyldes af main.py: db, telegram, tautulli, tautulli_enabled, now, kv_get, kv_set, log, before_charge

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
    "pay_days": 7,             # {frist} i beskeden til kunden: så mange dage har kunden til at betale, fra beskeden sendes
    "inactive_days": 60,       # mærket "ikke set længe" på kunden
    "plex_price": 120,         # pris pr. måned for en ny Plex-konto fra Tautulli
    "message_hour": 8,         # klokkeslæt for beskeder på Stream365 Drift
    "sync_hour": 3,            # natlig synk fra Tautulli
    "fixed_costs": "",         # faste udgifter pr. måned, én pr. linje: "Hetzner: 2813"
    "template": ("Hej {fornavn}! 👋\n\nHermed opkrævning for dine tjenester ({tjenester}):\n"
                 "💰 Beløb: {beløb} kr. for {antal_måneder}\n📆 Dækker: {periode}\n{rabatter}\n{betaling}\n"
                 "⏰ Betales senest: {frist}\n\nNæste opkrævning: {næste}\n\n{nyhed}\n\n"
                 "Sig endelig til hvis der er noget. Rigtig god fornøjelse! 🍿"),
    # linjen {betaling} i beskeden – én tekst pr. måde, du anmoder på (1.19.0)
    "pay_link_text": "💳 Betal nemt med kort her: {link}",
    "pay_revolut_text": "💳 Jeg har sendt dig en anmodning i Revolut-appen.",
    "pay_mobilepay_text": "💳 Jeg har sendt dig en anmodning i MobilePay.",
    "pay_other_text": "💳 Betales via: {metode}",
    # Android-pakkenavn på dine apps (1.19.2) – kun nødvendigt for patchede/uofficielle udgaver. Tomt = Android vælger selv.
    "app_tg_pkg": "",
    "app_fb_pkg": "",
}
OLD_TEMPLATE = ("Hej {fornavn}! 👋\n\nHermed opkrævning for dine tjenester ({tjenester}):\n"
                "💰 Beløb: {beløb} kr. ({frekvens} • Cyklus: {cyklus})\n💳 Betales via: {metode}\n\n"
                "Sig endelig til hvis der er noget. Rigtig god fornøjelse! 🍿")   # standardteksten før 1.19.0
OLD_TEMPLATE_119 = ("Hej {fornavn}! 👋\n\nHermed opkrævning for dine tjenester ({tjenester}):\n"
                    "💰 Beløb: {beløb} kr. ({frekvens} • Cyklus: {cyklus})\n{rabatter}\n{betaling}\n\n{nyhed}\n\n"
                    "Sig endelig til hvis der er noget. Rigtig god fornøjelse! 🍿")   # standardteksten 1.19.0 – 1.20.2
PAY_TEXTS = ("pay_link_text", "pay_revolut_text", "pay_mobilepay_text", "pay_other_text")
REVOLUT = ("", "link", "app")   # sådan anmoder du en Revolut-kunde: ikke valgt · betalingslink · direkte i appen
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
        # 1.19.0 – Send besked: Telegram/Messenger på kunden, betalingslink og nyhed på opkrævningen
        for table, col in (("k_customers", "tg TEXT DEFAULT ''"), ("k_customers", "fb TEXT DEFAULT ''"), ("k_customers", "revolut TEXT DEFAULT ''"),
                           ("k_charges", "pay_link TEXT DEFAULT ''"), ("k_charges", "news_id TEXT DEFAULT ''"), ("k_charges", "sent_at TEXT")):
            have = {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
            if col.split(" ")[0] not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
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
    if s["template"].strip() in (OLD_TEMPLATE, OLD_TEMPLATE_119):      # en gammel standardtekst afløses af den nyeste
        s["template"] = DEFAULTS["template"]
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


def news():
    """Den fælles nyhed, der flettes ind i beskederne med {nyhed}. Tom tekst = ingen nyhed."""
    n = D["kv_get"]("kunder_news", {}) or {}
    return n if str(n.get("text") or "").strip() and n.get("id") else None


def news_due(cid, chid, nw=None):
    """Skal kunden have nyheden med i denne besked? Ja, indtil den er sendt med én af kundens opkrævninger.
    Samme opkrævning tæller ikke, så beskeden kan sendes igen med nyheden i."""
    nw = nw or news()
    if not nw:
        return False
    return not one("SELECT id FROM k_charges WHERE customer_id=? AND news_id=? AND id!=?", (cid, nw["id"], chid or 0))


def pay_variants(c):
    """Hvilke tekster kan stå på linjen {betaling} for denne kunde?"""
    m = norm(c["method"])
    if m == "revolut":
        return ["link", "app"]
    if m == "mobilepay":
        return ["mobilepay"]
    return ["other"]


def _amount(v):
    """1314 -> '1.314' · 49.5 -> '49,50' (dansk skrivemåde til beskeden)."""
    v = num(v)
    return f"{v:,}".replace(",", ".") if isinstance(v, int) else f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def adjust_lines(adjust):
    out = []
    for a in adjust or []:
        amt = float(a.get("amount") or 0)
        if not amt:
            continue
        txt = str(a.get("text") or "").strip() or ("Rabat" if amt < 0 else "Tillæg")
        out.append(f"{'🎁' if amt < 0 else '➕'} {txt}: {'+' if amt > 0 else '-'}{_amount(abs(amt))} kr.")
    return "\n".join(out)


def _due_date(due_day, period):
    """Betalingsdatoen som dato: kundens faste dato i måneden (ellers den 1.), aldrig senere end månedens sidste dag."""
    y, m = int(period[:4]), int(period[5:7])
    try:
        d = int(due_day or 1)
    except (TypeError, ValueError):
        d = 1
    return datetime.date(y, m, min(max(d, 1), calendar.monthrange(y, m)[1]))


def _add_months(period, n):
    i = int(period[:4]) * 12 + int(period[5:7]) - 1 + n
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def _day_text(d, year=None):
    """24. november – med årstal, når det ikke er i år (eller når year=True)."""
    show = year if isinstance(year, bool) else d.year != now().year
    return f"{d.day}. {MONTHS_DA[d.month - 1]}" + (f" {d.year}" if show else "")


def covers_text(start, end):
    """Hvad betalingen dækker: fra betalingsdatoen til dagen før den næste. Hele måneder skrives uden dage."""
    whole = start.day == 1 and end.day == calendar.monthrange(end.year, end.month)[1]
    if whole:
        a, b = MONTHS_DA[start.month - 1], MONTHS_DA[end.month - 1]
        if (start.year, start.month) == (end.year, end.month):
            return f"{a} {start.year}"
        return f"{a} – {b} {end.year}" if start.year == end.year else f"{a} {start.year} – {b} {end.year}"
    return f"{_day_text(start, start.year != end.year)} – {_day_text(end, True)}"


def next_amount(c, months):
    """Forventet beløb ved næste opkrævning: kundens nuværende priser + de fradrag/tillæg, der stadig har gange tilbage."""
    sv = rows("SELECT * FROM k_services WHERE customer_id=?", (c["id"],))
    adj = rows("SELECT amount FROM k_adjust WHERE customer_id=? AND remaining>0", (c["id"],))
    return max(0.0, monthly(sv) * months + sum(float(a["amount"] or 0) for a in adj))


def months_text(n):
    return "1 måned" if n == 1 else f"{n} måneder"


def date_fields(c, ch, det):
    """Felterne {frist}, {periode}, {næste} og {antal_måneder} for én opkrævning.
    Fristen tælles fra den dag, beskeden blev sendt – er den ikke sendt endnu, fra i dag – men ligger aldrig før
    kundens betalingsdato (sendes beskeden den 17. til en kunde med fast dato den 25., er fristen den 25.)."""
    n = int(det.get("months") or FREQ.get(c["freq"]) or 0)
    period = ch["period"][:7]
    try:
        base = datetime.datetime.fromisoformat(ch["sent_at"]).date() if ch["sent_at"] else now().date()
    except (TypeError, ValueError):
        base = now().date()
    frist = base + datetime.timedelta(days=int(settings()["pay_days"]))
    out = {"frist": _day_text(frist), "antal_måneder": months_text(n) if n else "–", "periode": "–", "næste": "–"}
    if n:
        start, nxt = _due_date(c["due_day"], period), _due_date(c["due_day"], _add_months(period, n))
        out["frist"] = _day_text(max(frist, start))      # aldrig før kundens egen betalingsdato
        out["periode"] = covers_text(start, nxt - datetime.timedelta(days=1))
        out["næste"] = _day_text(nxt, True)
        if c["status"] == "aktiv" and FREQ.get(c["freq"]):
            exp = next_amount(c, FREQ[c["freq"]])
            if abs(exp - float(ch["amount"] or 0)) >= 0.005:      # kun når beløbet bliver et andet end denne gang
                out["næste"] += f" (forventet {_amount(exp)} kr.)"
    return out


_OPTIONAL = ("rabatter", "betaling", "nyhed")


def message_for(c, amount, lines, adjust=None, variant="other", news_text="", extra=None):
    """Beskeden til kunden. {link} bliver stående – det sættes ind i browseren, når du har indsat betalingslinket.
    En linje, der kun består af {rabatter}, {betaling} eller {nyhed}, forsvinder, når feltet er tomt."""
    s = settings()
    key = {"link": "pay_link_text", "app": "pay_revolut_text", "mobilepay": "pay_mobilepay_text"}.get(variant, "pay_other_text")
    vals = {"fornavn": (c["name"] or "").split(" ")[0], "navn": c["name"] or "", "tjenester": service_names(lines) or "–",
            "beløb": _amount(amount), "frekvens": FREQ_DA.get(c["freq"], "–"),
            "cyklus": cycle_text(c["freq"], c["cycle"]), "metode": c["method"] or "–"}
    vals.update({"frist": "–", "periode": "–", "næste": "–", "antal_måneder": months_text(FREQ[c["freq"]]) if FREQ.get(c["freq"]) else "–"})
    vals.update(extra or {})
    vals.update({"rabatter": adjust_lines(adjust), "betaling": str(s.get(key) or "").strip(), "nyhed": str(news_text or "").strip()})
    out = []
    for line in s["template"].split("\n"):
        if any("{" + k + "}" in line for k in _OPTIONAL):
            bare = line
            for k in _OPTIONAL:
                bare = bare.replace("{" + k + "}", vals[k])
            if not bare.strip():
                continue
        out.append(line)
    txt = "\n".join(out)
    for k in _OPTIONAL:                 # først de tre, så felter inde i dem (fx {metode}) også bliver udfyldt
        txt = txt.replace("{" + k + "}", vals[k])
    for k, v in vals.items():
        txt = txt.replace("{" + k + "}", str(v))
    return re.sub(r"\n{3,}", "\n\n", txt).strip()


def messages_for(c, ch, det, nw=None):
    """Alle udgaver af beskeden for én opkrævning – én pr. måde at anmode på."""
    txt = nw["text"] if nw and news_due(c["id"], ch["id"], nw) else ""
    extra = date_fields(c, ch, det)
    return {v: message_for(c, ch["amount"], det.get("lines", []), det.get("adjust", []), v, txt, extra) for v in pay_variants(c)}, bool(txt)


def handle(v, kind):
    """Ryd op i et brugernavn: '@navn', 'https://t.me/navn' og 'facebook.com/navn' bliver til 'navn'."""
    v = str(v or "").strip()
    if kind == "tg":
        v = re.sub(r"^(https?://)?(t\.me|telegram\.me)/", "", v, flags=re.I).lstrip("@").split("?")[0]
        return v if re.fullmatch(r"\+?[\d ]{6,20}|[A-Za-z][A-Za-z0-9_]{3,31}", v) else ""
    m = re.search(r"profile\.php\?id=(\d+)", v)
    if m:
        return m.group(1)
    v = re.sub(r"^(https?://)?((www|m|web)\.)?(facebook\.com|messenger\.com/t|m\.me)/", "", v, flags=re.I).lstrip("@").split("?")[0].strip("/")
    return v if re.fullmatch(r"[A-Za-z0-9.\-]{2,60}", v) else ""


def channel(c):
    """Hvor skrives der med kunden? Læses af 'Kontakt via' (FB, TG …), ellers af hvilket brugernavn der er udfyldt."""
    k = norm(c.get("contact"))
    if k.startswith(("fb", "messenger", "facebook")):
        return "messenger"
    if k.startswith(("tg", "telegram")):
        return "telegram"
    if c.get("tg") and not c.get("fb"):
        return "telegram"
    if c.get("fb") and not c.get("tg"):
        return "messenger"
    return ""


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
                    if D.get("before_charge"):      # Seerr-ønsker (1.23.0): planlagt skift til mindre pakke eller stop
                        D["before_charge"](con, dict(c), period)
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


def snoozed():
    """2.1.0: "Udsæt en uge" fra Telegram – {charge_id: dato}. Udsatte opkrævninger er ikke med i påmindelserne før datoen."""
    today = now().date().isoformat()
    return {int(k): v for k, v in (D["kv_get"]("kunder_snooze", {}) or {}).items() if v > today}


def overdue_list(skip_snoozed=False):
    rd = int(settings()["remind_days"])
    limit = iso(now() - datetime.timedelta(days=rd))
    if skip_snoozed:
        sz = snoozed()
        return [r for r in overdue_list() if r["id"] not in sz]
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


def _contact_fields(b, o):
    out = {}
    for k in ("tg", "fb"):
        raw = str(b.get(k, o.get(k, "")) or "").strip()
        out[k] = handle(raw, k)
        if raw and not out[k]:
            raise HTTPException(400, "Telegram: skriv brugernavnet (fx @navn) eller telefonnummeret" if k == "tg"
                                else "Messenger: skriv det, der står efter facebook.com/ på kundens profil")
    rv = str(b.get("revolut", o.get("revolut", "")) or "")
    out["revolut"] = rv if rv in REVOLUT else ""
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
            "notes": str(b.get("notes", o.get("notes", "")) or "").strip(), **_contact_fields(b, o)}


def add_customer(d):
    return run("INSERT INTO k_customers (name, status, kind, method, freq, cycle, due_day, phone, email, contact, notes, tg, fb, revolut, created, updated)"
               " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (d["name"], d["status"], d["kind"], d["method"], d["freq"], d["cycle"], d["due_day"], d["phone"], d["email"], d["contact"],
                d["notes"], d.get("tg", ""), d.get("fb", ""), d.get("revolut", ""), iso(now()), iso(now())))


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


def news_out():
    nw = news()
    if not nw:
        return None
    total = one("SELECT COUNT(*) n FROM k_customers WHERE status='aktiv' AND kind='kunde' AND freq IS NOT NULL")["n"]
    sent = one("SELECT COUNT(DISTINCT customer_id) n FROM k_charges WHERE news_id=?", (nw["id"],))["n"]
    return {"id": nw["id"], "text": nw["text"], "created": nw.get("created"), "sent": sent, "total": total}


@router.put("/news")
async def news_put(req: Request):
    """Gem den fælles nyhed. 'fresh' giver den et nyt nummer, så alle kunder får den igen."""
    b = await req.json()
    text = str(b.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "skriv nyheden – eller tryk Fjern for at stoppe den")
    if len(text) > 1500:
        raise HTTPException(400, "nyheden er for lang (højst 1.500 tegn) – så kan beskeden ikke åbnes i Telegram")
    old = news()
    if old and not b.get("fresh"):
        nw = {**old, "text": text}
    else:
        nw = {"id": uuid.uuid4().hex[:12], "text": text, "created": iso(now())}
    D["kv_set"]("kunder_news", nw)
    return news_out()


@router.delete("/news")
def news_delete():
    D["kv_set"]("kunder_news", {})
    return None


@router.get("/state")
def state():
    return {"settings": settings(), "services": SERVICES, "freq": FREQ_DA, "period": cur_period(), "news": news_out(),
            "tautulli": D["tautulli_enabled"](), "sync": D["kv_get"]("kunder_sync"),
            "plex_free": [p for p in rows("SELECT user_id, username, friendly_name FROM k_plex WHERE active=1 AND user_id NOT IN"
                                          " (SELECT plex_user_id FROM k_services WHERE plex_user_id IS NOT NULL) ORDER BY friendly_name")]}


@router.put("/settings")
async def put_settings(req: Request):
    b = await req.json()
    s = settings()
    for k in ("remind_days", "remind_repeat_days", "pay_days", "inactive_days", "message_hour", "sync_hour"):
        if k in b:
            try:
                s[k] = max(0, int(b[k]))
            except (TypeError, ValueError):
                raise HTTPException(400, f"{k} skal være et helt tal")
    if "plex_price" in b:
        s["plex_price"] = num(money(b["plex_price"]))
    for k in ("fixed_costs", "template") + PAY_TEXTS:
        if k in b:
            s[k] = str(b[k])
    for k in PAY_TEXTS:
        if not s[k].strip():
            s[k] = DEFAULTS[k]
    for k in ("app_tg_pkg", "app_fb_pkg"):
        if k in b:
            v = str(b[k] or "").strip()
            if v and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+", v):
                raise HTTPException(400, "pakkenavnet skal ligne com.noget.noget (kun bogstaver, tal og punktummer)")
            s[k] = v
    if not s["template"].strip():
        s["template"] = DEFAULTS["template"]
    D["kv_set"]("kunder_settings", s)
    return settings()


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
    run("UPDATE k_customers SET name=?, status=?, kind=?, method=?, freq=?, cycle=?, due_day=?, phone=?, email=?, contact=?, notes=?, tg=?, fb=?,"
        " revolut=?, updated=? WHERE id=?", (d["name"], d["status"], d["kind"], d["method"], d["freq"], d["cycle"], d["due_day"], d["phone"],
                                             d["email"], d["contact"], d["notes"], d["tg"], d["fb"], d["revolut"], iso(now()), cid))
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


def due_in(due_day, period):
    """Betalingsdatoen i måneden: kundens faste dato, ellers den 1. En dato, måneden ikke har (fx 31. i en måned med
    30 dage), bliver til månedens sidste dag."""
    last = calendar.monthrange(int(period[:4]), int(period[5:7]))[1]
    try:
        d = int(due_day or 1)
    except (TypeError, ValueError):
        d = 1
    return min(max(d, 1), last)


def charges_for(period):
    cur = cur_period()
    rd = int(settings()["remind_days"])
    if period == cur:
        ensure_charges(period)
    cust = {c["id"]: c for c in rows("SELECT * FROM k_customers")}
    out = []
    nw = news()
    for r in rows("SELECT * FROM k_charges WHERE period=?", (period,)):
        c = cust.get(r["customer_id"])
        if not c:
            continue
        det = json.loads(r["detail"] or "{}")
        st, late = charge_status(r, rd)
        msgs, has_news = messages_for(c, r, det, nw)
        variant = (c["revolut"] if c["revolut"] in msgs else "") if len(msgs) > 1 else next(iter(msgs))
        out.append({"id": r["id"], "customer_id": c["id"], "name": c["name"], "amount": num(r["amount"]), "base": num(r["base"]),
                    "messages": msgs, "variant": variant, "news": has_news, "channel": channel(c), "tg": c["tg"], "fb": c["fb"],
                    "pay_link": r["pay_link"] or "", "sent_at": r["sent_at"],
                    "lines": det.get("lines", []), "adjust": det.get("adjust", []), "services": service_names(det.get("lines", [])),
                    "method": c["method"], "status": st, "late": late, "requested_at": r["requested_at"], "paid_at": r["paid_at"],
                    "note": r["note"], "due_day": c["due_day"], "due": due_in(c["due_day"], period), "contact": c["contact"], "phone": c["phone"],
                    "message": msgs.get(variant) or next(iter(msgs.values()))})
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
                            "status": "kommer", "late": False, "requested_at": None, "paid_at": None, "note": "", "due_day": c["due_day"], "due": due_in(c["due_day"], period),
                            "contact": c["contact"], "phone": c["phone"], "message": ""})
    out.sort(key=lambda x: norm(x["name"]))
    return {"period": period, "current": cur, "preview": preview, "prev": _prev_next(period, -1), "next": _prev_next(period, 1),
            "today": now().day if period == cur else None,
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
    elif a == "sent":          # beskeden er sendt (Telegram, Messenger, Del eller Kopiér): sæt Anmodet, gem linket og husk nyheden
        c = one("SELECT * FROM k_customers WHERE id=?", (ch["customer_id"],))
        variant = str(b.get("variant") or "")
        if not c or variant not in pay_variants(c):
            raise HTTPException(400, "vælg, hvordan du anmoder kunden")
        link = str(b.get("link") or "").strip()
        if variant == "link":
            if not re.fullmatch(r"https://[^\s<>\"']{4,500}", link):
                raise HTTPException(400, "indsæt betalingslinket fra Revolut (det skal begynde med https://)")
            run("UPDATE k_charges SET pay_link=? WHERE id=?", (link, chid))
        if variant in ("link", "app") and c["revolut"] != variant:
            run("UPDATE k_customers SET revolut=? WHERE id=?", (variant, c["id"]))      # husk valget til næste gang
        nw = news()
        if nw and b.get("news") and news_due(c["id"], chid, nw):
            run("UPDATE k_charges SET news_id=? WHERE id=?", (nw["id"], chid))
        run("UPDATE k_charges SET requested_at=COALESCE(requested_at, ?), sent_at=?, skipped=0 WHERE id=?", (t, t, chid))
    elif a == "unrequest":
        run("UPDATE k_charges SET requested_at=NULL, sent_at=NULL, news_id='' WHERE id=?", (chid,))
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
        recalc_charge(chid)
    else:
        raise HTTPException(400, "ukendt handling")
    return charges_for(ch["period"][:7])


def recalc_charge(chid):
    """Regn grundbeløbet om ud fra kundens nuværende priser; fradrag og tillæg bevares (også brugt af Ændring for alle, 2.2.0)."""
    ch = one("SELECT * FROM k_charges WHERE id=?", (chid,))
    c = one("SELECT * FROM k_customers WHERE id=?", (ch["customer_id"],)) if ch else None
    if not ch or not c:
        return
    sv = rows("SELECT * FROM k_services WHERE customer_id=?", (ch["customer_id"],))
    det = json.loads(ch["detail"] or "{}")
    n = FREQ.get(c["freq"], det.get("months") or 0)
    base = monthly(sv) * n
    det.update({"lines": service_lines(sv), "months": n})
    amount = max(0.0, base + sum(x["amount"] for x in det.get("adjust", [])))
    run("UPDATE k_charges SET amount=?, base=?, detail=? WHERE id=?", (amount, base, json.dumps(det, ensure_ascii=False), chid))


# ---------------------------------------------------------------- knapper i Stream365 Drift (2.1.0)

def tg_paid(p):
    ch = one("SELECT ch.*, c.name FROM k_charges ch JOIN k_customers c ON c.id=ch.customer_id WHERE ch.id=?", (p["id"],))
    if not ch:
        raise RuntimeError("opkrævningen findes ikke længere")
    if ch["paid_at"]:
        return f"{ch['name']} var allerede markeret betalt", None
    t = iso(now())
    run("UPDATE k_charges SET paid_at=?, requested_at=COALESCE(requested_at, ?), skipped=0 WHERE id=?", (t, t, ch["id"]))
    return f"{ch['name']} markeret betalt ({_kr(ch['amount'])})", {"id": ch["id"]}


def tg_unpaid(p):
    run("UPDATE k_charges SET paid_at=NULL WHERE id=?", (p["id"],))
    return "markeret som ikke betalt igen"


def tg_snooze(p):
    sz = D["kv_get"]("kunder_snooze", {}) or {}
    old = sz.get(str(p["id"]))
    until = (now().date() + datetime.timedelta(days=7)).isoformat()
    sz[str(p["id"])] = until
    D["kv_set"]("kunder_snooze", sz)
    return f"ingen påmindelse før {until[8:10]}/{until[5:7]}", {"id": p["id"], "old": old}


def tg_unsnooze(p):
    sz = D["kv_get"]("kunder_snooze", {}) or {}
    if p.get("old"):
        sz[str(p["id"])] = p["old"]
    else:
        sz.pop(str(p["id"]), None)
    D["kv_set"]("kunder_snooze", sz)
    return "påmindelsen er tilbage"


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
    fixed = D["fixed_costs"]() if D.get("fixed_costs") else fixed_costs(settings()["fixed_costs"])   # 2.1.0: Opkrævning › Udgifter
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


def due_message(period, day):
    """Besked på dagen: de kunder, der har betalingsdato i dag, og som endnu ikke er anmodet, betalt eller sprunget over.
    Navnene står i beskeden (Jespers valg 13. nov. 2026) – aldrig telefonnumre, koder eller andre oplysninger."""
    ensure_charges(period)
    due = [r for r in rows("SELECT ch.amount, c.name, c.method, c.due_day FROM k_charges ch JOIN k_customers c ON c.id=ch.customer_id"
                           " WHERE ch.period=? AND ch.skipped=0 AND ch.requested_at IS NULL AND ch.paid_at IS NULL", (period,))
           if due_in(r["due_day"], period) == day]
    if not due:
        return ""
    due.sort(key=lambda r: norm(r["name"]))
    lines = [f"• {r['name']}: {_kr(r['amount'])}" + (f" · {r['method']}" if r["method"] else "") for r in due[:60]]
    if len(due) > 60:
        lines.append(f"… og {len(due) - 60} flere")
    return (f"📅 Stream365 – skal opkræves i dag ({day}. {MONTHS_DA[int(period[5:7]) - 1]})\n\n" + "\n".join(lines)
            + f"\n\n{len(due)} {'kunde' if len(due) == 1 else 'kunder'}, {_kr(sum(r['amount'] for r in due))} i alt."
            + "\nSe dem i Fangarr › Opkrævning › I dag.")


def tick():
    """Kaldes hvert minut af Fangarrs baggrundsjob."""
    n = now()
    s = settings()
    st = D["kv_get"]("kunder_jobs", {}) or {}
    changed = False
    today, cur = n.date().isoformat(), period_of(n)
    # natlig synk – først når du selv har synket første gang
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
        if st.get("due_sent") != today:      # besked på dagen om dem, der har betalingsdato i dag
            st["due_sent"] = today
            changed = True
            try:
                msg = due_message(cur, n.day)
                if msg:
                    D["telegram"](msg)
            except Exception as e:   # må aldrig stoppe baggrundsjobbet
                D["log"].warning("Dagens opkrævningsbesked fejlede: %s", e)
        if st.get("remind_day") != today:
            st["remind_day"] = today
            changed = True
            late = overdue_list(skip_snoozed=True)
            ids = [r["id"] for r in late]
            sent = set(st.get("remind_ids") or [])
            last = st.get("remind_sent") or ""
            repeat = max(1, int(s["remind_repeat_days"]))
            old = not last or (n.date() - datetime.date.fromisoformat(last)).days >= repeat
            if late and (old or set(ids) - sent):
                lines = [f"• {r['name']}: {_kr(r['amount'])} (anmodet {r['requested_at'][8:10]}/{r['requested_at'][5:7]})" for r in late[:40]]
                knapper = [[(f"✅ {r['name'][:22]} betalt", "pay_paid", {"id": r["id"]}),
                            (f"⏳ {r['name'][:14]} +1 uge", "pay_snooze", {"id": r["id"]})] for r in late[:12]]
                D["telegram_rows"](f"⏰ Stream365 – {len(late)} {'kunde mangler' if len(late) == 1 else 'kunder mangler'} at betale "
                                   f"({_kr(sum(r['amount'] for r in late))})\n\n" + "\n".join(lines) +
                                   "\n\nTryk Betalt herunder eller i Fangarr › Opkrævning. \"+1 uge\" udsætter påmindelsen.", knapper)
                st["remind_sent"], st["remind_ids"] = today, ids
            elif not late and sent:
                D["telegram"]("✅ Stream365 – alle, der var anmodet, har nu betalt.")
                st["remind_ids"], st["remind_sent"] = [], ""
            elif late:
                st["remind_ids"] = [i for i in sent if i in ids]
    if changed:
        D["kv_set"]("kunder_jobs", st)


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
