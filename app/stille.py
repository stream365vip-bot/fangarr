"""Besked ved 0 streams (2.1.0).

Tryk "Sig til ved 0 streams" på Overblik (eller "Sig til igen" i Telegram). Fangarr spørger Tautulli hvert minut og
sender én besked til Stream365 Drift, når ingen streamer – evt. kun inden for et tidsrum, du vælger. Bagefter er den
slået fra igen. Bruges til ting, der afbryder kundernes streaming (genstart, opdatering af Plex, plex-db …).

Overblik viser også, hvornår der normalt er stille om natten (ud fra Tautullis historik for de sidste 30 nætter).
"""

import datetime
import time

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api")
D = {}   # udfyldes af main.py: tautulli, tautulli_enabled, kv_get, kv_set, now, iso, telegram_rows, log

_quiet = {"day": None, "data": None}


def state():
    return D["kv_get"]("stille", {}) or {}


def _in_window(st, n):
    a, b = st.get("from"), st.get("to")
    if a in (None, "") or b in (None, ""):
        return True
    a, b, h = int(a), int(b), n.hour
    return a <= h < b if a < b else (h >= a or h < b)


def arm(frm=None, to=None):
    st = {"armed": True, "armed_at": D["iso"](D["now"]()), "from": frm, "to": to}
    D["kv_set"]("stille", st)
    return st


def streams_now():
    d = D["tautulli"]("get_activity") or {}
    return int(d.get("stream_count") or 0)


def tick():
    st = state()
    if not st.get("armed") or not D["tautulli_enabled"]():
        return
    n = D["now"]()
    if not _in_window(st, n):
        return
    try:
        cnt = streams_now()
    except Exception as e:   # Tautulli nede: prøv igen om et minut
        D["log"].warning("0 streams: Tautulli svarede ikke: %s", e)
        return
    st["last_check"], st["last_count"] = D["iso"](n), cnt
    if cnt == 0:
        st["armed"] = False
        st["fired_at"] = D["iso"](n)
        D["kv_set"]("stille", st)
        D["telegram_rows"](f"🌙 0 streams lige nu (kl. {n.strftime('%H:%M')}) – godt tidspunkt til ting, der afbryder streaming.",
                           [[("Sig til igen", "stille_again", {"from": st.get("from"), "to": st.get("to")})]])
    else:
        D["kv_set"]("stille", st)


def again(p):
    arm(p.get("from"), p.get("to"))
    return "jeg siger til næste gang, der er 0 streams", None


@router.get("/stille")
def stille_get():
    st = state()
    out = {"enabled": D["tautulli_enabled"](), **st, "quiet": quiet_nights()}
    return out


@router.post("/stille")
async def stille_arm(req: Request):
    if not D["tautulli_enabled"]():
        raise HTTPException(400, "Tautulli er ikke sat op i fangarr.env")
    try:
        b = await req.json()
    except ValueError:
        b = {}
    frm, to = b.get("from"), b.get("to")
    for v in (frm, to):
        if v not in (None, "") and not (str(v).isdigit() and 0 <= int(v) <= 23):
            raise HTTPException(400, "tidsrummet skal være hele timer 0–23")
    arm(None if frm in (None, "") else int(frm), None if to in (None, "") else int(to))
    return stille_get()


@router.delete("/stille")
def stille_off():
    st = state()
    st["armed"] = False
    D["kv_set"]("stille", st)
    return stille_get()


# ---------------------------------------------------------------- hvornår er der normalt stille om natten?

def quiet_nights(days=30):
    """Ud fra Tautullis historik: for hvert minut kl. 00–09 – hvor stor en del af nætterne havde 0 streams.
    Svaret er det længste stykke, hvor mindst 90 % af nætterne var stille. Regnes ud én gang i døgnet."""
    if not D["tautulli_enabled"]():
        return None
    today = D["now"]().date()
    if _quiet["day"] == today:
        return _quiet["data"]
    _quiet["day"] = today
    try:
        start = today - datetime.timedelta(days=days)
        sessions, pos = [], 0
        while pos < 20000:
            d = D["tautulli"]("get_history", grouping=0, start=pos, length=1000, after=start.isoformat(),
                              order_column="date", order_dir="asc") or {}
            chunk = d.get("data") or []
            for r in chunk:
                a, b = int(r.get("started") or 0), int(r.get("stopped") or 0)
                if a and b >= a:
                    sessions.append((a, b))
            pos += len(chunk)
            if len(chunk) < 1000:
                break
        nights = {}
        base = {}
        for i in range(1, days + 1):
            day = today - datetime.timedelta(days=i)
            base[i] = int(time.mktime(datetime.datetime.combine(day, datetime.time(0, 0)).timetuple()))
            nights[i] = [False] * 540   # 00:00–09:00 i minutter
        for a, b in sessions:
            for i, t0 in base.items():
                if b < t0 or a > t0 + 540 * 60:
                    continue
                busy = nights[i]
                for m in range(max(0, (a - t0) // 60), min(540, (b - t0) // 60 + 1)):
                    busy[m] = True
        nights = list(nights.values())
        n = len(nights)
        quiet = [sum(1 for b in nights if not b[m]) / n for m in range(540)]
        best, cur = (0, 0), None
        for m in range(541):
            ok = m < 540 and quiet[m] >= 0.9
            if ok and cur is None:
                cur = m
            if not ok and cur is not None:
                if m - cur > best[1] - best[0]:
                    best = (cur, m)
                cur = None
        fmt = lambda m: f"{m // 60:02d}:{m % 60:02d}"  # noqa: E731
        data = {"nights": n, "sessions": len(sessions), "from": fmt(best[0]) if best[1] > best[0] else "",
                "to": fmt(best[1]) if best[1] > best[0] else "", "minutes": best[1] - best[0]}
    except Exception as e:
        D["log"].warning("Stille nætter kunne ikke regnes ud: %s", e)
        data = {"error": str(e)[:150]}
    _quiet["data"] = data
    return data
