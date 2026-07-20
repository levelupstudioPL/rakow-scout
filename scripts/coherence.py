#!/usr/bin/env python3
# =====================================================================
# coherence.py — rdzeń analizy koherencji.
#
# Dwie miary liczone z realnych metryk StatsBomb:
#   1. POZIOM (0-100): jak dobry jest zawodnik — percentyl wybranych
#      metryk względem ligi bazowej (Ekstraklasy).
#   2. KOHERENCJA (0-100): jak PODOBNIE gra kandydat do konkretnego
#      zawodnika Rakowa — podobieństwo profili na metrykach właściwych
#      dla pozycji (position-specific similarity).
#
# Metryki dobrane per linia — profil gry definiują akcje typowe dla roli.
# =====================================================================

import math

# --- Metryki definiujące PROFIL GRY per linia ---
# Do koherencji (podobieństwa) i do poziomu. Nazwy = pola StatsBomb.
LINE_METRICS = {
    "Bramka": [
        # Bramkarze mają osobny zestaw danych; przy braku pól fallback niżej.
        "player_season_gsaa_90", "player_season_save_ratio",
        "player_season_op_passes_90", "player_season_passing_ratio",
    ],
    "Obrona": [
        "player_season_padj_tackles_and_interceptions_90",
        "player_season_aerial_wins_90", "player_season_aerial_ratio",
        "player_season_clearance_90", "player_season_challenge_ratio",
        "player_season_op_passes_90", "player_season_passing_ratio",
        "player_season_op_f3_passes_90",
    ],
    "Pomoc": [
        "player_season_op_xgchain_90", "player_season_xgbuildup_90",
        "player_season_key_passes_90", "player_season_xa_90",
        "player_season_passes_into_box_90", "player_season_op_passes_90",
        "player_season_passing_ratio", "player_season_forward_pass_proportion",
        "player_season_padj_tackles_and_interceptions_90",
        "player_season_dribbles_90", "player_season_op_f3_passes_90",
    ],
    "Atak": [
        "player_season_np_xg_90", "player_season_npg_90",
        "player_season_np_shots_90", "player_season_touches_inside_box_90",
        "player_season_xa_90", "player_season_key_passes_90",
        "player_season_conversion_ratio", "player_season_aerial_wins_90",
        "player_season_op_xgchain_90",
    ],
}

# Podzbiór metryk "jakościowych" (wyższa wartość = lepszy) do liczenia POZIOMU.
# Metryki proporcjonalne (ratio, proportion) pomijamy w poziomie — opisują styl,
# nie jakość. Zostają za to w profilu koherencji.
#
# WARIANT OSTROŻNY (rozszerzenie obrony + bramki):
#   - Obrona: do czystej defensywy (odbiory, powietrze, wybicia) DODANO wymiar
#     gry w wyprowadzeniu piłki: op_passes_90 (wolumen gry nogą) i op_f3_passes_90
#     (podania w tercję ofensywną). Powód: nowoczesny stoper to też pierwszy
#     rozgrywający — poprzedni zestaw tego wymiaru w ogóle nie widział. To NIE są
#     metryki proporcjonalne, więc uczciwie wchodzą do poziomu.
#   - Bramka: dodano op_passes_90 (gra nogą bramkarza). Danych stricte bramkarskich
#     (gsaa/save_ratio) w tych ligach zwykle brak; to daje modelowi cokolwiek do
#     policzenia zamiast pustki. UWAGA: to i tak nie mierzy obron strzałów — tych
#     danych po prostu nie ma w źródle.
#   - Pomoc i Atak: BEZ ZMIAN — zestawy zrównoważone, dokładanie rozcieńczyłoby
#     sygnał.
#
# UCZCIWOŚĆ: dobór i waga tych metryk to założenie piłkarskie — do weryfikacji
# przez kogoś znającego Ekstraklasę i te ligi. Rozszerzenie pogłębia model, ale
# nie zmniejsza potrzeby jego walidacji.
QUALITY_METRICS = {
    "Bramka": ["player_season_gsaa_90", "player_season_save_ratio",
               "player_season_op_passes_90"],
    "Obrona": ["player_season_padj_tackles_and_interceptions_90",
               "player_season_aerial_wins_90", "player_season_clearance_90",
               "player_season_op_passes_90", "player_season_op_f3_passes_90"],
    "Pomoc": ["player_season_op_xgchain_90", "player_season_xgbuildup_90",
              "player_season_key_passes_90", "player_season_xa_90",
              "player_season_passes_into_box_90",
              "player_season_padj_tackles_and_interceptions_90"],
    "Atak": ["player_season_np_xg_90", "player_season_npg_90",
             "player_season_np_shots_90", "player_season_touches_inside_box_90",
             "player_season_xa_90"],
}


def _val(row, key):
    v = row.get(key)
    if not isinstance(v, (int, float)):
        return None
    fv = float(v)
    if math.isnan(fv) or math.isinf(fv):  # puste/niepoprawne metryki -> brak
        return None
    return fv


def build_league_stats(rows, line):
    """Dla każdej metryki linii liczy min/max/średnią/odchylenie w populacji ligi.
    Służy do normalizacji (percentyl / z-score)."""
    metrics = LINE_METRICS.get(line, [])
    stats = {}
    for m in metrics:
        vals = [_val(r, m) for r in rows]
        vals = [v for v in vals if v is not None]
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        stats[m] = {"mean": mean, "std": math.sqrt(var) or 1.0,
                    "min": min(vals), "max": max(vals),
                    "sorted": sorted(vals)}
    return stats


def _percentile(value, sorted_vals):
    """Percentyl wartości w posortowanej populacji (0-100)."""
    if not sorted_vals:
        return 50.0
    below = sum(1 for v in sorted_vals if v < value)
    return 100.0 * below / len(sorted_vals)


# DIAGNOSTYKA: zlicza, ile metryk realnie weszlo do liczenia poziomu.
# Odpowiada na pytanie: czy rozszerzenie QUALITY_METRICS dziala, czy dodane
# metryki sa puste w danych StatsBomb (wtedy sa po cichu pomijane).
DIAG = {}

def quality_level(row, line, league_stats):
    """POZIOM 0-100: średni percentyl metryk jakościowych względem ligi bazowej."""
    metrics = QUALITY_METRICS.get(line, [])
    pcts = []
    used, missing = [], []
    for m in metrics:
        v = _val(row, m)
        st = league_stats.get(m)
        if v is None or not st:
            missing.append(m.replace("player_season_", ""))
            continue
        used.append(m.replace("player_season_", ""))
        pcts.append(_percentile(v, st["sorted"]))
    # Zapamietaj statystyke per linia (pierwsze 3 przypadki wystarcza)
    d = DIAG.setdefault(line, {"n": 0, "used": None, "missing": None, "counts": {}})
    d["n"] += 1
    key = f"{len(used)}/{len(metrics)}"
    d["counts"][key] = d["counts"].get(key, 0) + 1
    if d["used"] is None:
        d["used"], d["missing"] = used, missing
    if not pcts:
        return 72  # neutralny fallback gdy brak metryk (np. bramkarze bez danych)
    avg = sum(pcts) / len(pcts)
    if math.isnan(avg) or math.isinf(avg):
        return 72
    return max(0, min(100, round(avg)))


def _zprofile(row, line, base_stats):
    """Profil zawodnika jako wektor z-score względem ligi bazowej."""
    metrics = LINE_METRICS.get(line, [])
    vec = []
    for m in metrics:
        v = _val(row, m)
        st = base_stats.get(m)
        if v is None or not st:
            vec.append(0.0)
        else:
            vec.append((v - st["mean"]) / st["std"])
    return vec


def coherence(candidate_row, rakow_row, line, base_stats):
    """KOHERENCJA 0-100: podobieństwo profili gry (kandydat vs zawodnik Rakowa).
    Liczone jako podobieństwo kosinusowe wektorów z-score, przeskalowane 0-100."""
    a = _zprofile(candidate_row, line, base_stats)
    b = _zprofile(rakow_row, line, base_stats)
    if not a or not b:
        return 50
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 50
    cos = dot / (na * nb)  # -1..1
    result = (cos + 1) / 2 * 100
    if math.isnan(result) or math.isinf(result):
        return 50
    return max(0, min(100, round(result)))  # 0..100, zabezpieczone


if __name__ == "__main__":
    # Test na danych syntetycznych
    base = [
        {"primary_position": "Center Midfield",
         "player_season_op_xgchain_90": 0.5, "player_season_key_passes_90": 1.2,
         "player_season_xa_90": 0.1, "player_season_op_passes_90": 30,
         "player_season_padj_tackles_and_interceptions_90": 1.5},
        {"primary_position": "Center Midfield",
         "player_season_op_xgchain_90": 0.3, "player_season_key_passes_90": 0.8,
         "player_season_xa_90": 0.05, "player_season_op_passes_90": 25,
         "player_season_padj_tackles_and_interceptions_90": 2.0},
    ]
    st = build_league_stats(base, "Pomoc")
    print("Poziom gracza 1:", quality_level(base[0], "Pomoc", st))
    print("Koherencja 1↔2:", coherence(base[0], base[1], "Pomoc", st), "%")
    print("Koherencja 1↔1:", coherence(base[0], base[0], "Pomoc", st), "% (powinno ~100)")
