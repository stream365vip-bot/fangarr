"""Huskeliste og udgifter (2.1.0).

Huskeliste (Drift › Huskeliste): opgaver med dato, server, valgfri kontrolkommando (vises med kopiknap) og gentagelse.
På dagen står opgaven under "Kræver din handling", og der kommer én besked i Stream365 Drift med knapperne
Udført og Udsæt en dag.

Udgifter (Opkrævning › Udgifter): navn, beløb pr. måned eller år, næste fornyelse og varsel. Når varslet nås,
lægges en opgave "Forny …" på huskelisten. Tryk Udført (= fornyet), så rykkes fornyelsen en måned/et år frem.
Økonomi bruger udgifterne i stedet for det gamle fritekstfelt "faste udgifter" (linjerne flyttes over én gang).

Intet her indeholder hemmeligheder: kontrolkommandoer skal kun vise ting, og der må aldrig stå nøgler i dem.
"""

import calendar
import datetime
import json
import re

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api")
D = {}   # udfyldes af main.py: db, kv_get, kv_set, now, iso, telegram_rows, get_settings, kunder_settings, money

REPEATS = {"": "Ingen", "dag": "Hver dag", "uge": "Hver uge", "maaned": "Hver måned", "kvartal": "Hvert kvartal", "aar": "Hvert år"}
SERVERS = ("", "feeder", "Mediabox", "begge", "Chromebook", "telefon", "andet")

# Datoopgaver fra servere-dokumentation.md (24. nov. 2026) – lægges ind én gang, når huskelisten er tom.
START = [
    ("Slet gamle kopier med nøgler: fangarr.env.bak-2026-11-16 og docker-compose.yml.bak-2026-11-16", "2026-11-25", "feeder",
     "ls -la /opt/fangarr/*.bak-2026-11-16", "Kunne slettes fra 23. nov. Kontrollér først, at Fangarr og widgetten virker."),
    ("Slet /opt/_backup på Mediabox (gamle app-data fra oktober)", "2026-11-25", "Mediabox", "sudo du -sh /opt/_backup",
     "Kunne slettes fra 23. nov. Tjek indholdet først."),
    ("Slet /opt/_backup_apps på feeder (gamle app-mapper)", "2026-11-25", "feeder", "sudo du -sh /opt/_backup_apps",
     "Kunne slettes fra 24. nov. Tjek indholdet først."),
    ("Kør sb install plex-db på et stille tidspunkt (efter oprydningen 22. nov.)", "2026-11-25", "Mediabox", "",
     "Plex er væk 5–15 min. Brug \"Sig til ved 0 streams\" på Overblik."),
    ("Slet fangarr.env.bak-2026-11-21 (indeholder nøgler)", "2026-11-28", "feeder", "ls -la /opt/fangarr/fangarr.env.bak-2026-11-21", ""),
    ("Slet sikkerhedskopien fangarr-foer-1.23.0.db, hvis Seerr-ønsker kører fint", "2026-11-28", "feeder",
     "ls -la /opt/fangarr/data/fangarr-foer-1.23.0.db", ""),
    ("Tjek første kørsel af sonarr_opdater.py", "2026-11-29", "feeder", "tail -n 2 /opt/scripts/sonarr-opdater/sonarr-opdater.log", ""),
    ("Slet julekalender-dubletterne (ca. 90 GB) efter kontrol", "2026-11-29", "feeder",
     "du -sh /mnt/local/Media/_julekalender-dubletter-2026-11-22/", ""),
    ("Tjek at Den Store Julefortælling og I Nissernes Tjeneste hentes og vises i Plex", "2026-12-01", "", "", ""),
    ("Slet fangarr-foer-2.0.0.db, hvis Fangarr 2 kører fint", "2026-12-01", "feeder", "ls -la /opt/fangarr/data/fangarr-foer-2.0.0.db", ""),
    ("Maintainerr: tjek sletningen af 5 serier og 174 film, tøm Plex' papirkurv for Film efter kontrol, tjek antal film (min. 5.500)",
     "2026-12-06", "Mediabox", "", "Se claude/maintainerr.md og claude/plex-papirkurv.md."),
    ("Slet sikkerhedskopierne backup-saltbox-2026-11-07.tar.gz på begge servere", "2026-12-07", "begge",
     "ls -la /mnt/local/backup-saltbox-2026-11-07.tar.gz ~/backup-saltbox-2026-11-07.tar.gz 2>/dev/null", ""),
    ("Tjek at etiketterne Jul er fjernet, og jule-rækkerne er væk fra Home", "2026-12-27", "Mediabox",
     "tail -n 3 /opt/scripts/julefilm/julefilm.log", ""),
    ("Sæt Maintainerr-reglen for Seerr-ønsker op (skal være klar før ca. 8. feb.)", "2027-01-25", "", "", "Se claude/seerr.md."),
]


def init():
    con = D["db"]()
    with con:
        con.execute("CREATE TABLE IF NOT EXISTS huske (id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, title TEXT, due TEXT,"
                    " server TEXT DEFAULT '', command TEXT DEFAULT '', repeat TEXT DEFAULT '', note TEXT DEFAULT '',"
                    " done_at TEXT, notified TEXT DEFAULT '', kind TEXT DEFAULT '', ref INTEGER DEFAULT 0, ref_date TEXT DEFAULT '')")
        con.execute("CREATE TABLE IF NOT EXISTS udgifter (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, amount REAL DEFAULT 0,"
                    " per TEXT DEFAULT 'maaned', renews TEXT DEFAULT '', notice INTEGER DEFAULT 14, note TEXT DEFAULT '', active INTEGER DEFAULT 1)")
    con.close()
    if not D["kv_get"]("huske_seeded"):
        con = D["db"]()
        empty = not con.execute("SELECT id FROM huske LIMIT 1").fetchone()
        if empty:
            with con:
                for t, due, srv, cmd, note in START:
                    con.execute("INSERT INTO huske (created, title, due, server, command, note) VALUES (?,?,?,?,?,?)",
                                (D["iso"](D["now"]()), t, due, srv, cmd, note))
        con.close()
        D["kv_set"]("huske_seeded", True)
    migrate_fixed_costs()


def migrate_fixed_costs():
    """Én gang: linjerne i det gamle felt "faste udgifter" (Kunder › Indstillinger) bliver til udgifter pr. måned."""
    if D["kv_get"]("udgifter_migrated"):
        return
    text = D["kunder_settings"]().get("fixed_costs") or ""
    con = D["db"]()
    with con:
        for line in str(text).splitlines():
            if ":" in line or "=" in line:
                k, v = re.split(r"[:=]", line, maxsplit=1)
                amount = D["money"](v)
                if k.strip() and amount:
                    con.execute("INSERT INTO udgifter (name, amount, per, renews, notice) VALUES (?,?,?,?,?)",
                                (k.strip()[:80], amount, "maaned", "", 0))
    con.close()
    D["kv_set"]("udgifter_migrated", True)


# ---------------------------------------------------------------- hjælpere

def _rows(sql, args=()):
    con = D["db"]()
    out = [dict(r) for r in con.execute(sql, args).fetchall()]
    con.close()
    return out


def _one(sql, args=()):
    r = _rows(sql, args)
    return r[0] if r else None


def _run(sql, args=()):
    con = D["db"]()
    with con:
        cur = con.execute(sql, args)
    con.close()
    return cur.lastrowid


def _date(v, required=True):
    v = str(v or "").strip()
    if not v and not required:
        return ""
    try:
        return datetime.date.fromisoformat(v).isoformat()
    except ValueError:
        raise HTTPException(400, "skriv datoen som åååå-mm-dd, fx 2026-12-01")


def add_months(d, n):
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))


def next_date(due, repeat):
    d = datetime.date.fromisoformat(due)
    if repeat == "dag":
        return d + datetime.timedelta(days=1)
    if repeat == "uge":
        return d + datetime.timedelta(days=7)
    if repeat == "maaned":
        return add_months(d, 1)
    if repeat == "kvartal":
        return add_months(d, 3)
    if repeat == "aar":
        return add_months(d, 12)
    return None


def today():
    return D["now"]().date().isoformat()


def due_items():
    """Opgaver, der skal gøres i dag eller er overskredet."""
    return _rows("SELECT * FROM huske WHERE done_at IS NULL AND due<=? ORDER BY due, id", (today(),))


# ---------------------------------------------------------------- huskeliste: handlinger (bruges af siden og af Telegram)

def mark_done(hid):
    """Udført. Gentagne opgaver rykkes til næste dato; en udgift rykkes en måned/et år frem. Returnerer (tekst, fortryd)."""
    h = _one("SELECT * FROM huske WHERE id=?", (hid,))
    if not h:
        raise HTTPException(404, "opgaven findes ikke længere")
    if h["done_at"]:
        return "var allerede udført", None
    undo = {"id": hid, "due": h["due"], "notified": h["notified"], "renews": None}
    if h["kind"] == "udgift" and h["ref"]:
        u = _one("SELECT * FROM udgifter WHERE id=?", (h["ref"],))
        if u and u["renews"]:
            undo["renews"] = u["renews"]
            new = add_months(datetime.date.fromisoformat(u["renews"]), 12 if u["per"] == "aar" else 1).isoformat()
            _run("UPDATE udgifter SET renews=? WHERE id=?", (new, u["id"]))
    nxt = next_date(h["due"], h["repeat"]) if h["repeat"] else None
    if nxt:
        # spring over datoer, der allerede er gået (fx en daglig opgave, der har ligget en uge)
        while nxt.isoformat() <= today() and h["repeat"]:
            nxt = next_date(nxt.isoformat(), h["repeat"])
        _run("UPDATE huske SET due=?, notified='' WHERE id=?", (nxt.isoformat(), hid))
        return f"udført – næste gang {nxt.strftime('%d/%m')}", undo
    _run("UPDATE huske SET done_at=? WHERE id=?", (D["iso"](D["now"]()), hid))
    return "udført", undo


def undo_done(u):
    _run("UPDATE huske SET done_at=NULL, due=?, notified=? WHERE id=?", (u["due"], u.get("notified") or "", u["id"]))
    h = _one("SELECT * FROM huske WHERE id=?", (u["id"],))
    if u.get("renews") and h and h["ref"]:
        _run("UPDATE udgifter SET renews=? WHERE id=?", (u["renews"], h["ref"]))
    return "står på huskelisten igen"


def snooze(hid, days=1):
    h = _one("SELECT * FROM huske WHERE id=?", (hid,))
    if not h:
        raise HTTPException(404, "opgaven findes ikke længere")
    base = max(datetime.date.fromisoformat(h["due"]), datetime.date.fromisoformat(today()))
    new = (base + datetime.timedelta(days=days)).isoformat()
    _run("UPDATE huske SET due=?, notified='' WHERE id=?", (new, hid))
    return f"udsat til {new[8:10]}/{new[5:7]}", {"id": hid, "due": h["due"], "notified": h["notified"]}


def undo_snooze(u):
    _run("UPDATE huske SET due=?, notified=? WHERE id=?", (u["due"], u.get("notified") or "", u["id"]))
    return "datoen er sat tilbage"


# ---------------------------------------------------------------- huskeliste: API

def _out(h):
    h = dict(h)
    h["overdue"] = not h["done_at"] and h["due"] < today()
    h["today"] = not h["done_at"] and h["due"] == today()
    h["repeat_label"] = REPEATS.get(h["repeat"] or "", "")
    return h


@router.get("/huskeliste")
def huske_list(done: int = 0):
    if done:
        items = _rows("SELECT * FROM huske WHERE done_at IS NOT NULL ORDER BY done_at DESC LIMIT 100")
    else:
        items = _rows("SELECT * FROM huske WHERE done_at IS NULL ORDER BY due, id")
    return {"today": today(), "items": [_out(h) for h in items], "repeats": REPEATS, "servers": list(SERVERS)}


@router.post("/huskeliste")
async def huske_save(req: Request):
    b = await req.json()
    title = str(b.get("title") or "").strip()[:300]
    if not title:
        raise HTTPException(400, "skriv, hvad du skal huske")
    due = _date(b.get("due"))
    repeat = str(b.get("repeat") or "")
    if repeat not in REPEATS:
        raise HTTPException(400, "ukendt gentagelse")
    vals = (title, due, str(b.get("server") or "")[:30], str(b.get("command") or "").strip()[:1000], repeat,
            str(b.get("note") or "").strip()[:1000])
    hid = b.get("id")
    if hid:
        if not _one("SELECT id FROM huske WHERE id=?", (hid,)):
            raise HTTPException(404, "opgaven findes ikke længere")
        _run("UPDATE huske SET title=?, due=?, server=?, command=?, repeat=?, note=?, notified='' WHERE id=?", vals + (hid,))
    else:
        _run("INSERT INTO huske (title, due, server, command, repeat, note, created) VALUES (?,?,?,?,?,?,?)", vals + (D["iso"](D["now"]()),))
    return huske_list()


@router.post("/huskeliste/{hid}/done")
def huske_done(hid: int):
    mark_done(hid)
    return huske_list()


@router.post("/huskeliste/{hid}/snooze")
def huske_snooze(hid: int, days: int = 1):
    snooze(hid, max(1, min(days, 60)))
    return huske_list()


@router.post("/huskeliste/{hid}/reopen")
def huske_reopen(hid: int):
    _run("UPDATE huske SET done_at=NULL, notified='' WHERE id=?", (hid,))
    return huske_list(done=1)


@router.delete("/huskeliste/{hid}")
def huske_delete(hid: int):
    _run("DELETE FROM huske WHERE id=?", (hid,))
    return huske_list()


# ---------------------------------------------------------------- udgifter

def monthly(u):
    return float(u["amount"] or 0) / (12 if u["per"] == "aar" else 1)


def fixed_for_economy():
    """Til Økonomi: [{name, amount pr. måned}] – erstatter det gamle fritekstfelt."""
    return [{"name": u["name"], "amount": round(monthly(u), 2)} for u in _rows("SELECT * FROM udgifter WHERE active=1 ORDER BY name")]


@router.get("/udgifter")
def udgifter_list():
    items = _rows("SELECT * FROM udgifter ORDER BY active DESC, (renews='' OR renews IS NULL), renews, name")
    for u in items:
        u["monthly"] = round(monthly(u), 2)
        u["soon"] = bool(u["renews"] and u["active"] and
                         datetime.date.fromisoformat(u["renews"]) - datetime.timedelta(days=int(u["notice"] or 0)) <= datetime.date.fromisoformat(today()))
    act = [u for u in items if u["active"]]
    return {"items": items, "per_month": round(sum(u["monthly"] for u in act), 2), "per_year": round(sum(u["monthly"] for u in act) * 12, 2)}


@router.post("/udgifter")
async def udgifter_save(req: Request):
    b = await req.json()
    name = str(b.get("name") or "").strip()[:80]
    if not name:
        raise HTTPException(400, "skriv udgiftens navn")
    amount = D["money"](b.get("amount"))
    if amount <= 0:
        raise HTTPException(400, "skriv beløbet")
    per = "aar" if b.get("per") == "aar" else "maaned"
    renews = _date(b.get("renews"), required=False)
    notice = max(0, min(int(D["money"](b.get("notice")) or 0), 120))
    vals = (name, amount, per, renews, notice, str(b.get("note") or "").strip()[:500], 1 if b.get("active", True) else 0)
    uid = b.get("id")
    if uid:
        old = _one("SELECT * FROM udgifter WHERE id=?", (uid,))
        if not old:
            raise HTTPException(404, "udgiften findes ikke længere")
        _run("UPDATE udgifter SET name=?, amount=?, per=?, renews=?, notice=?, note=?, active=? WHERE id=?", vals + (uid,))
        if old["renews"] != renews:   # ny dato: en gammel påmindelse om fornyelse gælder ikke længere
            _run("DELETE FROM huske WHERE kind='udgift' AND ref=? AND done_at IS NULL", (uid,))
    else:
        _run("INSERT INTO udgifter (name, amount, per, renews, notice, note, active) VALUES (?,?,?,?,?,?,?)", vals)
    return udgifter_list()


@router.delete("/udgifter/{uid}")
def udgifter_delete(uid: int):
    _run("DELETE FROM udgifter WHERE id=?", (uid,))
    _run("DELETE FROM huske WHERE kind='udgift' AND ref=? AND done_at IS NULL", (uid,))
    return udgifter_list()


def _kr(v):
    return f"{v:,.0f} kr.".replace(",", ".")


def renewals_to_huske():
    """Udgifter, hvor varslet er nået: læg "Forny …" på huskelisten (én gang pr. fornyelsesdato)."""
    t = datetime.date.fromisoformat(today())
    for u in _rows("SELECT * FROM udgifter WHERE active=1 AND renews!='' AND renews IS NOT NULL"):
        r = datetime.date.fromisoformat(u["renews"])
        if r - datetime.timedelta(days=int(u["notice"] or 0)) > t:
            continue
        if _one("SELECT id FROM huske WHERE kind='udgift' AND ref=? AND ref_date=?", (u["id"], u["renews"])):
            continue
        per = "år" if u["per"] == "aar" else "måned"
        _run("INSERT INTO huske (created, title, due, server, note, kind, ref, ref_date) VALUES (?,?,?,?,?,?,?,?)",
             (D["iso"](D["now"]()), f"Forny {u['name']} ({_kr(u['amount'])} pr. {per}) – fornyes {r.strftime('%d/%m/%Y')}",
              t.isoformat(), "", "Tryk Udført, når den er fornyet. Så rykkes datoen en " + ("år" if u["per"] == "aar" else "måned") + " frem.",
              "udgift", u["id"], u["renews"]))


# ---------------------------------------------------------------- baggrund

def tick():
    """Kaldes hvert minut. På dagen (fra kl. i indstillingen): én besked pr. opgave med Udført og Udsæt en dag."""
    renewals_to_huske()
    hour = int(D["get_settings"]().get("huske_hour", 8))
    if hour < 0 or D["now"]().hour < hour:
        return
    for h in due_items():
        if h["notified"] == h["due"]:
            continue
        _run("UPDATE huske SET notified=? WHERE id=?", (h["due"], h["id"]))
        late = " (skulle have været gjort " + h["due"][8:10] + "/" + h["due"][5:7] + ")" if h["due"] < today() else ""
        lines = [f"📌 Huskeliste{late}: {h['title']}"]
        if h["server"]:
            lines.append(f"Server: {h['server']}")
        if h["command"]:
            lines.append(f"Kontrol: {h['command']}")
        if h["note"]:
            lines.append(h["note"])
        D["telegram_rows"]("\n".join(lines), [[("Udført", "huske_done", {"id": h["id"]}), ("Udsæt en dag", "huske_snooze", {"id": h["id"]})]])
