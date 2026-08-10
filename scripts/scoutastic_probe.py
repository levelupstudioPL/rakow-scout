#!/usr/bin/env python3
"""
SONDA API Scoutastic v4 — rozstrzyga, czy ROZEGRANE mecze Rakowa mają wypełniony
skład z minutami (to decyduje, czy adapter meczowy z Scoutastic ma sens).
 
Wiemy: Ekstraklasa = competitionId=PL1; filtr działa jako ?competitionId=PL1&season=2026
(306 meczów = pełny terminarz 2026/27). Mecze Rakowa (ext=9644) w próbce miały pusty
homeTeamPlayers — ale to głównie przyszłe spotkania. Ta sonda:
  1. Przechodzi WSZYSTKIE strony sezonu 2026, zbiera mecze Rakowa, dzieli na
     rozegrane vs terminarz, i pokazuje ile mają zawodników/eventów.
  2. Dla rozegranego meczu próbuje SZCZEGÓŁU /matches/{internalId} (lista bywa skrócona).
  3. Dumpuje kształt wpisu zawodnika (minuty/gole) i eventu.
  4. Dumpuje /teams/9644 (może mieć skład / referencje).
 
Uruchom przez workflow. Nic nie zapisuje, nie loguje tokenu.
"""
import json
import os
import sys
import urllib.parse
 
import scoutastic as sc
 
MAXLEN = 1500
COMP = os.getenv("PROBE_COMP", "PL1")
SEASON = os.getenv("PROBE_SEASON", "2026")
EXT = "9644"  # Raków Częstochowa (externalId), potwierdzony wcześniej
 
 
def _short(obj):
    try:
        s = json.dumps(obj, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        s = str(obj)
    return s[:MAXLEN] + (" …[ucięto]" if len(s) > MAXLEN else "")
 
 
def _get(c, path, params=None):
    try:
        return c._request("GET", path, params=params), None
    except sc.ApiError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return None, str(e)
 
 
def _played(m):
    """Rozegrany = ma liczbowy wynik (scoreHome/Away nie '-')."""
    sh, sa = str(m.get("scoreHome")), str(m.get("scoreAway"))
    return sh.isdigit() and sa.isdigit()
 
 
def main():
    if not os.getenv("SCOUTASTIC_TOKEN"):
        print("[sonda] Brak SCOUTASTIC_TOKEN.", file=sys.stderr)
        sys.exit(1)
    c = sc.Client(os.getenv("SCOUTASTIC_TOKEN"))
 
    # --- 1) Zbierz wszystkie mecze Rakowa z sezonu (paginacja) ---
    rk = []
    for page in range(1, 6):
        res, err = _get(c, "/matches", {"competitionId": COMP, "season": SEASON,
                                        "limit": 100, "page": page})
        if err:
            print(f"[sonda] strona {page}: {err}")
            break
        docs = res.get("docs") if isinstance(res, dict) else None
        if not docs:
            break
        for m in docs:
            if EXT in (str(m.get("homeTeamId")), str(m.get("awayTeamId"))):
                rk.append(m)
        if not (isinstance(res, dict) and res.get("hasNextPage")):
            break
 
    print(f"[sonda] Mecze Rakowa w {COMP}/{SEASON}: {len(rk)}")
    played = [m for m in rk if _played(m)]
    print(f"[sonda] rozegrane (liczbowy wynik): {len(played)} / terminarz: {len(rk) - len(played)}")
    for m in sorted(rk, key=lambda x: str(x.get("date")))[:12]:
        nh = len(m.get("homeTeamPlayers") or [])
        na = len(m.get("awayTeamPlayers") or [])
        ne = len(m.get("events") or [])
        print(f"[sonda]   {str(m.get('date'))[:10]} {m.get('homeTeamName')} "
              f"{m.get('scoreHome')}:{m.get('scoreAway')} {m.get('awayTeamName')} "
              f"| status={m.get('status')} | players {nh}/{na} events {ne}")
 
    # --- 2) Rozegrany mecz: skład z listy albo ze SZCZEGÓŁU /matches/{internalId} ---
    target = None
    for m in sorted(played, key=lambda x: str(x.get("date")), reverse=True):
        target = m
        break
    if target:
        iid = target.get("internalId") or target.get("transfermarktId")
        print(f"\n[sonda] Rozegrany mecz: {str(target.get('date'))[:10]} "
              f"{target.get('homeTeamName')} {target.get('scoreHome')}:{target.get('scoreAway')} "
              f"{target.get('awayTeamName')} (internalId={iid})")
        src = target
        if not (target.get("homeTeamPlayers") or target.get("awayTeamPlayers")):
            print("[sonda]   lista ma pusty skład — próbuję szczegółu…")
            for path in (f"/matches/{urllib.parse.quote(str(iid))}",
                         f"/matches/{urllib.parse.quote(str(target.get('transfermarktId')))}"):
                det, err = _get(c, path)
                if isinstance(det, dict):
                    print(f"[sonda]   {path} -> klucze: {sorted(det.keys())[:30]}")
                    if det.get("homeTeamPlayers") or det.get("awayTeamPlayers"):
                        src = det
                        break
                else:
                    print(f"[sonda]   {path} -> {err}")
        side = src.get("homeTeamPlayers") or src.get("awayTeamPlayers") or []
        print(f"[sonda]   skład: home={len(src.get('homeTeamPlayers') or [])} "
              f"away={len(src.get('awayTeamPlayers') or [])}")
        if side:
            print(f"[sonda]   player[0]: {_short(side[0])}")
        ev = src.get("events") or []
        print(f"[sonda]   events: {len(ev)}; events[0]: {_short(ev[0]) if ev else '(brak)'}")
    else:
        print("\n[sonda] Brak rozegranego meczu Rakowa w tym sezonie (za wcześnie?).")
 
    # --- 3) /teams/9644 — co zawiera ---
    det, err = _get(c, f"/teams/{EXT}")
    if isinstance(det, dict):
        print(f"\n[sonda] /teams/{EXT} klucze: {sorted(det.keys())}")
        for k in ("squad", "players", "matches", "currentSeason", "seasons"):
            if k in det:
                v = det[k]
                print(f"[sonda]   • '{k}': {('lista['+str(len(v))+']') if isinstance(v, list) else type(v).__name__}")
 
    print("\n[sonda] Gotowe. Wklej mi wszystkie linie [sonda].")
 
 
if __name__ == "__main__":
    main()
