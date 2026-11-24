"""Start Fangarr lokalt med efterlignede apps og OPDIGTEDE testdata – til at se siderne og tage skærmbilleder.

    python tests/demo.py            (Fangarr på http://127.0.0.1:18080, stop med Ctrl+C)

Bruger en midlertidig database. Ingen rigtige kunder, intet til Telegram, ingen rigtige apps.
"""

import datetime
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import efterligning  # noqa: E402

MOCK, PORT = 18990, int(os.environ.get("DEMO_PORT", "18080"))
DATA = tempfile.mkdtemp(prefix="fangarr-demo-")
for k in list(os.environ):
    if k.endswith(("_URL", "_APIKEY", "_TOKEN")) or k in ("ARR_INSTANCES", "TELEGRAM_CHAT_ID"):
        os.environ.pop(k)
os.environ.update(efterligning.env(MOCK))
os.environ.update({"DATA_DIR": DATA, "DISK_PATH": DATA, "TZ": "Europe/Copenhagen"})

import httpx  # noqa: E402
import uvicorn  # noqa: E402

threading.Thread(target=lambda: uvicorn.run(efterligning.app, host="127.0.0.1", port=MOCK, log_level="warning"), daemon=True).start()

from app import main  # noqa: E402

main.background_loop = lambda: None
main._latest_version = lambda: ""

NAVNE = ["Anna Testesen", "Bo Prøvesen", "Carla Eksempel", "Dan Demo", "Eva Fiktiv", "Finn Opdigt", "Gitte Prøve", "Hans Testmand"]


def seed():
    b = f"http://127.0.0.1:{PORT}"
    c = httpx.Client(base_url=b, timeout=30)
    for _ in range(100):
        try:
            c.get("/health"); break
        except httpx.HTTPError:
            time.sleep(0.1)
    rules = [
        {"name": "Danske serier", "media": "series", "instance": "sonarr2", "release_contains": ["NORDiC", "DANiSH"], "languages": ["Danish"],
         "root_folder": "/data/TV/TV", "quality_profile_id": 1, "monitor": "latestSeason", "wait": True, "allow_missing_genre": True, "active": True, "search": True},
        {"name": "Nordiske krimiserier", "media": "series", "instance": "sonarr2", "release_contains": ["NORDiC"], "languages": ["Swedish", "Norwegian"],
         "genres_any": ["Crime", "Thriller"], "min_rating": 6.5, "root_folder": "/data/TV/Serier", "quality_profile_id": 1, "monitor": "firstSeason", "active": True, "search": True},
        {"name": "Nye film", "media": "movie", "instance": "radarr", "release_contains": ["NORDiC"], "genres_none": ["Horror"], "year_min": 2024,
         "root_folder": "/data/Film/Film", "quality_profile_id": 1, "active": True, "search": True},
        {"name": "4K-udgaver", "media": "movie", "instance": "radarr4k", "release_contains": ["NORDiC"], "resolution": "2160p", "extra": True, "released_months": 12,
         "root_folder": "/data/Film/Film", "quality_profile_id": 4, "active": True, "search": True},
    ]
    for r in rules:
        c.post("/api/rules", json={**r, "tag": "auto-fangarr"})
    s = c.get("/api/state").json()["settings"]
    c.put("/api/settings", json={**s, "dry_run": False})

    now = datetime.datetime.now()
    t = lambda h: (now - datetime.timedelta(hours=h)).isoformat(timespec="seconds")
    con = sqlite3.connect(os.path.join(DATA, "fangarr.db"))
    log = [("series", "Testby.S01E01.NORDiC.1080p.WEB-GRP", "Testby", 2026, "tilføjet", "Danske serier", "tilføjet til sonarr2 › /data/TV/TV"),
           ("movie", "Den.Opdigtede.Film.2026.NORDiC.1080p.WEB-GRP", "Den Opdigtede Film", 2026, "tilføjet", "Nye film", "tilføjet til radarr › /data/Film/Film"),
           ("series", "Fjordmord.S01E01.NORDiC.1080p.WEB-GRP", "Fjordmord", 2026, "tilføjet", "Nordiske krimiserier", "tilføjet til sonarr2 › /data/TV/Serier"),
           ("series", "Bageduel.S02E01.DANiSH.720p.WEB-GRP", "Bageduel", 2025, "findes allerede", "", "findes allerede i sonarr2"),
           ("series", "Skovens.Folk.S01E01.NORDiC.1080p.WEB-GRP", "Skovens Folk", None, "venteliste", "Danske serier", "TheTVDB har ikke titlen endnu"),
           ("movie", "Gyserhuset.2026.NORDiC.1080p.WEB-GRP", "Gyserhuset", 2026, "afvist", "", "ingen regel passer: genre Gys er udelukket"),
           ("series", "Ukendt.Show.S01E01.NORDiC.1080p.WEB-GRP", "Ukendt Show", None, "fejl", "", "sonarr2 svarede ikke")]
    for i, (m, rel, title, y, d, rule, det) in enumerate(log):
        con.execute("INSERT INTO log (ts, media, release, title, year, decision, rule, detail, dry_run, info) VALUES (?,?,?,?,?,?,?,?,0,'')",
                    (t(i * 3 + 1), m, rel, title, y, d, rule, det))
    for i, (inst, m, title, rule) in enumerate([("sonarr2", "series", "Testby", "Danske serier"), ("radarr", "movie", "Den Opdigtede Film", "Nye film"),
                                                ("sonarr2", "series", "Fjordmord", "Nordiske krimiserier"), ("radarr4k", "movie", "Den Opdigtede Film", "4K-udgaver")]):
        con.execute("INSERT INTO added (ts, instance, media, arr_id, title, ext_id, rule) VALUES (?,?,?,?,?,?,?)", (t(i * 3 + 1), inst, m, 100 + i, title, "", rule))
    sugg = json.dumps([{"id": 4242, "title": "The Forest People", "year": 2026, "language": "Danish", "network": "DR1", "genres": ["Documentary"]}])
    con.execute("INSERT INTO waitlist (created, media, title, release, payload, attempts, next_try, status, reason, rule, suggestions) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (t(20), "series", "Skovens Folk", "Skovens.Folk.S01E01.NORDiC.1080p.WEB-GRP", "{}", 3, t(-2), "venter", "TheTVDB har ikke titlen endnu", "Danske serier", sugg))
    con.execute("INSERT INTO waitlist (created, media, title, release, payload, attempts, next_try, status, reason, rule, suggestions) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (t(30), "series", "Morgenmaden", "Morgenmaden.S01E03.DANiSH.720p.WEB-GRP", "{}", 5, t(-1), "venter", "mangler årstal hos TheTVDB", "Danske serier", "[]"))
    con.execute("INSERT INTO aliases (created, media, key, release_title, ext_id, title) VALUES (?,?,?,?,?,?)", (t(200), "series", "simonsiger", "Simon Siger", 1, "Simon Says (2026)"))
    con.execute("INSERT INTO ignored (created, media, key, title) VALUES (?,?,?,?)", (t(100), "series", "kokkeskolen", "Kokkeskolen"))
    con.commit()
    con.close()

    methods = ["MobilePay", "Revolut", "MobilePay", "Revolut", "MobilePay", "Andet", "MobilePay", "Revolut"]
    for i, n in enumerate(NAVNE):
        cu = c.post("/api/kunder/customers", json={"name": n, "method": methods[i], "freq": "maaned" if i % 3 else "kvartal"}).json()
        upd = {**cu, "cycle": "2" if i % 3 == 0 else "", "due_day": str(1 + i * 3), "status": "aktiv", "kind": "egen" if i == 7 else "kunde"}
        c.put(f"/api/kunder/customers/{cu['id']}", json=upd)
        c.post("/api/kunder/services", json={"customer_id": cu["id"], "service": "plex", "price": 75, "username": f"testbruger{i + 1}"})
        if i in (1, 4):
            c.post("/api/kunder/iptv", json={"customer_id": cu["id"], "label": f"Linje {i}", "expires": (now + datetime.timedelta(days=10 + i)).date().isoformat(), "cost": 45, "renew": 1})
    c.post("/api/kunder/customers", json={"name": "Ida Mangler", "method": "", "freq": ""})
    c.post("/api/kunder/logins", json={"service": "Spotify", "username": "familie@eksempel.dk", "password": "opdigtet"})
    c.post("/api/kunder/charges/generate", json={"period": now.strftime("%Y-%m")})
    ch = c.get("/api/kunder/charges").json()["charges"]
    for x in ch[:3]:
        c.post(f"/api/kunder/charges/{x['id']}", json={"action": "paid"})
    for x in ch[3:5]:
        c.post(f"/api/kunder/charges/{x['id']}", json={"action": "request"})
    st = c.get("/api/kunder/state").json()["settings"]
    c.put("/api/kunder/settings", json={**st, "fixed_costs": "Hetzner: 2813\nDomæne: 15"})
    c.put("/api/kunder/news", json={"text": "📣 Nyt: nu kan du selv ønske film og serier i Seerr."})
    c.put("/api/apps/config", json={"links": "", "extra": "Daglig | Uptime | https://uptime.eksempel.dk"})
    print("Testdata lagt ind.", flush=True)


if __name__ == "__main__":
    threading.Thread(target=seed, daemon=True).start()
    uvicorn.run(main.app, host="127.0.0.1", port=PORT, log_level="warning")
