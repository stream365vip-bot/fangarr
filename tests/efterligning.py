"""Efterlignede apps til test og skærmbilleder: sonarr2, radarr, radarr4k, Uptime Kuma, Telegram og Tautulli.

Alt her er opdigtet testdata – aldrig rigtige kunder eller rigtige titler fra serveren.
Kør for sig selv (til skærmbilleder):  python tests/efterligning.py 18990
Adresserne: http://127.0.0.1:18990/<sonarr2|radarr|radarr4k>/api/v3/...  og  /uptime/api/status-page/...
"""

import sys

from fastapi import FastAPI, Request

app = FastAPI()

ROOTS = {"sonarr2": ["/data/TV/TV", "/data/TV/Serier"], "radarr": ["/data/Film/Film", "/data/Film/Animation"],
         "radarr4k": ["/data/Film/Film"]}
PROFILES = [{"id": 1, "name": "HD-1080p"}, {"id": 4, "name": "Ultra-HD"}]


@app.get("/{inst}/api/v3/system/status")
def status(inst: str):
    return {"version": "4.0.0", "appName": inst}


@app.get("/{inst}/api/v3/rootfolder")
def roots(inst: str):
    return [{"id": i + 1, "path": p, "freeSpace": 10**12} for i, p in enumerate(ROOTS.get(inst, ["/data"]))]


@app.get("/{inst}/api/v3/qualityprofile")
def profiles(inst: str):
    return PROFILES


@app.get("/{inst}/api/v3/queue")
def queue(inst: str):
    return {"records": [], "totalRecords": 0}


@app.get("/{inst}/api/v3/series")
def series(inst: str):
    return [{"id": 100, "title": "Testby", "titleSlug": "testby", "statistics": {"episodeFileCount": 6, "episodeCount": 6},
             "monitored": True, "qualityProfileId": 1, "path": "/data/TV/TV/Testby", "genres": []},
            {"id": 102, "title": "Fjordmord", "titleSlug": "fjordmord", "statistics": {"episodeFileCount": 2, "episodeCount": 4},
             "monitored": True, "qualityProfileId": 1, "path": "/data/TV/Serier/Fjordmord", "genres": ["Crime"]}]


@app.get("/{inst}/api/v3/movie")
def movies(inst: str):
    return [{"id": 101, "title": "Den Opdigtede Film", "tmdbId": 1, "hasFile": True, "qualityProfileId": 1, "year": 2026},
            {"id": 103, "title": "Den Opdigtede Film", "tmdbId": 1, "hasFile": False, "isAvailable": True, "qualityProfileId": 9, "year": 2026}]


@app.api_route("/{inst}/api/v3/{rest:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def other(inst: str, rest: str, req: Request):
    if req.method == "POST":
        return {"id": 1}
    return []


@app.get("/uptime/api/status-page/apps")
def page():
    def grp(gid, name, apps):
        return {"id": gid, "name": name, "monitorList": [{"id": gid * 10 + i, "name": a} for i, a in enumerate(apps)]}
    return {"publicGroupList": [grp(1, "Kunder", ["Plex", "Seerr", "Guide"]),
                                grp(2, "Daglig", ["Fangarr", "sonarr2", "radarr", "Tautulli", "Tracearr"]),
                                grp(3, "Drift", ["qBittorrent", "autobrr", "Bazarr", "Oversætter"])]}


@app.get("/uptime/api/status-page/heartbeat/apps")
def beats():
    hb, up = {}, {}
    for gid in (1, 2, 3):
        for i in range(6):
            mid = str(gid * 10 + i)
            hb[mid] = [{"status": 0 if mid == "32" else 1}]
            up[f"{mid}_24"] = 0.991 if mid == "32" else 1.0
    return {"heartbeatList": hb, "uptimeList": up}


@app.get("/uptime/api/status-page/kunder")
def page_kunder():
    return {"publicGroupList": [{"id": 9, "name": "Kunder", "monitorList": [{"id": 91, "name": "Plex"}, {"id": 92, "name": "Seerr"},
                                                                             {"id": 93, "name": "IPTV 1"}]}]}


@app.get("/uptime/api/status-page/heartbeat/kunder")
def beats_kunder():
    return {"heartbeatList": {"91": [{"status": 1}], "92": [{"status": 1}], "93": [{"status": 1 if TRACEARR["iptv_up"] else 0}]},
            "uptimeList": {}}


# ---------------------------------------------------------------- Tracearr (2.4) – kun læsning, opdigtede brugere
# Tracearr-bruger "tu1" = Plex-bruger 9001 (Kunde Testesen), "tu2" = Plex-bruger 9002 (ingen kunde), "tu3" = ukendt i Plex.
TRACEARR = {"iptv_up": True, "violations": [], "history": {}, "streams": []}
TR_USERS = [{"id": "tu1", "username": "testesen", "identity_name": "Kunde Testesen", "email": "x@eksempel.dk", "plex_account_id": None,
             "accounts": [{"external_user_id": "9001", "server_id": "s1", "server_type": "plex", "server_user_id": "su1", "username": "testesen", "removed_at": None}]},
            {"id": "tu2", "username": "naboen", "identity_name": "", "email": "", "plex_account_id": None,
             "accounts": [{"external_user_id": "9002", "server_id": "s1", "server_type": "plex", "server_user_id": "su2", "username": "naboen", "removed_at": None}]},
            {"id": "tu3", "username": "fremmed", "identity_name": "", "email": "", "plex_account_id": None, "accounts": []}]


def _page(items, cursor, size):
    i = int(cursor or 0)
    nxt = i + size
    return {"data": items[i:nxt], "meta": {"nextCursor": str(nxt) if nxt < len(items) else None, "pageSize": size}}


@app.get("/tracearr/api/v2/public/users")
def tr_users(cursor: str = None, pageSize: int = 100, include_removed: str = ""):
    return _page(TR_USERS, cursor, pageSize)


@app.get("/tracearr/api/v2/public/violations")
def tr_violations(cursor: str = None, pageSize: int = 100, since: str = ""):
    items = [v for v in TRACEARR["violations"] if not since or v["created_at"] >= since]
    return _page(items, cursor, pageSize)


@app.get("/tracearr/api/v2/public/users/{uid}/history")
def tr_user_history(uid: str, cursor: str = None, pageSize: int = 100):
    return _page(TRACEARR["history"].get(uid, []), cursor, pageSize)


@app.get("/tracearr/api/v2/public/streams")
def tr_streams():
    return {"data": TRACEARR["streams"], "summary": {"total": len(TRACEARR["streams"])}}


@app.get("/tracearr/api/v2/public/media/{ref}/stats")
def tr_media_stats(ref: str):
    return {"error": "not found"}


def tr_violation(vid, user, rule, created, title="Fjordmord", acked=None):
    """Opdigtet overtrædelse i Tracearrs form."""
    u = {"tu1": "testesen", "tu2": "naboen", "tu3": "fremmed"}[user]
    return {"id": vid, "created_at": created, "acknowledged_at": acked, "severity": "high", "session_id": "s-" + vid,
            "rule": {"id": "r-" + rule, "name": rule}, "server": {"id": "s1"},
            "user": {"id": user, "username": u, "server_user_id": "su", "avatar_url": None, "thumb_url": None},
            "data": {"ruleName": rule, "mediaTitle": title, "ipAddress": "192.0.2.10", "evidence": [{"field": "Device Type", "value": "TV"}]}}


# ---------------------------------------------------------------- Telegram og Tautulli (2.1)
TG = {"sent": [], "edits": [], "answers": [], "updates": []}
TAUTULLI = {"streams": 3}


@app.post("/tg/bot{tok}/{method}")
async def telegram(tok: str, method: str, req: Request):
    try:
        b = await req.json()
    except ValueError:
        b = {}
    if method == "sendMessage":
        TG["sent"].append(b)
        return {"ok": True, "result": {"message_id": len(TG["sent"]), "chat": {"id": int(b.get("chat_id") or 0)},
                                       "text": b.get("text"), "reply_markup": b.get("reply_markup")}}
    if method == "editMessageText":
        TG["edits"].append(b)
        return {"ok": True, "result": True}
    if method == "answerCallbackQuery":
        TG["answers"].append(b)
        return {"ok": True, "result": True}
    if method == "getUpdates":
        ups, TG["updates"] = TG["updates"], []
        return {"ok": True, "result": ups}
    return {"ok": False, "description": "ukendt"}


@app.get("/tautulli/api/v2")
def tautulli(cmd: str = ""):
    if cmd == "get_activity":
        return {"response": {"result": "success", "data": {"stream_count": str(TAUTULLI["streams"]), "sessions": []}}}
    if cmd == "get_history":
        return {"response": {"result": "success", "data": {"data": [], "recordsFiltered": 0}}}
    if cmd == "get_users":
        return {"response": {"result": "success", "data": []}}
    return {"response": {"result": "success", "data": {}}}


# ---------------------------------------------------------------- Seerr (2.2) – kun de adresser, Beskeder bruger
SEERR = {"requests": []}
SEERR_TITLES = {("movie", 501): ("Den Opdigtede Film", "2026-01-01"), ("tv", 601): ("Fjordmord", "2025-03-01"),
                ("movie", 502): ("Juleræset", "2025-11-01")}


@app.get("/seerr/api/v1/request")
def seerr_requests(take: int = 20, skip: int = 0, filter: str = "all", sort: str = "added"):
    rs = SEERR["requests"]
    if filter == "available":
        rs = [r for r in rs if (r.get("media") or {}).get("status") in (4, 5)]
    return {"pageInfo": {"results": len(rs)}, "results": rs[skip:skip + take]}


@app.get("/seerr/api/v1/{kind}/{tmdb}")
def seerr_media(kind: str, tmdb: int):
    t, d = SEERR_TITLES.get((kind, tmdb), (f"Titel {tmdb}", "2024-01-01"))
    return {"title": t, "name": t, "releaseDate": d, "firstAirDate": d}


# ---------------------------------------------------------------- qBittorrent (2.3.0) – opdigtede torrents
H = 3600
QB = {"new_style": True, "torrents": [
    {"hash": "a1", "name": "Testby.S01E01.DANiSH.1080p.WEB", "tracker": "https://tracker.superbits.org/announce", "tags": "superbits",
     "category": "sonarr-done", "state": "stalledUP", "ratio": 0.3, "seeding_time": 10 * H, "progress": 1, "size": 2 * 10**9,
     "uploaded": 6 * 10**8, "downloaded": 2 * 10**9, "added_on": 1},
    {"hash": "a2", "name": "Fjordmord.S02E03.NORDiC.1080p.WEB", "tracker": "", "tags": "nordicbytes, issue",
     "category": "sonarr-done", "state": "stoppedUP", "ratio": 0.1, "seeding_time": 5 * H, "progress": 1, "size": 10**9,
     "uploaded": 10**8, "downloaded": 10**9, "added_on": 2},
    {"hash": "a3", "name": "Den.Opdigtede.Film.2026.NORDiC.1080p", "tracker": "https://t.nordicbytes.org/a", "tags": "nordicbytes",
     "category": "radarr-done", "state": "uploading", "ratio": 1.4, "seeding_time": 80 * H, "progress": 1, "size": 8 * 10**9,
     "uploaded": 11 * 10**9, "downloaded": 8 * 10**9, "added_on": 3},
    {"hash": "a4", "name": "Opdigtet.Boxset.2160p", "tracker": "https://tracker.torrentleech.org/a/x", "tags": "",
     "category": "ratio", "state": "uploading", "ratio": 0.6, "seeding_time": 20 * H, "progress": 1, "size": 40 * 10**9,
     "uploaded": 24 * 10**9, "downloaded": 0, "added_on": 4}]}


@app.post("/qbit/api/v2/auth/login")
async def qb_login(req: Request):
    from fastapi.responses import PlainTextResponse
    f = await req.form()
    if f.get("username") == "test" and f.get("password") == "test":
        if QB["new_style"]:   # qBittorrent 5.2+: 204 uden tekst, cookie QBT_SID_<port>
            from fastapi import Response
            r = Response(status_code=204)
            r.set_cookie("QBT_SID_8080", "abc")
            return r
        r = PlainTextResponse("Ok.")
        r.set_cookie("SID", "abc")
        return r
    return PlainTextResponse("Fails.")


@app.get("/qbit/api/v2/torrents/info")
def qb_info(req: Request):
    from fastapi.responses import PlainTextResponse
    if "abc" not in (req.cookies.get("SID"), req.cookies.get("QBT_SID_8080")):
        return PlainTextResponse("Forbidden", status_code=403)
    return QB["torrents"]


# ---------------------------------------------------------------- adresser til sikkerhedstjekket (2.3.0)
@app.get("/sik/login")
def sik_login():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("https://login.eksempel.dk/?rd=x", status_code=302)


@app.get("/sik/aaben")
def sik_open():
    return {"hej": 1}


def env(port):
    """Miljøvariabler, så Fangarr bruger de efterlignede apps."""
    base = f"http://127.0.0.1:{port}"
    return {"ARR_INSTANCES": "sonarr2,radarr,radarr4k",
            "SONARR2_URL": base + "/sonarr2", "SONARR2_APIKEY": "test",
            "RADARR_URL": base + "/radarr", "RADARR_APIKEY": "test",
            "RADARR4K_URL": base + "/radarr4k", "RADARR4K_APIKEY": "test",
            "UPTIME_URL": base + "/uptime", "APPS_DOMAIN": "eksempel.dk",
            "TELEGRAM_TOKEN": "test", "TELEGRAM_CHAT_ID": "731397952", "TELEGRAM_API": base + "/tg",
            "TAUTULLI_URL": base + "/tautulli", "TAUTULLI_APIKEY": "test",
            "QBIT_URL": base + "/qbit", "QBIT_USER": "test", "QBIT_PASS": "test",
            "TRACEARR_URL": base + "/tracearr", "TRACEARR_APIKEY": "test"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1] if len(sys.argv) > 1 else 18990), log_level="warning")
