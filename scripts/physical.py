#!/usr/bin/env python3
# =====================================================================
# physical.py — dołączanie danych SkillCornera (FIZYKA + GAME INTELLIGENCE)
# do wierszy zawodników StatsBomb (join po nazwisku, w obrębie ligi).
#
# Dane SkillCorner zasilają WYŁĄCZNIE profil KOHERENCJI (styl gry) — patrz
# PHYS_STYLE_METRICS / GI_STYLE_METRICS w coherence.py. NIE wchodzą do RC
# (poziomu): walidacja na ocenach trenerów pokazała, że to pogarsza zgodność.
#
# Źródła (kolumna 'league' = etykieta ligi jak w LEAGUE_CONFIG / data.json):
#   scripts/skillcorner_physical_all.csv               — fizyka
#   scripts/skillcorner_gi_off_ball_runs_all.csv       — GI: biegi bez piłki
#   scripts/skillcorner_gi_passes_all.csv              — GI: podania
#   scripts/skillcorner_gi_passing_options_all.csv     — GI: opcje podań
#   scripts/skillcorner_gi_possessions_all.csv         — GI: posiadanie
#   scripts/skillcorner_gi_on_ball_engagements_all.csv — GI: angażowanie
# Brak dowolnego pliku = pipeline działa dalej bez tej części danych.
# =====================================================================
 
import re
import sys
import unicodedata
from pathlib import Path
from collections import defaultdict
 
HERE = Path(__file__).resolve().parent
PHYS_CSV = HERE / "skillcorner_physical_all.csv"
 
# --- FIZYKA: metryki stylu ruchu (per mecz) ---
PHYS_COLUMNS = [
    "total_metersperminute_full_all",
    "hsr_distance_full_all",
    "sprint_count_full_all",
    "hi_count_full_all",
    "psv99",
    "highaccel_count_full_all",
    "cod_count_full_all",
]
 
# --- GAME INTELLIGENCE: wyselekcjonowane metryki stylu (per mecz) ---
# Po ~4 z każdej rodziny — najbardziej „stylotwórcze", bez rozmywania sygnału.
GI_FILES = {
    "off_ball_runs":       "skillcorner_gi_off_ball_runs_all.csv",
    "passes":              "skillcorner_gi_passes_all.csv",
    "passing_options":     "skillcorner_gi_passing_options_all.csv",
    "possessions":         "skillcorner_gi_possessions_all.csv",
    "on_ball_engagements": "skillcorner_gi_on_ball_engagements_all.csv",
}
GI_COLUMNS = [
    # biegi bez piłki (jak dużo/gdzie biega bez piłki)
    "offballrun_count", "offballrun_count_dangerous",
    "offballrun_count_penaltyarea", "offballrun_count_abovehsr",
    # podania (zasięg, przecinanie linii)
    "pass_count_completed", "pass_avgdistance",
    "pass_count_longrange_attempted", "pass_count_linebreak_completed",
    # oferowanie się do podania
    "optionoffered_count", "optionoffered_count_inspace",
    "optionoffered_count_penaltyarea", "optionoffered_count_dangerous",
    # posiadanie / prowadzenie / odporność na pressing
    "possession_count", "longcarry_count_forwardtrajectory",
    "possession_count_forwardmomentum", "possession_count_escapedpressure",
    # angażowanie / pressing / odbiory
    "onballengagement_count", "onballengagement_count_directregain",
    "onballengagement_count_pressingchain", "onballengagement_count_forwardtrajectory",
]
 
# wszystkie kolumny SkillCornera wstrzykiwane do wiersza zawodnika
ALL_COLUMNS = PHYS_COLUMNS + GI_COLUMNS
 
 
def _norm(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()
 
 
def _toks(s):
    return [t for t in _norm(s).split() if len(t) > 1]
 
 
def _row_name(row):
    for k in ("player_name", "player_known_name", "player_common_name"):
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""
 
 
# --- Wczytanie i scalenie źródeł SkillCornera w jedną szeroką tabelę ---
_WIDE = None
_LOADED = False
 
 
def _load_wide():
    """Scala fizykę + 5 rodzin GI po (league, player_id). Zwraca DataFrame albo None."""
    global _WIDE, _LOADED
    if _LOADED:
        return _WIDE
    _LOADED = True
    try:
        import pandas as pd
    except ImportError:
        print("[skillcorner] Brak pandas — pomijam dane SkillCorner.", file=sys.stderr)
        _WIDE = None
        return None
 
    frames = []
 
    def _take(path, cols):
        if not path.exists():
            print(f"[skillcorner] Brak {path.name} — pomijam.", file=sys.stderr)
            return None
        df = pd.read_csv(path)
        keys = [c for c in ("league", "player_id", "player_name", "player_short_name")
                if c in df.columns]
        use = keys + [c for c in cols if c in df.columns]
        return df[use].copy()
 
    base = _take(PHYS_CSV, PHYS_COLUMNS)
    if base is not None:
        frames.append(base)
    for fname in GI_FILES.values():
        g = _take(HERE / fname, GI_COLUMNS)
        if g is not None:
            frames.append(g)
 
    if not frames:
        _WIDE = None
        return None
 
    def _merge(a, b):
        m = a.merge(b, on=["league", "player_id"], how="outer", suffixes=("", "_r"))
        for col in ("player_name", "player_short_name"):
            r = col + "_r"
            if r in m.columns:
                m[col] = m[col].fillna(m[r])
                m.drop(columns=[r], inplace=True)
        return m
 
    from functools import reduce
    wide = reduce(_merge, frames)
    _WIDE = wide
    return wide
 
 
_INDEX_CACHE = {}
 
 
def _index_for_league(league_label):
    if league_label in _INDEX_CACHE:
        return _INDEX_CACHE[league_label]
    wide = _load_wide()
    idx = defaultdict(list)
    if wide is not None and "league" in wide.columns:
        import pandas as pd  # noqa
        sub = wide[wide["league"] == league_label]
        present = [c for c in ALL_COLUMNS if c in sub.columns]
        for _, r in sub.iterrows():
            feats = {}
            for c in present:
                v = r[c]
                feats[c] = None if pd.isna(v) else float(v)
            for nm in (r.get("player_name"), r.get("player_short_name")):
                t = _toks(nm)
                if t:
                    idx[t[-1]].append((set(t), feats))
    _INDEX_CACHE[league_label] = idx
    return idx
 
 
def _match(name, idx):
    ts = set(_toks(name))
    if not ts:
        return None
    lk = _toks(name)[-1]
    for cand, feats in idx.get(lk, []):
        if lk in cand and (
            cand <= ts or ts <= cand or len(cand & ts) >= 2
            or any(len(a) == 1 and a in {x[0] for x in ts} for a in cand)
        ):
            return feats
    return None
 
 
def enrich_rows(rows, league_label):
    """Dokłada pola SkillCornera (fizyka + GI) do wierszy danej ligi. In-place.
    Zwraca (dopasowane, wszystkie)."""
    idx = _index_for_league(league_label)
    if not idx:
        return (0, len(rows))
    matched = 0
    for row in rows:
        feats = _match(_row_name(row), idx)
        if feats is not None:
            row.update({k: v for k, v in feats.items() if v is not None})
            matched += 1
    return (matched, len(rows))
 
