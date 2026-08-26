#!/usr/bin/env python3
# =====================================================================
# faza2_probe.py — SONDA pod Fazę 2 (dane eventowe wg listy KPI Igora).
#
# NIC nie zapisuje ani nie commituje — tylko czyta z API i wypisuje
# schemat do loga (linie [sonda2]). Nie drukuje poświadczeń.
#
# Cel: ustalić REALNY schemat danych, zanim napiszemy agregację. Dwa źródła:
#   A. StatsBomb — dane EVENTOWE (potwierdzić dostęp + pola pod: łamanie
#      linii B1/B2/B3, mapy stref przyjęć, liczenie minut z eventów
#      Half Start/Player Off — metodyka Igora).
#   B. SkillCorner — Off-Ball Runs: sprawdzić, czy jest rozbicie na TYPY
#      biegów (za obrońcę / naddanie / do nogi), czego agregat GI nie ma.
#
# UŻYCIE (lokalnie lub w Actions):
#   python scripts/faza2_probe.py            # obie sondy
#   python scripts/faza2_probe.py statsbomb  # tylko StatsBomb
#   python scripts/faza2_probe.py skillcorner
# =====================================================================
import os
import sys
 
 
def _p(msg):
    print(f"[sonda2] {msg}", flush=True)
 
 
def _norm(s):
    return "".join(c for c in str(s).lower() if c.isalnum())
 
 
# ---------------------------------------------------------------------
#  A. STATSBOMB — EVENTY
# ---------------------------------------------------------------------
def probe_statsbomb():
    _p("=== StatsBomb: sonda danych EVENTOWYCH ===")
    user, pw = os.getenv("SB_USERNAME"), os.getenv("SB_PASSWORD")
    if not user or not pw:
        _p("[SB] BRAK SB_USERNAME/SB_PASSWORD w środowisku — pomijam.")
        return
    creds = {"user": user, "passwd": pw}
    try:
        from statsbombpy import sb
    except ImportError:
        _p("[SB] Brak biblioteki statsbombpy — pomijam.")
        return
 
    # 1) Znajdź Ekstraklasę i najnowszy sezon.
    try:
        comps = sb.competitions(creds=creds).to_dict("records")
    except Exception as e:  # noqa: BLE001
        _p(f"[SB] Nie pobrano listy rozgrywek: {type(e).__name__}: {e}")
        return
    ekstra = [c for c in comps if "ekstraklasa" in _norm(c.get("competition_name"))]
    if not ekstra:
        _p("[SB] Nie znalazłem Ekstraklasy w liście rozgrywek — pomijam.")
        return
    _p("[SB] Dostępne sezony Ekstraklasy: "
       + ", ".join(f"{c.get('season_name')}(id={c.get('season_id')})"
                   for c in sorted(ekstra, key=lambda c: c.get('season_id', 0), reverse=True)))
    comp_id = ekstra[0].get("competition_id")
 
    # 2) Pętla po sezonach NAJNOWSZE→NAJSTARSZE: szukaj ROZEGRANEGO meczu z eventami.
    #    Przyszłe/nierozegrane mecze zwracają puste eventy ('No objects to concatenate'),
    #    co NIE oznacza braku licencji — po prostu meczu jeszcze nie ma.
    ev, mid, chosen = None, None, None
    for c in sorted(ekstra, key=lambda c: c.get("season_id", 0), reverse=True):
        sid = c.get("season_id")
        try:
            matches = sb.matches(competition_id=comp_id, season_id=sid, creds=creds).to_dict("records")
        except Exception as e:  # noqa: BLE001
            _p(f"[SB] Sezon {c.get('season_name')}: nie pobrano meczów: {type(e).__name__}: {e}")
            continue
 
        def _played(m):
            # StatsBomb: 'available' = zebrane eventy; wynik uzupełniony = rozegrany.
            st = str(m.get("match_status") or "").lower()
            hs, as_ = m.get("home_score"), m.get("away_score")
            return st == "available" or isinstance(hs, (int, float)) and isinstance(as_, (int, float))
 
        def _is_rakow(m):
            return "rakow" in _norm(m.get("home_team")) or "rakow" in _norm(m.get("away_team"))
 
        played = [m for m in matches if _played(m)]
        n_avail = sum(1 for m in matches if str(m.get("match_status") or "").lower() == "available")
        _p(f"[SB] Sezon {c.get('season_name')}: meczów={len(matches)}, "
           f"rozegranych~={len(played)}, status=available: {n_avail}.")
        if not played:
            continue
        # preferuj mecz Rakowa spośród rozegranych
        cand = next((m for m in played if _is_rakow(m)), played[0])
        mid = cand.get("match_id")
        try:
            ev = sb.events(match_id=mid, creds=creds)
            chosen = cand
            _p(f"[SB] Mecz do sondy: {cand.get('home_team')} vs {cand.get('away_team')} "
               f"({cand.get('match_date')}, status={cand.get('match_status')}), match_id={mid}.")
            break
        except Exception as e:  # noqa: BLE001
            status = getattr(getattr(e, "response", None), "status_code", None)
            _p(f"[SB] Eventy meczu {mid} nie przeszły (status={status}): "
               f"{type(e).__name__}: {e} — próbuję dalej.")
            ev = None
            if status == 403:
                _p("[SB] !!! 403 — to jest BRAK dostępu do eventów (licencja sezonowa). "
                   "Faza 2 ze StatsBomb odpada; zostaje SkillCorner + proxy.")
                return
            continue
 
    if ev is None or len(ev) == 0:
        _p("[SB] Nie udało się pobrać niepustych eventów w żadnym sezonie. Jeśli nie było "
           "403, to najpewniej brak ROZEGRANYCH meczów z zebranymi eventami w tych sezonach "
           "(a nie brak licencji). Zdiagnozujemy po tym logu.")
        return
    _p(f"[SB] OK — EVENTY DOSTĘPNE. Wierszy: {len(ev)}, kolumn: {len(ev.columns)}.")
 
    # 3b) DANE 360 (freeze frames) — potrzebne do PRAWDZIWEGO packingu i B1/B2/B3
    #     (pozycje rywali). Bez 360 zrobimy tylko proxy progresji przez tercje.
    has_360 = False
    try:
        ev360 = sb.events(match_id=mid, creds=creds, include_360_metrics=True)
        cols360 = [c for c in ev360.columns if "360" in c.lower() or "freeze" in c.lower()
                   or "visible" in c.lower() or "teammate" in c.lower()]
        nonnull = {c: int(ev360[c].notna().sum()) for c in cols360}
        has_360 = any(v > 0 for v in nonnull.values())
        _p(f"[SB] 360 przez include_360_metrics: kolumny={cols360}, niepuste={nonnull}")
    except Exception as e:  # noqa: BLE001
        _p(f"[SB] include_360_metrics nie przeszło: {type(e).__name__}: {e}")
    if not has_360:
        try:
            fr = sb.frames(match_id=mid, creds=creds)
            _p(f"[SB] sb.frames(): {len(fr)} wierszy, kolumny={list(fr.columns)[:12]}"
               f"{' …' if len(fr.columns) > 12 else ''}. 360 DOSTĘPNE.")
            has_360 = len(fr) > 0
        except Exception as e:  # noqa: BLE001
            _p(f"[SB] sb.frames() nie przeszło: {type(e).__name__}: {e}")
    _p(f"[SB] >>> DANE 360 (freeze frames): {'DOSTĘPNE' if has_360 else 'BRAK'} "
       f"— {'zrobimy prawdziwy packing + B1/B2/B3' if has_360 else 'tylko proxy progresji przez tercje'}.")
 
    # 4) Typy eventów (to jest kręgosłup wszystkich KPI eventowych).
    try:
        vc = ev["type"].value_counts()
        _p("[SB] Typy eventów (top 25):")
        for t, n in list(vc.items())[:25]:
            _p(f"[SB]    {t}: {n}")
    except Exception as e:  # noqa: BLE001
        _p(f"[SB] Nie policzyłem typów eventów: {e}")
 
    cols = set(ev.columns)
 
    # 5) MINUTY Z EVENTÓW (metodyka Igora): które typy są dostępne?
    types_present = set(ev["type"].unique()) if "type" in cols else set()
    need_min = ["Half Start", "Half End", "Starting XI", "Substitution", "Player Off", "Player On"]
    _p("[SB] Minuty z eventów — typy obecne: "
       + ", ".join(f"{t}={'TAK' if t in types_present else 'nie'}" for t in need_min))
 
    # 6) Pola PODAŃ pod łamanie linii B1/B2/B3 i grę pod presją.
    pass_fields = ["location", "pass_end_location", "pass_height", "pass_length",
                   "pass_angle", "pass_outcome", "pass_type", "under_pressure",
                   "play_pattern", "pass_recipient"]
    _p("[SB] Pola podań (pod B1/B2/B3 + presja): "
       + ", ".join(f"{c}={'TAK' if c in cols else 'nie'}" for c in pass_fields))
 
    # 7) PRZYJĘCIA piłki (mapy stref) — typ 'Ball Receipt*' + lokalizacja.
    n_recv = int((ev["type"].astype(str).str.startswith("Ball Receipt")).sum()) if "type" in cols else 0
    _p(f"[SB] Przyjęcia (type startswith 'Ball Receipt'): {n_recv} zdarzeń; "
       f"kolumna 'location' obecna: {'TAK' if 'location' in cols else 'nie'}.")
 
    # 8) Prowadzenia / drybling / OBV (jeśli w evencie).
    extra = ["carry_end_location", "dribble_outcome", "duel_type", "obv_total_net",
             "obv_for_net", "counterpress"]
    _p("[SB] Pola dodatkowe (carry/dribbling/duel/obv): "
       + ", ".join(f"{c}={'TAK' if c in cols else 'nie'}" for c in extra))
 
    # 9) Przykładowe wiersze (kształt location = [x,y]) — 1 podanie, 1 przyjęcie.
    try:
        pas = ev[ev["type"] == "Pass"].head(1)
        if len(pas):
            r = pas.iloc[0]
            _p(f"[SB] Przykład Pass: location={r.get('location')}, "
               f"end={r.get('pass_end_location')}, height={r.get('pass_height')}, "
               f"under_pressure={r.get('under_pressure')}")
    except Exception as e:  # noqa: BLE001
        _p(f"[SB] (przykład Pass pominięty: {e})")
    _p("[SB] === koniec sondy StatsBomb ===")
 
 
# ---------------------------------------------------------------------
#  B. SKILLCORNER — OFF-BALL RUNS (typy biegów)
# ---------------------------------------------------------------------
def probe_skillcorner():
    _p("=== SkillCorner: sonda Off-Ball Runs (typy biegów) ===")
    if not os.getenv("SKILLCORNER_USERNAME") or not os.getenv("SKILLCORNER_PASSWORD"):
        _p("[SC] BRAK SKILLCORNER_USERNAME/PASSWORD — pomijam.")
        return
    try:
        from skillcorner.client import SkillcornerClient
    except ImportError:
        _p("[SC] Brak biblioteki skillcorner — pomijam.")
        return
    client = SkillcornerClient()
 
    # 1) Odkrycie metod klienta związanych z biegami / off-ball.
    meth = [m for m in dir(client)
            if (("run" in m.lower()) or ("off_ball" in m.lower()) or ("offball" in m.lower()))
            and not m.startswith("_")]
    _p(f"[SC] Metody klienta (run/off_ball): {meth}")
 
    import pandas as pd
 
    def _frame(data):
        if data is None:
            return pd.DataFrame()
        if isinstance(data, dict):
            data = data.get("results", [data]) if "results" in data else [data]
        try:
            return pd.json_normalize(data)
        except Exception:  # noqa: BLE001
            return pd.DataFrame(data)
 
    EK = 1171  # Ekstraklasa (edition id, jak w fetch_skillcorner.EDITIONS)
 
    # 2) Standardowe wywołanie (to, co już mamy) — dla porównania kolumn.
    try:
        base = _frame(client.get_metrics_gi_ip_off_ball_runs(
            params={"competition_edition": EK, "group_by": "player"}))
        _p(f"[SC] off_ball_runs (group_by=player): {len(base)} wierszy, "
           f"{len(base.columns)} kolumn.")
        runcols = [c for c in base.columns if "run" in c.lower()]
        _p(f"[SC] Kolumny z 'run' (obecny agregat): {runcols}")
    except Exception as e:  # noqa: BLE001
        status = getattr(getattr(e, "response", None), "status_code", None)
        _p(f"[SC] Standardowe off_ball_runs nie przeszło (status={status}): "
           f"{type(e).__name__}: {e}")
 
    # 3) Zagregowany GI NIE przyjmuje run_type (potwierdzone sondą). Nazwane TYPY biegów
    #    siedzą w endpointach EVENTOWYCH. Sondujemy je z małym limitem i zrzucamy kolumny
    #    + rozpoznane wartości typu biegu. Event-level bywa duży → limit.
    def _dump(method, params, label):
        fn = getattr(client, method, None)
        if fn is None:
            _p(f"[SC] {label}: klient nie ma metody {method} — pomijam.")
            return
        try:
            df = _frame(fn(params=params))
        except Exception as e:  # noqa: BLE001
            status = getattr(getattr(e, "response", None), "status_code", None)
            _p(f"[SC] {label} ({method}) nie przeszło (status={status}): {type(e).__name__}: {e}")
            return
        _p(f"[SC] {label}: {len(df)} wierszy, {len(df.columns)} kolumn.")
        # kolumny, które mogą nieść typ/kategorię biegu
        typecols = [c for c in df.columns
                    if any(k in c.lower() for k in ("type", "category", "class", "name", "label", "kind"))]
        _p(f"[SC] {label}: kolumny (wszystkie): {list(df.columns)}")
        for tc in typecols:
            try:
                vals = sorted(str(v) for v in df[tc].dropna().unique())[:25]
                _p(f"[SC] {label}: '{tc}' wartości({len(set(df[tc].dropna()))}): {vals}")
            except Exception:  # noqa: BLE001
                pass
 
    # 3a) get_in_possession_off_ball_runs: 'limit' niedozwolony, ale 'run_type' TAK
    #     (jako filtr) + group_by=player. Najpierw agregat bez filtra (kolumny/kształt).
    _dump("get_in_possession_off_ball_runs",
          {"competition_edition": EK, "group_by": "player"}, "in_possession (agregat/player)")
 
    # 3b) ENUMERACJA wartości run_type — podajemy nieprawidłową wartość i czytamy z
    #     błędu listę dozwolonych (ten sam trik, co przy group_by).
    try:
        client.get_in_possession_off_ball_runs(
            params={"competition_edition": EK, "group_by": "player", "run_type": "__enumeruj__"})
        _p("[SC] run_type='__enumeruj__' NIE zwrócił błędu — sprawdź kolumny wyżej.")
    except Exception as e:  # noqa: BLE001
        _p(f"[SC] Dozwolone wartości run_type (z błędu API): {e}")
 
    # 3c) To samo dla 'channel' i 'third' (kanał/tercja) — mogą się przydać do
    #     lokalizacji biegów; enumerujemy przy okazji.
    for prm in ("channel", "third"):
        try:
            client.get_in_possession_off_ball_runs(
                params={"competition_edition": EK, "group_by": "player", prm: "__enumeruj__"})
        except Exception as e:  # noqa: BLE001
            _p(f"[SC] Dozwolone wartości {prm}: {e}")
 
    _p("[SC] === koniec sondy SkillCorner ===")
 
 
# ---------------------------------------------------------------------
#  C. PUCHARY EUROPEJSKIE — czy StatsBomb je licencjonuje i czy jest Raków.
#     Jedno źródło (StatsBomb) obsłuży i RC (dane sezonowe), i „Ostatnie mecze".
# ---------------------------------------------------------------------
def probe_cups():
    _p("=== Puchary europejskie: sonda dostępności w StatsBomb ===")
    user, pw = os.getenv("SB_USERNAME"), os.getenv("SB_PASSWORD")
    if not user or not pw:
        _p("[CUP] BRAK SB_USERNAME/SB_PASSWORD — pomijam.")
        return
    creds = {"user": user, "passwd": pw}
    try:
        from statsbombpy import sb
    except ImportError:
        _p("[CUP] Brak statsbombpy — pomijam.")
        return
    try:
        comps = sb.competitions(creds=creds).to_dict("records")
    except Exception as e:  # noqa: BLE001
        _p(f"[CUP] Nie pobrano listy rozgrywek: {type(e).__name__}: {e}")
        return
 
    KEYS = ("champions", "europa", "conference", "uefa", "european")
    cups = [c for c in comps if any(k in str(c.get("competition_name", "")).lower() for k in KEYS)]
    if not cups:
        _p("[CUP] Brak rozgrywek UEFA w licencji StatsBomb — RC/mecze z pucharów NIE są możliwe z tego źródła.")
        return
    # unikalne rozgrywki + dostępne sezony
    by_comp = {}
    for c in cups:
        by_comp.setdefault(c.get("competition_name"), []).append(c)
    _p(f"[CUP] Rozgrywki UEFA w licencji ({len(by_comp)}):")
    for name, rows in by_comp.items():
        seasons = sorted({r.get("season_name") for r in rows})
        _p(f"[CUP]   {name} (competition_id={rows[0].get('competition_id')}): sezony {seasons}")
 
    # Czy Raków pojawia się w meczach najnowszego sezonu któregoś pucharu?
    def _is_rakow(m):
        return "rakow" in _norm(m.get("home_team")) or "rakow" in _norm(m.get("away_team"))
 
    found_any = False
    for name, rows in by_comp.items():
        newest = max(rows, key=lambda r: r.get("season_id", 0))
        cid, sid = newest.get("competition_id"), newest.get("season_id")
        try:
            ms = sb.matches(competition_id=cid, season_id=sid, creds=creds).to_dict("records")
        except Exception as e:  # noqa: BLE001
            _p(f"[CUP]   {name} {newest.get('season_name')}: nie pobrano meczów: {type(e).__name__}: {e}")
            continue
        rk = [m for m in ms if _is_rakow(m)]
        avail = sum(1 for m in ms if str(m.get("match_status") or "").lower() == "available")
        _p(f"[CUP]   {name} {newest.get('season_name')}: meczów={len(ms)} (available={avail}), "
           f"meczów Rakowa={len(rk)}.")
        for m in rk[:6]:
            _p(f"[CUP]      Raków: {m.get('home_team')} {m.get('home_score')}-{m.get('away_score')} "
               f"{m.get('away_team')} ({m.get('match_date')}, status={m.get('match_status')})")
        if rk:
            found_any = True
    _p(f"[CUP] >>> Raków w pucharach StatsBomb: {'JEST — da się zrobić RC i ostatnie mecze' if found_any else 'BRAK meczów Rakowa (albo sezon jeszcze nierozegrany)'}.")
    _p("[CUP] === koniec sondy pucharów ===")
 
 
def main():
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "both"
    if mode in ("both", "statsbomb", "sb"):
        try:
            probe_statsbomb()
        except Exception as e:  # noqa: BLE001
            _p(f"[SB] Sonda przerwana wyjątkiem: {type(e).__name__}: {e}")
    if mode in ("both", "skillcorner", "sc"):
        try:
            probe_skillcorner()
        except Exception as e:  # noqa: BLE001
            _p(f"[SC] Sonda przerwana wyjątkiem: {type(e).__name__}: {e}")
    if mode in ("cups", "puchary", "cup"):
        try:
            probe_cups()
        except Exception as e:  # noqa: BLE001
            _p(f"[CUP] Sonda przerwana wyjątkiem: {type(e).__name__}: {e}")
    _p("Gotowe. Skopiuj wszystkie linie [sonda2] i wklej do rozmowy.")
 
 
if __name__ == "__main__":
    main()
 
