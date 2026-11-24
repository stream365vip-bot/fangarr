"""Skærmbilleder af alle sider og underfaner på computer (1360 px) og telefon (390 px) – og fejl i browserens konsol.

    python tests/demo.py &                       (Fangarr med opdigtede testdata)
    python tests/skaermbilleder.py <mappe>       (kræver: pip install playwright, og Chrome)

Stopper med fejlkode 1, hvis en side giver en JavaScript-fejl.
"""

import os
import re
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("FANGARR", "http://127.0.0.1:18080")
OUT = sys.argv[1] if len(sys.argv) > 1 else "skaermbilleder"
CHROME = os.environ.get("CHROME", "/usr/bin/google-chrome")
HTML = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "static", "index.html"), encoding="utf-8").read()


def pages():
    out = []
    for sec in re.findall(r'<section id="([a-z]+)"', HTML):
        if sec == "search":
            continue
        body = HTML[HTML.index(f'<section id="{sec}"'):]
        body = body[:body.index("</section>")]
        subs = re.findall(r'data-sub="([a-z]+)"', body)
        out += [(sec, s) for s in subs] or [(sec, "")]
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        for name, w, h, mobile in (("pc", 1360, 900, False), ("tlf", 390, 844, True)):
            ctx = br.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if mobile else 1, is_mobile=mobile, has_touch=mobile)
            pg = ctx.new_page()
            pg.on("pageerror", lambda e, n=name: errors.append(f"{n}: {e}"))
            pg.on("console", lambda m, n=name: errors.append(f"{n} konsol: {m.text}") if m.type == "error" and "Failed to load resource" not in m.text else None)
            pg.on("response", lambda r, n=name: errors.append(f"{n}: {r.status} {r.url}") if r.status >= 400 and "favicon" not in r.url else None)
            pg.goto(BASE + "/#home")
            pg.wait_for_timeout(1500)
            for sec, sub in pages():
                pg.evaluate(f"go('{sec}', '{sub}')")
                pg.wait_for_timeout(900)
                pg.screenshot(path=os.path.join(OUT, f"{name}-{sec}{'-' + sub if sub else ''}.png"), full_page=not mobile)
            # gamle adresser sendes videre
            for old, want in (("setup", "#rules/afproev"), ("iptv", "#cust/iptv"), ("eco", "#pay/oekonomi"), ("stats", "#bib"), ("settings/vente", "#wait/indst")):
                pg.goto(BASE + "/#" + old); pg.reload(); pg.wait_for_timeout(700)
                if not pg.url.endswith(want):
                    errors.append(f"{name}: #{old} gik til {pg.url} (ventet {want})")
            if mobile:   # menuen på telefonen
                pg.goto(BASE + "/#home"); pg.reload(); pg.wait_for_timeout(800)
                pg.click(".bbar [data-menu]"); pg.wait_for_timeout(400)
                pg.screenshot(path=os.path.join(OUT, f"{name}-menu.png"))
            else:        # en fold-ud-beskrivelse og kundekortet
                pg.goto(BASE + "/#log"); pg.reload(); pg.wait_for_timeout(900)
                pg.click("#log details.hjd summary"); pg.wait_for_timeout(300)
                pg.screenshot(path=os.path.join(OUT, f"{name}-log-beskrivelse.png"))
                pg.goto(BASE + "/#cust/liste"); pg.reload(); pg.wait_for_timeout(900)
                pg.click("#kList .kr.click"); pg.wait_for_timeout(700)
                pg.screenshot(path=os.path.join(OUT, f"{name}-kundekort.png"))
            ctx.close()
        br.close()
    errors = [e for e in errors if "favicon" not in e]
    print("\n".join(errors) if errors else "Ingen JavaScript-fejl.")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
