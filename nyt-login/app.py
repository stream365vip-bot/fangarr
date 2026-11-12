"""nyt-login – viser en statisk side (nyhedsbrevet), men kun for Plex-konti med adgang til Stream365-serveren.

Sådan virker det (samme metode som login i Seerr):
1. Brugeren trykker "Log ind med Plex". Appen beder plex.tv om en engangskode (PIN) og sender brugeren til Plex.
2. Plex sender brugeren tilbage. Appen henter brugerens nøgle hos plex.tv og spørger, hvilke servere kontoen har adgang til.
3. Er Stream365-serveren på listen, får brugeren en cookie (underskrevet, gælder SESSION_DAYS dage) og ser siden.
Brugerens kodeord ses aldrig, og brugerens Plex-nøgle gemmes ikke – den bruges kun til det ene opslag.
"""

import hashlib
import hmac
import logging
import mimetypes
import os
import re
import secrets
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


def logged_in(req: Request):
    return read_cookie(req.cookies.get(COOKIE)) is not None


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
</style></head><body><main>
<div class="logo" aria-hidden="true">365</div>
__BODY__
</main></body></html>"""


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


@app.get("/health")
def health():
    return {"ok": True, "site": os.path.isfile(os.path.join(SITE_DIR, "index.html")), "server_id": bool(machine_id())}


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
    log.info("Adgang givet til Plex-kontoen %s", user or "?")
    resp = RedirectResponse(safe_next(next_path), status_code=303)
    resp.set_cookie(COOKIE, make_cookie(uid or "bruger", SESSION_DAYS * 86400), max_age=SESSION_DAYS * 86400,
                    httponly=True, secure=SECURE, samesite="lax")
    resp.delete_cookie(PIN_COOKIE)
    return resp


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
    full = os.path.realpath(os.path.join(SITE_DIR, path))
    if full != SITE_DIR and not full.startswith(SITE_DIR + os.sep):
        return page("<h1>Siden findes ikke</h1><p>Adressen er forkert.</p><a class=\"btn\" href=\"/\">Til forsiden</a>", 404)
    if os.path.isdir(full):
        full = os.path.join(full, "index.html")
    if not os.path.isfile(full):
        return page("<h1>Siden findes ikke</h1><p>Adressen er forkert.</p><a class=\"btn\" href=\"/\">Til forsiden</a>", 404)
    is_html = full.endswith(".html")
    return FileResponse(full, media_type=mimetypes.guess_type(full)[0] or "application/octet-stream",
                        headers={"Cache-Control": "private, no-cache" if is_html else "private, max-age=86400",
                                 "X-Robots-Tag": "noindex, nofollow"})
