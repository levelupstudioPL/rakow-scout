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
    # KOHERENCJA = OŚ STYLU (po audycie analityka). Tu wchodzą TYLKO deskryptory
    # SPOSOBU gry — wolumeny podań/strzałów, proporcje, tendencje, prowadzenia,
    # aktywność defensywna — a NIE metryki jakości/outputu (xG, xGChain, xGBuildup,
    # xA, gsaa, save_ratio, obv, gole). Te ostatnie przeniesione do RC (poziom).
    # Dzięki temu symetryczna kara Mahalanobisa jest uzasadniona: szukamy zawodnika
    # o IDENTYCZNYM stylu (koherencja), a jakość rozstrzyga osobno RC. Do koherencji
    # dochodzą jeszcze fizyka (waga 0.5) i Game Intelligence (0.35) — też czysto stylowe.
    "Bramka": [
        # Styl dystrybucji + pozycjonowanie (sweeper) bramkarza — bez shot-stoppingu (to RC).
        # Pogłębione z 5 do 8 wymiarów: sam profil dystrybucji był zbyt cienki (koherencja
        # GK zbijała się do ~100). Dokładamy długość dystrybucji i tendencję do wychodzenia.
        "player_season_op_passes_90", "player_season_passing_ratio",
        "player_season_long_balls_90", "player_season_long_ball_ratio",
        "player_season_pass_length",
        "player_season_np_optimal_gk_dlength",   # optymalna długość dystrybucji (styl gry nogą)
        "player_season_da_aggressive_distance",  # jak wysoko od bramki interweniuje (sweeper)
        "player_season_aggressive_actions_90",   # proaktywne akcje poza polem karnym
    ],
    "Obrona": [
        # Aktywność i styl defensywny + styl wyprowadzenia (bez ratio jakościowych,
        # które poszły do RC).
        "player_season_padj_tackles_and_interceptions_90",
        "player_season_aerial_wins_90", "player_season_clearance_90",
        "player_season_op_passes_90", "player_season_passing_ratio",
        "player_season_op_f3_passes_90", "player_season_forward_pass_proportion",
    ],
    "Pomoc": [
        # Styl gry środka: wolumen kreacji i penetracji, tendencja do przodu, drybling,
        # aktywność defensywna. Sama JAKOŚĆ kreacji (xA, xGChain) jest w RC.
        "player_season_key_passes_90", "player_season_passes_into_box_90",
        "player_season_op_passes_90", "player_season_passing_ratio",
        "player_season_forward_pass_proportion",
        "player_season_padj_tackles_and_interceptions_90",
        "player_season_dribbles_90", "player_season_op_f3_passes_90",
    ],
    "Atak": [
        # Styl napastnika: wolumen strzałów, pozycjonowanie w polu, kreacja,
        # gra w powietrzu, drybling. JAKOŚĆ (xG, gole, xA, efektywność) jest w RC.
        "player_season_np_shots_90", "player_season_touches_inside_box_90",
        "player_season_key_passes_90", "player_season_aerial_wins_90",
        "player_season_dribbles_90",
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
 
# WERSJA SUROWA (per-90, wolumen) — Twój dotychczasowy zestaw. Problem z audytu:
# metryki wolumenowe zawyżają zawodników drużyn dużo posiadających piłkę.
QUALITY_METRICS_RAW = {
    # RC = OŚ JAKOŚCI (audyt analityka): tylko jakość/efektywność, bez surowego wolumenu.
    # Obrona: wartość działań obronnych (obv_defensive_action) + skuteczność
    # (aerial_ratio, challenge_ratio, blocks_per_shot) zamiast liczby akcji.
    "Bramka": ["player_season_gsaa_90", "player_season_save_ratio",
               "player_season_positive_outcome_90", "player_season_obv_gk_90"],
    "Obrona": ["player_season_obv_defensive_action_90", "player_season_aerial_ratio",
               "player_season_challenge_ratio", "player_season_blocks_per_shot",
               "player_season_op_xgbuildup_90"],
    "Pomoc": ["player_season_op_xgchain_90", "player_season_xgbuildup_90",
              "player_season_xa_90", "player_season_obv_defensive_action_90"],
    "Atak": ["player_season_np_xg_90", "player_season_npg_90",
             "player_season_xa_90", "player_season_np_xg_per_shot"],
}
 
# WERSJA POSSESSION-ADJUSTED — natywne metryki StatsBomb skorygowane o posiadanie
# (padj_*, *_per_possession) tam, gdzie problem jest największy (Obrona, Pomoc),
# plus metryki wolumenowe znormalizowane przez posiadanie drużyny (sufiks __tpadj).
# RC liczy każdą metrykę jako PERCENTYL vs Ekstraklasa, więc mieszanie skal jest OK.
# Bramka i Atak (xG/output) — bez zmian, tam problem posiadania nie występuje.
QUALITY_METRICS_PADJ = {
    # Jak RAW, ale budowanie/rozgrywanie liczone per-posiadanie. Wskaźniki skuteczności
    # (ratio, per_shot) są niewrażliwe na posiadanie → identyczne jak w RAW.
    "Bramka": ["player_season_gsaa_90", "player_season_save_ratio",
               "player_season_positive_outcome_90", "player_season_obv_gk_90"],
    "Obrona": ["player_season_obv_defensive_action_90", "player_season_aerial_ratio",
               "player_season_challenge_ratio", "player_season_blocks_per_shot",
               "player_season_op_xgbuildup_per_possession"],
    "Pomoc": ["player_season_op_xgchain_per_possession",
              "player_season_xgbuildup_per_possession",
              "player_season_xa_90", "player_season_obv_defensive_action_90"],
    "Atak": ["player_season_np_xg_90", "player_season_npg_90",
             "player_season_xa_90", "player_season_np_xg_per_shot"],
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
 
# --- SHRINKAGE percentyla przy małej próbie minut (audyt, p.9) ---
# Empirical-Bayes: RC ściągane w stronę prioru (mediana rozkładu = ~50 percentyl)
# tym mocniej, im mniej minut. w = minuty/(minuty+K); RC' = w*RC + (1-w)*PRIOR.
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
    minutes podane → stosujemy shrinkage małej próby. Diagnostyka possession-adjustment
    woła bez minut, żeby izolować sam efekt doboru metryk."""
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
 
 
# --- Mahalanobis (wybielony kosinus) w koherencji (audyt, p. 17) ---
# Zwykły kosinus na z-score PODWÓJNIE liczy skorelowane metryki (patrz p. 6:
# xA↔podania kluczowe r=0,90 itd.). Wybielony kosinus = kosinus w przestrzeni
# ZDEKORELOWANEJ macierzą kowariancji: aᵀP·b / sqrt(aᵀP·a · bᵀP·b), gdzie P = Σ⁻¹
# (precyzja) profilu w populacji bazowej. Zachowuje magnitude-invariance kosinusa
# (koherencja = STYL, nie poziom), a jednocześnie odważa redundancję — czyli lek na
# multikolinearność. Przełącznik: COH_MAHALANOBIS=0 wraca do zwykłego kosinusa.
COH_MAHALANOBIS = os.getenv("COH_MAHALANOBIS", "1") not in ("0", "false", "False")
COH_SHRINK = float(os.getenv("COH_SHRINK", "0.15"))  # ściąganie kowariancji do diagonali
 
 
def _invert(mat):
    """Odwrotność macierzy kwadratowej (Gauss-Jordan, pure Python). None gdy osobliwa."""
    n = len(mat)
    A = [list(mat[i]) + [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(A[r][col]))
        if abs(A[piv][col]) < 1e-12:
            return None
        A[col], A[piv] = A[piv], A[col]
        pv = A[col][col]
        A[col] = [x / pv for x in A[col]]
        for r in range(n):
            if r != col and A[r][col] != 0.0:
                f = A[r][col]
                A[r] = [A[r][k] - f * A[col][k] for k in range(2 * n)]
    return [row[n:] for row in A]
 
 
def build_precision(base_rows, line, base_stats):
    """Macierz precyzji P = Σ⁻¹ profilu koherencji w populacji bazowej (do wybielonego
    kosinusa). Kowariancja ściągana do diagonali (COH_SHRINK) + drobny ridge, żeby była
    zawsze odwracalna. Zwraca None (→ coherence spada do zwykłego kosinusa) gdy Mahalanobis
    wyłączony, próba za mała albo macierz osobliwa."""
    if not COH_MAHALANOBIS:
        return None
    metrics = _profile_metrics(line)
    d = len(metrics)
    if d == 0:
        return None
    vecs = [_zprofile(r, line, base_stats) for r in base_rows]
    n = len(vecs)
    if n < d + 5:
        return None
    means = [sum(v[i] for v in vecs) / n for i in range(d)]
    cov = [[0.0] * d for _ in range(d)]
    for v in vecs:
        dv = [v[i] - means[i] for i in range(d)]
        for i in range(d):
            di = dv[i]
            if di == 0.0:
                continue
            row = cov[i]
            for j in range(i, d):
                row[j] += di * dv[j]
    for i in range(d):
        for j in range(i, d):
            c = cov[i][j] / n
            cov[i][j] = c
            cov[j][i] = c
    diag = [cov[i][i] for i in range(d)]
    s = COH_SHRINK
    for i in range(d):
        for j in range(d):
            if i == j:
                cov[i][j] = cov[i][j] + 1e-3 * (diag[i] or 1.0) + 1e-6
            else:
                cov[i][j] = (1.0 - s) * cov[i][j]
    return _invert(cov)
 
 
def coherence(candidate_row, rakow_row, line, base_stats, precision=None):
    """KOHERENCJA 0-100: podobieństwo profili gry (kandydat vs zawodnik Rakowa).
    Gdy podano precision i Mahalanobis włączony — WYBIELONY KOSINUS (odważa skorelowane
    metryki). Inaczej zwykły kosinus wektorów z-score. Oba magnitude-invariant (styl)."""
    a = _zprofile(candidate_row, line, base_stats)
    b = _zprofile(rakow_row, line, base_stats)
    if not a or not b:
        return 50
    if COH_MAHALANOBIS and precision is not None:
        d = len(a)
        Pb = [sum(precision[i][k] * b[k] for k in range(d)) for i in range(d)]
        Pa = [sum(precision[i][k] * a[k] for k in range(d)) for i in range(d)]
        num = sum(a[i] * Pb[i] for i in range(d))   # aᵀ P b
        da = sum(a[i] * Pa[i] for i in range(d))     # aᵀ P a
        db = sum(b[i] * Pb[i] for i in range(d))     # bᵀ P b
        if da > 0 and db > 0:
            cos = max(-1.0, min(1.0, num / math.sqrt(da * db)))
            res = (cos + 1) / 2 * 100
            if not (math.isnan(res) or math.isinf(res)):
                return max(0, min(100, round(res)))
        # w innym razie: fallback do zwykłego kosinusa poniżej
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
 
 
# =====================================================================
#  PROFIL DOPASOWANY DO POZYCJI (position-fitted)
#  Bogatszy zestaw atrybutów DLA KAŻDEJ LINII osobno — pod panele
#  "mocne strony" i "kandydat vs nasz". Z-score liczony względem
#  zawodników TEJ SAMEJ LINII w Ekstraklasie (position-fair). Kolejność
#  (metryka, etykieta) jest źródłem prawdy — etykiety trafiają do
#  data.json (meta.style_labels), więc front ich nie powiela.
#  Wszystkie kolumny potwierdzone w statsbomb_columns.txt.
# =====================================================================
_PHYS_LABELED = [
    ("total_metersperminute_full_all", "Dystans / intensywność"),
    ("psv99", "Prędkość maksymalna"),
    ("sprint_count_full_all", "Liczba sprintów"),
]
POS_STYLE = {
    "Bramka": [
        ("player_season_gsaa_90", "Obrony ponad oczekiwane (GSAA)"),
        ("player_season_save_ratio", "Skuteczność obron"),
        ("player_season_positive_outcome_90", "Pozytywne interwencje"),
        ("player_season_obv_gk_90", "Wartość działań GK (OBV)"),
        ("player_season_op_passes_90", "Podania (wolumen)"),
        ("player_season_passing_ratio", "Celność podań"),
        ("player_season_long_balls_90", "Długie podania"),
        ("player_season_long_ball_ratio", "Udział długich podań"),
        ("player_season_pass_length", "Śr. długość podania"),
        ("player_season_np_optimal_gk_dlength", "Długość dystrybucji"),
        ("player_season_da_aggressive_distance", "Wysokość interwencji"),
        ("player_season_aggressive_actions_90", "Akcje poza polem"),
    ],
    "Obrona": [
        ("player_season_padj_tackles_and_interceptions_90", "Odbiory i przechwyty"),
        ("player_season_padj_tackles_90", "Odbiory (PAdj)"),
        ("player_season_padj_interceptions_90", "Przechwyty (PAdj)"),
        ("player_season_aerial_wins_90", "Pojedynki powietrzne"),
        ("player_season_aerial_ratio", "Skuteczność w powietrzu"),
        ("player_season_padj_clearances_90", "Wybicia (PAdj)"),
        ("player_season_blocks_per_shot", "Bloki strzałów"),
        ("player_season_ball_recoveries_90", "Odzyski piłki"),
        ("player_season_pressures_90", "Pressing (liczba)"),
        ("player_season_op_passes_90", "Podania (wolumen)"),
        ("player_season_passing_ratio", "Celność podań"),
        ("player_season_forward_pass_proportion", "Podania do przodu"),
        ("player_season_deep_progressions_90", "Progresja piłki"),
        ("player_season_op_f3_passes_90", "Podania w tercji ataku"),
        ("player_season_carries_90", "Prowadzenia piłki"),
        ("player_season_obv_90", "Wartość działań (OBV)"),
    ] + _PHYS_LABELED,
    "Pomoc": [
        ("player_season_op_xgchain_90", "Udział w akcjach (xGChain)"),
        ("player_season_xgbuildup_90", "Budowanie akcji (xGBuildup)"),
        ("player_season_key_passes_90", "Podania kluczowe"),
        ("player_season_xa_90", "Asysty oczekiwane (xA)"),
        ("player_season_passes_into_box_90", "Podania w pole karne"),
        ("player_season_op_passes_90", "Podania (wolumen)"),
        ("player_season_passing_ratio", "Celność podań"),
        ("player_season_forward_pass_proportion", "Podania do przodu"),
        ("player_season_deep_progressions_90", "Progresja piłki"),
        ("player_season_op_f3_passes_90", "Podania w tercji ataku"),
        ("player_season_dribbles_90", "Drybling"),
        ("player_season_dribble_ratio", "Skuteczność dryblingu"),
        ("player_season_carries_90", "Prowadzenia piłki"),
        ("player_season_padj_tackles_and_interceptions_90", "Odbiory i przechwyty"),
        ("player_season_pressures_90", "Pressing (liczba)"),
        ("player_season_ball_recoveries_90", "Odzyski piłki"),
        ("player_season_obv_90", "Wartość działań (OBV)"),
    ] + _PHYS_LABELED,
    "Atak": [
        ("player_season_np_xg_90", "Groźność pod bramką (xG)"),
        ("player_season_npg_90", "Gole (bez karnych)"),
        ("player_season_np_shots_90", "Strzały"),
        ("player_season_conversion_ratio", "Skuteczność wykończenia"),
        ("player_season_touches_inside_box_90", "Kontakty w polu karnym"),
        ("player_season_shot_touch_ratio", "Strzały na kontakt"),
        ("player_season_xa_90", "Asysty oczekiwane (xA)"),
        ("player_season_key_passes_90", "Podania kluczowe"),
        ("player_season_aerial_wins_90", "Pojedynki powietrzne"),
        ("player_season_aerial_ratio", "Skuteczność w powietrzu"),
        ("player_season_dribbles_90", "Drybling"),
        ("player_season_dribble_ratio", "Skuteczność dryblingu"),
        ("player_season_op_xgchain_90", "Udział w akcjach (xGChain)"),
        ("player_season_fouls_won_90", "Wymuszone faule"),
        ("player_season_carries_90", "Prowadzenia piłki"),
        ("player_season_obv_90", "Wartość działań (OBV)"),
    ] + _PHYS_LABELED,
}
 
 
def pos_style_labels(line):
    """Etykiety (po polsku) profilu pozycyjnego — do meta.style_labels."""
    return [lab for _, lab in POS_STYLE.get(line, [])]
 
 
def build_pos_style_stats(rows_of_line, line):
    """Średnia/odchylenie metryk POS_STYLE[line] w populacji TEJ linii (Ekstraklasa)."""
    stats = {}
    for m, _lab in POS_STYLE.get(line, []):
        vals = [v for v in (_val(r, m) for r in rows_of_line) if v is not None]
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        stats[m] = {"mean": mean, "std": math.sqrt(var) or 1.0}
    return stats
 
 
def pos_style_profile(row, line, stats):
    """Wektor z-score atrybutów dopasowanych do pozycji (kolejność = POS_STYLE[line])."""
    vec = []
    for m, _lab in POS_STYLE.get(line, []):
        v = _val(row, m)
        st = stats.get(m)
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
