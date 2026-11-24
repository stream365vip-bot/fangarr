"""Alle API-adresser svarer, og de vigtigste ændringer kan gemmes og læses igen.

Formålet er at se, at intet gammelt er gået i stykker, når Fangarr ændres.
"""

import pytest

# Adresser, der kun læser. Alle skal svare 200 – også når en app ikke er sat op.
GET = [
    "/", "/health", "/api/state", "/api/log", "/api/log/summary", "/api/waitlist", "/api/aliases", "/api/ignored",
    "/api/autobrr", "/api/export", "/api/backups", "/api/stats", "/api/translations", "/api/translations/stats",
    "/api/sharing", "/api/version", "/api/connections", "/api/added", "/api/overview", "/api/search?q=borgen",
    "/api/premieres", "/api/hentegraense", "/api/apps", "/api/apps/config", "/api/guide",
    "/api/kunder/state", "/api/kunder/customers", "/api/kunder/charges", "/api/kunder/iptv", "/api/kunder/logins",
    "/api/kunder/economy", "/api/kunder/export.csv",
    "/api/oensker/state", "/api/nyheder", "/api/nyheder/gallery",
    "/api/instance/sonarr2/options", "/api/instance/radarr/options",
]
# Kræver en app, der ikke er efterlignet (fx Seerr): et pænt 400-svar er i orden – men aldrig 500.
NEEDS_APP = {"/api/premieres": "Seerr"}


@pytest.mark.parametrize("path", GET)
def test_get(client, path):
    r = client.get(path)
    ok = (200, 400) if path in NEEDS_APP else (200,)
    assert r.status_code in ok, (path, r.status_code, r.text[:300])


def test_static_files(client):
    html = client.get("/").text
    import re
    files = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)
    assert files, "index.html henter ingen filer fra /static"
    for f in files:
        assert client.get(f).status_code == 200, f


def test_import_removed(client):
    """Import fra regneark er fjernet i 2.0."""
    assert client.post("/api/kunder/import/preview", json={}).status_code in (404, 405)
    assert "doubts" not in client.get("/api/kunder/state").json()


def test_settings_roundtrip(client):
    s = client.get("/api/state").json()["settings"]
    body = dict(s, max_series_per_day=7, wait_hours=3, summary_hour=8)
    r = client.put("/api/settings", json=body)
    assert r.status_code == 200, r.text
    s2 = client.get("/api/state").json()["settings"]
    assert s2["max_series_per_day"] == 7 and s2["wait_hours"] == 3 and s2["summary_hour"] == 8


def test_rules(client):
    rule = {"name": "Danske serier", "media": "series", "instance": "sonarr2", "active": True,
            "release_contains": ["NORDiC"], "languages": ["Danish"], "root_folder": "/data/TV/TV",
            "quality_profile_id": 1, "monitor": "latestSeason", "tag": "auto-fangarr", "search": True}
    r = client.post("/api/rules", json=rule)
    assert r.status_code == 200, r.text
    rules = r.json()
    rid = rules[-1]["id"]
    r = client.put(f"/api/rules/{rid}", json=dict(rules[-1], active=False))
    assert r.status_code == 200 and r.json()[-1]["active"] is False
    assert client.post("/api/rules/order", json={"ids": [x["id"] for x in r.json()]}).status_code == 200
    assert client.delete(f"/api/rules/{rid}").status_code == 200


def test_test_title(client):
    r = client.post("/api/test", json={"media": "series", "title": "Borgen", "year": "", "release": "Borgen.S01E01.NORDiC.1080p.WEB-GRP"})
    assert r.status_code == 200, r.text
    assert "decision" in r.json()


def test_customers_flow(client):
    r = client.post("/api/kunder/customers", json={"name": "Testkunde Et", "status": "aktiv", "kind": "kunde", "method": "mobilepay",
                                                   "freq": "maaned", "cycle": "", "due_day": "", "phone": "", "email": ""})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    r = client.post("/api/kunder/services", json={"customer_id": cid, "service": "plex", "label": "", "price": 75})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/kunder/customers/{cid}").status_code == 200
    st = client.get("/api/kunder/state").json()
    r = client.put("/api/kunder/settings", json=dict(st["settings"]))
    assert r.status_code == 200, r.text
    # 2.1: faste udgifter ligger under Opkrævning › Udgifter
    r = client.post("/api/udgifter", json={"name": "Hetzner", "amount": 1200, "per": "aar", "renews": "2027-01-10", "notice": 14})
    assert r.status_code == 200, r.text
    fixed = client.get("/api/kunder/economy").json()["fixed"]
    assert any(f["name"] == "Hetzner" and f["amount"] == 100 for f in fixed)
    r = client.post("/api/kunder/charges/generate", json={"period": st.get("period") or ""})
    assert r.status_code in (200, 400), r.text
    r = client.put("/api/kunder/news", json={"text": "Nyhed til test"})
    assert r.status_code == 200, r.text
    assert client.delete("/api/kunder/news").status_code == 200
    assert client.delete(f"/api/kunder/customers/{cid}").status_code == 200


def test_iptv_and_logins(client):
    r = client.post("/api/kunder/iptv", json={"label": "Linje test", "expires": "2027-01-01", "cost": 50, "renew": 1})
    assert r.status_code == 200, r.text
    lines = r.json()["lines"]
    assert lines
    assert client.delete(f"/api/kunder/iptv/{lines[-1]['id']}").status_code == 200
    r = client.post("/api/kunder/logins", json={"name": "Spotify", "username": "test", "password": "x"})
    assert r.status_code == 200, r.text


def test_apps_config(client):
    r = client.put("/api/apps/config", json={"links": "", "extra": "Daglig | Uptime | https://uptime.eksempel.dk"})
    assert r.status_code == 200, r.text
    apps = client.get("/api/apps?refresh=1").json()
    assert apps["enabled"] and apps["total"] >= 1


def test_backup_now(client):
    assert client.post("/api/backups/now").status_code == 200
    assert client.get("/api/backups").json()
