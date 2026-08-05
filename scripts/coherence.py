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
import os
 
# --- Metryki definiujące PROFIL GRY per linia ---
# Do koherencji (podobieństwa) i do poziomu. Nazwy = pola StatsBomb.
LINE_METRICS = {
    "Bramka": [
        # Rozbudowany profil bramkarza: shot-stopping + wartość ogólna + styl
        # gry nogą (krótka vs długa dystrybucja). Metryki realnie dostępne w
        # StatsBomb dla tych lig (potwierdzone w statsbomb_columns.txt).
        "player_season_gsaa_90", "player_season_save_ratio",
        "player_season_positive_outcome_90", "player_season_obv_gk_90",
        "player_season_op_passes_90", "player_season_passing_ratio",
        "player_season_long_balls_90", "player_season_long_ball_ratio",
        "player_season_pass_length",
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
# Metryki wolumenowe bez natywnego wariantu per-posiadanie — normalizowane przez
# PROXY posiadania drużyny (współczynnik z wolumenu podań drużyny w obrębie ligi).
# fetch_statsbomb dolicza do wierszy pola z sufiksem __tpadj PRZED liczeniem RC.
TEAM_NORM_SUFFIX = "__tpadj"
TEAM_NORM_METRICS = [
    "player_season_key_passes_90",
    "player_season_passes_into_box_90",
    "player_season_np_shots_90",
    "player_season_touches_inside_box_90",
]
 
# WERSJA SUROWA (per-90, wolumen) — historyczna. Problem, na który słusznie zwrócił
# uwagę audyt: metryki wolumenowe (podania, xgchain/xgbuildup na 90) zawyżają zawodników
# drużyn dużo posiadających piłkę (skrzydła, „szóstki”), a zaniżają obrońców drużyn
# broniących się nisko — bo więcej piłki = więcej akcji, niezależnie od jakości.
QUALITY_METRICS_RAW = {
    "Bramka": ["player_season_gsaa_90", "player_season_save_ratio",
               "player_season_positive_outcome_90", "player_season_obv_gk_90",
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
 
# WERSJA POSSESSION-ADJUSTED — używa natywnych metryk StatsBomb skorygowanych o
# posiadanie tam, gdzie problem jest największy (Obrona, Pomoc):
#   • padj_clearances / padj_pressures — obronne akcje znormalizowane o posiadanie
#     rywala (obrońca broniącej się drużyny nie jest już karany za „mało piłki”);
#   • *_per_possession (xgchain/xgbuildup) — wkład w rozgrywanie NA POSIADANIE,
#     a nie na 90 min → znika premia za sam wolumen posiadania drużyny.
# RC liczy każdą metrykę jako PERCENTYL vs Ekstraklasa, więc mieszanie skal
# (per-90 i per-posiadanie) jest bezpieczne. Bramka i Atak bez zmian — tam problem
# posiadania praktycznie nie występuje (metryki bramkarskie i xG/output).
QUALITY_METRICS_PADJ = {
    "Bramka": ["player_season_gsaa_90", "player_season_save_ratio",
               "player_season_positive_outcome_90", "player_season_obv_gk_90",
               "player_season_op_passes_90"],
    "Obrona": ["player_season_padj_tackles_and_interceptions_90",
               "player_season_padj_clearances_90", "player_season_padj_pressures_90",
               "player_season_aerial_wins_90",
               "player_season_op_xgbuildup_per_possession"],
    "Pomoc": ["player_season_op_xgchain_per_possession",
              "player_season_xgbuildup_per_possession",
              "player_season_key_passes_90__tpadj", "player_season_xa_90",
              "player_season_passes_into_box_90__tpadj",
              "player_season_padj_tackles_and_interceptions_90"],
    "Atak": ["player_season_np_xg_90", "player_season_npg_90",
             "player_season_np_shots_90__tpadj",
             "player_season_touches_inside_box_90__tpadj",
             "player_season_xa_90"],
}
 
# Przełącznik: POSSESSION_ADJUST=0 wraca do wersji surowej (do porównań A/B).
POSSESSION_ADJUST = os.getenv("POSSESSION_ADJUST", "1") not in ("0", "false", "False")
QUALITY_METRICS = QUALITY_METRICS_PADJ if POSSESSION_ADJUST else QUALITY_METRICS_RAW
 
 
# --- Fizyka (SkillCorner) w profilu KOHERENCJI (styl gry) ---
# WAŻNE: fizyka wchodzi tylko do koherencji (podobieństwo stylu), NIE do RC
# (QUALITY_METRICS). Walidacja na ocenach trenerów pokazała, że domieszka
# fizyki do RC pogarsza zgodność — dlatego RC zostaje czysto techniczne.
# Pola dokładane do wierszy przez physical.enrich_rows (nazwy natywne SkillCornera).
# Bramkarze: bez fizyki (styl ruchu nieistotny dla podobieństwa GK).
_PHYS_STYLE = [
    "total_metersperminute_full_all",   # tempo/wolumen ruchu
    "hsr_distance_full_all",            # biegi wysokiej prędkości
    "sprint_count_full_all",           # częstość sprintów
    "hi_count_full_all",               # akcje wysokiej intensywności
    "psv99",                           # prędkość szczytowa
    "highaccel_count_full_all",        # dynamika (przyspieszenia)
    "cod_count_full_all",              # zwroty / zmiany kierunku
]
PHYS_STYLE_METRICS = {
    "Bramka": [],
    "Obrona": _PHYS_STYLE,
    "Pomoc": _PHYS_STYLE,
    "Atak": _PHYS_STYLE,
}
 
# --- Game Intelligence (SkillCorner) w profilu KOHERENCJI (styl gry) ---
# Trzecia warstwa stylu (obok techniki StatsBomb i fizyki). Też TYLKO koherencja,
# nie RC. Metryki opisują SPOSÓB gry: biegi bez piłki, styl podań, oferowanie się,
# prowadzenie/odporność na pressing, angażowanie/pressing. Bramkarze: bez GI.
_GI_STYLE = [
    "offballrun_count", "offballrun_count_dangerous",
    "offballrun_count_penaltyarea", "offballrun_count_abovehsr",
    "pass_count_completed", "pass_avgdistance",
    "pass_count_longrange_attempted", "pass_count_linebreak_completed",
    "optionoffered_count", "optionoffered_count_inspace",
    "optionoffered_count_penaltyarea", "optionoffered_count_dangerous",
    "possession_count", "longcarry_count_forwardtrajectory",
    "possession_count_forwardmomentum", "possession_count_escapedpressure",
    "onballengagement_count", "onballengagement_count_directregain",
    "onballengagement_count_pressingchain", "onballengagement_count_forwardtrajectory",
]
GI_STYLE_METRICS = {
    "Bramka": [],
    "Obrona": _GI_STYLE,
    "Pomoc": _GI_STYLE,
    "Atak": _GI_STYLE,
}
 
# Wagi w profilu koherencji (<1 = warstwa wzbogaca, nie dominuje techniki).
# GI ma dużo metryk, więc niższa waga na metrykę niż fizyka, by SkillCorner
# łącznie nie przytłoczył sygnału technicznego StatsBomb.
PHYS_WEIGHT = 0.5
GI_WEIGHT = 0.35
METRIC_WEIGHTS = {}
METRIC_WEIGHTS.update({m: PHYS_WEIGHT for m in _PHYS_STYLE})
METRIC_WEIGHTS.update({m: GI_WEIGHT for m in _GI_STYLE})
 
 
def _profile_metrics(line):
    """Pełny profil koherencji = technika StatsBomb + fizyka + Game Intelligence
    (te z warstw SkillCornera, które realnie dołączono do wiersza)."""
    return (LINE_METRICS.get(line, [])
            + PHYS_STYLE_METRICS.get(line, [])
            + GI_STYLE_METRICS.get(line, []))
 
 
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
    Służy do normalizacji (percentyl / z-score). Obejmuje profil koherencji ORAZ
    obie wersje metryk jakościowych (surową i possession-adjusted), żeby dało się
    policzyć RC dowolnym zestawem — także do diagnostyki A/B."""
    metrics = list(dict.fromkeys(
        _profile_metrics(line)
        + QUALITY_METRICS_RAW.get(line, [])
        + QUALITY_METRICS_PADJ.get(line, [])))
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
 
# --- SHRINKAGE percentyla przy małej próbie minut (odpowiedź na audyt, p.9) ---
# Problem: zawodnik tuż powyżej progu minut (mała próba) potrafi mieć zawyżony
# percentyl z jednego dobrego okresu. Empirical-Bayes: ściągamy RC w stronę PRIORU
# (mediana rozkładu = ~50 percentyl) tym mocniej, im mniej minut.
#   waga w = minuty / (minuty + K);  RC' = w*RC + (1-w)*PRIOR
# K = liczba minut, przy której ufamy próbie w połowie (domyślnie 300 ~ 3-4 mecze
# ponad progiem 540). Pełny sezon (~2500+ min) → shrink pomijalny.
SHRINK = os.getenv("SHRINK", "1") not in ("0", "false", "False")
SHRINK_K = float(os.getenv("SHRINK_K", "300"))
SHRINK_PRIOR = float(os.getenv("SHRINK_PRIOR", "50"))
 
 
def shrink_rc(rc, minutes):
    """Ściąga RC w stronę prioru proporcjonalnie do małej próby minut. Zwraca
    (rc_po, delta). Gdy SHRINK wyłączony albo brak minut — bez zmian."""
    if not SHRINK or not isinstance(minutes, (int, float)) or minutes <= 0:
        return rc, 0
    w = minutes / (minutes + SHRINK_K)
    out = max(0, min(100, round(w * rc + (1 - w) * SHRINK_PRIOR)))
    return out, out - rc
 
 
def quality_level(row, line, league_stats, metrics=None, minutes=None):
    """POZIOM 0-100: średni percentyl metryk jakościowych względem ligi bazowej.
    metrics=None → aktywny zestaw (QUALITY_METRICS); można podać własny (do A/B).
    minutes podane → stosujemy shrinkage małej próby (patrz shrink_rc). Diagnostyka
    possession-adjustment woła bez minut, żeby izolować sam efekt doboru metryk."""
    metrics = metrics if metrics is not None else QUALITY_METRICS.get(line, [])
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
    rc = max(0, min(100, round(avg)))
    return shrink_rc(rc, minutes)[0]  # shrinkage tylko gdy podano minuty
 
 
def _zprofile(row, line, base_stats):
    """Profil zawodnika jako wektor z-score względem ligi bazowej.
    Metryki fizyczne (SkillCorner) wchodzą z wagą METRIC_WEIGHTS (<1)."""
    metrics = _profile_metrics(line)
    vec = []
    for m in metrics:
        w = METRIC_WEIGHTS.get(m, 1.0)
        v = _val(row, m)
        st = base_stats.get(m)
        if v is None or not st:
            vec.append(0.0)
        else:
            vec.append(w * (v - st["mean"]) / st["std"])
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
 
 
# =====================================================================
# PROFIL STYLU (uniwersalny) — do koherencji „każdy z każdym" w drużynie.
# Jeden, POZYCYJNIE NIEZALEŻNY zestaw metryk (technika + fizyka + GI), z-score
# vs Ekstraklasa, żeby dało się policzyć podobieństwo stylu MIĘDZY dowolnymi
# dwoma zawodnikami pola. Eksportowany do data.json jako pole "profile";
# front liczy z niego macierz koherencji składu. Bramkarze: profil pomijany.
# =====================================================================
UNIVERSAL_STYLE = [
    "player_season_op_passes_90", "player_season_passing_ratio",
    "player_season_forward_pass_proportion", "player_season_op_f3_passes_90",
    "player_season_padj_tackles_and_interceptions_90", "player_season_aerial_wins_90",
    "player_season_dribbles_90", "player_season_key_passes_90",
    "player_season_xa_90", "player_season_np_xg_90", "player_season_op_xgchain_90",
    "total_metersperminute_full_all", "sprint_count_full_all", "psv99",
    "offballrun_count", "pass_avgdistance", "onballengagement_count",
]
 
 
def build_universal_stats(rows):
    """Średnia/odchylenie metryk UNIVERSAL_STYLE w populacji bazowej (Ekstraklasa)."""
    stats = {}
    for m in UNIVERSAL_STYLE:
        vals = [v for v in (_val(r, m) for r in rows) if v is not None]
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        stats[m] = {"mean": mean, "std": math.sqrt(var) or 1.0}
    return stats
 
 
def style_profile(row, ustats):
    """Wektor z-score stylu zawodnika (stała długość = len(UNIVERSAL_STYLE))."""
    vec = []
    for m in UNIVERSAL_STYLE:
        v = _val(row, m)
        st = ustats.get(m)
        vec.append(0.0 if (v is None or not st) else round((v - st["mean"]) / st["std"], 2))
    return vec
 
 
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
 
