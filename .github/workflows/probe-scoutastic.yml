#!/usr/bin/env python3
"""
SONDA API Scoutastic v2 — drążenie /matches i /competitions pod walidator „Ostatnie mecze".
 
Sonda v1 pokazała: brak endpointów per-zawodnik (/players/{id}/performances = 404),
ale ISTNIEJĄ stronicowane /matches i /competitions (200). Ta wersja zagląda do środka:
jaki kształt ma mecz, czy zawiera skład z minutami, jak filtrować po drużynie/sezonie,
oraz jak nazywa się Ekstraklasa i drużyna Rakowa w tym API.
 
Uruchom (workflow „Scoutastic — sonda danych meczowych" albo lokalnie):
    SCOUTASTIC_TOKEN=... python scripts/scoutastic_probe.py
 
Bezpieczne: nic nie zapisuje, nie loguje tokenu. Drukuje kształty i SKRÓCONE próbki
JSON (do ~1600 znaków), żeby było widać strukturę bez zalewania loga.
"""
import json
import os
import sys
import urllib.parse
 
import scoutastic as sc
 
MAXLEN = 1600
 
 
def _short(obj):
    try:
        s = json.dumps(obj, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        s = str(obj)
    return s[:MAXLEN] + (" …[ucięto]" if len(s) > MAXLEN else "")
 
 
def _keys(obj):
    if isinstance(obj, dict):
        return sorted(obj.keys())
    if isinstance(obj, list):
        return f"lista[{len(obj)}]" + (f", elem: {sorted(obj[0].keys())}"
                                       if obj and isinstance(obj[0], dict) else "")
    return type(obj).__name__
 
 
def _docs(res):
    """Wyciąga listę dokumentów ze stronicowanej odpowiedzi (docs) albo z listy."""
    if isinstance(res, dict) and isinstance(res.get("docs"), list):
        return res["docs"], res.get("totalDocs")
    if isinstance(res, list):
        return res, len(res)
    return [], None
 
 
def _get(c, path, params=None):
    try:
        return c._request("GET", path, params=params), None
    except sc.ApiError as e:
        return None, f"{e.code}"
    except Exception as e:  # noqa: BLE001
        return None, str(e)
 
 
def _load_names():
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        squad = json.load(open(os.path.join(here, "..", "public", "squad.json"), encoding="utf-8"))
        return [p.get("name") for p in squad if p.get("name")]
    except Exception:  # noqa: BLE001
        return ["Stratos Svarnas", "Bogdan Racovițan", "Marko Bulat"]
 
 
def main():
    token = os.getenv("SCOUTASTIC_TOKEN")
    if not token:
        print("[sonda] Brak SCOUTASTIC_TOKEN.", file=sys.stderr)
        sys.exit(1)
    c = sc.Client(token)
 
    # --- 1) Zawodnik Rakowa: id + pola łączące (teams/statsbomb/transfermarkt) ---
    ext, pl = None, None
    for name in _load_names():
        try:
            res = c.search_player(name)
        except Exception as e:  # noqa: BLE001
            print(f"[sonda] search '{name}': {e}", file=sys.stderr)
            continue
        if res:
            ext = res[0].get("playerId") or res[0].get("externalId") or res[0].get("id")
            if ext:
                print(f"[sonda] zawodnik: {name} -> externalId={ext}")
                break
    if ext:
        pl, err = _get(c, f"/players/{urllib.parse.quote(str(ext))}")
        if isinstance(pl, dict):
            print(f"[sonda] player.statsbomb   = {_short(pl.get('statsbomb'))}")
            print(f"[sonda] player.transfermarktId = {pl.get('transfermarktId')}")
            print(f"[sonda] player.optaId      = {pl.get('optaId')}")
            print(f"[sonda] player.teams       = {_short(pl.get('teams'))}")
 
    # --- 2) /competitions: znajdź Ekstraklasę (id + kształt) ---
    res, err = _get(c, "/competitions", params={"limit": 100})
    docs, total = _docs(res)
    print(f"\n[sonda] /competitions -> totalDocs={total}; elem klucze: "
          f"{_keys(docs[0]) if docs else '(brak)'}")
    ekstraklasa = []
    for d in docs:
        blob = json.dumps(d, ensure_ascii=False).lower()
        if "ekstraklasa" in blob or "poland" in blob or "polska" in blob:
            ekstraklasa.append(d)
    if ekstraklasa:
        print(f"[sonda] Ekstraklasa/Polska ({len(ekstraklasa)}):")
        for d in ekstraklasa[:4]:
            print(f"[sonda]   {_short(d)}")
    elif docs:
        print(f"[sonda] (nie znalazłem Ekstraklasy po nazwie) przykład: {_short(docs[0])}")
 
    # --- 3) /matches: kształt meczu + czy zawiera skład/minuty ---
    res, err = _get(c, "/matches", params={"limit": 2})
    docs, total = _docs(res)
    print(f"\n[sonda] /matches -> totalDocs={total}; elem klucze: "
          f"{_keys(docs[0]) if docs else '(brak)'}")
    if err:
        print(f"[sonda] /matches błąd: {err}")
    match_id = None
    if docs:
        print(f"[sonda] przykładowy mecz: {_short(docs[0])}")
        match_id = docs[0].get("id") or docs[0].get("_id") or docs[0].get("matchId")
 
    # --- 4) /matches/{id}: czy detal ma skład zawodników z minutami ---
    if match_id is not None:
        res, err = _get(c, f"/matches/{urllib.parse.quote(str(match_id))}")
        if isinstance(res, dict):
            print(f"\n[sonda] /matches/{match_id} -> klucze: {sorted(res.keys())}")
            for k in ("lineups", "lineup", "players", "playerStats", "appearances",
                      "homeLineup", "awayLineup", "events"):
                if k in res:
                    print(f"[sonda]   • '{k}': {_keys(res[k])}")
            print(f"[sonda]   próbka: {_short(res)}")
        else:
            print(f"\n[sonda] /matches/{match_id} -> {err}")
 
    # --- 5) Filtry /matches: sprawdź, które parametry zawężają (po team/competition/season) ---
    team_id = None
    if isinstance(pl, dict):
        t = pl.get("teams")
        if isinstance(t, list) and t and isinstance(t[0], dict):
            team_id = t[0].get("id") or t[0].get("teamId") or t[0].get("externalId")
    comp_id = None
    if ekstraklasa:
        comp_id = ekstraklasa[0].get("id") or ekstraklasa[0].get("_id") or ekstraklasa[0].get("competitionId")
    print(f"\n[sonda] Filtry (team_id={team_id}, comp_id={comp_id}):")
    trials = []
    for pname in ("team", "teamId", "club", "clubId"):
        if team_id is not None:
            trials.append((pname, team_id))
    for pname in ("competition", "competitionId"):
        if comp_id is not None:
            trials.append((pname, comp_id))
    for pname, val in trials:
        res, err = _get(c, "/matches", params={pname: val, "limit": 1})
        _, t = _docs(res)
        print(f"[sonda]   /matches?{pname}={val} -> totalDocs={t}{'  BŁĄD '+err if err else ''}")
 
    print("\n[sonda] Gotowe. Wklej mi wszystkie linie [sonda].")
 
 
if __name__ == "__main__":
    main()
 
