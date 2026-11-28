"""Sikkerhedstjek (2.3.0) – Drift › Sikkerhed.

Hver uge (og når du trykker "Tjek nu") tjekker Fangarr to ting – og ændrer intet:

1. Adresserne udefra: alle apps i Apps-listen (Uptime Kumas statusside + dine egne apps) skal sende dig til
   Authelia-login (svar 30x til login.<domæne>), og deres /api skal også gøre det (eller give 404, dvs. findes ikke).
   Apps, kunderne skal kunne nå (Plex, Seerr, guiden …), og apps med en bevidst åben /api (Tracearr, Tautulli …)
   står i to lister med undtagelser, som du kan rette på siden. Widgetten skal afvise en forkert nøgle med 404.
2. Portene: Fangarr prøver at forbinde til alle TCP-porte på begge servers offentlige adresser og sammenligner
   med listen over porte, der skal være åbne. En ny åben port er et fund. UDP kan ikke tjekkes på den måde.

Besked i Stream365 Drift kun ved nye fund og "i orden igen" – ikke ved hver kørsel.
"""

import asyncio
import re
import threading
import time

import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api")
D = {}   # udfyldes af main.py: apps, kv_get, kv_set, now, iso, telegram, log

CFG_KEY, RES_KEY, ALARM_KEY = "sik_cfg", "sik_result", "sik_alarm"
DEFAULT = {
    "hosts": "feeder 65.21.142.239 22,80,443,56881\nmediabox 37.27.105.61 22,80,443",
    "ports": "1-65535",
    "public": "plex, seerr, login, guide, nyt, app, proeve",
    "open_api": "tracearr, tautulli, autoscan",
    "weekday": 0, "hour": 3,          # mandag kl. 3 (lokal tid)
}
CONCURRENCY = 300
PORT_TIMEOUT = 1.5
_lock = threading.Lock()
_running = {"v": False}


def setup(**deps):
    D.update(deps)


def _keys(text):
    return [k for k in (D["apps"].key(x) for x in re.split(r"[,\s]+", str(text or ""))) if k]


def parse_ports(text):
    out = set()
    for part in re.split(r"[,\s]+", str(text or "").strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise ValueError(f"forstår ikke porten \"{part}\"")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if not (1 <= a <= b <= 65535):
            raise ValueError(f"porten \"{part}\" skal ligge mellem 1 og 65535")
        out.update(range(a, b + 1))
    return out


def parse_hosts(text):
    hosts = []
    for line in str(text or "").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 2 or not re.fullmatch(r"[0-9a-fA-F.:]+", parts[1]):
            raise ValueError(f"linjen \"{line}\" skal være: navn adresse porte")
        hosts.append({"name": parts[0][:30], "ip": parts[1], "expected": sorted(parse_ports(parts[2] if len(parts) > 2 else ""))})
    return hosts


def get_cfg():
    c = dict(DEFAULT)
    c.update(D["kv_get"](CFG_KEY, {}) or {})
    return c


# ---------------------------------------------------------------- adresser

def _to_login(r):
    loc = r.headers.get("location") or ""
    return 300 <= r.status_code < 400 and "login." in loc.lower()


def check_url(client, url, kind):
    """kind: 'side' (skal kræve login), 'api' (login eller 404), 'widget' (skal give 404).
    Returnerer (status, tekst): status er ok / fund / ingen-svar."""
    try:
        r = client.get(url)
    except httpx.HTTPError as e:
        return "ingen-svar", f"svarer ikke ({e.__class__.__name__})"
    code = r.status_code
    if kind == "widget":
        return ("ok", "404 – forkert nøgle afvises") if code == 404 else ("fund", f"svarer {code} på en forkert nøgle (skal være 404)")
    if _to_login(r):
        return "ok", f"{code} → login"
    if kind == "api" and code == 404:
        return "ok", "404 – findes ikke"
    if 300 <= code < 400:
        return "fund", f"{code} → {r.headers.get('location', '')[:80]} (ikke Authelia)"
    return "fund", f"svarer {code} uden login"


def url_targets(cfg):
    """[(nøgle, navn, adresse)] for alle https-apps i Apps-listen."""
    a = D["apps"]
    out, seen = [], set()
    if a.enabled() or a.get_config()["extra"]:
        for g in a.build(None)["groups"]:
            for x in g["apps"]:
                u = (x.get("url") or "").strip()
                k = a.key(x["name"])
                if not u.startswith("https://") or k in seen:
                    continue
                seen.add(k)
                out.append((k, x["name"], u))
    return out


def check_urls(cfg):
    public, open_api = set(_keys(cfg["public"])), set(_keys(cfg["open_api"]))
    rows = []
    with httpx.Client(timeout=10, follow_redirects=False, verify=True) as client:
        for k, name, url in url_targets(cfg):
            m = re.match(r"(https://[^/]+)", url)
            base = m.group(1)
            if k in public:
                rows.append({"app": name, "url": url, "check": "side", "status": "undtaget", "text": "må være åben (kunderne bruger den)"})
            else:
                st, txt = check_url(client, url, "side")
                rows.append({"app": name, "url": url, "check": "side", "status": st, "text": txt})
            api = base + "/api/"
            if k in open_api:
                rows.append({"app": name, "url": api, "check": "api", "status": "undtaget", "text": "bevidst åben /api"})
            elif k not in public:
                st, txt = check_url(client, api, "api")
                rows.append({"app": name, "url": api, "check": "api", "status": st, "text": txt})
        dom = D["apps"].domain()
        if dom and D["apps"].widget_enabled():
            u = f"https://fangarr.{dom}/widget/forkert"
            st, txt = check_url(client, u, "widget")
            rows.append({"app": "Fangarr (widget)", "url": u, "check": "widget", "status": st, "text": txt})
    return rows


# ---------------------------------------------------------------- porte

async def _scan(ip, ports):
    sem = asyncio.Semaphore(CONCURRENCY)
    found = []

    async def one(p):
        async with sem:
            try:
                _, w = await asyncio.wait_for(asyncio.open_connection(ip, p), PORT_TIMEOUT)
                found.append(p)
                w.close()
                try:
                    await w.wait_closed()
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001 – lukket, filtreret eller ingen svar
                pass

    await asyncio.gather(*(one(p) for p in ports))
    return sorted(found)


def check_ports(cfg):
    ports = sorted(parse_ports(cfg["ports"]))
    out = []
    for h in parse_hosts(cfg["hosts"]):
        scan = sorted(set(ports) | set(h["expected"]))
        t0 = time.time()
        opened = asyncio.run(_scan(h["ip"], scan))
        exp = set(h["expected"])
        out.append({"name": h["name"], "ip": h["ip"], "open": opened, "expected": h["expected"],
                    "unexpected": [p for p in opened if p not in exp],
                    "closed": [p for p in h["expected"] if p not in opened],
                    "reachable": bool(opened), "scanned": len(scan), "seconds": round(time.time() - t0, 1)})
    return out


# ---------------------------------------------------------------- kørsel og beskeder

def findings(res):
    """Fund, der giver besked (nøgle, tekst)."""
    out = []
    for r in res.get("urls") or []:
        if r["status"] == "fund":
            out.append((f"url|{r['url']}", f"{r['app']}: {r['url']} – {r['text']}"))
    for h in res.get("hosts") or []:
        for p in h["unexpected"]:
            out.append((f"port|{h['ip']}|{p}", f"{h['name']}: port {p} er åben udefra (står ikke på listen)"))
    return out


def notify(res):
    f = findings(res)
    now_keys = sorted(k for k, _ in f)
    prev = D["kv_get"](ALARM_KEY, []) or []
    new = [t for k, t in f if k not in prev]
    if new:
        lines = "\n".join(f"• {t}" for _, t in f[:15]) + (f"\n… og {len(f) - 15} mere" if len(f) > 15 else "")
        D["telegram"](f"🔐 Fangarr – sikkerhedstjek: {len(f)} fund\n\n{lines}\n\n"
                      "Se Fangarr › Drift › Sikkerhed. Fangarr har ikke ændret noget.")
    elif prev and not f:
        D["telegram"]("✅ Fangarr – sikkerhedstjekket er i orden igen (ingen åbne adresser eller nye porte).")
    D["kv_set"](ALARM_KEY, now_keys)


def run(manual=False):
    with _lock:
        if _running["v"]:
            return False
        _running["v"] = True
    started = D["iso"](D["now"]())
    D["kv_set"](RES_KEY, {**(D["kv_get"](RES_KEY, {}) or {}), "running": True, "started": started})
    try:
        cfg = get_cfg()
        res = {"started": started, "manual": manual, "urls": [], "hosts": [], "errors": []}
        try:
            res["urls"] = check_urls(cfg)
        except Exception as e:  # noqa: BLE001
            res["errors"].append(f"adresser: {e}")
        try:
            res["hosts"] = check_ports(cfg)
        except Exception as e:  # noqa: BLE001
            res["errors"].append(f"porte: {e}")
        res["finished"] = D["iso"](D["now"]())
        res["running"] = False
        res["findings"] = len(findings(res))
        D["kv_set"](RES_KEY, res)
        notify(res)
        D["log"].info("Sikkerhedstjek: %s fund", res["findings"])
        return True
    finally:
        _running["v"] = False


def start(manual=False):
    threading.Thread(target=run, kwargs={"manual": manual}, daemon=True).start()


def tick():
    cfg = get_cfg()
    n = D["now"]()
    if n.weekday() != int(cfg["weekday"]) or n.hour != int(cfg["hour"]):
        return
    last = (D["kv_get"](RES_KEY, {}) or {}).get("started") or ""
    if last[:10] == n.date().isoformat() or _running["v"]:
        return
    start()


# ---------------------------------------------------------------- adresser i Fangarr

@router.get("/sikkerhed")
def get_state():
    res = D["kv_get"](RES_KEY, {}) or {}
    res["running"] = _running["v"]
    cfg = get_cfg()
    return {"result": res, "config": {k: cfg[k] for k in ("hosts", "ports", "public", "open_api")}, "alarm": len(D["kv_get"](ALARM_KEY, []) or [])}


@router.post("/sikkerhed/tjek")
def tjek():
    if _running["v"]:
        raise HTTPException(409, "Tjekket kører allerede")
    start(manual=True)
    return {"ok": True}


@router.put("/sikkerhed/indst")
async def save(req: Request):
    b = await req.json()
    c = get_cfg()
    try:
        hosts = str(b.get("hosts", c["hosts"]))[:2000]
        parse_hosts(hosts)
        ports = str(b.get("ports", c["ports"]))[:500]
        if not parse_ports(ports):
            raise ValueError("vælg mindst én port at tjekke")
    except ValueError as e:
        raise HTTPException(400, str(e))
    c.update(hosts=hosts, ports=ports, public=str(b.get("public", c["public"]))[:1000],
             open_api=str(b.get("open_api", c["open_api"]))[:1000])
    D["kv_set"](CFG_KEY, {k: c[k] for k in ("hosts", "ports", "public", "open_api", "weekday", "hour")})
    return {"ok": True}
