"""Guide (Fangarr 1.18.0) – hvem har været inde på guide.stream365.vip, hvornår, og hvad har de set på.

Appen `nyt` (mappen nyt-login/) skriver én lille fil pr. dag med logins, besøg, læste afsnit og søgeord.
Fangarr læser kun filerne (mappen er monteret skrivebeskyttet som /guide-stat) og sætter rigtige navne på
ud fra Kunder (som kommer fra Tautulli). Fangarr ændrer intet i guiden og sender ingen beskeder.

Vigtigt:
- Der gemmes Plex-id, brugernavn og tidspunkt – ingen IP-adresser. `nyt` sletter selv filer ældre end 90 dage.
- Konti i STAT_EXCLUDE i /opt/nyt/docker-compose.yml (standard: Stream365) tælles slet ikke med.
"""
import datetime
import json
import os
import re
import threading

from fastapi import APIRouter

router = APIRouter(prefix="/api/guide")
D = {}   # udfyldes af main.py: db, now, log
STAT_DIR = os.environ.get("GUIDE_STAT_DIR") or "/guide-stat"
_cache = {}          # filnavn -> (mtime, størrelse, hændelser)
_lock = threading.Lock()
SEARCH_GAP = 90      # "ju" → "jul" → "julefilm" inden for så mange sekunder regnes som én søgning


def setup(**deps):
    D.update(deps)


def enabled():
    return os.path.isdir(STAT_DIR)


def _read_day(path):
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("t") and r.get("uid") and r.get("e") in ("login", "visit", "section", "search"):
                    out.append(r)
    except OSError:
        pass
    return out


def events(days):
    """Alle hændelser fra de seneste `days` dage, ældste først. Filerne læses kun igen, når de er ændret."""
    first = (D["now"]() - datetime.timedelta(days=days - 1)).strftime("%Y-%m-%d")
    out = []
    try:
        names = sorted(n for n in os.listdir(STAT_DIR) if re.fullmatch(r"\d{4}-\d\d-\d\d\.jsonl", n) and n[:10] >= first)
    except OSError:
        return out
    with _lock:
        for n in names:
            p = os.path.join(STAT_DIR, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            c = _cache.get(n)
            if not c or c[0] != st.st_mtime or c[1] != st.st_size:
                c = _cache[n] = (st.st_mtime, st.st_size, _read_day(p))
            out.extend(c[2])
        for n in [k for k in _cache if k not in names and k[:10] < first]:
            _cache.pop(n, None)
    out.sort(key=lambda r: r["t"])
    return out


def accepted():
    """Hvem har accepteret reglerne (kopi af /opt/nyt/data/accepteret.json uden dine egne konti)."""
    try:
        with open(os.path.join(STAT_DIR, "accepteret.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def names():
    """Plex-id -> rigtigt navn. Kundens navn fra Kunder, ellers navnet fra Tautulli."""
    con = D["db"]()
    try:
        plex = {str(r["user_id"]): dict(r) for r in con.execute("SELECT user_id, username, friendly_name, active FROM k_plex").fetchall()}
        cust = {}
        for r in con.execute("SELECT s.plex_user_id uid, c.id cid, c.name, c.kind, c.status FROM k_services s JOIN k_customers c ON c.id=s.customer_id"
                             " WHERE s.service='plex' AND s.plex_user_id IS NOT NULL").fetchall():
            cust[str(r["uid"])] = dict(r)
    except Exception:   # tabellerne findes ikke endnu (Kunder er aldrig åbnet/synket)
        plex, cust = {}, {}
    finally:
        con.close()
    return plex, cust


def _collapse_searches(rows):
    """Fjern søgninger, der bare er begyndelsen på den næste ("jul" lige før "julefilm")."""
    out = []
    for r in rows:
        if out and out[-1]["q"] != r["q"] and r["q"].startswith(out[-1]["q"]) and _secs(out[-1]["t"], r["t"]) <= SEARCH_GAP:
            out[-1] = r
        elif not (out and out[-1]["q"] == r["q"] and _secs(out[-1]["t"], r["t"]) <= SEARCH_GAP):
            out.append(r)
    return out


def _secs(a, b):
    try:
        return abs((datetime.datetime.fromisoformat(b) - datetime.datetime.fromisoformat(a)).total_seconds())
    except ValueError:
        return 10 ** 9


def summary(days=30):
    days = max(1, min(int(days or 30), 90))
    plex, cust = names()
    acc = accepted()
    users, sec_tot, daily = {}, {}, {}

    def user(uid, username=""):
        u = users.get(uid)
        if not u:
            c, p = cust.get(uid), plex.get(uid) or {}
            u = users[uid] = {"uid": uid, "username": username or p.get("username") or "", "name": (c or {}).get("name") or p.get("friendly_name") or username or uid,
                              "customer_id": (c or {}).get("cid"), "known": bool(c or p), "first": None, "last": None, "visits": 0, "logins": 0,
                              "accepted_at": (acc.get(uid) or {}).get("at"), "sections": {}, "searches": []}
        if username and not u["username"]:
            u["username"] = username
        return u

    for r in events(days):
        uid = str(r["uid"])
        u = user(uid, str(r.get("user") or ""))
        u["first"] = u["first"] or r["t"]
        u["last"] = r["t"]
        day = daily.setdefault(r["t"][:10], {"visits": 0, "users": set()})
        day["users"].add(uid)
        if r["e"] == "visit":
            u["visits"] += 1
            day["visits"] += 1
        elif r["e"] == "login":
            u["logins"] += 1
        elif r["e"] == "section":
            key = str(r.get("id") or "")
            title = str(r.get("title") or key)
            s = u["sections"].setdefault(key, {"id": key, "title": title, "n": 0, "last": r["t"]})
            s.update(n=s["n"] + 1, last=r["t"], title=title)
            t = sec_tot.setdefault(key, {"id": key, "title": title, "views": 0, "users": set(), "last": r["t"]})
            t.update(views=t["views"] + 1, last=r["t"], title=title)
            t["users"].add(uid)
        elif r["e"] == "search" and r.get("q"):
            u["searches"].append({"q": str(r["q"]), "t": r["t"]})

    q_tot = {}
    for u in users.values():
        u["searches"] = _collapse_searches(u["searches"])
        for s in u["searches"]:
            t = q_tot.setdefault(s["q"], {"q": s["q"], "n": 0, "users": set(), "last": s["t"]})
            t.update(n=t["n"] + 1, last=max(t["last"], s["t"]))
            t["users"].add(u["name"])
        u["searches"].reverse()
        u["sections"] = sorted(u["sections"].values(), key=lambda s: s["last"], reverse=True)

    seen = set(users)
    # Brugere, der har accepteret reglerne før tælleren blev sat i gang (eller for mere end `days` dage siden)
    earlier = []
    for uid, a in acc.items():
        if uid not in seen:
            c, p = cust.get(uid), plex.get(uid) or {}
            earlier.append({"uid": uid, "name": (c or {}).get("name") or p.get("friendly_name") or (a or {}).get("user") or uid,
                            "username": (a or {}).get("user") or p.get("username") or "", "accepted_at": (a or {}).get("at")})
    ever = seen | set(acc)
    # Aktive kunder med Plex, som aldrig har været inde (hverken i perioden eller accepteret reglerne)
    never = sorted({c["name"] for uid, c in cust.items() if uid not in ever and c["kind"] == "kunde" and c["status"] == "aktiv"
                    and (plex.get(uid) or {}).get("active")}, key=str.lower)
    active = len({uid for uid, c in cust.items() if c["kind"] == "kunde" and c["status"] == "aktiv" and (plex.get(uid) or {}).get("active")})
    today = D["now"]().date()
    days_out = []
    for i in range(min(days, 30) - 1, -1, -1):
        d = (today - datetime.timedelta(days=i)).isoformat()
        x = daily.get(d) or {"visits": 0, "users": ()}
        days_out.append({"date": d, "visits": x["visits"], "users": len(x["users"])})
    first_event = min((u["first"] for u in users.values() if u["first"]), default=None)
    return {
        "enabled": enabled(), "dir": STAT_DIR, "days": days, "first_event": first_event,
        "kpis": {"visitors": len(users), "visits": sum(u["visits"] for u in users.values()),
                 "accepted": len(acc), "active_customers": active, "never": len(never),
                 "sections": sum(t["views"] for t in sec_tot.values()), "searches": sum(t["n"] for t in q_tot.values())},
        "users": sorted(users.values(), key=lambda u: u["last"] or "", reverse=True),
        "sections": sorted(({**t, "users": len(t["users"])} for t in sec_tot.values()), key=lambda t: (-t["users"], -t["views"])),
        "searches": sorted(({**t, "users": sorted(t["users"])} for t in q_tot.values()), key=lambda t: (-t["n"], t["q"])),
        "earlier": sorted(earlier, key=lambda a: a["accepted_at"] or "", reverse=True),
        "never": never, "daily": days_out,
    }


@router.get("")
def guide_get(days: int = 30):
    return summary(days)
