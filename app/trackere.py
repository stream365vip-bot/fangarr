"""Trackerne (2.3.0) – Drift › Trackere.

Fangarr spørger qBittorrent hvert 15. minut (eget login i fangarr.env: QBIT_URL, QBIT_USER, QBIT_PASS) og viser
pr. tracker: antal torrents, ratio, upload, torrents der endnu ikke har opfyldt trackerens krav (seedet X timer
eller ratio Y), torrents der står stille før kravet (stoppet, fejl, manglende filer) og torrents med tracker-fejl.

Risiko for hit-and-run giver besked i Stream365 Drift:
- en torrent er stoppet eller har fejl, før kravet er opfyldt,
- en torrent er forsvundet fra qBittorrent, før kravet var opfyldt.
Besked kun ved nye problemer og "i orden igen". Fangarr ændrer intet i qBittorrent – den læser kun.

Kravene rettes på siden (standard fra trackernes regler: SuperBits 48 t eller
ratio 1,1 · NordicBytes 48 t eller 1,0 · TorrentLeech 240 t eller 1,0 – uden besked, så længe du har VIP).
"""

import datetime
import os
import threading
import time

import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api")
D = {}   # udfyldes af main.py: db, kv_get, kv_set, now, iso, telegram, log

QBIT_URL = (os.environ.get("QBIT_URL") or "").rstrip("/")
QBIT_USER = os.environ.get("QBIT_USER") or ""
QBIT_PASS = os.environ.get("QBIT_PASS") or ""
EVERY = int(os.environ.get("QBIT_CHECK_MINUTES") or "15") * 60

TRACKERS = [   # navn, ord i tracker-adressen eller i qbit_manage's mærker
    ("SuperBits", ("superbits", "sptracker")),
    ("NordicBytes", ("nordicbytes", "nordicswarm", "polarswarm")),
    ("TorrentLeech", ("torrentleech", "tleechreload")),
]
DEFAULT_RULES = {"SuperBits": {"hours": 48, "ratio": 1.1, "alert": True},
                 "NordicBytes": {"hours": 48, "ratio": 1.0, "alert": True},
                 "TorrentLeech": {"hours": 240, "ratio": 1.0, "alert": False},
                 "Andet": {"hours": 0, "ratio": 0, "alert": False}}
STALLED = {"stoppedUP", "stoppedDL", "pausedUP", "pausedDL", "error", "missingFiles"}
RULES_KEY, STATE_KEY = "tr_rules", "tr_state"

_s = {"cookie": None, "last": 0.0, "data": None, "err": ""}
_lock = threading.Lock()


def setup(**deps):
    D.update(deps)


def enabled():
    return bool(QBIT_URL and QBIT_USER and QBIT_PASS)


def init():
    con = D["db"]()
    with con:
        con.execute("CREATE TABLE IF NOT EXISTS tr_watch (hash TEXT PRIMARY KEY, tracker TEXT, name TEXT, added TEXT,"
                    " seed_h REAL DEFAULT 0, ratio REAL DEFAULT 0, last_seen TEXT, gone_at TEXT, notified INTEGER DEFAULT 0)")
        con.execute("CREATE TABLE IF NOT EXISTS tr_snap (day TEXT, tracker TEXT, uploaded INTEGER, downloaded INTEGER,"
                    " PRIMARY KEY (day, tracker))")
    con.close()


def rules():
    r = {k: dict(v) for k, v in DEFAULT_RULES.items()}
    for k, v in (D["kv_get"](RULES_KEY, {}) or {}).items():
        if k in r:
            r[k].update(v)
    return r


def tracker_of(t):
    hay = " ".join([t.get("tracker") or "", t.get("tags") or ""]).lower()
    for name, words in TRACKERS:
        if any(w in hay for w in words):
            return name
    return "Andet"


def met(t, rule):
    """Kravet er opfyldt: seedet nok timer (kun færdige torrents) eller nået ratioen."""
    if not rule["hours"] and not rule["ratio"]:
        return True
    hours = (t.get("seeding_time") or 0) / 3600
    done = (t.get("progress") or 0) >= 1
    return (done and rule["hours"] and hours >= rule["hours"]) or (rule["ratio"] and (t.get("ratio") or 0) >= rule["ratio"])


# ---------------------------------------------------------------- qBittorrent

def _login(c):
    """qBittorrent 5.2+ svarer 204 uden tekst og kalder cookien QBT_SID_<port>; ældre udgaver svarer 200 "Ok." og SID."""
    r = c.post(QBIT_URL + "/api/v2/auth/login", data={"username": QBIT_USER, "password": QBIT_PASS},
               headers={"Referer": QBIT_URL})
    if r.status_code == 403:
        raise RuntimeError("qBittorrent har midlertidigt spærret Fangarr efter for mange forkerte logins")
    ok = r.status_code == 204 or (r.status_code == 200 and r.text.strip() == "Ok.")
    sid = next(((k, v) for k, v in r.cookies.items() if "SID" in k.upper()), None)
    if not ok or not sid:
        raise RuntimeError("qBittorrent afviste login (QBIT_USER/QBIT_PASS i fangarr.env)")
    _s["cookie"] = sid


def torrents():
    with httpx.Client(timeout=30) as c:
        if _s["cookie"]:
            c.cookies.set(*_s["cookie"])
        r = c.get(QBIT_URL + "/api/v2/torrents/info", headers={"Referer": QBIT_URL})
        if r.status_code in (401, 403):
            _login(c)
            c.cookies.set(*_s["cookie"])
            r = c.get(QBIT_URL + "/api/v2/torrents/info", headers={"Referer": QBIT_URL})
        r.raise_for_status()
        return r.json()


def summarize(ts, rl):
    by = {}
    for t in ts:
        name = tracker_of(t)
        rule = rl.get(name) or rl["Andet"]
        g = by.setdefault(name, {"name": name, "count": 0, "size": 0, "uploaded": 0, "downloaded": 0, "pending": [], "stalled": [],
                                 "issues": [], "rule": rule})
        g["count"] += 1
        g["size"] += t.get("size") or 0
        g["uploaded"] += t.get("uploaded") or 0
        g["downloaded"] += t.get("downloaded") or 0
        row = {"hash": t.get("hash"), "name": t.get("name"), "category": t.get("category"), "state": t.get("state"),
               "ratio": round(t.get("ratio") or 0, 2), "seed_h": round((t.get("seeding_time") or 0) / 3600, 1),
               "progress": round((t.get("progress") or 0) * 100), "added": t.get("added_on")}
        ok = met(t, rule)
        if not ok:
            g["pending"].append(row)
            if t.get("state") in STALLED:
                g["stalled"].append(row)
        if "issue" in (t.get("tags") or "").split(", ") or t.get("state") == "error":
            g["issues"].append(row)
    out = []
    for name in [n for n, _ in TRACKERS] + ["Andet"]:
        g = by.get(name)
        if not g:
            continue
        g["ratio"] = round(g["uploaded"] / g["downloaded"], 2) if g["downloaded"] else None
        g["pending"].sort(key=lambda r: r["seed_h"])
        out.append(g)
    return out


def _snapshot(groups):
    day = D["now"]().date().isoformat()
    con = D["db"]()
    with con:
        for g in groups:
            con.execute("INSERT OR REPLACE INTO tr_snap (day, tracker, uploaded, downloaded) VALUES (?,?,?,?)",
                        (day, g["name"], g["uploaded"], g["downloaded"]))
        con.execute("DELETE FROM tr_snap WHERE day < date(?, '-60 days')", (day,))
    con.close()


def upload_since(name, days):
    """Upload de sidste X døgn ud fra de daglige tal (summen kan falde, når torrents fjernes – så vises intet)."""
    con = D["db"]()
    rows = con.execute("SELECT day, uploaded FROM tr_snap WHERE tracker=? ORDER BY day", (name,)).fetchall()
    con.close()
    if len(rows) < 2:
        return None
    last = rows[-1]
    target = (D["now"]().date() - datetime.timedelta(days=days)).isoformat()
    first = next((r for r in rows if r["day"] >= target), rows[0])
    diff = last["uploaded"] - first["uploaded"]
    return diff if diff >= 0 and first["day"] != last["day"] else None


def _watch(ts, rl):
    """Hold øje med torrents, der ikke har opfyldt kravet. Forsvinder en, før kravet er opfyldt → risiko."""
    now = D["iso"](D["now"]())
    con = D["db"]()
    cur = {t["hash"]: t for t in ts}
    gone = []
    with con:
        for t in ts:
            name = tracker_of(t)
            rule = rl.get(name) or rl["Andet"]
            if not rule["alert"]:
                continue
            if met(t, rule):
                con.execute("DELETE FROM tr_watch WHERE hash=?", (t["hash"],))
            else:
                con.execute("INSERT INTO tr_watch (hash, tracker, name, added, seed_h, ratio, last_seen) VALUES (?,?,?,?,?,?,?)"
                            " ON CONFLICT(hash) DO UPDATE SET seed_h=excluded.seed_h, ratio=excluded.ratio, last_seen=excluded.last_seen, gone_at=NULL",
                            (t["hash"], name, t.get("name") or "", str(t.get("added_on") or ""), round((t.get("seeding_time") or 0) / 3600, 1),
                             round(t.get("ratio") or 0, 2), now))
        for r in con.execute("SELECT * FROM tr_watch WHERE gone_at IS NULL").fetchall():
            if r["hash"] not in cur:
                con.execute("UPDATE tr_watch SET gone_at=? WHERE hash=?", (now, r["hash"]))
                gone.append(dict(r))
        con.execute("DELETE FROM tr_watch WHERE gone_at IS NOT NULL AND gone_at < datetime(?, '-30 days')", (now,))
    con.close()
    return gone


def notify(groups, gone):
    st = D["kv_get"](STATE_KEY, {}) or {}
    prev = set(st.get("stalled") or [])
    stalled = {r["hash"]: (g["name"], r) for g in groups if g["rule"]["alert"] for r in g["stalled"]}
    new = [stalled[h] for h in stalled if h not in prev]
    lines = []
    for name, r in new[:10]:
        lines.append(f"• {name}: {r['name'][:70]} – {r['state']}, seedet {r['seed_h']:g} t, ratio {r['ratio']:g}")
    for r in gone[:10]:
        lines.append(f"• {r['tracker']}: {r['name'][:70]} – fjernet efter {r['seed_h']:g} t, ratio {r['ratio']:g}")
    if lines:
        D["telegram"]("⚠️ Fangarr – risiko for hit-and-run\n\n" + "\n".join(lines) +
                      "\n\nStoppede torrents: start dem igen i qBittorrent. Se Fangarr › Drift › Trackere.")
    elif prev and not stalled:
        D["telegram"]("✅ Fangarr – trackerne: ingen torrents står stille før seedingkravet længere.")
    st["stalled"] = sorted(stalled)
    D["kv_set"](STATE_KEY, st)


def refresh():
    rl = rules()
    ts = torrents()
    groups = summarize(ts, rl)
    _snapshot(groups)
    gone = _watch(ts, rl)
    with _lock:
        _s.update(data={"at": D["iso"](D["now"]()), "groups": groups, "total": len(ts)}, err="", last=time.time())
    return groups, gone


def tick():
    if not enabled() or time.time() - _s["last"] < EVERY:
        return
    _s["last"] = time.time()
    try:
        groups, gone = refresh()
        notify(groups, gone)
        if (D["kv_get"](STATE_KEY, {}) or {}).get("down"):
            st = D["kv_get"](STATE_KEY, {}) or {}
            st["down"] = False
            D["kv_set"](STATE_KEY, st)
            D["telegram"]("✅ Fangarr – qBittorrent svarer igen.")
    except Exception as e:  # noqa: BLE001
        _s["err"] = str(e)[:200]
        D["log"].warning("Trackere: %s", e)
        st = D["kv_get"](STATE_KEY, {}) or {}
        st["fails"] = int(st.get("fails") or 0) + 1
        if st["fails"] >= 4 and not st.get("down"):   # ca. en time uden svar
            st["down"] = True
            D["telegram"](f"🚨 Fangarr – kan ikke læse qBittorrent (trackerne): {_s['err']}")
        D["kv_set"](STATE_KEY, st)
        return
    st = D["kv_get"](STATE_KEY, {}) or {}
    if st.get("fails"):
        st["fails"] = 0
        D["kv_set"](STATE_KEY, st)


# ---------------------------------------------------------------- adresser

@router.get("/trackere")
def api_state(refresh_now: int = 0):
    if not enabled():
        return {"enabled": False, "rules": rules()}
    if refresh_now or not _s["data"]:
        try:
            refresh()
        except Exception as e:  # noqa: BLE001
            _s["err"] = str(e)[:200]
    d = dict(_s["data"] or {"groups": []})
    for g in d.get("groups", []):
        g["up_1"], g["up_7"] = upload_since(g["name"], 1), upload_since(g["name"], 7)
        g["pending_n"], g["pending"] = len(g["pending"]), g["pending"][:50]
    con = D["db"]()
    gone = [dict(r) for r in con.execute("SELECT tracker, name, seed_h, ratio, gone_at FROM tr_watch WHERE gone_at IS NOT NULL"
                                         " ORDER BY gone_at DESC LIMIT 20").fetchall()]
    con.close()
    return {"enabled": True, "error": _s["err"], "rules": rules(), "gone": gone, **d}


@router.put("/trackere/regler")
async def save_rules(req: Request):
    b = await req.json()
    out = {}
    for name in DEFAULT_RULES:
        v = b.get(name) or {}
        try:
            h, r = float(v.get("hours", DEFAULT_RULES[name]["hours"])), float(v.get("ratio", DEFAULT_RULES[name]["ratio"]))
        except (TypeError, ValueError):
            raise HTTPException(400, f"{name}: timer og ratio skal være tal")
        if h < 0 or r < 0 or h > 10000 or r > 100:
            raise HTTPException(400, f"{name}: urimelige tal")
        out[name] = {"hours": h, "ratio": r, "alert": bool(v.get("alert", DEFAULT_RULES[name]["alert"]))}
    D["kv_set"](RULES_KEY, out)
    return {"ok": True, "rules": rules()}
