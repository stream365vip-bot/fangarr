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
    return [{"id": 100, "title": "Testby", "titleSlug": "testby", "statistics": {"episodeFileCount": 6, "episodeCount": 6}},
            {"id": 102, "title": "Fjordmord", "titleSlug": "fjordmord", "statistics": {"episodeFileCount": 2, "episodeCount": 4}}]


@app.get("/{inst}/api/v3/movie")
def movies(inst: str):
    return [{"id": 101, "title": "Den Opdigtede Film", "tmdbId": 1, "hasFile": True},
            {"id": 103, "title": "Den Opdigtede Film", "tmdbId": 1, "hasFile": False, "isAvailable": True}]


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


def env(port):
    """Miljøvariabler, så Fangarr bruger de efterlignede apps."""
    base = f"http://127.0.0.1:{port}"
    return {"ARR_INSTANCES": "sonarr2,radarr,radarr4k",
            "SONARR2_URL": base + "/sonarr2", "SONARR2_APIKEY": "test",
            "RADARR_URL": base + "/radarr", "RADARR_APIKEY": "test",
            "RADARR4K_URL": base + "/radarr4k", "RADARR4K_APIKEY": "test",
            "UPTIME_URL": base + "/uptime", "APPS_DOMAIN": "eksempel.dk",
            "TELEGRAM_TOKEN": "test", "TELEGRAM_CHAT_ID": "731397952", "TELEGRAM_API": base + "/tg",
            "TAUTULLI_URL": base + "/tautulli", "TAUTULLI_APIKEY": "test"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1] if len(sys.argv) > 1 else 18990), log_level="warning")
