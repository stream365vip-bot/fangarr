"""Fejlsøg pr. kunde (2.4.0) – knappen Fejlsøg på kundekortet.

Når en kunde skriver "det virker ikke", samler Fangarr det, du ellers skal finde fem steder:
- kundens seneste afspilninger fra Tracearr: enhed, app, opløsning, om Plex omkodede og hvorfor, bitrate, undertekster,
- hvad kunden ser lige nu,
- overtrædelser fra Tracearr (stoppede afspilninger) de seneste 7 dage,
- om en titel, kunden spørger om, er skjult og venter på dansk tekst (Oversætteren),
- om Plex, Seerr og IPTV er oppe (Uptime Kumas statusside "kunder"),
- og et forslag til svar, du kan kopiere. Fangarr sender intet selv.
Kun læsning. IP-adresser vises på siden (bag Authelia), men aldrig i Telegram eller logs.
"""

import datetime

from fastapi import APIRouter, HTTPException

from . import apps, blokeringer

router = APIRouter(prefix="/api")
D = {}   # udfyldes af main.py: db, now, iso, reveal_all (Oversætterens skjulte/viste), log
STATUS_SLUG = "kunder"


def setup(**deps):
    D.update(deps)


def _customer(cid):
    con = D["db"]()
    try:
        c = con.execute("SELECT id, name FROM k_customers WHERE id=?", (cid,)).fetchone()
        px = [r[0] for r in con.execute("SELECT plex_user_id FROM k_services WHERE customer_id=? AND service='plex'"
                                        " AND plex_user_id IS NOT NULL", (cid,)).fetchall()]
    finally:
        con.close()
    if not c:
        raise HTTPException(404, "kunden findes ikke")
    return dict(c), px


def _reasons(ti):
    """Grunde til omkodning fra Tracearrs transcode_info (kan være tekst, liste eller et opslag)."""
    if not ti:
        return []
    if isinstance(ti, str):
        return [ti]
    if isinstance(ti, list):
        return [str(x) for x in ti if x][:4]
    if isinstance(ti, dict):
        out = []
        for k, v in ti.items():
            if "reason" in k.lower() and v:
                out += v if isinstance(v, list) else [v]
        return [str(x) for x in out][:4]
    return []


def _subs(si):
    if not si:
        return ""
    if isinstance(si, dict):
        parts = [si.get(k) for k in ("language", "codec", "decision") if si.get(k)]
        return " · ".join(str(p) for p in parts)
    return str(si)[:80]


def _title(h):
    if h.get("show_title"):
        se = ""
        if h.get("season_number") is not None and h.get("episode_number") is not None:
            se = f" S{int(h['season_number']):02d}E{int(h['episode_number']):02d}"
        return f"{h['show_title']}{se}"
    return str(h.get("media_title") or "–") + (f" ({h['year']})" if h.get("year") else "")


def _play(h):
    trans = bool(h.get("is_transcode")) or "transcode" in str(h.get("video_decision") or "").lower()
    return {"started": blokeringer._local(h.get("started_at")), "title": _title(h),
            "device": " · ".join(str(x) for x in (h.get("device") or h.get("player"), h.get("product") or h.get("platform")) if x),
            "resolution": str(h.get("resolution") or ""), "transcode": trans,
            "video": str(h.get("video_decision") or ""), "audio": str(h.get("audio_decision") or ""),
            "reasons": _reasons(h.get("transcode_info")), "bitrate": h.get("bitrate"), "subs": _subs(h.get("subtitle_info")),
            "percent": h.get("percent_complete"), "state": str(h.get("state") or "")}


def _status():
    if not apps.enabled():
        return None
    try:
        return [{"name": a["name"], "state": a["state"]} for g in apps._fetch(STATUS_SLUG) for a in g["apps"]]
    except Exception as e:  # noqa: BLE001
        return {"error": f"Uptime Kuma svarer ikke ({e.__class__.__name__})"}


def _hidden(q):
    """Titler, der matcher søgningen og er skjult (venter på dansk tekst) eller er vist uden dansk tekst."""
    if not q or not D.get("reveal_all"):
        return None
    try:
        rv = D["reveal_all"]() or {}
    except Exception as e:  # noqa: BLE001
        return {"error": f"Oversætteren svarer ikke ({e.__class__.__name__})"}
    if not rv.get("enabled", True):
        return {"off": True}
    ql = q.lower()
    match = lambda i: ql in str(i.get("title") or "").lower() or ql in str(i.get("file") or "").lower()  # noqa: E731
    return {"waiting": [{"title": i.get("title"), "reveal_by": i.get("reveal_by"), "reason": i.get("reason") or ""}
                        for i in (rv.get("waiting") or []) if match(i)][:10],
            "shown": [{"title": i.get("title"), "shown_at": i.get("shown_at"), "danish": i.get("shown_by") != "sikkerhedsnet"}
                      for i in (rv.get("shown") or []) if match(i)][:10]}


def suggest(first, plays, viols, status, hidden, q):
    """Forslag til svar ud fra det, Fangarr har fundet. Det vigtigste først."""
    out = []
    down = [s["name"] for s in (status if isinstance(status, list) else []) if s["state"] == "down"]
    if down:
        out.append(f"Vi har lige nu et problem med {', '.join(down)}. Jeg arbejder på det, og det burde virke igen snart.")
    stop = [v for v in viols if v["action"] == "stopper"]
    if any("betal" in v["rule"].lower() for v in stop):
        out.append("Din afspilning blev stoppet, fordi betalingen mangler. Når betalingen er på plads, virker det igen med det samme.")
    elif stop:
        out.append("Din afspilning blev stoppet, fordi kontoen blev brugt på to tv på forskellige adresser samtidig. "
                   "Dit abonnement gælder én husstand – skriv til mig, hvis det er en fejl.")
    if isinstance(hidden, dict) and hidden.get("waiting"):
        w = hidden["waiting"][0]
        when = str(w.get("reveal_by") or "")[:16].replace("T", " kl. ")
        out.append(f"“{w['title']}” er kommet på serveren, men venter på danske undertekster. "
                   f"Den bliver synlig i Plex{(' senest ' + when) if when else ' snart'}.")
    recent = plays[:5]
    if recent and sum(1 for p in recent if p["transcode"] and p["video"].lower().startswith("transcode")) >= 3:
        out.append("Plex omkoder dine afspilninger, hvilket kan give hak. Prøv at sætte kvaliteten i Plex-appen til "
                   "Original/Maksimum (Indstillinger › Kvalitet), og slå undertekster fra, hvis de står som “brændt ind”.")
    if not out:
        out.append("Jeg kan se, at alt virker på serveren lige nu. Kan du prøve at lukke Plex-appen helt og åbne den igen? "
                   "Virker det stadig ikke, så skriv hvilken titel og hvilken enhed (tv, telefon …) det drejer sig om.")
    return f"Hej {first}.\n" + "\n".join(out)


@router.get("/fejlsoeg/{cid}")
def api_fejlsoeg(cid: int, titel: str = ""):
    c, plex_ids = _customer(cid)
    q = titel.strip()[:100]
    first = (c["name"] or "").split(" ")[0] or "der"
    res = {"customer": c, "plex_users": len(plex_ids), "tracearr": blokeringer.enabled(), "errors": [],
           "plays": [], "now": [], "violations": [], "status": _status(), "hidden": _hidden(q), "query": q}
    tids = []
    if blokeringer.enabled() and plex_ids:
        try:
            tids = blokeringer.tracearr_ids(plex_ids)
            if not tids:
                res["errors"].append("Kundens Plex-bruger findes ikke i Tracearr.")
            for tid in tids:
                h = blokeringer.tget(f"users/{tid}/history", pageSize=15).get("data") or []
                res["plays"] += [_play(x) for x in h]
            res["plays"].sort(key=lambda p: p["started"], reverse=True)
            res["plays"] = res["plays"][:15]
            st = blokeringer.tget("streams")
            for s in (st.get("data") or [] if isinstance(st, dict) else st or []):
                u = s.get("user") if isinstance(s.get("user"), dict) else {}
                if str(u.get("id") or s.get("user_id") or "") in tids:
                    res["now"].append(_play(s))
        except Exception as e:  # noqa: BLE001
            res["errors"].append(f"Tracearr: {e}")
    elif not plex_ids:
        res["errors"].append("Kunden har ingen tjeneste Plex koblet til en Plex-bruger – afspilninger kan ikke findes.")
    since = D["iso"](D["now"]() - datetime.timedelta(days=7))
    for g in (blokeringer.grouped(7) if blokeringer.enabled() else []):
        if g["plex_user"] is not None and g["plex_user"] in plex_ids:
            res["violations"] += [v for v in g["items"] if v["created"] >= since]
    res["violations"].sort(key=lambda v: v["created"], reverse=True)
    # Forslaget bruger kun stop fra de seneste 2 døgn – ældre er sandsynligvis ikke det, kunden skriver om
    recent = D["iso"](D["now"]() - datetime.timedelta(hours=48))
    res["suggestion"] = suggest(first, res["plays"], [v for v in res["violations"] if v["created"] >= recent],
                                res["status"], res["hidden"], q)
    return res
