"""Efterlignede apps til test og skærmbilleder: sonarr2, radarr, radarr4k og Uptime Kuma.

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


def env(port):
    """Miljøvariabler, så Fangarr bruger de efterlignede apps."""
    base = f"http://127.0.0.1:{port}"
    return {"ARR_INSTANCES": "sonarr2,radarr,radarr4k",
            "SONARR2_URL": base + "/sonarr2", "SONARR2_APIKEY": "test",
            "RADARR_URL": base + "/radarr", "RADARR_APIKEY": "test",
            "RADARR4K_URL": base + "/radarr4k", "RADARR4K_APIKEY": "test",
            "UPTIME_URL": base + "/uptime", "APPS_DOMAIN": "eksempel.dk"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1] if len(sys.argv) > 1 else 18990), log_level="warning")
