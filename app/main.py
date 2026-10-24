"""Fangarr – fanger nye serier og film og lægger dem i Sonarr/Radarr ud fra regler.

autobrr kalder /webhook/autobrr (eksternt filter). Fangarr slår titlen op i
Sonarr/Radarr, tjekker reglerne og tilføjer titlen (eller logger, hvad den
ville have gjort, i prøvetilstand). Mangler TheTVDB/TMDb oplysninger om
titlen endnu, kan den lægges på en venteliste og prøves igen senere.
Regler og indstillinger redigeres i interfacet på /.
"""

import datetime
import json
import logging
import os
import re
import sqlite3
import threading
import time
import unicodedata

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

DATA_DIR = os.environ.get("DATA_DIR", "/config")
DB_PATH = os.path.join(DATA_DIR, "fangarr.db")
DISK_PATH = os.environ.get("DISK_PATH", "/data")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
LOOP_SECONDS = int(os.environ.get("LOOP_SECONDS", "60"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fangarr")

DEFAULT_SETTINGS = {
    "dry_run": True,            # prøvetilstand: logger kun, tilføjer intet
    "max_series_per_day": 5,
    "max_movies_per_day": 10,
    "max_disk_pct": 85,         # tilføj intet, hvis disken er mere fyldt end dette
    "summary_hour": 9,          # dagligt resumé til Telegram (lokal tid), -1 = fra
    "pass_existing": False,     # svar "match" til autobrr, hvis titlen allerede findes
    "wait_hours": 2,            # venteliste: prøv igen hver X. time
    "wait_days": 14,            # venteliste: giv op efter X dage
    "refresh_hours": 2,         # nye serier: bed Sonarr opdatere oplysninger hver X. time
    "refresh_days": 7,          # … i de første X dage
    "seerr_check": True,        # spring titler over, der er anmodet om eller afvist i Seerr
    "backup_hour": 3,           # natlig eksport til /config/backup (lokal tid), -1 = fra
    "backup_keep": 14,          # antal natlige eksporter der gemmes
}

DEFAULT_TAG = "auto-fangarr"
VERSION = os.environ.get("FANGARR_VERSION") or (open(os.path.join(os.path.dirname(__file__), "VERSION")).read().strip() if os.path.exists(os.path.join(os.path.dirname(__file__), "VERSION")) else "dev")


def now():
    return datetime.datetime.now()


def iso(dt):
    return dt.isoformat(timespec="seconds")


# ---------------------------------------------------------------- database

def db():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = db()
    with con:
        con.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS rules (id INTEGER PRIMARY KEY AUTOINCREMENT, position INTEGER, data TEXT)")
        con.execute(
            "CREATE TABLE IF NOT EXISTS log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, media TEXT,"
            " release TEXT, title TEXT, year INTEGER, decision TEXT, rule TEXT, detail TEXT, dry_run INTEGER)"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS waitlist (id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, media TEXT,"
            " title TEXT, release TEXT, payload TEXT, attempts INTEGER DEFAULT 0, next_try TEXT, last_try TEXT,"
            " status TEXT, reason TEXT, rule TEXT)"
        )
        cols = [r[1] for r in con.execute("PRAGMA table_info(log)").fetchall()]
        if "info" not in cols:
            con.execute("ALTER TABLE log ADD COLUMN info TEXT DEFAULT ''")
        con.execute(
            "CREATE TABLE IF NOT EXISTS added (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, instance TEXT,"
            " media TEXT, arr_id INTEGER, title TEXT, last_refresh TEXT)"
        )
        cols = [r[1] for r in con.execute("PRAGMA table_info(added)").fetchall()]
        for c in ("ext_id", "rule"):
            if c not in cols:
                con.execute(f"ALTER TABLE added ADD COLUMN {c} TEXT DEFAULT ''")
    con.close()


def get_settings():
    con = db()
    rows = con.execute("SELECT key, value FROM settings").fetchall()
    con.close()
    s = dict(DEFAULT_SETTINGS)
    for r in rows:
        try:
            s[r["key"]] = json.loads(r["value"])
        except ValueError:
            pass
    return s


def save_settings(new):
    con = db()
    with con:
        for k, v in new.items():
            if k in DEFAULT_SETTINGS:
                con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, json.dumps(v)))
    con.close()


def get_rules():
    con = db()
    rows = con.execute("SELECT id, data FROM rules ORDER BY position, id").fetchall()
    con.close()
    out = []
    for r in rows:
        d = json.loads(r["data"])
        d["id"] = r["id"]
        out.append(d)
    return out


def write_log(media, release, title, year, decision, rule, detail, dry_run, info=""):
    con = db()
    with con:
        con.execute(
            "INSERT INTO log (ts, media, release, title, year, decision, rule, detail, dry_run, info) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (iso(now()), media, release, title, year or 0, decision, rule or "", detail or "", 1 if dry_run else 0, info or ""),
        )
        con.execute("DELETE FROM log WHERE id NOT IN (SELECT id FROM log ORDER BY id DESC LIMIT 5000)")
    con.close()


def added_today(media, dry=None):
    """Antal tilføjede i dag. I prøvetilstand tælles "ville tilføje", ellers "tilføjet"."""
    if dry is None:
        dry = bool(get_settings()["dry_run"])
    start = iso(now().replace(hour=0, minute=0, second=0, microsecond=0))
    con = db()
    n = con.execute(
        "SELECT COUNT(*) FROM log WHERE media=? AND ts>=? AND decision=?",
        (media, start, "ville tilføje" if dry else "tilføjet"),
    ).fetchone()[0]
    con.close()
    return n


# ---------------------------------------------------------------- Sonarr/Radarr

def load_instances():
    names = [n.strip() for n in os.environ.get("ARR_INSTANCES", "").split(",") if n.strip()]
    inst = {}
    for n in names:
        key = re.sub(r"[^A-Z0-9]", "_", n.upper())
        url = os.environ.get(f"{key}_URL")
        api = os.environ.get(f"{key}_APIKEY")
        typ = os.environ.get(f"{key}_TYPE") or ("radarr" if n.lower().startswith("radarr") else "sonarr")
        if url and api:
            inst[n] = {"name": n, "type": typ, "url": url.rstrip("/"), "apikey": api}
        else:
            log.warning("Instans %s mangler %s_URL eller %s_APIKEY", n, key, key)
    return inst


INSTANCES = load_instances()

_err_lock = threading.Lock()
_err_state = {"active": False, "last_sent": 0.0}


def notify_error(text):
    with _err_lock:
        t = time.time()
        if not _err_state["active"] or t - _err_state["last_sent"] > 3600:
            telegram(f"🚨 Fangarr – fejl\n\n{text}")
            _err_state["last_sent"] = t
        _err_state["active"] = True


def notify_ok():
    with _err_lock:
        if _err_state["active"]:
            _err_state["active"] = False
            telegram("✅ Fangarr – forbindelsen til Sonarr/Radarr er i orden igen.")


def arr(inst, method, path, **kw):
    try:
        r = httpx.request(method, inst["url"] + "/api/v3" + path,
                          headers={"X-Api-Key": inst["apikey"]}, timeout=30, **kw)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        notify_error(f"{inst['name']}: {method} {path} gav {e.response.status_code}\n{e.response.text[:300]}")
        raise
    except httpx.HTTPError as e:
        notify_error(f"{inst['name']}: kan ikke nås ({e.__class__.__name__})")
        raise
    notify_ok()
    return r.json() if r.content else None


def telegram(text):
    tok = os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return
    try:
        httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                   data={"chat_id": chat, "text": text}, timeout=20)
    except httpx.HTTPError as e:
        log.warning("Telegram fejlede: %s", e)


# ---------------------------------------------------------------- titler og regler

def norm(s):
    s = (s or "").lower()
    s = re.sub(r"\(\d{4}\)", " ", s)
    s = s.replace("&", " and ").replace("æ", "ae").replace("ø", "oe").replace("å", "aa")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", s)


LOOSE_DROP = {"and", "og", "the", "der", "die", "das"}


def loose(s):
    """Løsere sammenligning: udgivelser skriver ø som o/oe, å som a/aa, & som og/and."""
    s = (s or "").lower()
    s = re.sub(r"\(\d{4}\)", " ", s)
    s = s.replace("æ", "ae").replace("ø", "o").replace("å", "a").replace("&", " ")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    words = [w for w in re.split(r"[^a-z0-9]+", s) if w and w not in LOOSE_DROP]
    s = "".join(words)
    return s.replace("aa", "a").replace("oe", "o").replace("ae", "e")


def to_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0


def to_float(v):
    try:
        return float(str(v).replace(",", ".").strip())
    except (TypeError, ValueError):
        return 0.0


_lib_cache = {}
_lib_lock = threading.Lock()


def library(inst, media):
    """Alle serier/film i Sonarr/Radarr (gemt i 10 min). Mappenavnet lægges til som ekstra titel,
    så f.eks. "Simon siger (2026)" findes, selvom Sonarr kalder serien "Simon Says"."""
    key = (inst["name"], media)
    with _lib_lock:
        hit = _lib_cache.get(key)
        if hit and time.time() - hit[0] < 600:
            return hit[1]
    items = arr(inst, "GET", "/movie" if media == "movie" else "/series") or []
    for it in items:
        folder = os.path.basename(str(it.get("path") or "").rstrip("/"))
        folder = re.sub(r"\{[^}]*\}|\[[^\]]*\]", " ", folder).strip()
        if folder:
            it["alternateTitles"] = list(it.get("alternateTitles") or []) + [{"title": folder}]
    with _lib_lock:
        _lib_cache[key] = (time.time(), items)
    return items


def tvmaze_tvdb_id(title):
    """TVmaze kender ofte den originale (danske) titel. Giver TheTVDB-nummeret, hvis det findes."""
    if os.environ.get("TVMAZE", "1") == "0":
        return None
    try:
        r = httpx.get("https://api.tvmaze.com/singlesearch/shows", params={"q": title}, timeout=15)
        if r.status_code != 200:
            return None
        d = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    if loose(d.get("name")) != loose(title):
        return None
    return (d.get("externals") or {}).get("thetvdb")


def find_title(inst, media, title, year):
    """Find titlen: 1) Sonarr/Radarr-opslag, 2) dit eget bibliotek (inkl. mappenavne),
    3) for serier: TVmaze -> TheTVDB-nummer -> Sonarr-opslag. Giver (titel, grund, samme-navn, note)."""
    cand, why, same = pick_all(lookup(inst, media, title, year), title, year)
    if cand or same or why != NOT_FOUND:
        return cand, why, same, ""
    try:
        lib = library(inst, media)
    except httpx.HTTPError:
        lib = []  # biblioteket kunne ikke hentes – gå videre til næste trin
    lcand, lwhy, lsame = pick_all(lib, title, year)
    if lcand:
        return lcand, None, [], "fundet i dit bibliotek som \"%s\"" % lcand.get("title")
    if lsame:
        return None, lwhy, lsame, ""
    if media == "series":
        tvdb = tvmaze_tvdb_id(title)
        if tvdb:
            try:
                found = arr(inst, "GET", "/series/lookup", params={"term": f"tvdb:{tvdb}"}) or []
            except httpx.HTTPError:
                found = []
            if len(found) == 1:
                c = found[0]
                if year and to_int(c.get("year")) and abs(to_int(c.get("year")) - year) > 1:
                    return None, f"titlen findes, men året passer ikke ({year})", [], ""
                return c, None, [], "fundet via TVmaze som \"%s\" (TheTVDB %s)" % (c.get("title"), tvdb)
    return None, NOT_FOUND, [], ""


def lookup(inst, media, title, year):
    term = f"{title} {year}" if (media == "movie" and year) else title
    path = "/movie/lookup" if media == "movie" else "/series/lookup"
    return arr(inst, "GET", path, params={"term": term}) or []


NOT_FOUND = "ingen titel passer præcist"


def pick(cands, title, year):
    """Find præcis én titel, der passer. Ellers en forklaring."""
    t, tl = norm(title), loose(title)

    def names(c):
        n = [c.get("title"), c.get("originalTitle")]
        n += [a.get("title") for a in (c.get("alternateTitles") or [])]
        return [x for x in n if x]

    exact = [c for c in cands if any(norm(n) == t for n in names(c))]
    if not exact:
        exact = [c for c in cands if any(loose(n) == tl for n in names(c))]
    if not exact:
        return None, NOT_FOUND
    if year:
        same = [c for c in exact if to_int(c.get("year")) == year]
        if len(same) == 1:
            return same[0], None
        near = [c for c in exact if abs(to_int(c.get("year")) - year) <= 1]
        if len(near) == 1:
            return near[0], None
        if len(same) > 1 or len(near) > 1:
            return None, "flere mulige titler med samme år – sprunget over"
        return None, f"titlen findes, men året passer ikke ({year})"
    if len(exact) == 1:
        return exact[0], None
    return None, f"{len(exact)} mulige titler (intet år i udgivelsen) – sprunget over"


def pick_all(cands, title, year):
    """Som pick, men giver også alle titler med præcis samme navn (til at vælge ud fra reglens årstal)."""
    cand, why = pick(cands, title, year)
    if cand or year:
        return cand, why, []
    t, tl = norm(title), loose(title)
    same = []
    for c in cands:
        n = [c.get("title"), c.get("originalTitle")] + [a.get("title") for a in (c.get("alternateTitles") or [])]
        n = [x for x in n if x]
        if any(norm(x) == t for x in n) or any(loose(x) == tl for x in n):
            same.append(c)
    return None, why, same


def narrow_by_rule_year(rule, same):
    """Flere titler med samme navn: vælg den eneste, der passer til reglens årstal."""
    ymin, ymax = to_int(rule.get("year_min")), to_int(rule.get("year_max"))
    if not (ymin or ymax) or len(same) < 2:
        return None
    fit = [c for c in same if to_int(c.get("year")) and (not ymin or to_int(c.get("year")) >= ymin)
           and (not ymax or to_int(c.get("year")) <= ymax)]
    return fit[0] if len(fit) == 1 else None


def describe(media, c):
    ratings = c.get("ratings") or {}
    if media == "movie":
        rating = to_float((ratings.get("imdb") or {}).get("value")) or to_float((ratings.get("tmdb") or {}).get("value"))
        network = c.get("studio") or ""
    else:
        rating = to_float(ratings.get("value"))
        network = c.get("network") or ""
    return {
        "title": c.get("title") or "",
        "year": to_int(c.get("year")),
        "language": ((c.get("originalLanguage") or {}).get("name")) or "",
        "genres": c.get("genres") or [],
        "network": network,
        "rating": rating,
        "exists": bool(c.get("id")),
    }


def release_ok(rule, release):
    words = [w for w in (rule.get("release_contains") or []) if w]
    if words and not any(w.lower() in release.lower() for w in words):
        return False
    bad = [w for w in (rule.get("release_excludes") or []) if w]
    return not any(w.lower() in release.lower() for w in bad)


def rule_check(rule, inf):
    """(passer, forklaring, mangler_data). mangler_data=True betyder, at TheTVDB/TMDb
    endnu ikke har det felt, reglen kræver – så kan titlen vente."""
    langs = [x.lower() for x in (rule.get("languages") or [])]
    if langs and not inf["language"]:
        return False, "TheTVDB/TMDb mangler sprog", True
    if langs and inf["language"].lower() not in langs:
        return False, f"sprog er {inf['language']}", False
    genres = [g.lower() for g in inf["genres"]]
    want = [g.lower() for g in (rule.get("genres_any") or [])]
    if want and not genres:
        return False, "TheTVDB/TMDb mangler genrer", True
    if want and not any(g in genres for g in want):
        return False, "genre passer ikke (" + ", ".join(inf["genres"]) + ")", False
    bad = [g.lower() for g in (rule.get("genres_none") or [])]
    hit = [g for g in bad if g in genres]
    if hit:
        return False, "udelukket genre: " + ", ".join(hit), False
    ymin, ymax = to_int(rule.get("year_min")), to_int(rule.get("year_max"))
    if (ymin or ymax) and not inf["year"]:
        return False, "TheTVDB/TMDb mangler årstal", True
    if ymin and inf["year"] < ymin:
        return False, f"år {inf['year']} er før {ymin}", False
    if ymax and inf["year"] > ymax:
        return False, f"år {inf['year']} er efter {ymax}", False
    nets = [n.lower() for n in (rule.get("networks_any") or []) if n]
    if nets and not inf["network"]:
        return False, "TheTVDB/TMDb mangler kanal/selskab", True
    if nets and not any(n in inf["network"].lower() for n in nets):
        return False, f"kanal/selskab er {inf['network']}", False
    minr = to_float(rule.get("min_rating"))
    if minr and inf["rating"] < minr:
        return False, f"rating {inf['rating'] or 'ingen'} er under {minr}", False
    return True, "alle krav opfyldt", False


def disk_pct():
    try:
        st = os.statvfs(DISK_PATH)
    except OSError:
        return None
    total = st.f_blocks * st.f_frsize
    if not total:
        return None
    return round(100 * (1 - (st.f_bavail * st.f_frsize) / total), 1)


def clean_tag(label):
    return re.sub(r"[^a-z0-9-]+", "-", (label or "").lower()).strip("-")


def tag_id(inst, label):
    label = clean_tag(label)
    if not label:
        return None
    for t in arr(inst, "GET", "/tag") or []:
        if t.get("label") == label:
            return t["id"]
    return arr(inst, "POST", "/tag", json={"label": label})["id"]


def add_title(inst, media, cand, rule):
    body = {k: v for k, v in cand.items() if k != "id"}
    tags = []
    tid = tag_id(inst, rule.get("tag") or DEFAULT_TAG)
    if tid is not None:
        tags.append(tid)
    body["qualityProfileId"] = to_int(rule.get("quality_profile_id"))
    body["rootFolderPath"] = rule.get("root_folder")
    body["monitored"] = True
    body["tags"] = tags
    search = bool(rule.get("search", True))
    if media == "movie":
        body["minimumAvailability"] = rule.get("minimum_availability") or "released"
        body["addOptions"] = {"searchForMovie": search, "monitor": "movieOnly"}
        return arr(inst, "POST", "/movie", json=body)
    body["seasonFolder"] = True
    body.setdefault("languageProfileId", 1)  # kun brugt af Sonarr v3
    body["addOptions"] = {
        "monitor": rule.get("monitor") or "latestSeason",
        "searchForMissingEpisodes": search,
        "searchForCutoffUnmetEpisodes": False,
    }
    return arr(inst, "POST", "/series", json=body)


def remember_added(inst, media, created, title, rule=""):
    if not created or not created.get("id"):
        return
    ext = created.get("tvdbId") if media == "series" else created.get("tmdbId")
    con = db()
    with con:
        con.execute("INSERT INTO added (ts, instance, media, arr_id, title, last_refresh, ext_id, rule) VALUES (?,?,?,?,?,?,?,?)",
                    (iso(now()), inst["name"], media, created["id"], title, iso(now()), str(ext or ""), rule))
    con.close()


def year_from_release(release, title=""):
    """Find årstallet i et udgivelsesnavn, f.eks. Moana.2026.NORDiC… -> 2026.
    Tager det sidste plausible år, så "Blade.Runner.2049.2017" giver 2017."""
    limit = now().year + 1
    years = [int(y) for y in re.findall(r"(?:^|[.\s_(\[-])((?:19|20)\d{2})(?=$|[.\s_)\]-])", release or "")]
    in_title = {int(y) for y in re.findall(r"(?:19|20)\d{2}", title or "")}
    years = [y for y in years if 1900 <= y <= limit]
    # et årstal, der er en del af titlen ("1923", "Blade Runner 2049"), er ikke udgivelsesåret
    while years and years[0] in in_title and len(years) >= 1:
        if years.count(years[0]) <= 1 and years[0] in in_title:
            years.pop(0)
        else:
            break
    return years[-1] if years else 0


def media_of(p):
    m = str(p.get("media") or "").lower()
    if m in ("series", "serie", "tv", "show"):
        return "series"
    if m in ("movie", "film", "movies"):
        return "movie"
    cat = str(p.get("category") or "").lower()
    if to_int(p.get("season")) > 0 or "tv" in cat or "serie" in cat:
        return "series"
    return "movie"


def process(p, test=False, from_waitlist=False, rules_override=None):
    """Behandl én udgivelse.
    test=True: tilføj intet, log intet, ingen venteliste.
    from_waitlist=True: kaldt af ventelisten – læg ikke på ventelisten igen.
    rules_override: brug disse regler i stedet for de gemte (prøv en regel på historikken).
    p["rule_id"]: kun den regel, og udgivelsesnavnet tjekkes ikke (fulgt fra premierelisten)."""
    s = get_settings()
    dry = test or bool(s["dry_run"])
    media = media_of(p)
    title = str(p.get("title") or "").strip()
    year = to_int(p.get("year"))
    release = str(p.get("release") or p.get("torrentName") or title).strip()
    if not year:
        year = year_from_release(release, title)
    res = {"media": media, "title": title, "year": year, "release": release,
           "decision": "afvist", "rule": "", "detail": "", "match": None, "checks": [], "can_wait": False}

    def done(decision, detail, rule=""):
        res.update(decision=decision, detail=detail, rule=rule)
        if not test:
            m = res["match"] or {}
            info = ""
            if m:
                parts = [f"{m.get('title')} ({m.get('year') or '?'})", m.get("language") or "sprog ukendt",
                         m.get("network") or "kanal ukendt", ", ".join(m.get("genres") or []) or "ingen genrer"]
                if m.get("rating"):
                    parts.append(f"rating {m['rating']}")
                info = " · ".join(parts)
            notes = [c for c in res["checks"] if "fundet i dit bibliotek" in c or "fundet via TVmaze" in c or "valgte den fra" in c]
            if notes:
                info = (info + " · " if info else "") + notes[0].split(": ", 1)[-1]
            write_log(media, release, m.get("title") or title, m.get("year") or year, decision, rule, detail, dry, info)
        return res

    if not title:
        return done("afvist", "ingen titel i udgivelsen")
    only = to_int(p.get("rule_id"))
    if rules_override is not None:
        rules = [r for r in rules_override if r.get("media") == media]
    elif only:
        allr = [r for r in get_rules() if r.get("media") == media]
        rules = [r for r in allr if r.get("id") == only] or [r for r in allr if r.get("name") == p.get("rule_name")]
    else:
        rules = [r for r in get_rules() if r.get("active", True) and r.get("media") == media]
    if not rules:
        return done("afvist", "ingen aktive regler for " + ("film" if media == "movie" else "serier"))

    cache = {}
    wait_rule, wait_why = None, ""
    for r in rules:
        name = r.get("name") or f"regel {r.get('id')}"
        if not only and not release_ok(r, release):
            res["checks"].append(f"{name}: udgivelsesnavnet passer ikke")
            continue
        inst = INSTANCES.get(r.get("instance"))
        if not inst:
            res["checks"].append(f"{name}: instansen '{r.get('instance')}' findes ikke")
            continue
        if inst["name"] not in cache:
            try:
                cache[inst["name"]] = find_title(inst, media, title, year)
            except httpx.HTTPError as e:
                return done("fejl", f"opslag i {inst['name']} fejlede: {e.__class__.__name__}", name)
        cand, why, same, note = cache[inst["name"]]
        if note:
            res["checks"].append(f"{name}: {note}")
        if not cand and same:
            cand = narrow_by_rule_year(r, same)
            if cand:
                res["checks"].append(f"{name}: {len(same)} titler med samme navn – valgte den fra {to_int(cand.get('year'))} ud fra reglens årstal")
        if not cand and same and only:  # fulgt premiere: tag den nyeste, hvis den er fra i år eller sidste år
            newest = max(same, key=lambda x: to_int(x.get("year")))
            if to_int(newest.get("year")) >= now().year - 1:
                cand = newest
                res["checks"].append(f"{name}: {len(same)} titler med samme navn – valgte den nyeste ({to_int(cand.get('year'))})")
        if not cand:
            res["checks"].append(f"{name}: {why}")
            if (why == NOT_FOUND or only) and (r.get("wait") or only) and not wait_rule:
                wait_rule, wait_why = name, why
            continue
        inf = describe(media, cand)
        res["match"] = inf
        if inf["exists"]:
            return done("findes allerede", f"findes allerede i {inst['name']}", name)
        if only:  # fulgt fra premierelisten: du har selv valgt titlen, så reglens krav springes over
            ok, why, missing = True, "fulgt manuelt – reglens krav springes over", []
        else:
            ok, why, missing = rule_check(r, inf)
        res["checks"].append(f"{name}: {why}")
        if not ok:
            if missing and r.get("wait") and not wait_rule:
                wait_rule, wait_why = name, why
            continue
        seerr = seerr_status(media, cand) if s.get("seerr_check") else None
        if seerr == "declined":
            return done("afvist i Seerr", "en anmodning på titlen er afvist i Seerr", name)
        if seerr == "pending":
            return done("anmodet i Seerr", "titlen venter på godkendelse i Seerr", name)
        limit = to_int(s["max_movies_per_day"] if media == "movie" else s["max_series_per_day"])
        if not test and added_today(media, dry) >= limit:
            return done("loft nået", f"dagens loft på {limit} er nået", name)
        pct = disk_pct()
        if pct is None and not test:
            return done("afvist", f"kan ikke læse diskplads på {DISK_PATH}", name)
        if pct is not None and pct > to_float(s["max_disk_pct"]):
            if not test:
                return done("for lidt plads", f"disken er {pct} % fyldt (grænse {s['max_disk_pct']} %)", name)
            res["checks"].append(f"bemærk: disken er {pct} % fyldt – i drift ville den blive stoppet af pladsgrænsen")
        if dry:
            return done("ville tilføje", f"til {inst['name']} › {r.get('root_folder')}" + (" (test)" if test else " (prøvetilstand)"), name)
        try:
            created = add_title(inst, media, cand, r)
        except httpx.HTTPError as e:
            return done("fejl", f"tilføjelse i {inst['name']} fejlede: {e.__class__.__name__}", name)
        remember_added(inst, media, created, inf["title"], name)
        return done("tilføjet", f"til {inst['name']} › {r.get('root_folder')}", name)

    if wait_rule:
        res["can_wait"] = True
        reason = wait_why
        if test:
            return done("venteliste", "kommer på ventelisten, til TheTVDB/TMDb har oplysningerne", wait_rule)
        if from_waitlist:
            res.update(decision="venter stadig", detail=reason, rule=wait_rule)
            return res
        add_to_waitlist(media, title, release, p, wait_rule, reason)
        return done("venteliste", "venter på TheTVDB/TMDb: " + reason, wait_rule)
    return done("afvist", "; ".join(res["checks"]) or "ingen regel passede")


# ---------------------------------------------------------------- Seerr

SEERR_URL = (os.environ.get("SEERR_URL") or "").rstrip("/")
SEERR_APIKEY = os.environ.get("SEERR_APIKEY") or ""


def seerr_status(media, cand):
    """'declined', 'pending' eller None. Kræver tmdbId (Radarr har altid, Sonarr v4 som regel)."""
    if not SEERR_URL or not SEERR_APIKEY:
        return None
    tmdb = to_int(cand.get("tmdbId"))
    if not tmdb:
        return None
    path = f"/api/v1/{'movie' if media == 'movie' else 'tv'}/{tmdb}"
    try:
        r = httpx.get(SEERR_URL + path, headers={"X-Api-Key": SEERR_APIKEY}, timeout=15)
        if r.status_code != 200:
            return None
        reqs = ((r.json().get("mediaInfo") or {}).get("requests")) or []
    except (httpx.HTTPError, ValueError):
        return None
    st = [to_int(q.get("status")) for q in reqs]
    if 3 in st and not (2 in st):
        return "declined"
    if 1 in st:
        return "pending"
    return None


# ---------------------------------------------------------------- venteliste

def add_to_waitlist(media, title, release, payload, rule, reason, created=None):
    key = loose(title)
    con = db()
    with con:
        rows = con.execute("SELECT id, title FROM waitlist WHERE status='venter' AND media=?", (media,)).fetchall()
        for r in rows:
            if loose(r["title"]) == key:
                con.execute("UPDATE waitlist SET release=?, reason=? WHERE id=?", (release, reason, r["id"]))
                break
        else:
            hours = to_int(get_settings()["wait_hours"]) or 2
            con.execute(
                "INSERT INTO waitlist (created, media, title, release, payload, attempts, next_try, status, reason, rule)"
                " VALUES (?,?,?,?,?,0,?,'venter',?,?)",
                (iso(created or now()), media, title, release, json.dumps(payload), iso(now() + datetime.timedelta(hours=hours)), reason, rule),
            )
    con.close()


def retry_waitlist_item(row, s):
    """Prøv én ventende titel igen. Returnerer den nye status."""
    p = json.loads(row["payload"])
    res = process(p, from_waitlist=True)
    d = res["decision"]
    hours = to_int(s["wait_hours"]) or 2
    created = datetime.datetime.fromisoformat(row["created"])
    if d in ("tilføjet", "ville tilføje", "findes allerede"):
        status, reason = ("klar", f"{d}: {res['detail']}")
    elif d in ("venter stadig", "loft nået", "for lidt plads", "fejl"):
        status, reason = ("venter", res["detail"])
        if now() - created > datetime.timedelta(days=to_int(s["wait_days"]) or 14):
            status, reason = ("udløbet", "gav op efter %s dage: %s" % (s["wait_days"], res["detail"]))
    else:  # afvist: data er kommet, men reglen passer ikke
        status, reason = ("afvist", res["detail"])
    con = db()
    with con:
        con.execute("UPDATE waitlist SET attempts=attempts+1, last_try=?, next_try=?, status=?, reason=? WHERE id=?",
                    (iso(now()), iso(now() + datetime.timedelta(hours=hours)), status, reason, row["id"]))
    con.close()
    if status == "udløbet":
        write_log(row["media"], row["release"], row["title"], 0, "udløbet", row["rule"], reason, bool(s["dry_run"]))
    return status


def get_waitlist():
    con = db()
    rows = con.execute("SELECT * FROM waitlist ORDER BY CASE status WHEN 'venter' THEN 0 ELSE 1 END, id DESC LIMIT 500").fetchall()
    con.close()
    out = []
    for r in rows:
        d = dict(r)
        d.pop("payload", None)
        out.append(d)
    return out


# ---------------------------------------------------------------- baggrundsjob

def refresh_new_series(s):
    """Bed Sonarr opdatere nye serier oftere, så afsnit fra TheTVDB kommer hurtigere med."""
    hours = to_int(s["refresh_hours"])
    days = to_int(s["refresh_days"])
    if hours <= 0 or days <= 0:
        return
    since = iso(now() - datetime.timedelta(days=days))
    due = iso(now() - datetime.timedelta(hours=hours))
    con = db()
    rows = con.execute("SELECT * FROM added WHERE media='series' AND ts>=? AND last_refresh<=?", (since, due)).fetchall()
    con.close()
    for r in rows:
        inst = INSTANCES.get(r["instance"])
        if not inst:
            continue
        try:
            arr(inst, "POST", "/command", json={"name": "RefreshSeries", "seriesId": r["arr_id"]})
        except httpx.HTTPError:
            continue
        con = db()
        with con:
            con.execute("UPDATE added SET last_refresh=? WHERE id=?", (iso(now()), r["id"]))
        con.close()


def daily_summary(s):
    since = iso(now() - datetime.timedelta(days=1))
    con = db()
    rows = con.execute(
        "SELECT media, title, year, decision FROM log WHERE ts>=? AND decision IN ('tilføjet','ville tilføje') ORDER BY id",
        (since,)).fetchall()
    fejl = con.execute("SELECT COUNT(*) FROM log WHERE ts>=? AND decision='fejl'", (since,)).fetchone()[0]
    venter = con.execute("SELECT COUNT(*) FROM waitlist WHERE status='venter'").fetchone()[0]
    udl = con.execute("SELECT COUNT(*) FROM log WHERE ts>=? AND decision='udløbet'", (since,)).fetchone()[0]
    con.close()
    if not (rows or fejl or udl):
        return
    lines = [f"{'🎬' if r['media'] == 'movie' else '📺'} {r['title']} ({r['year'] or '?'}) – {r['decision']}" for r in rows[:30]]
    more = f"\n… og {len(rows) - 30} mere" if len(rows) > 30 else ""
    mode = " (prøvetilstand)" if s.get("dry_run") else ""
    txt = f"📦 Fangarr – sidste døgn{mode}\n\n" + ("\n".join(lines) or "Intet tilføjet.") + more
    txt += f"\n\n⏳ {venter} på ventelisten"
    if udl:
        txt += f", {udl} opgivet (ikke på TheTVDB/TMDb i tide)"
    if fejl:
        txt += f"\n⚠️ {fejl} fejl – se loggen i Fangarr."
    telegram(txt)


_last_backup = {}


def background_loop():
    last_summary = None
    while True:
        try:
            s = get_settings()
            con = db()
            due = con.execute("SELECT * FROM waitlist WHERE status='venter' AND next_try<=? ORDER BY next_try LIMIT 20",
                              (iso(now()),)).fetchall()
            con.close()
            for row in due:
                retry_waitlist_item(row, s)
            refresh_new_series(s)
            bh = to_int(s.get("backup_hour"))
            n = now()
            if bh >= 0 and n.hour == bh and _last_backup.get("date") != n.date():
                _last_backup["date"] = n.date()
                nightly_backup(s)
            hour = to_int(s.get("summary_hour"))
            if hour >= 0 and n.hour == hour and last_summary != n.date():
                last_summary = n.date()
                daily_summary(s)
        except Exception as e:  # baggrundsjobbet må aldrig stoppe appen
            log.warning("Baggrundsjob fejlede: %s", e)
        time.sleep(LOOP_SECONDS)


# ---------------------------------------------------------------- autobrr-filtre

AUTOBRR_URL = (os.environ.get("AUTOBRR_URL") or "").rstrip("/")
AUTOBRR_APIKEY = os.environ.get("AUTOBRR_APIKEY") or ""
FANGARR_URL = (os.environ.get("FANGARR_URL") or "http://fangarr:8080").rstrip("/")

AUTOBRR_DEFAULTS = {
    "series": {"name": "Fangarr – serier", "categories": "*TV*,*Serie*", "seasons": "1", "priority": 10},
    "movie": {"name": "Fangarr – film", "categories": "*Movie*,*Film*", "seasons": "", "priority": 10},
}


def autobrr(method, path, **kw):
    if not AUTOBRR_URL or not AUTOBRR_APIKEY:
        raise HTTPException(400, "autobrr er ikke sat op (AUTOBRR_URL og AUTOBRR_APIKEY i fangarr.env)")
    try:
        r = httpx.request(method, AUTOBRR_URL + "/api" + path, headers={"X-API-Token": AUTOBRR_APIKEY}, timeout=30, **kw)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"autobrr svarede {e.response.status_code}: {e.response.text[:200]}")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"kan ikke nå autobrr ({e.__class__.__name__})")
    return r.json() if r.content else None


def autobrr_saved(media):
    """Gemte valg for autobrr-filteret (navn, kategorier, sæsoner, trackere)."""
    con = db()
    row = con.execute("SELECT value FROM settings WHERE key=?", (f"autobrr_{media}",)).fetchone()
    con.close()
    saved = {}
    if row:
        try:
            saved = json.loads(row["value"]) or {}
        except ValueError:
            saved = {}
    out = {**AUTOBRR_DEFAULTS[media], "indexers": []}
    out.update({k: v for k, v in saved.items() if k in ("name", "categories", "seasons", "indexers")})
    return out


def autobrr_save(media, opts):
    keep = {k: opts[k] for k in ("name", "categories", "seasons", "indexers") if k in opts and opts[k] is not None}
    cur = autobrr_saved(media)
    cur.update(keep)
    con = db()
    with con:
        con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (f"autobrr_{media}", json.dumps(cur)))
    con.close()


def release_words(media):
    """Ord fra reglernes "skal indeholde" – bruges som autobrrs Match releases."""
    words = []
    for r in get_rules():
        if not r.get("active", True) or r.get("media") != media:
            continue
        if not r.get("release_contains"):
            return []  # en regel tager alle udgivelser – autobrr må ikke begrænse
        for w in r["release_contains"]:
            if w.lower() not in [x.lower() for x in words]:
                words.append(w)
    return words


def webhook_data(media):
    return ('{"media":"%s","title":"{{ .Title }}","year":"{{ .Year }}","season":"{{ .Season }}",'
            '"release":"{{ .TorrentName }}","category":"{{ .Category }}","indexer":"{{ .Indexer }}"}') % media


def filter_fields(media, opts):
    d = {**AUTOBRR_DEFAULTS[media], **{k: v for k, v in (opts or {}).items() if v is not None}}
    words = release_words(media)
    fields = {
        "name": str(d["name"]).strip() or AUTOBRR_DEFAULTS[media]["name"],
        "enabled": True,
        "priority": to_int(d.get("priority")),
        "announce_types": ["NEW"],
        "match_releases": ",".join(f"*{w}*" for w in words),
        "match_categories": str(d.get("categories") or ""),
        "seasons": str(d.get("seasons") or "") if media == "series" else "",
        "episodes": "",
        "resolutions": [], "codecs": [], "sources": [], "containers": [],
        "match_hdr": [], "except_hdr": [], "match_other": [], "except_other": [],
        "origins": [], "except_origins": [], "match_language": [], "except_language": [],
        "external": [{
            "name": "Fangarr", "index": 0, "type": "WEBHOOK", "enabled": True,
            "webhook_host": FANGARR_URL + "/webhook/autobrr", "webhook_method": "POST",
            "webhook_data": webhook_data(media), "webhook_headers": "",
            "webhook_expect_status": 200, "on_error": "REJECT",
        }],
    }
    return fields


# ---------------------------------------------------------------- web

app = FastAPI(title="Fangarr", docs_url=None, redoc_url=None)


@app.on_event("startup")
def startup():
    init_db()
    threading.Thread(target=background_loop, daemon=True).start()
    log.info("Fangarr startet. Instanser: %s", ", ".join(INSTANCES) or "ingen")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/webhook/autobrr")
async def webhook(req: Request):
    try:
        p = await req.json()
    except ValueError:
        raise HTTPException(400, "forventede JSON")
    res = await run_in_threadpool(process, p)
    s = get_settings()
    log.info("%s | %s | %s | %s", res["media"], res["release"], res["decision"], res["detail"])
    if res["decision"] == "findes allerede" and s.get("pass_existing"):
        return JSONResponse(res, status_code=200)   # autobrr må fortsætte
    return JSONResponse(res, status_code=202)        # håndteret – autobrr stopper


@app.get("/api/state")
def state():
    con = db()
    venter = con.execute("SELECT COUNT(*) FROM waitlist WHERE status='venter'").fetchone()[0]
    con.close()
    return {
        "settings": get_settings(),
        "rules": get_rules(),
        "instances": [{"name": i["name"], "type": i["type"]} for i in INSTANCES.values()],
        "disk_pct": disk_pct(),
        "today": {"series": added_today("series"), "movie": added_today("movie")},
        "waiting": venter,
        "features": {"tracearr": bool(TRACEARR_URL and TRACEARR_APIKEY), "seerr": bool(SEERR_URL and SEERR_APIKEY),
                     "autobrr": bool(AUTOBRR_URL and AUTOBRR_APIKEY), "version": VERSION},
    }


@app.get("/api/instance/{name}/options")
def instance_options(name: str):
    inst = INSTANCES.get(name)
    if not inst:
        raise HTTPException(404, "ukendt instans")
    try:
        profiles = arr(inst, "GET", "/qualityprofile") or []
        roots = arr(inst, "GET", "/rootfolder") or []
    except httpx.HTTPError as e:
        raise HTTPException(502, f"kan ikke hente fra {name}: {e.__class__.__name__}")
    return {
        "profiles": [{"id": p["id"], "name": p["name"]} for p in profiles],
        "root_folders": [r["path"] for r in roots],
    }


@app.put("/api/settings")
async def put_settings(req: Request):
    body = await req.json()
    clean = {}
    for k, default in DEFAULT_SETTINGS.items():
        if k in body:
            v = body[k]
            clean[k] = bool(v) if isinstance(default, bool) else to_int(v)
    save_settings(clean)
    return get_settings()


RULE_FIELDS = {
    "name": str, "active": bool, "media": str, "instance": str,
    "release_contains": list, "release_excludes": list, "languages": list,
    "genres_any": list, "genres_none": list, "networks_any": list,
    "year_min": int, "year_max": int, "min_rating": float,
    "root_folder": str, "quality_profile_id": int, "monitor": str,
    "minimum_availability": str, "tag": str, "search": bool, "wait": bool,
}


def clean_rule(body, strict=True):
    out = {}
    for k, t in RULE_FIELDS.items():
        v = body.get(k)
        if t is list:
            if isinstance(v, str):
                v = v.split(",")
            out[k] = [str(x).strip() for x in (v or []) if str(x).strip()]
        elif t is bool:
            out[k] = bool(v) if v is not None else (k in ("active", "search"))
        elif t is int:
            out[k] = to_int(v)
        elif t is float:
            out[k] = to_float(v)
        else:
            out[k] = str(v or "").strip()
    out["tag"] = clean_tag(out["tag"]) or DEFAULT_TAG
    if out["media"] not in ("series", "movie"):
        raise HTTPException(400, "medietype skal være serier eller film")
    if not out["name"]:
        raise HTTPException(400, "reglen skal have et navn")
    if out["instance"] not in INSTANCES:
        raise HTTPException(400, "vælg en Sonarr/Radarr")
    if strict and (not out["root_folder"] or not out["quality_profile_id"]):
        raise HTTPException(400, "vælg mappe og kvalitetsprofil")
    return out


@app.post("/api/rules")
async def create_rule(req: Request):
    data = clean_rule(await req.json())
    con = db()
    with con:
        pos = con.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM rules").fetchone()[0]
        con.execute("INSERT INTO rules (position, data) VALUES (?, ?)", (pos, json.dumps(data)))
    con.close()
    return get_rules()


@app.put("/api/rules/{rid}")
async def update_rule(rid: int, req: Request):
    data = clean_rule(await req.json())
    con = db()
    with con:
        n = con.execute("UPDATE rules SET data=? WHERE id=?", (json.dumps(data), rid)).rowcount
    con.close()
    if not n:
        raise HTTPException(404, "reglen findes ikke")
    return get_rules()


@app.delete("/api/rules/{rid}")
def delete_rule(rid: int):
    con = db()
    with con:
        con.execute("DELETE FROM rules WHERE id=?", (rid,))
    con.close()
    return get_rules()


@app.post("/api/rules/order")
async def order_rules(req: Request):
    ids = (await req.json()).get("ids") or []
    con = db()
    with con:
        for i, rid in enumerate(ids):
            con.execute("UPDATE rules SET position=? WHERE id=?", (i, to_int(rid)))
    con.close()
    return get_rules()


@app.get("/api/log")
def get_log(limit: int = 300):
    con = db()
    rows = con.execute("SELECT * FROM log ORDER BY id DESC LIMIT ?", (min(max(limit, 1), 2000),)).fetchall()
    con.close()
    return [dict(r) for r in rows]


@app.get("/api/log/summary")
def log_summary():
    since = iso(now() - datetime.timedelta(days=1))
    con = db()
    rows = con.execute("SELECT decision, COUNT(*) AS n FROM log WHERE ts>=? GROUP BY decision", (since,)).fetchall()
    con.close()
    return {r["decision"]: r["n"] for r in rows}


@app.post("/api/test")
async def test(req: Request):
    p = await req.json()
    return await run_in_threadpool(process, p, True)


@app.get("/api/waitlist")
def waitlist():
    return get_waitlist()


@app.post("/api/waitlist/{wid}/retry")
async def waitlist_retry(wid: int):
    con = db()
    row = con.execute("SELECT * FROM waitlist WHERE id=?", (wid,)).fetchone()
    con.close()
    if not row:
        raise HTTPException(404, "findes ikke på ventelisten")
    if row["status"] != "venter":
        con = db()
        with con:  # giv en afsluttet titel en ny chance
            con.execute("UPDATE waitlist SET status='venter', created=? WHERE id=?", (iso(now()), wid))
        con.close()
        con = db()
        row = con.execute("SELECT * FROM waitlist WHERE id=?", (wid,)).fetchone()
        con.close()
    await run_in_threadpool(retry_waitlist_item, row, get_settings())
    return get_waitlist()


@app.delete("/api/waitlist/{wid}")
def waitlist_delete(wid: int):
    con = db()
    with con:
        con.execute("DELETE FROM waitlist WHERE id=?", (wid,))
    con.close()
    return get_waitlist()


@app.get("/api/autobrr")
def autobrr_status():
    out = {"configured": bool(AUTOBRR_URL and AUTOBRR_APIKEY), "url": AUTOBRR_URL, "fangarr_url": FANGARR_URL,
           "defaults": {"series": autobrr_saved("series"), "movie": autobrr_saved("movie")}, "words": {"series": release_words("series"), "movie": release_words("movie")},
           "indexers": [], "filters": [], "error": ""}
    if out["configured"]:
        try:
            out["indexers"] = [{"id": i["id"], "name": i["name"], "enabled": i.get("enabled", True)}
                               for i in (autobrr("GET", "/indexer") or []) if not i.get("archived")]
            out["filters"] = [{"id": f["id"], "name": f["name"]} for f in (autobrr("GET", "/filters") or [])]
        except HTTPException as e:
            out["error"] = e.detail
    return out


@app.post("/api/autobrr/export")
async def autobrr_export(req: Request):
    b = await req.json()
    media = "movie" if b.get("media") == "movie" else "series"
    autobrr_save(media, b)
    f = filter_fields(media, b)
    name = f.pop("name")
    return {"name": name, "version": "1.0", "data": f}


@app.post("/api/autobrr/apply")
async def autobrr_apply(req: Request):
    """Opret eller opdatér Fangarr-filteret i autobrr. Andre indstillinger på et
    eksisterende filter (handlinger, notifikationer, størrelser) bevares."""
    b = await req.json()
    media = "movie" if b.get("media") == "movie" else "series"
    f = filter_fields(media, b)
    ids = [to_int(x) for x in (b.get("indexers") or []) if to_int(x)]
    if not ids:
        raise HTTPException(400, "vælg mindst én tracker")
    f["indexers"] = [{"id": i} for i in ids]

    def run():
        existing = [x for x in (autobrr("GET", "/filters") or []) if x.get("name") == f["name"]]
        if existing:
            full = autobrr("GET", f"/filters/{existing[0]['id']}")
            full.update(f)
            autobrr("PUT", f"/filters/{full['id']}", json=full)
            return {"action": "opdateret", "id": full["id"], "name": f["name"]}
        created = autobrr("POST", "/filters", json={k: v for k, v in f.items() if k not in ("external", "indexers")})
        full = {**created, **f}
        autobrr("PUT", f"/filters/{created['id']}", json=full)
        return {"action": "oprettet", "id": created["id"], "name": f["name"]}

    autobrr_save(media, {**b, "indexers": ids})
    return await run_in_threadpool(run)



# ================================================================ baggrundsjob til UI

import fnmatch
import uuid
from concurrent.futures import ThreadPoolExecutor

_jobs = {}


def new_job(kind):
    jid = uuid.uuid4().hex[:10]
    _jobs[jid] = {"id": jid, "kind": kind, "status": "kører", "total": 0, "done": 0, "results": [],
                  "note": "", "error": "", "started": iso(now())}
    for k in [k for k, v in _jobs.items() if v["kind"] == kind and k != jid][:-3]:
        _jobs.pop(k, None)  # behold kun de nyeste
    return _jobs[jid]


def parse_ts(v):
    try:
        d = datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d.astimezone().replace(tzinfo=None) if d.tzinfo else d
    except ValueError:
        return None


# ================================================================ #3 prøv en regel på historikken

def category_matches(media, category):
    globs = [g.strip().lower() for g in str(autobrr_saved(media).get("categories") or "").split(",") if g.strip()]
    return bool(category) and any(fnmatch.fnmatch(category.lower(), g) for g in globs)


def fetch_history(days, limit=4000):
    """Udgivelser fra autobrr (dem der har passet et filter) + Fangarrs egen log."""
    cutoff = now() - datetime.timedelta(days=days)
    out, note = [], []
    if AUTOBRR_URL and AUTOBRR_APIKEY:
        offset = 0
        try:
            while len(out) < limit:
                d = autobrr("GET", "/release", params={"limit": 500, "offset": offset}) or {}
                data = d.get("data") or []
                stop = False
                for r in data:
                    ts = parse_ts(r.get("timestamp"))
                    if ts and ts < cutoff:
                        stop = True
                        break
                    out.append({"source": "autobrr", "ts": iso(ts) if ts else "", "title": r.get("title") or "",
                                "year": to_int(r.get("year")), "season": to_int(r.get("season")),
                                "release": r.get("name") or "", "category": r.get("category") or "",
                                "indexer": (r.get("indexer") or {}).get("name") or ""})
                if stop or len(data) < 500:
                    break
                offset += 500
        except HTTPException as e:
            note.append(f"autobrr: {e.detail}")
    else:
        note.append("autobrr er ikke forbundet – kun Fangarrs egen log bruges")
    con = db()
    for r in con.execute("SELECT ts, media, release, title, year FROM log WHERE ts>=? ORDER BY id DESC", (iso(cutoff),)).fetchall():
        out.append({"source": "fangarr", "ts": r["ts"], "title": r["title"], "year": r["year"], "season": 0,
                    "release": r["release"], "category": "", "media": r["media"], "indexer": ""})
    con.close()
    return out, note


def run_simulation(job, rule, days):
    try:
        media = rule["media"]
        items, note = fetch_history(days)
        mine = []
        for it in items:
            if it.get("media"):
                ok = it["media"] == media
            elif it["category"]:
                ok = category_matches(media, it["category"])
            else:
                ok = (it["season"] > 0) == (media == "series")
            if ok:
                mine.append(it)
        groups = {}
        skipped = 0
        for it in mine:
            if not release_ok(rule, it["release"]):
                skipped += 1
                continue
            key = (loose(it["title"]), it["year"] if media == "movie" else 0)
            g = groups.setdefault(key, {**it, "count": 0})
            g["count"] += 1
        uniq = list(groups.values())
        cap = 300
        if len(uniq) > cap:
            note.append(f"kun de {cap} nyeste titler er testet (der var {len(uniq)})")
            uniq = uniq[:cap]
        job["total"] = len(uniq)
        note.append(f"{len(mine)} udgivelser af typen, {skipped} sorteret fra på udgivelsesnavnet, {len(uniq)} titler slået op")
        job["note"] = "; ".join(note)

        def one(it):
            r = process({"media": media, "title": it["title"], "year": it["year"] or "", "release": it["release"]},
                        test=True, rules_override=[rule])
            job["done"] += 1
            return {"title": it["title"], "year": it["year"], "release": it["release"], "count": it["count"],
                    "source": it["source"], "ts": it["ts"], "decision": r["decision"], "detail": r["detail"],
                    "match": r["match"], "checks": r["checks"]}

        with ThreadPoolExecutor(max_workers=4) as ex:
            job["results"] = list(ex.map(one, uniq))
        job["status"] = "færdig"
    except Exception as e:  # vis fejlen i UI i stedet for at stoppe
        job["status"] = "fejl"
        job["error"] = f"{e.__class__.__name__}: {e}"


@app.post("/api/simulate")
async def simulate(req: Request):
    b = await req.json()
    if b.get("rule_id"):
        rule = next((r for r in get_rules() if r["id"] == to_int(b["rule_id"])), None)
        if not rule:
            raise HTTPException(404, "reglen findes ikke")
    else:
        rule = clean_rule(b.get("rule") or {}, strict=False)
    rule = {**rule, "active": True}
    days = max(1, min(30, to_int(b.get("days")) or 7))
    job = new_job("simulate")
    job["rule"] = rule.get("name")
    job["days"] = days
    threading.Thread(target=run_simulation, args=(job, rule, days), daemon=True).start()
    return job


@app.get("/api/jobs/{jid}")
def job_status(jid: str):
    job = _jobs.get(jid)
    if not job:
        raise HTTPException(404, "ukendt job")
    return job


# ================================================================ #12 eksport, import og natlig backup

BACKUP_DIR = os.path.join(DATA_DIR, "backup")


def export_data():
    con = db()
    settings = {r["key"]: json.loads(r["value"]) for r in con.execute("SELECT key, value FROM settings").fetchall()}
    waiting = [dict(r) for r in con.execute("SELECT * FROM waitlist WHERE status='venter'").fetchall()]
    con.close()
    rules = get_rules()
    for r in rules:
        r.pop("id", None)
    return {"fangarr_export": 1, "created": iso(now()), "settings": settings, "rules": rules, "waitlist": waiting}


def import_data(d):
    if not isinstance(d, dict) or d.get("fangarr_export") != 1:
        raise HTTPException(400, "filen er ikke en Fangarr-eksport")
    rules = [clean_rule(r, strict=False) for r in (d.get("rules") or [])]
    con = db()
    with con:
        for k, v in (d.get("settings") or {}).items():
            con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, json.dumps(v)))
        con.execute("DELETE FROM rules")
        for i, r in enumerate(rules):
            con.execute("INSERT INTO rules (position, data) VALUES (?, ?)", (i, json.dumps(r)))
        added_w = 0
        for w in d.get("waitlist") or []:
            if not con.execute("SELECT 1 FROM waitlist WHERE status='venter' AND title=? AND media=?",
                               (w.get("title"), w.get("media"))).fetchone():
                con.execute("INSERT INTO waitlist (created, media, title, release, payload, attempts, next_try, status, reason, rule)"
                            " VALUES (?,?,?,?,?,?,?,'venter',?,?)",
                            (w.get("created"), w.get("media"), w.get("title"), w.get("release"), w.get("payload") or "{}",
                             to_int(w.get("attempts")), w.get("next_try") or iso(now()), w.get("reason") or "", w.get("rule") or ""))
                added_w += 1
    con.close()
    return {"rules": len(rules), "settings": len(d.get("settings") or {}), "waitlist": added_w}


def nightly_backup(s):
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        path = os.path.join(BACKUP_DIR, f"fangarr-{now():%Y-%m-%d}.json")
        with open(path + ".tmp", "w") as f:
            json.dump(export_data(), f, ensure_ascii=False, indent=1)
        os.replace(path + ".tmp", path)
        keep = max(1, to_int(s.get("backup_keep")) or 14)
        files = sorted(x for x in os.listdir(BACKUP_DIR) if x.startswith("fangarr-") and x.endswith(".json"))
        for old in files[:-keep]:
            os.remove(os.path.join(BACKUP_DIR, old))
    except OSError as e:
        telegram(f"🚨 Fangarr – natlig eksport fejlede\n\n{e}")


@app.get("/api/export")
def export_download():
    return JSONResponse(export_data(), headers={"Content-Disposition": f'attachment; filename="fangarr-{now():%Y-%m-%d}.json"'})


@app.post("/api/import")
async def import_upload(req: Request):
    try:
        d = await req.json()
    except ValueError:
        raise HTTPException(400, "filen kunne ikke læses som JSON")
    return import_data(d)


@app.get("/api/backups")
def backups():
    try:
        files = sorted((x for x in os.listdir(BACKUP_DIR) if x.endswith(".json")), reverse=True)
    except OSError:
        files = []
    return [{"name": x, "size": os.path.getsize(os.path.join(BACKUP_DIR, x))} for x in files]


@app.post("/api/backups/now")
def backup_now():
    nightly_backup(get_settings())
    return backups()


# ================================================================ #8 statistik med Tracearr

TRACEARR_URL = (os.environ.get("TRACEARR_URL") or "").rstrip("/")
TRACEARR_APIKEY = os.environ.get("TRACEARR_APIKEY") or ""
_stats = {"result": None}


def tracearr_stats(media, ext_id):
    """Afspilninger fra Tracearr. None = ukendt (fejl), 0-tal = ingen afspilninger."""
    if not TRACEARR_URL or not TRACEARR_APIKEY or not ext_id:
        return None
    ref = f"show:tvdb:{ext_id}" if media == "series" else f"movie:tmdb:{ext_id}"
    try:
        r = httpx.get(f"{TRACEARR_URL}/api/v2/public/media/{ref}/stats",
                      headers={"Authorization": f"Bearer {TRACEARR_APIKEY}"}, timeout=20, follow_redirects=False)
    except httpx.HTTPError:
        return None
    if r.status_code == 404:
        return {"plays": 0, "users": 0, "plays_30": 0, "hours": 0.0}
    if r.status_code != 200:
        return None
    try:
        w = r.json().get("windows") or {}
    except ValueError:
        return None
    a = (w.get("all_time") or {}).get("combined") or {}
    l30 = (w.get("last_30") or {}).get("combined") or {}
    return {"plays": to_int(a.get("plays")), "users": to_int(a.get("unique_users")),
            "plays_30": to_int(l30.get("plays")), "hours": round(to_int(a.get("watch_time_ms")) / 3600000, 1)}


def run_stats(job):
    try:
        labels = {clean_tag(r.get("tag") or DEFAULT_TAG) for r in get_rules()} | {DEFAULT_TAG}
        con = db()
        known = {(r["instance"], r["arr_id"]): r["rule"] for r in con.execute("SELECT instance, arr_id, rule FROM added").fetchall()}
        con.close()
        items = []
        for inst in INSTANCES.values():
            media = "movie" if inst["type"] == "radarr" else "series"
            tags = {t["id"]: t["label"] for t in (arr(inst, "GET", "/tag") or [])}
            want = {tid for tid, lab in tags.items() if lab in labels}
            if not want:
                continue
            with _lib_lock:
                _lib_cache.pop((inst["name"], media), None)  # frisk liste
            for it in library(inst, media):
                hit = set(it.get("tags") or []) & want
                if not hit:
                    continue
                st = it.get("statistics") or {}
                size = to_int(st.get("sizeOnDisk")) or to_int(it.get("sizeOnDisk"))
                ext = it.get("tvdbId") if media == "series" else it.get("tmdbId")
                rule = known.get((inst["name"], it.get("id"))) or ("mærke: " + tags[sorted(hit)[0]])
                items.append({"media": media, "instance": inst["name"], "title": it.get("title"), "year": to_int(it.get("year")),
                              "added": str(it.get("added") or "")[:10], "gb": round(size / 1e9, 2), "ext_id": ext, "rule": rule})
        job["total"] = len(items)

        def one(it):
            it["watch"] = tracearr_stats(it["media"], it["ext_id"])
            job["done"] += 1
            return it

        with ThreadPoolExecutor(max_workers=4) as ex:
            items = list(ex.map(one, items))
        cutoff = (now() - datetime.timedelta(days=30)).date().isoformat()
        rules = {}
        for it in items:
            w = it["watch"] or {}
            it["stale"] = bool(it["watch"]) and w.get("plays", 0) == 0 and it["added"] and it["added"] <= cutoff
            g = rules.setdefault(it["rule"], {"rule": it["rule"], "titles": 0, "gb": 0.0, "plays": 0, "users": 0,
                                              "plays_30": 0, "unwatched": 0, "stale": 0, "unknown": 0})
            g["titles"] += 1
            g["gb"] = round(g["gb"] + it["gb"], 2)
            if not it["watch"]:
                g["unknown"] += 1
                continue
            g["plays"] += w["plays"]
            g["users"] += w["users"]
            g["plays_30"] += w["plays_30"]
            g["unwatched"] += 1 if w["plays"] == 0 else 0
            g["stale"] += 1 if it["stale"] else 0
        for g in rules.values():
            g["plays_per_gb"] = round(g["plays"] / g["gb"], 2) if g["gb"] else 0
        job["results"] = {"rules": sorted(rules.values(), key=lambda g: -g["gb"]),
                          "items": sorted(items, key=lambda i: (not i["stale"], -i["gb"]))}
        if not (TRACEARR_URL and TRACEARR_APIKEY):
            job["note"] = "Tracearr er ikke sat op (TRACEARR_URL og TRACEARR_APIKEY i fangarr.env) – kun størrelser vises"
        elif any(i["watch"] is None for i in items):
            job["note"] = "nogle titler kunne ikke slås op i Tracearr – tjek adresse og API-nøgle"
        job["status"] = "færdig"
        _stats["result"] = {**job}
    except Exception as e:
        job["status"] = "fejl"
        job["error"] = f"{e.__class__.__name__}: {e}"


@app.post("/api/stats/refresh")
def stats_refresh():
    job = new_job("stats")
    threading.Thread(target=run_stats, args=(job,), daemon=True).start()
    return job


@app.get("/api/stats")
def stats_get():
    return _stats["result"] or {}


# ================================================================ #9 kommende danske premierer (TVmaze)

_prem = {"ts": 0.0, "items": []}
_prem_lock = threading.Lock()


def tvmaze(path, params):
    for _ in range(3):
        try:
            r = httpx.get("https://api.tvmaze.com" + path, params=params, timeout=20)
        except httpx.HTTPError:
            return []
        if r.status_code == 429:
            time.sleep(2)
            continue
        if r.status_code != 200:
            return []
        try:
            return r.json()
        except ValueError:
            return []
    return []


def strip_html(t):
    return re.sub(r"<[^>]+>", "", t or "").strip()


def fetch_premieres(days):
    seen, out = set(), []
    for d in range(days):
        date = (now() + datetime.timedelta(days=d)).date().isoformat()
        for path in ("/schedule", "/schedule/web"):
            for ep in tvmaze(path, {"country": "DK", "date": date}) or []:
                if to_int(ep.get("season")) != 1 or to_int(ep.get("number")) != 1:
                    continue
                show = ep.get("show") or (ep.get("_embedded") or {}).get("show") or {}
                if not show or show.get("id") in seen:
                    continue
                seen.add(show.get("id"))
                net = (show.get("network") or {}).get("name") or (show.get("webChannel") or {}).get("name") or ""
                out.append({"date": ep.get("airdate") or date, "title": show.get("name") or "", "network": net,
                            "language": show.get("language") or "", "genres": show.get("genres") or [],
                            "type": show.get("type") or "", "tvdb": (show.get("externals") or {}).get("thetvdb"),
                            "url": show.get("url") or "", "summary": strip_html(show.get("summary"))[:240]})
            time.sleep(0.4)  # TVmaze tillader ca. 20 kald pr. 10 sek.
    return sorted(out, key=lambda x: (x["date"], x["title"]))


def premiere_status(items):
    tvdb_have = set()
    for inst in INSTANCES.values():
        if inst["type"] != "sonarr":
            continue
        try:
            tvdb_have |= {to_int(x.get("tvdbId")) for x in library(inst, "series")}
        except httpx.HTTPError:
            pass
    con = db()
    waiting = {loose(r["title"]) for r in con.execute("SELECT title FROM waitlist WHERE status='venter' AND media='series'").fetchall()}
    con.close()
    for it in items:
        it["exists"] = bool(it["tvdb"]) and to_int(it["tvdb"]) in tvdb_have
        it["following"] = loose(it["title"]) in waiting
    return items


@app.get("/api/premieres")
def premieres(refresh: int = 0, days: int = 21):
    days = max(1, min(30, days))
    with _prem_lock:
        if refresh or not _prem["items"] or time.time() - _prem["ts"] > 6 * 3600:
            _prem["items"] = fetch_premieres(days)
            _prem["ts"] = time.time()
        items = [dict(x) for x in _prem["items"]]
    return {"fetched": datetime.datetime.fromtimestamp(_prem["ts"]).isoformat(timespec="minutes") if _prem["ts"] else "",
            "items": premiere_status(items)}


@app.post("/api/premieres/add")
async def premiere_add(req: Request):
    b = await req.json()
    rule = next((r for r in get_rules() if r["id"] == to_int(b.get("rule_id")) and r["media"] == "series"), None)
    if not rule:
        raise HTTPException(400, "vælg en serieregel – den bestemmer mappe, kvalitet og overvågning")
    inst = INSTANCES.get(rule.get("instance"))
    tvdb = to_int(b.get("tvdb"))
    if not inst or not tvdb:
        raise HTTPException(400, "titlen har intet TheTVDB-nummer endnu – brug Følg i stedet")
    s = get_settings()
    pct = disk_pct()
    if pct is not None and pct > to_float(s["max_disk_pct"]):
        raise HTTPException(400, f"disken er {pct} % fyldt (grænse {s['max_disk_pct']} %)")
    found = await run_in_threadpool(arr, inst, "GET", "/series/lookup", params={"term": f"tvdb:{tvdb}"})
    if not found:
        raise HTTPException(404, "TheTVDB-nummeret blev ikke fundet i Sonarr – prøv Følg")
    cand = found[0]
    if cand.get("id"):
        return {"result": "findes allerede"}
    created = await run_in_threadpool(add_title, inst, "series", cand, rule)
    remember_added(inst, "series", created, cand.get("title") or "", rule.get("name") or "")
    write_log("series", "(tilføjet fra premierelisten)", cand.get("title") or b.get("title") or "", to_int(cand.get("year")),
              "tilføjet", rule.get("name") or "", f"manuelt fra premierelisten til {inst['name']} › {rule.get('root_folder')}", False)
    return {"result": "tilføjet", "title": cand.get("title")}


@app.post("/api/premieres/follow")
async def premiere_follow(req: Request):
    b = await req.json()
    rule = next((r for r in get_rules() if r["id"] == to_int(b.get("rule_id")) and r["media"] == "series"), None)
    if not rule:
        raise HTTPException(400, "vælg en serieregel")
    title = str(b.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "mangler titel")
    start = None
    try:
        start = datetime.datetime.fromisoformat(str(b.get("date")))
    except ValueError:
        pass
    add_to_waitlist("series", title, "(fulgt fra premierelisten)",
                    {"media": "series", "title": title, "release": title, "rule_id": rule["id"], "rule_name": rule.get("name")},
                    rule.get("name") or "", "følger premieren – venter på TheTVDB", created=start if start and start > now() else None)
    return {"result": "følger"}
