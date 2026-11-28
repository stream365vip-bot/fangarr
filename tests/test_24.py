"""2.4.0: blokeringer fra Tracearr, kontodeling af sig selv og Fejlsøg pr. kunde.

Tracearr, Uptime Kuma og Telegram er efterlignet (tests/efterligning.py). Alle navne er opdigtede.
"""

import datetime

import efterligning
from app import blokeringer, main


def _z(days_ago=0, hours_ago=0):
    t = datetime.datetime.utcnow() - datetime.timedelta(days=days_ago, hours=hours_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _sent():
    return [m.get("text", "") for m in efterligning.TG["sent"]]


def _customer(client):
    c = client.post("/api/kunder/customers", json={"name": "Kunde Testesen", "method": "MobilePay", "freq": "maaned"}).json()
    client.post("/api/kunder/services", json={"customer_id": c["id"], "service": "plex", "plex_user_id": 9001, "price": 49})
    return c["id"]


def _reset():
    main.kv_set(blokeringer.STATE_KEY, {})
    main.kv_set(blokeringer.RULES_KEY, {})
    con = main.db()
    with con:
        con.execute("DELETE FROM tc_viol")
    con.close()
    blokeringer._users.update(at=0.0, map={}, names={})


def test_users_map_to_plex(client):
    _reset()
    m, names = blokeringer.users(refresh=True)
    assert m == {"tu1": 9001, "tu2": 9002}, "kobles via accounts[].external_user_id; tu3 har ingen Plex-konto"
    assert names["tu1"] == "Kunde Testesen"
    assert blokeringer.tracearr_ids([9001]) == ["tu1"]


def test_first_sync_sends_nothing_then_new_ones_do(client):
    _reset()
    cid = _customer(client)
    efterligning.TRACEARR["violations"] = [
        efterligning.tr_violation("v1", "tu1", "Tv på flere adresser", _z(3)),
        efterligning.tr_violation("v2", "tu2", "Flere end 6 mobile enheder", _z(2)),
        efterligning.tr_violation("v3", "tu1", "Betaling", _z(5), acked=_z(4)),
    ]
    before = len(_sent())
    assert blokeringer.sync() == 3
    assert blokeringer.notify() == 0 and len(_sent()) == before, "alt fra før første synk er kendt – ingen bunke beskeder"
    d = client.get("/api/blokeringer").json()
    assert d["enabled"] and d["new"] == 0
    names = [g["name"] for g in d["groups"]]
    assert names == ["Kunde Testesen"], "mobilreglen er skjult som standard (Jesper 28. nov.)"
    g = d["groups"][0]
    assert g["customer_id"] == cid and g["count"] == 2 and g["open"] == 1, "den kvitterede tæller som afgjort"
    act = {i["rule"]: i["action"] for i in g["items"]}
    assert act == {"Tv på flere adresser": "stopper", "Betaling": "stopper"}

    # En ny overtrædelse efter første synk → under Kræver din handling og én besked (uden IP-adresse)
    efterligning.TRACEARR["violations"].append(efterligning.tr_violation("v4", "tu1", "Chromecast på flere adresser", _z(0, -1)))
    efterligning.TRACEARR["violations"].append(efterligning.tr_violation("v5", "tu3", "Blokeret: Jesper", _z(0, -1)))
    blokeringer.sync()
    assert [r["id"] for r in blokeringer.new_open()] == ["v4"], "testreglen giver aldrig besked"
    assert blokeringer.notify() == 1
    msg = _sent()[-1]
    assert "Kunde Testesen" in msg and "Chromecast" in msg and "kun besked" in msg and "192.0.2" not in msg
    assert blokeringer.notify() == 0, "samme overtrædelse giver kun én besked"
    assert client.get("/api/overview").json()["blokeringer"]["new"] == 1

    # Markér som set → afgjort
    assert client.put("/api/blokeringer/set", json={"key": "9001"}).status_code == 200
    assert client.get("/api/overview").json()["blokeringer"]["new"] == 0
    assert client.get("/api/blokeringer?open=1").json()["groups"] == []
    client.put("/api/blokeringer/set", json={"key": "9001", "undo": True})
    assert client.get("/api/blokeringer?open=1").json()["groups"][0]["open"] == 2


def test_rules_settings(client):
    _reset()
    assert client.put("/api/blokeringer/regler", json={"rules": [{"name": "X", "action": "slet alt", "show": True}]}).status_code == 400
    r = client.put("/api/blokeringer/regler", json={"rules": [{"name": "Flere end 6 mobile enheder", "action": "besked", "show": True},
                                                               {"name": "Ny regel", "action": "", "show": True}]}).json()
    assert r["rules"]["Flere end 6 mobile enheder"]["show"] is True
    assert r["rules"]["Ny regel"]["action"] == ""
    assert r["rules"]["Tv på flere adresser"]["action"] == "stopper", "standarden bevares for regler, der ikke er rettet"
    _reset()


def test_case_shared_with_analysis(client):
    _reset()
    efterligning.TRACEARR["violations"] = [efterligning.tr_violation("v9", "tu1", "Tv på flere adresser", _z(1))]
    blokeringer.sync()
    client.put("/api/sharing/user", json={"user_id": "9001", "status": "blokeret", "note": "regel lavet 28. nov."})
    g = client.get("/api/blokeringer").json()["groups"][0]
    assert g["case"]["status"] == "blokeret" and "28. nov." in g["case"]["note"]


def test_sharing_auto_compare_only_new(client):
    main.kv_set(main.SH_AUTO_KEY, {})
    main.kv_set(main.SH_AUTO_NEW, [])
    before = len(_sent())
    users = [{"user_id": "1", "name": "A", "bucket": "bloker", "evenings": 3}, {"user_id": "2", "name": "B", "bucket": "intet"}]
    assert [u["user_id"] for u in main.sharing_auto_compare(users)] == ["1"]
    assert len(_sent()) == before + 1 and "A – kan blokeres (3 aftener" in _sent()[-1]
    assert main.sharing_auto_compare(users) == [], "samme konto næste uge = ikke ny"
    users.append({"user_id": "3", "name": "C", "bucket": "afgoer"})
    assert [u["user_id"] for u in main.sharing_auto_compare(users)] == ["3"]
    assert {x["user_id"] for x in main.kv_get(main.SH_AUTO_NEW)} == {"1", "3"}


def test_sharing_auto_endpoint_and_schedule(client):
    main.kv_set(main.SH_AUTO_NEW, [{"user_id": "1", "name": "A", "bucket": "bloker", "evenings": 2, "at": "x"}])
    assert client.get("/api/overview").json()["sharing_new"] == 1
    d = client.put("/api/sharing/auto", json={"seen": True, "enabled": False}).json()
    assert d["new"] == [] and d["enabled"] is False
    assert main.sharing_auto_tick() is None, "slået fra"
    client.put("/api/sharing/auto", json={"enabled": True})
    res = main.sharing_auto_tick(force=True)
    assert res, "kører, når den tvinges"
    job, th = res
    th.join(30)
    assert job["status"] == "færdig", job.get("error")


def test_fejlsoeg(client):
    _reset()
    cid = _customer(client) if not main.db().execute("SELECT 1 FROM k_services WHERE plex_user_id=9001").fetchone() else \
        main.db().execute("SELECT customer_id FROM k_services WHERE plex_user_id=9001").fetchone()[0]
    efterligning.TRACEARR["history"] = {"tu1": [
        {"started_at": _z(0, 2), "show_title": "Fjordmord", "season_number": 1, "episode_number": 2, "device": "Stuen", "product": "Plex for LG",
         "resolution": "1080p", "is_transcode": True, "video_decision": "transcode", "audio_decision": "copy",
         "transcode_info": {"videoReason": "bitrate for høj"}, "bitrate": 8200, "subtitle_info": {"language": "da", "codec": "srt"},
         "percent_complete": 40},
        {"started_at": _z(1), "media_title": "Den Opdigtede Film", "year": 2026, "device": "Telefon", "product": "Plex for Android",
         "is_transcode": False, "video_decision": "directplay"}]}
    efterligning.TRACEARR["streams"] = [{"user": {"id": "tu1"}, "media_title": "Juleræset", "started_at": _z(0, 0), "is_transcode": False}]
    efterligning.TRACEARR["violations"] = [efterligning.tr_violation("v20", "tu1", "Betaling", _z(1))]
    blokeringer.sync()
    d = client.get(f"/api/fejlsoeg/{cid}").json()
    assert d["errors"] == []
    assert [p["title"] for p in d["plays"]] == ["Fjordmord S01E02", "Den Opdigtede Film (2026)"]
    assert d["plays"][0]["transcode"] and d["plays"][0]["reasons"] == ["bitrate for høj"]
    assert d["now"][0]["title"] == "Juleræset"
    assert d["violations"][0]["rule"] == "Betaling"
    assert {s["name"] for s in d["status"]} == {"Plex", "Seerr", "IPTV 1"}
    assert d["suggestion"].startswith("Hej Kunde.") and "betalingen mangler" in d["suggestion"]

    efterligning.TRACEARR["iptv_up"] = False
    d = client.get(f"/api/fejlsoeg/{cid}").json()
    assert "problem med IPTV 1" in d["suggestion"]
    efterligning.TRACEARR["iptv_up"] = True
    assert client.get("/api/fejlsoeg/99999").status_code == 404


def test_suggestion_texts():
    s = __import__("app.fejlsoeg", fromlist=["x"]).suggest
    assert "genstarte" not in s("Ib", [], [], [], None, "") and "lukke Plex-appen" in s("Ib", [], [], [], None, "")
    hid = {"waiting": [{"title": "Juleræset", "reveal_by": "2026-11-29T10:00:00"}], "shown": []}
    assert "venter på danske undertekster" in s("Ib", [], [], [], hid, "jule") and "2026-11-29 kl. 10:00" in s("Ib", [], [], [], hid, "jule")
    assert "lukke Plex-appen" in s("Ib", [], [], [], {"waiting": [], "shown": []}, "Ukendt")
    tv = [{"rule": "Tv på flere adresser", "action": "stopper"}]
    assert "to tv på forskellige adresser" in s("Ib", [], tv, [], None, "")
    many = [{"transcode": True, "video": "transcode"}] * 3
    assert "Original/Maksimum" in s("Ib", many, [], [], None, "")
