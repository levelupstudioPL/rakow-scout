#!/usr/bin/env python3
# =====================================================================
# handicap.py — PEŁNA metoda liczenia handicapów lig względem Ekstraklasy.
#
# To jest kompletna, działająca logika (nie placeholder). Handicap ligi
# to procentowe odchylenie wybranej metryki danej linii (obrona/pomoc/atak)
# względem tej samej metryki w Ekstraklasie, przeliczone na skok RC.
#
# Zasada (wg ustalenia z użytkownikiem):
#   różnica +10% w danej linii  ->  handicap RC+1 w tym obszarze.
#
# Jedyna decyzja dziedzinowa analityka: KTÓRA metryka reprezentuje daną
# linię (LINE_METRICS poniżej). Sama matematyka jest gotowa.
# =====================================================================

from statistics import mean

# --- Które metryki reprezentują "poziom" danej linii ---
# Klucz = linia w modelu; wartość = nazwa kolumny metryki w danych StatsBomb.
# Analityk podmienia nazwy na te faktycznie dostępne i sensowne dla linii.
# Przykład: dla pomocy — udział/utrzymanie piłki; dla ataku — xG per 90 itd.
LINE_METRICS = {
    "Bramka": "player_season_op_passes_90",              # dystrybucja bramkarza (proxy poziomu gry)
    "Obrona": "player_season_padj_tackles_and_interceptions_90",  # akcje obronne / 90
    "Pomoc":  "player_season_op_xgchain_90",             # zaangażowanie w akcje bramkowe (środek)
    "Atak":   "player_season_np_xg_90",                  # xG / 90
}

# Ile procent różnicy = jeden skok RC (wg przykładu: 10% -> RC+1).
PCT_PER_RC_STEP = 10.0


def line_average(player_rows, line: str, pos_to_line: dict) -> float:
    """
    Średnia wartość metryki danej linii dla zawodników z tej linii.
    player_rows: iterowalne słowniki-zawodnicy z metrykami.
    pos_to_line: mapowanie pozycji -> linia (z fetch_statsbomb.py).
    """
    metric = LINE_METRICS.get(line)
    if not metric:
        return 0.0
    vals = []
    for row in player_rows:
        raw_pos = row.get("primary_position") or row.get("position")
        mapped = pos_to_line.get(raw_pos)
        if mapped and mapped[1] == line:
            v = row.get(metric)
            if isinstance(v, (int, float)):
                vals.append(float(v))
    return mean(vals) if vals else 0.0


def compute_handicaps(base_rows, league_rows, pos_to_line: dict) -> dict:
    """
    Liczy handicap ligi per linia względem bazy (Ekstraklasy).

    Zwraca np.: {"Bramka": 4, "Obrona": 8, "Pomoc": 10, "Atak": 6}
    gdzie liczby to % odchylenia (dodatnie = liga mocniejsza w tej linii).

    base_rows   — zawodnicy Ekstraklasy (tabela bazowa)
    league_rows — zawodnicy porównywanej ligi
    """
    out = {}
    for line in ("Bramka", "Obrona", "Pomoc", "Atak"):
        base_avg = line_average(base_rows, line, pos_to_line)
        lg_avg = line_average(league_rows, line, pos_to_line)
        if base_avg <= 0:
            out[line] = 0
            continue
        pct = round((lg_avg - base_avg) / base_avg * 100)
        out[line] = pct
    return out


def pct_to_rc_step(pct: float) -> int:
    """Zamienia % odchylenia na skok RC (10% -> 1, 20% -> 2, itd.)."""
    return round(pct / PCT_PER_RC_STEP)


def apply_handicap_to_level(raw_level: int, line: str, handicaps: dict) -> int:
    """
    Koryguje surowy poziom zawodnika o handicap jego ligi w danej linii.
    Każdy skok RC to +2 pkt na skali 0-100 (spójne z aplikacją).
    """
    pct = handicaps.get(line, 0)
    return raw_level + pct_to_rc_step(pct) * 2


# --- Samodzielny test na danych syntetycznych (bez StatsBomb) ---
if __name__ == "__main__":
    pos_to_line = {
        "Center Midfield": ("CM", "Pomoc"),
        "Center Forward": ("ST", "Atak"),
    }
    base = [
        {"position": "Center Midfield", "possession_retention_pct": 50.0},
        {"position": "Center Forward", "xg_per90": 0.40},
    ]
    belgia = [
        {"position": "Center Midfield", "possession_retention_pct": 55.0},  # +10%
        {"position": "Center Forward", "xg_per90": 0.424},                  # +6%
    ]
    h = compute_handicaps(base, belgia, pos_to_line)
    print("Handicap Ligi Belgijskiej vs Ekstraklasa:", h)
    print("  Pomoc: {}% -> RC+{}".format(h["Pomoc"], pct_to_rc_step(h["Pomoc"])))
    print("  Atak:  {}% -> RC+{}".format(h["Atak"], pct_to_rc_step(h["Atak"])))
    print("  Zawodnik pomocy raw 70 ->", apply_handicap_to_level(70, "Pomoc", h))
