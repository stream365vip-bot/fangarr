"""nyt-login – viser en statisk side (nyhedsbrevet), men kun for Plex-konti med adgang til Stream365-serveren.

Sådan virker det (samme metode som login i Seerr):
1. Brugeren trykker "Log ind med Plex". Appen beder plex.tv om en engangskode (PIN) og sender brugeren til Plex.
2. Plex sender brugeren tilbage. Appen henter brugerens nøgle hos plex.tv og spørger, hvilke servere kontoen har adgang til.
3. Er Stream365-serveren på listen, får brugeren en cookie (underskrevet, gælder SESSION_DAYS dage) og ser siden.
Brugerens kodeord ses aldrig, og brugerens Plex-nøgle gemmes ikke – den bruges kun til det ene opslag.
"""

import base64
import datetime
import hashlib
import hmac
import html
import json
import logging
import mimetypes
import os
import re
import secrets
import threading
import time
import urllib.parse
import uuid
import xml.etree.ElementTree as ET

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

SITE_DIR = os.path.realpath(os.environ.get("SITE_DIR", "/site"))
DATA_DIR = os.environ.get("DATA_DIR", "/config")
PUBLIC_URL = (os.environ.get("PUBLIC_URL") or "https://nyt.stream365.vip").rstrip("/")
PLEX_URL = (os.environ.get("PLEX_URL") or "https://plex.stream365.vip").rstrip("/")
PLEXTV_URL = (os.environ.get("PLEXTV_URL") or "https://plex.tv").rstrip("/")
PLEX_AUTH_URL = os.environ.get("PLEX_AUTH_URL") or "https://app.plex.tv/auth"
MACHINE_ID = (os.environ.get("PLEX_MACHINE_ID") or "").strip()
PRODUCT = os.environ.get("PRODUCT_NAME") or "Stream365"
SESSION_DAYS = int(os.environ.get("SESSION_DAYS") or "90")
CONTACT = os.environ.get("CONTACT_TEXT") or "Skriv til Stream365, hvis du mener, det er en fejl."
OLD_HOSTS = {h.strip().lower() for h in (os.environ.get("OLD_HOSTS") or "").split(",") if h.strip()}   # gamle adresser, der sendes videre
UPTIME_URL = (os.environ.get("UPTIME_URL") or "").rstrip("/")             # fx http://uptime:3001 (Uptime Kuma internt på feeder)
UPTIME_SLUG = (os.environ.get("UPTIME_SLUG") or "kunder").strip()          # statussiden i Uptime Kuma
# Tekst vist under en monitor, fx adressen kunderne kan skrive af: "IPTV 1=http://…;IPTV 2=http://…"
STATUS_LINKS = {k.strip().lower(): v.strip() for k, _, v in
                (x.partition("=") for x in (os.environ.get("STATUS_LINKS") or "").split(";")) if k.strip() and v.strip()}
RULES_FILE = os.path.join(SITE_DIR, "_regler.json")      # regler + spørgsmål ved første login (ligger sammen med siden)
ACCEPT_FILE = os.path.join(DATA_DIR, "accepteret.json")  # hvem har accepteret reglerne, og hvornår
COOKIE, PIN_COOKIE = "s365_nyt", "s365_pin"
SECURE = PUBLIC_URL.startswith("https://")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("nyt-login")
logging.getLogger("httpx").setLevel(logging.WARNING)   # httpx skriver adresser i loggen – vis kun advarsler

app = FastAPI(title="nyt-login", docs_url=None, redoc_url=None, openapi_url=None)


def _stored(name, make):
    """En værdi, der laves én gang og gemmes i DATA_DIR (hemmelig nøgle, appens id hos Plex)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, name)
    try:
        with open(path) as f:
            val = f.read().strip()
        if val:
            return val
    except OSError:
        pass
    val = make()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(val)
    return val


SECRET = _stored("secret", lambda: secrets.token_hex(32)).encode()   # slet filen = alle logges ud
CLIENT_ID = _stored("client_id", lambda: "stream365-nyt-" + uuid.uuid4().hex)
_machine = {"id": MACHINE_ID, "ts": 0.0}


def plex_headers(token=None):
    h = {"Accept": "application/json", "X-Plex-Product": PRODUCT, "X-Plex-Client-Identifier": CLIENT_ID,
         "X-Plex-Device-Name": "Stream365 nyhedsbrev"}
    if token:
        h["X-Plex-Token"] = token
    return h


def machine_id():
    """Serverens id hos Plex. Sættes med PLEX_MACHINE_ID eller hentes fra PLEX_URL/identity (kræver ingen nøgle)."""
    if _machine["id"]:
        return _machine["id"]
    if time.time() - _machine["ts"] < 30:
        return ""
    _machine["ts"] = time.time()
    try:
        r = httpx.get(PLEX_URL + "/identity", timeout=10)
        r.raise_for_status()
        _machine["id"] = ET.fromstring(r.text).get("machineIdentifier") or ""
        log.info("Plex-serverens id er hentet fra %s", PLEX_URL)
    except Exception as e:
        log.warning("Kunne ikke hente serverens id fra %s/identity: %s", PLEX_URL, e.__class__.__name__)
    return _machine["id"]


def sign(value):
    return hmac.new(SECRET, value.encode(), hashlib.sha256).hexdigest()


def make_cookie(value, seconds):
    body = f"{value}.{int(time.time()) + seconds}"
    return f"{body}.{sign(body)}"


def read_cookie(raw):
    """Returnerer værdien, hvis underskriften passer, og cookien ikke er udløbet. Ellers None."""
    try:
        value, exp, sig = str(raw or "").rsplit(".", 2)
        if hmac.compare_digest(sig, sign(f"{value}.{exp}")) and int(exp) > time.time():
            return value
    except ValueError:
        pass
    return None


def session(req: Request):
    """Den indloggede bruger som (plex-id, brugernavn) – eller None."""
    val = read_cookie(req.cookies.get(COOKIE))
    if val is None:
        return None
    uid, _, name = val.partition(":")
    try:
        name = base64.urlsafe_b64decode(name.encode()).decode() if name else ""
    except Exception:
        name = ""
    return uid, name


def logged_in(req: Request):
    return session(req) is not None


# ---------------------------------------------------------------- regler ved første login
_rules = {"mtime": 0.0, "data": None}
_accept_lock = threading.Lock()


def rules():
    """Reglerne og spørgsmålene fra _regler.json. Findes filen ikke (eller er den forkert), spørges der ikke."""
    try:
        m = os.path.getmtime(RULES_FILE)
    except OSError:
        return None
    if m != _rules["mtime"]:
        _rules["mtime"] = m
        try:
            with open(RULES_FILE, encoding="utf-8") as f:
                d = json.load(f)
            qs = d.get("questions") or []
            ok = bool(d.get("rules")) and all(isinstance(q.get("options"), list) and 0 <= int(q.get("correct", -1)) < len(q["options"]) for q in qs)
            _rules["data"] = d if ok else None
            if not ok:
                log.warning("_regler.json er ikke gyldig – reglerne vises ikke")
        except Exception as e:
            _rules["data"] = None
            log.warning("_regler.json kunne ikke læses (%s) – reglerne vises ikke", e.__class__.__name__)
    return _rules["data"]


def _accepted_all():
    try:
        with open(ACCEPT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def has_accepted(uid):
    r = rules()
    if not r:
        return True
    with _accept_lock:
        a = _accepted_all().get(str(uid))
    return bool(a) and int(a.get("version") or 0) >= int(r.get("version") or 1)


def save_accept(uid, name):
    r = rules() or {}
    with _accept_lock:
        d = _accepted_all()
        d[str(uid)] = {"user": name, "version": int(r.get("version") or 1),
                       "at": datetime.datetime.now().isoformat(timespec="seconds")}
        tmp = ACCEPT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, ACCEPT_FILE)
    log.info("Reglerne (version %s) er accepteret af Plex-kontoen %s", r.get("version") or 1, name or uid)


def safe_next(path):
    """Kun stier på denne side (ikke adresser til andre sider)."""
    path = str(path or "/")
    return path if re.fullmatch(r"/[A-Za-z0-9_\-./%]*", path) and not path.startswith("//") else "/"


PAGE = """<!doctype html>
<html lang="da"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><meta name="theme-color" content="#0B0C0E">
<title>Nyt på Stream365 – log ind</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0B0C0E;color:#ECEEF1;
font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:24px}
main{width:100%;max-width:420px;background:#121418;border:1px solid #262A32;border-radius:18px;padding:32px 28px;text-align:center}
.logo{width:48px;height:48px;border-radius:14px;background:#58D9AE;color:#06231A;display:grid;place-items:center;font-weight:700;font-size:20px;margin:0 auto 18px}
h1{font-size:24px;line-height:1.25;margin:0 0 8px}p{color:#9BA3AE;margin:0 0 22px}
a.btn,button.btn{display:flex;align-items:center;justify-content:center;width:100%;min-height:50px;border-radius:12px;border:0;background:#58D9AE;color:#06231A;
font:inherit;font-weight:700;cursor:pointer;text-decoration:none}
a.btn:hover,button.btn:hover{background:#6FE2BC}a.btn:focus-visible,button.btn:focus-visible{outline:2px solid #ECEEF1;outline-offset:3px}
.small{font-size:13.5px;margin:18px 0 0}.err{color:#F27D77}
main.wide{max-width:640px;text-align:left;padding:28px 24px}main.wide .logo{margin:0 0 16px}
.eyebrow{font-size:12.5px;letter-spacing:.14em;text-transform:uppercase;color:#58D9AE;font-weight:700;margin:0 0 6px}
ol.r{list-style:none;margin:0 0 22px;padding:0;border:1px solid #262A32;border-radius:14px;overflow:hidden}
ol.r li{display:grid;grid-template-columns:36px minmax(0,1fr);gap:12px;padding:14px 16px;border-bottom:1px solid #262A32}
ol.r li:last-child{border-bottom:0}ol.r b{display:block;color:#ECEEF1}ol.r span.t{color:#C9CFCD;font-size:15px}
ol.r i{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;border:1.5px solid #58D9AE;color:#58D9AE;font:700 14px/1 system-ui;font-style:normal}
h2{font-size:19px;margin:0 0 4px}fieldset{border:1px solid #262A32;border-radius:14px;margin:0 0 12px;padding:14px 16px}
fieldset.bad{border-color:#F27D77}legend{font-weight:700;padding:0 6px}
label.o{display:flex;gap:10px;align-items:flex-start;padding:9px 4px;min-height:44px;cursor:pointer;color:#D5D9DF}
label.o input{width:20px;height:20px;margin-top:2px;accent-color:#58D9AE;flex:none}
.note{background:#3A1C1B;border:1px solid #5A2A28;color:#FFC1BD;border-radius:12px;padding:12px 14px;margin:0 0 14px}
</style></head><body><main>
<div class="logo" aria-hidden="true">365</div>
__BODY__
</main></body></html>"""


def rules_page(req_path, name="", wrong=None, chosen=None):
    """Reglerne som det første, brugeren møder – og tre spørgsmål, der skal besvares rigtigt."""
    r, e = rules(), html.escape
    wrong, chosen = wrong or set(), chosen or {}
    items = "".join(f'<li><i>{n}</i><div><b>{e(str(x.get("title") or ""))}</b><span class="t">{e(str(x.get("text") or ""))}</span></div></li>'
                    for n, x in enumerate(r["rules"], 1))
    qs = ""
    for i, q in enumerate(r.get("questions") or []):
        opts = "".join(f'<label class="o"><input type="radio" name="q{i}" value="{j}" required{" checked" if chosen.get(i) == j and i not in wrong else ""}> <span>{e(str(o))}</span></label>'
                       for j, o in enumerate(q["options"]))
        qs += f'<fieldset class="{"bad" if i in wrong else ""}"><legend>{i + 1}. {e(str(q.get("q") or ""))}</legend>{opts}</fieldset>'
    note = ('<p class="note" role="alert">Et eller flere svar passer ikke med reglerne. Læs dem igen, og ret de spørgsmål, der er markeret med rødt.</p>'
            if wrong else "")
    q = urllib.parse.quote(safe_next(req_path), safe="/")
    body = f"""<p class="eyebrow">Før du går i gang</p>
<h1>{e(str(r.get("title") or "Reglerne for din konto"))}</h1>
<p>{e(str(r.get("intro") or ""))}</p>
<ol class="r">{items}</ol>
<h2>{e(str(r.get("quiz_title") or "Tre hurtige spørgsmål"))}</h2>
<p>{e(str(r.get("quiz_intro") or "Svar rigtigt på alle tre for at bekræfte, at du har læst og accepterer reglerne."))}</p>
{note}<form method="post" action="/regler?next={q}">{qs}
<button class="btn" type="submit">{e(str(r.get("button") or "Jeg accepterer reglerne"))}</button></form>
<p class="small">Du ser kun denne side første gang, du logger ind.</p>"""
    return HTMLResponse(PAGE.replace('<main>', '<main class="wide">').replace("__BODY__", body), status_code=200,
                        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"})


def page(body, status=200):
    return HTMLResponse(PAGE.replace("__BODY__", body), status_code=status,
                        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"})


def login_page(next_path="/", note=""):
    q = urllib.parse.quote(safe_next(next_path), safe="/")
    return page(f"""<h1>Nyt på Stream365</h1>
<p>Siden er kun for brugere af Stream365. Log ind med den Plex-konto, du bruger til Stream365.</p>
{f'<p class="err">{note}</p>' if note else ''}
<form method="post" action="/auth/start?next={q}"><button class="btn" type="submit">Log ind med Plex</button></form>
<p class="small">Du logger ind hos Plex. Stream365 ser ikke dit kodeord. Du bliver husket på denne enhed i {SESSION_DAYS} dage.</p>""")


@app.middleware("http")
async def old_hosts(req: Request, call_next):
    """Gamle adresser (fx nyt.stream365.vip) sendes videre til den nye."""
    host = (req.headers.get("host") or "").split(":")[0].lower()
    if host in OLD_HOSTS and req.url.path != "/health":
        return RedirectResponse(PUBLIC_URL + safe_next(req.url.path), status_code=301)
    return await call_next(req)


@app.get("/health")
def health():
    return {"ok": True, "site": os.path.isfile(os.path.join(SITE_DIR, "index.html")), "server_id": bool(machine_id()),
            "rules": bool(rules()), "status": (status_data()["ok"] if UPTIME_URL else None)}


@app.post("/regler")
async def rules_accept(req: Request, next: str = "/"):
    """Svarene på de tre spørgsmål. Alle skal være rigtige, før reglerne regnes som accepteret."""
    s = session(req)
    if not s:
        return RedirectResponse("/login", status_code=303)
    r = rules()
    if not r:
        return RedirectResponse(safe_next(next), status_code=303)
    form = urllib.parse.parse_qs((await req.body()).decode("utf-8", "replace"))
    wrong, chosen = set(), {}
    for i, q in enumerate(r.get("questions") or []):
        try:
            chosen[i] = int((form.get(f"q{i}") or [""])[0])
        except ValueError:
            chosen[i] = -1
        if chosen[i] != int(q["correct"]):
            wrong.add(i)
    if wrong:
        return rules_page(next, s[1], wrong, chosen)
    save_accept(s[0], s[1])
    return RedirectResponse(safe_next(next), status_code=303)


@app.get("/login")
def login(req: Request, next: str = "/"):
    if logged_in(req):
        return RedirectResponse(safe_next(next), status_code=303)
    return login_page(next)


@app.post("/auth/start")
def auth_start(next: str = "/"):
    """Bed plex.tv om en engangskode, og send brugeren til Plex' login."""
    try:
        r = httpx.post(PLEXTV_URL + "/api/v2/pins", headers=plex_headers(), timeout=15,
                       data={"strong": "true", "X-Plex-Product": PRODUCT, "X-Plex-Client-Identifier": CLIENT_ID})
        r.raise_for_status()
        pin = r.json()
        pin_id, code = int(pin["id"]), str(pin["code"])
    except Exception as e:
        log.warning("Kunne ikke få en kode hos plex.tv: %s", e.__class__.__name__)
        return login_page(next, "Plex svarer ikke lige nu. Prøv igen om lidt.")
    params = {"clientID": CLIENT_ID, "code": code, "context[device][product]": PRODUCT, "forwardUrl": PUBLIC_URL + "/auth/done"}
    resp = RedirectResponse(PLEX_AUTH_URL + "#?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote), status_code=303)
    resp.set_cookie(PIN_COOKIE, make_cookie(f"{pin_id}|{code}|{safe_next(next)}", 900), max_age=900, httponly=True, secure=SECURE, samesite="lax")
    return resp


@app.get("/auth/done")
def auth_done(req: Request):
    """Brugeren kommer tilbage fra Plex: hent nøglen, og tjek at kontoen har adgang til serveren."""
    raw = read_cookie(req.cookies.get(PIN_COOKIE))
    if not raw:
        return login_page("/", "Login tog for lang tid eller blev afbrudt. Prøv igen.")
    pin_id, code, next_path = (raw.split("|", 2) + ["", ""])[:3]
    token, user, uid = "", "", ""
    try:
        r = httpx.get(f"{PLEXTV_URL}/api/v2/pins/{int(pin_id)}", headers=plex_headers(), timeout=15,
                      params={"code": code, "X-Plex-Client-Identifier": CLIENT_ID})
        r.raise_for_status()
        token = str(r.json().get("authToken") or "")
    except Exception as e:
        log.warning("Kunne ikke hente svaret fra plex.tv: %s", e.__class__.__name__)
    if not token:
        return login_page(next_path, "Du blev ikke logget ind hos Plex. Prøv igen.")
    mid = machine_id()
    if not mid:
        return login_page(next_path, "Stream365 kan ikke tjekke din adgang lige nu. Prøv igen om lidt.")
    try:
        u = httpx.get(PLEXTV_URL + "/api/v2/user", headers=plex_headers(token), timeout=15)
        if u.status_code == 200:
            user, uid = str(u.json().get("username") or u.json().get("email") or ""), str(u.json().get("id") or "")
        res = httpx.get(PLEXTV_URL + "/api/v2/resources", headers=plex_headers(token), params={"includeHttps": 1}, timeout=20)
        res.raise_for_status()
        ok = any(str(x.get("clientIdentifier")) == mid and "server" in str(x.get("provides") or "") for x in res.json())
    except Exception as e:
        log.warning("Kunne ikke tjekke adgangen hos plex.tv: %s", e.__class__.__name__)
        return login_page(next_path, "Plex svarer ikke lige nu. Prøv igen om lidt.")
    finally:
        token = ""   # nøglen gemmes ikke
    if not ok:
        log.info("Afvist: Plex-kontoen %s har ikke adgang til serveren", user or "?")
        resp = page(f"""<h1>Kun for brugere af Stream365</h1>
<p>Plex-kontoen{f' <b style="color:#ECEEF1">{user}</b>' if user and re.fullmatch(r'[\w.@+\- ]{1,80}', user) else ''} har ikke adgang til Stream365. {CONTACT}</p>
<a class="btn" href="/login">Prøv med en anden konto</a>""", 403)
        resp.delete_cookie(PIN_COOKIE)
        return resp
    if not uid:
        return login_page(next_path, "Plex svarer ikke lige nu. Prøv igen om lidt.")
    log.info("Adgang givet til Plex-kontoen %s", user or "?")
    resp = RedirectResponse(safe_next(next_path), status_code=303)
    val = uid + ":" + base64.urlsafe_b64encode(user.encode()).decode()
    resp.set_cookie(COOKIE, make_cookie(val, SESSION_DAYS * 86400), max_age=SESSION_DAYS * 86400,
                    httponly=True, secure=SECURE, samesite="lax")
    resp.delete_cookie(PIN_COOKIE)
    return resp


# ---------------------------------------------------------------- driftstatus (fra Uptime Kuma)
_status = {"ts": 0.0, "data": None}
_status_lock = threading.Lock()
STATUS_TTL = 30   # sekunder – Uptime Kuma spørges højst to gange i minuttet, uanset antal brugere
_STATE = {0: "down", 1: "up", 2: "pending", 3: "maintenance"}


def fetch_status():
    """Statussiden UPTIME_SLUG fra Uptime Kuma: navn, seneste status og oppetid 24 t for hver monitor."""
    base = f"{UPTIME_URL}/api/status-page"
    page_ = httpx.get(f"{base}/{UPTIME_SLUG}", timeout=8)
    page_.raise_for_status()
    beats = httpx.get(f"{base}/heartbeat/{UPTIME_SLUG}", timeout=8)
    beats.raise_for_status()
    p, b = page_.json(), beats.json()
    hb, up = b.get("heartbeatList") or {}, b.get("uptimeList") or {}
    items = []
    for group in p.get("publicGroupList") or []:
        for m in group.get("monitorList") or []:
            mid = str(m.get("id"))
            last = (hb.get(mid) or hb.get(m.get("id")) or [])
            last = last[-1] if last else {}
            u = up.get(f"{mid}_24")
            name = str(m.get("name") or "")
            items.append({
                "name": name,
                "link": STATUS_LINKS.get(name.lower()) or "",
                "state": _STATE.get(last.get("status"), "unknown"),
                "uptime": round(float(u) * 100, 2) if isinstance(u, (int, float)) else None,
                "since": str(last.get("time") or ""),
            })
    inc = p.get("incident") or None
    notice = None
    if inc and (inc.get("title") or inc.get("content")):
        notice = {"title": str(inc.get("title") or ""), "text": str(inc.get("content") or ""), "style": str(inc.get("style") or "info")}
    maint = [str(x.get("title") or "") for x in (p.get("maintenanceList") or []) if x.get("title")]
    return {"ok": True, "items": items, "notice": notice, "maintenance": maint,
            "updated": datetime.datetime.now().strftime("%H:%M")}


def status_data():
    with _status_lock:
        if _status["data"] is not None and time.time() - _status["ts"] < STATUS_TTL:
            return _status["data"]
        try:
            data = fetch_status()
        except Exception as e:
            log.warning("Kunne ikke hente driftstatus fra Uptime Kuma: %s", e.__class__.__name__)
            data = {"ok": False, "items": [], "notice": None, "maintenance": [],
                    "updated": datetime.datetime.now().strftime("%H:%M")}
        _status.update(ts=time.time(), data=data)
        return data


STATUS_JS = r"""(function(){
var L={up:"Kører",down:"Nede",pending:"Ustabil",maintenance:"Vedligehold",unknown:"Ukendt"};
var css="#s365s{background:#121418;border-bottom:1px solid #262A32;color:#ECEEF1;font:14px/1.45 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;position:relative;z-index:50}"+
"#s365s *{box-sizing:border-box}#s365s summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:10px;padding:10px 16px;min-height:44px;max-width:1200px;margin:0 auto}"+
"#s365s summary::-webkit-details-marker{display:none}#s365s summary:focus-visible{outline:2px solid #58D9AE;outline-offset:-2px}"+
"#s365s .d{width:10px;height:10px;border-radius:50%;flex:none;background:#6B7280}#s365s .up{background:#58D9AE;box-shadow:0 0 0 3px rgba(88,217,174,.18)}"+
"#s365s .down{background:#F27D77;box-shadow:0 0 0 3px rgba(242,125,119,.2)}#s365s .pending{background:#F2C14E}#s365s .maintenance{background:#7AA7FF}"+
"#s365s .sum{font-weight:600;flex:1;min-width:0}#s365s .upd{color:#9BA3AE;font-size:12.5px;white-space:nowrap}"+
"#s365s .chev{color:#9BA3AE;transition:transform .15s}#s365s details[open] .chev{transform:rotate(180deg)}"+
"#s365s .body{max-width:1200px;margin:0 auto;padding:0 16px 14px}#s365s ul{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:8px;align-items:start}"+
"#s365s li{background:#0B0C0E;border:1px solid #262A32;border-radius:12px;padding:10px 12px;display:grid;grid-template-columns:auto 1fr auto;gap:4px 10px;align-items:center}"+
"#s365s li .n{font-weight:600}#s365s li .st{color:#9BA3AE;font-size:13px;text-align:right}#s365s li .u{grid-column:2/4;color:#9BA3AE;font-size:12.5px}"+
"#s365s li .lk{grid-column:2/4;display:flex;gap:8px;align-items:center;min-width:0}#s365s li code{font:13px ui-monospace,Menlo,Consolas,monospace;color:#C9CFCD;user-select:all;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}"+
"#s365s button{background:none;border:1px solid #262A32;color:#58D9AE;border-radius:8px;font:600 12.5px system-ui,sans-serif;padding:4px 9px;min-height:30px;cursor:pointer;flex:none}"+
"#s365s button:hover{border-color:#58D9AE}#s365s .note{background:#1A1F27;border:1px solid #2F3846;border-radius:12px;padding:10px 12px;margin:0 0 10px;color:#D5D9DF}"+
"#s365s .note.danger{background:#3A1C1B;border-color:#5A2A28;color:#FFC1BD}#s365s .note.warning{background:#3A311B;border-color:#5A4A28;color:#FFE3A8}#s365s .note b{display:block;color:inherit}";
var st=document.createElement("style");st.textContent=css;document.head.appendChild(st);
var box=document.createElement("div");box.id="s365s";box.setAttribute("role","region");box.setAttribute("aria-label","Driftstatus");
document.body.insertBefore(box,document.body.firstChild);
var userToggled=false,lastOpen=null;
function esc(t){var d=document.createElement("div");d.textContent=t==null?"":String(t);return d.innerHTML;}
function pct(u){return u==null?"":(u>=99.995?"100":u.toFixed(u>=99?2:1).replace(".",","))+" %";}
function render(s){
 var items=s.items||[],bad=items.filter(function(i){return i.state!=="up";}),dot,txt;
 if(!s.ok||!items.length){dot="";txt="Driftstatus kan ikke hentes lige nu";}
 else if(!bad.length){dot="up";txt="Alle tjenester kører";}
 else if(bad.every(function(i){return i.state==="maintenance";})){dot="maintenance";txt="Vedligehold: "+bad.map(function(i){return i.name;}).join(", ");}
 else{var dn=bad.filter(function(i){return i.state==="down";});dot=dn.length?"down":"pending";
  txt=(dn.length?dn:bad).map(function(i){return i.name;}).join(", ")+(dn.length?(dn.length>1?" er nede":" er nede"):" er ustabil");}
 var note="";
 if(s.notice){note='<div class="note '+esc(s.notice.style)+'"><b>'+esc(s.notice.title)+'</b>'+esc(s.notice.text)+'</div>';}
 (s.maintenance||[]).forEach(function(m){note+='<div class="note"><b>Planlagt vedligehold</b>'+esc(m)+'</div>';});
 var li=items.map(function(i){
  return '<li><span class="d '+esc(i.state)+'" aria-hidden="true"></span><span class="n">'+esc(i.name)+'</span><span class="st">'+L[i.state]+'</span>'+
   (i.link?'<span class="lk"><code>'+esc(i.link)+'</code><button type="button" data-c="'+esc(i.link)+'">Kopiér</button></span>':'')+
   '<span class="u">Oppetid seneste 24 timer: '+(i.uptime==null?"–":pct(i.uptime))+'</span></li>';}).join("");
 var problem=!!(bad.length||s.notice||(s.maintenance||[]).length);
 var open=userToggled?lastOpen:(problem||window.matchMedia("(min-width: 900px)").matches);
 box.innerHTML='<details'+(open?" open":"")+'><summary><span class="d '+dot+'" aria-hidden="true"></span><span class="sum">'+esc(txt)+
  '</span><span class="upd">Opdateret '+esc(s.updated||"")+'</span><span class="chev" aria-hidden="true">▾</span></summary><div class="body">'+note+
  (items.length?'<ul>'+li+'</ul>':'')+'</div></details>';
 var d=box.querySelector("details");d.addEventListener("toggle",function(){userToggled=true;lastOpen=d.open;});
 box.querySelectorAll("button[data-c]").forEach(function(b){b.addEventListener("click",function(){
  var t=b.getAttribute("data-c");(navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(function(){b.textContent="Kopieret";},function(){b.textContent="Markér og kopiér";});
  setTimeout(function(){b.textContent="Kopiér";},2000);});});
}
function load(){fetch("/api/status",{credentials:"same-origin",cache:"no-store"}).then(function(r){return r.ok?r.json():null;}).then(function(s){if(s)render(s);}).catch(function(){});}
load();setInterval(load,60000);
document.addEventListener("visibilitychange",function(){if(!document.hidden)load();});
})();"""


def status_allowed(req: Request):
    s = session(req)
    return bool(UPTIME_URL) and s is not None and has_accepted(s[0])


@app.get("/api/status")
def api_status(req: Request):
    """Driftstatus til linjen øverst i guiden – kun for brugere, der er logget ind."""
    if not status_allowed(req):
        return JSONResponse({"detail": "log ind først"}, status_code=401)
    return JSONResponse(status_data(), headers={"Cache-Control": "no-store"})


@app.get("/api/status.js")
def api_status_js(req: Request):
    if not status_allowed(req):
        return HTMLResponse("", status_code=401, media_type="application/javascript")
    return HTMLResponse(STATUS_JS, media_type="application/javascript", headers={"Cache-Control": "private, max-age=300"})


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


@app.get("/robots.txt")
def robots():
    return HTMLResponse("User-agent: *\nDisallow: /\n", media_type="text/plain")


@app.get("/{path:path}")
def site(path: str, req: Request):
    """Siden selv – kun for dem, der er logget ind."""
    if not logged_in(req):
        if path == "" or path.endswith((".html", "/")) or "." not in os.path.basename(path):
            return RedirectResponse("/login?next=" + urllib.parse.quote(safe_next("/" + path), safe="/"), status_code=303)
        return JSONResponse({"detail": "log ind først"}, status_code=401)
    s = session(req)
    wants_page = path == "" or path.endswith((".html", "/")) or "." not in os.path.basename(path)
    if not has_accepted(s[0]):
        return rules_page("/" + path, s[1]) if wants_page else JSONResponse({"detail": "acceptér reglerne først"}, status_code=401)
    full = os.path.realpath(os.path.join(SITE_DIR, path))
    if any(part.startswith(("_", ".")) for part in path.split("/") if part):
        full = ""    # filer, der begynder med _ eller . (fx _regler.json), vises aldrig
    if full != SITE_DIR and not full.startswith(SITE_DIR + os.sep):
        return page("<h1>Siden findes ikke</h1><p>Adressen er forkert.</p><a class=\"btn\" href=\"/\">Til forsiden</a>", 404)
    if os.path.isdir(full):
        full = os.path.join(full, "index.html")
    if not os.path.isfile(full):
        return page("<h1>Siden findes ikke</h1><p>Adressen er forkert.</p><a class=\"btn\" href=\"/\">Til forsiden</a>", 404)
    is_html = full.endswith(".html")
    if is_html and UPTIME_URL:
        with open(full, encoding="utf-8", errors="replace") as f:
            doc = f.read()
        tag = '<script src="/api/status.js" defer></script>'
        doc = doc.replace("</body>", tag + "</body>", 1) if "</body>" in doc else doc + tag
        return HTMLResponse(doc, headers={"Cache-Control": "private, no-cache", "X-Robots-Tag": "noindex, nofollow"})
    return FileResponse(full, media_type=mimetypes.guess_type(full)[0] or "application/octet-stream",
                        headers={"Cache-Control": "private, no-cache" if is_html else "private, max-age=86400",
                                 "X-Robots-Tag": "noindex, nofollow"})
