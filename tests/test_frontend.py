"""Tjek af siden uden browser: alle knapper kalder funktioner, der findes, og alle faste felter findes.

Fanger de typiske fejl, når siden flyttes rundt: en knap, der kalder en funktion, som ikke længere findes,
eller JavaScript, der leder efter et felt (id), som er fjernet fra index.html.
"""

import os
import re

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "static")


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


HTML = _read(os.path.join(STATIC, "index.html"))
JS_FILES = re.findall(r'<script src="/static/(js/[^"?]+)', HTML)
JS = {f: _read(os.path.join(STATIC, f)) for f in JS_FILES}
ALL_JS = "\n".join(JS.values()) + _read(os.path.join(STATIC, "nyhed-vis.js"))
SECTIONS = re.findall(r'<section id="([^"]+)"', HTML)


def _defined():
    names = set(re.findall(r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", ALL_JS))
    names |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", ALL_JS))
    names |= set(re.findall(r"(?:const|let|var)\s+[^;=]*?,\s*([A-Za-z_$][\w$]*)\s*=", ALL_JS))
    return names | {"event", "this", "document", "window", "if", "return", "confirm", "history", "location", "String", "Number"}


def test_all_js_files_exist():
    assert len(JS_FILES) >= 10
    for f in JS_FILES:
        assert os.path.exists(os.path.join(STATIC, f)), f
    assert os.path.exists(os.path.join(STATIC, "fangarr.css"))


def test_handlers_exist():
    names = _defined()
    src = HTML + ALL_JS
    calls = set()
    for h in re.findall(r'on(?:click|change|input|keydown)="([^"]+)"', src):
        for m in re.finditer(r"(?:^|[;\s(])([A-Za-z_$][\w$]*)\s*\(", h):
            calls.add(m.group(1))
    missing = sorted(c for c in calls if c not in names and not c.startswith("$"))
    assert not missing, f"knapper kalder funktioner, der ikke findes: {missing}"


def test_ids_exist():
    ids = set(re.findall(r'\bid="([^"$]+)"', HTML)) | set(re.findall(r'\bid="([^"$]+)"', ALL_JS))
    used = set(re.findall(r'\$\("([A-Za-z0-9_-]+)"\)', ALL_JS)) | set(re.findall(r"getElementById\('([A-Za-z0-9_-]+)'\)", ALL_JS))
    created_in_js = set(re.findall(r'id="([A-Za-z0-9_-]+)"', ALL_JS))
    missing = sorted(i for i in used if i not in ids and i not in created_in_js)
    assert not missing, f"JavaScript bruger felter, der ikke findes i index.html: {missing}"


def test_every_section_has_description():
    hj = JS["js/hjaelp.js"]
    for sec in SECTIONS:
        if sec == "search":
            continue
        assert f'data-hj="{sec}"' in HTML, f"siden {sec} mangler sin beskrivelse (data-hj)"
        assert re.search(rf"\b{sec}: \{{navn:", hj), f"hjaelp.js mangler teksten til {sec}"
    for p, s in re.findall(r'data-hjs="([a-z]+)/([a-z]+)"', HTML):
        assert re.search(rf"\b{s}:\s*\"", hj), f"hjaelp.js mangler underfanen {p}/{s}"


def test_menu_matches_plan():
    """Menuen fra planen (afsnit 3): 14 punkter + Hjælp, og bundmenuen på telefonen."""
    side = HTML[HTML.index('<aside id="side"'):HTML.index("</aside>")]
    tabs = re.findall(r'data-tab="([a-z]+)"', side)
    assert tabs == ["home", "log", "wait", "tr", "bib", "rules", "cust", "pay", "besk", "oensker", "share", "guide", "drift", "settings", "hjaelp"]
    bbar = HTML[HTML.index('<nav class="bbar"'):HTML.index("</nav>")]
    assert re.findall(r'data-tab="([a-z]+)"', bbar) == ["home", "cust", "pay", "log"]
    for tab in tabs:
        assert f'<section id="{tab}"' in HTML, tab


def test_removed_pages():
    for gone in ('id="prem"', 'id="setup"', 'id="stats"', 'id="iptv"', 'id="eco"', 'data-sub="import"', "kImport"):
        assert gone not in HTML + ALL_JS, gone


def test_old_addresses_redirect():
    f = JS["js/faelles.js"]
    for old in ("setup", "iptv", "eco", "prem", "stats"):
        assert re.search(rf'\b{old}: \[', f), f"gammel adresse #{old} sendes ikke videre"



def test_no_duplicate_globals():
    """Alle JavaScript-filer deler ét fælles rum. Samme navn to steder (let/const/function) stopper hele filen i browseren."""
    import glob
    import re
    jsdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "static", "js")
    seen = {}
    for f in sorted(glob.glob(os.path.join(jsdir, "*.js"))):
        for line in open(f, encoding="utf-8"):
            names = []
            m = re.match(r"(?:async\s+)?function\s+([\w$]+)", line)
            if m:
                names = [m.group(1)]
            m = re.match(r"(?:let|const|var)\s+(.*)", line)
            if m:
                body = re.sub(r"\{[^{}]*\}|\[[^\[\]]*\]|\([^()]*\)|\"[^\"]*\"|'[^']*'|`[^`]*`", "", m.group(1))
                names = re.findall(r"(?:^|,)\s*([A-Za-z_$][\w$]*)\s*(?==|,|;|$)", body)
            for n in names:
                assert n not in seen, f"{n} findes både i {seen[n]} og {os.path.basename(f)}"
                seen[n] = os.path.basename(f)
    assert len(seen) > 100
