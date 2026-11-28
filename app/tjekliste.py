"""Tjekliste for biblioteket (2.3.0) – Bibliotek › Tjekliste.

Hver søndag nat (og når du trykker "Tjek nu") samler Fangarr ting, der bør ses på. Kun visning – intet rettes:
- film med samme titel og år i Radarr (Radarr kan så ikke vælge, når en udgivelse kommer – se dokumentationen),
- overvågede film, der er udgivet, men ikke hentet, og serier, der mangler overvågede afsnit,
- titler vist i Plex uden dansk tekst den seneste uge (Oversætterens sikkerhedsnet),
- titler uden plakat i Plex (de får heller ikke overlays),
- serier og film på en kvalitetsprofil, der ikke findes længere,
- serier i TV/TV uden genre (Agregarrs rækker for tv-programmer bruger genren).
Hvert punkt har et link til titlen i Radarr/sonarr2. Besked i Stream365 Drift kun med antal, og kun når der er nyt.
"""

import collections
import threading

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api")
D = {}   # udfyldes af main.py: arr, instances, plex (url, token), reveal, kv_get, kv_set, now, iso, telegram, log

RES_KEY = "tjek_result"
LIMIT = 200   # højst så mange linjer pr. punkt gemmes
_running = {"v": False}


def setup(**deps):
    D.update(deps)


def _inst(typ):
    return next((i for i in D["instances"]().values() if i["type"] == typ and not i.get("extra")), None)


def _item(inst, title, year=None, path="", note=""):
    return {"title": title, "year": year, "instance": inst["name"] if inst else "", "path": path, "note": note}


def radarr_checks(out):
    inst = _inst("radarr")
    if not inst:
        return
    movies = D["arr"](inst, "GET", "/movie")
    profiles = {p["id"] for p in D["arr"](inst, "GET", "/qualityprofile")}
    by = collections.defaultdict(list)
    for m in movies:
        by[(str(m.get("title") or "").lower(), m.get("year"))].append(m)
    for (_, _), ms in by.items():
        if len(ms) > 1:
            m = ms[0]
            out["dubletter"].append(_item(inst, m.get("title"), m.get("year"), f"/movie/{m.get('tmdbId')}",
                                          ", ".join(f"tmdb {x.get('tmdbId')} ({'fil' if x.get('hasFile') else 'ingen fil'})" for x in ms)))
    for m in movies:
        p = f"/movie/{m.get('tmdbId')}"
        if m.get("monitored") and not m.get("hasFile") and m.get("isAvailable"):
            out["mangler"].append(_item(inst, m.get("title"), m.get("year"), p, "film udgivet, men ikke hentet"))
        if m.get("qualityProfileId") not in profiles:
            out["profil"].append(_item(inst, m.get("title"), m.get("year"), p, f"profil {m.get('qualityProfileId')} findes ikke"))


def sonarr_checks(out):
    inst = _inst("sonarr")
    if not inst:
        return
    series = D["arr"](inst, "GET", "/series")
    profiles = {p["id"] for p in D["arr"](inst, "GET", "/qualityprofile")}
    for s in series:
        p = f"/series/{s.get('titleSlug')}"
        st = s.get("statistics") or {}
        have, want = int(st.get("episodeFileCount") or 0), int(st.get("episodeCount") or 0)
        if s.get("monitored") and want and have < want:
            out["mangler"].append(_item(inst, s.get("title"), s.get("year"), p, f"{want - have} af {want} overvågede afsnit mangler"))
        if s.get("qualityProfileId") not in profiles:
            out["profil"].append(_item(inst, s.get("title"), s.get("year"), p, f"profil {s.get('qualityProfileId')} findes ikke"))
        path = str(s.get("path") or s.get("rootFolderPath") or "").replace("\\", "/")
        if "/TV/TV/" in path + "/" and not s.get("genres"):
            out["genre"].append(_item(inst, s.get("title"), s.get("year"), p, "ingen genre"))


def reveal_checks(out):
    rv = D["reveal"]()
    if rv is None:
        return
    for i in (rv.get("shown") or []):
        if i.get("shown_by") == "sikkerhedsnet":
            out["uden_dansk"].append({"title": i.get("title") or i.get("key"), "year": None, "instance": "", "path": "",
                                      "note": f"vist {str(i.get('shown_at') or '')[:16].replace('T', ' ')} – {i.get('reason') or ''}"})


def plex_checks(out):
    url, token = D["plex"]()
    if not (url and token):
        return
    h = {"X-Plex-Token": token, "Accept": "application/json"}
    secs = httpx.get(url + "/library/sections", headers=h, timeout=20).json()["MediaContainer"].get("Directory", [])
    for sec in secs:
        if sec.get("type") not in ("movie", "show"):
            continue
        r = httpx.get(f"{url}/library/sections/{sec['key']}/all", headers=h, timeout=120)
        for m in r.json()["MediaContainer"].get("Metadata", []):
            if not m.get("thumb"):
                out["plakat"].append({"title": m.get("title"), "year": m.get("year"), "instance": "", "path": "",
                                      "note": f"Plex-biblioteket {sec.get('title')}"})


CHECKS = [("dubletter", "Film med samme titel og år i Radarr"),
          ("mangler", "Overvåget, men ikke hentet"),
          ("uden_dansk", "Vist i Plex uden dansk tekst (seneste uge)"),
          ("plakat", "Uden plakat i Plex"),
          ("profil", "På en kvalitetsprofil, der ikke findes"),
          ("genre", "Serier i TV/TV uden genre")]
LABELS = dict(CHECKS)


def run(manual=False):
    if _running["v"]:
        return False
    _running["v"] = True
    try:
        out = {k: [] for k, _ in CHECKS}
        errors = []
        for name, fn in (("Radarr", radarr_checks), ("sonarr2", sonarr_checks), ("Oversætteren", reveal_checks), ("Plex", plex_checks)):
            try:
                fn(out)
            except Exception as e:  # noqa: BLE001 – én app nede må ikke stoppe resten
                errors.append(f"{name}: {e.__class__.__name__}: {str(e)[:120]}")
        prev = D["kv_get"](RES_KEY, {}) or {}
        counts = {k: len(v) for k, v in out.items()}
        res = {"at": D["iso"](D["now"]()), "manual": manual, "errors": errors, "counts": counts,
               "sections": [{"key": k, "label": LABELS[k], "count": counts[k], "items": out[k][:LIMIT]} for k, _ in CHECKS]}
        D["kv_set"](RES_KEY, res)
        old = prev.get("counts") or {}
        grew = [k for k in counts if counts[k] > int(old.get(k) or 0) and k != "mangler"]
        if not manual and grew:
            lines = "\n".join(f"• {LABELS[k]}: {counts[k]}" + (f" (før {old.get(k)})" if k in old else "") for k in grew)
            D["telegram"](f"📋 Fangarr – tjekliste for biblioteket\n\n{lines}\n\nSe Fangarr › Bibliotek › Tjekliste.")
        return True
    finally:
        _running["v"] = False


def tick():
    n = D["now"]()
    if n.weekday() != 6 or n.hour != 4 or _running["v"]:   # søndag kl. 4
        return
    if ((D["kv_get"](RES_KEY, {}) or {}).get("at") or "")[:10] == n.date().isoformat():
        return
    threading.Thread(target=run, daemon=True).start()


@router.get("/tjekliste")
def get_state():
    res = D["kv_get"](RES_KEY, {}) or {}
    return {**res, "running": _running["v"]}


@router.post("/tjekliste/tjek")
def tjek():
    if _running["v"]:
        raise HTTPException(409, "Tjeklisten kører allerede")
    threading.Thread(target=run, kwargs={"manual": True}, daemon=True).start()
    return {"ok": True}
