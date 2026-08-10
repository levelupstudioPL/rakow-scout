#!/usr/bin/env python3
"""
SONDA API Scoutastic v3 — ustalenie FILTRA /matches, competitionId Ekstraklasy
oraz kształtu składu w ROZEGRANYM meczu (homeTeamPlayers/events).
 
Ustalone wcześniej: mecz w /matches ma pola homeTeamId/awayTeamId (external),
competitionId, season, status, score(Home/Away), homeTeamPlayers/awayTeamPlayers,
events. Raków: externalId=9644. Brakuje: działającego parametru filtrującego
/matches (team/teamId/club/clubId NIE zawężały), competitionId Ekstraklasy oraz
kształtu wpisu zawodnika w składzie (minuty? gole?).
 
Uruchom przez workflow „Scoutastic — sonda danych meczowych".
Bezpieczne: nic nie zapisuje, nie loguje tokenu.
"""
import json
import os
import sys
import urllib.parse
 
import scoutastic as sc
 
MAXLEN = 1400
 
 
def _short(obj):
    try:
        s = json.dumps(obj, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        s = str(obj)
    return s[:MAXLEN] + (" …[ucięto]" if len(s) > MAXLEN else "")
 
 
def _docs(res):
    if isinstance(res, dict) and isinstance(res.get("docs"), list):
        return res["docs"], res.get("totalDocs")
    if isinstance(res, list):
        return res, len(res)
    return [], None
 
 
def _get(c, path, params=None):
    try:
        return c._request("GET", path, params=params), None
    except sc.ApiError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return None, str(e)
 
 
def _rakow_team(c):
    """Zwraca (externalId, internalId) Rakowa z pierwszego znalezionego zawodnika."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        names = [p.get("name") for p in json.load(
            open(os.path.join(here, "..", "public", "squad.json"), encoding="utf-8")) if p.get("name")]
    except Exception:  # noqa: BLE001
        names = ["Kacper Trelowski", "Stratos Svarnas"]
    for name in names:
        try:
            res = c.search_player(name)
        except Exception:  # noqa: BLE001
            continue
        if res and (res[0].get("playerId") or res[0].get("id")):
            ext = res[0].get("playerId") or res[0].get("id")
            pl = c.get_player(ext)
            teams = (pl or {}).get("teams") or []
            for t in teams:
                if "rakow" in (t.get("name", "").lower().replace("ó", "o")):
                    return t.get("externalId"), t.get("internalId"), name
            if teams:
                return teams[0].get("externalId"), teams[0].get("internalId"), name
    return None, None, None
 
 
def main():
    if not os.getenv("SCOUTASTIC_TOKEN"):
        print("[sonda] Brak SCOUTASTIC_TOKEN.", file=sys.stderr)
        sys.exit(1)
    c = sc.Client(os.getenv("SCOUTASTIC_TOKEN"))
 
    ext, internal, via = _rakow_team(c)
    print(f"[sonda] Raków team: externalId={ext}, internalId={internal} (przez {via})")
 
    # --- A) Ekstraklasa: competitionId (TM code Ekstraklasy to zwykle 'PL1') ---
    print("\n[sonda] Szukam Ekstraklasy w /competitions:")
    comp_id = None
    for params in ({"transfermarktId": "PL1"}, {"area": "Poland"}, {"name": "Ekstraklasa"},
                   {"search": "Ekstraklasa"}, {"query": "Ekstraklasa"}):
        res, err = _get(c, "/competitions", {**params, "limit": 10})
        docs, total = _docs(res)
        hit = None
        for d in (docs or []):
            nm = (d.get("name") or "").lower()
            if "ekstraklasa" in nm or (d.get("area") == "Poland" and d.get("level") == 1):
                hit = d
                break
        tag = f"-> total={total}" + (f", TRAFIENIE: id={hit.get('transfermarktId')} name={hit.get('name')} "
                                     f"seasons={hit.get('availableSeasons')}" if hit else "")
        print(f"[sonda]   /competitions?{urllib.parse.urlencode(params)} {tag}")
        if hit and not comp_id:
            comp_id = hit.get("transfermarktId") or hit.get("id") or hit.get("internalId")
    if not comp_id:
        comp_id = "PL1"
        print(f"[sonda]   (nie potwierdzono — próbuję domyślnie competitionId={comp_id})")
 
    # --- B) Który parametr FILTRUJE /matches? (szukam totalDocs << 135416) ---
    print(f"\n[sonda] Test filtrów /matches (Raków ext={ext}, comp={comp_id}):")
    trials = [
        {"competitionId": comp_id},
        {"competition": comp_id},
        {"competitionId": comp_id, "season": "2026"},
        {"competitionId": comp_id, "season": "2025"},
        {"homeTeamId": ext}, {"awayTeamId": ext},
        {"homeTeamId": ext, "season": "2025"},
        {"teamId": internal}, {"homeTeamInternalId": internal},
        {"teamExternalId": ext}, {"teams": ext},
    ]
    working = None
    for params in trials:
        res, err = _get(c, "/matches", {**params, "limit": 3})
        docs, total = _docs(res)
        flag = ""
        if isinstance(total, int) and total < 135416:
            flag = "  <<< ZAWĘŻA"
            if working is None and docs:
                working = (params, docs)
        print(f"[sonda]   /matches?{urllib.parse.urlencode(params)} -> total={total}"
              f"{'  '+err if err else ''}{flag}")
 
    # --- C) Kształt ROZEGRANEGO meczu: skład (minuty/gole) + events ---
    # Bierzemy zakończony sezon Ekstraklasy (pewne, że są pełne składy) i skanujemy
    # po mecz Rakowa z niepustym homeTeamPlayers/awayTeamPlayers.
    print("\n[sonda] Szukam rozegranego meczu Rakowa ze składem (competitionId + sezon):")
    found = False
    for season in ("2025", "2024", "2026"):
        for params in ({"competitionId": comp_id, "season": season},
                       {"competition": comp_id, "season": season}):
            res, err = _get(c, "/matches", {**params, "limit": 100})
            docs, total = _docs(res)
            if not docs:
                continue
            rk = [m for m in docs if ext in (str(m.get("homeTeamId")), str(m.get("awayTeamId")))]
            print(f"[sonda]   {urllib.parse.urlencode(params)} -> total={total}, w próbce meczów Rakowa={len(rk)}")
            for m in rk:
                players = (m.get("homeTeamPlayers") or []) + (m.get("awayTeamPlayers") or [])
                if players:
                    print(f"[sonda]   MECZ {m.get('date')} | {m.get('homeTeamName')} "
                          f"{m.get('score')} {m.get('awayTeamName')} | status={m.get('status')}")
                    print(f"[sonda]   pola meczu: {sorted(m.keys())}")
                    side = m.get("homeTeamPlayers") or m.get("awayTeamPlayers")
                    print(f"[sonda]   player[0]: {_short(side[0])}")
                    ev = m.get("events") or []
                    print(f"[sonda]   events[0]: {_short(ev[0]) if ev else '(brak events)'}")
                    found = True
                    break
            if found:
                break
        if found:
            break
    if not found:
        print("[sonda]   (nie znalazłem meczu Rakowa z niepustym składem — wklej mimo to resztę)")
 
    # --- D) Alternatywa: endpoint drużyny ---
    print("\n[sonda] Endpoity drużyny:")
    for path in (f"/teams/{ext}", f"/teams/{ext}/matches", f"/clubs/{ext}", f"/clubs/{ext}/matches"):
        res, err = _get(c, path)
        docs, total = _docs(res)
        print(f"[sonda]   {path} -> {'OK '+ (str(total) if total is not None else 'obiekt') if not err else err}")
 
    print("\n[sonda] Gotowe. Wklej mi wszystkie linie [sonda].")
 
 
if __name__ == "__main__":
    main()
 
