"""Kontodeling › Blokeringer (2.4.0) – overtrædelser fra Tracearr samlet pr. kunde.

Tracearrs offentlige API (v2) kan kun LÆSES. Fangarr henter overtrædelserne hvert 15. minut og gemmer dem i
tabellen tc_viol, så siden er hurtig og kan vise mere end Tracearr selv (kunde, din sag og note).
- Hvad hver regel gør (stopper afspilningen / kun besked / test), og om den skal vises, står under
  Kontodeling › Indstillinger. API'en siger ikke selv, hvad en regel gør.
- Kvitterede overtrædelser (i Tracearr) og dem, du har markeret som set her, regnes som afgjort.
- Nye, uafgjorte overtrædelser kommer under "Kræver din handling" og i Stream365 Drift – navn, regel og titel,
  aldrig IP-adresser, telefon eller e-mail.
- Tracearrs bruger kobles til Plex-brugeren via accounts[].external_user_id (= Tautullis user_id), og
  Plex-brugeren til kunden via Kunder › tjenesten Plex.
"""

import datetime
import json
import os
import threading
import time

import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api")
D = {}   # udfyldes af main.py: db, kv_get, kv_set, now, iso, telegram, log

TRACEARR_URL = (os.environ.get("TRACEARR_URL") or "").rstrip("/")
TRACEARR_APIKEY = os.environ.get("TRACEARR_APIKEY") or ""
TRACEARR_LINK = (os.environ.get("TRACEARR_PUBLIC_URL") or "").rstrip("/")

RULES_KEY = "tc_rules"
STATE_KEY = "tc_state"
ACTIONS = ("stopper", "besked", "test")
# Jespers svar 28. nov. 2026. Regler, der ikke står her, vises med "ukendt", til du har valgt.
DEFAULT_RULES = {
    "Tv på flere adresser": {"action": "stopper", "show": True},
    "Betaling": {"action": "stopper", "show": True},
    "Chromecast på flere adresser": {"action": "besked", "show": True},
    "Flere end 6 mobile enheder": {"action": "besked", "show": False},
    "Blokeret: Jesper": {"action": "test", "show": False},
}
SYNC_MINUTES = 15
KEEP_DAYS = 35          # så langt tilbage hentes ved hver synk (kvitteringer i Tracearr opdateres)
FIRST_DAYS = 180        # første gang
MAX_PAGES = 40
_lock = threading.Lock()
_users = {"at": 0.0, "map": {}, "names": {}}


def setup(**deps):
    D.update(deps)


def enabled():
    return bool(TRACEARR_URL and TRACEARR_APIKEY)


def link():
    """Adressen til Tracearr i browseren (TRACEARR_PUBLIC_URL – ellers TRACEARR_URL, hvis den er https)."""
    if TRACEARR_LINK:
        return TRACEARR_LINK
    return TRACEARR_URL if TRACEARR_URL.startswith("https://") else ""


def init():
    con = D["db"]()
    with con:
        con.execute("CREATE TABLE IF NOT EXISTS tc_viol (id TEXT PRIMARY KEY, created TEXT, rule TEXT, rule_id TEXT,"
                    " severity TEXT, acked TEXT, seen TEXT, tr_user TEXT, plex_user INTEGER, username TEXT, title TEXT,"
                    " ip TEXT, evidence TEXT, session_id TEXT)")
        con.execute("CREATE INDEX IF NOT EXISTS tc_viol_created ON tc_viol(created)")
        con.execute("CREATE INDEX IF NOT EXISTS tc_viol_plex ON tc_viol(plex_user)")
    con.close()


# ---------------------------------------------------------------- Tracearr

def tget(path, **params):
    if not enabled():
        raise RuntimeError("Tracearr er ikke sat op (TRACEARR_URL og TRACEARR_APIKEY i fangarr.env)")
    r = httpx.get(f"{TRACEARR_URL}/api/v2/public/{path.lstrip('/')}", params={k: v for k, v in params.items() if v is not None},
                  headers={"Authorization": f"Bearer {TRACEARR_APIKEY}"}, timeout=30, follow_redirects=False)
    if r.status_code >= 400:
        raise RuntimeError(f"Tracearr svarede {r.status_code} på {path}")
    return r.json()


def tpages(path, max_pages=MAX_PAGES, **params):
    out, cur = [], None
    for _ in range(max_pages):
        j = tget(path, pageSize=100, cursor=cur, **params)
        out += j.get("data") or []
        cur = (j.get("meta") or {}).get("nextCursor")
        if not cur:
            break
    return out


def users(refresh=False):
    """{tracearr-id: plex-bruger-id} og {tracearr-id: brugernavn}. Gemmes en time."""
    if not refresh and time.time() - _users["at"] < 3600 and _users["map"]:
        return _users["map"], _users["names"]
    m, names = {}, {}
    for u in tpages("users", max_pages=20, include_removed="true"):
        tid = str(u.get("id") or "")
        if not tid:
            continue
        names[tid] = str(u.get("identity_name") or u.get("username") or "")
        ext = None
        for a in u.get("accounts") or []:
            if isinstance(a, dict) and str(a.get("external_user_id") or "").isdigit():
                ext = int(a["external_user_id"])
                if (a.get("server_type") or "plex") == "plex":
                    break
        if ext is None and str(u.get("plex_account_id") or "").isdigit():
            ext = int(u["plex_account_id"])
        if ext is not None:
            m[tid] = ext
    _users.update(at=time.time(), map=m, names=names)
    return m, names


def tracearr_ids(plex_ids):
    """Tracearr-brugere for en liste Plex-brugere."""
    m, _ = users()
    want = {int(p) for p in plex_ids if p}
    return [tid for tid, p in m.items() if p in want]


def _local(ts):
    """Tracearrs tid (UTC, ...Z) → lokal tid som i resten af Fangarr."""
    try:
        dt = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone().replace(tzinfo=None)
        return D["iso"](dt)
    except (TypeError, ValueError):
        return str(ts or "")[:19]


# ---------------------------------------------------------------- regler

def rules_cfg():
    cfg = {k: dict(v) for k, v in DEFAULT_RULES.items()}
    for k, v in (D["kv_get"](RULES_KEY, {}) or {}).items():
        if isinstance(v, dict):
            cfg[k] = {"action": v.get("action") if v.get("action") in ACTIONS else "", "show": bool(v.get("show", True))}
    return cfg


def rule_info(name):
    c = rules_cfg().get(name)
    return c or {"action": "", "show": True}


def counts_alert(name):
    """Skal en ny overtrædelse af reglen komme under Kræver din handling og i Telegram?"""
    c = rule_info(name)
    return c["show"] and c["action"] != "test"


# ---------------------------------------------------------------- synk

def sync(full=False):
    """Hent overtrædelser fra Tracearr og gem dem. Første gang (og ved full) 180 dage tilbage."""
    with _lock:
        st = D["kv_get"](STATE_KEY, {}) or {}
        first = not st.get("synced")
        days = FIRST_DAYS if (first or full) else KEEP_DAYS
        since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        umap, names = users(refresh=full)
        items = tpages("violations", since=since)
        con = D["db"]()
        with con:
            for v in items:
                data = v.get("data") if isinstance(v.get("data"), dict) else {}
                user = v.get("user") if isinstance(v.get("user"), dict) else {}
                rule = v.get("rule") if isinstance(v.get("rule"), dict) else {}
                tid = str(user.get("id") or "")
                ev = data.get("evidence")
                con.execute(
                    "INSERT INTO tc_viol (id, created, rule, rule_id, severity, acked, seen, tr_user, plex_user, username, title, ip,"
                    " evidence, session_id) VALUES (?,?,?,?,?,?,NULL,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET"
                    " acked=excluded.acked, rule=excluded.rule, plex_user=COALESCE(excluded.plex_user, tc_viol.plex_user),"
                    " username=excluded.username, title=excluded.title",
                    (str(v.get("id")), _local(v.get("created_at")), str(rule.get("name") or data.get("ruleName") or "–"),
                     str(rule.get("id") or ""), str(v.get("severity") or ""), _local(v["acknowledged_at"]) if v.get("acknowledged_at") else None,
                     tid, umap.get(tid), str(user.get("username") or names.get(tid) or ""), str(data.get("mediaTitle") or ""),
                     str(data.get("ipAddress") or ""), json.dumps(ev, ensure_ascii=False)[:3000] if ev else "", str(v.get("session_id") or "")))
        con.close()
        st.update(synced=D["iso"](D["now"]()), error="", count=len(items))
        if first:
            # Alt fra før første synk regnes som kendt – ingen bunke beskeder ved installationen.
            st["alert_from"] = st["synced"]
        D["kv_set"](STATE_KEY, st)
        return len(items)


def _customers():
    """{plex-bruger-id: {id, name}} fra Kunder (tjenesten Plex)."""
    con = D["db"]()
    try:
        rs = con.execute("SELECT s.plex_user_id AS p, c.id AS id, c.name AS name FROM k_services s JOIN k_customers c ON c.id=s.customer_id"
                         " WHERE s.service='plex' AND s.plex_user_id IS NOT NULL").fetchall()
        fr = con.execute("SELECT user_id, friendly_name FROM k_plex").fetchall()
    except Exception:
        return {}, {}
    finally:
        con.close()
    return {int(r["p"]): {"id": r["id"], "name": r["name"]} for r in rs}, {int(r[0]): r[1] for r in fr}


def _rows(days=30, include_hidden=False):
    since = D["iso"](D["now"]() - datetime.timedelta(days=days))
    con = D["db"]()
    try:
        rs = [dict(r) for r in con.execute("SELECT * FROM tc_viol WHERE created>=? ORDER BY created DESC", (since,)).fetchall()]
    finally:
        con.close()
    if include_hidden:
        return rs
    return [r for r in rs if rule_info(r["rule"])["show"]]


def new_open():
    """Uafgjorte overtrædelser efter første synk, på regler der giver besked (til Overblik og Telegram)."""
    st = D["kv_get"](STATE_KEY, {}) or {}
    frm = st.get("alert_from") or ""
    return [r for r in _rows(30) if not r["acked"] and not r["seen"] and r["created"] >= frm and counts_alert(r["rule"])]


def _who(r, cust, plexn):
    c = cust.get(r["plex_user"]) if r["plex_user"] is not None else None
    if c:
        return c["name"]
    return plexn.get(r["plex_user"]) or r["username"] or "ukendt bruger"


def notify():
    """Én samlet besked om overtrædelser, der ikke er sendt besked om før. Kun navn, regel og titel."""
    st = D["kv_get"](STATE_KEY, {}) or {}
    sent = set(st.get("sent") or [])
    new = [r for r in new_open() if r["id"] not in sent]
    if not new:
        return 0
    cust, plexn = _customers()
    lines = []
    for r in new[:10]:
        act = {"stopper": " (stoppet)", "besked": " (kun besked)"}.get(rule_info(r["rule"])["action"], "")
        lines.append(f"• {_who(r, cust, plexn)} – {r['rule']}{act}{' – ' + r['title'] if r['title'] else ''}")
    more = f"\n… og {len(new) - 10} mere" if len(new) > 10 else ""
    D["telegram"](f"🚫 Tracearr: {len(new)} {'ny overtrædelse' if len(new) == 1 else 'nye overtrædelser'}\n" + "\n".join(lines) + more
                  + "\nSe Fangarr › Kontodeling › Blokeringer.")
    st["sent"] = (list(sent) + [r["id"] for r in new])[-2000:]
    D["kv_set"](STATE_KEY, st)
    return len(new)


def tick():
    if not enabled():
        return
    st = D["kv_get"](STATE_KEY, {}) or {}
    last = st.get("tried") or ""
    if last and last > D["iso"](D["now"]() - datetime.timedelta(minutes=SYNC_MINUTES)):
        return
    st["tried"] = D["iso"](D["now"]())
    D["kv_set"](STATE_KEY, st)
    try:
        sync()
        notify()
    except Exception as e:  # noqa: BLE001 – Tracearr nede må ikke stoppe resten af Fangarr
        st = D["kv_get"](STATE_KEY, {}) or {}
        st["error"] = f"{e.__class__.__name__}: {e}"[:300]
        D["kv_set"](STATE_KEY, st)
        D["log"].warning("Blokeringer: kunne ikke hente fra Tracearr: %s", e)


def brief():
    try:
        return {"new": len(new_open())} if enabled() else {}
    except Exception:
        return {}


# ---------------------------------------------------------------- sider

def _evidence(txt):
    try:
        ev = json.loads(txt) if txt else []
    except ValueError:
        return []
    out = []
    for e in ev if isinstance(ev, list) else [ev]:
        if isinstance(e, dict):
            out.append(", ".join(f"{k}: {v}" for k, v in e.items() if not isinstance(v, (dict, list)) and v not in (None, ""))[:300])
        elif e not in (None, ""):
            out.append(str(e)[:300])
    return [x for x in out if x][:8]


def grouped(days=30, rule="", only_open=False, plex_user=None):
    cust, plexn = _customers()
    try:
        from_sharing = D.get("cases", lambda: {})()
    except Exception:
        from_sharing = {}
    groups = {}
    for r in _rows(days):
        if rule and r["rule"] != rule:
            continue
        if plex_user is not None and r["plex_user"] != plex_user:
            continue
        done = bool(r["acked"] or r["seen"])
        if only_open and done:
            continue
        key = str(r["plex_user"]) if r["plex_user"] is not None else "t" + r["tr_user"]
        c = cust.get(r["plex_user"]) if r["plex_user"] is not None else None
        g = groups.setdefault(key, {"key": key, "plex_user": r["plex_user"], "customer_id": c["id"] if c else None,
                                    "name": _who(r, cust, plexn), "username": r["username"], "count": 0, "open": 0,
                                    "last": "", "rules": {}, "items": [],
                                    "case": from_sharing.get(str(r["plex_user"])) if r["plex_user"] is not None else None})
        g["count"] += 1
        g["open"] += 0 if done else 1
        g["last"] = max(g["last"], r["created"])
        g["rules"][r["rule"]] = g["rules"].get(r["rule"], 0) + 1
        if len(g["items"]) < 100:
            g["items"].append({"id": r["id"], "created": r["created"], "rule": r["rule"], "action": rule_info(r["rule"])["action"],
                               "severity": r["severity"], "title": r["title"], "ip": r["ip"], "acked": r["acked"], "seen": r["seen"],
                               "evidence": _evidence(r["evidence"])})
    out = sorted(groups.values(), key=lambda g: g["last"], reverse=True)   # nyeste først …
    out.sort(key=lambda g: g["open"] == 0)                                # … og brugere med uafgjorte øverst
    return out


@router.get("/blokeringer")
def api_list(days: int = 30, rule: str = "", open: int = 0):
    days = min(max(days, 1), 180)
    st = D["kv_get"](STATE_KEY, {}) or {}
    all_rows = _rows(days, include_hidden=True)
    cfg = rules_cfg()
    seen_rules = {}
    for r in all_rows:
        seen_rules[r["rule"]] = seen_rules.get(r["rule"], 0) + 1
    rules = [{"name": n, "count": seen_rules.get(n, 0), **cfg.get(n, {"action": "", "show": True})}
             for n in sorted(set(cfg) | set(seen_rules), key=lambda n: (-seen_rules.get(n, 0), n))]
    return {"enabled": enabled(), "link": link(), "synced": st.get("synced"), "error": st.get("error") or "",
            "days": days, "rules": rules, "groups": grouped(days, rule, bool(open)), "new": len(new_open()) if enabled() else 0}


@router.post("/blokeringer/hent")
def api_refresh():
    if not enabled():
        raise HTTPException(400, "Tracearr er ikke sat op (TRACEARR_URL og TRACEARR_APIKEY i fangarr.env)")
    try:
        n = sync(full=True)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Tracearr svarer ikke: {e}")
    return {"ok": True, "count": n}


@router.put("/blokeringer/set")
async def api_seen(req: Request):
    """Markér overtrædelser som set i Fangarr (Tracearr selv ændres ikke). ids=[...] eller plex_user/key."""
    b = await req.json()
    ids = [str(i) for i in (b.get("ids") or [])][:2000]
    val = None if b.get("undo") else D["iso"](D["now"]())
    con = D["db"]()
    with con:
        if ids:
            con.executemany("UPDATE tc_viol SET seen=? WHERE id=?", [(val, i) for i in ids])
        elif b.get("key"):
            k = str(b["key"])
            if k.startswith("t"):
                con.execute("UPDATE tc_viol SET seen=? WHERE tr_user=? AND plex_user IS NULL", (val, k[1:]))
            else:
                con.execute("UPDATE tc_viol SET seen=? WHERE plex_user=?", (val, int(k)))
        else:
            raise HTTPException(400, "mangler ids eller key")
    con.close()
    return {"ok": True}


@router.put("/blokeringer/regler")
async def api_rules(req: Request):
    b = await req.json()
    cfg = {}
    for r in b.get("rules") or []:
        n = str(r.get("name") or "").strip()[:120]
        if not n:
            continue
        if r.get("action") not in ACTIONS + ("",):
            raise HTTPException(400, f"ukendt handling for {n}")
        cfg[n] = {"action": r.get("action") or "", "show": bool(r.get("show"))}
    D["kv_set"](RULES_KEY, cfg)
    return {"ok": True, "rules": rules_cfg()}
