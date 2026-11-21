"""Nyheder i guiden (Fangarr 1.24.0) – det farvede kort øverst på guide.stream365.vip og nyhedens pop-up.

Du skriver nyhederne under Guide › Nyheder. Guiden (appen `nyt`) henter dem selv hos Fangarr hvert 30. sekund inde i
Docker-netværket (`http://fangarr:8080/api/nyheder/guide`) og viser dem for kunder, der er logget ind. Der skal ikke
ændres noget i docker-compose-filerne, og guidens egen side (index.html) røres ikke.

- Fangarr laver alt det, kunderne ser: farver, illustrationer og selve tegningen af kortet og pop-up'en
  (`static/nyhed-vis.js`). Guiden får tegningen med, så forhåndsvisningen i Fangarr er præcis det, kunderne ser.
- Guiden sender listen over sine afsnit (`<section id>`) med, når den henter. Den bruges til "Knappen fører til afsnit"
  og "Læs også", og Fangarr advarer, hvis et afsnit forsvinder fra guiden.
- Guiden gemmer seneste svar i /opt/nyt/data/nyheder.json, så nyhederne bliver vist, også når Fangarr genstarter.
- Hvor mange der har set og trykket, kommer fra guidens tæller (samme mapper som fanen Guide – kræver /guide-stat).
- Ingen kundedata sendes til guiden. Adressen svarer kun med nyheder, der er udgivet.
"""
import datetime
import hashlib
import json
import math
import os
import re
import threading
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/nyheder")
D = {}   # udfyldes af main.py: db, now, kv_get, kv_set, log, stat_events (fra guide.py)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
SETTINGS_KEY, GUIDE_KEY = "nyheder_settings", "nyheder_guide"
DEFAULTS = {"messenger": "", "telegram": "", "contact_label": "Skriv til os", "new_days": 14}
_lock = threading.Lock()
MONTHS = ["januar", "februar", "marts", "april", "maj", "juni", "juli", "august", "september", "oktober", "november", "december"]

# ---------------------------------------------------------------- skabeloner (farver) og illustrationer

THEMES = {
    "tilbud": {"name": "Tilbud", "bg": "#58D9AE", "ink": "#06110D", "sub": "#0E2A21", "pillBg": "#06110D", "pillInk": "#58D9AE",
               "btnBg": "#0B0C0E", "btnInk": "#FFFFFF", "chip": "rgba(6,17,13,.1)", "border": "none",
               "accent": "#58D9AE", "accentInk": "#06110D", "obj": "#0B0C0E", "objHi": "#58D9AE", "objTx": "#FFFFFF", "deco": "#06110D",
               "ex": {"title": "Forlæng 12 måneder – få 2 med i købet", "text": "Black Friday hos Stream365. Læs her, hvordan du får de to ekstra måneder.",
                      "btn": "Sådan får du tilbuddet", "art": "billet"}},
    "nyhed": {"name": "Nyhed", "bg": "#13201B", "ink": "#FFFFFF", "sub": "#B4BABE", "pillBg": "#58D9AE", "pillInk": "#06110D",
              "btnBg": "#58D9AE", "btnInk": "#06110D", "chip": "rgba(255,255,255,.08)", "border": "2px solid #58D9AE",
              "accent": "#58D9AE", "accentInk": "#06110D", "obj": "#58D9AE", "objHi": "#06110D", "objTx": "#06110D", "deco": "#58D9AE",
              "ex": {"title": "Ny række: Top i Danmark lige nu", "text": "Det, danskerne ser mest lige nu, samlet på Anbefalet i Film og Serier.",
                     "btn": "Se hvor du finder den", "art": "raekke"}},
    "jul": {"name": "Jul", "bg": "#B8323F", "ink": "#FFFFFF", "sub": "#FBE3E6", "pillBg": "#F6C453", "pillInk": "#2A0A0F",
            "btnBg": "#F6C453", "btnInk": "#2A0A0F", "chip": "rgba(255,255,255,.14)", "border": "none",
            "accent": "#F6C453", "accentInk": "#2A0A0F", "obj": "#F6C453", "objHi": "#B8323F", "objTx": "#2A0A0F", "deco": "#FFFFFF",
            "ex": {"title": "Julekalenderne er klar", "text": "Alle de klassiske julekalendere ligger klar til 1. december.",
                   "btn": "Vis mig julekalenderne", "art": "kalender"}},
    "vigtigt": {"name": "Vigtig besked", "bg": "#F4B740", "ink": "#1D1404", "sub": "#3A2A08", "pillBg": "#1D1404", "pillInk": "#F4B740",
                "btnBg": "#1D1404", "btnInk": "#F4B740", "chip": "rgba(29,20,4,.1)", "border": "none",
                "accent": "#F4B740", "accentInk": "#1D1404", "obj": "#1D1404", "objHi": "#F4B740", "objTx": "#FFFFFF", "deco": "#1D1404",
                "ex": {"title": "Nye regler fra 1. januar", "text": "Vi har gjort reglerne for skærme og afspilninger tydeligere. Læs dem her.",
                       "btn": "Læs de nye regler", "art": "besked"}},
}
COLOR_KEYS = ("bg", "ink", "sub", "pillBg", "pillInk", "btnBg", "btnInk", "chip", "border", "accent", "accentInk")


def _waves(c):
    return "".join(f'<path d="M196 {y}q20-14 40 0t40 0t40 0t40 0" fill="none" stroke="{c["deco"]}" stroke-opacity=".16" stroke-width="7" stroke-linecap="round"/>'
                   for y in (44, 68, 92))


def _spark(x, y, r, c, op=".4"):
    return (f'<path d="M{x} {y - r}Q{x} {y} {x + r} {y}Q{x} {y} {x} {y + r}Q{x} {y} {x - r} {y}Q{x} {y} {x} {y - r}Z" '
            f'fill="{c["deco"]}" fill-opacity="{op}"/>')


def _text_w(t, size):
    """Groft skøn over bredden af en tekst i Outfit (fed)."""
    w = 0.0
    for ch in t:
        w += 0.36 if ch in " .,:;'!|il1" else 0.75 if ch in "MWmw%@" else 0.62 if ch.isupper() or ch.isdigit() else 0.56
    return w * size


def _art_billet(c, t):
    raw1, raw2, raw3 = (t.get(k, "") for k in ("t1", "t2", "t3"))
    t1, t2, t3 = (xml_escape(x) for x in (raw1, raw2, raw3))
    shape = (f'<path d="M0 14a14 14 0 0 1 14-14h172a14 14 0 0 1 14 14v22a12 12 0 0 0 0 24v22a14 14 0 0 1-14 14H14A14 14 0 0 1 0 82V60a12 12 0 0 0 0-24z" '
             f'fill="{c["obj"]}"/>')
    font = 'font-family="Outfit, sans-serif"'
    txt = []
    s1 = 54
    while raw1 and _text_w(raw1, s1) > 120 and s1 > 26:
        s1 -= 2
    x2 = 18 + (_text_w(raw1, s1) + 14 if raw1 else 0)
    s2 = 16 if raw1 else 22
    while max(_text_w(raw2, s2), _text_w(raw3, s2)) > 188 - x2 and s2 > 10:
        s2 -= 1
    if raw1 and (raw2 or raw3) and s2 < 13:
        # lang stor tekst: den små tekst på én linje under den store
        s1 = 46
        while _text_w(raw1, s1) > 164 and s1 > 26:
            s1 -= 2
        small = (raw2 + " " + raw3).strip()
        s2 = 15
        while _text_w(small, s2) > 164 and s2 > 9:
            s2 -= 1
        txt.append(f'<text x="18" y="54" {font} font-weight="800" font-size="{s1}" fill="{c["objHi"]}">{t1}</text>')
        txt.append(f'<text x="18" y="78" {font} font-weight="700" font-size="{s2}" fill="{c["objTx"]}">{xml_escape(small)}</text>')
    else:
        if raw1:
            txt.append(f'<text x="18" y="{48 + s1 * 0.37:.0f}" {font} font-weight="800" font-size="{s1}" fill="{c["objHi"]}">{t1}</text>')
        y2, y3 = ((44, 64) if raw1 else (45, 71)) if raw3 else ((56, 0) if raw1 else (58, 0))
        if raw2:
            txt.append(f'<text x="{x2:.0f}" y="{y2}" {font} font-weight="700" font-size="{s2}" fill="{c["objTx"]}">{t2}</text>')
        if raw3:
            txt.append(f'<text x="{x2:.0f}" y="{y3}" {font} font-weight="700" font-size="{s2}" fill="{c["objTx"]}">{t3}</text>')
    return _waves(c) + '<g transform="translate(20 22) rotate(-4 100 48)">' + shape + "".join(txt) + "</g>"


def _art_gave(c, t):
    return (_waves(c) + '<g transform="translate(52 8)">'
            f'<rect x="8" y="46" width="124" height="66" rx="10" fill="{c["obj"]}"/>'
            f'<rect x="0" y="28" width="140" height="24" rx="8" fill="{c["obj"]}"/>'
            f'<path d="M70 29C62 8 34 2 34 18c0 12 24 12 36 11z" fill="{c["obj"]}"/>'
            f'<path d="M70 29c8-21 36-27 36-11 0 12-24 12-36 11z" fill="{c["obj"]}"/>'
            f'<rect x="62" y="28" width="16" height="84" fill="{c["objTx"]}" fill-opacity=".9"/>'
            f'<rect x="0" y="40" width="140" height="6" fill="{c["objTx"]}" fill-opacity=".25"/>'
            f'<circle cx="70" cy="27" r="8" fill="{c["objTx"]}"/>'
            "</g>" + _spark(36, 34, 9, c) + _spark(214, 26, 7, c) + _spark(206, 108, 6, c))


def _art_kalender(c, t):
    doors = []
    n = [7, 18, 3, 11, 21, 5, 24, 14, 9, 16, 1, 20]
    for r in range(3):
        for col in range(4):
            x, y, k = 12 + col * 40, 12 + r * 28, r * 4 + col
            if (r, col) == (1, 2):
                doors.append(f'<rect x="{x}" y="{y}" width="34" height="22" rx="5" fill="{c["objHi"]}"/>'
                             f'<text x="{x + 17}" y="{y + 16.5}" text-anchor="middle" font-family="Outfit, sans-serif" font-weight="800" font-size="15" fill="{c["obj"]}">24</text>')
            else:
                doors.append(f'<rect x="{x}" y="{y}" width="34" height="22" rx="5" fill="{c["objTx"]}" fill-opacity=".14"/>'
                             f'<text x="{x + 17}" y="{y + 15}" text-anchor="middle" font-family="Outfit, sans-serif" font-weight="700" font-size="10" fill="{c["objTx"]}" fill-opacity=".55">{n[k] if n[k] != 24 else 2}</text>')
    return (_waves(c) + '<g transform="translate(22 14) rotate(-3 88 50)">'
            f'<rect width="176" height="100" rx="14" fill="{c["obj"]}"/>' + "".join(doors) + "</g>"
            + _spark(214, 22, 8, c) + _spark(226, 106, 6, c))


def _art_raekke(c, t):
    out = [_waves(c), '<g transform="translate(18 20)">']
    for i, (x, op) in enumerate(((0, "1"), (62, ".78"), (124, ".56"))):
        out.append(f'<rect x="{x}" y="0" width="54" height="80" rx="8" fill="{c["obj"]}" fill-opacity="{op}"/>')
    out.append(f'<path d="M20 36l18 10-18 10z" fill="{c["objHi"]}"/>')
    out.append(f'<rect x="6" y="6" width="34" height="20" rx="10" fill="{c["objHi"]}"/>'
               f'<text x="23" y="20.2" text-anchor="middle" font-family="Outfit, sans-serif" font-weight="800" font-size="11.5" fill="{c["obj"]}">NY</text>')
    out.append(f'<rect x="0" y="90" width="178" height="7" rx="3.5" fill="{c["deco"]}" fill-opacity=".22"/>'
               f'<rect x="0" y="90" width="64" height="7" rx="3.5" fill="{c["obj"]}"/>')
    out.append("</g>")
    return "".join(out)


def _star(cx, cy, r1, r2, n=5):
    pts = []
    for i in range(n * 2):
        a = -math.pi / 2 + i * math.pi / n
        r = r1 if i % 2 == 0 else r2
        pts.append(f"{cx + r * math.cos(a):.1f},{cy + r * math.sin(a):.1f}")
    return "M" + "L".join(pts) + "Z"


def _art_oenske(c, t):
    return (_waves(c) + f'<path d="{_star(104, 66, 54, 24)}" fill="{c["obj"]}" stroke="{c["obj"]}" stroke-width="8" stroke-linejoin="round"/>'
            f'<circle cx="160" cy="30" r="20" fill="{c["objTx"]}"/>'
            f'<path d="M160 20v20M150 30h20" stroke="{c["obj"]}" stroke-width="4.5" stroke-linecap="round"/>'
            + _spark(34, 30, 8, c) + _spark(196, 104, 7, c))


def _art_tekster(c, t):
    return (_waves(c) + '<g transform="translate(20 9)">'
            f'<rect width="180" height="100" rx="12" fill="{c["obj"]}"/>'
            f'<rect x="40" y="62" width="100" height="9" rx="4.5" fill="{c["objTx"]}"/>'
            f'<rect x="56" y="78" width="68" height="9" rx="4.5" fill="{c["objTx"]}" fill-opacity=".65"/>'
            f'<rect x="12" y="12" width="44" height="26" rx="8" fill="{c["objHi"]}"/>'
            f'<text x="34" y="30" text-anchor="middle" font-family="Outfit, sans-serif" font-weight="800" font-size="14" fill="{c["obj"]}">DA</text>'
            f'<rect x="70" y="104" width="40" height="8" rx="4" fill="{c["obj"]}"/>'
            "</g>")


def _art_download(c, t):
    return (_waves(c) + '<g transform="translate(70 6)">'
            f'<rect width="72" height="116" rx="14" fill="{c["obj"]}"/>'
            f'<rect x="8" y="12" width="56" height="88" rx="6" fill="{c["objTx"]}" fill-opacity=".12"/>'
            f'<path d="M36 30v40M22 56l14 14 14-14" stroke="{c["objHi"]}" stroke-width="7" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<path d="M22 84h28" stroke="{c["objHi"]}" stroke-width="7" stroke-linecap="round"/>'
            "</g>" + _spark(40, 36, 8, c) + _spark(170, 100, 7, c))


def _art_film(c, t):
    stripes = "".join(f'<path d="M{x} 7h16l-9 22h-16z" fill="{c["objHi"]}"/>' for x in (22, 54, 86, 118))
    return (_waves(c) + '<g transform="translate(34 26)">'
            f'<rect x="0" y="34" width="156" height="64" rx="10" fill="{c["obj"]}"/>'
            f'<g transform="rotate(-11 4 32)"><rect x="0" y="6" width="156" height="24" rx="6" fill="{c["obj"]}"/>{stripes}</g>'
            f'<rect x="16" y="54" width="76" height="9" rx="4.5" fill="{c["objTx"]}" fill-opacity=".55"/>'
            f'<rect x="16" y="72" width="50" height="9" rx="4.5" fill="{c["objTx"]}" fill-opacity=".35"/>'
            f'<circle cx="128" cy="68" r="16" fill="{c["objHi"]}"/><path d="M123 60l14 8-14 8z" fill="{c["obj"]}"/>'
            "</g>")


def _art_besked(c, t):
    return (_waves(c) + '<g transform="translate(40 18)">'
            f'<rect x="0" y="34" width="28" height="38" rx="7" fill="{c["obj"]}"/>'
            f'<path d="M24 36 104 4v100L24 70z" fill="{c["obj"]}" stroke="{c["obj"]}" stroke-width="6" stroke-linejoin="round"/>'
            f'<path d="M30 70l9 26h16l-8-26" fill="{c["obj"]}"/>'
            f'<path d="M124 34q12 20 0 40" stroke="{c["obj"]}" stroke-opacity=".6" stroke-width="7" fill="none" stroke-linecap="round"/>'
            f'<path d="M142 20q24 34 0 68" stroke="{c["obj"]}" stroke-opacity=".35" stroke-width="7" fill="none" stroke-linecap="round"/>'
            "</g>")


ARTS = {
    "billet": ("Billet med din tekst", _art_billet),
    "gave": ("Gave", _art_gave),
    "kalender": ("Julekalender", _art_kalender),
    "raekke": ("Ny række", _art_raekke),
    "oenske": ("Seerr-ønske", _art_oenske),
    "tekster": ("Danske tekster", _art_tekster),
    "download": ("Download", _art_download),
    "film": ("Film", _art_film),
    "besked": ("Vigtig besked", _art_besked),
}


def art_svg(key, theme, texts=None):
    """Illustrationen som SVG i skabelonens farver. Tom tekst = ingen illustration."""
    if key not in ARTS:
        return ""
    c = THEMES.get(theme) or THEMES["tilbud"]
    body = ARTS[key][1](c, texts or {})
    label = xml_escape(ARTS[key][0])
    return f'<svg viewBox="0 0 358 128" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{label}" focusable="false">{body}</svg>'


def gallery(theme, texts=None):
    return [{"key": k, "name": v[0], "svg": art_svg(k, theme, texts)} for k, v in ARTS.items()]


# ---------------------------------------------------------------- data

def setup(**deps):
    D.update(deps)


def init():
    con = D["db"]()
    with con:
        con.execute("CREATE TABLE IF NOT EXISTS g_news (id INTEGER PRIMARY KEY AUTOINCREMENT, sort INTEGER DEFAULT 0, published INTEGER DEFAULT 0,"
                    " data TEXT, created TEXT, updated TEXT, published_at TEXT)")
    con.close()


def settings():
    s = dict(DEFAULTS)
    s.update(D["kv_get"](SETTINGS_KEY, {}) or {})
    return s


def guide_info():
    return D["kv_get"](GUIDE_KEY, {}) or {}


def _rows():
    con = D["db"]()
    try:
        return [dict(r) for r in con.execute("SELECT * FROM g_news ORDER BY sort, id").fetchall()]
    finally:
        con.close()


def _row(nid):
    con = D["db"]()
    try:
        r = con.execute("SELECT * FROM g_news WHERE id=?", (nid,)).fetchone()
    finally:
        con.close()
    if not r:
        raise HTTPException(404, "nyheden findes ikke")
    return dict(r)


def _parse_dt(v):
    """'2026-11-21T08:00' (dansk tid) → datetime. Tom = None."""
    v = str(v or "").strip()
    if not v:
        return None
    try:
        return datetime.datetime.fromisoformat(v[:16])
    except ValueError:
        raise HTTPException(400, f"ugyldig dato: {v}") from None


def _ts(dt):
    return int(dt.timestamp()) if dt else None   # containeren kører med dansk tid, så datoen tolkes som dansk tid


def _day_text(dt):
    if not dt:
        return ""
    s = f"{dt.day}. {MONTHS[dt.month - 1]}"
    if dt.year != D["now"]().year:
        s += f" {dt.year}"
    if (dt.hour, dt.minute) not in ((23, 59), (0, 0)):
        s += f" kl. {dt.strftime('%H:%M')}"
    return s


def _txt(v, n):
    v = str(v or "").replace("\r\n", "\n").replace("\r", "\n")
    v = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", v)
    v = re.sub(r"\n{3,}", "\n\n", v).strip()
    return v[:n]


def clean(d):
    """Det, der må gemmes – alt andet smides væk. Rejser fejl med en dansk forklaring."""
    d = d if isinstance(d, dict) else {}
    theme = d.get("theme") if d.get("theme") in THEMES else "tilbud"
    action = d.get("action") if d.get("action") in ("popup", "section", "none") else "popup"
    art = d.get("art") if d.get("art") in ARTS else ""
    p = d.get("popup") if isinstance(d.get("popup"), dict) else {}
    steps = []
    for s in (p.get("steps") if isinstance(p.get("steps"), list) else [])[:8]:
        if isinstance(s, dict) and (str(s.get("title") or "").strip() or str(s.get("text") or "").strip()):
            steps.append({"title": _txt(s.get("title"), 80), "text": _txt(s.get("text"), 400), "art": s.get("art") if s.get("art") in ARTS else ""})
    out = {
        "theme": theme, "tag": _txt(d.get("tag"), 24) or THEMES[theme]["name"],
        "title": _txt(d.get("title"), 100), "text": _txt(d.get("text"), 300), "btn": _txt(d.get("btn"), 40),
        "action": action, "section": _txt(d.get("section"), 80) if action == "section" else "",
        "art": art, "art_t1": _txt(d.get("art_t1"), 6), "art_t2": _txt(d.get("art_t2"), 18), "art_t3": _txt(d.get("art_t3"), 18),
        "start": str(d.get("start") or "")[:16], "end": str(d.get("end") or "")[:16],
        "countdown": bool(d.get("countdown")), "closable": d.get("closable", True) is not False, "only_new": bool(d.get("only_new")),
        "popup": {"title": _txt(p.get("title"), 100), "price": _txt(p.get("price"), 24), "price_sub": _txt(p.get("price_sub"), 80),
                  "intro": _txt(p.get("intro"), 600), "steps": steps, "read": _txt(p.get("read"), 80),
                  "contact": p.get("contact", True) is not False, "close": _txt(p.get("close"), 30) or "Forstået"},
    }
    start, end = _parse_dt(out["start"]), _parse_dt(out["end"])
    out["start"] = start.isoformat(timespec="minutes") if start else ""
    out["end"] = end.isoformat(timespec="minutes") if end else ""
    return out


def problems(d, for_publish=True):
    """Det, der mangler, før nyheden kan udgives (tom liste = klar)."""
    out = []
    if not d["title"]:
        out.append("Skriv en overskrift.")
    if d["action"] != "none" and not d["btn"]:
        out.append("Skriv en tekst på knappen – eller vælg Ingen knap.")
    if d["action"] == "section" and not d["section"]:
        out.append("Vælg hvilket afsnit i guiden knappen fører til.")
    if not d["start"]:
        out.append("Vælg hvornår nyheden skal vises fra.")
    if d["countdown"] and not d["end"]:
        out.append("Nedtællingen kræver en slutdato.")
    s, e = _parse_dt(d["start"]), _parse_dt(d["end"])
    if s and e and e <= s:
        out.append("Slutdatoen skal ligge efter startdatoen.")
    if for_publish and e and e <= D["now"]():
        out.append("Slutdatoen er allerede passeret.")
    if d["action"] == "popup" and not (d["popup"]["intro"] or d["popup"]["steps"] or d["popup"]["price"]):
        out.append("Pop-up'en er tom – skriv en indledning, en pris eller mindst ét trin.")
    return out


def status_of(row, d=None, now=None):
    d = d or json.loads(row["data"])
    now = now or D["now"]()
    if not row["published"]:
        return "kladde"
    s, e = _parse_dt(d.get("start")), _parse_dt(d.get("end"))
    if e and e <= now:
        return "udloebet"
    if s and s > now:
        return "planlagt"
    return "aktiv"


def _sections():
    return {s["id"]: s["title"] for s in (guide_info().get("sections") or []) if isinstance(s, dict) and s.get("id")}


def build(d, nid=0):
    """Nyheden, som guiden (og forhåndsvisningen) får den – farver og illustrationer er lavet færdige."""
    t = THEMES[d["theme"]]
    secs = _sections()
    texts = {"t1": d.get("art_t1", ""), "t2": d.get("art_t2", ""), "t3": d.get("art_t3", "")}
    p = d["popup"]
    s, e = _parse_dt(d["start"]), _parse_dt(d["end"])
    item = {
        "id": nid, "theme": d["theme"], "colors": {k: t[k] for k in COLOR_KEYS}, "tag": d["tag"],
        "title": d["title"], "text": d["text"], "btn": d["btn"] if d["action"] != "none" else "", "action": d["action"],
        "section": d["section"], "section_title": secs.get(d["section"], ""),
        "art": art_svg(d["art"], d["theme"], texts),
        "start_ts": _ts(s), "end_ts": _ts(e), "end_text": _day_text(e),
        "countdown": bool(d["countdown"] and e), "closable": d["closable"], "only_new": d["only_new"],
        "popup": None,
    }
    if d["action"] == "popup":
        item["popup"] = {"title": p["title"] or d["title"], "price": p["price"], "price_sub": p["price_sub"], "intro": p["intro"],
                         "steps": [{"title": x["title"], "text": x["text"], "art": art_svg(x["art"], d["theme"])} for x in p["steps"]],
                         "read": {"id": p["read"], "title": secs.get(p["read"], "")} if p["read"] else None,
                         "contact": p["contact"], "close": p["close"], "art": item["art"]}
    return item


def contact():
    s = settings()
    links = {k: s[k] for k in ("messenger", "telegram") if str(s.get(k) or "").startswith("https://")}
    return {"label": s.get("contact_label") or "Skriv til os", **links} if links else None


def renderer():
    with open(os.path.join(STATIC_DIR, "nyhed-vis.js"), encoding="utf-8") as f:
        return f.read()


def live():
    """Udgivne nyheder, der ikke er udløbet – guiden viser selv hver nyhed fra start til slut."""
    now = D["now"]()
    out = []
    for r in _rows():
        if not r["published"]:
            continue
        d = clean(json.loads(r["data"]))
        e = _parse_dt(d["end"])
        if e and e <= now:
            continue
        out.append(build(d, r["id"]))
    return out


# ---------------------------------------------------------------- tal fra guidens tæller

def stats(days=90):
    """Pr. nyhed: hvor mange forskellige brugere har set den, trykket på knappen, åbnet pop-up'en og trykket Skriv til os."""
    fn = D.get("stat_events")
    if not fn:
        return None, False
    try:
        ok = bool(D.get("stat_enabled") and D["stat_enabled"]())
        evs = fn(days) if ok else []
    except Exception:
        return None, False
    out = {}
    for r in evs:
        if r.get("e") != "news":
            continue
        try:
            nid = int(r.get("id"))
        except (TypeError, ValueError):
            continue
        x = out.setdefault(nid, {"seen": set(), "click": set(), "popup": set(), "contact": set(), "close": set()})
        a = r.get("a")
        if a in x:
            x[a].add(str(r.get("uid")))
    return {k: {a: len(v) for a, v in x.items()} for k, x in out.items()}, ok


# ---------------------------------------------------------------- adresser

def _item_out(r, st, secs, now):
    d = clean(json.loads(r["data"]))
    warn = []
    if secs:
        for sid, what in ((d["section"], "Knappen"), (d["popup"]["read"] if d["action"] == "popup" else "", "\"Læs også\"")):
            if sid and sid not in secs:
                warn.append(f"{what} fører til et afsnit, der ikke længere findes i guiden ({sid}).")
    return {"id": r["id"], "published": bool(r["published"]), "status": status_of(r, d, now), "data": d, "sort": r["sort"],
            "created": r["created"], "updated": r["updated"], "published_at": r["published_at"],
            "stats": (st or {}).get(r["id"]), "warnings": warn, "problems": problems(d, False)}


@router.get("")
def list_news():
    now = D["now"]()
    st, stat_ok = stats()
    secs = _sections()
    g = guide_info()
    seen = g.get("seen")
    age = None
    if seen:
        try:
            age = int((now - datetime.datetime.fromisoformat(seen)).total_seconds())
        except ValueError:
            age = None
    return {"items": [_item_out(r, st, secs, now) for r in _rows()],
            "themes": {k: {"name": v["name"], "bg": v["bg"], "ink": v["ink"], "border": v["border"], "ex": v["ex"]} for k, v in THEMES.items()},
            "arts": [{"key": k, "name": v[0]} for k, v in ARTS.items()],
            "sections": [{"id": k, "title": v} for k, v in secs.items()],
            "guide": {"seen": seen, "age": age, "ok": age is not None and age < 300, "site": bool(g.get("sections"))},
            "settings": settings(), "contact": contact(), "stat_ok": stat_ok}


@router.get("/gallery")
def gallery_get(theme: str = "tilbud", t1: str = "", t2: str = "", t3: str = ""):
    return gallery(theme if theme in THEMES else "tilbud", {"t1": t1[:6], "t2": t2[:18], "t3": t3[:18]})


@router.post("/preview")
async def preview(req: Request):
    d = clean(await req.json())
    return {"item": build(d, 0), "contact": contact(), "problems": problems(d)}


def _save(nid, d, publish=None):
    now = D["now"]().isoformat(timespec="seconds")
    with _lock:
        con = D["db"]()
        try:
            with con:
                if nid:
                    con.execute("UPDATE g_news SET data=?, updated=? WHERE id=?", (json.dumps(d, ensure_ascii=False), now, nid))
                else:
                    top = con.execute("SELECT MIN(sort) m FROM g_news").fetchone()["m"]
                    nid = con.execute("INSERT INTO g_news (sort, published, data, created, updated) VALUES (?,?,?,?,?)",
                                      ((top or 0) - 1, 0, json.dumps(d, ensure_ascii=False), now, now)).lastrowid
                if publish is not None:
                    con.execute("UPDATE g_news SET published=?, published_at=CASE WHEN ? THEN ? ELSE published_at END WHERE id=?",
                                (1 if publish else 0, 1 if publish else 0, now, nid))
        finally:
            con.close()
    return nid


@router.post("")
async def create(req: Request):
    b = await req.json()
    d = clean(b.get("data"))
    publish = bool(b.get("publish"))
    if publish and problems(d):
        raise HTTPException(400, " ".join(problems(d)))
    nid = _save(0, d, publish)
    D["log"].info("Nyheder: %s \"%s\"", "udgivet" if publish else "kladde gemt", d["title"])
    return {"id": nid, "message": "Udgivet – kunderne ser den inden for et minut." if publish else "Gemt som kladde."}


@router.put("/{nid:int}")
async def update(nid: int, req: Request):
    r = _row(nid)
    b = await req.json()
    d = clean(b.get("data"))
    publish = b.get("publish")   # True = udgiv, False = skjul for kunderne, None = som før
    if (publish is True or (publish is None and r["published"])) and problems(d):
        raise HTTPException(400, " ".join(problems(d)))
    _save(nid, d, None if publish is None else bool(publish))
    pub = r["published"] if publish is None else bool(publish)
    D["log"].info("Nyheder: \"%s\" gemt (%s)", d["title"], "udgivet" if pub else "kladde")
    msg = ("Udgivet – kunderne ser den inden for et minut." if publish is True else
           "Skjult for kunderne – nyheden er nu en kladde." if publish is False else
           "Gemt – kunderne ser ændringen inden for et minut." if pub else "Gemt som kladde.")
    return {"id": nid, "message": msg}


@router.post("/{nid:int}/copy")
def copy(nid: int):
    d = clean(json.loads(_row(nid)["data"]))
    d["title"] = (d["title"] + " (kopi)")[:100]
    return {"id": _save(0, d, False), "message": "Kopieret som kladde."}


@router.delete("/{nid:int}")
def delete(nid: int):
    r = _row(nid)
    con = D["db"]()
    with con:
        con.execute("DELETE FROM g_news WHERE id=?", (nid,))
    con.close()
    D["log"].info("Nyheder: \"%s\" slettet", json.loads(r["data"]).get("title"))
    return {"message": "Slettet."}


@router.post("/order")
async def order(req: Request):
    ids = [int(x) for x in ((await req.json()).get("ids") or []) if str(x).isdigit()]
    with _lock:
        con = D["db"]()
        with con:
            for i, nid in enumerate(ids):
                con.execute("UPDATE g_news SET sort=? WHERE id=?", (i, nid))
        con.close()
    return {"message": "Rækkefølgen er gemt."}


@router.put("/settings")
async def settings_put(req: Request):
    b = await req.json()
    s = settings()
    for k in ("messenger", "telegram"):
        if k in b:
            v = str(b[k] or "").strip()
            if v and not re.fullmatch(r"https://[^\s\"'<>]{4,300}", v):
                raise HTTPException(400, f"Linket til {'Messenger' if k == 'messenger' else 'Telegram'} skal begynde med https://")
            s[k] = v
    if "contact_label" in b:
        s["contact_label"] = _txt(b["contact_label"], 30) or "Skriv til os"
    if "new_days" in b:
        try:
            s["new_days"] = max(1, min(int(b["new_days"]), 90))
        except (TypeError, ValueError):
            raise HTTPException(400, "Antal dage skal være et tal") from None
    D["kv_set"](SETTINGS_KEY, s)
    return {"message": "Gemt.", "settings": s}


@router.post("/guide")
async def guide_pull(req: Request):
    """Kaldes af guiden (appen nyt) hvert 30. sekund inde i Docker-netværket. Guiden sender sine afsnit med og får
    de udgivne nyheder, kontaktlinks og tegningen (nyhed-vis.js) tilbage."""
    try:
        b = await req.json()
    except Exception:
        b = {}
    secs = []
    for s in (b.get("sections") if isinstance(b, dict) and isinstance(b.get("sections"), list) else [])[:80]:
        if isinstance(s, dict) and re.fullmatch(r"[\w\-:.]{1,80}", str(s.get("id") or "")):
            secs.append({"id": str(s["id"]), "title": _txt(s.get("title"), 80) or str(s["id"])})
    g = guide_info()
    now = D["now"]()
    changed = secs and secs != g.get("sections")
    last = g.get("seen")
    stale = True
    if last:
        try:
            stale = (now - datetime.datetime.fromisoformat(last)).total_seconds() > 120
        except ValueError:
            pass
    if changed or stale:   # skriv kun til databasen, når noget er ændret, eller højst hvert 2. minut
        D["kv_set"](GUIDE_KEY, {"sections": secs or g.get("sections") or [], "seen": now.isoformat(timespec="seconds")})
    js = renderer()
    return {"ok": True, "news": live(), "contact": contact(), "new_days": settings()["new_days"],
            "js": js, "js_v": hashlib.sha1(js.encode()).hexdigest()[:10], "generated": now.isoformat(timespec="seconds")}


def brief():
    """Til forsiden: antal aktive nyheder og om guiden henter dem."""
    try:
        rows = _rows()
    except Exception:
        return None
    now = D["now"]()
    active = sum(1 for r in rows if status_of(r, None, now) == "aktiv")
    return {"active": active, "total": len(rows)}
