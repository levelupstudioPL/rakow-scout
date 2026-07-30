#!/usr/bin/env python3
# =====================================================================
# discover_statsbomb.py — jednorazowe rozpoznanie licencji StatsBomb.
#
# Zapisuje dwie rzeczy potrzebne do (a) dodania nowych lig i (b) rozbudowy
# oceny bramkarzy:
#   scripts/statsbomb_competitions.csv — wszystkie rozgrywki/sezony w licencji
#       (competition_id, season_id, country, competition_name, season_name)
#   scripts/statsbomb_columns.txt      — pełna lista kolumn player_season_stats
#       (żeby dobrać realne metryki, w tym bramkarskie)
#
# Poświadczenia WYŁĄCZNIE ze zmiennych środowiskowych SB_USERNAME/SB_PASSWORD.
# Uruchomienie w chmurze: workflow .github/workflows/discover-statsbomb.yml.
# =====================================================================
 
import os
import sys
from pathlib import Path
 
HERE = Path(__file__).resolve().parent
 
 
def die(msg):
    print(f"[BŁĄD] {msg}", file=sys.stderr)
    sys.exit(1)
 
 
user, pw = os.getenv("SB_USERNAME"), os.getenv("SB_PASSWORD")
if not user or not pw:
    die("Ustaw SB_USERNAME i SB_PASSWORD (sekrety Actions).")
creds = {"user": user, "passwd": pw}
 
try:
    from statsbombpy import sb
except ImportError:
    die("pip install statsbombpy pandas")
 
# --- 1) Rozgrywki dostępne w licencji ---
comps = sb.competitions(creds=creds)
cols = [c for c in ["competition_id", "season_id", "country_name",
                    "competition_name", "season_name", "competition_gender"]
        if c in comps.columns]
out_comp = HERE / "statsbomb_competitions.csv"
comps[cols].to_csv(out_comp, index=False)
print(f"[OK] Rozgrywek w licencji: {len(comps)} → {out_comp.name}")
 
# Podgląd: kraje, męskie rozgrywki dorosłe (do wyboru nowych lig)
try:
    male = comps[comps.get("competition_gender", "male") == "male"] if "competition_gender" in comps else comps
    view = male[["country_name", "competition_name", "season_name",
                 "competition_id", "season_id"]].sort_values(["country_name", "competition_name"])
    print(view.to_string(index=False, max_rows=400))
except Exception as e:  # noqa
    print(f"[uwaga] podgląd: {e}", file=sys.stderr)
 
# --- 2) Kolumny player_season_stats (z Ekstraklasy) — do doboru metryk ---
try:
    stats = sb.player_season_stats(competition_id=38, season_id=318, creds=creds)
    cols_all = sorted(str(c) for c in stats.columns)
    out_cols = HERE / "statsbomb_columns.txt"
    out_cols.write_text("\n".join(cols_all), encoding="utf-8")
    print(f"\n[OK] Kolumn player_season_stats: {len(cols_all)} → {out_cols.name}")
    # wyróżnij metryki bramkarskie / obronne bramki
    gk = [c for c in cols_all if any(k in c.lower() for k in
          ["gk", "save", "gsaa", "keeper", "claim", "sweep", "shot_faced",
           "shots_faced", "xs_", "goals_conceded", "ot_shots", "positive_outcome",
           "launch", "pass_length", "goalkeep"])]
    print("\n[BRAMKARSKIE / kandydaci na metryki GK]:")
    for c in gk:
        print("   ", c)
except Exception as e:  # noqa
    print(f"[uwaga] Nie pobrano kolumn (Ekstraklasa 38/318): {e}", file=sys.stderr)
