#!/usr/bin/env python3
# =====================================================================
# physical.py — dołączanie danych fizycznych SkillCornera do wierszy
# zawodników StatsBomb (join po nazwisku, w obrębie tej samej ligi).
#
# Fizyka wchodzi WYŁĄCZNIE do profilu KOHERENCJI (styl gry) — patrz
# PHYS_STYLE_METRICS w coherence.py. NIE wchodzi do RC (poziomu), bo
# walidacja na ocenach trenerów pokazała, że pogarsza to zgodność.
#
# Źródło: scripts/skillcorner_physical_all.csv (kolumna 'league' = etykieta
# ligi identyczna jak w LEAGUE_CONFIG / data.json). Gdy pliku brak, moduł
# nic nie robi (pipeline działa dalej bez fizyki).
# =====================================================================
 
import re
import sys
import unicodedata
from pathlib import Path
from collections import defaultdict
 
HERE = Path(__file__).resolve().parent
CSV = HERE / "skillcorner_physical_all.csv"
 
# Kolumny fizyczne wstrzykiwane do wiersza zawodnika (nazwy natywne SkillCornera).
# To metryki STYLU ruchu (nie „jakości"): tempo, biegi wysokiej intensywności,
# sprinty, prędkość szczytowa, dynamika (przyspieszenia, zwroty).
PHYS_COLUMNS = [
    "total_metersperminute_full_all",
    "hsr_distance_full_all",
    "sprint_count_full_all",
    "hi_count_full_all",
    "psv99",
    "highaccel_count_full_all",
    "cod_count_full_all",
]
 
 
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
 
 
def _load_csv():
    if not CSV.exists():
        print(f"[fizyka] Brak {CSV.name} — koherencja policzona bez fizyki.",
              file=sys.stderr)
        return None
    try:
        import pandas as pd
    except ImportError:
        print("[fizyka] Brak pandas — pomijam fizykę.", file=sys.stderr)
        return None
    return pd.read_csv(CSV)
 
 
# cache indeksów per liga, żeby nie budować wielokrotnie
_INDEX_CACHE = {}
_DF = None
_LOADED = False
 
 
def _ensure_loaded():
    global _DF, _LOADED
    if not _LOADED:
        _DF = _load_csv()
        _LOADED = True
    return _DF
 
 
def _index_for_league(league_label):
    if league_label in _INDEX_CACHE:
        return _INDEX_CACHE[league_label]
    df = _ensure_loaded()
    idx = defaultdict(list)
    if df is not None and "league" in df.columns:
        import pandas as pd  # noqa
        sub = df[df["league"] == league_label]
        for _, r in sub.iterrows():
            phys = {c: (None if (c not in r or pd.isna(r[c])) else float(r[c]))
                    for c in PHYS_COLUMNS}
            for nm in (r.get("player_name"), r.get("player_short_name")):
                t = _toks(nm)
                if t:
                    idx[t[-1]].append((set(t), phys))
    _INDEX_CACHE[league_label] = idx
    return idx
 
 
def _match(name, idx):
    ts = set(_toks(name))
    if not ts:
        return None
    lk = _toks(name)[-1]
    for cand, phys in idx.get(lk, []):
        if lk in cand and (
            cand <= ts or ts <= cand or len(cand & ts) >= 2
            or any(len(a) == 1 and a in {x[0] for x in ts} for a in cand)
        ):
            return phys
    return None
 
 
def enrich_rows(rows, league_label):
    """Dokłada pola fizyczne (PHYS_COLUMNS) do wierszy danej ligi. In-place.
    Zwraca (dopasowane, wszystkie)."""
    idx = _index_for_league(league_label)
    if not idx:
        return (0, len(rows))
    matched = 0
    for row in rows:
        phys = _match(_row_name(row), idx)
        if phys is not None:
            row.update(phys)
            matched += 1
    return (matched, len(rows))
