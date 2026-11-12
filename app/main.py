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
from fastapi.staticfiles import StaticFiles

from . import kunder

DATA_DIR = os.environ.get("DATA_DIR", "/config")
DB_PATH = os.path.join(DATA_DIR, "fangarr.db")
DISK_PATH = os.environ.get("DISK_PATH", "/data")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
LOOP_SECONDS = int(os.environ.get("LOOP_SECONDS", "60"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fangarr")
# httpx skriver hele adressen i loggen – for Telegram indeholder den bot-tokenet. Vis kun advarsler.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

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
    "rescue_grab": True,        # hent for sonarr2, når den ikke genkender navnet på en serie, den har
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
        con.execute(
            "CREATE TABLE IF NOT EXISTS aliases (id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, media TEXT,"
            " key TEXT, release_title TEXT, ext_id INTEGER, title TEXT, UNIQUE(media, key))"
        )
        cols = [r[1] for r in con.execute("PRAGMA table_info(waitlist)").fetchall()]
        if "suggestions" not in cols:
            con.execute("ALTER TABLE waitlist ADD COLUMN suggestions TEXT DEFAULT '[]'")
        con.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)")  # intern tilstand
        con.execute("CREATE TABLE IF NOT EXISTS reveal_notified (id TEXT PRIMARY KEY, ts TEXT)")
        # titler, du har fjernet fra ventelisten med "Fjern og husk" – de kommer ikke på ventelisten igen
        con.execute("CREATE TABLE IF NOT EXISTS ignored (id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, media TEXT,"
                    " key TEXT, title TEXT, UNIQUE(media, key))")
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
        link = (os.environ.get(f"{key}_LINK") or "").rstrip("/")   # valgfri: adressen, du selv åbner appen på
        typ = os.environ.get(f"{key}_TYPE") or ("radarr" if n.lower().startswith("radarr") else "sonarr")
        if url and api:
            inst[n] = {"name": n, "type": typ, "url": url.rstrip("/"), "apikey": api, "link": link}
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
        if e.response.status_code == 409 and method == "POST":
            # 409 ved tilføjelse = titlen er lige blevet lagt ind (samme udgivelse fra to trackere) – ingen alarm
            raise
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


def find_title(inst, media, title, year, release=""):
    """Find titlen: 1) Sonarr/Radarr-opslag, 2) dit eget bibliotek (inkl. mappenavne),
    3) for serier: TVmaze -> TheTVDB-nummer -> Sonarr-opslag. Giver (titel, grund, samme-navn, note)."""
    al = get_alias(media, title)
    if al:
        try:
            hit = ext_lookup(inst, media, al["ext_id"])
        except httpx.HTTPError:
            hit = None
        if hit:
            return hit, None, [], "fundet via din godkendte kobling \"%s\" = \"%s\"" % (al["release_title"], hit.get("title"))
    found = lookup(inst, media, title, year)
    cand, why, same = pick_all(found, title, year)
    if cand or same or why != NOT_FOUND:
        return cand, why, same, ""
    cc = country_match(found, title, year, release)
    if cc:
        return cc, None, [], "fundet som \"%s\" (landekode i TheTVDB-navnet passer til udgivelsen)" % cc.get("title")
    if media == "movie" and year:
        sub = subtitle_match(found, title, year)
        if sub:
            return sub, None, [], "fundet som \"%s\" (undertitel/nummer mangler i udgivelsen, samme år)" % sub.get("title")
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

_SEQUEL = re.compile(r"\b(?:[2-9]|1[0-9]|ii|iii|iv|v|vi)\b", re.I)


def title_variants(name):
    """Kortere udgaver af en filmtitel: uden undertitel (efter kolon/tankestreg) og uden fortsættelsesnummer."""
    out = set()
    head = re.split(r"\s*(?::|\s[-–—]\s)\s*", name, maxsplit=1)[0]
    dash = re.split(r"\s[-–—]\s", name.replace(":", " "), maxsplit=1)[0]
    for v in (head, dash, name.replace(":", " "), _SEQUEL.sub(" ", name.replace(":", " ")), _SEQUEL.sub(" ", head), _SEQUEL.sub(" ", dash)):
        lv = loose(v)
        if lv:
            out.add(lv)
    return out


def subtitle_match(cands, title, year):
    """Kun film: "The Disciple" = "The Disciple: A Wu-Tang Fable", "Den of Thieves Pantera" = "Den of Thieves 2: Pantera".
    Kræver samme år og præcis ét match."""
    t = loose(title)
    if len(t) < 4 or not year:
        return None
    hits = []
    for c in cands:
        if to_int(c.get("year")) != year:
            continue
        names = [c.get("title"), c.get("originalTitle")] + [a.get("title") for a in (c.get("alternateTitles") or [])]
        if any(t in title_variants(n) for n in names if n):
            hits.append(c)
    return hits[0] if len(hits) == 1 else None


# landekoder i TheTVDB-navne ("Ton of Cash (DK)") – kun når udgivelsens sprog-mærke peger på landet
RELEASE_COUNTRY = {"danish": {"DK"}, "swedish": {"SE"}, "norwegian": {"NO"}, "finnish": {"FI"},
                   "icelandic": {"IS"}, "nordic": {"DK", "SE", "NO", "FI"}}


def release_countries(release):
    words = {w.lower() for w in re.split(r"[^A-Za-z]+", release or "") if w}
    out = set()
    for w, cc in RELEASE_COUNTRY.items():
        if w in words:
            out |= cc
    return out


def country_match(cands, title, year, release):
    ccs = release_countries(release)
    t = loose(title)
    if not ccs or len(t) < 4:
        return None
    hits = []
    for c in cands:
        names = [c.get("title"), c.get("originalTitle")] + [a.get("title") for a in (c.get("alternateTitles") or [])]
        for n in names:
            m = re.match(r"^(.*?)\s*\((?:(\d{4})\)\s*\()?([A-Z]{2})\)\s*$", n or "")
            if m and m.group(3) in ccs and loose(m.group(1)) == t:
                if not year or abs(to_int(c.get("year")) - year) <= 1:
                    hits.append(c)
                break
    return hits[0] if len(hits) == 1 else None


def get_alias(media, title):
    con = db()
    row = con.execute("SELECT * FROM aliases WHERE media=? AND key=?", (media, loose(title))).fetchone()
    con.close()
    return dict(row) if row else None


def save_alias(media, release_title, ext_id, shown):
    con = db()
    with con:
        con.execute("INSERT OR REPLACE INTO aliases (created, media, key, release_title, ext_id, title) VALUES (?,?,?,?,?,?)",
                    (iso(now()), media, loose(release_title), release_title, to_int(ext_id), shown))
    con.close()


def ext_lookup(inst, media, ext_id):
    term = f"tvdb:{ext_id}" if media == "series" else f"tmdb:{ext_id}"
    found = arr(inst, "GET", "/series/lookup" if media == "series" else "/movie/lookup", params={"term": term})
    if isinstance(found, dict):
        return found
    return (found or [None])[0]


def dk_variant(title):
    """Udgivelser skriver æ/ø/å som ae/oe/aa. Giv den danske stavemåde (eller None)."""
    v = re.sub(r"aa", "å", title)
    v = re.sub(r"Aa", "Å", v)
    v = re.sub(r"oe", "ø", v)
    v = re.sub(r"Oe", "Ø", v)
    v = re.sub(r"ae", "æ", v)
    v = re.sub(r"Ae", "Æ", v)
    return v if v != title else None


def suggest(inst, media, title, year, rule, limit=3, cache=None):
    """Mulige match, når titlen ikke passer præcist (fx dansk titel, men engelsk navn hos TheTVDB).
    Kun bud, der passer til reglen (eller hvor TheTVDB mangler oplysninger). Godkendes manuelt."""
    seen, out = set(), []
    for term in [title, dk_variant(title)]:
        if not term:
            continue
        ck = (inst["name"], term)
        if cache is not None and ck in cache:
            found = cache[ck]
        else:
            try:
                found = lookup(inst, media, term, year)
            except httpx.HTTPError:
                found = []
            if cache is not None:
                cache[ck] = found
        for c in found[:5]:
            key = c.get("tvdbId") if media == "series" else c.get("tmdbId")
            if not key or key in seen:
                continue
            seen.add(key)
            inf = describe(media, c)
            ok, why, missing = rule_check(rule, inf)
            if not ok and not missing:
                continue
            out.append({"id": key, "title": inf["title"], "year": inf["year"], "language": inf["language"],
                        "network": inf["network"], "genres": inf["genres"], "exists": inf["exists"],
                        "instance": inst["name"], "rule": rule.get("name") or "", "note": "" if ok else why})
    return out[:limit]


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
    accepted = []  # krav, der springes over, fordi TheTVDB/TMDb mangler feltet (reglens valg)
    genres = [g.lower() for g in inf["genres"]]
    want = [g.lower() for g in (rule.get("genres_any") or [])]
    if want and not genres:
        if not rule.get("allow_missing_genre"):
            return False, "TheTVDB/TMDb mangler genrer", True
        accepted.append("genre")
        want = []
    if want and not any(g in genres for g in want):
        return False, "genre passer ikke (" + ", ".join(inf["genres"]) + ")", False
    bad = [g.lower() for g in (rule.get("genres_none") or [])]
    hit = [g for g in bad if g in genres]
    if hit:
        return False, "udelukket genre: " + ", ".join(hit), False
    ymin, ymax = to_int(rule.get("year_min")), to_int(rule.get("year_max"))
    if (ymin or ymax) and not inf["year"]:
        if not rule.get("allow_missing_year"):
            return False, "TheTVDB/TMDb mangler årstal", True
        accepted.append("år")
        ymin = ymax = 0
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
    if accepted:
        return True, "alle krav opfyldt – " + " og ".join(accepted) + " mangler hos TheTVDB/TMDb, accepteret", False
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
    # nye sæsoner, der kommer senere, overvåges automatisk (Sonarr v4; ignoreres af v3)
    body["monitorNewItems"] = "none" if rule.get("monitor") == "none" else "all"
    body.setdefault("languageProfileId", 1)  # kun brugt af Sonarr v3
    body["addOptions"] = {
        "monitor": rule.get("monitor") or "latestSeason",
        "searchForMissingEpisodes": search,
        "searchForCutoffUnmetEpisodes": False,
    }
    return arr(inst, "POST", "/series", json=body)


def missing_aired(inst, series_id):
    """Antal udsendte, overvågede afsnit uden fil (sæson 0/specials tælles ikke)."""
    eps = arr(inst, "GET", "/episode", params={"seriesId": series_id}) or []
    nowu = datetime.datetime.now(datetime.timezone.utc)
    n = 0
    for e in eps:
        if not e.get("monitored") or e.get("hasFile") or not to_int(e.get("seasonNumber")):
            continue
        try:
            aired = datetime.datetime.fromisoformat(str(e.get("airDateUtc") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if aired <= nowu:
            n += 1
    return n


def search_missing(inst, series_id, title, why):
    """Bed sonarr2 søge efter manglende afsnit, hvis der mangler udsendte, overvågede afsnit."""
    try:
        n = missing_aired(inst, series_id)
        if n:
            arr(inst, "POST", "/command", json={"name": "SeriesSearch", "seriesId": series_id})
            log.info("series | %s | søgning startet (%s) – %s afsnit mangler", title, why, n)
        return n
    except httpx.HTTPError as e:
        log.warning("Søgning efter %s fejlede: %s", title, e.__class__.__name__)
        return 0


SEARCH_AFTER_ADD = 180   # sekunder: sonarr2 skal først nå at hente afsnitslisten fra TheTVDB


def remember_added(inst, media, created, title, rule=""):
    if not created or not created.get("id"):
        return
    if media == "series":
        # autobrr skubber udgivelsen få sekunder efter tilføjelsen, før sonarr2 kender afsnittene
        # ("Unable to identify correct episode(s)"), og "Søg straks" kommer for tidligt. Søg igen om lidt.
        t = threading.Timer(SEARCH_AFTER_ADD, search_missing, args=(inst, created["id"], title, "3 min. efter tilføjelse"))
        t.daemon = True
        t.start()
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


_title_locks = {}
_title_locks_guard = threading.Lock()


def _title_lock(media, title):
    """Én lås pr. titel: kommer samme udgivelse fra to trackere samtidig, venter den anden på den første."""
    key = (media, loose(title))
    with _title_locks_guard:
        lk = _title_locks.get(key)
        if lk is None:
            lk = _title_locks[key] = threading.Lock()
        return lk


def is_transient(e):
    """Fejl, der typisk går over af sig selv: kan ikke nås, timeout, 429 eller 5xx."""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        return code == 429 or code >= 500
    return True


def process(p, test=False, from_waitlist=False, rules_override=None):
    """Som _process, men kun én behandling ad gangen pr. titel (undgår dobbelt-tilføjelse og 409)."""
    title = str(p.get("title") or "").strip()
    if test or not title:
        return _process(p, test=test, from_waitlist=from_waitlist, rules_override=rules_override)
    with _title_lock(media_of(p), title):
        return _process(p, test=test, from_waitlist=from_waitlist, rules_override=rules_override)


def _process(p, test=False, from_waitlist=False, rules_override=None):
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
    season = to_int(p.get("season"))
    if not season and media == "series":
        m_s = re.search(r"\bS(\d{1,2})(?:E\d|\b)", release, re.I)
        season = to_int(m_s.group(1)) if m_s else 0
    res = {"media": media, "title": title, "year": year, "release": release,
           "decision": "afvist", "rule": "", "detail": "", "match": None, "checks": [], "can_wait": False,
           "suggestions": []}

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
            notes = [c for c in res["checks"] if "fundet i dit bibliotek" in c or "fundet via TVmaze" in c or "valgte den fra" in c or "undertitel" in c
                     or "godkendte kobling" in c or "landekode" in c]
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
    sugg_cache = {}
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
                cache[inst["name"]] = find_title(inst, media, title, year, release)
            except httpx.HTTPError as e:
                detail = f"opslag i {inst['name']} fejlede: {e.__class__.__name__}"
                if isinstance(e, httpx.HTTPStatusError):
                    detail += f" {e.response.status_code}"
                if not test and not from_waitlist and not only and rules_override is None and is_transient(e):
                    add_to_waitlist(media, title, release, p, name, detail + " – prøver igen")
                    return done("venteliste", detail + " – prøver igen", name)
                return done("fejl", detail, name)
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
            if media == "series" and season > 1 and not only:
                # nye serier tilføjes kun fra sæson 1 – sæson 2+ sendes kun til Fangarr for at hjælpe eksisterende serier
                res["checks"].append(f"{name}: sæson {season} – kun sæson 1 kan tilføje nye serier")
                continue
            ymin, ymax = to_int(r.get("year_min")), to_int(r.get("year_max"))
            if not only and year and ((ymin and year < ymin) or (ymax and year > ymax)):
                # årstallet i udgivelsen ligger uden for reglen – der er ingen grund til at vente på TheTVDB/TMDb
                res["checks"].append(f"{name}: årstallet {year} i udgivelsen passer ikke til reglen – venter ikke")
                continue
            if (why == NOT_FOUND or only) and (r.get("wait") or only) and not wait_rule:
                wait_rule, wait_why = name, why
            if why == NOT_FOUND and r.get("wait") and not only:
                # forslag for hver regel, der venter – et bud knyttes til den første regel, det passer til
                try:
                    found = suggest(inst, media, title, year, r, cache=sugg_cache)
                except Exception:  # forslag er en hjælp – må aldrig stoppe behandlingen
                    found = []
                have = {x["id"] for x in res["suggestions"]}
                for sg in found:
                    if sg["id"] in have or len(res["suggestions"]) >= 3:
                        continue
                    res["suggestions"].append(sg)
                    res["checks"].append(f"{name}: muligt match (kræver godkendelse): {sg['title']}"
                                         + ("" if re.search(r"\(\d{4}\)$", sg["title"]) else f" ({sg['year'] or '?'})")
                                         + (" – findes allerede" if sg["exists"] else ""))
            continue
        inf = describe(media, cand)
        res["match"] = inf
        if inf["exists"]:
            if media == "series" and not test and not dry and s.get("rescue_grab", True) and to_int(cand.get("id")):
                rescue_start(inst, to_int(cand.get("id")), inf["title"], release)
            return done("findes allerede", f"findes allerede i {inst['name']}", name)
        if media == "series" and season > 1 and not only:
            res["checks"].append(f"{name}: sæson {season} – kun sæson 1 kan tilføje nye serier")
            continue
        if only:  # fulgt fra premierelisten: du har selv valgt titlen, så reglens krav springes over
            ok, why, missing = True, "fulgt manuelt – reglens krav springes over", []
        else:
            ok, why, missing = rule_check(r, inf)
        res["checks"].append(f"{name}: {why}")
        if not ok:
            if missing and r.get("wait") and not wait_rule:
                wait_rule, wait_why = name, why
            continue
        note = (" – " + why.split(" – ", 1)[1]) if "accepteret" in why else ""
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
            return done("ville tilføje", f"til {inst['name']} › {r.get('root_folder')}" + (" (test)" if test else " (prøvetilstand)") + note, name)
        try:
            created = add_title(inst, media, cand, r)
        except httpx.HTTPError as e:
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 409:
                # titlen blev lagt ind lige før (samme udgivelse fra to trackere) – ikke en fejl
                return done("findes allerede", f"findes allerede i {inst['name']} (lige tilføjet)", name)
            detail = f"tilføjelse i {inst['name']} fejlede: {e.__class__.__name__}"
            if isinstance(e, httpx.HTTPStatusError):
                detail += f" {e.response.status_code}"
            if not from_waitlist and not only and rules_override is None and is_transient(e):
                add_to_waitlist(media, title, release, p, name, detail + " – prøver igen")
                return done("venteliste", detail + " – prøver igen", name)
            return done("fejl", detail, name)
        remember_added(inst, media, created, inf["title"], name)
        return done("tilføjet", f"til {inst['name']} › {r.get('root_folder')}" + note, name)

    if wait_rule:
        res["can_wait"] = True
        reason = wait_why
        if test:
            return done("venteliste", "kommer på ventelisten, til TheTVDB/TMDb har oplysningerne", wait_rule)
        if from_waitlist:
            res.update(decision="venter stadig", detail=reason, rule=wait_rule)
            return res
        if not only and rules_override is None and is_ignored(media, title):
            return done("afvist", "du har fjernet titlen fra ventelisten (Fjern og husk) – den kommer ikke på igen. "
                                  "Glem den under Indstillinger › Koblinger og fjernede titler", wait_rule)
        add_to_waitlist(media, title, release, p, wait_rule, reason, suggestions=res["suggestions"])
        return done("venteliste", "venter på TheTVDB/TMDb: " + reason, wait_rule)
    return done("afvist", "; ".join(res["checks"]) or "ingen regel passede")


# ---------------------------------------------------------------- hjælp til sonarr2 (navn ikke genkendt)
# Nogle danske serier kan sonarr2 ikke genkende på udgivelsesnavnet ("Luksusmaeglerne.paa.Havnefronten"
# vs "Luksusmæglerne på Havnefronten"), fordi sonarr2 laver å om til a men lader æ/ø stå. Så virker
# hverken autobrr-skub eller RSS. Fangarr finder udgivelsen ved en søgning på afsnittet og beder
# sonarr2 hente den til den rigtige serie – det samme som personikonet i sonarr2's søgning.

RESCUE_DELAYS = [0, 300, 900, 3600]   # sekunder: med det samme, efter 5 min, 15 min og 1 time
_rescue_recent = {}
_rescue_lock = threading.Lock()


def rel_key(t):
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def allowed_quality_ids(profile):
    out = set()

    def walk(items, parent_ok=False):
        for it in items or []:
            ok = bool(it.get("allowed")) or parent_ok
            q = it.get("quality")
            if q and ok:
                out.add(to_int(q.get("id")))
            walk(it.get("items"), ok)
    walk(profile.get("items"))
    return out


def rescue_grab(inst, series_id, release):
    """(True, tekst) = hentet, (False, tekst) = bevidst ikke hentet, (None, tekst) = prøv igen senere."""
    pr = arr(inst, "GET", "/parse", params={"title": release}) or {}
    if pr.get("series"):
        return False, "sonarr2 genkender selv navnet – ingen hjælp nødvendig"
    pe = pr.get("parsedEpisodeInfo") or {}
    season = to_int(pe.get("seasonNumber"))
    nums = [to_int(n) for n in (pe.get("episodeNumbers") or [])]
    full = bool(pe.get("fullSeason"))
    if not season or not (nums or full):
        return False, "sæson/afsnit kan ikke læses i udgivelsesnavnet"
    series = arr(inst, "GET", f"/series/{series_id}") or {}
    if not series.get("monitored"):
        return False, "serien er ikke overvåget i sonarr2"
    eps = arr(inst, "GET", "/episode", params={"seriesId": series_id}) or []
    want = [e for e in eps if to_int(e.get("seasonNumber")) == season and (full or to_int(e.get("episodeNumber")) in nums)]
    label = f"S{season:02d}" + ("" if full else "".join(f"E{n:02d}" for n in nums))
    if not want:
        return None, f"{label} findes ikke i sonarr2 endnu (TheTVDB mangler afsnittet)"
    need = [e for e in want if e.get("monitored") and not e.get("hasFile")]
    if not need:
        return False, f"{label} findes allerede eller er ikke overvåget"
    q = arr(inst, "GET", "/queue", params={"seriesIds": series_id, "pageSize": 500}) or {}
    inq = {to_int(r.get("episodeId")) for r in (q.get("records") or [])}
    if any(to_int(e.get("id")) in inq for e in need):
        return False, f"{label} er allerede ved at blive hentet"
    key = (inst["name"], series_id, tuple(sorted(to_int(e.get("id")) for e in need)))
    with _rescue_lock:
        if time.time() - _rescue_recent.get(key, 0) < 6 * 3600:
            return False, f"{label} er hentet for nylig"
    params = {"seriesId": series_id, "seasonNumber": season} if full else {"episodeId": to_int(need[0].get("id"))}
    rels = arr(inst, "GET", "/release", params=params) or []
    target = rel_key(release)
    hit = next((r for r in rels if rel_key(r.get("title")) == target), None)
    if not hit:
        return None, f"udgivelsen blev ikke fundet ved søgning på {label}"
    other = [x for x in (hit.get("rejections") or []) if "unknown" not in str(x).lower()]
    if other:
        return False, "sonarr2 afviser udgivelsen: " + "; ".join(str(x) for x in other)
    qual = ((hit.get("quality") or {}).get("quality") or {})
    prof = arr(inst, "GET", f"/qualityprofile/{to_int(series.get('qualityProfileId'))}") or {}
    if to_int(qual.get("id")) not in allowed_quality_ids(prof):
        return False, f"kvaliteten {qual.get('name') or '?'} er ikke tilladt i profilen {prof.get('name') or '?'}"
    body = {"guid": hit.get("guid"), "indexerId": to_int(hit.get("indexerId")), "seriesId": series_id}
    if not full and len(need) == 1 and len(nums) == 1:
        body["episodeId"] = to_int(need[0].get("id"))
    arr(inst, "POST", "/release", json=body)
    with _rescue_lock:
        _rescue_recent[key] = time.time()
    return True, f"{label} hentet til {series.get('title')} ({qual.get('name') or '?'}) – sonarr2 genkendte ikke navnet"


def _rescue_run(inst, series_id, title, release):
    ok, msg = None, ""
    for delay in RESCUE_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            ok, msg = rescue_grab(inst, series_id, release)
        except httpx.HTTPError as e:
            ok, msg = None, f"fejl i sonarr2 ({e.__class__.__name__})"
        except Exception as e:  # hjælpen må aldrig vælte Fangarr
            ok, msg = False, f"uventet fejl: {e.__class__.__name__}"
        if ok is not None:
            break
    if ok is False and "ingen hjælp nødvendig" in msg:
        return  # det normale tilfælde – skriv ikke i loggen
    decision = "hentet for sonarr2" if ok else "ikke hentet"
    if ok is None:
        msg = "gav op: " + msg
    log.info("series | %s | %s | %s", release, decision, msg)
    write_log("series", release, title, 0, decision, "", msg, False)


def rescue_start(inst, series_id, title, release):
    threading.Thread(target=_rescue_run, args=(inst, series_id, title, release), daemon=True).start()


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

def is_ignored(media, title):
    """Har du fjernet titlen fra ventelisten med "Fjern og husk"?"""
    con = db()
    row = con.execute("SELECT 1 FROM ignored WHERE media=? AND key=?", (media, loose(title))).fetchone()
    con.close()
    return bool(row)


def ignore_title(media, title):
    key = loose(title)
    if not key:
        return
    con = db()
    with con:
        con.execute("INSERT OR IGNORE INTO ignored (created, media, key, title) VALUES (?,?,?,?)",
                    (iso(now()), media, key, title))
    con.close()


def add_to_waitlist(media, title, release, payload, rule, reason, created=None, suggestions=None):
    sj = json.dumps(suggestions or [])
    key = loose(title)
    con = db()
    with con:
        rows = con.execute("SELECT id, title FROM waitlist WHERE status='venter' AND media=?", (media,)).fetchall()
        for r in rows:
            if loose(r["title"]) == key:
                con.execute("UPDATE waitlist SET release=?, reason=?, suggestions=? WHERE id=?", (release, reason, sj, r["id"]))
                break
        else:
            hours = to_int(get_settings()["wait_hours"]) or 2
            con.execute(
                "INSERT INTO waitlist (created, media, title, release, payload, attempts, next_try, status, reason, rule, suggestions)"
                " VALUES (?,?,?,?,?,0,?,'venter',?,?,?)",
                (iso(created or now()), media, title, release, json.dumps(payload), iso(now() + datetime.timedelta(hours=hours)), reason, rule, sj),
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
        con.execute("UPDATE waitlist SET attempts=attempts+1, last_try=?, next_try=?, status=?, reason=?, suggestions=? WHERE id=?",
                    (iso(now()), iso(now() + datetime.timedelta(hours=hours)), status, reason,
                     json.dumps(res.get("suggestions") or []) if status == "venter" else "[]", row["id"]))
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
        try:
            d["suggestions"] = json.loads(d.get("suggestions") or "[]")
        except ValueError:
            d["suggestions"] = []
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
        # mangler der udsendte afsnit, så søg igen (fanger udgivelser, sonarr2 afviste lige efter tilføjelsen)
        search_missing(inst, r["arr_id"], r["title"], "opdatering af ny serie")
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
    forslag = con.execute("SELECT COUNT(*) FROM waitlist WHERE status='venter' AND suggestions NOT IN ('', '[]')").fetchone()[0]
    hjulpet = con.execute("SELECT COUNT(*) FROM log WHERE ts>=? AND decision='hentet for sonarr2'", (since,)).fetchone()[0]
    con.close()
    tr_lines = translation_summary_lines()
    if not (rows or fejl or udl or forslag or hjulpet or tr_lines):
        return
    lines = [f"{'🎬' if r['media'] == 'movie' else '📺'} {r['title']} ({r['year'] or '?'}) – {r['decision']}" for r in rows[:30]]
    more = f"\n… og {len(rows) - 30} mere" if len(rows) > 30 else ""
    mode = " (prøvetilstand)" if s.get("dry_run") else ""
    txt = f"📦 Fangarr – sidste døgn{mode}\n\n" + ("\n".join(lines) or "Intet tilføjet.") + more
    if hjulpet:
        txt += f"\n\n🔧 {hjulpet} afsnit hentet for sonarr2 (navnet blev ikke genkendt)"
    txt += f"\n\n⏳ {venter} på ventelisten"
    if udl:
        txt += f", {udl} opgivet (ikke på TheTVDB/TMDb i tide)"
    if forslag:
        txt += f"\n👉 {forslag} med forslag, der venter på din godkendelse (Fangarr › Venteliste)"
    if fejl:
        txt += f"\n⚠️ {fejl} fejl – se loggen i Fangarr."
    if tr_lines:
        txt += "\n\n" + "\n".join(tr_lines)
    telegram(txt)


_last_backup = {}


def background_loop():
    last_summary = None
    last_tr_check = 0.0
    last_rv_check = 0.0
    last_ss_check = 0.0
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
            if time.time() - last_tr_check >= 600:
                last_tr_check = time.time()
                check_translator()
            if time.time() - last_rv_check >= 300:
                last_rv_check = time.time()
                check_reveal()
            if time.time() - last_ss_check >= 120:
                last_ss_check = time.time()
                check_seerr_straks()
            refresh_premieres_bg()
            kunder.tick()
        except Exception as e:  # baggrundsjobbet må aldrig stoppe appen
            log.warning("Baggrundsjob fejlede: %s", e)
        time.sleep(LOOP_SECONDS)


# ---------------------------------------------------------------- autobrr-filtre

AUTOBRR_URL = (os.environ.get("AUTOBRR_URL") or "").rstrip("/")
AUTOBRR_APIKEY = os.environ.get("AUTOBRR_APIKEY") or ""
FANGARR_URL = (os.environ.get("FANGARR_URL") or "http://fangarr:8080").rstrip("/")

AUTOBRR_DEFAULTS = {
    "series": {"name": "Fangarr – serier", "categories": "*TV*,*Serie*", "seasons": "", "priority": 10},
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
app.include_router(kunder.router)   # Kunder og betalinger (1.16.0) – se app/kunder.py


@app.on_event("startup")
def startup():
    init_db()
    kunder.init()
    threading.Thread(target=background_loop, daemon=True).start()
    log.info("Fangarr startet. Instanser: %s", ", ".join(INSTANCES) or "ingen")


@app.get("/")
def index():
    # no-cache: browseren spørger hver gang, så en opdatering af Fangarr ses med det samme
    return FileResponse(os.path.join(STATIC_DIR, "index.html"), headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")   # skrifterne (Outfit, DM Sans) ligger i Fangarr selv


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
    return JSONResponse(res, status_code=202)        # håndteret – Fangarr-filteret afvises, autobrr går videre til næste filter


@app.get("/api/state")
def state():
    con = db()
    venter = con.execute("SELECT COUNT(*) FROM waitlist WHERE status='venter'").fetchone()[0]
    con.close()
    return {
        "settings": get_settings(),
        "rules": get_rules(),
        "instances": [{"name": i["name"], "type": i["type"], "link": i.get("link") or ""} for i in INSTANCES.values()],
        "disk_pct": disk_pct(),
        "today": {"series": added_today("series"), "movie": added_today("movie")},
        "waiting": venter,
        "features": {"tracearr": bool(TRACEARR_URL and TRACEARR_APIKEY), "seerr": bool(SEERR_URL and SEERR_APIKEY),
                     "autobrr": bool(AUTOBRR_URL and AUTOBRR_APIKEY), "translator": ov_enabled(),
                     "plex": bool(PLEX_URL and PLEX_TOKEN), "tautulli": tautulli_enabled(), "version": VERSION},
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
    "allow_missing_genre": bool, "allow_missing_year": bool,
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


@app.post("/api/waitlist/{wid}/approve")
async def waitlist_approve(wid: int, req: Request):
    b = await req.json()
    con = db()
    row = con.execute("SELECT * FROM waitlist WHERE id=?", (wid,)).fetchone()
    con.close()
    if not row or row["status"] != "venter":
        raise HTTPException(404, "titlen står ikke længere på ventelisten")
    sugg = json.loads(row["suggestions"] or "[]")
    sg = next((x for x in sugg if str(x.get("id")) == str(b.get("id"))), None)
    if not sg:
        raise HTTPException(400, "forslaget findes ikke længere – tryk Opdatér")
    media = row["media"]
    rule = next((r for r in get_rules() if r.get("name") == sg.get("rule") and r.get("media") == media), None)
    inst = INSTANCES.get(sg.get("instance"))
    if not rule or not inst:
        raise HTTPException(400, "reglen eller Sonarr/Radarr findes ikke længere")
    term = f"tvdb:{sg['id']}" if media == "series" else f"tmdb:{sg['id']}"
    found = await run_in_threadpool(arr, inst, "GET", "/series/lookup" if media == "series" else "/movie/lookup", params={"term": term})
    cand = (found or [None])[0] if isinstance(found, list) else found
    if not cand:
        raise HTTPException(404, f"{term} blev ikke fundet i {inst['name']}")
    save_alias(media, row["title"], sg["id"], cand.get("title") or "")
    shown = cand.get("title") or "?"
    if not re.search(r"\(\d{4}\)$", shown):
        shown += f" ({to_int(cand.get('year')) or '?'})"
    if cand.get("id"):
        result, detail = "findes allerede", f"godkendt: {row['title']} = {shown}, findes allerede i {inst['name']}"
    else:
        s = get_settings()
        pct = disk_pct()
        if pct is not None and pct > to_float(s["max_disk_pct"]):
            raise HTTPException(400, f"disken er {pct} % fyldt (grænse {s['max_disk_pct']} %)")
        created = await run_in_threadpool(add_title, inst, media, cand, rule)
        remember_added(inst, media, created, cand.get("title") or "", rule.get("name") or "")
        result, detail = "tilføjet", f"godkendt manuelt: {row['title']} = {shown} → {inst['name']} › {rule.get('root_folder')}"
    write_log(media, row["release"], cand.get("title") or row["title"], to_int(cand.get("year")), result,
              rule.get("name") or "", detail, False)
    con = db()
    with con:
        con.execute("UPDATE waitlist SET status='klar', reason=?, suggestions='[]' WHERE id=?", (detail, wid))
    con.close()
    return get_waitlist()


@app.get("/api/aliases")
def aliases_list():
    con = db()
    rows = [dict(r) for r in con.execute("SELECT * FROM aliases ORDER BY id DESC").fetchall()]
    con.close()
    return rows


@app.delete("/api/aliases/{aid}")
def aliases_delete(aid: int):
    con = db()
    with con:
        con.execute("DELETE FROM aliases WHERE id=?", (aid,))
    con.close()
    return aliases_list()


@app.delete("/api/waitlist/{wid}")
def waitlist_delete(wid: int, remember: int = 0):
    """Fjern en titel fra ventelisten. remember=1: husk den, så den ikke kommer på ventelisten igen."""
    con = db()
    row = con.execute("SELECT media, title, release, rule FROM waitlist WHERE id=?", (wid,)).fetchone()
    with con:
        con.execute("DELETE FROM waitlist WHERE id=?", (wid,))
    con.close()
    if row and remember:
        ignore_title(row["media"], row["title"])
        write_log(row["media"], row["release"], row["title"], 0, "afvist", row["rule"],
                  "fjernet fra ventelisten og husket – kommer ikke på igen", bool(get_settings()["dry_run"]))
    return get_waitlist()


@app.get("/api/ignored")
def ignored_list():
    con = db()
    rows = [dict(r) for r in con.execute("SELECT * FROM ignored ORDER BY id DESC").fetchall()]
    con.close()
    return rows


@app.delete("/api/ignored/{iid}")
def ignored_delete(iid: int):
    con = db()
    with con:
        con.execute("DELETE FROM ignored WHERE id=?", (iid,))
    con.close()
    return ignored_list()


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
    aliases = [{k: r[k] for k in ("media", "release_title", "ext_id", "title")} for r in con.execute("SELECT * FROM aliases").fetchall()]
    ignored = [{k: r[k] for k in ("media", "title")} for r in con.execute("SELECT * FROM ignored").fetchall()]
    con.close()
    rules = get_rules()
    for r in rules:
        r.pop("id", None)
    return {"fangarr_export": 1, "created": iso(now()), "settings": settings, "rules": rules, "waitlist": waiting,
            "aliases": aliases, "ignored": ignored}


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
    for a in d.get("aliases") or []:
        if a.get("media") and a.get("release_title") and a.get("ext_id"):
            save_alias(a["media"], a["release_title"], a["ext_id"], a.get("title") or "")
    for g in d.get("ignored") or []:
        if g.get("media") in ("series", "movie") and g.get("title"):
            ignore_title(g["media"], str(g["title"]))
    return {"rules": len(rules), "settings": len(d.get("settings") or {}), "waitlist": added_w,
            "aliases": len(d.get("aliases") or [])}


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

_prem = {"ts": 0.0, "items": [], "key": None}
_prem_lock = threading.Lock()


def seerr_get(path, params=None):
    r = httpx.get(SEERR_URL + "/api/v1" + path, headers={"X-Api-Key": SEERR_APIKEY}, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_premieres(days, lang):
    """Kommende nye serier fra TMDb via Seerr (Seerr har selv TMDb-adgang). TVmaze har næsten ingen danske data."""
    if not SEERR_URL or not SEERR_APIKEY:
        raise HTTPException(400, "Premierer kræver Seerr (SEERR_URL og SEERR_APIKEY i fangarr.env)")
    fra = now().date()
    til = fra + datetime.timedelta(days=days)
    found = []
    try:
        for code in [c.strip() for c in lang.split(",") if c.strip()]:
            for page in range(1, 6):
                d = seerr_get("/discover/tv", {"page": page, "language": code, "sortBy": "first_air_date.asc",
                                                "firstAirDateGte": fra.isoformat(), "firstAirDateLte": til.isoformat()})
                found += d.get("results") or []
                if page >= to_int(d.get("totalPages")):
                    break
    except httpx.HTTPError as e:
        raise HTTPException(502, f"kan ikke hente fra Seerr ({e.__class__.__name__})")
    out, seen = [], set()
    for x in found:
        if x.get("id") in seen:
            continue
        seen.add(x.get("id"))
        it = {"date": x.get("firstAirDate") or "", "title": x.get("name") or x.get("originalName") or "",
              "network": "", "language": x.get("originalLanguage") or "", "genres": [], "type": "",
              "tvdb": None, "tmdb": x.get("id"), "url": f"https://www.themoviedb.org/tv/{x.get('id')}",
              "summary": (x.get("overview") or "")[:240], "country": ", ".join(x.get("originCountry") or [])}
        try:
            det = seerr_get(f"/tv/{x.get('id')}")
            it["tvdb"] = (det.get("externalIds") or {}).get("tvdbId")
            it["network"] = ", ".join(n.get("name") for n in (det.get("networks") or []) if n.get("name"))
            it["genres"] = [g.get("name") for g in (det.get("genres") or []) if g.get("name")]
            it["summary"] = it["summary"] or (det.get("overview") or "")[:240]
        except (httpx.HTTPError, ValueError):
            pass
        out.append(it)
    return sorted(out, key=lambda i: (i["date"], i["title"]))


def premiere_status(items):
    tvdb_have, tmdb_have = set(), set()
    for inst in INSTANCES.values():
        if inst["type"] != "sonarr":
            continue
        try:
            lib = library(inst, "series")
            tvdb_have |= {to_int(x.get("tvdbId")) for x in lib}
            tmdb_have |= {to_int(x.get("tmdbId")) for x in lib if x.get("tmdbId")}
        except httpx.HTTPError:
            pass
    con = db()
    waiting = {loose(r["title"]) for r in con.execute("SELECT title FROM waitlist WHERE status='venter' AND media='series'").fetchall()}
    con.close()
    for it in items:
        it["exists"] = (bool(it["tvdb"]) and to_int(it["tvdb"]) in tvdb_have) or (bool(it.get("tmdb")) and to_int(it["tmdb"]) in tmdb_have)
        it["following"] = loose(it["title"]) in waiting
    return items


@app.get("/api/premieres")
def premieres(refresh: int = 0, days: int = 21, lang: str = "da"):
    days = max(1, min(60, days))
    lang = ",".join(c for c in re.findall(r"[a-z]{2}", lang.lower())[:5]) or "da"
    with _prem_lock:
        if refresh or _prem.get("key") != (days, lang) or time.time() - _prem["ts"] > 6 * 3600:
            _prem["items"] = fetch_premieres(days, lang)
            _prem["ts"] = time.time()
            _prem["key"] = (days, lang)
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


# ================================================================ #10 Oversættelser (Oversætteren, 8. nov. 2026)
# Fangarr henter alt gennem Oversætterens interne adresse (kun på Docker-netværket, kræver X-Api-Token).
# Fangarr læser aldrig Oversætterens database direkte og skriver intet hos Oversætteren.

OVERSAETTER_URL = (os.environ.get("OVERSAETTER_URL") or "").rstrip("/")
OVERSAETTER_TOKEN = os.environ.get("OVERSAETTER_TOKEN") or ""
NORDIC_RE = re.compile(r"nordic|danish|dansk|dksubs?", re.I)
TR_PROBLEMS = ("fejlet", "mangler_engelsk", "forsoeg_igen", "ikke_muligt", "venter_paa_dansk")
_tr_cache = {"ts": 0.0, "days": None, "data": None}
_tr_lock = threading.Lock()
_ov_alert = {"budget": False, "down": 0, "down_sent": False}


def ov_enabled():
    return bool(OVERSAETTER_URL and OVERSAETTER_TOKEN)


def ov_get(path, params=None):
    r = httpx.get(OVERSAETTER_URL + path, params=params, headers={"X-Api-Token": OVERSAETTER_TOKEN}, timeout=15)
    if r.status_code == 401:
        raise RuntimeError("Oversætteren afviste nøglen – OVERSAETTER_TOKEN skal være lig API_TOKEN i oversætterens .env")
    r.raise_for_status()
    return r.json()


def _arr_of(typ):
    return next((i for i in INSTANCES.values() if i["type"] == typ), None)


def _days_in_month(d):
    nxt = (d.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return (nxt - datetime.timedelta(days=1)).day


def forecast(spend, today=None):
    """Prognose for månedens forbrug: forbrugt indtil nu + gennemsnit pr. dag de seneste 7 dage × dage tilbage."""
    today = today or datetime.date.today()
    since = (today - datetime.timedelta(days=7)).isoformat()
    last7 = sum(d["usd"] for d in spend.get("days", []) if d["day"] > since)
    per_day = last7 / 7
    left = _days_in_month(today) - today.day
    month = float(spend.get("month_usd") or 0)
    return {"per_day_usd": round(per_day, 3), "days_left": left, "month_usd": round(month, 2),
            "forecast_usd": round(month + per_day * left, 2), "budget_usd": spend.get("budget_usd")}


def delay_profiles():
    out = []
    for inst in INSTANCES.values():
        try:
            tags = {t["id"]: t["label"] for t in (arr(inst, "GET", "/tag") or [])}
            for d in arr(inst, "GET", "/delayprofile") or []:
                out.append({"instance": inst["name"], "order": d.get("order"), "torrent_min": d.get("torrentDelay"),
                            "bypass": d.get("bypassIfAboveCustomFormatScore"),
                            "min_score": d.get("minimumCustomFormatScore"),
                            "tags": [tags.get(t, str(t)) for t in d.get("tags") or []]})
        except Exception as e:
            out.append({"instance": inst["name"], "error": f"{e.__class__.__name__}"})
    return sorted(out, key=lambda d: (d["instance"], d.get("order") or 0))


@app.get("/api/translations")
def translations():
    """Fanen Oversættelser: A overblik, D færdige, E problemer og H indstillinger. Hver del fejler for sig."""
    if not ov_enabled():
        return {"enabled": False}
    out, errors = {"enabled": True}, []
    for key, path, params in (("status", "/api/status", None), ("config", "/api/config", None),
                              ("spend", "/api/spend", {"days": 60}),
                              ("done", "/api/items", {"status": "faerdig", "days": 30, "limit": 300}),
                              ("problems", "/api/items", {"status": ",".join(TR_PROBLEMS), "limit": 200})):
        try:
            out[key] = ov_get(path, params)
        except Exception as e:
            errors.append(f"{path}: {e.__class__.__name__}: {e}")
    if "spend" in out:
        out["forecast"] = forecast(out["spend"])
    try:
        out["reveal"] = ov_get("/api/reveal", {"days": 7})
    except Exception as e:
        errors.append(f"/api/reveal: {e.__class__.__name__}: {e}")
    out["on_the_way"] = on_the_way()
    out["delay_profiles"] = delay_profiles()
    out["errors"] = errors
    return out


def on_the_way():
    """Fanen Oversættelser › C: udgivelser, Sonarr/Radarr holder tilbage på grund af ventetiden (Delay Profile)."""
    out = []
    for inst in INSTANCES.values():
        movie = inst["type"] == "radarr"
        params = ({"includeUnknownMovieItems": "true", "includeMovie": "true"} if movie else
                  {"includeUnknownSeriesItems": "true", "includeSeries": "true", "includeEpisode": "true"})
        try:
            records = (arr(inst, "GET", "/queue", params={"pageSize": 500, **params}) or {}).get("records") or []
        except Exception as e:
            out.append({"instance": inst["name"], "error": e.__class__.__name__})
            continue
        for r in records:
            if str(r.get("status") or "").lower() != "delay":
                continue
            if movie:
                m = r.get("movie") or {}
                name = f"{m.get('title') or '?'} ({m.get('year') or '?'})"
            else:
                se, ep = r.get("series") or {}, r.get("episode") or {}
                name = f"{se.get('title') or '?'} {ep.get('seasonNumber', 0)}x{int(ep.get('episodeNumber') or 0):02d}"
            out.append({"instance": inst["name"], "title": name, "release": r.get("title") or "",
                        "nordic": bool(NORDIC_RE.search(r.get("title") or "")),
                        "score": r.get("customFormatScore"), "until": r.get("estimatedCompletionTime"),
                        "quality": ((r.get("quality") or {}).get("quality") or {}).get("name")})
    return sorted(out, key=lambda x: str(x.get("until") or ""))


# ---------------------------------------------------------------- skjult indtil dansk (Oversætterens trin C3)
# Oversætteren viser nye filer i Plex, når de har dansk tale/tekst - senest efter 24 timer (sikkerhedsnet).
# Fangarr sender en besked om hvert sikkerhedsnet. Svarer Oversætteren ikke i REVEAL_FALLBACK_MINUTES (60), beder
# Fangarr selv Plex vise de seneste importer (nødløsning), så intet bliver skjult for kunderne, mens den er nede.

PLEX_URL = (os.environ.get("PLEX_URL") or "").rstrip("/")
PLEX_TOKEN = os.environ.get("PLEX_TOKEN") or ""
PLEX_PATH_MAP = os.environ.get("PLEX_PATH_MAP") or ""
REVEAL_FALLBACK_MINUTES = int(os.environ.get("REVEAL_FALLBACK_MINUTES") or "60")
_rv = {"fail_since": None, "fallback_at": None, "fallback_sent": False}


def kv_get(key, default=None):
    con = db()
    row = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    con.close()
    return json.loads(row["value"]) if row else default


def kv_set(key, value):
    con = db()
    with con:
        con.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value)))
    con.close()


def plex_map(path):
    if "=" not in PLEX_PATH_MAP:
        return path
    old, new = (x.strip().rstrip("/") for x in PLEX_PATH_MAP.split("=", 1))
    if old and (path == old or path.startswith(old + "/")):
        return new + path[len(old):]
    return path


def plex_refresh(folders):
    """Bed Plex scanne mapperne (samme kald som Oversætteren). Returnerer antal mapper, Plex blev bedt om."""
    if not (PLEX_URL and PLEX_TOKEN) or not folders:
        return 0
    h = {"X-Plex-Token": PLEX_TOKEN, "Accept": "application/json"}
    r = httpx.get(PLEX_URL + "/library/sections", headers=h, timeout=20)
    r.raise_for_status()
    sections = r.json()["MediaContainer"].get("Directory") or []
    done = 0
    for folder in sorted(folders):
        folder = plex_map(folder)
        best, best_len = None, -1
        for sec in sections:
            for loc in sec.get("Location") or []:
                root = (loc.get("path") or "").rstrip("/")
                if root and (folder == root or folder.startswith(root + "/")) and len(root) > best_len:
                    best, best_len = sec.get("key"), len(root)
        if best is None:
            log.warning("Nødløsning: intet Plex-bibliotek indeholder %s", folder)
            continue
        httpx.get(f"{PLEX_URL}/library/sections/{best}/refresh", params={"path": folder}, headers=h,
                  timeout=20).raise_for_status()
        done += 1
    return done


def recent_import_folders(since):
    """Mapperne for alle importer i Sonarr/Radarr siden tidspunktet."""
    stamp = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    folders = set()
    for inst in INSTANCES.values():
        for h in arr(inst, "GET", "/history/since", params={"date": stamp, "eventType": "downloadFolderImported"}) or []:
            path = (h.get("data") or {}).get("importedPath")
            if path:
                folders.add(os.path.dirname(path))
    return folders


def notify_safety_net(shown):
    """Én besked pr. kørsel med de film/afsnit, der er vist uden dansk tekst efter 24 timer (kun nye)."""
    late = [x for x in shown if x.get("shown_by") == "sikkerhedsnet"]
    if not late:
        return
    con = db()
    seen = {r["id"] for r in con.execute("SELECT id FROM reveal_notified").fetchall()}
    new = [x for x in late if f"{x['key']}|{x['import_at']}" not in seen]
    with con:
        for x in new:
            con.execute("INSERT OR IGNORE INTO reveal_notified (id, ts) VALUES (?, ?)",
                        (f"{x['key']}|{x['import_at']}", iso(now())))
        con.execute("DELETE FROM reveal_notified WHERE ts < ?", (iso(now() - datetime.timedelta(days=30)),))
    con.close()
    if not new:
        return
    lines = "\n".join(f"• {x.get('title') or x['key']} – {x.get('reason') or ''}" for x in new[:20])
    more = f"\n… og {len(new) - 20} mere" if len(new) > 20 else ""
    telegram(f"⏰ Fangarr – vist i Plex UDEN dansk tekst (sikkerhedsnet):\n{lines}{more}\n\n"
             "Se Fangarr › Oversættelser › Skjult for kunderne.")


def check_reveal():
    """Køres fra baggrundsjobbet ca. hvert 5. minut."""
    if not ov_enabled():
        return
    try:
        data = ov_get("/api/reveal", {"days": 2})
    except Exception as e:
        if not kv_get("reveal_enabled", False):
            return  # trinnet er ikke slået til (eller har aldrig svaret) - intet at redde
        t = now()
        _rv["fail_since"] = _rv["fail_since"] or t
        if t - _rv["fail_since"] < datetime.timedelta(minutes=REVEAL_FALLBACK_MINUTES):
            return
        if _rv["fallback_at"] and t - _rv["fallback_at"] < datetime.timedelta(hours=1):
            return
        since = (_rv["fallback_at"] - datetime.timedelta(minutes=10)) if _rv["fallback_at"] else \
            t - datetime.timedelta(hours=48)
        try:
            n = plex_refresh(recent_import_folders(since))
        except Exception as e2:
            log.warning("Nødløsning: kunne ikke bede Plex vise nye filer: %s", e2)
            if not _rv["fallback_sent"]:
                telegram(f"🚨 Fangarr – Oversætteren svarer ikke ({e.__class__.__name__}), og Fangarr kunne heller "
                         f"ikke bede Plex vise nye filer ({e2.__class__.__name__}). Nye film/afsnit er skjult for "
                         "kunderne – tjek Oversætteren og PLEX_URL/PLEX_TOKEN i fangarr.env.")
                _rv["fallback_sent"] = True
            return
        _rv["fallback_at"] = t
        if not _rv["fallback_sent"]:
            telegram(f"🚨 Fangarr – Oversætteren har ikke svaret i {REVEAL_FALLBACK_MINUTES} minutter. Fangarr viser nu "
                     f"selv nye filer i Plex (også uden dansk tekst), så intet er skjult for kunderne. "
                     f"{n} mapper vist – gentages hver time.")
            _rv["fallback_sent"] = True
        log.info("Nødløsning: bad Plex vise %d mapper", n)
        return
    if _rv["fallback_sent"]:
        telegram("✅ Fangarr – Oversætteren svarer igen og skjuler igen nye filer, indtil de har dansk tekst.")
    _rv.update(fail_since=None, fallback_at=None, fallback_sent=False)
    enabled = bool(data.get("enabled"))
    if enabled != kv_get("reveal_enabled", False):
        kv_set("reveal_enabled", enabled)
    if enabled:
        notify_safety_net(data.get("shown") or [])


def classify_imports(days):
    """Importer de sidste dage fordelt på dansk tale / NORDiC / skal oversættes (som ~/optaelling.py)."""
    start = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result, imports = {}, {}
    for typ, media in (("sonarr", "series"), ("radarr", "movie")):
        inst = _arr_of(typ)
        if not inst:
            continue
        lang = {it["id"]: ((it.get("originalLanguage") or {}).get("name") or "") for it in library(inst, media)}
        counts = {"dansk_tale": 0, "nordic": 0, "oversaet": 0}
        per_day = {}
        for h in arr(inst, "GET", "/history/since", params={"date": start, "eventType": "downloadFolderImported"}) or []:
            owner = h.get("seriesId") if media == "series" else h.get("movieId")
            src = h.get("sourceTitle") or ""
            g = "dansk_tale" if lang.get(owner) == "Danish" else "nordic" if NORDIC_RE.search(src) else "oversaet"
            counts[g] += 1
            day = str(h.get("date") or "")[:10]
            per_day.setdefault(day, {"dansk_tale": 0, "nordic": 0, "oversaet": 0})[g] += 1
            ident = h.get("episodeId") if media == "series" else h.get("movieId")
            if ident:
                imports.setdefault(f"{'episode' if media == 'series' else 'movie'}:{ident}", []).append(
                    {"date": str(h.get("date") or ""), "nordic": bool(NORDIC_RE.search(src)), "source": src})
        result[media] = {"counts": counts, "per_day": [{"day": d, **c} for d, c in sorted(per_day.items())]}
    return result, imports


def series_name(title):
    """"Gold Rush 17x06" -> "Gold Rush"."""
    return re.sub(r"\s+\d+x\d+\s*$", "", str(title or "")).strip() or str(title or "")


def translation_stats(days):
    done = ov_get("/api/items", {"status": "faerdig", "days": max(days, 30), "limit": 1000})["items"]
    spend = ov_get("/api/spend", {"days": days})
    imports, imp = classify_imports(days)
    wasted = []
    for it in done:
        later = [x for x in imp.get(it["key"], []) if x["nordic"] and x["date"] > str(it.get("updated_at") or "")]
        if later:
            wasted.append({"title": it["title"], "cost_usd": it.get("cost_usd") or 0, "translated": it.get("updated_at"),
                           "nordic_at": later[0]["date"], "source": later[0]["source"]})
    top = {}
    for it in done:
        name = series_name(it["title"]) if it["media_type"] == "episode" else it["title"]
        g = top.setdefault(name, {"title": name, "count": 0, "usd": 0.0, "media": it["media_type"]})
        g["count"] += 1
        g["usd"] = round(g["usd"] + float(it.get("cost_usd") or 0), 4)
    return {"days": days, "spend": spend, "imports": imports, "wasted": wasted,
            "wasted_usd": round(sum(w["cost_usd"] for w in wasted), 2),
            "top": sorted(top.values(), key=lambda g: -g["usd"])[:15], "computed": iso(now())}


@app.get("/api/translations/stats")
def translations_stats(days: int = 14, refresh: int = 0):
    """Fanen Oversættelser › G statistik. Gemmes i 10 minutter (læser historikken i Sonarr/Radarr)."""
    if not ov_enabled():
        return {"enabled": False}
    days = max(1, min(60, days))
    with _tr_lock:
        if not refresh and _tr_cache["data"] and _tr_cache["days"] == days and time.time() - _tr_cache["ts"] < 600:
            return _tr_cache["data"]
    try:
        data = translation_stats(days)
    except Exception as e:
        raise HTTPException(502, f"kunne ikke beregne statistikken: {e.__class__.__name__}: {e}")
    with _tr_lock:
        _tr_cache.update(ts=time.time(), days=days, data=data)
    return data


def translation_summary_lines():
    """Linjer til det daglige resumé: oversat i går, pris, problemer og prognose."""
    if not ov_enabled():
        return []
    try:
        spend = ov_get("/api/spend", {"days": 3})
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        rows = [d for d in spend.get("days", []) if d["day"] == yesterday]
        n = sum(d["titles"] for d in rows)
        usd = sum(d["usd"] for d in rows)
        status = ov_get("/api/status")
        problems = ov_get("/api/items", {"status": "fejlet,mangler_engelsk", "days": 1, "limit": 200})["items"]
        f = forecast(ov_get("/api/spend", {"days": 10}))
    except Exception as e:
        return [f"🈯 Oversætteren kunne ikke spørges ({e.__class__.__name__})"]
    kurs = float(status.get("usd_to_dkk") or 6.7)
    line = f"🈯 Oversat i går: {n} ({usd * kurs:.0f} kr.)"
    if problems:
        line += f", {len(problems)} problem{'er' if len(problems) != 1 else ''}"
    out = [line, f"   Måned: {f['month_usd'] * kurs:.0f} kr. af {float(f['budget_usd'] or 0) * kurs:.0f} kr. – "
                 f"prognose {f['forecast_usd'] * kurs:.0f} kr."]
    return out


def check_translator():
    """Køres fra baggrundsjobbet ca. hvert 10. minut: besked ved prognose over loftet og når Oversætteren ikke svarer
    (efter 3 forsøg i træk), og "i orden igen" bagefter."""
    if not ov_enabled():
        return
    try:
        spend = ov_get("/api/spend", {"days": 10})
    except Exception as e:
        _ov_alert["down"] += 1
        if _ov_alert["down"] >= 3 and not _ov_alert["down_sent"]:
            telegram(f"🚨 Fangarr – Oversætteren svarer ikke ({e.__class__.__name__}). Nyt bliver ikke oversat.")
            _ov_alert["down_sent"] = True
        return
    if _ov_alert["down_sent"]:
        telegram("✅ Fangarr – Oversætteren svarer igen.")
    _ov_alert["down"], _ov_alert["down_sent"] = 0, False
    f = forecast(spend)
    budget = float(f["budget_usd"] or 0)
    over = budget > 0 and f["forecast_usd"] > budget
    if over and not _ov_alert["budget"]:
        telegram(f"⚠️ Fangarr – oversættelserne ventes at koste {f['forecast_usd']:.0f} USD denne måned, "
                 f"loftet er {budget:.0f} USD. Når loftet er nået, oversættes der ikke mere i denne måned.")
    elif not over and _ov_alert["budget"]:
        telegram(f"✅ Fangarr – prognosen for oversættelser er under loftet igen ({f['forecast_usd']:.0f} af {budget:.0f} USD).")
    _ov_alert["budget"] = over


# ---------------------------------------------------------------- knapperne (Oversætterens trin C4, Fase 4)
# "Oversæt nu" (valgte sæsoner/film), "Ingen ventetid fremover" (mærket straks), "Prøv igen" og "Opgiv".
# Fangarr skriver kun i Oversætterens egen database gennem den interne adresse, og sætter/fjerner mærker i
# Sonarr/Radarr. Seerr-ønsker: kun første download uden ventetid (mærket seerr-straks).

STRAKS_TAG = "straks"
SEERR_STRAKS_TAG = "seerr-straks"


def ov_post(path, body):
    r = httpx.post(OVERSAETTER_URL + path, json=body, headers={"X-Api-Token": OVERSAETTER_TOKEN}, timeout=60)
    if r.status_code == 401:
        raise RuntimeError("Oversætteren afviste nøglen – OVERSAETTER_TOKEN skal være lig API_TOKEN i oversætterens .env")
    return r.status_code, (r.json() if r.content else {})


def _ov_or_http_error(fn):
    try:
        return fn()
    except httpx.HTTPStatusError as e:
        try:
            msg = e.response.json().get("error")
        except ValueError:
            msg = None
        raise HTTPException(e.response.status_code, msg or f"Oversætteren svarede {e.response.status_code}")
    except (httpx.HTTPError, RuntimeError) as e:
        raise HTTPException(502, f"Oversætteren kunne ikke nås ({e.__class__.__name__}: {e})")


def _tag_ids(inst, labels):
    tags = {t["label"]: t["id"] for t in arr(inst, "GET", "/tag") or []}
    return {label: tags.get(label) for label in labels}


@app.get("/api/translations/search")
def translations_search(q: str = ""):
    """Find serier og film i Sonarr/Radarr til "Oversæt en titel"."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    want_n, want_l = norm(q), loose(q)
    out = []
    for inst in INSTANCES.values():
        media = "movie" if inst["type"] == "radarr" else "series"
        straks = _tag_ids(inst, [STRAKS_TAG])[STRAKS_TAG]
        for it in library(inst, media):
            names = [it.get("title") or ""] + [a.get("title") or "" for a in it.get("alternateTitles") or []]
            hit = 0
            for n in names:
                if norm(n) == want_n:
                    hit = max(hit, 3)
                elif norm(n).startswith(want_n):
                    hit = max(hit, 2)
                elif want_l and want_l in loose(n):
                    hit = max(hit, 1)
            if hit:
                out.append({"media": media, "instance": inst["name"], "id": it["id"], "title": it.get("title"),
                            "year": it.get("year"), "straks": straks is not None and straks in (it.get("tags") or []),
                            "_hit": hit})
    out.sort(key=lambda x: (-x["_hit"], str(x["title"])))
    for x in out:
        x.pop("_hit")
    return out[:15]


@app.get("/api/translations/estimate")
def translations_estimate(media: str, id: int):
    if not ov_enabled():
        raise HTTPException(400, "Oversætteren er ikke forbundet")
    params = {"movie_id": id} if media == "movie" else {"series_id": id}
    return _ov_or_http_error(lambda: ov_get("/api/estimate", params))


def _ov_post_or_error(path, body):
    try:
        code, out = ov_post(path, body)
    except (httpx.HTTPError, RuntimeError) as e:
        raise HTTPException(502, f"Oversætteren kunne ikke nås ({e.__class__.__name__}: {e})")
    if code != 200:
        raise HTTPException(code, out.get("error") or f"Oversætteren svarede {code}")
    return out


@app.post("/api/translations/translate")
async def translations_translate(req: Request):
    """"Oversæt nu": de valgte sæsoner (serie) eller filmen."""
    b = await req.json()
    media, ident = b.get("media"), int(b.get("id") or 0)
    if media == "movie":
        body = {"movie_id": ident}
    else:
        body = {"series_id": ident, "seasons": [int(s) for s in b.get("seasons") or []]}
    out = await run_in_threadpool(_ov_post_or_error, "/api/translate", body)
    write_log(media if media == "movie" else "series", "", out.get("title") or "", None, "oversæt nu", "",
              f"{out.get('added', 0)} lagt i kø hos Oversætteren", False)
    return out


@app.post("/api/translations/item")
async def translations_item(req: Request):
    """"Prøv igen" / "Opgiv" fra Problemer."""
    b = await req.json()
    action = b.get("action")
    if action not in ("retry", "skip"):
        raise HTTPException(400, "ukendt handling")
    path = "/api/items/retry" if action == "retry" else "/api/items/skip"
    return await run_in_threadpool(_ov_post_or_error, path, {"key": str(b.get("key") or "")})


def set_tag(inst, media, ident, label, on):
    """Sæt eller fjern et mærke på en serie/film. Returnerer True, hvis noget blev ændret."""
    path = f"/movie/{ident}" if media == "movie" else f"/series/{ident}"
    item = arr(inst, "GET", path)
    tid = tag_id(inst, label) if on else _tag_ids(inst, [label])[label]
    if tid is None:
        return False
    tags = list(item.get("tags") or [])
    if on == (tid in tags):
        return False
    item["tags"] = tags + [tid] if on else [t for t in tags if t != tid]
    arr(inst, "PUT", path, json=item)
    with _lib_lock:
        _lib_cache.pop((inst["name"], media), None)
    return True


@app.post("/api/translations/straks")
async def translations_straks(req: Request):
    """"Ingen ventetid fremover": mærket straks på serien/filmen (fjernes aldrig automatisk)."""
    b = await req.json()
    inst = INSTANCES.get(b.get("instance"))
    if not inst:
        raise HTTPException(400, "ukendt instans")
    media, ident, on = b.get("media"), int(b.get("id") or 0), bool(b.get("on"))
    changed = await run_in_threadpool(set_tag, inst, media, ident, STRAKS_TAG, on)
    write_log(media, "", str(b.get("title") or ident), None, "ingen ventetid" if on else "ventetid igen", "",
              f"mærket {STRAKS_TAG} {'sat på' if on else 'fjernet'} i {inst['name']}", False)
    return {"changed": changed, "on": on}


# ---- Seerr-ønsker: kun første download uden ventetid

def _seerr_straks_table():
    con = db()
    with con:
        con.execute("CREATE TABLE IF NOT EXISTS seerr_straks (series_id INTEGER PRIMARY KEY, set_at TEXT, request_id INTEGER)")
        con.execute("CREATE TABLE IF NOT EXISTS seerr_seen (request_id INTEGER PRIMARY KEY, ts TEXT)")
    return con


def _parse_utc(v):
    try:
        d = datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def _imported_since(inst, series_id, since):
    """Er der importeret et afsnit til serien efter tidspunktet (UTC)?"""
    stamp = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    for h in arr(inst, "GET", "/history/since", params={"date": stamp, "eventType": "downloadFolderImported"}) or []:
        if h.get("seriesId") == series_id:
            return True
    return False


def check_seerr_straks():
    """Køres ca. hvert 2. minut.

    1. Seerr-ønsker på en serie, der allerede findes i sonarr2: mærket seerr-straks sættes på, og der søges efter de
       ønskede sæsoner, så første download kommer uden ventetid. (Seerr sætter selv mærket på nye serier.)
    2. Serier med seerr-straks, hvor et afsnit er kommet hjem efter mærket blev sat: mærket fjernes, så senere
       afsnit får de normale 6 timers ventetid.
    """
    inst = _arr_of("sonarr")
    if not inst:
        return
    con = _seerr_straks_table()
    utc = datetime.datetime.now(datetime.timezone.utc)
    # 1. nye ønsker
    if SEERR_URL and SEERR_APIKEY:
        try:
            reqs = seerr_get("/request", {"take": 50, "skip": 0, "sort": "added", "filter": "all"}).get("results") or []
        except Exception as e:
            log.warning("Seerr-straks: kunne ikke hente ønsker fra Seerr: %s", e.__class__.__name__)
            reqs = []
        seen = {r["request_id"] for r in con.execute("SELECT request_id FROM seerr_seen").fetchall()}
        series = None
        for r in reqs:
            rid, created = r.get("id"), _parse_utc(r.get("createdAt"))
            if r.get("type") != "tv" or rid in seen or created is None or r.get("is4k"):
                continue
            if utc - created > datetime.timedelta(hours=48) or r.get("status") != 2:
                if utc - created > datetime.timedelta(hours=48):
                    with con:
                        con.execute("INSERT OR IGNORE INTO seerr_seen VALUES (?, ?)", (rid, iso(now())))
                continue
            tvdb = (r.get("media") or {}).get("tvdbId")
            if series is None:
                series = {s.get("tvdbId"): s for s in arr(inst, "GET", "/series") or []}
            s = series.get(tvdb)
            if s is None:
                if utc - created > datetime.timedelta(hours=2):  # kom aldrig i sonarr2 - opgiv
                    with con:
                        con.execute("INSERT OR IGNORE INTO seerr_seen VALUES (?, ?)", (rid, iso(now())))
                continue
            sid = s["id"]
            ids = _tag_ids(inst, [SEERR_STRAKS_TAG])
            has_tag = ids[SEERR_STRAKS_TAG] is not None and ids[SEERR_STRAKS_TAG] in (s.get("tags") or [])
            added = _parse_utc(s.get("added"))
            existing = added is not None and added < created - datetime.timedelta(minutes=10)
            if not has_tag and not _imported_since(inst, sid, created):
                set_tag(inst, "series", sid, SEERR_STRAKS_TAG, True)
                with con:
                    con.execute("INSERT OR REPLACE INTO seerr_straks VALUES (?, ?, ?)", (sid, utc.isoformat(), rid))
                seasons = [x.get("seasonNumber") for x in r.get("seasons") or [] if x.get("seasonNumber") is not None]
                for n in seasons or [None]:
                    cmd = {"name": "SeasonSearch", "seriesId": sid, "seasonNumber": n} if n is not None else \
                        {"name": "SeriesSearch", "seriesId": sid}
                    arr(inst, "POST", "/command", json=cmd)
                why = "eksisterende serie" if existing else "ny serie uden mærket"
                log.info("Seerr-straks: %s fik %s (%s) – søger sæson %s", s.get("title"), SEERR_STRAKS_TAG, why,
                         ", ".join(str(n) for n in seasons) or "alle")
                write_log("series", "", s.get("title") or "", s.get("year"), "seerr uden ventetid", "",
                          f"Seerr-ønske ({why}): {SEERR_STRAKS_TAG} sat på, søgning startet", False)
            with con:
                con.execute("INSERT OR IGNORE INTO seerr_seen VALUES (?, ?)", (rid, iso(now())))
    # 2. fjern mærket efter første import
    tid = _tag_ids(inst, [SEERR_STRAKS_TAG])[SEERR_STRAKS_TAG]
    if tid is not None:
        set_at = {r["series_id"]: r["set_at"] for r in con.execute("SELECT series_id, set_at FROM seerr_straks").fetchall()}
        for s in arr(inst, "GET", "/series") or []:
            if tid not in (s.get("tags") or []):
                continue
            since = _parse_utc(set_at.get(s["id"])) or _parse_utc(s.get("added"))
            if since is None or not _imported_since(inst, s["id"], since):
                continue
            set_tag(inst, "series", s["id"], SEERR_STRAKS_TAG, False)
            with con:
                con.execute("DELETE FROM seerr_straks WHERE series_id=?", (s["id"],))
            log.info("Seerr-straks: %s – første afsnit er hjemme, %s fjernet (6 timers ventetid fremover)",
                     s.get("title"), SEERR_STRAKS_TAG)
            write_log("series", "", s.get("title") or "", s.get("year"), "seerr-straks fjernet", "",
                      "første afsnit er hjemme – normal ventetid fremover", False)
    with con:
        con.execute("DELETE FROM seerr_seen WHERE ts < ?", (iso(now() - datetime.timedelta(days=7)),))
    con.close()


# ================================================================ kontodeling (Tautulli)
# Fanen Kontodeling: finder konti, hvor to tv afspiller samtidig fra hver sin adresse.
# Læser kun fra Tautulli (get_history) – ændrer intet, sender intet og gemmer intet på disken.

import ipaddress

TAUTULLI_URL = (os.environ.get("TAUTULLI_URL") or "").rstrip("/")
TAUTULLI_APIKEY = os.environ.get("TAUTULLI_APIKEY") or ""
_sharing = {"result": None}
SHARING_PAGE = 5000          # rækker pr. kald til Tautulli
SHARING_MAX_ROWS = 400000    # sikkerhedsloft
SHARING_LOOKBACK_DAYS = 30   # mindst så mange dage bruges til at finde ud af, hvilke tv der står sammen
SHARING_COLOC_DAYS = 3       # to tv står sammen, når de har delt adresse på mindst så mange forskellige dage
SHARING_MERGE_GAP = 20 * 60  # overlap mellem samme to tv med kortere pause end dette regnes som ét
SHARING_MAX_SESSION = 8 * 3600

TV_PLATFORMS = {"webos", "tvos", "roku", "tizen", "chromecast", "playstation", "xbox", "android tv", "netcast",
                "vizio", "vidaa", "fire tv", "firetv", "samsung", "lg", "apple tv"}
MOBILE_PLATFORMS = {"ios", "ipados", "windows", "macos", "osx", "linux", "chrome", "firefox", "safari",
                    "microsoft edge", "edge", "opera", "plexamp"}
TV_PRODUCTS = ("(tv)", "plex for lg", "plex for samsung", "plex for apple tv", "plex for roku", "plex for playstation",
               "plex for xbox", "plex for vizio", "smart tv", "chromecast")
MOBILE_PRODUCTS = ("(mobile)", "plex web", "plex for windows", "plex for mac", "plex for ios", "plex for linux",
                   "plex htpc", "plex media player", "plexamp", "plex desktop")
TV_PLAYER_WORDS = ("tv", "shield", "chromecast", "streamer", "bravia", "fire", "mibox", "mi box")


def tautulli_enabled():
    return bool(TAUTULLI_URL and TAUTULLI_APIKEY)


def tautulli(cmd, **params):
    """Kald Tautullis API. Fejlbeskederne indeholder aldrig adressen (API-nøglen står i den)."""
    if not tautulli_enabled():
        raise RuntimeError("Tautulli er ikke sat op (TAUTULLI_URL og TAUTULLI_APIKEY i fangarr.env)")
    try:
        r = httpx.get(f"{TAUTULLI_URL}/api/v2", params={"apikey": TAUTULLI_APIKEY, "cmd": cmd, **params},
                      timeout=120, follow_redirects=False)
    except httpx.HTTPError as e:
        raise RuntimeError(f"Tautulli svarer ikke ({e.__class__.__name__})") from None
    if r.status_code in (301, 302, 303, 307, 308):
        raise RuntimeError("Tautulli sendte videre til login – API'en kan ikke nås fra Fangarr")
    if r.status_code == 401:
        raise RuntimeError("Tautulli afviste API-nøglen (TAUTULLI_APIKEY)")
    if r.status_code != 200:
        raise RuntimeError(f"Tautulli svarede med fejl {r.status_code}")
    try:
        resp = r.json().get("response") or {}
    except ValueError:
        raise RuntimeError("Tautulli gav et svar, der ikke kunne læses") from None
    if resp.get("result") != "success":
        raise RuntimeError("Tautulli: " + str(resp.get("message") or "ukendt fejl")[:200])
    return resp.get("data")


kunder.setup(db=db, telegram=telegram, tautulli=tautulli, tautulli_enabled=tautulli_enabled, now=now,
             kv_get=kv_get, kv_set=kv_set, log=log)


def device_kind(platform, product, player):
    """'tv', 'mobil' eller 'ukendt'. Telefoner, tablets og computere er 'mobil' (kontoreglerne)."""
    p, pr, pl = (platform or "").lower().strip(), (product or "").lower(), (player or "").lower()
    if any(k in pr for k in TV_PRODUCTS) or p in TV_PLATFORMS or any(k in p for k in ("playstation", "xbox", "roku")):
        return "tv"
    if any(k in pr for k in MOBILE_PRODUCTS) or p in MOBILE_PLATFORMS:
        return "mobil"
    if p == "android" and any(k in pl for k in TV_PLAYER_WORDS):
        return "tv"   # Android uden oplysning om app: gæt ud fra enhedens navn
    return "ukendt"


def public_ip(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_unspecified)


import bisect
import gzip
import sys

SHARING_PARTED_DAYS = 14     # to enheder er gået hver til sit, når begge er brugt (3+ dage) senere end så mange dage efter sidste fælles dag
SHARING_STICKY_DAYS = 5      # en adresse er "fast", når kontoens tv har brugt den på mindst så mange forskellige dage
SHARING_MOVE_OVERLAP = 60    # flytning: det gamle og det nye sted må højst være i brug samtidig i så mange dage
SHARING_ORIGIN_DAYS = 14     # kontoens start: de første dage efter første tv-afspilning
SHARING_DEAD_DAYS = 45       # et sted er "ikke i brug", når det ikke er set i så mange dage
_sh_hist = {"rows": [], "fetched": "", "oldest": ""}
_sh_lock = threading.Lock()
SH_MARKS = ("kunde", "ikke", "godkendt")
SH_STATUS = ("", "blokeres", "blokeret", "undtagelse aftalt", "afsluttet", "advarsel sendt")


def _sharing_db():
    con = db()
    with con:
        con.execute("CREATE TABLE IF NOT EXISTS sharing_marks (user_id TEXT, mid TEXT, mark TEXT, note TEXT, updated TEXT,"
                    " PRIMARY KEY (user_id, mid))")
        con.execute("CREATE TABLE IF NOT EXISTS sharing_users (user_id TEXT PRIMARY KEY, status TEXT, note TEXT, updated TEXT)")
    return con


def _ord(ts):
    return datetime.date.fromtimestamp(ts).toordinal()


def _oday(o):
    return datetime.date.fromordinal(o).isoformat() if o else ""


def _sharing_session(r, now_ts):
    a = to_int(r.get("started"))
    if not a:
        return None
    b = to_int(r.get("stopped")) or now_ts
    if b <= a:
        return None
    b = min(b, a + SHARING_MAX_SESSION)
    # tid på pause trækkes fra, så en afspilning, der står på pause, ikke tæller som i gang
    b = max(a + 60, b - max(0, to_int(r.get("paused_counter"))))
    player, platform, product = str(r.get("player") or ""), str(r.get("platform") or ""), str(r.get("product") or "")
    ip = str(r.get("ip_address") or "").strip()
    mid = str(r.get("machine_id") or f"{player}|{platform}")
    if platform.lower().strip() == "chromecast" or "plex cast" in product.lower():
        # en Chromecast får nyt machine_id, hver gang der castes – regn alle casts fra samme adresse som én enhed
        mid, player = f"chromecast@{ip or '?'}", "Chromecast"
    i = sys.intern
    return {"uid": i(str(r.get("user_id") or r.get("user") or "?")), "user": i(str(r.get("user") or "")),
            "name": i(str(r.get("friendly_name") or r.get("user") or "?")), "a": a, "b": b, "d": _ord(a),
            "ip": i(ip), "pub": public_ip(ip), "mid": i(mid), "player": i(player or "?"), "platform": i(platform),
            "product": i(product), "kind": device_kind(platform, product, player),
            "title": str(r.get("full_title") or r.get("title") or "")[:80]}


SH_FILE = os.path.join(DATA_DIR, "kontodeling-historik.json.gz")
SH_COLS = ("uid", "user", "name", "a", "b", "d", "ip", "pub", "mid", "player", "platform", "product", "kind", "title")
SH_INTERN = ("uid", "user", "name", "ip", "mid", "player", "platform", "product")


def _sharing_save():
    """Gem den hentede historik på disken, så den ikke skal hentes forfra efter en genstart eller opdatering."""
    try:
        tmp = SH_FILE + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump({"v": 1, "cols": SH_COLS, "fetched": _sh_hist["fetched"],
                       "rows": [[r[c] for c in SH_COLS] for r in _sh_hist["rows"]]}, f, ensure_ascii=False)
        os.replace(tmp, SH_FILE)
    except (OSError, KeyError) as e:
        log.warning("Kontodeling: historikken kunne ikke gemmes: %s", e)


def _sharing_load():
    """Læs den gemte historik. Fejler det (ingen fil, gammel eller ødelagt fil), hentes alt bare forfra."""
    try:
        with gzip.open(SH_FILE, "rt", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("v") != 1 or tuple(d.get("cols") or ()) != SH_COLS:
            return False
        rows = []
        for vals in d["rows"]:
            r = dict(zip(SH_COLS, vals))
            for c in SH_INTERN:
                r[c] = sys.intern(str(r[c]))
            rows.append(r)
        rows.sort(key=lambda s: s["a"])
        _sh_hist.update(rows=rows, fetched=str(d.get("fetched") or ""),
                        oldest=iso(datetime.datetime.fromtimestamp(rows[0]["a"])) if rows else "")
        log.info("Kontodeling: %s afspilninger læst fra den gemte historik", len(rows))
        return bool(rows)
    except FileNotFoundError:
        return False
    except Exception as e:
        log.warning("Kontodeling: den gemte historik kunne ikke læses (%s) – henter forfra", e.__class__.__name__)
        return False


def sharing_history(job, full=False):
    """Hele historikken fra Tautulli (én række pr. afspilning). Første gang hentes alt; derefter kun det nye.
    Historikken gemmes på disken (kontodeling-historik.json.gz), så den også huskes efter en genstart."""
    with _sh_lock:
        if not full and not _sh_hist["rows"]:
            job["note"] = "læser den gemte historik"
            _sharing_load()
        now_ts, rows = int(time.time()), _sh_hist["rows"]
        if full or not rows:
            base, cutoff, after = [], 0, None
        else:
            cutoff = max(r["a"] for r in rows) - 2 * 86400
            base = [r for r in rows if r["a"] < cutoff]
            after = datetime.date.fromtimestamp(cutoff - 86400).isoformat()
        new, pos = [], 0
        job["note"] = "henter hele historikken fra Tautulli (kun første gang)" if not base else "henter nye afspilninger"
        while True:
            p = {"grouping": 0, "start": pos, "length": SHARING_PAGE, "order_column": "date", "order_dir": "asc"}
            if after:
                p["after"] = after
            d = tautulli("get_history", **p) or {}
            chunk = d.get("data") or []
            for r in chunk:
                s = _sharing_session(r, now_ts)
                if s and s["a"] >= cutoff:
                    new.append(s)
            pos += len(chunk)
            job["total"] = max(to_int(d.get("recordsFiltered")), pos)
            job["done"] = pos
            if len(chunk) < SHARING_PAGE or pos >= SHARING_MAX_ROWS:
                break
        rows = base + new
        rows.sort(key=lambda s: s["a"])
        _sh_hist.update(rows=rows, fetched=iso(now()), oldest=iso(datetime.datetime.fromtimestamp(rows[0]["a"])) if rows else "")
        job["note"] = "gemmer historikken"
        _sharing_save()
        job["note"] = ""
        return rows, pos >= SHARING_MAX_ROWS


def _dev_label(d):
    """Enhed i almindeligt sprog til beskeder og Tracearr-hjælp."""
    p = (d["platform"] or "").lower()
    if p == "tvos":
        return "Apple TV"
    if p == "chromecast" or d["mid"].startswith("chromecast"):
        return "Chromecast"
    if p in ("webos", "netcast"):
        return "LG-tv"
    if p in ("tizen", "samsung"):
        return "Samsung-tv"
    if "playstation" in p:
        return "PlayStation"
    if "xbox" in p:
        return "Xbox"
    if "roku" in p:
        return "Roku"
    return d["player"] if d["kind"] == "tv" else d["player"]


def _sharing_identities(ss):
    """Nogle tv (især Samsung) får nyt machine_id med jævne mellemrum, fx når Plex-appen opdateres.
    Et tv med samme navn og app, der begynder, når et andet er holdt op (højst 30 dage efter, og uden at de
    er brugt samtidig), regnes som det samme tv. Deler de en adresse, er det sikkert; ellers kræves, at der
    kun er én mulig forgænger. Giver {id: fælles id}, {fælles id: antal id'er} og {fælles id: forklaring}."""
    info = {}
    for x in ss:
        m = x["mid"]
        if x["kind"] != "tv" or m.startswith("chromecast@"):
            continue
        d = info.get(m)
        if d is None:
            d = info[m] = {"key": (x["player"], x["platform"], x["product"]), "first": x["a"], "last": x["a"], "ips": set()}
        d["last"] = max(d["last"], x["a"])
        if x["pub"]:
            d["ips"].add(x["ip"])
    canon = {x["mid"]: x["mid"] for x in ss}
    lines = {}     # nøgle -> liste af "linjer": {id, last, ips, n, weak}
    for m, d in sorted(info.items(), key=lambda t: t[1]["first"]):
        cands = [L for L in lines.get(d["key"], []) if L["last"] <= d["first"] + 86400 and d["first"] - L["last"] <= 30 * 86400]
        pick = None
        shared = [L for L in cands if L["ips"] & d["ips"]]
        if shared:
            pick = max(shared, key=lambda L: L["last"])
        elif len(cands) == 1:
            pick = cands[0]
            pick["weak"] = True     # samme navn og app, men ingen fælles adresse
        if pick is None:
            lines.setdefault(d["key"], []).append({"id": m, "last": d["last"], "ips": set(d["ips"]), "n": 1, "weak": False})
        else:
            canon[m] = pick["id"]
            pick["last"], pick["n"] = max(pick["last"], d["last"]), pick["n"] + 1
            pick["ips"] |= d["ips"]
    count = {L["id"]: L["n"] for ls in lines.values() for L in ls if L["n"] > 1}
    why = {L["id"]: ("samme navn og app, afløser hinanden uden fælles adresse" if L["weak"] else "samme navn, app og adresse")
           for ls in lines.values() for L in ls if L["n"] > 1}
    return canon, count, why


def _sharing_rules(username, sim, own_products, own_nets):
    """Find den bedste Tracearr-regel til at stoppe de tv, der ikke er kundens, og prøv hver mulighed af på
    brugerens egne afspilninger. sim = tv-afspilninger fra de seneste 90 dage: (klasse, app, adresse, dag, enhed),
    klasse = 'blok' (aldrig hos kunden / valgt: ikke kundens), 'egen' (kundens) eller 'andet' (tidligere/uafklaret)."""
    blk = [x for x in sim if x[0] == "blok"]
    own = [x for x in sim if x[0] == "egen"]
    oth = [x for x in sim if x[0] == "andet"]
    if not blk:
        return []
    net = lambda ip: ".".join(ip.split(".")[:2]) + ".0.0/16" if ip.count(".") == 3 else ""
    bprod = sorted({x[1] for x in blk if x[1]})
    free_prod = [p for p in bprod if p not in own_products]
    home = {}
    for x in own:
        home[x[2]] = home.get(x[2], 0) + 1
    htot = sum(home.values())
    htop = sorted(home.items(), key=lambda t: -t[1])[:2]
    home_ips = [ip for ip, _n in htop] if htot >= 10 and sum(n for _ip, n in htop) >= 0.98 * htot else []
    fdays = {}
    for x in blk:
        fdays.setdefault(x[2], set()).add(x[3])
    fixed = sorted(ip for ip, dd in fdays.items() if len(dd) >= 4 and ip not in home)
    rest = [x for x in blk if x[2] not in fixed]
    nets = sorted({net(x[2]) for x in rest if net(x[2]) and net(x[2]) not in own_nets})
    user = {"field": "User", "op": "is", "value": [username]}
    tv = {"field": "Device Type", "op": "is", "value": ["TV"]}
    cands = []

    def add(key, rank, title, conds, pred, why, risk):
        b, o, a = sum(1 for x in blk if pred(x)), sum(1 for x in own if pred(x)), sum(1 for x in oth if pred(x))
        if b:
            cands.append({"key": key, "rank": rank, "title": title, "conds": [user] + conds, "why": why, "risk": risk,
                          "blk_hit": b, "blk_total": len(blk), "own_hit": o, "own_total": len(own),
                          "oth_hit": a, "oth_total": len(oth),
                          "devices": sorted({x[4] for x in blk if pred(x)}), "missed": sorted({x[4] for x in blk if not pred(x)})})

    if free_prod:
        add("app", 5, "Stop appen, de fremmede tv bruger",
            [{"field": "Client/Player", "op": "equals" if len(free_prod) == 1 else "is one of", "value": free_prod}],
            lambda x: x[1] in free_prod,
            "Kundens egne tv har ikke brugt den app det seneste år, så reglen kan ikke ramme dem.",
            "Reglen rammer alle afspillere af den slags på kontoen. Køber kunden selv sådan en, bliver den også stoppet.")
    if fixed:
        add("adresse", 4, "Stop tv på de fremmede adresser",
            [tv, {"field": "IP Range", "op": "equals" if len(fixed) == 1 else "is one of", "value": [ip + "/32" for ip in fixed]}],
            lambda x: x[2] in fixed,
            "De fremmede tv står på en fast adresse, som kundens tv aldrig bruger.",
            "Skifter den fremmede adresse (ny internetudbyder, genstart af router hos nogle udbydere), holder reglen op med at virke, og du skal rette adressen.")
    if nets and len(nets) <= 6:
        allv = [ip + "/32" for ip in fixed] + nets
        add("net", 3, "Stop tv på de fremmede adresser og net" if fixed else "Stop tv på det fremmede net",
            [tv, {"field": "IP Range", "op": "equals" if len(allv) == 1 else "is one of", "value": allv}],
            lambda x: x[2] in fixed or net(x[2]) in nets,
            "De fremmede tv bruger et net med skiftende adresser (typisk mobilt bredbånd). Kundens tv har ikke brugt det net det seneste år.",
            "Et helt net dækker mange tusinde adresser hos samme udbyder. Tager kunden sit eget tv med et sted, der bruger samme udbyder, bliver det stoppet. Telefoner og tablets er ikke berørt.")
    if home_ips and bprod and bprod != free_prod:
        add("app-ude", 2, "Stop appen, når den bruges uden for kundens adresse",
            [{"field": "Client/Player", "op": "equals" if len(bprod) == 1 else "is one of", "value": bprod},
             {"field": "IP Range", "op": "not equals" if len(home_ips) == 1 else "is not one of", "value": [ip + "/32" for ip in home_ips]}],
            lambda x: x[1] in bprod and x[2] not in home_ips,
            "Kunden bruger selv samme app, men kun på sin faste adresse.",
            "Skifter kundens egen adresse, bliver kundens tv med den app stoppet, indtil reglen rettes.")
    if home_ips:
        add("hjemme", 1, "Tillad kun tv på kundens adresse",
            [tv, {"field": "IP Range", "op": "not equals" if len(home_ips) == 1 else "is not one of", "value": [ip + "/32" for ip in home_ips]}],
            lambda x: x[2] not in home_ips,
            "Kunden har fast adresse. Alt tv uden for den stoppes – også nye fremmede tv, der kommer til senere.",
            "Skifter kundens adresse, bliver kundens egne tv stoppet, indtil reglen rettes. Kundens tv på ferie eller i sommerhus stoppes også.")
    for c in cands:
        c["cover"] = round(100 * c["blk_hit"] / c["blk_total"])
    cands.sort(key=lambda c: (c["own_hit"] == 0, c["oth_hit"] == 0, c["cover"] >= 90, c["rank"], c["cover"]), reverse=True)
    if cands:
        cands[0]["recommended"] = cands[0]["own_hit"] == 0
    return cands


def _sharing_user(ss, lo, hi, min_seconds, marks, cut_ts, hist_start):
    """Analyse af én bruger ud fra HELE brugerens historik (ss, sorteret efter tid).
    Kundens enheder findes ved at følge en kæde fra kontoens første tv – der gættes ikke ud fra antal afspilninger."""
    fmt = lambda ts: iso(datetime.datetime.fromtimestamp(ts))
    # ---------- 0. samme tv med nyt id (Samsung m.fl. skifter machine_id): slå dem sammen til ét tv
    canon, id_count, id_why = _sharing_identities(ss)
    if any(k != v for k, v in canon.items()):
        ss = [x if canon[x["mid"]] == x["mid"] else {**x, "mid": canon[x["mid"]]} for x in ss]
    marks = {canon.get(m, m): mk for m, mk in marks.items()}
    # ---------- 1. enheder
    dev = {}
    for s in ss:
        d = dev.get(s["mid"])
        if d is None:
            d = dev[s["mid"]] = {"mid": s["mid"], "player": s["player"], "platform": s["platform"], "product": s["product"],
                                 "kind": s["kind"], "first": s["a"], "last": s["a"], "days": set(), "all_plays": 0}
        d["last"], d["player"] = s["a"], s["player"]
        d["days"].add(s["d"])
        d["all_plays"] += 1
    act = {m: sorted(d["days"]) for m, d in dev.items()}
    later = lambda m, o: len(act[m]) - bisect.bisect_right(act[m], o)   # aktive dage efter dag o
    tvs = [m for m, d in dev.items() if d["kind"] == "tv"]

    # ---------- 2. hvem har delt adresse (samme offentlige adresse inden for et døgn)
    by_ip, pair = {}, {}
    for s in ss:
        if s["pub"]:
            by_ip.setdefault(s["ip"], []).append(s)
    ipdays = {}
    for ip, lst in by_ip.items():
        last, per = {}, ipdays.setdefault(ip, {})
        for s in lst:
            per.setdefault(s["mid"], set()).add(s["d"])
            for m, ts in last.items():
                if m != s["mid"] and s["a"] - ts <= 86400:
                    pair.setdefault((m, s["mid"]) if m < s["mid"] else (s["mid"], m), set()).add(s["d"])
            last[s["mid"]] = s["a"]

    def parted(a, b):
        dd = pair.get((a, b) if a < b else (b, a))
        if not dd:
            return False
        L = max(dd) + SHARING_PARTED_DAYS
        return later(a, L) >= 3 and later(b, L) >= 3

    # ---------- 3. steder = tv, der står sammen
    parent = {m: m for m in tvs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    links, former = {}, {}     # links[(a,b)] = bevis for koblingen; former[m] = [(anden enhed, sidste fælles dag)]
    left_addr = {}             # tv, der har forladt en fast adresse, mens andre blev der: {enhed: en af dem, der blev}

    def link(a, b, kind, n, first, last_):
        links[(a, b)] = links[(b, a)] = {"kind": kind, "days": n, "first": first, "last": last_}
        parent[find(a)] = find(b)

    for (a, b), dd in pair.items():
        if dev[a]["kind"] != "tv" or dev[b]["kind"] != "tv":
            continue
        if parted(a, b):
            if len(dd) >= SHARING_COLOC_DAYS:
                former.setdefault(a, []).append((b, max(dd)))
                former.setdefault(b, []).append((a, max(dd)))
        elif len(dd) >= SHARING_COLOC_DAYS:
            link(a, b, "delt adresse", len(dd), min(dd), max(dd))
    # faste adresser: tv, der har brugt samme faste adresse, står samme sted – også når det ene har afløst det andet
    for ip, per in ipdays.items():
        tvd = {m: dd for m, dd in per.items() if dev[m]["kind"] == "tv"}
        alld = sorted(set().union(*tvd.values())) if tvd else []
        if len(alld) < SHARING_STICKY_DAYS:
            continue
        members = []
        for m, dd in tvd.items():
            if len(dd) < SHARING_COLOC_DAYS:
                continue
            L = max(dd) + SHARING_PARTED_DAYS
            others_later = len({o for mm, d2 in tvd.items() if mm != m for o in d2 if o > L})
            if later(m, L) >= 3 and others_later >= 3:
                stay = max(((len(d2), mm) for mm, d2 in tvd.items() if mm != m), default=(0, None))[1]
                if stay:
                    former.setdefault(m, []).append((stay, max(dd)))   # har forladt adressen, mens andre blev
                    left_addr[m] = stay
                continue
            members.append((min(dd), m))
        members.sort()
        for (_, m) in members[1:]:
            a = members[0][1]
            if find(a) != find(m) and (a, m) not in links:
                link(a, m, "samme faste adresse", len(tvd[m]), min(tvd[m]), max(tvd[m]))
    # løse enheder (brugt få dage): hægtes på det sted, de har delt adresse med
    size = {}
    for m in tvs:
        size[find(m)] = size.get(find(m), 0) + 1
    loose = {m for m in tvs if size[find(m)] == 1 and len(act[m]) < SHARING_COLOC_DAYS}
    for m in loose:
        best = None
        for (a, b), dd in pair.items():
            if m not in (a, b):
                continue
            o = b if m == a else a
            if o in loose or dev[o]["kind"] != "tv" or parted(a, b):
                continue
            key = (len(dd), dev[o]["all_plays"])
            if best is None or key > best[0]:
                best = (key, o, dd)
        if best:
            link(m, best[1], "delt adresse (få dage)", len(best[2]), min(best[2]), max(best[2]))
    # Chromecast på et net, hvor adressen skifter (mobilt bredbånd): hver adresse blev sin egen "enhed".
    # Dem, der ikke kunne kobles til noget tv, samles pr. net (de to første tal i adressen).
    size = {}
    for m in tvs:
        size[find(m)] = size.get(find(m), 0) + 1
    nets = {}
    for m in tvs:
        if m.startswith("chromecast@") and size[find(m)] == 1:
            nets.setdefault(".".join(m[11:].split(".")[:2]), []).append(m)
    for ms in nets.values():
        for m in ms[1:]:
            parent[find(m)] = find(ms[0])
    group = {m: find(m) for m in tvs}
    places = {}
    for m in tvs:
        p = places.setdefault(group[m], {"members": [], "first": dev[m]["first"], "last": dev[m]["last"]})
        p["members"].append(m)
        p["first"], p["last"] = min(p["first"], dev[m]["first"]), max(p["last"], dev[m]["last"])

    # ---------- 4. flytninger: en telefon/tablet set begge steder, og det gamle sted holdt op, da det nye begyndte
    mob_place = {}
    for (a, b), dd in pair.items():
        ka, kb = dev[a]["kind"], dev[b]["kind"]
        if (ka == "tv") == (kb == "tv"):
            continue
        t, m = (a, b) if ka == "tv" else (b, a)
        e = mob_place.setdefault(m, {}).setdefault(group[t], {"days": set(), "tv": t})
        e["days"] |= dd
    bridges, weak_br = {}, {}
    gap = SHARING_MOVE_OVERLAP * 86400
    for m, pl in mob_place.items():
        gs = list(pl)
        for i, g1 in enumerate(gs):
            for g2 in gs[i + 1:]:
                p1, p2 = places[g1], places[g2]
                # en flytning: det ene sted holdt op (højst 60 dages overlap), omkring da det andet begyndte.
                # To steder, der er i brug samtidig i lang tid, er to hjem – ikke en flytning.
                if not (p1["last"] <= p2["first"] + gap or p2["last"] <= p1["first"] + gap):
                    continue
                n = min(len(pl[g1]["days"]), len(pl[g2]["days"]))
                br = {"kind": "flytning", "days": n, "via": m, "a": pl[g1]["tv"], "b": pl[g2]["tv"],
                      "first": min(min(pl[g1]["days"]), min(pl[g2]["days"])),
                      "last": max(max(pl[g1]["days"]), max(pl[g2]["days"]))}
                target = bridges if n >= SHARING_COLOC_DAYS else weak_br   # under 3 dage hvert sted = for svagt til kæden
                cur = target.get((g1, g2))
                if cur is None or n > cur["days"]:
                    target[(g1, g2)] = target[(g2, g1)] = br

    # ---------- 5. udgangspunkt: kontoens første tv
    notes, info, origin, first_tv = [], [], None, None
    if tvs:
        first_tv = min(tvs, key=lambda m: dev[m]["first"])
        origin = group[first_tv]
        # er det første tv senere gået fra dem, det stod sammen med? Så er udgangspunktet dem, der blev tilbage
        weight = lambda g: len(places[g]["members"]) + sum(1 for pl in mob_place.values() if g in pl and len(pl[g]["days"]) >= SHARING_COLOC_DAYS)
        if first_tv in left_addr:
            origin = group[left_addr[first_tv]]
            info.append("Kontoens første tv er senere flyttet væk fra den faste adresse, kontoen startede på – enhederne, der blev på adressen, regnes som kunden.")
        else:
            for (o, _last) in former.get(first_tv, []):
                g = group[o]
                if g == origin or o in left_addr or dev[o]["first"] > dev[first_tv]["first"] + 90 * 86400:
                    continue
                if weight(g) > weight(origin):
                    origin = g
                    notes.append("Kontoens første tv er senere gået fra de enheder, det stod sammen med – de regnes som kunden, fordi flest enheder blev der.")
                elif weight(g) == weight(origin):
                    notes.append("Usikkert udgangspunkt: kontoens første tv og et tv, det stod sammen med fra start, er gået hver til sit.")
                break
        # blev kontoen brugt flere steder (uden fælles adresse) allerede i de første dage?
        t0 = dev[first_tv]["first"]
        early, par0 = {}, {}
        for x in ss:
            if x["a"] > t0 + SHARING_ORIGIN_DAYS * 86400:
                break
            if x["kind"] == "tv":
                par0.setdefault(x["mid"], x["mid"])
                if x["pub"]:
                    early.setdefault(x["ip"], set()).add(x["mid"])

        def f0(v):
            while par0[v] != v:
                v = par0[v]
            return v

        for ms in early.values():
            ms = list(ms)
            for o in ms[1:]:
                par0[f0(o)] = f0(ms[0])
        n0 = len({f0(v) for v in par0})
        old_account = t0 <= hist_start + 30 * 86400
        if old_account:
            info.append(f"Kontoen er formentlig ældre end Tautullis historik (begynder {fmt(hist_start)[:10]}). "
                        f"Udgangspunktet er derfor det første tv i historikken, ikke nødvendigvis kontoens første.")
        if n0 > 1:
            notes.append(f"Usikkert udgangspunkt: kontoen blev brugt på tv {n0} forskellige steder i de første {SHARING_ORIGIN_DAYS} dage"
                         + (" af historikken" if old_account else "") + ". Fangarr kan ikke se, hvilket af dem der er kundens – "
                         "afgør det selv med knapperne Kundens / Ikke kundens.")
    chain, via_bridge = set(), {}
    if origin is not None:
        chain, todo = {origin}, [origin]
        while todo:
            g = todo.pop()
            for (g1, g2), br in bridges.items():
                if g1 == g and g2 not in chain:
                    chain.add(g2)
                    via_bridge[g2] = (g1, br)
                    todo.append(g2)

    # ---------- 6. dine egne afgørelser
    forced, approved, denied = set(), set(), set()
    for m, mk in marks.items():
        g = group.get(m)
        if g is None:
            continue
        (forced if mk["mark"] == "kunde" else approved if mk["mark"] == "godkendt" else denied).add(g)
    chain = (chain | forced) - denied
    if forced and notes:     # du har selv valgt kundens sted – så er udgangspunktet ikke længere i tvivl
        info.append("Du har selv valgt kundens sted, så Fangarrs tvivl om udgangspunktet gælder ikke længere.")
        notes = []
    chain_last = max((places[g]["last"] for g in chain), default=0)
    now_cut = time.time() - SHARING_DEAD_DAYS * 86400
    chain_alive = chain_last >= now_cut

    def status_of(g):
        if g in denied:
            return "ikke", "valgt af dig: ikke kundens"
        if g in forced:
            return "kunde", "valgt af dig: kundens"
        if g in approved:
            return "godkendt", "godkendt undtagelse (valgt af dig)"
        if g in chain:
            return "kunde", ""
        for m in places[g]["members"]:
            for (o, lastd) in former.get(m, []):
                if group.get(o) in chain:
                    return "tidligere", f"stod sammen med {dev[o]['player']} til {_oday(lastd)}, men er siden brugt et andet sted"
        for (g1, g2), br in weak_br.items():
            if g1 == g and g2 in chain:
                dn = "dag" if br["days"] == 1 else "dage"
                return "uafklaret", (f"muligvis en flytning: {dev[br['via']]['player']} er set både hos kunden og her, "
                                     f"men kun {br['days']} {dn} hvert sted – for lidt til, at Fangarr tør afgøre det")
        if chain and not chain_alive and places[g]["last"] >= now_cut:
            return "uafklaret", f"kundens kendte enheder er ikke brugt siden {fmt(chain_last)[:10]} – muligvis en flytning, som ikke kan ses i historikken"
        if not chain:
            return "uafklaret", "kontoen har ingen kendt start"
        return "aldrig", "har aldrig delt adresse med kundens enheder"

    pstat = {g: status_of(g) for g in places}

    # ---------- 7. bevis for hver enhed i kæden (hvordan er den koblet til kontoens første tv?)
    why = {}
    if first_tv is not None and group[first_tv] in chain:
        why[first_tv] = f"kontoens første tv ({fmt(dev[first_tv]['first'])[:10]})"
    seen, todo = set(why), list(why)
    if not todo and chain:
        for g in chain:   # udgangspunktet er dem, der blev tilbage – start ved stedets ældste tv
            m0 = min(places[g]["members"], key=lambda m: dev[m]["first"])
            if g == origin:
                why[m0] = f"stod sammen med kontoens første tv fra starten ({fmt(dev[m0]['first'])[:10]})"
                seen.add(m0)
                todo.append(m0)
    while todo:
        a = todo.pop(0)
        for (x, b), lk in links.items():
            if x == a and b not in seen and group[b] in chain:
                seen.add(b)
                why[b] = f"{lk['kind']} med {dev[a]['player']} på {lk['days']} dage ({_oday(lk['first'])} – {_oday(lk['last'])})"
                todo.append(b)
        for g2, (g1, br) in via_bridge.items():
            if group[a] == g1:
                b = br["b"] if group[br["b"]] == g2 else br["a"]
                if b not in seen:
                    seen.add(b)
                    why[b] = (f"flytning: {dev[br['via']]['player']} er set både på det gamle sted og her "
                              f"(mindst {br['days']} dage hvert sted)")
                    todo.append(b)

    # ---------- 8. overlap i perioden: to tv fra hvert sit sted, hver sin adresse, på samme tid
    cur = [s for s in ss if s["kind"] == "tv" and s["pub"] and s["b"] >= lo and s["a"] <= hi]
    order = sorted(places, key=lambda g: (g not in chain, -sum(dev[m]["all_plays"] for m in places[g]["members"])))
    pidx, n = {}, 0
    for g in order:
        if g in chain:
            pidx[g] = 0
        else:
            n += 1
            pidx[g] = n
    pairs, ok_events = {}, 0
    for i, s1 in enumerate(cur):
        for s2 in cur[i + 1:]:
            if s2["a"] >= s1["b"]:
                break
            if s1["mid"] == s2["mid"] or s1["ip"] == s2["ip"] or group[s1["mid"]] == group[s2["mid"]]:
                continue
            if group[s1["mid"]] in chain and group[s2["mid"]] in chain:
                continue     # begge er kundens (fx gammelt og nyt hjem under en flytning)
            a, b = max(s1["a"], s2["a"]), min(s1["b"], s2["b"])
            if b - a < 60 or a < lo or a > hi:
                continue
            x, y = (s1, s2) if pidx[group[s1["mid"]]] <= pidx[group[s2["mid"]]] else (s2, s1)
            pairs.setdefault((x["mid"], y["mid"]), []).append((a, b, x, y))
    events = []
    for segs in pairs.values():
        segs.sort(key=lambda t: t[0])
        ev = None
        for a, b, x, y in segs:
            if ev and a - ev["end"] <= SHARING_MERGE_GAP:
                ev["seconds"] += max(0, b - max(a, ev["end"]))
                ev["end"] = max(ev["end"], b)
                for k, s in (("x", x), ("y", y)):
                    if s["title"] and s["title"] not in ev[k]["titles"]:
                        ev[k]["titles"].append(s["title"])
            else:
                ev = {"start": a, "end": b, "seconds": b - a}
                for k, s in (("x", x), ("y", y)):
                    g = group[s["mid"]]
                    ev[k] = {"mid": s["mid"], "player": s["player"], "ip": s["ip"], "place": pidx[g],
                             "status": pstat[g][0], "titles": [s["title"]] if s["title"] else []}
                events.append(ev)
    events = [e for e in events if e["seconds"] >= min_seconds]
    for e in events:
        e["approved"] = "godkendt" in (e["x"]["status"], e["y"]["status"])
    counted = sorted((e for e in events if not e["approved"]), key=lambda e: -e["start"])
    ok_events = sum(1 for e in events if e["approved"])
    eve = lambda e: time.strftime("%Y-%m-%d", time.localtime(e["start"] - 5 * 3600))   # en aften = kl. 05 til kl. 05
    evenings = sorted({eve(e) for e in counted})
    before = sorted({eve(e) for e in counted if cut_ts and e["start"] < cut_ts})
    after = sorted({eve(e) for e in counted if cut_ts and e["start"] >= cut_ts})
    involved = {e[k]["mid"] for e in counted for k in ("x", "y")}

    # ---------- 9. enheder til visning
    per = {}
    for s in ss:
        if s["b"] < lo or s["a"] > hi:
            continue
        p = per.setdefault(s["mid"], {"plays": 0, "ips": {}, "days": set()})
        p["plays"] += 1
        p["days"].add(s["d"])
        if s["pub"]:
            p["ips"][s["ip"]] = p["ips"].get(s["ip"], 0) + 1
    devices, cast = [], {}
    for m, d in dev.items():
        g = group.get(m)
        in_period = m in per
        st, why_not = pstat[g] if g is not None else ("", "")
        relevant = in_period or (g is not None and (g in chain or st in ("tidligere", "godkendt") or m in marks))
        if not relevant:
            continue
        p = per.get(m, {"plays": 0, "ips": {}, "days": set()})
        if d["kind"] != "tv":   # mobil: vis blot, om den er set hos kunden
            at = [gg for gg in mob_place.get(m, {}) if gg in chain]
            st, why_not = ("set hos kunden" if at else ""), ""
        row = {"mid": m, "mids": {m}, "player": d["player"], "label": _dev_label(d), "platform": d["platform"],
               "product": d["product"], "kind": d["kind"], "place": pidx.get(g) if g is not None else None,
               "status": st, "why": why.get(m) or why_not or "", "mark": (marks.get(m) or {}).get("mark", ""),
               "mark_note": (marks.get(m) or {}).get("note", ""), "plays": p["plays"], "period_days": len(p["days"]),
               "ips": dict(p["ips"]), "first": d["first"], "last": d["last"], "in_period": in_period,
               "ids": id_count.get(m, 1), "ids_why": id_why.get(m, ""), "group": g}
        if m.startswith("chromecast@") and g is not None:   # Chromecast: én linje pr. sted
            c = cast.get(g)
            if c:
                c["mids"].add(m)
                c["plays"] += row["plays"]
                c["period_days"] = max(c["period_days"], row["period_days"])
                for ip, k in row["ips"].items():
                    c["ips"][ip] = c["ips"].get(ip, 0) + k
                c["first"], c["last"] = min(c["first"], row["first"]), max(c["last"], row["last"])
                c["in_period"] = c["in_period"] or in_period
                c["mark"], c["mark_note"] = c["mark"] or row["mark"], c["mark_note"] or row["mark_note"]
                continue
            cast[g] = row
        devices.append(row)
    out_devices = []
    for r in devices:
        ips = sorted(r["ips"].items(), key=lambda t: -t[1])
        mids = r.pop("mids")
        out_devices.append({**r, "ips": [{"ip": ip, "plays": k} for ip, k in ips[:4]], "ip_count": len(ips),
                            "first": fmt(r["first"]), "last": fmt(r["last"]), "in_overlap": bool(mids & involved),
                            "all_mids": sorted(mids)[:100]})
    rank = {"kunde": 0, "godkendt": 1, "uafklaret": 2, "tidligere": 3, "aldrig": 4, "ikke": 4}
    out_devices.sort(key=lambda d: (not d["in_period"], d["kind"] != "tv", rank.get(d["status"], 5), -d["plays"]))

    # ---------- 10. skiftevis brug: tv, der ikke er kundens, brugt i perioden
    others = []
    for g in places:
        st = pstat[g][0]
        if st in ("kunde", "godkendt"):
            continue
        ms = [m for m in places[g]["members"] if m in per]
        if not ms:
            continue
        nights = len({eve(e) for e in counted if group[e["x"]["mid"]] == g or group[e["y"]["mid"]] == g})
        others.append({"place": pidx[g], "status": st, "devices": sorted({dev[m]["player"] for m in ms}),
                       "plays": sum(per[m]["plays"] for m in ms), "days": len(set().union(*(per[m]["days"] for m in ms))),
                       "evenings": nights})
    others.sort(key=lambda o: -o["plays"])

    # ---------- 11. steder (det, man afgør): ét sted = de tv, der står sammen
    BLOCK = ("aldrig", "ikke")
    place_rows = []
    for g in order:
        st, why_g = pstat[g]
        ds = [d for d in out_devices if d.get("group") == g]
        if not ds:
            continue
        act_ds = [d for d in ds if d["in_period"]]
        if not act_ds and st != "kunde":
            continue
        ipc = {}
        for d in act_ds:
            for i in d["ips"]:
                ipc[i["ip"]] = ipc.get(i["ip"], 0) + i["plays"]
        nip = sum(d["ip_count"] for d in act_ds)
        tot_ip = sum(ipc.values())
        top2 = sum(sorted(ipc.values(), reverse=True)[:2])
        nights = sorted({eve(e) for e in counted if group[e["x"]["mid"]] == g or group[e["y"]["mid"]] == g})
        place_rows.append({
            "place": pidx[g], "status": st, "why": (next((why[d["mid"]] for d in ds if d["mid"] in why), "") if st == "kunde" and not why_g else why_g),
            "names": sorted({d["player"] for d in (act_ds or ds)}), "tv_count": len(act_ds or ds), "active": bool(act_ds),
            "plays": sum(d["plays"] for d in act_ds), "days": max((d["period_days"] for d in act_ds), default=0),
            "net": "" if not act_ds else ("fast adresse" if tot_ip and nip <= 2 or (tot_ip and top2 >= 0.9 * tot_ip) else "skiftende adresser (mobilt net?)"),
            "first": min(d["first"] for d in ds), "last": max(d["last"] for d in ds),
            "evenings": len(nights), "last_overlap": max(nights) if nights else "",
            "mark": next((d["mark"] for d in ds if d["mark"]), ""), "mark_note": next((d["mark_note"] for d in ds if d["mark_note"]), ""),
            "mids": sorted({m for d in ds for m in d["all_mids"]})[:100]})
    for d in out_devices:
        d.pop("group", None)

    # ---------- 12. bedste blokering: prøv hver mulig Tracearr-regel af på de seneste 90 dage
    t90, t365 = time.time() - 90 * 86400, time.time() - 365 * 86400
    cls = lambda g: "egen" if pstat[g][0] in ("kunde", "godkendt") else ("blok" if pstat[g][0] in BLOCK else "andet")
    sim = [(cls(group[x["mid"]]), x["product"], x["ip"], x["d"], dev[x["mid"]]["player"])
           for x in ss if x["kind"] == "tv" and x["pub"] and x["a"] >= t90]
    own_long = [x for x in ss if x["kind"] == "tv" and x["a"] >= t365 and cls(group[x["mid"]]) == "egen"]
    rules = _sharing_rules(ss[-1]["user"], sim, {x["product"] for x in own_long},
                           {".".join(x["ip"].split(".")[:2]) + ".0.0/16" for x in own_long if x["pub"]})

    # ---------- 13. konklusion i klart sprog + hvilken bunke brugeren hører til
    blockable = [p for p in place_rows if p["status"] in BLOCK and p["active"]]
    b_over = [p for p in blockable if p["evenings"]]
    unclear_p = [p for p in place_rows if p["status"] == "uafklaret" and p["active"] and (p["evenings"] or p["plays"] >= 5)]
    former_p = [p for p in place_rows if p["status"] == "tidligere" and p["active"] and p["evenings"]]
    ntv = lambda ps: sum(p["tv_count"] for p in ps)
    tvs_txt = lambda ps: f"{ntv(ps)} tv ({', '.join(sorted({n for p in ps for n in p['names']}))})"
    if notes:
        bucket, concl = "afgoer", "Fangarr kan ikke se, hvilket sted der er kundens. Vælg selv kundens sted nedenfor – så får du en blokering."
    elif b_over:
        bucket = "bloker"
        rel = "som du har markeret som ikke kundens" if all(p["status"] == "ikke" for p in b_over) else "der aldrig har stået hos kunden"
        concl = (f"{tvs_txt(b_over)}, {rel}, bruges samtidig med kundens tv "
                 f"({len(evenings)} {'aften' if len(evenings) == 1 else 'aftener'} i perioden).")
    elif unclear_p:
        bucket, concl = "afgoer", f"{tvs_txt(unclear_p)} kan ikke kobles til kundens kendte tv. Afgør selv, om stedet er kundens."
    elif former_p:
        bucket, concl = "afgoer", f"{tvs_txt(former_p)} har tidligere stået hos kunden, men bruges nu et andet sted samtidig med kundens tv. Afgør selv, om det skal blokeres."
    elif blockable:
        bucket, concl = "skift", f"{tvs_txt(blockable)}, der aldrig har stået hos kunden, er brugt i perioden – men ikke samtidig med kundens tv."
    else:
        bucket, concl = "intet", "Ingen fremmede tv i perioden."
    if bucket in ("bloker", "skift") and rules:
        r0 = rules[0]
        concl += (f" Bedste blokering: {r0['title'].lower()} – den ville have stoppet {r0['blk_hit']} af {r0['blk_total']} fremmede "
                  f"afspilninger og {r0['own_hit']} af kundens {r0['own_total']} de seneste 90 dage.")

    return {"user_id": ss[0]["uid"], "name": ss[-1]["name"], "username": ss[-1]["user"],
            "plays": sum(p["plays"] for p in per.values()),
            "tv_places": len({d["place"] for d in out_devices if d["place"] is not None and d["in_period"]}),
            "evenings": len(evenings), "evening_dates": evenings, "before": len(before), "after": len(after),
            "overlaps": len(counted), "approved_overlaps": ok_events,
            "minutes": round(sum(e["seconds"] for e in counted) / 60),
            "last_overlap": fmt(counted[0]["start"]) if counted else "",
            "first_seen": fmt(ss[0]["a"]), "notes": notes, "info": info, "others": others,
            "places": place_rows,
            "rules": rules, "bucket": bucket, "conclusion": concl,
            "foreign_tv": ntv(blockable),
            "unclear": bool(notes) or any(d["status"] == "uafklaret" and d["in_period"] and (d["in_overlap"] or d["plays"] >= 5)
                                          for d in out_devices),
            "devices": out_devices,
            "events": [{"start": fmt(e["start"]), "end": fmt(e["end"]), "minutes": round(e["seconds"] / 60),
                        "approved": e["approved"],
                        "home": {**e["x"], "titles": e["x"]["titles"][:3]},
                        "other": {**e["y"], "titles": e["y"]["titles"][:3]}}
                       for e in sorted(events, key=lambda e: -e["start"])[:150]]}


def sharing_marks():
    con = _sharing_db()
    marks, users = {}, {}
    for r in con.execute("SELECT * FROM sharing_marks").fetchall():
        marks.setdefault(r["user_id"], {})[r["mid"]] = {"mark": r["mark"], "note": r["note"] or ""}
    for r in con.execute("SELECT * FROM sharing_users").fetchall():
        users[r["user_id"]] = {"status": r["status"] or "", "note": r["note"] or "", "updated": r["updated"] or ""}
    con.close()
    return marks, users


def run_sharing(job, start, end, min_minutes, red_days, cut, full):
    try:
        rows, capped = sharing_history(job, full)
        lo, hi = start.timestamp(), end.timestamp()
        marks, ustat = sharing_marks()
        by_user = {}
        for s in rows:
            if s["a"] <= hi:
                by_user.setdefault(s["uid"], []).append(s)
        users, kinds, hist_start = [], {}, (rows[0]["a"] if rows else 0)
        cut_ts = cut.timestamp() if cut else 0
        for uid, ss in by_user.items():
            if max(x["b"] for x in ss[-50:]) < lo:
                continue     # ingen afspilninger i perioden
            u = _sharing_user(ss, lo, hi, min_minutes * 60, marks.get(uid, {}), cut_ts, hist_start)
            if not u["plays"]:
                continue
            u["level"] = "rød" if u["evenings"] >= red_days else ("gul" if u["evenings"] >= 1 else "grøn")
            u["case"] = ustat.get(uid, {"status": "", "note": "", "updated": ""})
            users.append(u)
            for d in u["devices"]:
                if not d["in_period"]:
                    continue
                k = kinds.setdefault((d["platform"], d["product"], d["kind"]),
                                     {"platform": d["platform"], "product": d["product"], "kind": d["kind"], "devices": 0, "plays": 0})
                k["devices"] += 1
                k["plays"] += d["plays"]
        rank = {"rød": 0, "gul": 1, "grøn": 2}
        for u in users:
            if (u["case"].get("status") or "") in ("blokeres", "blokeret", "undtagelse aftalt", "advarsel sendt"):
                u["bucket"] = "igang"
        users.sort(key=lambda u: (-(u["after"] if cut else u["evenings"]), -u["evenings"], -u["foreign_tv"], -u["minutes"], u["name"].lower()))
        job["results"] = {"from": iso(start), "to": iso(end), "cut": iso(cut) if cut else "", "min_minutes": min_minutes,
                          "red_days": red_days, "sessions": sum(u["plays"] for u in users),
                          "history": {"rows": len(rows), "oldest": _sh_hist["oldest"], "fetched": _sh_hist["fetched"]},
                          "counts": {lv: sum(1 for u in users if u["level"] == lv) for lv in rank},
                          "buckets": {b: sum(1 for u in users if u["bucket"] == b) for b in ("bloker", "afgoer", "skift", "igang", "intet")},
                          "users": users, "kinds": sorted(kinds.values(), key=lambda k: -k["plays"])}
        note = []
        if capped:
            note.append("historikken er meget stor – kun de første afspilninger er med")
        unknown = sum(k["devices"] for k in kinds.values() if k["kind"] == "ukendt")
        if unknown:
            note.append(f"{unknown} enheder kunne ikke bestemmes som tv eller mobil (tælles ikke som tv) – se Enhedstyper nederst")
        job["note"] = " · ".join(note)
        job["status"] = "færdig"
        _sharing["result"] = {**job}
        kv_set("sharing_summary", {"at": iso(now()), "from": iso(start), "to": iso(end), "buckets": job["results"]["buckets"]})
    except Exception as e:
        log.exception("Kontodeling: analysen fejlede") if not isinstance(e, RuntimeError) else None
        job["status"] = "fejl"
        job["error"] = str(e) if isinstance(e, RuntimeError) else f"{e.__class__.__name__}: {e}"


def _sharing_day(v, end_of_day=False):
    try:
        d = datetime.datetime.strptime(str(v), "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "datoer skal skrives som ÅÅÅÅ-MM-DD")
    return d + datetime.timedelta(days=1) if end_of_day else d


@app.post("/api/sharing/run")
async def sharing_run(req: Request):
    try:
        b = await req.json()
    except ValueError:
        b = {}
    if not tautulli_enabled():
        raise HTTPException(400, "Tautulli er ikke sat op (TAUTULLI_URL og TAUTULLI_APIKEY i fangarr.env)")
    if any(j["kind"] == "sharing" and j["status"] == "kører" for j in _jobs.values()):
        raise HTTPException(409, "en analyse kører allerede")
    end = now()
    if b.get("from"):
        start = _sharing_day(b["from"])
        end = min(end, _sharing_day(b.get("to") or end.strftime("%Y-%m-%d"), True))
    else:
        start = end - datetime.timedelta(days=min(max(to_int(b.get("days")) or 30, 1), 1500))
    if start >= end:
        raise HTTPException(400, "startdatoen skal ligge før slutdatoen")
    cut = _sharing_day(b["cut"]) if b.get("cut") else None
    if cut and not (start < cut < end):
        raise HTTPException(400, "skæringsdatoen skal ligge inde i perioden")
    min_minutes = min(max(to_int(b.get("min_minutes")) or 10, 1), 240)
    red_days = min(max(to_int(b.get("red_days")) or 5, 1), 365)
    job = new_job("sharing")
    threading.Thread(target=run_sharing, args=(job, start, end, min_minutes, red_days, cut, bool(b.get("refresh"))),
                     daemon=True).start()
    return job


@app.get("/api/sharing")
def sharing_get():
    return _sharing["result"] or {}


@app.put("/api/sharing/mark")
async def sharing_mark(req: Request):
    """Din egen afgørelse for en enhed: 'kunde' (kundens), 'ikke' (ikke kundens), 'godkendt' (fx sommerhus) eller '' (fjern)."""
    b = await req.json()
    uid, mids, mark = str(b.get("user_id") or ""), b.get("mids") or [], str(b.get("mark") or "")
    if not uid or not mids or mark not in SH_MARKS + ("",):
        raise HTTPException(400, "mangler bruger, enhed eller gyldigt valg")
    con = _sharing_db()
    with con:
        for m in mids[:200]:
            if mark:
                con.execute("INSERT INTO sharing_marks VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, mid) DO UPDATE SET"
                            " mark=excluded.mark, note=excluded.note, updated=excluded.updated",
                            (uid, str(m), mark, str(b.get("note") or "")[:300], iso(now())))
            else:
                con.execute("DELETE FROM sharing_marks WHERE user_id=? AND mid=?", (uid, str(m)))
    con.close()
    log.info("Kontodeling: afgørelse '%s' gemt for bruger %s (%s enheder)", mark or "fjernet", uid, len(mids))
    return {"ok": True}


@app.put("/api/sharing/user")
async def sharing_user_put(req: Request):
    """Status og note på en bruger (hvor langt er du med sagen?)."""
    b = await req.json()
    uid, status = str(b.get("user_id") or ""), str(b.get("status") or "")
    if not uid or status not in SH_STATUS:
        raise HTTPException(400, "mangler bruger eller gyldig status")
    con = _sharing_db()
    with con:
        con.execute("INSERT INTO sharing_users VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET"
                    " status=excluded.status, note=excluded.note, updated=excluded.updated",
                    (uid, status, str(b.get("note") or "")[:1000], iso(now())))
    con.close()
    res = _sharing["result"]
    if res and res.get("results"):
        for u in res["results"].get("users", []):
            if u["user_id"] == uid:
                u["case"] = {"status": status, "note": str(b.get("note") or "")[:1000], "updated": iso(now())}
    return {"ok": True}


# ================================================================ 1.15: forside, forbindelser, version, status og søgning

GITHUB_VERSION_URL = os.environ.get("VERSION_URL") or "https://raw.githubusercontent.com/stream365vip-bot/fangarr/main/app/VERSION"
_cache = {}
_cache_lock = threading.Lock()


def cached(key, ttl, fn):
    """Gem svaret fra fn() i ttl sekunder, så forsiden ikke spørger de andre apps ved hver visning."""
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _cache_lock:
        _cache[key] = (time.time(), val)
    return val


# ---------------------------------------------------------------- version

def _ver_tuple(v):
    return tuple(to_int(x) for x in re.findall(r"\d+", str(v))[:3])


def _latest_version():
    try:
        r = httpx.get(GITHUB_VERSION_URL, timeout=10, follow_redirects=True)
        if r.status_code == 200 and re.fullmatch(r"\d+(\.\d+){1,2}", r.text.strip()):
            return r.text.strip()
    except httpx.HTTPError:
        pass
    return ""


@app.get("/api/version")
def version_info():
    """Den version, der kører, og den nyeste på GitHub (spørges højst hver 3. time)."""
    latest = cached("version", 3 * 3600, _latest_version)
    return {"version": VERSION, "latest": latest,
            "update": bool(latest) and _ver_tuple(latest) > _ver_tuple(VERSION)}


# ---------------------------------------------------------------- forbindelser

def _probe(name, fn):
    t = time.time()
    try:
        fn()
        return {"name": name, "ok": True, "detail": "", "ms": int((time.time() - t) * 1000)}
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        why = "afviste nøglen" if code in (401, 403) else f"svarede med fejl {code}"
        return {"name": name, "ok": False, "detail": why, "ms": int((time.time() - t) * 1000)}
    except httpx.HTTPError as e:
        return {"name": name, "ok": False, "detail": "svarer ikke" if isinstance(e, (httpx.ConnectError, httpx.TimeoutException)) else e.__class__.__name__, "ms": 0}
    except Exception as e:  # fx RuntimeError fra tautulli()/ov_get() – teksten indeholder aldrig nøgler
        return {"name": name, "ok": False, "detail": str(e)[:120] or e.__class__.__name__, "ms": 0}


def _get_ok(url, headers=None, params=None, ok=(200,)):
    r = httpx.get(url, headers=headers, params=params, timeout=8, follow_redirects=False)
    if r.status_code not in ok:
        raise httpx.HTTPStatusError("status", request=r.request, response=r)


def _connections():
    checks = []
    for inst in INSTANCES.values():
        checks.append((inst["name"], lambda i=inst: _get_ok(i["url"] + "/api/v3/system/status", {"X-Api-Key": i["apikey"]})))
    if AUTOBRR_URL and AUTOBRR_APIKEY:
        checks.append(("autobrr", lambda: _get_ok(AUTOBRR_URL + "/api/filters", {"X-API-Token": AUTOBRR_APIKEY})))
    if SEERR_URL and SEERR_APIKEY:
        checks.append(("Seerr", lambda: _get_ok(SEERR_URL + "/api/v1/settings/about", {"X-Api-Key": SEERR_APIKEY})))
    if tautulli_enabled():
        checks.append(("Tautulli", lambda: _get_ok(TAUTULLI_URL + "/api/v2", params={"apikey": TAUTULLI_APIKEY, "cmd": "get_server_friendly_name"})))
    if TRACEARR_URL and TRACEARR_APIKEY:
        # samme adresse som Statistik bruger: 200 eller 404 (titlen kendes ikke) betyder, at Tracearr svarer og nøglen virker
        checks.append(("Tracearr", lambda: _get_ok(f"{TRACEARR_URL}/api/v2/public/media/movie:tmdb:1/stats",
                                                    {"Authorization": f"Bearer {TRACEARR_APIKEY}"}, ok=(200, 404))))
    if ov_enabled():
        checks.append(("Oversætteren", lambda: ov_get("/api/health")))
    if PLEX_URL and PLEX_TOKEN:
        checks.append(("Plex", lambda: _get_ok(PLEX_URL + "/identity", {"X-Plex-Token": PLEX_TOKEN})))
    if not checks:
        return []
    with ThreadPoolExecutor(max_workers=len(checks)) as ex:
        return list(ex.map(lambda c: _probe(*c), checks))


@app.get("/api/connections")
def connections(refresh: int = 0):
    """Svarer de apps, Fangarr taler med? Kun dem, der er sat op i fangarr.env, vises. Gemmes i 60 sekunder."""
    if refresh:
        with _cache_lock:
            _cache.pop("connections", None)
    items = cached("connections", 60, _connections)
    return {"checked": iso(now()), "items": items}


# ---------------------------------------------------------------- "kom den hjem?" – status i Sonarr/Radarr

def _arr_snapshot(inst):
    """Titler og kø i én Sonarr/Radarr (uden Telegram-alarm ved fejl – forsiden må ikke larme)."""
    media = "movie" if inst["type"] == "radarr" else "series"
    h = {"X-Api-Key": inst["apikey"]}
    r = httpx.get(inst["url"] + "/api/v3" + ("/movie" if media == "movie" else "/series"), headers=h, timeout=30)
    r.raise_for_status()
    items = {to_int(x.get("id")): x for x in r.json() or []}
    queue = {}
    try:
        q = httpx.get(inst["url"] + "/api/v3/queue", headers=h, timeout=20,
                      params={"pageSize": 500, "includeUnknownMovieItems": "false", "includeUnknownSeriesItems": "false"})
        q.raise_for_status()
        for rec in (q.json() or {}).get("records") or []:
            queue[to_int(rec.get("movieId") if media == "movie" else rec.get("seriesId"))] = str(rec.get("status") or "").lower()
    except (httpx.HTTPError, ValueError):
        pass
    return {"items": items, "queue": queue}


def arr_state(inst, media, arr_id, snap):
    """Er titlen hentet? state: hentet · delvist · henter · venter · mangler · fjernet."""
    it = snap["items"].get(to_int(arr_id))
    if not it:
        return {"state": "fjernet", "text": f"findes ikke længere i {inst['name']}", "path": ""}
    qs = snap["queue"].get(to_int(arr_id))
    if media == "movie":
        path = f"/movie/{it.get('tmdbId')}"
        if it.get("hasFile"):
            return {"state": "hentet", "text": "hentet", "path": path}
        if qs:
            return {"state": "venter" if qs == "delay" else "henter",
                    "text": "holdes tilbage (ventetid)" if qs == "delay" else "er ved at blive hentet", "path": path}
        if not it.get("isAvailable", True):
            return {"state": "venter", "text": "ikke udgivet endnu", "path": path}
        return {"state": "mangler", "text": "ikke hentet endnu", "path": path}
    path = f"/series/{it.get('titleSlug')}"
    st = it.get("statistics") or {}
    have, want = to_int(st.get("episodeFileCount")), to_int(st.get("episodeCount"))
    if want and have >= want:
        return {"state": "hentet", "text": f"alle {want} udsendte afsnit hentet", "path": path}
    if qs:
        return {"state": "venter" if qs == "delay" else "henter",
                "text": (f"{have} af {want} afsnit · " if have else "") + ("holdes tilbage (ventetid)" if qs == "delay" else "henter"), "path": path}
    if have:
        return {"state": "delvist", "text": f"{have} af {want} udsendte afsnit hentet", "path": path}
    if not want:
        return {"state": "venter", "text": "ingen afsnit udsendt endnu", "path": path}
    return {"state": "mangler", "text": f"0 af {want} udsendte afsnit hentet", "path": path}


def added_status(limit=300):
    """Det, Fangarr har lagt i Sonarr/Radarr (nyeste først), med status for om det er kommet hjem."""
    con = db()
    rows = [dict(r) for r in con.execute("SELECT * FROM added ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    con.close()
    snaps = {}
    for name in {r["instance"] for r in rows}:
        inst = INSTANCES.get(name)
        if not inst:
            continue
        try:
            snaps[name] = cached(("snap", name), 300, lambda i=inst: _arr_snapshot(i))
        except (httpx.HTTPError, ValueError):
            snaps[name] = None
    out = []
    for r in rows:
        inst, snap = INSTANCES.get(r["instance"]), snaps.get(r["instance"])
        if not inst or not snap:
            s = {"state": "ukendt", "text": f"{r['instance']} svarer ikke", "path": ""}
        else:
            s = arr_state(inst, r["media"], r["arr_id"], snap)
        out.append({"ts": r["ts"], "media": r["media"], "instance": r["instance"], "title": r["title"],
                    "rule": r["rule"] or "", **s})
    return out


@app.get("/api/added")
def added_get(limit: int = 300):
    return added_status(min(max(limit, 1), 1000))


# ---------------------------------------------------------------- premierer: tal i menuen

_prem_bg = {"ts": 0.0, "items": None}


def refresh_premieres_bg():
    """Kaldes af baggrundsjobbet hver 6. time: hent de kommende danske premierer, så menuen kan vise et tal."""
    if not SEERR_URL or not SEERR_APIKEY or time.time() - _prem_bg["ts"] < 6 * 3600:
        return
    _prem_bg["ts"] = time.time()
    try:
        _prem_bg["items"] = fetch_premieres(21, "da")
    except Exception as e:
        log.warning("Premierer kunne ikke hentes til menuen: %s", e.__class__.__name__)


def premieres_new():
    """Kommende danske serier (3 uger), som hverken findes, følges eller er set af dig på siden Premierer."""
    if not _prem_bg["items"]:
        return 0
    try:
        items = premiere_status([dict(x) for x in _prem_bg["items"]])
    except Exception:
        return 0
    seen = set(kv_get("premieres_seen", []) or [])
    return sum(1 for i in items if not i["exists"] and not i["following"] and i.get("tmdb") not in seen)


@app.post("/api/premieres/seen")
async def premieres_seen(req: Request):
    """Siden Premierer er åbnet: de viste titler tæller ikke længere som nye i menuen."""
    try:
        b = await req.json()
    except ValueError:
        b = {}
    ids = [to_int(x) for x in (b.get("ids") or []) if to_int(x)]
    seen = set(kv_get("premieres_seen", []) or []) | set(ids)
    kv_set("premieres_seen", sorted(seen)[-2000:])
    return {"ok": True}


# ---------------------------------------------------------------- forside

def _translator_brief():
    """Kort status fra Oversætteren til forsiden. Hver del fejler for sig."""
    out = {"enabled": True, "ok": True, "problems": None, "hidden": None, "month_kr": None, "forecast_kr": None,
           "budget_kr": None, "queue": None}
    kurs = 6.7
    try:
        st = ov_get("/api/status")
        kurs = float(st.get("usd_to_dkk") or kurs)
    except Exception:
        out["ok"] = False
        return out
    try:
        items = ov_get("/api/items", {"status": ",".join(TR_PROBLEMS), "limit": 200}).get("items") or []
        out["problems"] = sum(1 for i in items if i.get("status") != "ikke_muligt")
    except Exception:
        pass
    try:
        rv = ov_get("/api/reveal", {"days": 1})
        out["hidden"] = len(rv.get("waiting") or []) if rv.get("enabled") else None
    except Exception:
        pass
    try:
        f = forecast(ov_get("/api/spend", {"days": 10}))
        out["month_kr"] = round(f["month_usd"] * kurs)
        out["forecast_kr"] = round(f["forecast_usd"] * kurs)
        out["budget_kr"] = round(float(f["budget_usd"] or 0) * kurs) or None
    except Exception:
        pass
    return out


def _kunder_brief():
    try:
        return kunder.brief()
    except Exception as e:
        log.warning("Kunder-overblik fejlede: %s", e)
        return {"enabled": False}


@app.get("/api/overview")
def overview():
    """Forsiden: det, der kræver handling, dagens tal og det seneste, der er sendt til Sonarr/Radarr."""
    s = get_settings()
    day = iso(now() - datetime.timedelta(days=1))
    con = db()
    waiting = con.execute("SELECT COUNT(*) FROM waitlist WHERE status='venter'").fetchone()[0]
    sugg = con.execute("SELECT COUNT(*) FROM waitlist WHERE status='venter' AND suggestions NOT IN ('', '[]')").fetchone()[0]
    errors = con.execute("SELECT COUNT(*) FROM log WHERE ts>=? AND decision='fejl'", (day,)).fetchone()[0]
    rescued = con.execute("SELECT COUNT(*) FROM log WHERE ts>=? AND decision='hentet for sonarr2'", (day,)).fetchone()[0]
    con.close()
    tr = cached("translator_brief", 60, _translator_brief) if ov_enabled() else {"enabled": False}
    try:
        recent = added_status(8)
    except Exception:
        recent = []
    try:
        prem_new = premieres_new()
    except Exception:
        prem_new = 0
    return {
        "dry_run": bool(s["dry_run"]), "disk_pct": disk_pct(), "max_disk_pct": s["max_disk_pct"],
        "today": {"series": added_today("series"), "movie": added_today("movie")},
        "waiting": waiting, "suggestions": sugg, "errors_24h": errors, "rescued_24h": rescued,
        "translator": tr, "sharing": kv_get("sharing_summary") if tautulli_enabled() else None,
        "premieres_new": prem_new, "recent": recent, "kunder": _kunder_brief(),
    }


# ---------------------------------------------------------------- søg efter en titel

@app.get("/api/search")
def search(q: str = ""):
    """Alt, Fangarr har gjort med en titel: log, venteliste, tilføjelser, koblinger, fjernede titler og oversættelser."""
    q = (q or "").strip()
    if len(q) < 2:
        return {"q": q, "log": [], "waitlist": [], "added": [], "aliases": [], "ignored": [], "translations": []}
    like = "%" + q.replace("%", "").replace("_", " ") + "%"
    key = loose(q)
    con = db()
    logs = [dict(r) for r in con.execute(
        "SELECT * FROM log WHERE title LIKE ? OR release LIKE ? ORDER BY id DESC LIMIT 60", (like, like)).fetchall()]
    wait = [dict(r) for r in con.execute(
        "SELECT id, created, media, title, release, attempts, next_try, status, reason, rule FROM waitlist"
        " WHERE title LIKE ? OR release LIKE ? ORDER BY id DESC LIMIT 20", (like, like)).fetchall()]
    aliases = [dict(r) for r in con.execute(
        "SELECT * FROM aliases WHERE release_title LIKE ? OR title LIKE ? ORDER BY id DESC LIMIT 20", (like, like)).fetchall()]
    ignored = [dict(r) for r in con.execute("SELECT * FROM ignored WHERE title LIKE ? ORDER BY id DESC LIMIT 20", (like,)).fetchall()]
    con.close()
    try:
        added = [a for a in added_status(1000) if q.lower() in (a["title"] or "").lower() or (key and key in loose(a["title"]))][:20]
    except Exception:
        added = []
    trans = []
    if ov_enabled():
        for params in ({"status": "faerdig", "days": 30, "limit": 300}, {"status": ",".join(TR_PROBLEMS), "limit": 200}):
            try:
                for i in ov_get("/api/items", params).get("items") or []:
                    if q.lower() in str(i.get("title") or "").lower():
                        trans.append({"title": i.get("title"), "status": i.get("status"), "reason": i.get("reason") or "",
                                      "updated_at": i.get("updated_at"), "cost_usd": i.get("cost_usd")})
            except Exception:
                pass
    return {"q": q, "log": logs, "waitlist": wait, "added": added, "aliases": aliases, "ignored": ignored,
            "translations": trans[:30]}
