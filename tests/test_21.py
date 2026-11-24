"""2.1.0: huskeliste, udgifter, besked ved 0 streams, knapper i Stream365 Drift og premierer med knapper.

Telegram og Tautulli er efterlignet (tests/efterligning.py) – intet sendes til den rigtige bot.
"""

import datetime
import json

import efterligning
from app import huskeliste, main, stille, tg

CHAT = 731397952


def _press(data, chat=CHAT, sender=CHAT, msg=None):
    """Efterlign et tryk på en knap, som Telegram sender det."""
    m = msg or {"message_id": 1, "chat": {"id": chat}, "text": "besked", "reply_markup": {"inline_keyboard": [[{"text": "x", "callback_data": data}]]}}
    m["chat"] = {"id": chat}
    return tg.handle_callback({"id": "cb1", "from": {"id": sender}, "message": m, "data": data})


def _last_buttons():
    kb = efterligning.TG["sent"][-1].get("reply_markup") or {}
    return [b for row in kb.get("inline_keyboard") or [] for b in row]


def test_huskeliste_seeded_and_crud(client):
    r = client.get("/api/huskeliste")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 10, "datoopgaverne fra dokumentationen er lagt ind"
    assert not any("TOKEN" in (i["command"] or "") or "KEY" in (i["command"] or "") for i in items)
    r = client.post("/api/huskeliste", json={"title": "Test-opgave", "due": "2026-01-01", "server": "feeder",
                                             "command": "df -h /mnt/local", "repeat": "uge"})
    assert r.status_code == 200, r.text
    h = next(i for i in r.json()["items"] if i["title"] == "Test-opgave")
    assert h["overdue"]
    r = client.post(f"/api/huskeliste/{h['id']}/done")
    h2 = next(i for i in r.json()["items"] if i["id"] == h["id"])
    assert h2["due"] > main.now().date().isoformat(), "gentagen opgave rykket frem til en fremtidig dato"
    assert client.post("/api/huskeliste", json={"title": "", "due": "2026-01-01"}).status_code == 400
    assert client.post("/api/huskeliste", json={"title": "x", "due": "1/12"}).status_code == 400
    assert client.delete(f"/api/huskeliste/{h['id']}").status_code == 200


def test_huskeliste_telegram_buttons_and_undo(client):
    today = main.now().date().isoformat()
    r = client.post("/api/huskeliste", json={"title": "Knaptest", "due": today, "server": "Mediabox", "command": "uptime"})
    hid = next(i for i in r.json()["items"] if i["title"] == "Knaptest")["id"]
    main.save_settings({"huske_hour": 0})
    n = len(efterligning.TG["sent"])
    huskeliste.tick()
    sent = [m for m in efterligning.TG["sent"][n:] if "Knaptest" in m["text"]]
    assert len(sent) == 1 and "Kontrol: uptime" in sent[0]["text"]
    huskeliste.tick()   # kun én besked pr. dag
    assert len([m for m in efterligning.TG["sent"][n:] if "Knaptest" in m["text"]]) == 1
    btns = [b for row in sent[0]["reply_markup"]["inline_keyboard"] for b in row]
    done = next(b for b in btns if b["text"] == "Udført")["callback_data"]
    assert _press(done) == "udført"
    assert not any(i["id"] == hid for i in client.get("/api/huskeliste").json()["items"])
    assert _press(done).startswith("Allerede") or "allerede" in _press(done).lower()
    # fortryd: knappen i den rettede besked
    edit = efterligning.TG["edits"][-1]
    undo = [b for row in edit["reply_markup"]["inline_keyboard"] for b in row if b["text"].startswith("↩️")][0]
    assert _press(undo["callback_data"]) == "står på huskelisten igen"
    assert any(i["id"] == hid for i in client.get("/api/huskeliste").json()["items"])
    # udsæt en dag
    snooze = next(b for b in btns if b["text"] == "Udsæt en dag")["callback_data"]
    assert _press(snooze).startswith("udsat til")
    h = next(i for i in client.get("/api/huskeliste").json()["items"] if i["id"] == hid)
    assert h["due"] == (main.now().date() + datetime.timedelta(days=1)).isoformat()


def test_buttons_only_from_own_chat(client):
    today = main.now().date().isoformat()
    r = client.post("/api/huskeliste", json={"title": "Fremmed tryk", "due": today})
    hid = next(i for i in r.json()["items"] if i["title"] == "Fremmed tryk")["id"]
    main.tg.send("x", [[("Udført", "huske_done", {"id": hid})]])
    data = _last_buttons()[0]["callback_data"]
    assert _press(data, chat=123, sender=123) == "afvist"
    assert _press(data, chat=CHAT, sender=999) == "afvist"
    assert any(i["id"] == hid for i in client.get("/api/huskeliste").json()["items"]), "fremmed tryk ændrer intet"
    assert _press("a:999999") == "ukendt"
    assert _press("noget-andet") == "ukendt"


def test_poll_once_reads_only_callbacks(client):
    today = main.now().date().isoformat()
    r = client.post("/api/huskeliste", json={"title": "Poll-test", "due": today})
    hid = next(i for i in r.json()["items"] if i["title"] == "Poll-test")["id"]
    main.tg.send("x", [[("Udført", "huske_done", {"id": hid})]])
    data = _last_buttons()[0]["callback_data"]
    efterligning.TG["updates"] = [
        {"update_id": 500, "message": {"text": "hej", "chat": {"id": CHAT}}},
        {"update_id": 501, "callback_query": {"id": "c", "from": {"id": CHAT}, "data": data,
                                              "message": {"message_id": 9, "chat": {"id": CHAT}, "text": "x"}}},
    ]
    assert tg.poll_once(timeout=0) == 2
    assert main.kv_get("tg_offset") == 502
    assert not any(i["id"] == hid for i in client.get("/api/huskeliste").json()["items"])
    st = client.get("/api/telegram/status").json()
    assert st["enabled"] and st["buttons"]
    assert "TOKEN" not in json.dumps(st) and "test" not in json.dumps({k: v for k, v in st.items() if k != "recent"})


def test_buttons_off_sends_plain_message(client):
    main.save_settings({"tg_buttons": False})
    try:
        main.tg.send("uden knapper", [[("Udført", "huske_done", {"id": 1})]])
        assert "reply_markup" not in efterligning.TG["sent"][-1]
    finally:
        main.save_settings({"tg_buttons": True})


def test_udgifter_and_renewal_reminder(client):
    soon = (main.now().date() + datetime.timedelta(days=5)).isoformat()
    r = client.post("/api/udgifter", json={"name": "Domæne", "amount": 120, "per": "aar", "renews": soon, "notice": 14})
    assert r.status_code == 200, r.text
    u = next(x for x in r.json()["items"] if x["name"] == "Domæne")
    assert u["soon"] and u["monthly"] == 10
    huskeliste.renewals_to_huske()
    huskeliste.renewals_to_huske()   # kun én gang pr. fornyelsesdato
    items = [i for i in client.get("/api/huskeliste").json()["items"] if i["kind"] == "udgift" and "Domæne" in i["title"]]
    assert len(items) == 1
    client.post(f"/api/huskeliste/{items[0]['id']}/done")
    u2 = next(x for x in client.get("/api/udgifter").json()["items"] if x["name"] == "Domæne")
    assert u2["renews"] > soon, "fornyelsen rykket et år frem"
    assert client.post("/api/udgifter", json={"name": "x", "amount": 0}).status_code == 400
    assert client.delete(f"/api/udgifter/{u['id']}").status_code == 200


def test_payment_reminder_buttons(client):
    from app import kunder
    r = client.post("/api/kunder/customers", json={"name": "Knap Kunde", "plex_user": "", "kind": "kunde", "status": "aktiv",
                                                   "freq": "maaned", "cycle": "", "due_day": "", "phone": "", "email": ""})
    cid = r.json()["id"]
    old = main.iso(main.now() - datetime.timedelta(days=30))
    chid = kunder.run("INSERT INTO k_charges (customer_id, period, amount, base, detail, requested_at, skipped) VALUES (?,?,?,?,?,?,0)",
                      (cid, "2026-10", 75, 75, "{}", old))
    text, undo = kunder.tg_paid({"id": chid})
    assert "Knap Kunde" in text and undo
    assert kunder.one("SELECT paid_at FROM k_charges WHERE id=?", (chid,))["paid_at"]
    kunder.tg_unpaid(undo)
    assert not kunder.one("SELECT paid_at FROM k_charges WHERE id=?", (chid,))["paid_at"]
    text, undo = kunder.tg_snooze({"id": chid})
    assert chid not in [x["id"] for x in kunder.overdue_list(skip_snoozed=True)]
    kunder.tg_unsnooze(undo)
    assert chid in [x["id"] for x in kunder.overdue_list(skip_snoozed=True)]
    assert "@" not in text and "+45" not in text


def test_zero_streams(client):
    r = client.post("/api/stille", json={"from": "", "to": ""})
    assert r.status_code == 200 and r.json()["armed"]
    efterligning.TAUTULLI["streams"] = 2
    n = len(efterligning.TG["sent"])
    stille.tick()
    assert len(efterligning.TG["sent"]) == n and stille.state()["armed"]
    efterligning.TAUTULLI["streams"] = 0
    stille.tick()
    assert "0 streams" in efterligning.TG["sent"][-1]["text"]
    assert not stille.state()["armed"]
    stille.tick()
    assert len(efterligning.TG["sent"]) == n + 1, "kun én besked"
    again = _last_buttons()[0]["callback_data"]
    assert "siger til" in _press(again)
    assert stille.state()["armed"]
    client.delete("/api/stille")
    assert not stille.state()["armed"]
    assert client.post("/api/stille", json={"from": "25", "to": "6"}).status_code == 400
    efterligning.TAUTULLI["streams"] = 3


def test_zero_streams_window():
    n = datetime.datetime(2026, 11, 24, 3, 0)
    assert stille._in_window({"from": 2, "to": 6}, n)
    assert not stille._in_window({"from": 22, "to": 2}, n)
    assert stille._in_window({"from": 22, "to": 6}, n)
    assert stille._in_window({}, n)


def test_premiere_buttons(client, monkeypatch):
    r = client.post("/api/rules", json={"name": "Danske serier", "active": True, "media": "series", "instance": "sonarr2",
                                        "root_folder": "/data/TV/TV", "quality_profile_id": 1})
    assert r.status_code in (200, 201), r.text
    items = [{"date": "2026-12-01", "title": "Opdigtet Serie", "network": "DR1", "genres": ["Drama"], "tvdb": 4242, "tmdb": 9191,
              "url": "", "summary": "Testdata"}]
    monkeypatch.setattr(main, "premiere_status", lambda xs: [dict(x, exists=False, following=False) for x in xs])
    main._prem_bg["items"] = items
    main.kv_set("premieres_told_init", True)
    main.kv_set("premieres_told", [])
    n = len(efterligning.TG["sent"])
    main.notify_premieres()
    assert len(efterligning.TG["sent"]) == n + 1
    labels = [b["text"] for b in _last_buttons()]
    assert labels == ["Tilføj nu", "Følg", "Ikke interesseret"]
    main.notify_premieres()
    assert len(efterligning.TG["sent"]) == n + 1, "hver premiere kun én gang"
    no = next(b for b in _last_buttons() if b["text"] == "Ikke interesseret")["callback_data"]
    assert "vises ikke" in _press(no)
    assert main.premieres_pending() == []
    main._prem_bg["items"] = None


def test_settings_have_21_fields(client):
    s = client.put("/api/settings", json={"huske_hour": 7}).json()
    assert s["huske_hour"] == 7
    for k in ("tg_buttons", "huske_hour", "prem_notify", "prem_rule"):
        assert k in s


def test_waitlist_suggestion_buttons(client):
    main.kv_set("wl_told_init", True)
    sugg = [{"id": 777, "title": "Opdigtet Forslag", "year": 2026, "rule": "Danske serier", "instance": "sonarr2", "exists": False}]
    main.add_to_waitlist("series", "Forslagstitel", "Forslagstitel.S01E01.DANiSH.1080p.WEB", {"media": "series"}, "Danske serier",
                         "ikke fundet", suggestions=sugg)
    n = len(efterligning.TG["sent"])
    main.notify_suggestions()
    assert len(efterligning.TG["sent"]) == n + 1
    labels = [b["text"] for b in _last_buttons()]
    assert labels[0].startswith("Godkend: Opdigtet Forslag") and labels[-1] == "Fjern fra ventelisten"
    main.notify_suggestions()
    assert len(efterligning.TG["sent"]) == n + 1, "hver titel kun én gang"
    remove = _last_buttons()[-1]["callback_data"]
    assert "fjernet fra ventelisten" in _press(remove)
    assert not any(w["title"] == "Forslagstitel" for w in client.get("/api/waitlist").json())
    undo = [b for row in efterligning.TG["edits"][-1]["reply_markup"]["inline_keyboard"] for b in row if b["text"].startswith("↩️")][0]
    assert _press(undo["callback_data"]) == "står på ventelisten igen"
    con = main.db()
    assert con.execute("SELECT status FROM waitlist WHERE title='Forslagstitel'").fetchone()["status"] == "venter"
    con.close()


def test_safety_net_has_translate_button(client):
    main.notify_safety_net([{"shown_by": "sikkerhedsnet", "key": "ep:55", "import_at": "2026-11-24T10:00:00", "title": "Opdigtet S01E01",
                             "reason": "ingen dansk tekst"}])
    assert "UDEN dansk tekst" in efterligning.TG["sent"][-1]["text"]
    assert _last_buttons()[0]["text"].startswith("Oversæt nu")
