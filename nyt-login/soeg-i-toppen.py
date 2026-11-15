#!/usr/bin/env python3
"""Flyt guidens søgefelt op i toppen (ved siden af "Menu") på telefon og smalle skærme.

Køres på feeder:  python3 /opt/fangarr/nyt-login/soeg-i-toppen.py /opt/nyt/site/index.html

- Tilføjer kun en blok lige før </body> – resten af siden røres ikke. Kan køres igen (blokken erstattes).
- Gemmer først en kopi uden for site-mappen (/opt/nyt/index.html.før-soeg-<dato>), så den ikke kan hentes af brugerne.
- Fortryd:  python3 /opt/fangarr/nyt-login/soeg-i-toppen.py /opt/nyt/site/index.html --fjern
- Skal køres igen, når en ny udgave af guiden er pakket ud i /opt/nyt/site/ (til ændringen er kommet med i byggescriptet).
"""
import datetime
import os
import re
import shutil
import sys

START, SLUT = "<!-- soeg-i-toppen:start -->", "<!-- soeg-i-toppen:slut -->"
BLOK = START + r"""
<style>
@media (max-width: 960px) {
  .gbar .gsw { position: relative; flex: 1 1 150px; min-width: 0; max-width: 520px; margin-left: auto; }
  .gbar .gsw .gsearch { margin: 0; }
  .gbar .gsw .gsearch input { min-height: 44px; font-size: 16px; }
  .gbar .gsw .gsearch .gi { top: 12px; }
  .gbar .gsw #hits { position: absolute; left: 0; right: 0; top: calc(100% + 8px); margin: 0; padding: 6px; background: #0E1012;
    border: 1px solid var(--line); border-radius: 12px; box-shadow: 0 14px 34px rgba(0,0,0,.65); max-height: 65vh; overflow-y: auto; z-index: 30; }
  .gbar .gsw #hits:empty { display: none; }
}
@media (max-width: 600px) { .gbar .brand { display: none; } .gbar .gsw { max-width: none; } }
</style>
<script>
(function () {
  var bar = document.querySelector('.gbar'), nav = document.querySelector('.gnav'), box = document.querySelector('.gnav .gsearch'),
      hits = document.getElementById('hits'), q = document.getElementById('gq');
  if (!bar || !nav || !box || !hits || !q || !window.matchMedia) return;
  var wrap = document.createElement('div'); wrap.className = 'gsw';
  var home = document.createComment('søgefeltets plads i menuen'); nav.insertBefore(home, box);
  var mq = window.matchMedia('(max-width: 960px)');
  function place() {
    if (mq.matches) { if (box.parentNode !== wrap) { wrap.appendChild(box); wrap.appendChild(hits); bar.appendChild(wrap); } }
    else if (box.parentNode === wrap) { nav.insertBefore(box, home.nextSibling); nav.insertBefore(hits, box.nextSibling); wrap.remove(); }
  }
  place(); (mq.addEventListener ? mq.addEventListener('change', place) : mq.addListener(place));
  function again() { if (q.value.trim().length >= 2 && !hits.firstChild) q.dispatchEvent(new Event('input', {bubbles: true})); }
  q.addEventListener('focus', again);
  // i toppen: luk listen, når man vælger et emne eller trykker uden for
  wrap.addEventListener('click', function (e) { if (e.target.closest('#hits a')) setTimeout(function () { hits.innerHTML = ''; q.blur(); }, 0); });
  document.addEventListener('click', function (e) { if (box.parentNode === wrap && !e.target.closest('.gsw')) hits.innerHTML = ''; });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && box.parentNode === wrap) { hits.innerHTML = ''; q.blur(); } });
})();
</script>
""" + SLUT


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    fjern = "--fjern" in sys.argv
    if len(args) != 1:
        sys.exit("Brug: soeg-i-toppen.py /opt/nyt/site/index.html [--fjern]")
    path = os.path.realpath(args[0])
    with open(path, encoding="utf-8") as f:
        doc = f.read()
    har = START in doc and SLUT in doc
    ren = re.sub(re.escape(START) + r".*?" + re.escape(SLUT) + r"\n?", "", doc, flags=re.S) if har else doc
    if fjern:
        if not har:
            print("Søgefeltet er ikke flyttet i denne fil – intet ændret.")
            return
        ny = ren
    else:
        for skal in ('class="gbar"', 'class="gnav"', 'class="gsearch"', 'id="gq"', 'id="hits"', "</body>"):
            if skal not in ren:
                sys.exit(f"Stopper: siden indeholder ikke {skal} – den er bygget anderledes end ventet. Intet ændret.")
        i = ren.rindex("</body>")
        ny = ren[:i] + BLOK + "\n" + ren[i:]
    if ny == doc:
        print("Siden har allerede den nyeste udgave af ændringen – intet ændret.")
        return
    kopi = os.path.join(os.path.dirname(os.path.dirname(path)), "index.html.før-soeg-" + datetime.datetime.now().strftime("%Y-%m-%d-%H%M"))
    shutil.copy2(path, kopi)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(ny)
    os.replace(tmp, path)
    print(("Fjernet: søgefeltet ligger igen kun i menuen." if fjern else "Færdig: søgefeltet står nu i toppen på telefon og smalle skærme.")
          + f"\nKopi af siden fra før: {kopi}")


if __name__ == "__main__":
    main()
