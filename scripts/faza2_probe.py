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
    # najnowszy sezon = max season_id
    ek = max(ekstra, key=lambda c: c.get("season_id", 0))
    comp_id, season_id = ek.get("competition_id"), ek.get("season_id")
    _p(f"[SB] Ekstraklasa: competition_id={comp_id}, season_id={season_id} "
       f"({ek.get('season_name')}). Dostępnych sezonów Ekstraklasy: "
       f"{sorted({c.get('season_name') for c in ekstra})}")

    # 2) Wybierz mecz (najlepiej Rakowa).
    try:
        matches = sb.matches(competition_id=comp_id, season_id=season_id, creds=creds).to_dict("records")
    except Exception as e:  # noqa: BLE001
        _p(f"[SB] Nie pobrano meczów: {type(e).__name__}: {e}")
        return
    _p(f"[SB] Meczów w sezonie: {len(matches)}.")

    def _is_rakow(m):
        return "rakow" in _norm(m.get("home_team")) or "rakow" in _norm(m.get("away_team"))

    match = next((m for m in matches if _is_rakow(m)), matches[0] if matches else None)
    if not match:
        _p("[SB] Brak meczów do sondy — pomijam.")
        return
    mid = match.get("match_id")
    _p(f"[SB] Mecz do sondy: {match.get('home_team')} vs {match.get('away_team')} "
       f"({match.get('match_date')}), match_id={mid}.")

    # 3) POBIERZ EVENTY — to potwierdza, czy licencja obejmuje dane eventowe.
    try:
        ev = sb.events(match_id=mid, creds=creds)
    except Exception as e:  # noqa: BLE001
        status = getattr(getattr(e, "response", None), "status_code", None)
        _p(f"[SB] !!! Nie pobrano EVENTÓW (status={status}): {type(e).__name__}: {e}")
        _p("[SB] Jeśli to 403 — licencja jest SEZONOWA (bez eventów). Wtedy Faza 2 "
           "z StatsBomb odpada i zostaje sam SkillCorner + ewentualny proxy.")
        return
    _p(f"[SB] OK — EVENTY DOSTĘPNE. Wierszy: {len(ev)}, kolumn: {len(ev.columns)}.")

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

    # 3) PRÓBA rozbicia na TYPY biegów — kilka wariantów group_by. Każdy w try.
    variants = [
        {"competition_edition": EK, "group_by": "player,run_type"},
        {"competition_edition": EK, "group_by": "run_type"},
        {"competition_edition": EK, "group_by": ["player", "run_type"]},
        {"competition_edition": EK, "group_by": "player", "run_type": "all"},
    ]
    for i, params in enumerate(variants, 1):
        try:
            df = _frame(client.get_metrics_gi_ip_off_ball_runs(params=params))
            gtxt = params.get("group_by")
            typecol = next((c for c in df.columns if "type" in c.lower()), None)
            types = sorted(df[typecol].dropna().unique().tolist())[:20] if typecol else None
            _p(f"[SC] Wariant {i} group_by={gtxt}: {len(df)} wierszy, "
               f"{len(df.columns)} kolumn; kolumna typu='{typecol}'; "
               f"wartości typu={types}")
        except Exception as e:  # noqa: BLE001
            status = getattr(getattr(e, "response", None), "status_code", None)
            _p(f"[SC] Wariant {i} ({params.get('group_by')}) nie przeszło "
               f"(status={status}): {type(e).__name__}: {e}")

    _p("[SC] === koniec sondy SkillCorner ===")


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
    _p("Gotowe. Skopiuj wszystkie linie [sonda2] i wklej do rozmowy.")


if __name__ == "__main__":
    main()
