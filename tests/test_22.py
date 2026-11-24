"""2.2.0: tidslinje, send-kø, ønsker klar, ændring for alle og det, kunderne leder efter.

Seerr er efterlignet (tests/efterligning.py) – intet sendes til kunderne og intet til den rigtige bot.
"""

import datetime
import json
import os

import efterligning
from app import beskeder, kunder, main


def _customer(client, name, price=75, tg="", fb="", kind="kunde", method="MobilePay", plex_user_id=None):
    c = client.post("/api/kunder/customers", json={"name": name, "method": method, "freq": "maaned"}).json()
    upd = {**c, "status": "aktiv", "kind": kind, "tg": tg, "fb": fb}
    client.put(f"/api/kunder/customers/{c['id']}", json=upd)
    client.post("/api/kunder/services", json={"customer_id": c["id"], "service": "plex", "price": price})
    if plex_user_id:
        kunder.run("UPDATE k_services SET plex_user_id=? WHERE customer_id=? AND service='plex'", (plex_user_id, c["id"]))
    return c["id"]


def test_templates_defaults_and_crud(client):
    d = client.get("/api/beskeder/skabeloner").json()
    kinds = {t["kind"] for t in d["templates"]}
    assert {"velkomst", "klar", "pris"} <= kinds
    assert "{fornavn}" in d["fields"]
    r = client.post("/api/beskeder/skabeloner", json={"name": "Jul", "text": "Glædelig jul {fornavn}!"})
    t = next(x for x in r.json()["templates"] if x["name"] == "Jul")
    assert client.delete(f"/api/beskeder/skabeloner/{t['id']}").status_code == 200
    klar = next(x for x in d["templates"] if x["kind"] == "klar")
    assert client.delete(f"/api/beskeder/skabeloner/{klar['id']}").status_code == 400, "faste skabeloner kan ikke slettes"
    assert client.post("/api/beskeder/skabeloner", json={"name": "", "text": "x"}).status_code == 400


def test_render_fields():
    out = beskeder.render("Hej {fornavn} ({navn}) – {titel} – {guide}", {"name": "Anna Testesen"}, {"titel": "Fjordmord"})
    assert out.startswith("Hej Anna (Anna Testesen) – Fjordmord – https://")


def test_queue_flow_and_timeline(client):
    a = _customer(client, "Kø Kunde", tg="@koekunde")
    b = _customer(client, "Kø Familie", kind="egen")
    tid = next(t["id"] for t in client.get("/api/beskeder/skabeloner").json()["templates"] if t["kind"] == "velkomst")
    pre = client.post("/api/beskeder/modtagere", json={"who": "udvalgte", "ids": [a, b]}).json()
    assert pre["count"] == 2
    alle = client.post("/api/beskeder/modtagere", json={"who": "alle"}).json()
    assert b not in [c["id"] for c in alle["customers"]], "familie er ikke med, medmindre det vælges"
    q = client.post("/api/beskeder/koe", json={"template_id": tid, "who": "udvalgte", "ids": [a]}).json()
    assert q["total"] == 1 and q["status"] == "aktiv"
    it = q["items"][0]
    assert it["text"].startswith("Hej Kø") and it["tg"] == "koekunde" and "{" not in it["text"]
    q = client.post(f"/api/beskeder/item/{it['id']}", json={"action": "sent"}).json()
    assert q["status"] == "færdig" and q["counts"]["sendt"] == 1
    tl = client.get(f"/api/beskeder/tidslinje/{a}").json()["events"]
    assert any("Besked sendt" in e["text"] for e in tl)
    assert any(e["text"] == "Oprettet i Fangarr" for e in tl)
    q = client.post(f"/api/beskeder/item/{it['id']}", json={"action": "undo"}).json()
    assert q["status"] == "aktiv"
    q = client.post(f"/api/beskeder/koe/{q['id']}/status", json={"status": "stoppet"}).json()
    assert q["status"] == "stoppet"
    assert client.post("/api/beskeder/koe", json={"template_id": tid, "who": "udvalgte", "ids": []}).status_code == 400


def test_timeline_notes(client):
    a = _customer(client, "Note Kunde")
    tl = client.post(f"/api/beskeder/tidslinje/{a}", json={"text": "Ringede om Chromecast"}).json()["events"]
    note = next(e for e in tl if e["kind"] == "note")
    assert note["text"] == "Ringede om Chromecast" and note["id"]
    tl = client.delete(f"/api/beskeder/tidslinje/note/{note['id']}").json()["events"]
    assert not any(e["kind"] == "note" for e in tl)
    assert client.post(f"/api/beskeder/tidslinje/{a}", json={"text": " "}).status_code == 400


def test_price_change_scheduled_and_applied(client):
    a = _customer(client, "Pris A", price=75)
    b = _customer(client, "Pris B", price=60)
    nxt = (main.now().date().replace(day=1) + datetime.timedelta(days=40)).strftime("%Y-%m")
    plan = client.post("/api/beskeder/pris/plan", json={"service": "plex", "price": 85, "from": nxt, "only_price": 75}).json()
    ids = [c["id"] for c in plan["customers"]]
    assert a in ids and b not in ids, "kun dem, der betaler 75 kr. i dag"
    pa = next(c for c in plan["customers"] if c["id"] == a)
    assert pa["monthly_before"] == 75 and pa["monthly_after"] == 85
    # intet ændret endnu
    assert kunder.one("SELECT price FROM k_services WHERE customer_id=?", (a,))["price"] == 75
    assert client.post("/api/beskeder/pris", json={"service": "plex", "price": 85, "from": nxt, "only_price": 75,
                                                    "confirm_ids": ids[:-1] if len(ids) > 1 else []}).status_code == 409
    r = client.post("/api/beskeder/pris", json={"service": "plex", "price": 85, "from": nxt, "only_price": 75, "confirm_ids": ids})
    assert r.status_code == 200, r.text
    assert kunder.one("SELECT price FROM k_services WHERE customer_id=?", (a,))["price"] == 75, "fremtidig dato: prisen ændres først den dato"
    q = client.get(f"/api/beskeder/koe/{r.json()['queue_id']}").json()
    msg = next(i for i in q["items"] if i["customer_id"] == a)["text"]
    assert "75 kr." in msg and "85 kr." in msg
    # annullér og lav en, der gælder fra i dag
    pid = r.json()["changes"][0]["id"]
    assert client.delete(f"/api/beskeder/pris/{pid}").status_code == 200
    cur = kunder.cur_period()
    kunder.ensure_charges(cur)
    ch_before = kunder.one("SELECT * FROM k_charges WHERE customer_id=? AND period=?", (a, cur))
    plan = client.post("/api/beskeder/pris/plan", json={"service": "plex", "price": 80, "from": cur, "only_price": 75}).json()
    r = client.post("/api/beskeder/pris", json={"service": "plex", "price": 80, "from": cur, "only_price": 75, "queue": False,
                                                 "confirm_ids": [c["id"] for c in plan["customers"]]})
    assert r.status_code == 200
    assert kunder.one("SELECT price FROM k_services WHERE customer_id=?", (a,))["price"] == 80
    if ch_before and not ch_before["requested_at"]:
        assert kunder.one("SELECT amount FROM k_charges WHERE id=?", (ch_before["id"],))["amount"] == 80
    assert kunder.one("SELECT price FROM k_services WHERE customer_id=?", (b,))["price"] == 60
    assert client.delete(f"/api/beskeder/pris/{r.json()['changes'][0]['id']}").status_code == 400, "gennemført kan ikke annulleres"


def test_ready_wishes(client, monkeypatch):
    monkeypatch.setattr(beskeder, "SEERR_URL", os.environ["UPTIME_URL"].replace("/uptime", "/seerr"))
    monkeypatch.setattr(beskeder, "SEERR_APIKEY", "test")
    cid = _customer(client, "Ønske Kunde", tg="@oenske", plex_user_id=777001)
    old = {"id": 9001, "type": "movie", "media": {"tmdbId": 502, "status": 5}, "requestedBy": {"plexId": 777001},
           "updatedAt": datetime.datetime.utcnow().isoformat() + "Z", "createdAt": datetime.datetime.utcnow().isoformat() + "Z"}
    efterligning.SEERR["requests"] = [old]
    main.kv_set("klar_init", False)
    beskeder.check_ready()
    assert client.get("/api/beskeder/klar").json()["items"] == [], "første gang huskes de gamle"
    now_ = datetime.datetime.utcnow().isoformat() + "Z"
    efterligning.SEERR["requests"] = [old,
        {"id": 9002, "type": "movie", "media": {"tmdbId": 501, "status": 5}, "requestedBy": {"plexId": 777001}, "updatedAt": now_, "createdAt": now_},
        {"id": 9003, "type": "tv", "seasons": [{"seasonNumber": 1}, {"seasonNumber": 2}],
         "media": {"tmdbId": 601, "status": 4, "seasons": [{"seasonNumber": 1, "status": 5}, {"seasonNumber": 2, "status": 3}]},
         "requestedBy": {"plexId": 777001}, "updatedAt": now_, "createdAt": now_}]
    assert beskeder.check_ready() == 1, "serien er kun delvist klar"
    items = client.get("/api/beskeder/klar").json()["items"]
    assert len(items) == 1 and items[0]["title"] == "Den Opdigtede Film (2026)" and "Den Opdigtede Film" in items[0]["text"]
    efterligning.SEERR["requests"][2]["media"]["seasons"][1]["status"] = 5
    assert beskeder.check_ready() == 1
    items = client.get("/api/beskeder/klar").json()["items"]
    assert any("sæson 1 og 2" in i["title"] for i in items)
    main.save_settings({"klar_hour": 0})
    main.kv_set("beskeder_jobs", {"klar_ts": main.now().timestamp()})
    n = len(efterligning.TG["sent"])
    beskeder.tick()
    msgs = [m for m in efterligning.TG["sent"][n:] if "ønske er klar" in m["text"]]
    assert len(msgs) == 1 and "2 kunder" in msgs[0]["text"]
    assert "@" not in msgs[0]["text"] and "oenske" not in msgs[0]["text"]
    beskeder.tick()
    assert len([m for m in efterligning.TG["sent"][n:] if "ønske er klar" in m["text"]]) == 1, "kun én om dagen"
    r = client.post(f"/api/beskeder/klar/{items[0]['id']}", json={"action": "sent"}).json()
    assert len(r["items"]) == 1
    tl = client.get(f"/api/beskeder/tidslinje/{cid}").json()["events"]
    assert any(e["kind"] == "klar" for e in tl) and any("Besked sendt" in e["text"] for e in tl)


def test_searches_page(client, monkeypatch, tmp_path):
    from app import guide
    d = tmp_path / "stat"
    d.mkdir()
    today = main.now().strftime("%Y-%m-%d")
    lines = [{"t": f"{today}T10:00:00", "uid": "1", "user": "a", "e": "search", "q": "chromecast", "h": "0"},
             {"t": f"{today}T11:00:00", "uid": "2", "user": "b", "e": "search", "q": "chromecast", "h": "0"},
             {"t": f"{today}T12:00:00", "uid": "2", "user": "b", "e": "search", "q": "betaling", "h": "3"},
             {"t": f"{today}T13:00:00", "uid": "3", "user": "c", "e": "search", "q": "gammel"}]
    (d / f"{today}.jsonl").write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    monkeypatch.setattr(guide, "STAT_DIR", str(d))
    guide._cache.clear()
    monkeypatch.setattr(beskeder, "SEERR_URL", os.environ["UPTIME_URL"].replace("/uptime", "/seerr"))
    monkeypatch.setattr(beskeder, "SEERR_APIKEY", "test")
    now_ = datetime.datetime.utcnow().isoformat() + "Z"
    efterligning.SEERR["requests"] = [
        {"id": 1, "type": "movie", "media": {"tmdbId": 501, "status": 3}, "requestedBy": {"id": 1}, "createdAt": now_},
        {"id": 2, "type": "movie", "media": {"tmdbId": 501, "status": 3}, "requestedBy": {"id": 2}, "createdAt": now_},
        {"id": 3, "type": "tv", "media": {"tmdbId": 601, "status": 5}, "requestedBy": {"id": 1}, "createdAt": now_}]
    r = client.get("/api/beskeder/soegninger").json()
    assert r["nohits"][0]["q"] == "chromecast" and r["nohits"][0]["nohit"] == 2
    assert all(q["q"] != "betaling" for q in r["nohits"])
    assert r["seerr"][0]["title"].startswith("Den Opdigtede Film") and r["seerr"][0]["users"] == 2


def test_overview_has_beskeder(client):
    ov = client.get("/api/overview").json()
    assert {"klar", "koe"} <= set(ov["beskeder"])
