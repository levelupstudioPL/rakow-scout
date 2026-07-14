#!/usr/bin/env python3
# Pomocniczy skrypt: wypisuje rozgrywki/sezony dostępne w Twojej licencji StatsBomb.
# Użyj wyników, by uzupełnić LEAGUE_CONFIG w fetch_statsbomb.py.
#
# Poświadczenia — jak w fetch_statsbomb.py, wyłącznie ze zmiennych środowiskowych.
#   export SB_USERNAME="..."; export SB_PASSWORD="..."
#   pip install statsbombpy pandas
#   python scripts/list_statsbomb_competitions.py

import os
import sys

user, pw = os.getenv("SB_USERNAME"), os.getenv("SB_PASSWORD")
if not user or not pw:
    print("[BŁĄD] Ustaw SB_USERNAME i SB_PASSWORD w zmiennych środowiskowych.", file=sys.stderr)
    sys.exit(1)

try:
    from statsbombpy import sb
except ImportError:
    print("[BŁĄD] pip install statsbombpy pandas", file=sys.stderr)
    sys.exit(1)

comps = sb.competitions(creds={"user": user, "passwd": pw})
cols = [c for c in ["competition_id", "season_id", "country_name",
                    "competition_name", "season_name"] if c in comps.columns]
print(comps[cols].to_string(index=False))
