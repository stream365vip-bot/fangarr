#!/usr/bin/env python3
# backuptjek.py - proeve af backuppen (Fangarr 2.3.0). Koerer paa feeder den 1. i maaneden.
# Tjekker den seneste backup af begge servere i Google Drive (gcrypt:Mediabox og gcrypt:Feeder):
#   1) alder (seneste fil under ca. 30 timer gammel) og samlet stoerrelse,
#   2) henter den mindste tar-fil, aabner den med tar og sletter kopien igen.
# Besked til Stream365 Drift kun ved problemer og "i orden igen". Aendrer intet i backuppen.
#   --prove          viser resultatet, sender ingen besked
#   --test-besked    sender en testbesked til Stream365 Drift
import datetime, json, os, shutil, subprocess, sys, tempfile, urllib.parse, urllib.request

MAPPE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(MAPPE, "backuptjek.log")
STATUS = os.path.join(MAPPE, "status.json")
MAAL = [("Mediabox", "gcrypt:Mediabox", 30), ("feeder", "gcrypt:Feeder", 5)]   # navn, rclone-sti, mindst GB
MAKS_TIMER = 30
RCLONE = shutil.which("rclone") or "/usr/bin/rclone"


def log(tekst):
    linje = "%s %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tekst)
    print(linje)
    with open(LOG, "a") as f:
        f.write(linje + "\n")


def telegram(tekst):
    env = {}
    with open(os.path.join(MAPPE, "telegram.env")) as f:
        for l in f:
            if "=" in l and not l.strip().startswith("#"):
                k, v = l.strip().split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    token = next(v for k, v in env.items() if "TOKEN" in k.upper())
    chat = next(v for k, v in env.items() if "CHAT" in k.upper())
    data = urllib.parse.urlencode({"chat_id": chat, "text": tekst}).encode()
    urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % token, data=data, timeout=20).read()


def rclone(*args, timeout=600):
    r = subprocess.run([RCLONE, *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("rclone %s fejlede: %s" % (args[0], (r.stderr or "").strip().splitlines()[-1:] or "ukendt fejl"))
    return r.stdout


def tjek(navn, sti, mindst_gb):
    """Returnerer (linje til loggen, problem eller None)."""
    filer = json.loads(rclone("lsjson", sti, "--recursive", "--files-only", "--max-depth", "3", timeout=300))
    filer = [f for f in filer if not f["Path"].lower().startswith("archived")]
    if not filer:
        return "%s: ingen filer" % navn, "%s: backuppen er tom eller findes ikke (%s)" % (navn, sti)
    nyeste = max(datetime.datetime.fromisoformat(f["ModTime"].replace("Z", "+00:00")) for f in filer)
    timer = (datetime.datetime.now(datetime.timezone.utc) - nyeste).total_seconds() / 3600
    gb = sum(f["Size"] for f in filer) / 1e9
    tars = sorted((f for f in filer if ".tar" in f["Name"] and f["Size"] > 1024), key=lambda f: f["Size"])
    linje = "%s: %d filer, %.1f GB, seneste %.0f timer gammel" % (navn, len(filer), gb, timer)
    if timer > MAKS_TIMER:
        return linje, "%s: seneste backup er %.0f timer gammel (højst %d)" % (navn, timer, MAKS_TIMER)
    if gb < mindst_gb:
        return linje, "%s: backuppen fylder kun %.1f GB (mindst %d)" % (navn, gb, mindst_gb)
    if not tars:
        return linje, "%s: ingen tar-filer i backuppen" % navn
    lille = tars[0]
    mappe = tempfile.mkdtemp(prefix="backuptjek-")
    try:
        lokal = os.path.join(mappe, lille["Name"])
        rclone("copyto", "%s/%s" % (sti, lille["Path"]), lokal, timeout=900)
        r = subprocess.run(["tar", "-tf", lokal], capture_output=True, text=True, timeout=300)
        antal = len(r.stdout.splitlines())
        if r.returncode != 0 or antal == 0:
            return linje, "%s: %s kunne hentes, men ikke åbnes (tar: %s)" % (navn, lille["Path"], (r.stderr or "").strip()[:120])
        return linje + ", prøvegendannelse af %s: %d filer" % (lille["Path"], antal), None
    finally:
        shutil.rmtree(mappe, ignore_errors=True)


def main():
    if "--test-besked" in sys.argv:
        telegram("🧪 feeder: test fra backuptjek – beskeder virker.")
        print("Testbesked sendt.")
        return
    prove = "--prove" in sys.argv
    problemer = []
    for navn, sti, mindst in MAAL:
        try:
            linje, problem = tjek(navn, sti, mindst)
        except Exception as e:
            linje, problem = "%s: fejl" % navn, "%s: %s" % (navn, e)
        log(linje)
        if problem:
            log("PROBLEM  " + problem)
            problemer.append(problem)
    if prove:
        print("Prøvekørsel færdig – ingen besked sendt.")
        return
    try:
        with open(STATUS) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    try:
        if problemer:
            telegram("🚨 feeder: prøven af backuppen fejlede\n" + "\n".join(problemer))
            st["meldt"] = True
        elif st.get("meldt"):
            telegram("✅ feeder: prøven af backuppen er i orden igen")
            st["meldt"] = False
    except Exception as e:
        log("Kunne ikke sende Telegram-besked: %s" % type(e).__name__)
    st["sidst_koert"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(STATUS, "w") as f:
        json.dump(st, f)


if __name__ == "__main__":
    main()
