"""Hentegrænse (Fangarr 1.22.0, udvidet i 1.22.1) – når trackeren afviser hentninger, søger Fangarr afsnittene igen senere.

Baggrund: Superbits afviser hentninger, når der hentes mange torrents på kort tid (set 20. nov. 2026: fem gik
igennem på otte sekunder, resten blev afvist). Det sker, når sonarr2 henter mange enkeltafsnit på én gang, fx
når en bruger ønsker flere sæsoner i Seerr. sonarr2 skriver "API Grab Limit reached" og "Couldn't add release …
to download queue" i sin log – og prøver ALDRIG igen. Afsnittene bliver stående som manglende.

Det gør Fangarr (hvert 2. minut, kun sonarr2):
1. Læser sonarr2's log og finder de udgivelser, der blev afvist på grund af grænsen.
2. Finder serien og afsnittene ud fra udgivelsens navn og husker dem (tabellen `grab_retry`). Kun afsnit, der
   er overvågede og mangler en fil, kommer med.
   Fra 1.22.1 kommer seriens ØVRIGE manglende afsnit også med (overvågede, uden fil, allerede sendt, ikke
   specials). Grunden: efter en afvisning sætter sonarr2 trackeren på pause og søger resten af serien uden
   den ("1 active indexers" i loggen) – de afsnit bliver hverken fundet eller afvist, og der står ingen fejl.
   Sådan forsvandt Hell's Kitchen sæson 25 den 20. nov. 2026.
3. Sender ÉN besked pr. serie til Telegram (Stream365 Drift).
4. Beder sonarr2 søge afsnittene igen i små portioner: GRAB_RETRY_BATCH afsnit (3) hvert GRAB_RETRY_MINUTES
   minut (10). Afsnit, der er kommet hjem, ligger i køen eller ikke længere er overvågede, røres ikke.
5. Sender "i orden igen", når alle afsnit er hjemme. Mangler nogle stadig efter GRAB_RETRY_HOURS timer (24),
   giver Fangarr op og skriver, hvilke afsnit der skal søges i hånden.

Første gang jobbet kører, læser det loggen GRAB_LOOKBACK_HOURS timer (48) tilbage, så afvisninger fra før
opdateringen også kommer med. Fangarr henter aldrig selv noget her – den beder kun sonarr2 søge, så sonarr2's
egne regler (profil, ventetid, point) gælder som altid. Slås fra med GRAB_RETRY=false i fangarr.env.
"""
import datetime
import os
import re
import urllib.parse

from fastapi import APIRouter

router = APIRouter()

ENABLED = (os.environ.get("GRAB_RETRY") or "true").strip().lower() not in ("false", "0", "nej", "no")
BATCH = max(1, int(os.environ.get("GRAB_RETRY_BATCH") or "3"))
MINUTES = max(1, int(os.environ.get("GRAB_RETRY_MINUTES") or "10"))
HOURS = max(1, int(os.environ.get("GRAB_RETRY_HOURS") or "24"))
LOOKBACK_HOURS = max(1, int(os.environ.get("GRAB_LOOKBACK_HOURS") or "48"))
MAX_PAGES = 30          # højst 3.000 loglinjer pr. runde
NEAR_SECONDS = 15       # så tæt skal "Couldn't add release" ligge på "Grab Limit reached" for at høre sammen

_RE_ADD = re.compile(r"Couldn't add release '(.+?)' from Indexer (.+?) to download queue", re.I)
_RE_LIMIT = re.compile(r"Grab Limit reached", re.I)
_RE_429 = re.compile(r"429|TooManyRequests|Grab Limit", re.I)

_d = {}


def setup(**deps):
    """Kobles på i main.py: arr, sonarr (giver sonarr2-instansen), db, telegram, write_log, kv_get, kv_set, log."""
    _d.update(deps)


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse_time(v):
    try:
        d = datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def _table():
    con = _d["db"]()
    with con:
        con.execute("CREATE TABLE IF NOT EXISTS grab_retry (episode_id INTEGER PRIMARY KEY, series_id INTEGER,"
                    " series TEXT, label TEXT, release TEXT, indexer TEXT, found_at TEXT, tries INTEGER DEFAULT 0,"
                    " last_try TEXT, status TEXT DEFAULT 'venter', notified INTEGER DEFAULT 0)")
        if "kind" not in [r[1] for r in con.execute("PRAGMA table_info(grab_retry)").fetchall()]:
            # 1.22.1: 'afvist' = trackeren afviste hentningen, 'ekstra' = seriens øvrige manglende afsnit
            con.execute("ALTER TABLE grab_retry ADD COLUMN kind TEXT DEFAULT 'afvist'")
    return con


def release_from_url(message):
    """Udgivelsens navn fra "API Grab Limit reached for http://prowlarr…&file=<navn>" – tom, hvis det ikke står der."""
    m = re.search(r"[?&]file=([^&\s]+)", message or "")
    return urllib.parse.unquote_plus(m.group(1)).strip() if m else ""


def rejected_releases(records):
    """Udgivelser, der blev afvist på grund af hentegrænsen. `records` er linjer fra sonarr2's log (nyeste først
    eller ældste først – rækkefølgen er ligegyldig). Returnerer {udgivelse: (indexer, tidspunkt)}."""
    limit_times, out, adds = [], {}, []
    for r in records:
        msg, t = r.get("message") or "", _parse_time(r.get("time"))
        if t is None:
            continue
        if _RE_LIMIT.search(msg):
            limit_times.append(t)
            name = release_from_url(msg)
            if name:
                out.setdefault(name, ("", t))
        m = _RE_ADD.search(msg)
        if m:
            adds.append((m.group(1).strip(), m.group(2).strip(), t, str(r.get("exception") or "")))
    for name, indexer, t, exc in adds:
        near = any(abs((t - lt).total_seconds()) <= NEAR_SECONDS for lt in limit_times)
        if near or _RE_429.search(exc):
            out[name] = (indexer, t)
    return out


def _fetch_log(inst, since):
    """sonarr2's loglinjer (advarsler og fejl) nyere end `since`."""
    out = []
    for page in range(1, MAX_PAGES + 1):
        data = _d["arr"](inst, "GET", "/log", params={"page": page, "pageSize": 100, "sortKey": "time",
                                                      "sortDirection": "descending", "level": "warn"}) or {}
        recs = data.get("records") or []
        if not recs:
            break
        done = False
        for r in recs:
            t = _parse_time(r.get("time"))
            if t is not None and t <= since:
                done = True
                break
            out.append(r)
        if done:
            break
    return out


def ep_label(ep):
    return "S%02dE%02d" % (int(ep.get("seasonNumber") or 0), int(ep.get("episodeNumber") or 0))


def short_list(labels, limit=12):
    """S21E04, S21E05 … som kort tekst: "S21E04–E08, S25E01" (højst `limit` stykker)."""
    eps = sorted({(int(m.group(1)), int(m.group(2))) for m in (re.match(r"S(\d+)E(\d+)$", x) for x in labels) if m})
    parts, i = [], 0
    while i < len(eps):
        j = i
        while j + 1 < len(eps) and eps[j + 1][0] == eps[i][0] and eps[j + 1][1] == eps[j][1] + 1:
            j += 1
        parts.append("S%02dE%02d" % eps[i] if j == i else "S%02dE%02d–E%02d" % (eps[i][0], eps[i][1], eps[j][1]))
        i = j + 1
    if len(parts) > limit:
        parts = parts[:limit] + ["…"]
    return ", ".join(parts)


def _n(count):
    return "1 afsnit" if count == 1 else f"{count} afsnit"


def scan(inst, con):
    """Trin 1-3: find nye afvisninger i sonarr2's log, husk afsnittene, og send én besked pr. serie."""
    utc = _utcnow()
    since = _parse_time(_d["kv_get"]("grab_seen")) or utc - datetime.timedelta(hours=LOOKBACK_HOURS)
    records = _fetch_log(inst, since)
    newest = max((t for t in (_parse_time(r.get("time")) for r in records) if t is not None), default=None)
    found = rejected_releases(records)
    new = {}   # series_id -> {"title":…, "labels":[…], "indexer":…}
    for name, (indexer, _t) in found.items():
        try:
            p = _d["arr"](inst, "GET", "/parse", params={"title": name}) or {}
        except Exception as e:   # ét navn, sonarr2 ikke kan læse, må ikke stoppe resten
            _d["log"].warning("Hentegrænse: kunne ikke slå %s op i sonarr2 (%s)", name, e.__class__.__name__)
            continue
        series = p.get("series") or {}
        if not series.get("id"):
            continue
        for ep in p.get("episodes") or []:
            if not ep.get("id") or ep.get("hasFile") or not ep.get("monitored"):
                continue
            old = con.execute("SELECT status FROM grab_retry WHERE episode_id=?", (ep["id"],)).fetchone()
            if old and old["status"] == "venter":
                continue   # er allerede i gang – ingen ny besked
            with con:
                con.execute("INSERT OR REPLACE INTO grab_retry (episode_id, series_id, series, label, release, indexer,"
                            " found_at, tries, last_try, status, notified) VALUES (?,?,?,?,?,?,?,0,NULL,'venter',0)",
                            (ep["id"], series["id"], series.get("title") or "", ep_label(ep), name, indexer,
                             utc.isoformat()))
            g = new.setdefault(series["id"], {"title": series.get("title") or "", "labels": [], "indexer": indexer})
            g["labels"].append(ep_label(ep))
            g["indexer"] = g["indexer"] or indexer
    if newest is not None:
        _d["kv_set"]("grab_seen", newest.isoformat())
    elif _d["kv_get"]("grab_seen") is None:
        _d["kv_set"]("grab_seen", utc.isoformat())
    return new


def expand(inst, con):
    """1.22.1: tag seriens øvrige manglende afsnit med. Køres én gang pr. sag (pr. serie, pr. ny afvisning).
    Returnerer {series_id: {"title":…, "labels":[…]}} med de afsnit, der blev lagt til."""
    utc = _utcnow()
    seen = _d["kv_get"]("grab_expanded") or {}
    out = {}
    # også når de afviste afsnit allerede er kommet hjem – resten af serien kan stadig mangle
    rows = con.execute("SELECT series_id, series, MAX(found_at) AS latest FROM grab_retry"
                       " WHERE kind='afvist' AND found_at > ? GROUP BY series_id",
                       ((utc - datetime.timedelta(hours=HOURS)).isoformat(),)).fetchall()
    for r in rows:
        key = str(r["series_id"])
        if seen.get(key) and seen[key] >= r["latest"]:
            continue   # denne sag er allerede udvidet
        have = {x["episode_id"] for x in con.execute("SELECT episode_id FROM grab_retry WHERE series_id=? AND"
                                                     " status='venter'", (r["series_id"],)).fetchall()}
        labels = []
        for ep in _d["arr"](inst, "GET", "/episode", params={"seriesId": r["series_id"]}) or []:
            aired = _parse_time(ep.get("airDateUtc"))
            if (ep.get("id") in have or ep.get("hasFile") or not ep.get("monitored")
                    or not ep.get("seasonNumber") or aired is None or aired > utc):
                continue
            with con:
                con.execute("INSERT OR REPLACE INTO grab_retry (episode_id, series_id, series, label, release, indexer,"
                            " found_at, tries, last_try, status, notified, kind) VALUES (?,?,?,?,'','',?,0,NULL,'venter',0,'ekstra')",
                            (ep["id"], r["series_id"], r["series"], ep_label(ep), utc.isoformat()))
            labels.append(ep_label(ep))
        seen[key] = utc.isoformat()
        if labels:
            out[r["series_id"]] = {"title": r["series"], "labels": labels}
    _d["kv_set"]("grab_expanded", seen)
    return out


def announce(new, extra):
    """Én besked pr. serie: de afviste afsnit og (1.22.1) seriens øvrige manglende afsnit."""
    for sid in list(new) + [x for x in extra if x not in new]:
        g, e = new.get(sid), extra.get(sid)
        title = (g or e)["title"]
        tail = f"Fangarr beder sonarr2 søge dem igen, {BATCH} ad gangen hvert {MINUTES}. minut. Du skal ikke gøre noget."
        more = (f"\n\nSeriens øvrige manglende afsnit tages også med ({_n(len(e['labels']))}: {short_list(e['labels'])}) – "
                "de kan være sprunget over, fordi sonarr2 sætter trackeren på pause efter en afvisning.") if e else ""
        if g:
            who = (g["indexer"] or "Trackeren").replace(" (Prowlarr)", "")
            text = (f"⚠️ Fangarr – hentegrænse\n\n{who} afviste {_n(len(g['labels']))} af {title}, fordi der blev hentet "
                    f"for meget på én gang: {short_list(g['labels'])}.{more}\n\n{tail}")
            detail = f"{who} afviste {_n(len(g['labels']))} ({short_list(g['labels'])})"
            if e:
                detail += f" + {_n(len(e['labels']))} øvrige manglende ({short_list(e['labels'])})"
            detail += " – søges igen i portioner"
        else:
            text = (f"⚠️ Fangarr – hentegrænse\n\n{title}: Fangarr tager også seriens øvrige manglende afsnit med "
                    f"({_n(len(e['labels']))}: {short_list(e['labels'])}). De kan være sprunget over, fordi sonarr2 sætter "
                    f"trackeren på pause efter en afvisning.\n\n{tail}")
            detail = f"{_n(len(e['labels']))} øvrige manglende tages med ({short_list(e['labels'])}) – søges igen i portioner"
        _d["telegram"](text)
        _d["log"].info("Hentegrænse: %s – %s", title, detail)
        _d["write_log"]("series", "", title, None, "hentegrænse", "", detail, False)


def retry(inst, con):
    """Trin 4-5: opdatér status, søg næste portion, og meld færdig."""
    utc = _utcnow()
    rows = con.execute("SELECT * FROM grab_retry WHERE status='venter' ORDER BY tries, kind, found_at, label, episode_id").fetchall()
    if rows:
        queued = set()
        q = _d["arr"](inst, "GET", "/queue", params={"page": 1, "pageSize": 1000}) or {}
        for rec in q.get("records") or []:
            if rec.get("episodeId"):
                queued.add(rec["episodeId"])
        eps = {}
        for sid in {r["series_id"] for r in rows}:
            for ep in _d["arr"](inst, "GET", "/episode", params={"seriesId": sid}) or []:
                eps[ep["id"]] = ep
        waiting = []
        for r in rows:
            ep = eps.get(r["episode_id"])
            found = _parse_time(r["found_at"]) or utc
            if ep is None or not ep.get("monitored"):
                status = "droppet"       # slettet eller ikke længere overvåget – ikke vores sag mere
            elif ep.get("hasFile"):
                status = "hentet"
            elif utc - found > datetime.timedelta(hours=HOURS):
                status = "opgivet"
            else:
                if r["episode_id"] not in queued:
                    waiting.append(r)
                continue
            with con:
                con.execute("UPDATE grab_retry SET status=? WHERE episode_id=?", (status, r["episode_id"]))
        last = _parse_time(_d["kv_get"]("grab_last_batch"))
        if waiting and (last is None or utc - last >= datetime.timedelta(minutes=MINUTES)):
            batch = waiting[:BATCH]
            _d["arr"](inst, "POST", "/command", json={"name": "EpisodeSearch",
                                                      "episodeIds": [r["episode_id"] for r in batch]})
            with con:
                for r in batch:
                    con.execute("UPDATE grab_retry SET tries=tries+1, last_try=? WHERE episode_id=?",
                                (utc.isoformat(), r["episode_id"]))
            _d["kv_set"]("grab_last_batch", utc.isoformat())
            _d["log"].info("Hentegrænse: søger igen – %s",
                           ", ".join(f"{r['series']} {r['label']}" for r in batch))
    # meld færdig pr. serie, når intet venter mere
    done = con.execute("SELECT * FROM grab_retry WHERE notified=0 AND status!='venter' AND series_id NOT IN"
                       " (SELECT series_id FROM grab_retry WHERE status='venter')").fetchall()
    by = {}
    for r in done:
        by.setdefault(r["series_id"], []).append(r)
    for sid, rs in by.items():
        title = rs[0]["series"]
        got = [r["label"] for r in rs if r["status"] == "hentet"]
        lost = [r["label"] for r in rs if r["status"] == "opgivet"]
        if lost:
            text = (f"⚠️ Fangarr – hentegrænse\n\n{title}: {_n(len(lost))} mangler stadig efter {HOURS} timer: "
                    f"{short_list(lost)}." + (f" {_n(len(got)).capitalize()} kom hjem." if got else "") +
                    "\n\nFangarr søger dem ikke mere. Søg dem selv i sonarr2 (forstørrelsesglasset ud for afsnittet).")
            detail = f"opgivet efter {HOURS} timer: {short_list(lost)}" + (f" – {_n(len(got))} kom hjem" if got else "")
        elif got:
            text = f"✅ Fangarr – hentegrænse i orden igen\n\n{title}: alle {_n(len(got))} er hentet ({short_list(got)})."
            detail = f"alle {_n(len(got))} hentet efter ny søgning ({short_list(got)})"
        else:
            text, detail = "", ""   # alt blev droppet (fx ikke længere overvåget) – ingen besked
        if text:
            _d["telegram"](text)
            _d["log"].info("Hentegrænse: %s – %s", title, detail)
            _d["write_log"]("series", "", title, None, "hentegrænse", "", detail, False)
        with con:
            con.execute("UPDATE grab_retry SET notified=1 WHERE series_id=? AND status!='venter'", (sid,))
    with con:
        con.execute("DELETE FROM grab_retry WHERE notified=1 AND found_at < ?",
                    ((utc - datetime.timedelta(days=30)).isoformat(),))


def tick():
    """Køres ca. hvert 2. minut fra baggrundsjobbet i main.py."""
    if not ENABLED:
        return
    inst = _d["sonarr"]()
    if not inst:
        return
    con = _table()
    try:
        new = scan(inst, con)
        extra = expand(inst, con)
        announce(new, extra)
        retry(inst, con)
    finally:
        con.close()


@router.get("/api/hentegraense")
def state():
    """Til Indstillinger: hvad der venter lige nu, og hvad der er sket de sidste 30 dage."""
    if not _d.get("db"):
        return {"enabled": False, "waiting": [], "recent": []}
    con = _table()
    rows = [dict(r) for r in con.execute("SELECT * FROM grab_retry ORDER BY found_at DESC, label").fetchall()]
    con.close()
    return {"enabled": ENABLED and bool(_d["sonarr"]()), "batch": BATCH, "minutes": MINUTES, "hours": HOURS,
            "waiting": [r for r in rows if r["status"] == "venter"],
            "recent": [r for r in rows if r["status"] != "venter"][:50]}
