"""Knapper i Stream365 Drift (2.1.0).

Fangarr kan nu både sende beskeder med knapper og læse dine tryk. Fangarr henter selv trykkene hos Telegram
(getUpdates) – der åbnes ingen ny adresse udefra, og intet går uden om Authelia.

Sikkerhed:
- Kun tryk fra din egen chat (TELEGRAM_CHAT_ID) tages imod. Tryk fra alle andre afvises og logges (uden indhold).
- Hver knap peger på en handling i tabellen tg_actions (tal-id). Knappens data er kun "a:<id>" / "u:<id>",
  så Telegram aldrig ser kundedata. En handling kan kun udføres én gang og udløber efter 14 dage.
- Efter et tryk skrives det, der skete, i beskeden. Kan handlingen fortrydes, kommer der en Fortryd-knap.
- Kun én app må læse en bot ad gangen. Tjekket 24. nov. 2026: ingen webhook, intet andet script læser botten.

Andre moduler registrerer handlinger med register(kind, gør, fortryd) og sender med send(text, rows).
"""

import datetime
import json
import logging
import os
import threading
import time

import httpx

log = logging.getLogger("fangarr")
D = {}   # udfyldes af main.py: db, kv_get, kv_set, now, iso, get_settings

API = (os.environ.get("TELEGRAM_API") or "https://api.telegram.org").rstrip("/")
HANDLERS = {}     # kind -> (do(payload) -> (tekst, undo_payload|None), undo(payload) -> tekst | None)
KEEP_DAYS = 14
_state = {"last_ok": "", "last_error": "", "rejected": 0, "handled": 0, "running": False}


def _tok():
    return os.environ.get("TELEGRAM_TOKEN") or ""


def _chat():
    return str(os.environ.get("TELEGRAM_CHAT_ID") or "")


def enabled():
    return bool(_tok() and _chat())


def buttons_on():
    return enabled() and bool(D["get_settings"]().get("tg_buttons", True))


def init():
    con = D["db"]()
    with con:
        con.execute("CREATE TABLE IF NOT EXISTS tg_actions (id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, kind TEXT,"
                    " label TEXT, payload TEXT, done_at TEXT, result TEXT, undo TEXT, undone_at TEXT)")
    con.close()


def register(kind, do, undo=None):
    HANDLERS[kind] = (do, undo)


def _call(method, **data):
    r = httpx.post(f"{API}/bot{_tok()}/{method}", json=data, timeout=40)
    try:
        body = r.json()
    except ValueError:
        body = {}
    if not body.get("ok"):
        # beskeden indeholder aldrig adressen (bot-tokenet står i den)
        raise RuntimeError(f"Telegram svarede {r.status_code}: {str(body.get('description') or '')[:120]}")
    return body.get("result")


def action(kind, label, payload):
    """Opret en handling og returnér knappen til den."""
    con = D["db"]()
    with con:
        cur = con.execute("INSERT INTO tg_actions (created, kind, label, payload) VALUES (?,?,?,?)",
                          (D["iso"](D["now"]()), kind, label, json.dumps(payload, ensure_ascii=False)))
        aid = cur.lastrowid
    con.close()
    return {"text": label, "callback_data": f"a:{aid}"}


def send(text, rows=None):
    """Send en besked. rows = liste af rækker med (tekst, kind, payload). Uden knapper (eller slået fra) = almindelig besked.
    Returnerer True, hvis beskeden blev sendt."""
    if not enabled():
        return False
    data = {"chat_id": _chat(), "text": text[:4000]}
    if rows and buttons_on():
        kb = [[action(kind, label, payload) for (label, kind, payload) in row] for row in rows if row]
        if kb:
            data["reply_markup"] = {"inline_keyboard": kb}
    try:
        _call("sendMessage", **data)
        return True
    except (httpx.HTTPError, RuntimeError) as e:
        log.warning("Telegram fejlede: %s", e.__class__.__name__ if isinstance(e, httpx.HTTPError) else e)
        return False


# ---------------------------------------------------------------- tryk fra Telegram

def _row_without(markup, cb, replacement=None):
    """Tastaturet uden rækken med den trykkede knap (eller med replacement i stedet)."""
    out = []
    for row in (markup or {}).get("inline_keyboard") or []:
        if any(b.get("callback_data") == cb for b in row):
            if replacement:
                out.append(replacement)
        else:
            out.append(row)
    return out


def handle_callback(cq):
    """Ét tryk. Returnerer det svar, der vises kort i Telegram (bruges også af testene)."""
    frm = str((cq.get("from") or {}).get("id") or "")
    msg = cq.get("message") or {}
    chat = str((msg.get("chat") or {}).get("id") or "")
    if frm != _chat() or chat != _chat():
        _state["rejected"] += 1
        log.warning("Telegram: tryk fra en anden chat afvist")
        _answer(cq, "Ikke tilladt")
        return "afvist"
    data = str(cq.get("data") or "")
    kind_flag, _, sid = data.partition(":")
    aid = int(sid) if sid.isdigit() else 0
    con = D["db"]()
    row = con.execute("SELECT * FROM tg_actions WHERE id=?", (aid,)).fetchone()
    con.close()
    if not row or kind_flag not in ("a", "u"):
        _answer(cq, "Knappen er for gammel – brug Fangarr")
        return "ukendt"
    do, undo = HANDLERS.get(row["kind"], (None, None))
    stamp = D["now"]().strftime("%H:%M")
    if kind_flag == "a":
        if row["done_at"]:
            _answer(cq, "Allerede gjort: " + (row["result"] or ""))
            return "allerede"
        if D["now"]() - datetime.datetime.fromisoformat(row["created"]) > datetime.timedelta(days=KEEP_DAYS):
            _answer(cq, "Knappen er udløbet – brug Fangarr")
            return "udløbet"
        if not do:
            _answer(cq, "Ukendt handling")
            return "ukendt"
        try:
            result, undo_payload = do(json.loads(row["payload"] or "{}"))
        except Exception as e:   # vis fejlen i Telegram, men stop aldrig løkken
            result, undo_payload = f"fejl: {str(e)[:150]}", None
            _set(aid, None, None, result)
            _answer(cq, result[:190])
            _edit(msg, cq.get("data"), f"⚠️ {row['label']}: {result} ({stamp})", None)
            return result
        _set(aid, D["iso"](D["now"]()), undo_payload, result)
        _state["handled"] += 1
        repl = [{"text": "↩️ Fortryd: " + row["label"], "callback_data": f"u:{aid}"}] if (undo and undo_payload is not None) else None
        _edit(msg, cq.get("data"), f"✅ {row['label']}: {result} ({stamp})", repl)
        _answer(cq, result[:190])
        return result
    # fortryd
    if not row["done_at"] or row["undone_at"] or not row["undo"] or not undo:
        _answer(cq, "Kan ikke fortrydes")
        return "kan ikke fortrydes"
    try:
        result = undo(json.loads(row["undo"]))
    except Exception as e:
        result = f"fejl: {str(e)[:150]}"
    con = D["db"]()
    with con:
        con.execute("UPDATE tg_actions SET undone_at=? WHERE id=?", (D["iso"](D["now"]()), aid))
    con.close()
    _edit(msg, cq.get("data"), f"↩️ Fortrudt – {row['label']}: {result} ({stamp})", None)
    _answer(cq, result[:190])
    return result


def _set(aid, done_at, undo, result):
    con = D["db"]()
    with con:
        con.execute("UPDATE tg_actions SET done_at=?, undo=?, result=? WHERE id=?",
                    (done_at, json.dumps(undo, ensure_ascii=False) if undo is not None else None, result, aid))
    con.close()


def _answer(cq, text):
    try:
        _call("answerCallbackQuery", callback_query_id=cq.get("id"), text=text[:190])
    except (httpx.HTTPError, RuntimeError):
        pass


def _edit(msg, cb, line, replacement):
    if not msg.get("message_id"):
        return
    text = (msg.get("text") or "")[:3700] + "\n\n" + line
    try:
        _call("editMessageText", chat_id=_chat(), message_id=msg["message_id"], text=text,
              reply_markup={"inline_keyboard": _row_without(msg.get("reply_markup"), cb, replacement)})
    except (httpx.HTTPError, RuntimeError) as e:
        log.warning("Telegram: beskeden kunne ikke rettes: %s", e.__class__.__name__ if isinstance(e, httpx.HTTPError) else e)


def poll_once(timeout=25):
    """Hent nye tryk hos Telegram (long polling). Kun callback-tryk behandles; almindelige beskeder ignoreres."""
    offset = int(D["kv_get"]("tg_offset", 0) or 0)
    ups = _call("getUpdates", offset=offset, timeout=timeout, allowed_updates=["callback_query"]) or []
    for u in ups:
        D["kv_set"]("tg_offset", int(u.get("update_id", 0)) + 1)
        if u.get("callback_query"):
            try:
                handle_callback(u["callback_query"])
            except Exception as e:
                log.warning("Telegram: tryk kunne ikke behandles: %s", e)
    _state["last_ok"] = D["iso"](D["now"]())
    _state["last_error"] = ""
    return len(ups)


def _loop():
    _state["running"] = True
    wait = 5
    while True:
        if not buttons_on():
            time.sleep(30)
            continue
        try:
            poll_once()
            wait = 5
        except Exception as e:   # netværk, Telegram nede osv. – prøv igen lidt senere
            _state["last_error"] = str(e)[:150] if not isinstance(e, httpx.HTTPError) else e.__class__.__name__
            time.sleep(wait)
            wait = min(wait * 2, 300)


def start():
    if enabled():
        threading.Thread(target=_loop, daemon=True).start()


def cleanup():
    con = D["db"]()
    with con:
        con.execute("DELETE FROM tg_actions WHERE created < ?", (D["iso"](D["now"]() - datetime.timedelta(days=KEEP_DAYS * 2)),))
    con.close()


def status():
    return {"enabled": enabled(), "buttons": buttons_on(), **_state}
