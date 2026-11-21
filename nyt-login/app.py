"""nyt-login – viser en statisk side (nyhedsbrevet), men kun for Plex-konti med adgang til Stream365-serveren.

Sådan virker det (samme metode som login i Seerr):
1. Brugeren trykker "Log ind med Plex". Brugerens browser beder plex.tv om en engangskode (PIN), så Plex ser brugerens
   egen adresse (ikke feeders i Finland). Virker det ikke, beder appen selv om koden. Brugeren sendes til Plex.
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
def link_key(name):
    """'IPTV 3', 'iptv3' og 'IPTV-3 ' er samme monitor."""
    return re.sub(r"[^a-z0-9æøå]+", "", str(name or "").lower())


STATUS_LINKS = {link_key(k): v.strip() for k, _, v in
                (x.partition("=") for x in (os.environ.get("STATUS_LINKS") or "").split(";")) if link_key(k) and v.strip()}
# Tælleren (hvem har været inde, hvilke afsnit, hvilke søgeord). Fangarr læser mappen og viser fanen Guide.
STAT_ON = (os.environ.get("STAT") or "1").strip() != "0"
STAT_DIR = os.environ.get("STAT_DIR") or os.path.join(DATA_DIR, "statistik")
STAT_DAYS = int(os.environ.get("STAT_DAYS") or "90")           # ældre dage slettes automatisk
STAT_VISIT_GAP = 30 * 60                                        # pause på 30 min. = et nyt besøg
# Konti, der ikke tælles med (Plex-brugernavn eller Plex-id, adskilt med komma) – fx din egen
STAT_EXCLUDE = {x.strip().lower() for x in (os.environ.get("STAT_EXCLUDE") or "Stream365").split(",") if x.strip()}
# Nyheder øverst i guiden (fra 21. nov. 2026). Hentes hos Fangarr inde i Docker-netværket – NEWS=0 slår dem fra.
NEWS_ON = (os.environ.get("NEWS") or "1").strip() != "0"
NEWS_URL = (os.environ.get("NEWS_URL") or "http://fangarr:8080/api/nyheder/guide").strip()
NEWS_EVERY = 30                                                   # sekunder mellem hver hentning
NEWS_FILE = os.path.join(DATA_DIR, "nyheder.json")                # seneste svar – så nyhederne vises, selv om Fangarr genstarter
# Køb i guiden ("Få flere ønsker", fra 21. nov. 2026): spørger Fangarr internt med en hemmelig nøgle (samme som NYT_TOKEN
# i /opt/fangarr/fangarr.env). Nøglen ligger i filen /opt/nyt/data/fangarr_token (eller miljøvariablen NYT_TOKEN).
KOB_URL = (os.environ.get("KOB_URL") or "http://fangarr:8080/api/kob").rstrip("/")
KOB_TOKEN_FILE = os.path.join(DATA_DIR, "fangarr_token")
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
    stat_copy_accepted()
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
<form id="lf" method="post" action="/auth/start?next={q}"><button class="btn" type="submit">Log ind med Plex</button></form>
<p class="small">Du logger ind hos Plex. Stream365 ser ikke dit kodeord. Du bliver husket på denne enhed i {SESSION_DAYS} dage.</p>
{login_script(q)}""")


def login_script(q):
    """Knappen beder selv plex.tv om koden fra brugerens browser. Så viser Plex brugerens egen adresse og by
    i stedet for feeders (Helsinki, Finland), og der kommer ingen advarsel om en fremmed enhed.
    Virker det ikke (gammel browser, plex.tv afviser), sendes formularen som før, og feeder beder om koden."""
    cfg = json.dumps({"plextv": PLEXTV_URL, "next": q, "headers": {
        k: v for k, v in plex_headers().items()}}).replace("</", "<\\/")
    return """<script>(function(){var c=__CFG__,f=document.getElementById("lf");if(!f||!window.fetch)return;
f.addEventListener("submit",function(ev){ev.preventDefault();var b=f.querySelector("button");b.disabled=true;b.textContent="Åbner Plex …";
fetch(c.plextv+"/api/v2/pins?strong=true",{method:"POST",headers:c.headers}).then(function(r){if(!r.ok)throw 0;return r.json()})
.then(function(p){return fetch("/auth/pin?next="+c.next,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},
body:JSON.stringify({id:p.id,code:p.code})})}).then(function(r){if(!r.ok)throw 0;return r.json()})
.then(function(j){location.href=j.url}).catch(function(){f.submit()})});})();</script>""".replace("__CFG__", cfg)


@app.on_event("startup")
def startup():
    stat_copy_accepted()
    if NEWS_ON:
        threading.Thread(target=news_loop, daemon=True, name="nyheder").start()


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
            "rules": bool(rules()), "status": (status_data()["ok"] if UPTIME_URL else None),
            "news": (_news["ok"] if NEWS_ON else None)}


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
    resp = RedirectResponse(plex_auth_url(code), status_code=303)
    set_pin_cookie(resp, pin_id, code, next)
    return resp


def plex_auth_url(code):
    params = {"clientID": CLIENT_ID, "code": code, "context[device][product]": PRODUCT, "forwardUrl": PUBLIC_URL + "/auth/done"}
    return PLEX_AUTH_URL + "#?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def set_pin_cookie(resp, pin_id, code, next_path):
    resp.set_cookie(PIN_COOKIE, make_cookie(f"{int(pin_id)}|{code}|{safe_next(next_path)}", 900), max_age=900,
                    httponly=True, secure=SECURE, samesite="lax")


@app.post("/auth/pin")
async def auth_pin(req: Request, next: str = "/"):
    """Koden er lavet i brugerens browser (så Plex ser brugerens egen adresse). Gem den, og giv adressen til Plex' login."""
    origin = (req.headers.get("origin") or "").rstrip("/")
    if origin and origin != PUBLIC_URL:   # kun fra vores egen side
        return JSONResponse({"error": "origin"}, status_code=403)
    try:
        d = json.loads(await req.body())
        pin_id, code = int(d["id"]), str(d["code"])
        if pin_id <= 0 or not re.fullmatch(r"[A-Za-z0-9]{4,64}", code):
            raise ValueError
    except Exception:
        return JSONResponse({"error": "pin"}, status_code=400)
    resp = JSONResponse({"url": plex_auth_url(code)}, headers={"Cache-Control": "no-store"})
    set_pin_cookie(resp, pin_id, code, next)
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
    stat_log(uid, user, "login")
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
    items, seen = [], set()
    for group in p.get("publicGroupList") or []:
        for m in group.get("monitorList") or []:
            mid = str(m.get("id"))
            last = (hb.get(mid) or hb.get(m.get("id")) or [])
            last = last[-1] if last else {}
            u = up.get(f"{mid}_24")
            name = str(m.get("name") or "")
            seen.add(link_key(name))
            items.append({
                "name": name,
                # adressen under lampen: fra STATUS_LINKS – ellers monitorens egen adresse, hvis den er slået til på statussiden
                "link": STATUS_LINKS.get(link_key(name)) or (str(m.get("url") or "") if m.get("sendUrl") else ""),
                "state": _STATE.get(last.get("status"), "unknown"),
                "uptime": round(float(u) * 100, 2) if isinstance(u, (int, float)) else None,
                "since": str(last.get("time") or ""),
            })
    missing = sorted(k for k in STATUS_LINKS if k not in seen)
    if items and missing != _status.get("warned"):
        _status["warned"] = missing
        if missing:
            log.warning("STATUS_LINKS: %s passer ikke til nogen monitor på statussiden (monitorer: %s)",
                        ", ".join(missing), ", ".join(i["name"] for i in items))
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
var css="#w{background:#0F1C18;border-bottom:2px solid rgba(88,217,174,.55);color:#ECEEF1;font:15px/1.45 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;position:relative;z-index:50}"+
"#w.down{background:#3A1C1B;border-bottom-color:#F27D77}#w.pending{background:#33290F;border-bottom-color:#F2C14E}"+
"#w.maintenance,#w.info{background:#141E33;border-bottom-color:#7AA7FF}#w.na{background:#121418;border-bottom-color:#262A32}"+
"#w *{box-sizing:border-box}#w summary{list-style:none;cursor:pointer;display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;padding:10px 16px;min-height:48px;max-width:1200px;margin:0 auto}"+
"#w summary::-webkit-details-marker{display:none}#w summary:focus-visible{outline:2px solid #58D9AE;outline-offset:-2px}"+
"#w .d{width:10px;height:10px;border-radius:50%;flex:none;background:#6B7280;display:inline-block}#w .up{background:#58D9AE;box-shadow:0 0 0 3px rgba(88,217,174,.18)}"+
"#w .down{background:#F27D77;box-shadow:0 0 0 3px rgba(242,125,119,.25)}#w .pending{background:#F2C14E}#w .maintenance{background:#7AA7FF}"+
"#w .hd{display:flex;flex-wrap:wrap;align-items:center;gap:2px 10px;flex:1 1 150px;min-width:0}#w .hd b{font-weight:700;white-space:nowrap}#w .sum{font-weight:600;min-width:0}"+
"#w.ok .sum{color:#8FE8C8}#w .more{display:inline-flex;align-items:center;gap:6px;border:1px solid rgba(236,238,241,.28);border-radius:999px;padding:5px 12px;font-size:13px;font-weight:600;white-space:nowrap;min-height:32px}"+
"#w summary:hover .more{border-color:#58D9AE}#w .chev{transition:transform .15s}#w details[open] .chev{transform:rotate(180deg)}"+
"#w .chips{display:flex;flex-wrap:wrap;gap:6px 8px;flex:1 0 100%}#w details[open] .chips{display:none}"+
"#w .c{display:inline-flex;align-items:center;gap:7px;background:rgba(11,12,14,.55);border:1px solid rgba(236,238,241,.14);border-radius:999px;padding:4px 11px 4px 9px;font-size:13.5px;font-weight:600;white-space:nowrap}"+
"#w .c.bad{border-color:currentColor}#w .c small{font-weight:500;color:#C9CFCD;font-size:12.5px}"+
"#w .body{max-width:1200px;margin:0 auto;padding:2px 16px 14px}#w ul{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:8px;align-items:start}"+
"#w li{background:#0B0C0E;border:1px solid #262A32;border-radius:12px;padding:10px 12px;display:grid;grid-template-columns:auto 1fr auto;gap:4px 10px;align-items:center}"+
"#w li .n{font-weight:600}#w li .st{color:#9BA3AE;font-size:13px;text-align:right}#w li .u{grid-column:2/4;color:#9BA3AE;font-size:12.5px}"+
"#w li .lk{grid-column:2/4;display:flex;gap:8px;align-items:center;min-width:0}#w li code{font:13px ui-monospace,Menlo,Consolas,monospace;color:#C9CFCD;user-select:all;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}"+
"#w button{background:none;border:1px solid #262A32;color:#58D9AE;border-radius:8px;font:600 12.5px system-ui,sans-serif;padding:4px 9px;min-height:30px;cursor:pointer;flex:none}"+
"#w button:hover{border-color:#58D9AE}#w .note{background:#1A1F27;border:1px solid #2F3846;border-radius:12px;padding:10px 12px;margin:0 0 10px;color:#D5D9DF}"+
"#w .note.danger{background:#3A1C1B;border-color:#5A2A28;color:#FFC1BD}#w .note.warning{background:#3A311B;border-color:#5A4A28;color:#FFE3A8}#w .note b{display:block;color:inherit}"+
"#w .upd{color:#9BA3AE;font-size:12.5px;margin:10px 0 0}#w .more .sm{display:none}"+
"@media(max-width:600px){#w .more .lg{display:none}#w .more .sm{display:inline}}";
// Linjen ligger i sin egen "skygge" (shadow DOM), så guidens egne stilarter ikke kan ændre dens udseende – og omvendt.
var host=document.createElement("div");host.id="s365s";host.style.cssText="display:block;position:relative;z-index:50";
document.body.insertBefore(host,document.body.firstChild);
var root=host.attachShadow?host.attachShadow({mode:"open"}):host;
var st=document.createElement("style");st.textContent=":host{all:initial;display:block}"+css;root.appendChild(st);
var box=document.createElement("div");box.id="w";box.setAttribute("role","region");box.setAttribute("aria-label","Driftstatus");root.appendChild(box);
var userToggled=false,lastOpen=null;
function esc(t){var d=document.createElement("div");d.textContent=t==null?"":String(t);return d.innerHTML;}
function pct(u){return u==null?"":(u>=99.995?"100":u.toFixed(u>=99?2:1).replace(".",","))+" %";}
function render(s){
 var items=s.items||[],bad=items.filter(function(i){return i.state!=="up";}),dot,txt,cls;
 if(!s.ok||!items.length){dot="";cls="na";txt="kan ikke hentes lige nu";}
 else if(!bad.length){dot="up";cls="ok";txt="Alle tjenester kører";}
 else if(bad.every(function(i){return i.state==="maintenance";})){dot=cls="maintenance";txt="Vedligehold: "+bad.map(function(i){return i.name;}).join(", ");}
 else{var dn=bad.filter(function(i){return i.state==="down";});dot=cls=dn.length?"down":"pending";
  txt=(dn.length?dn:bad).map(function(i){return i.name;}).join(", ")+(dn.length?" er nede":" er ustabil");}
 if(cls==="ok"&&(s.notice||(s.maintenance||[]).length))cls=s.notice&&s.notice.style==="danger"?"down":s.notice&&s.notice.style==="warning"?"pending":"info";
 var note="";
 if(s.notice){note='<div class="note '+esc(s.notice.style)+'"><b>'+esc(s.notice.title)+'</b>'+esc(s.notice.text)+'</div>';}
 (s.maintenance||[]).forEach(function(m){note+='<div class="note"><b>Planlagt vedligehold</b>'+esc(m)+'</div>';});
 var chips=items.map(function(i){return '<span class="c'+(i.state==="up"?"":" bad")+'"><span class="d '+esc(i.state)+'" aria-hidden="true"></span>'+esc(i.name)+
  (i.state==="up"?'<span style="position:absolute;left:-9999px"> kører</span>':' <small>'+L[i.state]+'</small>')+'</span>';}).join("");
 var li=items.map(function(i){
  return '<li><span class="d '+esc(i.state)+'" aria-hidden="true"></span><span class="n">'+esc(i.name)+'</span><span class="st">'+L[i.state]+'</span>'+
   (i.link?'<span class="lk"><code>'+esc(i.link)+'</code><button type="button" data-c="'+esc(i.link)+'">Kopiér</button></span>':'')+
   '<span class="u">Oppetid seneste 24 timer: '+(i.uptime==null?"–":pct(i.uptime))+'</span></li>';}).join("");
 var problem=!!(bad.length||s.notice||(s.maintenance||[]).length);
 var open=userToggled?lastOpen:(problem||window.matchMedia("(min-width: 900px)").matches);
 var links=items.some(function(i){return i.link;});
 box.className=cls;
 box.innerHTML='<details'+(open?" open":"")+'><summary><span class="hd"><span class="d '+dot+'" aria-hidden="true"></span><b>Driftstatus</b><span class="sum">'+esc(txt)+
  '</span></span>'+(items.length||note?'<span class="more"><span class="lg">'+(links?"Adresser og oppetid":"Oppetid")+'</span><span class="sm">'+(links?"Adresser":"Oppetid")+'</span> <span class="chev" aria-hidden="true">▾</span></span>':'')+
  (chips?'<span class="chips">'+chips+'</span>':'')+'</summary><div class="body">'+note+
  (items.length?'<ul>'+li+'</ul>':'')+'<p class="upd">Opdateret kl. '+esc(s.updated||"")+' – opdateres hvert minut</p></div></details>';
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


# ---------------------------------------------------------------- nyheder (skrives i Fangarr › Guide › Nyheder)
# Fangarr laver alt: teksterne, farverne, illustrationerne og selve tegningen (JavaScript). Appen her henter det hvert
# 30. sekund, gemmer seneste svar i NEWS_FILE og viser det kun for kunder, der er logget ind og har accepteret reglerne.
# Fangarr får guidens afsnit (<section id> + overskrift) med, så knappen kan føre til et afsnit. Ingen kundedata sendes.
_news_lock = threading.Lock()
_news = {"data": None, "ok": False, "fails": 0, "sections": None, "site_mtime": None}


def site_sections():
    """Guidens afsnit: [{"id": …, "title": …}] fra <section id="…"> og den første overskrift i afsnittet."""
    path = os.path.join(SITE_DIR, "index.html")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return []
    if _news["sections"] is not None and _news["site_mtime"] == mtime:
        return _news["sections"]
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            doc = f.read()
    except OSError:
        return []
    out, seen = [], set()
    for m in re.finditer(r"<section\b[^>]*\bid=[\"']([\w\-:.]{1,80})[\"'][^>]*>(.*?)(?=<section\b|</main>|</body>|$)", doc, flags=re.S | re.I):
        sid = m.group(1)
        if sid in seen:
            continue
        seen.add(sid)
        h = re.search(r"<h[1-4]\b[^>]*>(.*?)</h[1-4]>", m.group(2), flags=re.S | re.I)
        title = html.unescape(re.sub(r"<[^>]+>", " ", h.group(1))) if h else sid
        out.append({"id": sid, "title": _clean_text(title, 80) or sid})
        if len(out) >= 80:
            break
    _news.update(sections=out, site_mtime=mtime)
    return out


def news_fetch():
    try:
        r = httpx.post(NEWS_URL, json={"sections": site_sections()}, timeout=6)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict) or not isinstance(data.get("news"), list):
            raise ValueError("uventet svar")
    except Exception as e:
        with _news_lock:
            _news["fails"] += 1
            first = _news["fails"] == 1
            _news["ok"] = False
        if first:
            log.warning("Nyhederne kunne ikke hentes hos Fangarr (%s) – viser de senest hentede", e.__class__.__name__)
        return
    with _news_lock:
        if _news["fails"]:
            log.info("Nyhederne hentes igen hos Fangarr")
        changed = data.get("news") != (_news["data"] or {}).get("news") or data.get("js_v") != (_news["data"] or {}).get("js_v") \
            or data.get("contact") != (_news["data"] or {}).get("contact")
        _news.update(data=data, ok=True, fails=0)
    if changed:
        try:
            tmp = NEWS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, NEWS_FILE)
        except OSError as e:
            log.warning("Nyhederne kunne ikke gemmes (%s)", e.__class__.__name__)


def news_loop():
    try:
        with open(NEWS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            _news["data"] = d
    except (OSError, ValueError):
        pass
    while True:
        news_fetch()
        time.sleep(NEWS_EVERY)


def news_for(uid):
    """De nyheder, denne kunde skal se lige nu (periode og "kun for nye brugere")."""
    d = _news["data"] or {}
    now = time.time()
    acc = None
    out = []
    for n in d.get("news") or []:
        if not isinstance(n, dict):
            continue
        if n.get("start_ts") and n["start_ts"] > now:
            continue
        if n.get("end_ts") and n["end_ts"] <= now:
            continue
        if n.get("only_new"):
            if acc is None:
                with _accept_lock:
                    acc = (_accepted_all().get(str(uid)) or {}).get("at") or ""
            try:
                days = (datetime.datetime.now() - datetime.datetime.fromisoformat(acc)).days if acc else 10 ** 6
            except ValueError:
                days = 10 ** 6
            if days >= int(d.get("new_days") or 14):
                continue
        out.append(n)
    return out


def news_allowed(req: Request):
    s = session(req)
    return s if NEWS_ON and s is not None and has_accepted(s[0]) else None


@app.get("/api/nyheder")
def api_news(req: Request):
    s = news_allowed(req)
    if not s:
        return JSONResponse({"detail": "log ind først"}, status_code=401)
    d = _news["data"] or {}
    shop = d.get("shop") if isinstance(d.get("shop"), dict) and d["shop"].get("open") and kob_token() else None
    return JSONResponse({"news": news_for(s[0]), "contact": d.get("contact"), "shop": shop}, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- køb i guiden ("Få flere ønsker")
# Appen her sender kun Plex-id og brugernavn på den indloggede kunde til Fangarr (aldrig hvad browseren påstår) og
# viser svaret. Fangarr finder kunden, regner beløbet ud, lægger det på næste betaling og retter Seerr.
_kob = {"token": None, "mtime": None}


def kob_token():
    t = (os.environ.get("NYT_TOKEN") or "").strip()
    if t:
        return t
    try:
        m = os.path.getmtime(KOB_TOKEN_FILE)
    except OSError:
        return ""
    if _kob["mtime"] != m:
        try:
            with open(KOB_TOKEN_FILE, encoding="utf-8") as f:
                _kob.update(token=f.read().strip(), mtime=m)
        except OSError:
            return ""
    return _kob["token"] if len(_kob["token"] or "") >= 32 else ""


def kob_call(path, body):
    t = kob_token()
    if not t:
        return JSONResponse({"detail": "Køb i guiden er ikke sat op."}, status_code=404)
    try:
        r = httpx.post(KOB_URL + path, json=body, headers={"X-Nyt-Token": t}, timeout=12)
    except Exception as e:
        log.warning("Køb i guiden: Fangarr svarer ikke (%s)", e.__class__.__name__)
        return JSONResponse({"detail": "Det kan ikke lade sig gøre lige nu. Prøv igen om lidt."}, status_code=503)
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code == 404:
        return JSONResponse({"detail": "Køb i guiden er ikke åbent."}, status_code=404)
    if r.status_code >= 400:
        detail = data.get("detail") if isinstance(data.get("detail"), str) else "Det kan ikke lade sig gøre lige nu."
        return JSONResponse({"detail": detail}, status_code=r.status_code if r.status_code in (400, 409, 429) else 502)
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


async def kob_body(req: Request, s):
    origin = (req.headers.get("origin") or "").rstrip("/")
    if origin and origin != PUBLIC_URL:
        return None
    try:
        raw = await req.body()
        b = json.loads(raw) if len(raw) <= 2000 else None
    except Exception:
        b = None
    if not isinstance(b, dict):
        return None
    out = {"uid": s[0], "name": s[1], "what": "buy" if b.get("what") == "buy" else "package"}
    for k in ("package", "film", "tv", "expect"):
        if k in b and isinstance(b[k], (str, int, float)) and not isinstance(b[k], bool):
            out[k] = b[k]
    return out


@app.get("/api/kob")
def api_kob(req: Request):
    s = news_allowed(req)
    if not s:
        return JSONResponse({"detail": "Log ind først."}, status_code=401)
    return kob_call("/mig", {"uid": s[0], "name": s[1]})


@app.post("/api/kob/tilbud")
async def api_kob_quote(req: Request):
    s = news_allowed(req)
    if not s:
        return JSONResponse({"detail": "Log ind først."}, status_code=401)
    b = await kob_body(req, s)
    if b is None:
        return JSONResponse({"detail": "Ugyldig forespørgsel."}, status_code=400)
    return kob_call("/tilbud", b)


@app.post("/api/kob/vaelg")
async def api_kob_choose(req: Request):
    s = news_allowed(req)
    if not s:
        return JSONResponse({"detail": "Log ind først."}, status_code=401)
    b = await kob_body(req, s)
    if b is None:
        return JSONResponse({"detail": "Ugyldig forespørgsel."}, status_code=400)
    res = kob_call("/vaelg", b)
    if res.status_code == 200:
        log.info("Køb i guiden: Plex-kontoen %s har valgt (%s)", s[1] or s[0], b.get("what"))
    return res


@app.get("/api/nyheder.js")
def api_news_js(req: Request):
    if not news_allowed(req):
        return HTMLResponse("", status_code=401, media_type="application/javascript")
    js = (_news["data"] or {}).get("js") or ""
    body = (js + "\n;window.S365News&&window.S365News.guide();") if js else ""
    return HTMLResponse(body, media_type="application/javascript", headers={"Cache-Control": "private, no-cache"})


# ---------------------------------------------------------------- tæller (læses af Fangarr, fanen Guide)
# Én fil pr. dag i STAT_DIR (fx 2026-11-15.jsonl), én linje pr. hændelse: login, besøg, afsnit, søgning.
# Der gemmes Plex-id, brugernavn og tidspunkt – ingen IP-adresser. Filer ældre end STAT_DAYS dage slettes.
_stat_lock = threading.Lock()
_stat = {"last": {}, "rate": {}, "cleaned": ""}


def stat_excluded(uid, name):
    return not STAT_ON or str(uid).lower() in STAT_EXCLUDE or str(name or "").lower() in STAT_EXCLUDE


def _clean_text(v, n):
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", str(v or ""))).strip()[:n]


def stat_log(uid, name, event, **fields):
    """Skriv én hændelse. Fejl her må aldrig give brugeren en fejl."""
    if stat_excluded(uid, name):
        return
    now = datetime.datetime.now()
    row = {"t": now.isoformat(timespec="seconds"), "uid": str(uid), "user": str(name or ""), "e": event}
    row.update({k: v for k, v in fields.items() if v})
    try:
        with _stat_lock:
            os.makedirs(STAT_DIR, exist_ok=True)
            day = now.strftime("%Y-%m-%d")
            with open(os.path.join(STAT_DIR, day + ".jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if _stat["cleaned"] != day:
                _stat["cleaned"] = day
                limit = (now - datetime.timedelta(days=STAT_DAYS)).strftime("%Y-%m-%d")
                for fn in os.listdir(STAT_DIR):
                    if re.fullmatch(r"\d{4}-\d\d-\d\d\.jsonl", fn) and fn[:10] < limit:
                        os.remove(os.path.join(STAT_DIR, fn))
    except OSError as e:
        log.warning("Tælleren kunne ikke skrive (%s)", e.__class__.__name__)


def stat_visit(uid, name):
    """Et besøg = brugeren åbner guiden efter mindst 30 minutters pause."""
    if stat_excluded(uid, name):
        return
    now = time.time()
    with _stat_lock:
        new = now - _stat["last"].get(str(uid), 0) > STAT_VISIT_GAP
        _stat["last"][str(uid)] = now
    if new:
        stat_log(uid, name, "visit")


def stat_rate_ok(uid, n):
    """Højst 120 hændelser pr. bruger pr. 10 minutter – resten smides væk."""
    now, key = time.time(), str(uid)
    with _stat_lock:
        start, used = _stat["rate"].get(key, (now, 0))
        if now - start > 600:
            start, used = now, 0
        ok = used + n <= 120
        _stat["rate"][key] = (start, used + n if ok else used)
        return ok


def stat_copy_accepted():
    """Kopi af listen over accepterede regler til Fangarr (uden dine egne konti)."""
    if not STAT_ON:
        return
    try:
        d = {k: v for k, v in _accepted_all().items() if not stat_excluded(k, (v or {}).get("user"))}
        os.makedirs(STAT_DIR, exist_ok=True)
        tmp = os.path.join(STAT_DIR, "accepteret.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, os.path.join(STAT_DIR, "accepteret.json"))
    except OSError as e:
        log.warning("Listen over accepterede regler kunne ikke kopieres til tælleren (%s)", e.__class__.__name__)


STAT_JS = r"""(function(){
var q=[],timer=null,done={},cur=null,ticks=0,lastQ="";
function flush(){if(!q.length)return;var b=JSON.stringify({events:q.splice(0,20)});
 try{if(navigator.sendBeacon&&navigator.sendBeacon("/api/stat",new Blob([b],{type:"application/json"})))return;}catch(e){}
 try{fetch("/api/stat",{method:"POST",credentials:"same-origin",keepalive:true,headers:{"Content-Type":"application/json"},body:b}).catch(function(){});}catch(e){}}
function push(ev){q.push(ev);clearTimeout(timer);timer=setTimeout(flush,2000);}
function txt(el){return (el.textContent||"").replace(/\s+/g," ").trim().slice(0,80);}
function list(){
 var a=[].slice.call(document.querySelectorAll("section[id],article[id]")).filter(function(e){return e.id!=="s365s"&&!e.closest("#s365s");});
 a=a.filter(function(e){return !e.querySelector("section[id],article[id]");});
 if(a.length>=3)return {mode:"box",els:a};
 return {mode:"head",els:[].slice.call(document.querySelectorAll("h2[id],h3[id]")).filter(function(e){return !e.closest("#s365s");})};}
function title(el){if(/^H\d$/.test(el.tagName))return txt(el);var h=el.querySelector("h1,h2,h3,h4");return h?txt(h):el.id;}
function current(){var L=list(),mid=window.innerHeight/2,hit=null,i,r;
 for(i=0;i<L.els.length;i++){r=L.els[i].getBoundingClientRect();if(!r.width&&!r.height)continue;
  if(L.mode==="box"){if(r.top<=mid&&r.bottom>mid){hit=L.els[i];break;}}
  else if(r.top<=mid)hit=L.els[i];else break;}
 return hit;}
setInterval(function(){if(document.hidden)return;var el=current();
 if(!el){cur=null;ticks=0;return;}
 if(el!==cur){cur=el;ticks=0;return;}
 if(++ticks===5&&!done[el.id]){done[el.id]=1;push({e:"section",id:el.id,title:title(el)});}},1000);
var st=null;
document.addEventListener("input",function(ev){var el=ev.target;
 if(!el||el.tagName!=="INPUT"||el.closest("#s365s"))return;
 var isSearch=el.type==="search"||/s(ø|oe)g|search/i.test((el.placeholder||"")+" "+(el.id||"")+" "+(el.name||"")+" "+(el.getAttribute("aria-label")||""));
 if(!isSearch)return;clearTimeout(st);
 st=setTimeout(function(){var v=(el.value||"").replace(/\s+/g," ").trim().toLowerCase().slice(0,60);
  if(v.length>=3&&v!==lastQ){lastQ=v;push({e:"search",q:v});}},1500);},true);
window.addEventListener("pagehide",flush);
document.addEventListener("visibilitychange",function(){if(document.hidden)flush();});
})();"""


@app.post("/api/stat")
async def api_stat(req: Request):
    """Tælleren: hvilke afsnit en indlogget bruger har læst, og hvad der er søgt efter. Svarer altid kort og uden indhold."""
    s = session(req)
    if not s or not has_accepted(s[0]):
        return JSONResponse({"detail": "log ind først"}, status_code=401)
    origin = (req.headers.get("origin") or "").rstrip("/")
    if origin and origin != PUBLIC_URL:   # kun fra vores egen side
        return JSONResponse({"error": "origin"}, status_code=403)
    empty = HTMLResponse("", status_code=204)
    if stat_excluded(s[0], s[1]):
        return empty
    try:
        body = await req.body()
        events = json.loads(body).get("events") if len(body) <= 8000 else None
    except Exception:
        events = None
    if not isinstance(events, list):
        return empty
    events = [e for e in events[:20] if isinstance(e, dict)]
    if not events or not stat_rate_ok(s[0], len(events)):
        return empty
    stat_visit(s[0], s[1])
    for e in events:
        if e.get("e") == "section" and re.fullmatch(r"[\w\-:.]{1,80}", str(e.get("id") or "")):
            stat_log(s[0], s[1], "section", id=str(e["id"]), title=_clean_text(e.get("title"), 80))
        elif e.get("e") == "news" and str(e.get("id") or "").isdigit() and e.get("a") in ("seen", "click", "popup", "contact", "close"):
            stat_log(s[0], s[1], "news", id=int(e["id"]), a=e["a"])
        elif e.get("e") == "search":
            term = _clean_text(e.get("q"), 60).lower()
            if len(term) >= 3:
                stat_log(s[0], s[1], "search", q=term)
    return empty


@app.get("/api/stat.js")
def api_stat_js(req: Request):
    s = session(req)
    if not s or not has_accepted(s[0]) or stat_excluded(s[0], s[1]):
        return HTMLResponse("", status_code=401, media_type="application/javascript")
    return HTMLResponse(STAT_JS, media_type="application/javascript", headers={"Cache-Control": "private, max-age=300"})


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
    if is_html:
        stat_visit(s[0], s[1])
    tags = ('<script src="/api/status.js" defer></script>' if UPTIME_URL else "") + \
           ('<script src="/api/nyheder.js" defer></script>' if NEWS_ON else "") + \
           ('<script src="/api/stat.js" defer></script>' if not stat_excluded(s[0], s[1]) else "")
    if is_html and tags:
        with open(full, encoding="utf-8", errors="replace") as f:
            doc = f.read()
        doc = doc.replace("</body>", tags + "</body>", 1) if "</body>" in doc else doc + tags
        return HTMLResponse(doc, headers={"Cache-Control": "private, no-cache", "X-Robots-Tag": "noindex, nofollow"})
    return FileResponse(full, media_type=mimetypes.guess_type(full)[0] or "application/octet-stream",
                        headers={"Cache-Control": "private, no-cache" if is_html else "private, max-age=86400",
                                 "X-Robots-Tag": "noindex, nofollow"})
