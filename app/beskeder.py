"""Kunder og beskeder (2.2.0).

- **Skabeloner** (Beskeder › Skabeloner): velkomst, "dit ønske er klar", prisændring og egne beskeder. Felterne
  {fornavn}, {navn}, {titel}, {guide}, {tjeneste}, {gammel_pris}, {ny_pris} og {dato} fyldes ud for hver kunde.
- **Send-kø** (Beskeder › Send-kø): vælg skabelon og modtagere. Kunderne gennemgås én ad gangen med beskeden klar i
  Telegram eller Messenger – du trykker selv send. Flueben ved sendt, og det kommer på tidslinjen. Køen kan stoppes.
- **Ønsker klar** (Beskeder › Ønsker klar): når et Seerr-ønske står som tilgængeligt i Seerr (dvs. er vist i Plex –
  og det sker først, når det har dansk tale eller tekst), kommer kunden på listen med "Din film/sæson er klar".
  Én besked om dagen til Stream365 Drift med antal. Fangarr skriver aldrig selv til kunderne.
- **Ændring for alle** (Beskeder › Ændring for alle): ny pris på en tjeneste fra en dato. Først vises, hvem der rammes,
  og hvad de betaler før og efter. Først efter bekræftelse gemmes ændringen; priserne skiftes den dato (opkrævninger
  før datoen røres ikke), og beskeden lægges i send-køen.
- **Tidslinje** på kundekortet: bygges af det, Fangarr allerede har gemt (oprettet, opkrævninger, Anmodet/Betalt,
  Seerr-ønsker og køb) + nye hændelser (beskeder sendt, ønske klar, prisændring) og dine egne noter.
- **Det, kunderne leder efter** (Guide › Søgninger): søgninger i guiden uden svar og de mest ønskede titler i Seerr.

Telefon, e-mail og koder sendes aldrig til Telegram – beskeden til dig indeholder kun antal.
"""

import datetime
import json
import os
import re

import httpx
from fastapi import APIRouter, HTTPException, Request

from . import kunder

router = APIRouter(prefix="/api/beskeder")
D = {}   # udfyldes af main.py: db, kv_get, kv_set, now, iso, telegram_rows, get_settings, log, guide_summary

SEERR_URL = (os.environ.get("SEERR_URL") or "").rstrip("/")
SEERR_APIKEY = os.environ.get("SEERR_APIKEY") or ""
GUIDE_URL = os.environ.get("GUIDE_PUBLIC_URL") or "https://guide.stream365.vip"
rows, one, run = kunder.rows, kunder.one, kunder.run

FIELDS = ["{fornavn}", "{navn}", "{titel}", "{guide}", "{tjeneste}", "{gammel_pris}", "{ny_pris}", "{dato}"]
KINDS = {"velkomst": "Velkomst", "klar": "Dit ønske er klar", "pris": "Prisændring", "fri": "Egen besked"}
DEFAULT_TEMPLATES = [
    ("velkomst", "Velkomst", "Hej {fornavn} 👋\n\nVelkommen til Stream365! Her er guiden med alt, du skal vide – "
     "sådan kommer du i gang, reglerne og hvordan du ønsker film og serier:\n{guide}\n\nSkriv endelig, hvis du har spørgsmål.\n\nMvh Stream365"),
    ("klar", "Dit ønske er klar", "Hej {fornavn} 🎬\n\n{titel} er nu klar i Plex – med danske tekster. God fornøjelse!\n\nMvh Stream365"),
    ("pris", "Prisændring", "Hej {fornavn}\n\nFra {dato} ændres prisen på {tjeneste} fra {gammel_pris} til {ny_pris} pr. måned.\n\n"
     "Det står også i din næste opkrævning. Skriv endelig, hvis du har spørgsmål.\n\nMvh Stream365"),
]


def setup(**deps):
    D.update(deps)


def iso(dt=None):
    return D["iso"](dt or D["now"]())


def init():
    con = D["db"]()
    with con:
        con.execute("CREATE TABLE IF NOT EXISTS b_templates (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT DEFAULT 'fri', name TEXT, text TEXT,"
                    " updated TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS b_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, name TEXT, template_id INTEGER,"
                    " text TEXT, status TEXT DEFAULT 'aktiv', kind TEXT DEFAULT 'fri', ref INTEGER DEFAULT 0)")
        con.execute("CREATE TABLE IF NOT EXISTS b_items (id INTEGER PRIMARY KEY AUTOINCREMENT, queue_id INTEGER, customer_id INTEGER,"
                    " data TEXT DEFAULT '{}', status TEXT DEFAULT 'venter', done_at TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS b_ready (request_id INTEGER PRIMARY KEY, customer_id INTEGER, plex_user_id INTEGER, title TEXT,"
                    " media TEXT, ready_at TEXT, status TEXT DEFAULT 'venter', done_at TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS b_price (id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, service TEXT, price_now REAL,"
                    " price_new REAL, from_period TEXT, customers TEXT DEFAULT '[]', applied_at TEXT, queue_id INTEGER, cancelled_at TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS k_events (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, ts TEXT, kind TEXT,"
                    " text TEXT)")
        if not con.execute("SELECT id FROM b_templates LIMIT 1").fetchone():
            for kind, name, text in DEFAULT_TEMPLATES:
                con.execute("INSERT INTO b_templates (kind, name, text, updated) VALUES (?,?,?,?)", (kind, name, text, iso()))
    con.close()


def event(cid, kind, text):
    """Én hændelse på kundens tidslinje (beskeder, ønsker klar, prisændringer, noter)."""
    if cid:
        run("INSERT INTO k_events (customer_id, ts, kind, text) VALUES (?,?,?,?)", (cid, iso(), kind, str(text)[:500]))


# ---------------------------------------------------------------- skabeloner og felter

def _kr(v):
    return kunder._kr(v) if hasattr(kunder, "_kr") else f"{v:,.0f} kr.".replace(",", ".")


def first_name(name):
    n = str(name or "").strip()
    return n.split()[0] if n else ""


def render(text, c, data=None):
    data = data or {}
    vals = {"{fornavn}": first_name(c.get("name")), "{navn}": c.get("name") or "", "{guide}": GUIDE_URL,
            "{titel}": data.get("titel") or "", "{tjeneste}": data.get("tjeneste") or "",
            "{gammel_pris}": data.get("gammel_pris") or "", "{ny_pris}": data.get("ny_pris") or "", "{dato}": data.get("dato") or ""}
    out = str(text or "")
    for k, v in vals.items():
        out = out.replace(k, str(v))
    return out.strip()


def contact(c):
    """Det, siden skal bruge for at åbne chatten – brugernavne fra kundekortet (vises kun bag Authelia)."""
    return {"tg": kunder.handle(c.get("tg"), "tg"), "fb": kunder.handle(c.get("fb"), "fb"), "channel": kunder.channel(c)}


def templates():
    return rows("SELECT * FROM b_templates ORDER BY CASE kind WHEN 'velkomst' THEN 0 WHEN 'klar' THEN 1 WHEN 'pris' THEN 2 ELSE 3 END, name")


def template(tid=None, kind=None):
    if tid:
        t = one("SELECT * FROM b_templates WHERE id=?", (tid,))
    else:
        t = one("SELECT * FROM b_templates WHERE kind=? ORDER BY id LIMIT 1", (kind,))
    if not t:
        raise HTTPException(404, "skabelonen findes ikke")
    return t


@router.get("/skabeloner")
def tpl_list():
    return {"templates": templates(), "fields": FIELDS, "kinds": KINDS}


@router.post("/skabeloner")
async def tpl_save(req: Request):
    b = await req.json()
    name, text = str(b.get("name") or "").strip()[:80], str(b.get("text") or "").strip()[:4000]
    if not name or not text:
        raise HTTPException(400, "skriv både navn og tekst")
    kind = b.get("kind") if b.get("kind") in KINDS else "fri"
    if b.get("id"):
        old = template(int(b["id"]))
        run("UPDATE b_templates SET name=?, text=?, updated=? WHERE id=?", (name, text, iso(), old["id"]))
    else:
        run("INSERT INTO b_templates (kind, name, text, updated) VALUES (?,?,?,?)", ("fri" if kind != "fri" else kind, name, text, iso()))
    return tpl_list()


@router.delete("/skabeloner/{tid}")
def tpl_delete(tid: int):
    t = template(tid)
    if t["kind"] != "fri":
        raise HTTPException(400, "de faste skabeloner (velkomst, ønske klar, prisændring) kan rettes, men ikke slettes")
    run("DELETE FROM b_templates WHERE id=?", (tid,))
    return tpl_list()


# ---------------------------------------------------------------- modtagere og send-kø

def _customers():
    return rows("SELECT * FROM k_customers ORDER BY name COLLATE NOCASE")


def recipients(b):
    """Hvem får beskeden? alle aktive kunder, pr. tjeneste, pr. betalingsmetode eller udvalgte. Familie kun hvis valgt."""
    who = b.get("who") or "alle"
    fam = bool(b.get("family"))
    cs = [c for c in _customers() if c["status"] == "aktiv" and (fam or c["kind"] == "kunde")]
    if who == "tjeneste":
        svc = str(b.get("service") or "")
        have = {r["customer_id"] for r in rows("SELECT DISTINCT customer_id FROM k_services WHERE service=? AND active=1", (svc,))}
        cs = [c for c in cs if c["id"] in have]
    elif who == "metode":
        m = str(b.get("method") or "")
        cs = [c for c in cs if (c["method"] or "") == m]
    elif who == "udvalgte":
        ids = {int(x) for x in (b.get("ids") or []) if str(x).isdigit()}
        cs = [c for c in _customers() if c["id"] in ids]
    elif who != "alle":
        raise HTTPException(400, "ukendt valg af modtagere")
    return cs


@router.post("/modtagere")
async def recipients_preview(req: Request):
    b = await req.json()
    cs = recipients(b)
    return {"count": len(cs), "customers": [{"id": c["id"], "name": c["name"], **{k: bool(v) for k, v in contact(c).items() if k != "channel"}}
                                            for c in cs]}


def _queue_out(q, with_items=True):
    items = rows("SELECT i.*, c.name, c.tg, c.fb, c.contact FROM b_items i LEFT JOIN k_customers c ON c.id=i.customer_id"
                 " WHERE i.queue_id=? ORDER BY i.id", (q["id"],))
    n = {s: sum(1 for i in items if i["status"] == s) for s in ("venter", "sendt", "sprunget")}
    out = {**q, "counts": n, "total": len(items)}
    if with_items:
        out["items"] = []
        for i in items:
            c = {"name": i["name"] or "(slettet kunde)", "tg": i["tg"], "fb": i["fb"], "contact": i["contact"]}
            data = json.loads(i["data"] or "{}")
            out["items"].append({"id": i["id"], "customer_id": i["customer_id"], "name": c["name"], "status": i["status"],
                                 "done_at": i["done_at"], "text": render(q["text"], c, data), **contact(c)})
    return out


def queues(include_done=False):
    qs = rows("SELECT * FROM b_queue ORDER BY id DESC LIMIT 30")
    out = [_queue_out(q, with_items=False) for q in qs]
    return [q for q in out if include_done or q["status"] != "færdig" or q["counts"]["venter"]]


def new_queue(name, text, customers, kind="fri", template_id=None, ref=0, data_for=None):
    con = D["db"]()
    with con:
        cur = con.execute("INSERT INTO b_queue (created, name, template_id, text, status, kind, ref) VALUES (?,?,?,?,?,?,?)",
                          (iso(), name[:120], template_id, text, "aktiv", kind, ref))
        qid = cur.lastrowid
        for c in customers:
            con.execute("INSERT INTO b_items (queue_id, customer_id, data) VALUES (?,?,?)",
                        (qid, c["id"], json.dumps((data_for or {}).get(c["id"], {}), ensure_ascii=False)))
    con.close()
    return qid


@router.get("/koe")
def queue_list(alle: int = 0):
    return {"queues": queues(bool(alle)), "templates": templates(), "services": kunder.SERVICES, "fields": FIELDS}


@router.get("/koe/{qid}")
def queue_get(qid: int):
    q = one("SELECT * FROM b_queue WHERE id=?", (qid,))
    if not q:
        raise HTTPException(404, "køen findes ikke")
    return _queue_out(q)


@router.post("/koe")
async def queue_create(req: Request):
    b = await req.json()
    t = template(int(b.get("template_id") or 0))
    text = str(b.get("text") or t["text"]).strip()[:4000]
    cs = recipients(b)
    if not cs:
        raise HTTPException(400, "ingen modtagere passer til dit valg")
    name = str(b.get("name") or t["name"]).strip()[:120] or t["name"]
    qid = new_queue(name, text, cs, kind=t["kind"], template_id=t["id"])
    return queue_get(qid)


@router.post("/koe/{qid}/status")
async def queue_status(qid: int, req: Request):
    b = await req.json()
    st = b.get("status")
    if st not in ("aktiv", "stoppet", "færdig"):
        raise HTTPException(400, "ukendt status")
    run("UPDATE b_queue SET status=? WHERE id=?", (st, qid))
    return queue_get(qid)


@router.post("/item/{iid}")
async def item_action(iid: int, req: Request):
    b = await req.json()
    a = b.get("action")
    i = one("SELECT i.*, q.name qname, q.id qid FROM b_items i JOIN b_queue q ON q.id=i.queue_id WHERE i.id=?", (iid,))
    if not i:
        raise HTTPException(404, "findes ikke længere")
    if a == "sent":
        if i["status"] != "sendt":
            run("UPDATE b_items SET status='sendt', done_at=? WHERE id=?", (iso(), iid))
            event(i["customer_id"], "besked", f"Besked sendt: {i['qname']}")
    elif a == "skip":
        run("UPDATE b_items SET status='sprunget', done_at=? WHERE id=?", (iso(), iid))
    elif a == "undo":
        if i["status"] == "sendt":
            event(i["customer_id"], "besked", f"Fortrudt: {i['qname']} (markeret ikke sendt)")
        run("UPDATE b_items SET status='venter', done_at=NULL WHERE id=?", (iid,))
    else:
        raise HTTPException(400, "ukendt handling")
    q = one("SELECT * FROM b_queue WHERE id=?", (i["qid"],))
    left = one("SELECT COUNT(*) n FROM b_items WHERE queue_id=? AND status='venter'", (q["id"],))["n"]
    if not left and q["status"] == "aktiv":
        run("UPDATE b_queue SET status='færdig' WHERE id=?", (q["id"],))
    elif left and q["status"] == "færdig":
        run("UPDATE b_queue SET status='aktiv' WHERE id=?", (q["id"],))
    return queue_get(q["id"])


# ---------------------------------------------------------------- ønsker klar (Seerr)

def seerr_enabled():
    return bool(SEERR_URL and SEERR_APIKEY)


def _sx(path, **params):
    r = httpx.get(SEERR_URL + "/api/v1" + path, headers={"X-Api-Key": SEERR_APIKEY}, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _title(media_type, tmdb):
    cache = D["kv_get"]("seerr_titles", {}) or {}
    key = f"{media_type}:{tmdb}"
    if key in cache:
        return cache[key]
    try:
        d = _sx(f"/{'tv' if media_type == 'tv' else 'movie'}/{tmdb}", language="da")
        t = d.get("name") or d.get("title") or d.get("originalName") or d.get("originalTitle") or ""
        y = (d.get("firstAirDate") or d.get("releaseDate") or "")[:4]
        t = f"{t} ({y})" if t and y else t
    except (httpx.HTTPError, ValueError):
        return ""
    cache[key] = t
    if len(cache) > 3000:
        cache = dict(list(cache.items())[-2000:])
    D["kv_set"]("seerr_titles", cache)
    return t


def _ready(req_):
    """Er ønsket klar? Film: tilgængelig. Serie: alle ønskede sæsoner er tilgængelige (eller hele serien er)."""
    m = req_.get("media") or {}
    if m.get("status") == 5:
        return True
    if req_.get("type") != "tv":
        return False
    want = {s.get("seasonNumber") for s in req_.get("seasons") or []}
    have = {s.get("seasonNumber") for s in m.get("seasons") or [] if s.get("status") == 5}
    return bool(want) and want <= have


def _season_text(req_):
    nums = sorted(s.get("seasonNumber") for s in req_.get("seasons") or [] if s.get("seasonNumber") is not None)
    if not nums:
        return ""
    return f" – sæson {nums[0]}" if len(nums) == 1 else " – sæson " + ", ".join(map(str, nums[:-1])) + f" og {nums[-1]}"


def check_ready():
    """Kaldes hvert 10. minut. Nye klare ønsker kommer på listen. Første gang huskes de gamle, så de ikke kommer på."""
    if not seerr_enabled():
        return 0
    plex_to_cust = {r["plex_user_id"]: r["customer_id"] for r in
                    rows("SELECT plex_user_id, customer_id FROM k_services WHERE service='plex' AND plex_user_id IS NOT NULL")}
    known = {r["request_id"] for r in rows("SELECT request_id FROM b_ready")}
    first = not D["kv_get"]("klar_init")
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=30)).isoformat()
    new = 0
    skip = 0
    while skip < 1000:
        d = _sx("/request", take=100, skip=skip, filter="available", sort="modified")
        res = d.get("results") or []
        for r in res:
            rid = r.get("id")
            if not rid or rid in known or (r.get("updatedAt") or "") < since[:19] and not first:
                continue
            if not _ready(r):
                continue
            pid = (r.get("requestedBy") or {}).get("plexId")
            cid = plex_to_cust.get(pid)
            m = r.get("media") or {}
            title = (_title(r.get("type"), m.get("tmdbId")) if not first else "") + (_season_text(r) if r.get("type") == "tv" and not first else "")
            run("INSERT OR IGNORE INTO b_ready (request_id, customer_id, plex_user_id, title, media, ready_at, status) VALUES (?,?,?,?,?,?,?)",
                (rid, cid, pid, title, r.get("type") or "", iso(), "gammel" if first or not cid else "venter"))
            known.add(rid)
            if not first and cid:
                new += 1
                event(cid, "klar", f"Ønske klar i Plex: {title}")
        skip += 100
        if len(res) < 100:
            break
    if first:
        D["kv_set"]("klar_init", True)
    return new


def ready_list(done=False):
    st = ("sendt", "sprunget") if done else ("venter",)
    items = rows("SELECT r.*, c.name, c.tg, c.fb, c.contact FROM b_ready r JOIN k_customers c ON c.id=r.customer_id"
                 f" WHERE r.status IN ({','.join('?' * len(st))}) ORDER BY r.ready_at DESC LIMIT 200", st)
    t = template(kind="klar")
    out = []
    for i in items:
        c = {"name": i["name"], "tg": i["tg"], "fb": i["fb"], "contact": i["contact"]}
        out.append({"id": i["request_id"], "customer_id": i["customer_id"], "name": i["name"], "title": i["title"], "media": i["media"],
                    "ready_at": i["ready_at"], "status": i["status"], "done_at": i["done_at"],
                    "text": render(t["text"], c, {"titel": i["title"]}), **contact(c)})
    return out


@router.get("/klar")
def ready_get(done: int = 0):
    return {"enabled": seerr_enabled(), "items": ready_list(bool(done)), "template": template(kind="klar"),
            "checked": D["kv_get"]("klar_checked")}


@router.post("/klar/tjek")
def ready_check_now():
    if not seerr_enabled():
        raise HTTPException(400, "Seerr er ikke sat op")
    try:
        n = check_ready()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Seerr svarer ikke ({e.__class__.__name__})") from None
    D["kv_set"]("klar_checked", iso())
    return {**ready_get(), "new": n}


@router.post("/klar/{rid}")
async def ready_action(rid: int, req: Request):
    b = await req.json()
    a = b.get("action")
    r = one("SELECT * FROM b_ready WHERE request_id=?", (rid,))
    if not r:
        raise HTTPException(404, "findes ikke længere")
    if a == "sent":
        run("UPDATE b_ready SET status='sendt', done_at=? WHERE request_id=?", (iso(), rid))
        event(r["customer_id"], "besked", f"Besked sendt: {r['title']} er klar")
    elif a == "skip":
        run("UPDATE b_ready SET status='sprunget', done_at=? WHERE request_id=?", (iso(), rid))
    elif a == "undo":
        run("UPDATE b_ready SET status='venter', done_at=NULL WHERE request_id=?", (rid,))
    else:
        raise HTTPException(400, "ukendt handling")
    return ready_get()


def pending_ready():
    return one("SELECT COUNT(*) n FROM b_ready WHERE status='venter' AND customer_id IS NOT NULL")["n"]


# ---------------------------------------------------------------- ændring for alle (pris)

def _period(v):
    v = str(v or "").strip()[:7]
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v):
        raise HTTPException(400, "vælg måneden, ændringen gælder fra")
    return v


def _period_text(p):
    return f"1. {kunder.MONTHS_DA[int(p[5:7]) - 1]} {p[:4]}"


def price_plan(b):
    """Hvem rammes, og hvad betaler de før og efter? Ændrer intet."""
    svc = str(b.get("service") or "")
    if svc not in dict(kunder.SERVICES):
        raise HTTPException(400, "vælg en tjeneste")
    new = kunder.money(b.get("price"))
    if new <= 0:
        raise HTTPException(400, "skriv den nye pris pr. måned")
    only = b.get("only_price")
    only = kunder.money(only) if only not in (None, "") else None
    frm = _period(b.get("from"))
    fam = bool(b.get("family"))
    out, total_before, total_after = [], 0.0, 0.0
    for c in _customers():
        if c["status"] != "aktiv" or (c["kind"] != "kunde" and not fam):
            continue
        sv = rows("SELECT * FROM k_services WHERE customer_id=? AND active=1", (c["id"],))
        hit = [s for s in sv if s["service"] == svc and (only is None or abs(float(s["price"] or 0) - only) < 0.005)]
        if not hit or all(abs(float(s["price"] or 0) - new) < 0.005 for s in hit):
            continue
        before = kunder.monthly(sv)
        after = before + sum(new - float(s["price"] or 0) for s in hit)
        n = kunder.FREQ.get(c["freq"], 1)
        out.append({"id": c["id"], "name": c["name"], "services": [{"id": s["id"], "label": s["label"] or "", "price": kunder.num(s["price"])} for s in hit],
                    "old_price": kunder.num(hit[0]["price"]), "monthly_before": kunder.num(before), "monthly_after": kunder.num(after),
                    "charge_before": kunder.num(before * n), "charge_after": kunder.num(after * n), "freq": kunder.FREQ_DA.get(c["freq"], ""),
                    **{k: bool(v) for k, v in contact(c).items() if k != "channel"}})
        total_before += before
        total_after += after
    pending = [_period_text(p["from_period"]) + f" ({_kr(p['price_new'])})" for p in
               rows("SELECT * FROM b_price WHERE service=? AND applied_at IS NULL AND cancelled_at IS NULL", (svc,))]
    return {"pending": pending, "service": svc, "service_name": kunder.SERVICE_DA.get(svc, svc), "price": kunder.num(new), "from": frm, "from_text": _period_text(frm),
            "only_price": only, "customers": out, "monthly_before": kunder.num(total_before), "monthly_after": kunder.num(total_after)}


@router.post("/pris/plan")
async def price_preview(req: Request):
    return price_plan(await req.json())


@router.post("/pris")
async def price_confirm(req: Request):
    b = await req.json()
    plan = price_plan(b)
    if not plan["customers"]:
        raise HTTPException(400, "ingen kunder rammes af ændringen")
    want = sorted(int(x) for x in (b.get("confirm_ids") or []))
    if want != sorted(c["id"] for c in plan["customers"]):
        raise HTTPException(409, "listen har ændret sig, siden du så den – vis den igen, før du bekræfter")
    pid = run("INSERT INTO b_price (created, service, price_now, price_new, from_period, customers) VALUES (?,?,?,?,?,?)",
              (iso(), plan["service"], plan["only_price"], plan["price"], plan["from"],
               json.dumps([{"id": c["id"], "services": [s["id"] for s in c["services"]], "old": c["old_price"]} for c in plan["customers"]])))
    qid = None
    if b.get("queue", True):
        t = template(kind="pris")
        data = {c["id"]: {"tjeneste": plan["service_name"], "gammel_pris": _kr(c["old_price"]), "ny_pris": _kr(plan["price"]),
                          "dato": plan["from_text"]} for c in plan["customers"]}
        qid = new_queue(f"Prisændring: {plan['service_name']} fra {plan['from_text']}", t["text"],
                        [{"id": c["id"]} for c in plan["customers"]], kind="pris", template_id=t["id"], ref=pid, data_for=data)
        run("UPDATE b_price SET queue_id=? WHERE id=?", (qid, pid))
    for c in plan["customers"]:
        event(c["id"], "pris", f"Prisændring besluttet: {plan['service_name']} {_kr(c['old_price'])} → {_kr(plan['price'])} fra {plan['from_text']}")
    apply_due()
    return {**prices(), "queue_id": qid}


def apply_due():
    """Ændringer, hvis måned er nået: skift prisen på tjenesterne og regn opkrævninger fra måneden om, som endnu ikke er
    anmodet eller betalt. Opkrævninger før måneden røres aldrig. Kaldes før kundernes egen månedskørsel."""
    cur = kunder.cur_period()
    done = 0
    for p in rows("SELECT * FROM b_price WHERE applied_at IS NULL AND cancelled_at IS NULL AND from_period<=?", (cur,)):
        for c in json.loads(p["customers"] or "[]"):
            for sid in c.get("services") or []:
                run("UPDATE k_services SET price=? WHERE id=? AND customer_id=?", (p["price_new"], sid, c["id"]))
            for ch in rows("SELECT id FROM k_charges WHERE customer_id=? AND period>=? AND requested_at IS NULL AND paid_at IS NULL AND skipped=0",
                           (c["id"], p["from_period"])):
                kunder.recalc_charge(ch["id"])
            event(c["id"], "pris", f"Ny pris på {kunder.SERVICE_DA.get(p['service'], p['service'])}: {_kr(p['price_new'])} pr. måned")
        run("UPDATE b_price SET applied_at=? WHERE id=?", (iso(), p["id"]))
        done += 1
    return done


def prices():
    out = []
    for p in rows("SELECT * FROM b_price ORDER BY id DESC LIMIT 20"):
        cs = json.loads(p["customers"] or "[]")
        out.append({"id": p["id"], "created": p["created"], "service": kunder.SERVICE_DA.get(p["service"], p["service"]),
                    "price_new": kunder.num(p["price_new"]), "from": p["from_period"], "from_text": _period_text(p["from_period"]),
                    "count": len(cs), "applied_at": p["applied_at"], "cancelled_at": p["cancelled_at"], "queue_id": p["queue_id"]})
    return {"changes": out, "services": kunder.SERVICES}


@router.get("/pris")
def price_list():
    return prices()


@router.delete("/pris/{pid}")
def price_cancel(pid: int):
    p = one("SELECT * FROM b_price WHERE id=?", (pid,))
    if not p or p["applied_at"]:
        raise HTTPException(400, "ændringen er allerede gennemført – ret priserne på kundekortene i stedet")
    run("UPDATE b_price SET cancelled_at=? WHERE id=?", (iso(), pid))
    if p["queue_id"]:
        run("UPDATE b_queue SET status='stoppet' WHERE id=?", (p["queue_id"],))
    for c in json.loads(p["customers"] or "[]"):
        event(c["id"], "pris", "Prisændringen blev annulleret")
    return prices()


# ---------------------------------------------------------------- tidslinje

def timeline(cid):
    c = one("SELECT * FROM k_customers WHERE id=?", (cid,))
    if not c:
        raise HTTPException(404, "kunden findes ikke")
    ev = []
    if c["created"]:
        ev.append({"ts": c["created"], "kind": "kunde", "text": "Oprettet i Fangarr"})
    for ch in rows("SELECT * FROM k_charges WHERE customer_id=?", (cid,)):
        p = ch["period"]
        label = f"{kunder.MONTHS_DA[int(p[5:7]) - 1]} {p[:4]}"
        if ch["created"]:
            ev.append({"ts": ch["created"], "kind": "opkraevning", "text": f"Opkrævning for {label}: {_kr(ch['amount'] or 0)}"})
        if ch["requested_at"]:
            ev.append({"ts": ch["requested_at"], "kind": "opkraevning", "text": f"Anmodet om betaling for {label}"})
        if ch["paid_at"]:
            ev.append({"ts": ch["paid_at"], "kind": "betalt", "text": f"Betalt for {label}: {_kr(ch['amount'] or 0)}"})
    try:
        for r in rows("SELECT ts, text FROM s_log WHERE customer_id=?", (cid,)):
            ev.append({"ts": r["ts"], "kind": "oensker", "text": r["text"]})
    except Exception:   # tabellen findes ikke uden Seerr-ønsker
        pass
    for r in rows("SELECT id, ts, kind, text FROM k_events WHERE customer_id=?", (cid,)):
        ev.append({"ts": r["ts"], "kind": r["kind"], "text": r["text"], "id": r["id"] if r["kind"] == "note" else None})
    ev.sort(key=lambda e: e["ts"] or "", reverse=True)
    return {"customer_id": cid, "events": ev[:300]}


@router.get("/tidslinje/{cid}")
def timeline_get(cid: int):
    return timeline(cid)


@router.post("/tidslinje/{cid}")
async def timeline_note(cid: int, req: Request):
    b = await req.json()
    text = str(b.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "skriv noten")
    if not one("SELECT id FROM k_customers WHERE id=?", (cid,)):
        raise HTTPException(404, "kunden findes ikke")
    event(cid, "note", text[:500])
    return timeline(cid)


@router.delete("/tidslinje/note/{eid}")
def timeline_note_delete(eid: int):
    e = one("SELECT * FROM k_events WHERE id=? AND kind='note'", (eid,))
    if not e:
        raise HTTPException(404, "noten findes ikke")
    run("DELETE FROM k_events WHERE id=?", (eid,))
    return timeline(e["customer_id"])


# ---------------------------------------------------------------- det, kunderne leder efter

def seerr_top(days=90, limit=25):
    if not seerr_enabled():
        return None
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()[:19]
    tot = {}
    skip = 0
    while skip < 2000:
        d = _sx("/request", take=100, skip=skip, filter="all", sort="added")
        res = d.get("results") or []
        for r in res:
            if (r.get("createdAt") or "") < since:
                continue
            m = r.get("media") or {}
            key = (r.get("type"), m.get("tmdbId"))
            t = tot.setdefault(key, {"type": r.get("type"), "tmdb": m.get("tmdbId"), "n": 0, "users": set(), "last": "",
                                     "available": m.get("status") == 5})
            t["n"] += 1
            t["users"].add((r.get("requestedBy") or {}).get("id"))
            t["last"] = max(t["last"], r.get("createdAt") or "")
        skip += 100
        if len(res) < 100 or (res and (res[-1].get("createdAt") or "") < since):
            break
    top = sorted(tot.values(), key=lambda t: (-len(t["users"]), -t["n"], t["last"]), reverse=False)[:limit]
    return [{"title": _title(t["type"], t["tmdb"]) or f"TMDB {t['tmdb']}", "type": "Serie" if t["type"] == "tv" else "Film",
             "requests": t["n"], "users": len(t["users"]), "last": t["last"][:10], "available": t["available"]} for t in top]


@router.get("/soegninger")
def searches(days: int = 30):
    days = max(1, min(int(days or 30), 90))
    g = D["guide_summary"](days)
    qs = g.get("searches") or []
    nohits = [q for q in qs if q.get("nohit")]
    known = sum(1 for q in qs if q.get("known"))
    seerr, err = None, ""
    try:
        seerr = seerr_top(90)
    except (httpx.HTTPError, ValueError) as e:
        err = f"Seerr svarer ikke ({e.__class__.__name__})"
    return {"enabled": g.get("enabled"), "days": days, "nohits": sorted(nohits, key=lambda q: (-q["nohit"], q["q"]))[:50],
            "all": qs[:50], "known": known, "total": len(qs), "seerr": seerr, "seerr_error": err}


# ---------------------------------------------------------------- baggrund

def tick():
    """Kaldes hvert minut: prisændringer, hvis måned er nået (før kundernes månedskørsel), ønsker klar hvert 10. minut,
    og én besked om dagen til Stream365 Drift, hvis nogen venter på "dit ønske er klar"."""
    apply_due()
    n = D["now"]()
    st = D["kv_get"]("beskeder_jobs", {}) or {}
    last = st.get("klar_ts") or 0
    if seerr_enabled() and n.timestamp() - last >= 600:
        st["klar_ts"] = n.timestamp()
        D["kv_set"]("beskeder_jobs", st)
        try:
            check_ready()
            D["kv_set"]("klar_checked", iso())
        except (httpx.HTTPError, ValueError) as e:
            D["log"].warning("Ønsker klar: Seerr svarede ikke: %s", e.__class__.__name__)
    s = D["get_settings"]()
    hour = int(s.get("klar_hour", 10))
    today = n.date().isoformat()
    if hour >= 0 and n.hour >= hour and st.get("klar_day") != today:
        st["klar_day"] = today
        D["kv_set"]("beskeder_jobs", st)
        k = pending_ready()
        if k:
            D["telegram_rows"](f"📬 {k} {'kunde venter' if k == 1 else 'kunder venter'} på beskeden om, at deres ønske er klar i Plex.\n\n"
                               "Send dem under Fangarr › Beskeder › Ønsker klar.")


def brief():
    try:
        act = rows("SELECT id FROM b_queue WHERE status='aktiv'")
        waiting = sum(one("SELECT COUNT(*) n FROM b_items WHERE queue_id=? AND status='venter'", (q["id"],))["n"] for q in act)
        return {"klar": pending_ready(), "koe": waiting, "koer": len(act)}
    except Exception:
        return {"klar": 0, "koe": 0, "koer": 0}
