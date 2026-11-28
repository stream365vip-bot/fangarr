"""2.3.0: sikkerhedstjek, trackerne og tjeklisten for biblioteket.

qBittorrent, sonarr2, Radarr og adresserne er efterlignet (tests/efterligning.py). Porttjekket kører kun mod
127.0.0.1 og nogle få porte. Intet sendes til den rigtige bot.
"""

import socket

import httpx

import conftest
import efterligning
from app import main, sikkerhed, tjekliste, trackere

BASE = f"http://127.0.0.1:{conftest.PORT}"


def _sent():
    return [m.get("text", "") for m in efterligning.TG["sent"]]


# ---------------------------------------------------------------- sikkerhed

def test_check_url_classifies():
    with httpx.Client(timeout=5, follow_redirects=False) as c:
        assert sikkerhed.check_url(c, BASE + "/sik/login", "side")[0] == "ok"
        st, txt = sikkerhed.check_url(c, BASE + "/sik/aaben", "side")
        assert st == "fund" and "200" in txt
        assert sikkerhed.check_url(c, BASE + "/findes-ikke", "api")[0] == "ok", "404 på /api = findes ikke = i orden"
        assert sikkerhed.check_url(c, BASE + "/findes-ikke", "widget")[0] == "ok"
        assert sikkerhed.check_url(c, BASE + "/sik/aaben", "widget")[0] == "fund"
        assert sikkerhed.check_url(c, "http://127.0.0.1:1/", "side")[0] == "ingen-svar"


def test_parse_hosts_and_ports():
    assert sikkerhed.parse_ports("22, 80,443 1000-1002") == {22, 80, 443, 1000, 1001, 1002}
    h = sikkerhed.parse_hosts("feeder 65.21.142.239 22,80  # kommentar\n\nmediabox 37.27.105.61 22")
    assert h[0]["expected"] == [22, 80] and h[1]["name"] == "mediabox"
    for bad in ("x", "0", "70000", "a-b"):
        try:
            sikkerhed.parse_ports(bad) if bad != "x" else sikkerhed.parse_hosts("kunnavn")
            assert False, bad
        except ValueError:
            pass


def test_settings_validation(client):
    assert client.put("/api/sikkerhed/indst", json={"hosts": "forkert"}).status_code == 400
    assert client.put("/api/sikkerhed/indst", json={"ports": "99999"}).status_code == 400
    d = client.get("/api/sikkerhed").json()
    assert "65.21.142.239" in d["config"]["hosts"], "standard: feeder og Mediabox"


def test_port_scan_and_notify(client):
    # en ekstra port åbnes kun til testen – den står ikke på listen og skal give ét fund
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    extra = srv.getsockname()[1]
    lo, hi = min(conftest.PORT, extra), max(conftest.PORT, extra)
    r = client.put("/api/sikkerhed/indst", json={"hosts": f"test 127.0.0.1 {conftest.PORT}", "ports": f"{lo}-{hi}" if hi - lo < 3000 else f"{conftest.PORT},{extra}",
                                                 "public": "plex", "open_api": "tracearr"})
    assert r.status_code == 200
    before = len(efterligning.TG["sent"])
    assert sikkerhed.run(manual=True)
    d = client.get("/api/sikkerhed").json()
    h = d["result"]["hosts"][0]
    assert conftest.PORT in h["open"] and extra in h["unexpected"]
    assert d["alarm"] >= 1
    assert any("sikkerhedstjek" in t and str(extra) in t for t in _sent()[before:])
    # samme fund igen → ingen ny besked
    n = len(efterligning.TG["sent"])
    sikkerhed.run(manual=True)
    assert not any("sikkerhedstjek" in t for t in _sent()[n:])
    # porten lukkes → "i orden igen" (kun hvis adresserne heller ikke giver fund)
    srv.close()
    n = len(efterligning.TG["sent"])
    sikkerhed.run(manual=True)
    res = client.get("/api/sikkerhed").json()["result"]
    if not sikkerhed.findings(res):
        assert any("i orden igen" in t for t in _sent()[n:])
    assert client.get("/api/overview").json()["drift"]["sikkerhed"] == len(sikkerhed.findings(res))


def test_urls_use_apps_list(client):
    targets = sikkerhed.url_targets(sikkerhed.get_cfg())
    assert all(u.startswith("https://") for _, _, u in targets)
    assert targets, "Apps-listen fra den efterlignede Uptime Kuma giver adresser"


# ---------------------------------------------------------------- trackere

def test_tracker_mapping_and_rules():
    assert trackere.tracker_of({"tracker": "https://tracker.superbits.org/x"}) == "SuperBits"
    assert trackere.tracker_of({"tracker": "", "tags": "nordicbytes, issue"}) == "NordicBytes"
    assert trackere.tracker_of({"tracker": "https://tracker.tleechreload.org/a"}) == "TorrentLeech"
    assert trackere.tracker_of({"tracker": "https://andet.dk"}) == "Andet"
    sb = trackere.DEFAULT_RULES["SuperBits"]
    assert trackere.met({"seeding_time": 49 * 3600, "progress": 1, "ratio": 0}, sb)
    assert trackere.met({"seeding_time": 0, "progress": 0.5, "ratio": 1.2}, sb)
    assert not trackere.met({"seeding_time": 49 * 3600, "progress": 0.9, "ratio": 0.2}, sb), "seedtid tæller kun for færdige"


def test_trackers_page_and_alerts(client):
    d = client.get("/api/trackere?refresh_now=1").json()
    assert d["enabled"] and not d["error"], d
    g = {x["name"]: x for x in d["groups"]}
    assert g["SuperBits"]["count"] == 1 and g["SuperBits"]["pending_n"] == 1 and not g["SuperBits"]["stalled"]
    assert len(g["NordicBytes"]["stalled"]) == 1 and len(g["NordicBytes"]["issues"]) == 1
    assert g["NordicBytes"]["pending_n"] == 1, "a3 har opfyldt kravet"
    assert g["TorrentLeech"]["rule"]["alert"] is False
    # første kørsel: den stoppede torrent giver én besked
    before = len(efterligning.TG["sent"])
    trackere._s["last"] = 0
    trackere.tick()
    assert any("hit-and-run" in t and "Fjordmord" in t for t in _sent()[before:])
    assert client.get("/api/overview").json()["drift"]["trackere"] == 1
    # samme igen → ingen ny besked
    n = len(efterligning.TG["sent"])
    trackere._s["last"] = 0
    trackere.tick()
    assert not any("hit-and-run" in t for t in _sent()[n:])
    # SuperBits-torrenten forsvinder før kravet, og den stoppede starter igen → besked om den fjernede
    saved = [dict(t) for t in efterligning.QB["torrents"]]
    efterligning.QB["torrents"] = [t for t in saved if t["hash"] != "a1"]
    for t in efterligning.QB["torrents"]:
        if t["hash"] == "a2":
            t["state"] = "uploading"
    n = len(efterligning.TG["sent"])
    trackere._s["last"] = 0
    trackere.tick()
    msgs = _sent()[n:]
    assert any("fjernet efter" in t and "Testby" in t for t in msgs)
    assert client.get("/api/trackere").json()["gone"], "den fjernede står på listen i 30 dage"
    efterligning.QB["torrents"] = saved
    trackere._s["last"] = 0
    trackere.tick()


def test_tracker_rules_save(client):
    r = client.put("/api/trackere/regler", json={"TorrentLeech": {"hours": 288, "ratio": 1, "alert": True}})
    assert r.status_code == 200 and r.json()["rules"]["TorrentLeech"]["hours"] == 288
    assert client.put("/api/trackere/regler", json={"SuperBits": {"hours": "x"}}).status_code == 400
    client.put("/api/trackere/regler", json={})


def test_qbit_old_and_new_login(client):
    for new in (True, False):
        efterligning.QB["new_style"] = new
        trackere._s["cookie"] = None
        assert len(trackere.torrents()) == 4
        assert len(trackere.torrents()) == 4, "cookien genbruges"
    efterligning.QB["new_style"] = True


def test_qbit_wrong_login(client, monkeypatch):
    monkeypatch.setattr(trackere, "QBIT_PASS", "forkert")
    trackere._s["cookie"] = None
    try:
        trackere.torrents()
        assert False
    except RuntimeError as e:
        assert "afviste login" in str(e)


# ---------------------------------------------------------------- tjekliste

def test_checklist(client):
    assert tjekliste.run(manual=True)
    d = client.get("/api/tjekliste").json()
    sec = {s["key"]: s for s in d["sections"]}
    assert sec["dubletter"]["count"] == 1, "Den Opdigtede Film to gange i den efterlignede Radarr"
    assert sec["dubletter"]["items"][0]["instance"] == "radarr"
    assert any("Fjordmord" in i["title"] for i in sec["mangler"]["items"]), "2 af 4 afsnit"
    assert set(sec) == {"dubletter", "mangler", "uden_dansk", "plakat", "profil", "genre"}
    assert client.post("/api/tjekliste/tjek").status_code == 200


# ---------------------------------------------------------------- backuptjek (script på feeder)

def test_backuptjek_with_fake_rclone(tmp_path, monkeypatch):
    import datetime as dt
    import importlib.util
    import json as js
    import os
    import tarfile
    spec = importlib.util.spec_from_file_location("backuptjek", os.path.join(conftest.ROOT, "scripts", "backuptjek", "backuptjek.py"))
    bt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bt)
    src = tmp_path / "lille.tar"
    (tmp_path / "x.txt").write_text("hej")
    with tarfile.open(src, "w") as t:
        t.add(tmp_path / "x.txt", arcname="x.txt")
    src.write_bytes(src.read_bytes() + b"\0" * 2048)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    files = [{"Path": "opt/lille.tar", "Name": "lille.tar", "Size": 40 * 10**9, "ModTime": now},
             {"Path": "opt/tom.tar", "Name": "tom.tar", "Size": 10240, "ModTime": now},
             {"Path": "archived/gammel.tar", "Name": "gammel.tar", "Size": 5, "ModTime": "2020-01-01T00:00:00Z"}]

    def fake(*args, timeout=0):
        if args[0] == "lsjson":
            return js.dumps(files)
        if args[0] == "copyto":
            import shutil
            shutil.copy(src, args[2])
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(bt, "rclone", fake)
    line, problem = bt.tjek("Mediabox", "gcrypt:Mediabox", 30)
    assert problem is None and "prøvegendannelse af opt/lille.tar" in line, "den næsten tomme fil springes over"
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=26)).isoformat()
    files[0]["ModTime"] = files[1]["ModTime"] = old
    assert "timer gammel" in bt.tjek("Mediabox", "gcrypt:Mediabox", 30)[1], "én mislykket nat skal opdages"
