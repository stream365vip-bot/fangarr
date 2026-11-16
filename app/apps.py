"""Apps (Fangarr 1.20.0) – alle dine server-apps med lampe på forsiden og i en widget på telefonen.

Listen kommer fra en statusside i Uptime Kuma (standard: `apps`). Grupperne og rækkefølgen på statussiden er
grupperne og rækkefølgen her. En ny app: opret monitoren i Uptime Kuma og læg den på statussiden – så dukker
den selv op. Fangarr ændrer intet i Uptime Kuma og sender ingen beskeder herfra (det gør Uptime Kuma selv).

To adresser:
- `/api/apps` – til Fangarrs egen forside. Ligger bag Authelia som resten af Fangarr.
- `/widget/<nøgle>` – til widgetten på telefonen. Den ENESTE adresse i Fangarr, der må åbnes uden om Authelia
  (én ekstra Traefik-regel, se LÆSMIG). Viser kun appnavn, gruppe, oppe/nede og appens adresse – ingen kunder,
  ingen tal, og den kan ikke ændre noget. Uden WIDGET_KEY i fangarr.env findes adressen ikke (404).

Appens adresse gættes ud fra monitorens navn: "WUD feeder" → https://wud-feeder.<domæne>. Passer gættet ikke,
rettes det under Indstillinger › Apps og widget. Apps uden monitor (fx Uptime Kuma selv) kan tilføjes samme sted;
de får et felt uden lampe, som bare åbner appen.
"""
import hmac
import os
import re
import threading
import time

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter()
D = {}   # udfyldes af main.py: kv_get, kv_set, now, log

UPTIME_URL = (os.environ.get("UPTIME_URL") or "").rstrip("/")            # fx http://uptime:3001 (internt på feeder)
UPTIME_SLUG = (os.environ.get("UPTIME_APPS_SLUG") or "apps").strip()      # statussiden i Uptime Kuma
WIDGET_KEY = (os.environ.get("WIDGET_KEY") or "").strip()                 # lang hemmelig nøgle til /widget/<nøgle>
APPS_DOMAIN = (os.environ.get("APPS_DOMAIN") or "").strip().strip(".")    # fx stream365.vip (ellers gættes det)
KEY_MIN = 32          # kortere nøgler afvises – så er adressen slået fra
TTL = 30              # sekunder: så tit spørges Uptime Kuma højst
CONFIG_KEY = "apps_config"

# Uptime Kumas tal for seneste tjek → tilstand. "pending" = et tjek er fejlet, og Uptime Kuma prøver igen.
_STATE = {0: "down", 1: "up", 2: "pending", 3: "maint"}
COLORS = {"up": "#58D9AE", "down": "#F27D77", "pending": "#E8B84A", "maint": "#8AB8F2",
          "unknown": "#9BA3AE", "none": "#9BA3AE"}
LABELS = {"up": "Oppe", "down": "Nede", "pending": "Tjekker", "maint": "Vedligehold",
          "unknown": "Ukendt", "none": ""}

_lock = threading.Lock()
_cache = {"at": 0.0, "data": None}      # seneste svar fra Uptime Kuma
_last_good = {"groups": None}           # seneste liste, der kunne hentes – bruges, når Uptime Kuma ikke svarer
_fails = {"since": 0.0, "n": 0}         # forkerte nøgler det seneste minut


def setup(**deps):
    D.update(deps)


def enabled():
    return bool(UPTIME_URL)


def widget_enabled():
    return enabled() and len(WIDGET_KEY) >= KEY_MIN


def key(name):
    """Navn → nøgle til sammenligning: "WUD feeder" og "wud-feeder" er det samme."""
    return re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")


# ---------------------------------------------------------------- indstillinger (gemmes i databasen)

def _clean_url(u):
    u = str(u or "").strip()
    return u if re.fullmatch(r"https?://[^\s\"'<>]{3,300}", u) else ""


def get_config():
    c = D["kv_get"](CONFIG_KEY, None) or {}
    links = {key(k): _clean_url(v) for k, v in (c.get("links") or {}).items()}
    extra = []
    for e in c.get("extra") or []:
        n, u = str(e.get("name") or "").strip()[:40], _clean_url(e.get("url"))
        if n and u:
            extra.append({"group": str(e.get("group") or "").strip()[:40], "name": n, "url": u})
    return {"links": {k: v for k, v in links.items() if k and v}, "extra": extra}


def config_text(c):
    """Indstillingerne som de to tekstfelter i Indstillinger."""
    return {"links": "\n".join(f"{k} = {v}" for k, v in c["links"].items()),
            "extra": "\n".join(f"{e['group']} | {e['name']} | {e['url']}" for e in c["extra"])}


def parse_config(links_text, extra_text):
    """Tekstfelterne → indstillinger. Returnerer (indstillinger, fejl-linjer)."""
    links, extra, bad = {}, [], []
    for line in str(links_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        n, sep, u = line.partition("=")
        if sep and key(n) and _clean_url(u):
            links[key(n)] = _clean_url(u)
        else:
            bad.append(line)
    for line in str(extra_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 3 and parts[1] and _clean_url(parts[2]):
            extra.append({"group": parts[0][:40], "name": parts[1][:40], "url": _clean_url(parts[2])})
        else:
            bad.append(line)
    return {"links": links, "extra": extra[:40]}, bad


# ---------------------------------------------------------------- hent fra Uptime Kuma

def _fetch():
    """Statussiden fra Uptime Kuma: grupper med navn og seneste tilstand for hver monitor."""
    base = f"{UPTIME_URL}/api/status-page"
    page = httpx.get(f"{base}/{UPTIME_SLUG}", timeout=8)
    page.raise_for_status()
    beats = httpx.get(f"{base}/heartbeat/{UPTIME_SLUG}", timeout=8)
    beats.raise_for_status()
    p, b = page.json(), beats.json()
    hb, up = b.get("heartbeatList") or {}, b.get("uptimeList") or {}
    groups = []
    for g in p.get("publicGroupList") or []:
        apps = []
        for m in g.get("monitorList") or []:
            mid = str(m.get("id"))
            last = hb.get(mid) or hb.get(m.get("id")) or []
            last = last[-1] if last else {}
            u = up.get(f"{mid}_24")
            apps.append({"name": str(m.get("name") or "").strip(),
                         "state": _STATE.get(last.get("status"), "unknown"),
                         "uptime": round(float(u) * 100, 2) if isinstance(u, (int, float)) else None})
        groups.append({"name": str(g.get("name") or "").strip(), "apps": apps})
    return groups


def _groups():
    """(grupper, fejl). Svaret gemmes i TTL sekunder. Svarer Uptime Kuma ikke, bruges den seneste liste
    med tilstanden "ukendt", så felterne bliver stående i widgetten."""
    with _lock:
        if _cache["data"] is not None and time.time() - _cache["at"] < TTL:
            return _cache["data"]
    try:
        groups, err = _fetch(), ""
        _last_good["groups"] = groups
    except Exception as e:  # noqa: BLE001 – enhver fejl her betyder bare "Uptime Kuma svarer ikke"
        err = f"Uptime Kuma svarer ikke ({e.__class__.__name__})"
        if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 404:
            err = f"Statussiden \"{UPTIME_SLUG}\" findes ikke i Uptime Kuma"
        old = _last_good["groups"] or []
        groups = [{"name": g["name"], "apps": [dict(a, state="unknown") for a in g["apps"]]} for g in old]
        if D.get("log"):
            D["log"].warning("Apps: %s", err)
    data = (groups, err)
    with _lock:
        _cache.update(at=time.time(), data=data)
    return data


def _domain(req):
    """Domænet, apps ligger på: APPS_DOMAIN – ellers Fangarrs egen adresse uden første led."""
    if APPS_DOMAIN:
        return APPS_DOMAIN
    host = (req.headers.get("x-forwarded-host") or req.headers.get("host") or "").split(",")[0].strip().split(":")[0]
    parts = host.split(".")
    return ".".join(parts[1:]) if len(parts) > 2 and not host.replace(".", "").isdigit() else ""


def build(req):
    """Den samlede liste: Uptime Kumas grupper + egne apps uden monitor, med adresse på hver."""
    if not enabled():
        return {"enabled": False, "ok": False, "error": "", "groups": [], "down": [], "total": 0}
    groups, err = _groups()
    cfg, dom = get_config(), _domain(req)
    out = []
    for g in groups:
        apps = []
        for a in g["apps"]:
            k = key(a["name"])
            url = cfg["links"].get(k) or (f"https://{k}.{dom}" if dom and k else "")
            apps.append({"name": a["name"], "state": a["state"], "uptime": a["uptime"], "url": url})
        out.append({"name": g["name"], "apps": apps})
    for e in cfg["extra"]:
        target = next((g for g in out if key(g["name"]) == key(e["group"])), None)
        if target is None:
            target = {"name": e["group"] or "Andre", "apps": []}
            out.append(target)
        if not any(key(a["name"]) == key(e["name"]) for a in target["apps"]):
            target["apps"].append({"name": e["name"], "state": "none", "uptime": None, "url": e["url"]})
    down = [a["name"] for g in out for a in g["apps"] if a["state"] == "down"]
    return {"enabled": True, "ok": not err, "error": err, "groups": out, "down": down,
            "total": sum(len(g["apps"]) for g in out)}


# ---------------------------------------------------------------- adresser

@router.get("/api/apps")
def api_apps(req: Request, refresh: int = 0):
    """Til forsiden i Fangarr (bag Authelia)."""
    if refresh:
        with _lock:
            _cache["data"] = None
    d = build(req)
    d["widget"] = widget_enabled()
    d["slug"] = UPTIME_SLUG
    return d


@router.get("/api/apps/config")
def api_config():
    return dict(config_text(get_config()), widget=widget_enabled(), enabled=enabled(), slug=UPTIME_SLUG)


@router.put("/api/apps/config")
async def api_config_put(req: Request):
    body = await req.json()
    cfg, bad = parse_config(body.get("links"), body.get("extra"))
    if bad:
        raise HTTPException(400, "Kan ikke læse: " + " · ".join(b[:60] for b in bad[:3])
                            + ". Adresser: Navn = https://…  Apps uden lampe: Gruppe | Navn | https://…")
    D["kv_set"](CONFIG_KEY, cfg)
    return dict(config_text(get_config()), widget=widget_enabled(), enabled=enabled(), slug=UPTIME_SLUG)


def _key_ok(given):
    """Sammenlign nøglen uden at afsløre noget via svartiden. For mange forkerte forsøg lukker i et minut."""
    t = time.time()
    with _lock:
        if t - _fails["since"] > 60:
            _fails.update(since=t, n=0)
        if _fails["n"] >= 20:
            raise HTTPException(429, "For mange forsøg – prøv igen om et minut")
    ok = widget_enabled() and hmac.compare_digest(str(given).encode(), WIDGET_KEY.encode())
    if not ok:
        with _lock:
            _fails["n"] += 1
    return ok


TILE = {"down": "#FF3A1C1B"}     # feltets baggrund i widgetten (AARRGGBB); alle andre tilstande: TILE_BG
TILE_BG, CLEAR = "#FF1A1D23", "#00000000"
PAD_MAX = 60
# Gruppens farve i widgetten: (mærkets baggrund, mærkets tekst). Gruppe nr. 7 begynder forfra.
GROUP_COLORS = [("#FF085041", "#FF9FE1CB"), ("#FF3C3489", "#FFCECBF6"), ("#FF712B13", "#FFF5C4B3"),
                ("#FF0C447C", "#FFB5D4F4"), ("#FF72243E", "#FFF4C0D1"), ("#FF633806", "#FFFAC775")]
EMPTY = {"n": "", "g": "", "h": "", "i": "", "s": "none", "t": "", "c": CLEAR, "b": CLEAR, "k": CLEAR, "kt": CLEAR, "u": ""}


def initials(name):
    """To bogstaver til appens mærke: "Sonarr2" → "So", "WUD feeder" → "Wf", "Qbit-manage" → "Qm"."""
    words = [w for w in re.split(r"[^0-9A-Za-zÆØÅæøå]+", str(name or "")) if w]
    if not words:
        return ""
    two = words[0][0] + words[1][0] if len(words) > 1 else words[0][:2]
    return two[0].upper() + two[1:].lower()


@router.get("/widget/{given}")
def widget(given: str, req: Request, pad: int = 0, cols: int = 0):
    """Til widgetten på telefonen. Flad liste, så KWGT kan slå felt nr. N op: .apps[N].n / .s / .c / .u
    `h` er gruppens navn på gruppens første app (ellers tom), `b` feltets baggrundsfarve, `i` to bogstaver til
    appens mærke og `k`/`kt` gruppens farve (mærkets baggrund og tekst).
    Med ?cols=4 begynder hver gruppe på en ny række (gruppen fyldes op med tomme felter til et helt antal rækker).
    Med ?pad=32 fyldes hele listen op til 32 med tomme, gennemsigtige felter, så en widget med et fast antal
    felter aldrig slår op uden for listen."""
    if not _key_ok(given):
        raise HTTPException(404, "Not Found")     # samme svar, uanset om adressen er slået fra eller nøglen er forkert
    d = build(req)
    cols = min(max(cols, 0), 12)
    apps = []
    for gi, g in enumerate(d["groups"]):
        k, kt = GROUP_COLORS[gi % len(GROUP_COLORS)]
        for i, a in enumerate(g["apps"]):
            apps.append({"n": a["name"], "g": g["name"], "h": g["name"] if i == 0 else "", "i": initials(a["name"]),
                         "s": a["state"], "t": LABELS[a["state"]], "c": COLORS[a["state"]],
                         "b": TILE.get(a["state"], TILE_BG), "k": k, "kt": kt, "u": a["url"]})
        while cols and len(apps) % cols:
            apps.append(dict(EMPTY))
    while len(apps) < min(max(pad, 0), PAD_MAX):
        apps.append(dict(EMPTY))
    n_down = len(d["down"])
    if not d["ok"]:
        head = d["error"] or "Ingen status"
    elif n_down:
        head = (f"{d['down'][0]} er nede" if n_down == 1 else f"{n_down} apps er nede")
    else:
        head = "Alt kører"
    body = {"ok": d["ok"], "at": D["now"]().strftime("%H:%M"), "head": head,
            "headc": COLORS["unknown" if not d["ok"] else ("down" if n_down else "up")],
            "down": n_down, "total": d["total"], "apps": apps,
            "groups": [{"n": g["name"], "count": len(g["apps"])} for g in d["groups"]]}
    return JSONResponse(body, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})
