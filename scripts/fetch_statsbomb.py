#!/usr/bin/env python3
# =====================================================================
# fetch_statsbomb.py — pobiera realne dane ze StatsBomb i zapisuje
# public/data.json w strukturze, którą czyta aplikacja.
#
# BEZPIECZEŃSTWO:
#   • Poświadczenia czytane WYŁĄCZNIE ze zmiennych środowiskowych.
#     Nigdy nie są w kodzie, nie są logowane, nie trafiają do repo.
#   • Ustaw przed uruchomieniem:
#         export SB_USERNAME="igor.rybinski@rakow.com"
#         export SB_PASSWORD="twoje-haslo"
#     (albo w pliku .env / w sekretach CI — patrz README)
#   • PRZYPOMNIENIE: hasło pojawiło się wcześniej w czacie jako tekst.
#     Zrotuj je w panelu StatsBomb przed realnym użyciem.
#
# URUCHOMIENIE:
#   pip install statsbombpy pandas
#   python scripts/fetch_statsbomb.py
#
# Skrypt NIE pyta o nic interaktywnie. Brak zmiennych = czytelny błąd i stop.
# =====================================================================
 
import os
import sys
import json
import math
from pathlib import Path
 
# Nowe moduły: handicapy, Transfermarkt, koherencja profili.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import handicap as hc
# transfermarkt: już nieużywany do wartości (zastąpiony plikiem player_values.csv).
# Import opcjonalny — brak modułu nie może wywalić skryptu.
try:
    import transfermarkt as tm  # noqa: F401
except Exception:
    tm = None
import coherence as coh
# physical: dołącza fizykę SkillCornera do profilu koherencji. Opcjonalny —
# brak modułu/pliku CSV nie może wywalić pipeline'u.
try:
    import physical as phys
except Exception:
    phys = None
 
OUT = Path(__file__).resolve().parent.parent / "public" / "data.json"
 
# --- ID rozgrywek / sezonów (z Twojej licencji StatsBomb, sezon 2025/2026) ---
# Ekstraklasa = baza handicapów. Reszta = pula odpowiedników.
# season_id 318 = sezon 2025/2026 (spójny między ligami jesień–wiosna).
# season_id 316 = sezon 2026 (ligi wiosna–jesień: Szwecja/Norwegia — gdyby były potrzebne).
# Zbiór lig dobrany pod poziom Rakowa; analityk może dodać/odjąć wpisy.
LEAGUE_CONFIG = [
    {"name": "Ekstraklasa (PL)",        "competition_id": 38,  "season_id": 318, "base": True},
    {"name": "Jupiler Pro League (BE)", "competition_id": 46,  "season_id": 318, "base": False},
    {"name": "Eredivisie (NL)",         "competition_id": 6,   "season_id": 318, "base": False},
    {"name": "Primeira Liga (PT)",      "competition_id": 13,  "season_id": 318, "base": False},
    {"name": "2. Bundesliga (DE)",      "competition_id": 10,  "season_id": 318, "base": False},
    {"name": "Superliga (DK)",          "competition_id": 77,  "season_id": 318, "base": False},
    {"name": "Czech Liga (CZ)",         "competition_id": 76,  "season_id": 318, "base": False},
    {"name": "Super League (CH)",       "competition_id": 80,  "season_id": 318, "base": False},
    # Rozszerzenie puli (budżet + poziom pod TOP3 Ekstraklasy) — sezon 2025/26.
    {"name": "1. HNL (HR)",             "competition_id": 78,  "season_id": 318, "base": False},
    {"name": "Super Liga (RS)",         "competition_id": 79,  "season_id": 318, "base": False},
    {"name": "Liga I (RO)",             "competition_id": 349, "season_id": 318, "base": False},
    {"name": "Super League (GR)",       "competition_id": 60,  "season_id": 318, "base": False},
    {"name": "1. SNL (SI)",             "competition_id": 1714, "season_id": 318, "base": False},
    # Norwegia gra wiosna–jesień (rok kalendarzowy): bieżący sezon 2026 = season_id 316.
    {"name": "Eliteserien (NO)",        "competition_id": 88,  "season_id": 316, "base": False},
    {"name": "Bundesliga (AT)",         "competition_id": 47,   "season_id": 318, "base": False},
    {"name": "Niké Liga (SK)",          "competition_id": 124,  "season_id": 318, "base": False},
    # Bułgaria — jest w StatsBombie, ale BRAK w SkillCornerze (koherencja bez fizyki).
    {"name": "First League (BG)",       "competition_id": 1865, "season_id": 318, "base": False},
    # (Turcja/Süper Lig — BRAK w licencji StatsBomb, więc nie da się dodać do modelu.)
    # (Węgry NB I — brak w licencji StatsBomb, więc pominięte mimo dostępności w SkillCorner.)
    {"name": "Jupiler / inne — dodaj wg potrzeb", "competition_id": None, "season_id": None, "base": False},
]
# Uwaga: ostatni wpis to placeholder-przykład; usuń go albo uzupełnij realnym ID.
LEAGUE_CONFIG = [lg for lg in LEAGUE_CONFIG if lg["competition_id"] is not None]
 
# Sezon HISTORYCZNY do fallbacku dla zawodników bez danych w bieżącym sezonie
# (nowy transfer / za mało minut). Schemat season_id jest spójny między ligami:
# 318 = 2025/2026, 317 = 2024/2025 (poprzedni), 281 = 2023/2024. Gdy zawodnik nie
# ma metryk w 318, próbujemy policzyć RC z 317 i OZNACZAMY to jako „historyczne".
# Wyłączalne: HIST_FALLBACK=0. Inny sezon: HIST_SEASON_ID / HIST_SEASON_LABEL.
HIST_SEASON_ID = int(os.getenv("HIST_SEASON_ID", "317"))
HIST_SEASON_LABEL = os.getenv("HIST_SEASON_LABEL", "2024/2025")
 
# Nazwa zespołu w danych StatsBomb (do wyfiltrowania składu Rakowa)
RAKOW_TEAM_NAME = "Raków Częstochowa"
 
# Minimalna liczba rozegranych minut, by zawodnik wszedł do analizy.
# Odsiewa małe próbki, które zawyżają metryki per-90 (np. poziom 94/96
# u zawodnika z jednym meczem). ~6 pełnych meczów.
MIN_MINUTES = 540
 
 
def die(msg: str, code: int = 1):
    print(f"[BŁĄD] {msg}", file=sys.stderr)
    sys.exit(code)
 
 
def get_credentials():
    """Czyta login/hasło ze zmiennych środowiskowych. Bez pytania."""
    user = os.getenv("SB_USERNAME")
    pw = os.getenv("SB_PASSWORD")
    if not user or not pw:
        die(
            "Brak poświadczeń. Ustaw zmienne środowiskowe SB_USERNAME i SB_PASSWORD "
            "przed uruchomieniem (nie wpisuj haseł do kodu). "
            "Przykład:\n"
            '    export SB_USERNAME="igor.rybinski@rakow.com"\n'
            '    export SB_PASSWORD="..."'
        )
    return {"user": user, "passwd": pw}
 
 
def load_statsbombpy():
    try:
        from statsbombpy import sb  # noqa
        return sb
    except ImportError:
        die("Brak biblioteki. Zainstaluj:  pip install statsbombpy pandas")
 
 
# =====================================================================
#  BLOK ANALITYKA — TU WCHODZI LOGIKA DZIEDZINOWA.
#  Poniższe funkcje to PROSTY placeholder. Analityk Rakowa podmienia je
#  na właściwy wzór: które metryki StatsBomb tworzą "poziom RC" na danej
#  pozycji i jak liczony jest handicap ligi per linia.
# =====================================================================
 
# Mapowanie pozycji StatsBomb -> uproszczona pozycja i linia w modelu.
# Pokrywa pełny zestaw etykiet StatsBomb (widziane w danych Ekstraklasy).
#
# UWAGA: nazwy poniżej to REALNE etykiety zwracane przez StatsBomb
# (potwierdzone na danych Ekstraklasy 25/26 — 23 unikalne wartości
# primary_position). StatsBomb używa brytyjskiej pisowni "Centre"
# (nie "Center") oraz końcówek "Midfielder"/"Forward". Wcześniejsza
# wersja słownika miała amerykańskie "Center" i "Midfield", przez co
# środek pola i napastnicy (AM/DM/ST) nie mapowali się i wypadali z puli.
# Dla odporności trzymamy OBIE pisownie.
POS_TO_LINE = {
    # --- Bramka ---
    "Goalkeeper": ("GK", "Bramka"),
 
    # --- Obrona środkowa ---
    "Centre Back": ("CB", "Obrona"),
    "Right Centre Back": ("CB", "Obrona"), "Left Centre Back": ("CB", "Obrona"),
    # (warianty amerykańskie — na wszelki wypadek)
    "Center Back": ("CB", "Obrona"),
    "Right Center Back": ("CB", "Obrona"), "Left Center Back": ("CB", "Obrona"),
 
    # --- Obrona boczna / wahadła ---
    "Right Back": ("WB", "Obrona"), "Left Back": ("WB", "Obrona"),
    "Right Wing Back": ("WB", "Obrona"), "Left Wing Back": ("WB", "Obrona"),
    "Wing Back": ("WB", "Obrona"),
 
    # --- Pomoc defensywna / centralna ---
    "Centre Defensive Midfielder": ("DM", "Pomoc"),
    "Right Defensive Midfielder": ("DM", "Pomoc"),
    "Left Defensive Midfielder": ("DM", "Pomoc"),
    "Centre Midfielder": ("CM", "Pomoc"),
    "Right Centre Midfielder": ("CM", "Pomoc"),
    "Left Centre Midfielder": ("CM", "Pomoc"),
    "Right Midfielder": ("WM", "Pomoc"), "Left Midfielder": ("WM", "Pomoc"),
    # (warianty amerykańskie / bez "-er")
    "Center Defensive Midfield": ("DM", "Pomoc"),
    "Right Defensive Midfield": ("DM", "Pomoc"), "Left Defensive Midfield": ("DM", "Pomoc"),
    "Center Midfield": ("CM", "Pomoc"), "Right Center Midfield": ("CM", "Pomoc"),
    "Left Center Midfield": ("CM", "Pomoc"),
    "Right Midfield": ("WM", "Pomoc"), "Left Midfield": ("WM", "Pomoc"),
 
    # --- Pomoc ofensywna / skrzydła ---
    "Centre Attacking Midfielder": ("AM", "Pomoc"),
    "Right Attacking Midfielder": ("AM", "Pomoc"),
    "Left Attacking Midfielder": ("AM", "Pomoc"),
    "Right Wing": ("W", "Pomoc"), "Left Wing": ("W", "Pomoc"),
    # (warianty)
    "Center Attacking Midfield": ("AM", "Pomoc"),
    "Right Attacking Midfield": ("AM", "Pomoc"), "Left Attacking Midfield": ("AM", "Pomoc"),
    "Right Winger": ("W", "Pomoc"), "Left Winger": ("W", "Pomoc"),
 
    # --- Atak ---
    "Centre Forward": ("ST", "Atak"),
    "Right Centre Forward": ("ST", "Atak"), "Left Centre Forward": ("ST", "Atak"),
    # (warianty)
    "Center Forward": ("ST", "Atak"),
    "Right Center Forward": ("ST", "Atak"), "Left Center Forward": ("ST", "Atak"),
    "Striker": ("ST", "Atak"),
    "Secondary Striker": ("ST", "Atak"), "Second Striker": ("ST", "Atak"),
}
 
 
def player_rc_from_stats(row) -> int:
    """
    PLACEHOLDER wzoru poziomu RC (0-100) dla zawodnika.
    Analityk: zastąp realnym złożeniem metryk (np. z aggregated_stats):
    ważona kombinacja per-90 dla podań progresywnych, xG/xA, odbiorów itd.,
    znormalizowana do skali 0-100 względem pozycji.
    """
    # Na razie neutralny placeholder, by pipeline działał end-to-end.
    return 72
 
 
def league_handicap(league_rows, base_rows) -> dict:
    """
    Handicap ligi per linia (% odchylenia vs Ekstraklasa).
    Używa PEŁNEJ metody z modułu handicap.py — nie placeholder.
    Analityk ustala tylko, które metryki reprezentują linie (LINE_METRICS
    w handicap.py). Sama matematyka jest gotowa i przetestowana.
    """
    return hc.compute_handicaps(base_rows, league_rows, POS_TO_LINE)
 
 
# =====================================================================
#  Pipeline pobierania. Struktura wyjścia = kontrakt data.json.
# =====================================================================
 
def _row_team_name(r):
    for k in ("team_name", "team", "team_name_x"):
        v = r.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""
 
 
def _is_rakow_row(r):
    return "rakow" in _norm_ascii(_row_team_name(r))
 
 
def _player_minutes(r):
    m = r.get("player_season_minutes")
    return m if isinstance(m, (int, float)) else 0
 
 
VALID_POS = {p for (p, _ln) in POS_TO_LINE.values()}
 
 
def _alt_positions(sb_row, manual_alt, primary_pos):
    """Pozycje alternatywne zawodnika (kody, bez podstawowej). Źródła łączone:
    (1) AUTO — druga pozycja ze StatsBomb (secondary_position), gdzie realnie grał;
    (2) MANUAL — lista alt_pos z squad.json (nadpisanie/uzupełnienie przez analityka).
    Zwraca listę kodów pozycji (np. ['ST']) w kolejności: auto, potem manual."""
    out = []
    if sb_row:
        sec = sb_row.get("secondary_position")
        if isinstance(sec, str) and sec.strip():
            m = POS_TO_LINE.get(sec.strip())
            if m and m[0] != primary_pos:
                out.append(m[0])
    if manual_alt:
        for code in manual_alt:
            if isinstance(code, str):
                c = code.strip().upper()
                if c in VALID_POS and c != primary_pos:
                    out.append(c)
    seen, res = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            res.append(c)
    return res
 
 
def _squad_entry(name, sb_row, pos, line, rc, est, universal_stats, pos_style_stats, manual_alt=None):
    return {
        "id": f"rk-{_slug(name)}", "name": name, "pos": pos, "line": line,
        "role": coh.role_of(pos, line),   # oś modelu (KPI Igora); line zostaje dla UI
        "alt_pos": _alt_positions(sb_row, manual_alt, pos),
        "rc": rc, "real": True, "rc_estimated": est,
        # wiek/wartość/kontrakt — zasilają moduły Priorytety i Czerwone flagi.
        # Wiek ze StatsBomb (jeśli jest); mv/contract/peak dokłada _enrich_squad.
        "age": _age(sb_row.get("birth_date")) if sb_row else None,
        "mv": 0.0, "contract": 0,
        "profile": coh.style_profile(sb_row, universal_stats) if sb_row else None,
        "profile_pos": coh.pos_style_profile(sb_row, line, pos_style_stats[line]) if sb_row else None,
        "_sb": sb_row,
        "_bd": (sb_row.get("birth_date") or "")[:10]
               if sb_row and isinstance(sb_row.get("birth_date"), str) else "",
    }
 
 
def build_squad_from_statsbomb(base_rows, base_stats_by_role, universal_stats, pos_style_stats):
    """SKŁAD RAKOWA — automatycznie ze StatsBomb: zawodnicy z minutami dla Rakowa
    w bieżącym sezonie Ekstraklasy. Odświeża się sam przy każdym pobraniu danych.
    RC z modelu, gdy próbka >= MIN_MINUTES; inaczej 'b.d.'.
 
    UCZCIWOŚĆ: to odzwierciedla „kto ZAGRAŁ", nie bieżącą kadrę z Transfermarktu —
    nowy transfer wejdzie dopiero, gdy rozegra minuty, a zawodnik, który odszedł,
    powisi póki ma rozegrane mecze w tym sezonie."""
    best = {}
    for r in base_rows:
        if not _is_rakow_row(r):
            continue
        nm = r.get("player_name")
        if not _is_valid_name(nm):
            continue
        key = _norm(nm)
        if key not in best or _player_minutes(r) > _player_minutes(best[key]):
            best[key] = r
    squad, rc_from_model = [], 0
    for r in best.values():
        mapped = POS_TO_LINE.get(r.get("primary_position") or r.get("position"))
        if not mapped:
            continue
        pos, line = mapped
        role = coh.role_of(pos, line)
        model_rc = (coh.quality_level(r, role, base_stats_by_role[role], minutes=_player_minutes(r))
                    if _player_minutes(r) >= MIN_MINUTES else None)
        if isinstance(model_rc, (int, float)):
            rc, est = model_rc, False
            rc_from_model += 1
        else:
            rc, est = 72, True   # za mała próbka / brak metryk -> "b.d." na froncie
        squad.append(_squad_entry(r.get("player_name"), r, pos, line, rc, est,
                                  universal_stats, pos_style_stats))
    return squad, rc_from_model
 
 
def build_squad_from_file(squad_path, base_by_name, base_stats_by_role, universal_stats, pos_style_stats):
    """Awaryjny skład z ręcznego public/squad.json (gdy auto ze StatsBomb zawiedzie)."""
    try:
        static_squad = json.loads(squad_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[BŁĄD] Nie wczytano {squad_path}: {e}", file=sys.stderr)
        static_squad = []
    # Indeks bazy po nazwisku — do dopasowania rozmytego, gdy nazwa w squad.json
    # (z Transfermarktu) różni się od zapisu StatsBomb. To odzyskuje RC np. dla
    # Racovițana, Napieraja, Emrelego zamiast pokazywać „b.d.".
    _seen, _rows = set(), []
    for r in base_by_name.values():
        pid = r.get("player_id")
        if pid in _seen:
            continue
        _seen.add(pid)
        _rows.append(r)
    base_sur = _surname_index([(r.get("player_name") or r.get("player_known_name") or "", r) for r in _rows])
 
    squad, rc_from_model = [], 0
    for pl in static_squad:
        name, pos, line = pl.get("name"), pl.get("pos"), pl.get("line")
        if not name or not pos or not line:
            print(f"[uwaga] Pomijam niekompletny wpis skladu: {pl}", file=sys.stderr)
            continue
        sb_row = base_by_name.get(_norm(name)) \
            or _match_by_tokens(name, base_sur, lambda r: r.get("player_id"))
        role = coh.role_of(pos, line)
        model_rc = (coh.quality_level(sb_row, role, base_stats_by_role[role],
                                      minutes=_player_minutes(sb_row)) if sb_row else None)
        if isinstance(model_rc, (int, float)):
            rc, est = model_rc, False
            rc_from_model += 1
        else:
            fb = pl.get("rc")
            rc, est = (fb if isinstance(fb, (int, float)) else 72), True
            # DIAGNOSTYKA „b.d." — mówi WPROST, czemu nie ma RC:
            if sb_row is None:
                tk = _tokens(name)
                near = base_sur.get(tk[-1], []) if tk else []
                if near:
                    alt = ", ".join(sorted({r.get("player_name", "?") for (_s, _f, r) in near})[:3])
                    reason = (f"NIE dopasowany, ale w StatsBomb są o tym nazwisku: {alt} "
                              f"→ sprawdź pisownię w squad.json")
                else:
                    reason = ("NIE ZNALEZIONY w StatsBomb (nikogo o tym nazwisku — nowy transfer / "
                              "nie zagrał w tym sezonie / dane jeszcze niewciągnięte)")
            else:
                reason = (f"znaleziony ({int(_player_minutes(sb_row))} min), "
                          f"ale BRAK metryk jakościowych dla linii {line}")
            print(f"[b.d.] {name}: {reason}", file=sys.stderr)
        entry = _squad_entry(name, sb_row, pos, line, rc, est, universal_stats, pos_style_stats,
                             manual_alt=pl.get("alt_pos"))
        if pl.get("id"):
            entry["id"] = pl["id"]
        squad.append(entry)
    return squad, rc_from_model
 
 
def _apply_historical_fallback(sb, creds, squad, base_stats_by_role,
                               universal_stats, pos_style_stats):
    """Dla zawodników składu bez danych w bieżącym sezonie (rc_estimated) szuka ich
    w SEZONIE POPRZEDNIM (HIST_SEASON_ID) we wszystkich skonfigurowanych ligach i —
    jeśli mają tam wystarczającą próbkę — liczy RC oraz profile z tych danych.
    Percentyl liczony WZGLĘDEM BIEŻĄCEJ ligi bazowej (base_stats_by_line), żeby RC
    było porównywalne z resztą składu. Wpis dostaje rc_source="historical" +
    rc_season, więc front pokaże, że to ocena na danych historycznych.
    Zwraca liczbę odzyskanych zawodników."""
    if os.getenv("HIST_FALLBACK", "1") not in ("1", "true", "True"):
        return 0
    todo = [e for e in squad if e.get("rc_estimated")]
    if not todo:
        return 0
    print(f"[hist] {len(todo)} zawodników bez danych bieżącego sezonu — "
          f"szukam w sezonie {HIST_SEASON_LABEL} (id {HIST_SEASON_ID})…")
    # Pobierz sezon historyczny dla wszystkich lig i zbierz wiersze do jednego indeksu.
    hist_rows = []
    for lg in LEAGUE_CONFIG:
        try:
            stats = sb.player_season_stats(
                competition_id=lg["competition_id"], season_id=HIST_SEASON_ID, creds=creds)
            hist_rows.extend(stats.to_dict("records"))
        except Exception as e:  # noqa: BLE001
            print(f"[hist] Nie pobrano {lg['name']} ({HIST_SEASON_LABEL}): {e}", file=sys.stderr)
    if not hist_rows:
        print("[hist] Brak danych historycznych — pomijam fallback.", file=sys.stderr)
        return 0
    hist_by_name = _name_index(hist_rows)
    hist_sur = _surname_index(
        [(r.get("player_name") or r.get("player_known_name") or "", r) for r in hist_rows])
    recovered = 0
    for e in todo:
        name, line = e["name"], e["line"]
        role = e.get("role") or coh.role_of(e.get("pos"), line)
        row = hist_by_name.get(_norm(name)) \
            or _match_by_tokens(name, hist_sur, lambda r: r.get("player_id"))
        if not row or _player_minutes(row) < MIN_MINUTES:
            continue
        rc = coh.quality_level(row, role, base_stats_by_role[role], minutes=_player_minutes(row))
        if not isinstance(rc, (int, float)):
            continue
        e["rc"] = rc
        e["rc_estimated"] = False
        e["rc_source"] = "historical"
        e["rc_season"] = HIST_SEASON_LABEL
        e["profile"] = coh.style_profile(row, universal_stats)
        e["profile_pos"] = coh.pos_style_profile(row, line, pos_style_stats[line])
        e["_sb"] = row              # staje się też referencją koherencji dla puli
        # dołóż pozycję alternatywną z danych historycznych (zachowaj manualne)
        e["alt_pos"] = _alt_positions(row, e.get("alt_pos"), e["pos"])
        recovered += 1
        print(f"[hist] {name}: RC {rc} z sezonu {HIST_SEASON_LABEL} "
              f"({int(_player_minutes(row))} min).")
    print(f"[hist] Odzyskano {recovered}/{len(todo)} zawodników z danych historycznych.")
    return recovered
 
 
# =====================================================================
#  OSTATNIE MECZE RAKOWA — walidator RC/koherencji na realnym boisku.
#  Pobiera ostatnie N meczów Ekstraklasy i per-zawodnik statystyki meczowe.
#  UCZCIWOŚĆ: mecz waliduje POZIOM (RC) i ujawnia preferencję trenera
#  (minuty = kto realnie gra), ale NIE waliduje koherencji wprost —
#  koherencja to podobieństwo stylu MIĘDZY zawodnikami, nie wielkość meczowa.
#  Front (analytics.js) zamienia te surowe agregaty na sygnały/rekomendacje.
#  DEFENSYWNIE: każdy błąd API jest łapany i NIE wywala pipeline'u —
#  w najgorszym razie recent.available=false i aplikacja działa jak dotąd.
# =====================================================================
 
# Kandydaci kolumn player_match_stats (statsbombpy). Bierzemy PIERWSZĄ istniejącą —
# nazwy bywają wersjonowane, więc nie zakładamy jednej. Klucz = nazwa u nas.
RECENT_STAT_COLS = {
    "minutes":       ["player_match_minutes"],
    "goals":         ["player_match_goals", "player_match_np_goals"],
    "np_xg":         ["player_match_np_xg"],
    "assists":       ["player_match_assists", "player_match_goal_assists"],
    "xa":            ["player_match_xa", "player_match_op_xa", "player_match_key_passes_xa"],
    "key_passes":    ["player_match_key_passes"],
    "np_shots":      ["player_match_np_shots", "player_match_shots"],
    "passes":        ["player_match_passes"],
    "tackles":       ["player_match_tackles"],
    "interceptions": ["player_match_interceptions"],
    "pressures":     ["player_match_pressures"],
}
 
 
def _first_col(row, candidates):
    """Pierwsza istniejąca, liczbowa i skończona wartość z listy kandydatów kolumn."""
    for c in candidates:
        v = row.get(c)
        if isinstance(v, (int, float)) and not (math.isnan(v) or math.isinf(v)):
            return float(v)
    return None
 
 
def _rakow_scoutastic_season():
    """Sezon Ekstraklasy w konwencji Scoutastic/TM (rok STARTU). Ekstraklasa startuje
    ~lipiec, więc miesiąc >= 7 → rok bieżący, inaczej rok poprzedni. Override: env."""
    forced = os.getenv("RECENT_SCOUTASTIC_SEASON")
    if forced:
        return forced
    try:
        import datetime as _d
        t = _d.date.today()
        return str(t.year if t.month >= 7 else t.year - 1)
    except Exception:  # noqa: BLE001
        return "2026"
 
 
def _fetch_recent_scoutastic(squad, n_matches=5):
    """Ostatnie N meczów Rakowa ze SCOUTASTIC (Transfermarkt) — źródło niezależne od
    dziurawego feedu meczowego StatsBomb. Mecz w /matches ma pełny skład
    (homeTeamPlayers/awayTeamPlayers: minutesPlayed, goals, assists, inLineup) i wynik.
    Zwraca obiekt data.json['recent'] w TYM SAMYM kształcie co ścieżka StatsBomb, żeby
    front był bez zmian. minutesPlayed = główny sygnał; xG/xA/tackles: brak (Scoutastic
    ich nie ma) → output pozostaje sygnałem miękkim. NIGDY nie rzuca."""
    token = os.getenv("SCOUTASTIC_TOKEN")
    if not token:
        return {"available": False, "reason": "no_scoutastic_token"}
    try:
        import scoutastic as sco
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": f"no_module: {e}"}
 
    comp = os.getenv("RECENT_SCOUTASTIC_COMP", "PL1")           # Ekstraklasa (potw. sondą)
    # Puchary do doliczenia (kody Transfermarkt: UCOL=Liga Konferencji, UCOQ=jej kwalif.).
    # Konfigurowalne przez RECENT_SCOUTASTIC_CUPS. Mecze pucharowe wpadną do „Ostatnich
    # meczów" i do statystyk zawodników automatycznie, gdy tylko źródło je wystawi.
    # Domyślnie puchary bierze StatsBomb (bogatsze dane + tegoroczne eliminacje), więc
    # tu domyślnie pusto. RECENT_SCOUTASTIC_CUPS="UCOL,UCOQ" włącza puchary też z Scoutastica.
    cup_codes = [c.strip() for c in os.getenv("RECENT_SCOUTASTIC_CUPS", "").split(",") if c.strip()]
    season = _rakow_scoutastic_season()                         # np. "2026" = 2026/27
    team_ext = str(os.getenv("RAKOW_SCOUTASTIC_TEAM", "9644"))  # Raków (externalId, potw.)
    try:
        client = sco.Client(token)
    except Exception as e:  # noqa: BLE001
        print(f"[mecze] Scoutastic klient błąd: {e}", file=sys.stderr)
        return {"available": False, "reason": f"scoutastic: {e}"}
    # Puchary ciągniemy z BIEŻĄCEGO i POPRZEDNIEGO sezonu — nowa edycja bywa jeszcze
    # niewciągnięta w źródle (np. UCOL/2026 puste), więc europejskie mecze i tak się
    # pokażą (kampania z poprzedniego sezonu), a tegoroczne dojdą, gdy tylko się pojawią.
    prev = str(int(season) - 1) if str(season).isdigit() else None
    # Liga + puchary w jednej puli meczów (liga = sygnał podstawowy; brak pucharu = OK).
    matches, comps_hit, _seen = [], [], set()
    plan = [(comp, season)] + [(c, s) for c in cup_codes for s in ([season, prev] if prev else [season])]
    for code, sea in plan:
        try:
            ms = client.league_matches(code, sea) or []
        except Exception as e:  # noqa: BLE001
            print(f"[mecze] Scoutastic {code}/{sea} błąd: {e}", file=sys.stderr)
            continue
        added = 0
        for m in ms:
            mid = m.get("internalId") or m.get("transfermarktId") or id(m)
            if mid in _seen:
                continue
            _seen.add(mid)
            m["_comp"] = code
            matches.append(m)
            added += 1
        if added:
            comps_hit.append(f"{code}/{sea}({added})")
    if not matches:
        print(f"[mecze] Scoutastic: brak danych meczowych ({comp}+{cup_codes}).", file=sys.stderr)
        return {"available": False, "reason": "no_matches"}
 
    def _sco_played(m):
        sh, sa = str(m.get("scoreHome")), str(m.get("scoreAway"))
        return sh.lstrip("-").isdigit() and sa.lstrip("-").isdigit() and sh != "-" and sa != "-"
 
    def _dk(m):
        return str(m.get("date") or "")
 
    rk = [m for m in matches
          if team_ext in (str(m.get("homeTeamId")), str(m.get("awayTeamId"))) and _sco_played(m)]
    if not rk:
        print(f"[mecze] Scoutastic: brak rozegranych meczów Rakowa w {comp}+{cup_codes}/{season}.", file=sys.stderr)
        return {"available": False, "reason": "no_played_matches"}
    n_cup_total = sum(1 for m in rk if m.get("_comp") != comp)
    if n_cup_total:
        print(f"[mecze] Scoutastic: w puli {n_cup_total} rozegranych meczów pucharowych Rakowa.", file=sys.stderr)
    rk.sort(key=_dk)
    recent = rk[-n_matches:]
 
    squad_by_norm = {_norm_ascii(s.get("name", "")): s for s in squad}
    matches_out, players_agg = [], {}
    team_gf = team_ga = team_pts = 0
    form = []
    for m in recent:
        rk_home = str(m.get("homeTeamId")) == team_ext
        opp = m.get("awayTeamName") if rk_home else m.get("homeTeamName")
        try:
            gf = int(m.get("scoreHome")) if rk_home else int(m.get("scoreAway"))
            ga = int(m.get("scoreAway")) if rk_home else int(m.get("scoreHome"))
            res = "W" if gf > ga else ("D" if gf == ga else "L")
            team_gf += gf; team_ga += ga
            team_pts += 3 if res == "W" else (1 if res == "D" else 0)
            form.append(res)
        except Exception:  # noqa: BLE001
            gf = ga = None; res = None
        _comp = m.get("_comp") or comp
        matches_out.append({
            "match_id": m.get("internalId") or m.get("transfermarktId"),
            "date": _dk(m)[:10], "opponent": opp, "home": rk_home,
            "gf": gf, "ga": ga, "result": res, "week": m.get("matchday"),
            "comp": _comp, "cup": _comp != comp,   # puchar vs liga (do etykiety na froncie)
            # id klubów (Transfermarkt) do herbów na froncie; przeciwnik + Raków.
            "opp_id": str(m.get("awayTeamId") if rk_home else m.get("homeTeamId") or ""),
            "rk_id": team_ext,
        })
        side = (m.get("homeTeamPlayers") if rk_home else m.get("awayTeamPlayers")) or []
        for p in side:
            nm = f"{p.get('firstName','')} {p.get('lastName','')}".strip()
            if not _is_valid_name(nm):
                continue
            key = _norm_ascii(nm)
            agg = players_agg.setdefault(key, {
                "name": nm, "minutes": 0.0, "matches_played": 0, "starts": 0,
                "goals": 0.0, "assists": 0.0})
            mins = p.get("minutesPlayed")
            mins = float(mins) if isinstance(mins, (int, float)) else 0.0
            if mins > 0:
                agg["matches_played"] += 1
                agg["minutes"] += mins
                if p.get("inLineup") or mins >= 60:
                    agg["starts"] += 1
            for k in ("goals", "assists"):
                v = p.get(k)
                if isinstance(v, (int, float)):
                    agg[k] += float(v)
 
    minutes_available = float(len(matches_out) * 90) or 90.0
    players_out = []
    for key, a in players_agg.items():
        s = squad_by_norm.get(key)
        players_out.append({
            "name": a["name"], "id": s.get("id") if s else None,
            "pos": s.get("pos") if s else None, "line": s.get("line") if s else None,
            "role": s.get("role") if s else None,
            "rc": s.get("rc") if s else None,
            "rc_estimated": s.get("rc_estimated") if s else None,
            "in_squad": s is not None,
            "minutes": round(a["minutes"], 1), "matches_played": a["matches_played"],
            "starts": a["starts"],
            "share": round(a["minutes"] / minutes_available, 3),
            "stats": {"goals": a["goals"], "assists": a["assists"]},
        })
    players_out.sort(key=lambda p: p["minutes"], reverse=True)
 
    newest = matches_out[-1]["date"] if matches_out else ""
    stale = False
    days_since = None
    try:
        import datetime as _d
        days_since = (_d.date.today() - _d.date.fromisoformat(newest)).days
        stale = days_since is not None and days_since > int(os.getenv("RECENT_STALE_DAYS", "45"))
    except Exception:  # noqa: BLE001
        pass
 
    n_joined = sum(1 for p in players_out if p["in_squad"])
    print(f"[mecze] Scoutastic: {len(matches_out)} rozegranych meczów Rakowa "
          f"({comp}/{season}), forma {''.join(form) or '—'}, bilans {team_gf}:{team_ga}, "
          f"{team_pts} pkt. Zawodników: {len(players_out)} (w składzie: {n_joined}).",
          file=sys.stderr)
    return {
        "available": bool(players_out) and bool(matches_out),
        "source": "scoutastic",
        "generated": __import__("datetime").date.today().isoformat(),
        "n_matches": len(matches_out), "matches": matches_out, "players": players_out,
        "team": {"gf": team_gf, "ga": team_ga, "points": team_pts,
                 "form": "".join(form), "minutes_available": minutes_available},
        "seasons_used": [{"season_id": season, "matches": len(matches_out), "provisional": False}],
        "newest_date": newest, "stale": stale, "days_since": days_since, "provisional": False,
        "note": ("Źródło: Scoutastic/Transfermarkt (minuty/gole/asysty). Mecz waliduje "
                 "minuty (preferencja trenera) i wynik; output miękko (bez xG/xA)."),
    }
 
 
def _statsbomb_cup_recent(sb, creds, squad):
    """Mecze PUCHAROWE Rakowa ze STATSBOMB (Liga Konferencji 353 + jej kwalifikacje 1896),
    2 najnowsze sezony. To źródło ma TEGOROCZNE eliminacje (Scoutastic wciąga nową edycję
    z opóźnieniem) + bogatsze dane (xG/xA/strzały). Zwraca (matches, players_dict) albo None.
    Nazwa drużyny dopasowywana ascii-owo (Raków != rakow przez akcent — patrz _norm_ascii)."""
    if os.getenv("RECENT_CUPS_SB", "1") in ("0", "false", "False"):
        return None
    cup_ids = [int(x) for x in os.getenv("RECENT_CUP_COMP_IDS", "353,1896").split(",") if x.strip().isdigit()]
    try:
        comps = sb.competitions(creds=creds).to_dict("records")
    except Exception as e:  # noqa: BLE001
        print(f"[mecze] StatsBomb puchary: brak listy rozgrywek: {e}", file=sys.stderr)
        return None
    rk_id = str(os.getenv("RAKOW_SCOUTASTIC_TEAM", "9644"))
    matches_out, players = [], {}
    for cid in cup_ids:
        rows = [c for c in comps if c.get("competition_id") == cid]
        if not rows:
            continue
        cname = str(rows[0].get("competition_name") or cid)
        short = ("LK-elim" if "qual" in cname.lower()
                 else "LK" if "conference" in cname.lower() else cname[:10])
        for r in sorted(rows, key=lambda x: x.get("season_id", 0), reverse=True)[:2]:
            sid = r.get("season_id")
            try:
                ms = sb.matches(competition_id=cid, season_id=sid, creds=creds).to_dict("records")
            except Exception as e:  # noqa: BLE001
                print(f"[mecze] StatsBomb {cname} {r.get('season_name')}: brak meczów ({e}).", file=sys.stderr)
                continue
            for m in ms:
                home = str(m.get("home_team") or ""); away = str(m.get("away_team") or "")
                rk_home = "rakow" in _norm_ascii(home)
                if not (rk_home or "rakow" in _norm_ascii(away)):
                    continue
                hs, as_ = m.get("home_score"), m.get("away_score")
                if not (isinstance(hs, (int, float)) and isinstance(as_, (int, float))):
                    continue  # nierozegrany
                gf, ga = (int(hs), int(as_)) if rk_home else (int(as_), int(hs))
                res = "W" if gf > ga else ("D" if gf == ga else "L")
                matches_out.append({
                    "match_id": m.get("match_id"), "date": str(m.get("match_date") or "")[:10],
                    "opponent": away if rk_home else home, "home": rk_home,
                    "gf": gf, "ga": ga, "result": res, "week": m.get("match_week"),
                    "comp": short, "cup": True, "opp_id": "", "rk_id": rk_id,
                })
                try:
                    pms = sb.player_match_stats(m.get("match_id"), creds=creds).to_dict("records")
                except Exception:  # noqa: BLE001
                    pms = []
                for pr in pms:
                    if "rakow" not in _norm_ascii(str(pr.get("team_name") or pr.get("team") or "")):
                        continue
                    pname = pr.get("player_name")
                    if not _is_valid_name(pname):
                        continue
                    key = _norm_ascii(pname)
                    a = players.setdefault(key, {"name": pname, "minutes": 0.0,
                                                 "matches_played": 0, "starts": 0, "goals": 0.0, "assists": 0.0})
                    mins = _first_col(pr, RECENT_STAT_COLS["minutes"]) or 0.0
                    if mins > 0:
                        a["matches_played"] += 1; a["minutes"] += mins
                        if mins >= 60:
                            a["starts"] += 1
                    a["goals"] += _first_col(pr, RECENT_STAT_COLS["goals"]) or 0.0
                    a["assists"] += _first_col(pr, RECENT_STAT_COLS["assists"]) or 0.0
    if not matches_out:
        print("[mecze] StatsBomb puchary: brak rozegranych meczów Rakowa w LK/kwalifikacjach.", file=sys.stderr)
        return None
    print(f"[mecze] StatsBomb puchary: {len(matches_out)} meczów Rakowa "
          f"({sorted({m['comp'] for m in matches_out})}).", file=sys.stderr)
    return matches_out, players


def _merge_cup_into_recent(base, cup, squad, cap=12):
    """Wmerguj mecze pucharowe (StatsBomb) w wynik recent (Scoutastic-liga). In-place."""
    if not cup:
        return base
    cup_matches, cup_players = cup
    squad_by_norm = {_norm_ascii(s.get("name", "")): s for s in squad}
    # 1) mecze: liga + puchary, dedupe po (data, przeciwnik), sort po dacie, cap
    seen, combined = set(), []
    for m in (base.get("matches", []) + cup_matches):
        k = (m.get("date"), _norm_ascii(str(m.get("opponent") or "")))
        if k in seen:
            continue
        seen.add(k); combined.append(m)
    combined.sort(key=lambda m: m.get("date") or "")
    combined = combined[-cap:]
    base["matches"] = combined
    base["n_matches"] = len(combined)
    # 2) bilans drużyny z wyświetlanych meczów
    gf = ga = pts = 0; form = []
    for m in combined:
        r = m.get("result")
        if r in ("W", "D", "L") and isinstance(m.get("gf"), int) and isinstance(m.get("ga"), int):
            gf += m["gf"]; ga += m["ga"]; pts += 3 if r == "W" else (1 if r == "D" else 0); form.append(r)
    mins_avail = float(len(combined) * 90) or 90.0
    base["team"] = {"gf": gf, "ga": ga, "points": pts, "form": "".join(form), "minutes_available": mins_avail}
    # 3) zawodnicy: dolicz puchar do istniejących / dopisz nowych
    pindex = {_norm_ascii(p.get("name", "")): p for p in base.get("players", [])}
    for key, cp in cup_players.items():
        tgt = pindex.get(key)
        if tgt is None:
            s = squad_by_norm.get(key)
            tgt = {"name": cp["name"], "id": s.get("id") if s else None,
                   "pos": s.get("pos") if s else None, "line": s.get("line") if s else None,
                   "role": s.get("role") if s else None, "rc": s.get("rc") if s else None,
                   "rc_estimated": s.get("rc_estimated") if s else None, "in_squad": s is not None,
                   "minutes": 0.0, "matches_played": 0, "starts": 0, "share": 0.0,
                   "stats": {"goals": 0.0, "assists": 0.0}}
            base.setdefault("players", []).append(tgt); pindex[key] = tgt
        tgt["minutes"] = round((tgt.get("minutes") or 0) + cp["minutes"], 1)
        tgt["matches_played"] = (tgt.get("matches_played") or 0) + cp["matches_played"]
        tgt["starts"] = (tgt.get("starts") or 0) + cp["starts"]
        st = tgt.setdefault("stats", {})
        st["goals"] = (st.get("goals") or 0) + cp["goals"]
        st["assists"] = (st.get("assists") or 0) + cp["assists"]
    for p in base.get("players", []):
        p["share"] = round((p.get("minutes") or 0) / mins_avail, 3)
    base["players"].sort(key=lambda p: p.get("minutes", 0), reverse=True)
    if combined:
        base["newest_date"] = combined[-1].get("date")
    base["available"] = bool(base.get("matches")) and bool(base.get("players"))
    base["note"] = (base.get("note", "") + " Doliczono mecze pucharowe (Liga Konferencji + eliminacje, StatsBomb).").strip()
    return base


def _fetch_recent_matches(sb, creds, squad, n_matches=5):
    """Dyspozytor źródła meczowego walidatora. RECENT_SOURCE: 'scoutastic' (domyślnie —
    Transfermarkt, realne wyniki bieżącego sezonu) albo 'statsbomb' (stary feed, bywa
    dziurawy). Puchary (Liga Konferencji + eliminacje) dokłada StatsBomb. Wyłączalne: RECENT_MATCHES=0."""
    if os.getenv("RECENT_MATCHES", "1") in ("0", "false", "False"):
        print("[mecze] Ostatnie mecze: WYŁĄCZONE (RECENT_MATCHES=0).", file=sys.stderr)
        return {"available": False, "reason": "disabled"}
    # Puchary Rakowa ze StatsBomb (Liga Konferencji + eliminacje — także tegoroczne).
    cup = None
    try:
        cup = _statsbomb_cup_recent(sb, creds, squad)
    except Exception as e:  # noqa: BLE001
        print(f"[mecze] StatsBomb puchary: pominięto ({type(e).__name__}: {e}).", file=sys.stderr)

    source = os.getenv("RECENT_SOURCE", "scoutastic").lower()
    if source == "scoutastic":
        out = _fetch_recent_scoutastic(squad, n_matches=n_matches)
        if out.get("available"):
            return _merge_cup_into_recent(out, cup, squad) if cup else out
        print(f"[mecze] Scoutastic niedostępne ({out.get('reason')}) — "
              f"fallback do StatsBomb.", file=sys.stderr)
    sb_out = _fetch_recent_statsbomb(sb, creds, squad, n_matches=n_matches)
    if cup and sb_out.get("available"):
        return _merge_cup_into_recent(sb_out, cup, squad)
    if cup and not sb_out.get("available"):
        # sama liga niedostępna, ale puchar jest — złóż wynik z pucharu
        base = {"available": True, "source": "statsbomb-cup",
                "generated": __import__("datetime").date.today().isoformat(),
                "matches": [], "players": [], "team": {}, "note": ""}
        return _merge_cup_into_recent(base, cup, squad)
    return sb_out
 
 
def _fetch_recent_statsbomb(sb, creds, squad, n_matches=5):
    """Ostatnie N meczów Rakowa ze STATSBOMB (feed bywa dziurawy — patrz strażnik
    wstępności). Zachowane jako fallback. Liczba meczów: RECENT_MATCHES_N."""
    try:
        n_matches = int(os.getenv("RECENT_MATCHES_N", str(n_matches)))
    except ValueError:
        n_matches = 5
 
    # Bazowa liga = Ekstraklasa (competition z konfiguracji base).
    base_cfg = next((lg for lg in LEAGUE_CONFIG if lg.get("base")), None)
    if not base_cfg:
        return {"available": False, "reason": "no_base_league"}
    comp_id = base_cfg["competition_id"]
 
    def _team(row, side):
        for k in (f"{side}_team", f"{side}_team_name"):
            v = row.get(k)
            if isinstance(v, str) and v.strip():
                return v
        return ""
 
    def _is_rakow(name):
        return "rakow" in _norm_ascii(name)
 
    def _date_key(m):
        d = m.get("match_date") or m.get("match_date_time") or ""
        return str(d)
 
    # --- 1. WYBÓR SEZONÓW ---
    # KLUCZOWE (fix): NIE bierzemy na sztywno sezonu bazowego modelu (318 = 2025/26),
    # bo jego ostatnie mecze to koniec sezonu (maj) — a „ostatni tydzień" to już nowy
    # sezon z INNYM season_id. Odpytujemy sb.competitions(), sortujemy sezony
    # Ekstraklasy od najnowszego i skanujemy kilka najnowszych, żeby złapać realnie
    # najświeższe spotkania. Override: RECENT_SEASON_ID wymusza konkretny sezon.
    forced = os.getenv("RECENT_SEASON_ID")
    if forced:
        try:
            season_ids = [int(forced)]
        except ValueError:
            season_ids = [base_cfg["season_id"]]
    else:
        season_ids = []
        try:
            comps = sb.competitions(creds=creds).to_dict("records")
            import re as _re
            seas = [c for c in comps if c.get("competition_id") == comp_id]
 
            def _seas_recency(c):
                nm = str(c.get("season_name") or "")
                yrs = _re.findall(r"\d{4}", nm)
                yr = int(yrs[-1]) if yrs else 0
                return (yr, c.get("season_id") or 0)
 
            seas.sort(key=_seas_recency, reverse=True)
            if os.getenv("RECENT_DEBUG") not in (None, "0", "false", "False"):
                print("[mecze:debug] Sezony Ekstraklasy (od najnowszego): "
                      + "; ".join(f"{c.get('season_id')}={c.get('season_name')}" for c in seas),
                      file=sys.stderr)
            for c in seas:
                sid = c.get("season_id")
                if sid is not None and sid not in season_ids:
                    season_ids.append(sid)
        except Exception as e:  # noqa: BLE001
            print(f"[mecze] Nie pobrano listy sezonów (competitions): {e} — "
                  f"używam sezonu bazowego.", file=sys.stderr)
        # Zawsze dołóż sezon bazowy jako bezpieczny fallback; przytnij do 3 najnowszych.
        if base_cfg["season_id"] not in season_ids:
            season_ids.append(base_cfg["season_id"])
        season_ids = season_ids[:3]
 
    debug = os.getenv("RECENT_DEBUG") not in (None, "0", "false", "False")
 
    import datetime as _dtx
    try:
        _today = _dtx.date.today()
    except Exception:  # noqa: BLE001
        _today = None
 
    def _played(m):
        """Mecz REALNIE rozegrany: status available + wynik obecny + data nie z przyszłości.
        Chroni przed wstępnymi/terminarzowymi wpisami (mecz, którego jeszcze nie było)."""
        status = str(m.get("match_status") or m.get("match_status_360") or "available").lower()
        if "available" not in status and status not in ("", "nan"):
            return False
        hs, as_ = m.get("home_score"), m.get("away_score")
        if not (isinstance(hs, (int, float)) and isinstance(as_, (int, float))):
            return False
        if _today is not None:
            try:
                if _dtx.date.fromisoformat(_date_key(m)[:10]) > _today:
                    return False  # mecz w przyszłości = terminarz, nie wynik
            except Exception:  # noqa: BLE001
                pass
        return True
 
    # --- 2. ZBIERZ MECZE RAKOWA per sezon + WYKRYJ FEED WSTĘPNY/BŁĘDNY ---
    # Sygnał brudnego feedu: dwa mecze Rakowa tego samego dnia (drużyna nie gra 2× dziennie)
    # albo mecze z przyszłości oznaczone jako rozegrane. Taki sezon oznaczamy jako
    # 'provisional' i wolimy od niego sezon czysty; brudny bierzemy tylko, gdy nie ma innego.
    per_season = []
    for sid in season_ids:
        try:
            match_rows = sb.matches(competition_id=comp_id, season_id=sid, creds=creds).to_dict("records")
        except Exception as e:  # noqa: BLE001
            print(f"[mecze] Nie pobrano meczów sezonu {sid}: {e}", file=sys.stderr)
            continue
        ms, seen_mid = [], set()
        for m in match_rows:
            home, away = _team(m, "home"), _team(m, "away")
            if not (_is_rakow(home) or _is_rakow(away)):
                continue
            if not _played(m):
                continue
            # DEDUP po match_id: feed potrafi zwracać ten sam mecz wielokrotnie (to właśnie
            # dawało "duplikaty dat" w zakończonych sezonach i zawyżało liczbę meczów/zawodników).
            mid = m.get("match_id")
            if mid is not None:
                if mid in seen_mid:
                    continue
                seen_mid.add(mid)
            m["__season_id"] = sid
            ms.append(m)
        if not ms:
            continue
        # Sygnał WSTĘPNOŚCI liczony na meczach UNIKALNYCH (po dedupie): dwa RÓŻNE mecze
        # Rakowa w tej samej dacie = niemożliwe w realnym terminarzu → feed zmyślony/wstępny.
        dates = [_date_key(m)[:10] for m in ms if _date_key(m)[:10]]
        dup = len(dates) != len(set(dates))
        per_season.append({"sid": sid, "matches": ms, "n": len(ms), "provisional": dup})
        if debug:
            print(f"[mecze:debug] sezon {sid}: {len(ms)} meczów Rakowa, duplikaty dat: {dup}", file=sys.stderr)
            for m in sorted(ms, key=_date_key)[-8:]:
                print(f"[mecze:debug]   {_date_key(m)[:10]} | {_team(m,'home')} {m.get('home_score')}"
                      f":{m.get('away_score')} {_team(m,'away')} | status={m.get('match_status')}",
                      file=sys.stderr)
        if dup:
            print(f"[mecze] UWAGA: sezon {sid} ma mecze Rakowa w tej samej dacie — "
                  f"feed wygląda na wstępny/błędny; wolę sezon czysty.", file=sys.stderr)
 
    if not per_season:
        print("[mecze] Brak rozegranych meczów Rakowa w pobranych sezonach.", file=sys.stderr)
        return {"available": False, "reason": "no_rakow_matches"}
 
    # Preferuj sezony czyste (bez sygnału wstępności). Brudne tylko w ostateczności.
    clean = [s for s in per_season if not s["provisional"]]
    chosen = clean if clean else per_season
    provisional_used = not clean
    rk = [m for s in chosen for m in s["matches"]]
    seasons_hit = [{"season_id": s["sid"], "matches": s["n"], "provisional": s["provisional"]} for s in chosen]
 
    rk.sort(key=_date_key)
 
    # --- OKNO ŚWIEŻOŚCI: nie mieszaj końcówki starego sezonu (maj) z nowym (sierpień) ---
    # Bierzemy tylko mecze w oknie RECENT_WINDOW_DAYS (domyślnie 60) od najświeższego
    # rozegranego meczu, POTEM ostatnie N. Dzięki temu, gdy nowy sezon ma dopiero 2
    # kolejki, pokazujemy właśnie te 2 (a nie doklejamy 3 sprzed transferów z maja);
    # w trakcie sezonu (mecze co tydzień) okno spokojnie mieści 5–6 spotkań.
    try:
        import datetime as _dt2
        _newest = _dt2.date.fromisoformat(_date_key(rk[-1])[:10])
        _win = int(os.getenv("RECENT_WINDOW_DAYS", "60"))
 
        def _within(m):
            try:
                return (_newest - _dt2.date.fromisoformat(_date_key(m)[:10])).days <= _win
            except Exception:  # noqa: BLE001
                return True
        windowed = [m for m in rk if _within(m)]
    except Exception:  # noqa: BLE001
        windowed = rk
    recent = windowed[-n_matches:]
 
    # --- STALENESS: ostrzeżenie, gdy najświeższy mecz jest wyraźnie stary ---
    # (np. StatsBomb nie zebrał jeszcze nowego sezonu → pokazujemy końcówkę poprzedniego).
    newest_date = _date_key(recent[-1])[:10]
    stale = False
    days_since = None
    try:
        import datetime as _dt
        d = _dt.date.fromisoformat(newest_date)
        days_since = (_dt.date.today() - d).days
        stale = days_since is not None and days_since > int(os.getenv("RECENT_STALE_DAYS", "45"))
    except Exception:  # noqa: BLE001
        pass
    if stale:
        print(f"[mecze] UWAGA: najświeższy zebrany mecz to {newest_date} "
              f"({days_since} dni temu) — prawdopodobnie brak danych nowego sezonu. "
              f"Pokazuję końcówkę dostępnego sezonu.", file=sys.stderr)
 
    # Indeks składu po znormalizowanej nazwie — do złączenia z RC na froncie.
    squad_by_norm = {}
    for s in squad:
        squad_by_norm[_norm_ascii(s.get("name", ""))] = s
 
    matches_out, players_agg, cols_seen = [], {}, None
    team_gf = team_ga = team_pts = 0
    form = []
 
    for m in recent:
        mid = m.get("match_id")
        home, away = _team(m, "home"), _team(m, "away")
        rk_home = _is_rakow(home)
        opp = away if rk_home else home
        hs = m.get("home_score"); as_ = m.get("away_score")
        gf = ga = None
        if isinstance(hs, (int, float)) and isinstance(as_, (int, float)):
            gf, ga = (int(hs), int(as_)) if rk_home else (int(as_), int(hs))
            res = "W" if gf > ga else ("D" if gf == ga else "L")
            team_gf += gf; team_ga += ga
            team_pts += 3 if res == "W" else (1 if res == "D" else 0)
            form.append(res)
        else:
            res = None
        matches_out.append({
            "match_id": mid, "date": _date_key(m)[:10], "opponent": opp,
            "home": rk_home, "gf": gf, "ga": ga, "result": res,
            "week": m.get("match_week"), "season_id": m.get("__season_id"),
        })
 
        # --- Per-zawodnik statystyki meczowe (defensywnie) ---
        try:
            pms = sb.player_match_stats(mid, creds=creds).to_dict("records")
        except Exception as e:  # noqa: BLE001
            print(f"[mecze] player_match_stats({mid}) niedostępne: {e}", file=sys.stderr)
            continue
        for pr in pms:
            tname = pr.get("team_name") or pr.get("team") or ""
            if not _is_rakow(tname):
                continue
            pname = pr.get("player_name")
            if not _is_valid_name(pname):
                continue
            if cols_seen is None:
                cols_seen = {k: next((c for c in cands if c in pr), None)
                             for k, cands in RECENT_STAT_COLS.items()}
            key = _norm_ascii(pname)
            agg = players_agg.setdefault(key, {
                "name": pname, "minutes": 0.0, "matches_played": 0, "starts": 0,
                "stats": {k: 0.0 for k in RECENT_STAT_COLS if k != "minutes"},
            })
            mins = _first_col(pr, RECENT_STAT_COLS["minutes"]) or 0.0
            if mins > 0:
                agg["matches_played"] += 1
                agg["minutes"] += mins
                if mins >= 60:
                    agg["starts"] += 1
            for k, cands in RECENT_STAT_COLS.items():
                if k == "minutes":
                    continue
                v = _first_col(pr, cands)
                if v is not None:
                    agg["stats"][k] += v
 
    # Domknij złączenie ze składem (RC, pozycja) — front i tak dokłada z squad,
    # ale zapisujemy id/pos/rc dla wygody i żeby ekran działał bez re-joinu.
    players_out = []
    # Podstawa udziału minut = FAKTYCZNA liczba pokazanych meczów (nie żądane N),
    # inaczej share byłby zaniżony, gdy nowy sezon ma mniej meczów niż N.
    minutes_available = float(len(matches_out) * 90) or 90.0
    for key, a in players_agg.items():
        s = squad_by_norm.get(key)
        players_out.append({
            "name": a["name"],
            "id": s.get("id") if s else None,
            "pos": s.get("pos") if s else None,
            "line": s.get("line") if s else None,
            "role": s.get("role") if s else None,
            "rc": s.get("rc") if s else None,
            "rc_estimated": s.get("rc_estimated") if s else None,
            "in_squad": s is not None,
            "minutes": round(a["minutes"], 1),
            "matches_played": a["matches_played"],
            "starts": a["starts"],
            "share": round(a["minutes"] / minutes_available, 3) if minutes_available else 0.0,
            "stats": {k: round(v, 3) for k, v in a["stats"].items()},
        })
    players_out.sort(key=lambda p: p["minutes"], reverse=True)
 
    n_joined = sum(1 for p in players_out if p["in_squad"])
    have_stats = any(p["minutes"] > 0 for p in players_out)
    print(f"[mecze] Ostatnie {len(matches_out)} meczów Rakowa: forma {''.join(form) or '—'}, "
          f"bilans {team_gf}:{team_ga}, {team_pts} pkt. "
          f"Zawodników ze statystykami: {len(players_out)} (w składzie: {n_joined}).",
          file=sys.stderr)
    if cols_seen:
        missing = [k for k, c in cols_seen.items() if c is None]
        if missing:
            print(f"[mecze] Uwaga: brak kolumn dla metryk: {missing}.", file=sys.stderr)
 
    if seasons_hit:
        print(f"[mecze] Sezony użyte (najnowsze pierwsze): "
              f"{[s['season_id'] for s in seasons_hit]}; najświeższy mecz {newest_date}.",
              file=sys.stderr)
    if provisional_used:
        print("[mecze] UWAGA: nie znaleziono czystego sezonu — dane oznaczone jako WSTĘPNE. "
              "Walidacja na froncie zostanie wstrzymana. Rozważ RECENT_SEASON_ID=<id> "
              "(RECENT_DEBUG=1 wypisze listę sezonów).", file=sys.stderr)
 
    return {
        "available": have_stats and bool(matches_out),
        "generated": __import__("datetime").date.today().isoformat(),
        "n_matches": len(matches_out),
        "matches": matches_out,
        "players": players_out,
        "team": {
            "gf": team_gf, "ga": team_ga, "points": team_pts,
            "form": "".join(form), "minutes_available": minutes_available,
        },
        # Świeżość danych: z jakich sezonów zebrano i czy najświeższy mecz nie jest stary.
        "seasons_used": seasons_hit,
        "newest_date": newest_date,
        "stale": stale,
        "days_since": days_since,
        # Feed wstępny/błędny (nie znaleziono czystego sezonu) — front ostrzega mocno.
        "provisional": provisional_used,
        "note": ("Mecz waliduje POZIOM (RC) i ujawnia preferencję trenera (minuty). "
                 "Koherencji nie waliduje wprost — to podobieństwo stylu między "
                 "zawodnikami, nie wielkość meczowa."),
    }
 
 
# =====================================================================
#  STABILNOŚĆ METRYK (ICC / test-retest) — odpowiedź na p.7 audytu Igora.
#  Mierzymy POWTARZALNOŚĆ każdej metryki wejściowej między sezonami: dla
#  zawodników Ekstraklasy z ≥MIN_MINUTES w OBU sezonach (bieżący 318 i
#  historyczny 317) liczymy korelację rang (Spearman) tej samej metryki.
#  Wysoka = metryka stabilna (sygnał, np. xG/strzały). Niska = kontekstowa/
#  szumna (np. przechwyty) — kandydat do obniżenia wagi lub usunięcia z modelu.
#  UCZCIWOŚĆ: to test-retest MIĘDZY sezonami — miesza prawdziwą niestabilność
#  metryki z realną zmianą zawodnika (forma, rola, drużyna, wiek). Ściślejszy
#  split-half w obrębie sezonu (po meczach) to naturalny upgrade — wymaga danych
#  meczowych całej populacji. DEFENSYWNIE: błąd/brak danych → available:false,
#  reszta pipeline'u działa bez zmian. Wyłączalne: STABILITY=0.
# =====================================================================
 
# Czytelne etykiety PL dla metryk (native StatsBomb) — front renderuje je wprost.
STAB_METRIC_LABELS = {
    "player_season_gsaa_90": "Bramki uratowane (GSAA)",
    "player_season_save_ratio": "Skuteczność obron",
    "player_season_positive_outcome_90": "Pozytywne interwencje",
    "player_season_obv_gk_90": "OBV bramkarza",
    "player_season_op_passes_90": "Podania z gry",
    "player_season_passing_ratio": "Celność podań",
    "player_season_long_balls_90": "Długie podania",
    "player_season_long_ball_ratio": "Celność długich podań",
    "player_season_pass_length": "Średnia długość podania",
    "player_season_padj_tackles_and_interceptions_90": "Odbiory+przechwyty (padj)",
    "player_season_aerial_wins_90": "Wygrane pojedynki powietrzne",
    "player_season_aerial_ratio": "Skuteczność w powietrzu",
    "player_season_clearance_90": "Wybicia",
    "player_season_padj_clearances_90": "Wybicia (padj)",
    "player_season_padj_pressures_90": "Pressing (padj)",
    "player_season_challenge_ratio": "Skuteczność pojedynków",
    "player_season_op_f3_passes_90": "Podania w tercji ataku",
    "player_season_op_xgchain_90": "xGChain (gra otwarta)",
    "player_season_op_xgchain_per_possession": "xGChain / posiadanie",
    "player_season_xgbuildup_90": "xGBuildup",
    "player_season_xgbuildup_per_possession": "xGBuildup / posiadanie",
    "player_season_op_xgbuildup_per_possession": "xGBuildup gry otwartej / pos.",
    "player_season_key_passes_90": "Podania kluczowe",
    "player_season_xa_90": "Oczekiwane asysty (xA)",
    "player_season_passes_into_box_90": "Podania w pole karne",
    "player_season_forward_pass_proportion": "Udział podań do przodu",
    "player_season_dribbles_90": "Drybling",
    "player_season_np_xg_90": "xG (bez karnych)",
    "player_season_npg_90": "Gole (bez karnych)",
    "player_season_np_shots_90": "Strzały (bez karnych)",
    "player_season_touches_inside_box_90": "Kontakty w polu karnym",
    "player_season_conversion_ratio": "Skuteczność (gole/strzały)",
}
 
 
def _stability_metric_lines():
    """Mapowanie: metryka (native, bez sufiksu __tpadj) → linie modelu, które jej
    używają. Bierzemy z aktywnych QUALITY_METRICS + profilu koherencji (LINE_METRICS)."""
    lines = {}
    for d in (coh.QUALITY_METRICS, coh.LINE_METRICS):
        for ln, arr in d.items():
            for m in arr:
                base = m.replace(coh.TEAM_NORM_SUFFIX, "")
                lines.setdefault(base, set()).add(ln)
    return {k: sorted(v) for k, v in lines.items()}
 
 
def _spearman(pairs):
    """Korelacja rang Spearmana dla listy par (x,y). Odporna na skalę i outliery
    (rangujemy, potem Pearson na rangach). Zwraca (rho, n) albo (None, n)."""
    n = len(pairs)
    if n < 8:
        return None, n
 
    def _ranks(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        rk = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0  # średnia ranga dla remisów
            for k in range(i, j + 1):
                rk[order[k]] = avg
            i = j + 1
        return rk
 
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    rx, ry = _ranks(xs), _ranks(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    sx = sy = cov = 0.0
    for a, b in zip(rx, ry):
        dx, dy = a - mx, b - my
        sx += dx * dx
        sy += dy * dy
        cov += dx * dy
    if sx <= 0 or sy <= 0:
        return None, n
    return cov / math.sqrt(sx * sy), n
 
 
def _metric_stability(sb, creds, base_current_rows):
    """Test-retest metryk między sezonem bieżącym a historycznym (Ekstraklasa).
    Zwraca obiekt do data.json['stability'] albo {'available': False,...}."""
    if os.getenv("STABILITY", "1") in ("0", "false", "False"):
        print("[stabilność] Analiza stabilności metryk: WYŁĄCZONA (STABILITY=0).", file=sys.stderr)
        return {"available": False, "reason": "disabled"}
    base_cfg = next((lg for lg in LEAGUE_CONFIG if lg.get("base")), None)
    if not base_cfg:
        return {"available": False, "reason": "no_base_league"}
 
    # Pełna populacja Ekstraklasy w sezonie historycznym (jedno zapytanie).
    try:
        prev_rows = sb.player_season_stats(
            competition_id=base_cfg["competition_id"], season_id=HIST_SEASON_ID, creds=creds
        ).to_dict("records")
    except Exception as e:  # noqa: BLE001
        print(f"[stabilność] Nie pobrano sezonu {HIST_SEASON_LABEL}: {e}", file=sys.stderr)
        return {"available": False, "reason": f"hist_season: {e}"}
 
    def _idx(rows):
        out = {}
        for r in rows:
            pid = r.get("player_id")
            if pid is None:
                continue
            if _player_minutes(r) >= MIN_MINUTES:
                out[pid] = r
        return out
 
    cur = _idx(base_current_rows)
    prv = _idx(prev_rows)
    common = [pid for pid in cur if pid in prv]
    if len(common) < 12:
        print(f"[stabilność] Za mała wspólna próba ({len(common)} zawodników w obu sezonach).", file=sys.stderr)
        return {"available": False, "reason": f"small_overlap:{len(common)}"}
 
    lines_of = _stability_metric_lines()
    metrics_out = []
    for key in sorted(lines_of):
        pairs = []
        for pid in common:
            a = cur[pid].get(key)
            b = prv[pid].get(key)
            if (isinstance(a, (int, float)) and isinstance(b, (int, float))
                    and not (math.isnan(a) or math.isinf(a) or math.isnan(b) or math.isinf(b))):
                pairs.append((float(a), float(b)))
        rho, n = _spearman(pairs)
        if rho is None:
            continue
        tier = "stable" if rho >= 0.6 else ("moderate" if rho >= 0.4 else "noisy")
        metrics_out.append({
            "key": key,
            "label": STAB_METRIC_LABELS.get(key, key.replace("player_season_", "").replace("_", " ")),
            "rho": round(rho, 3), "n": n, "tier": tier, "lines": lines_of[key],
        })
    metrics_out.sort(key=lambda m: m["rho"], reverse=True)
 
    summary = {
        "stable": sum(1 for m in metrics_out if m["tier"] == "stable"),
        "moderate": sum(1 for m in metrics_out if m["tier"] == "moderate"),
        "noisy": sum(1 for m in metrics_out if m["tier"] == "noisy"),
    }
    print(f"[stabilność] Test-retest {len(metrics_out)} metryk na {len(common)} zawodnikach "
          f"(≥{MIN_MINUTES} min w obu sezonach): stabilne {summary['stable']}, "
          f"umiarkowane {summary['moderate']}, szumne {summary['noisy']}.", file=sys.stderr)
    return {
        "available": bool(metrics_out),
        "generated": __import__("datetime").date.today().isoformat(),
        "min_minutes": MIN_MINUTES,
        "n_players": len(common),
        "seasons": {"current": base_cfg["season_id"], "previous": HIST_SEASON_ID,
                    "previous_label": HIST_SEASON_LABEL},
        "metrics": metrics_out,
        "summary": summary,
        "note": ("Test-retest MIĘDZY sezonami (Spearman) — miesza niestabilność metryki "
                 "z realną zmianą zawodnika. Split-half po meczach to ściślejszy upgrade."),
    }
 
 
def build_dataset(sb, creds):
    if not LEAGUE_CONFIG:
        die("LEAGUE_CONFIG jest puste — uzupełnij competition_id/season_id.")
 
    # --- Pass 1: pobierz pełne profile metryk dla każdej ligi ---
    league_rows = {}
    base_name = None
    for lg in LEAGUE_CONFIG:
        try:
            stats = sb.player_season_stats(
                competition_id=lg["competition_id"],
                season_id=lg["season_id"], creds=creds,
            )
            rows = stats.to_dict("records")
        except Exception as e:
            print(f"[uwaga] Nie pobrano {lg['name']}: {e}", file=sys.stderr)
            rows = []
        league_rows[lg["name"]] = rows
        if lg.get("base"):
            base_name = lg["name"]
 
    # --- Dołącz fizykę SkillCornera do wierszy (po nazwisku, w obrębie ligi) ---
    # Fizyka zasila WYŁĄCZNIE profil koherencji (styl gry); RC pozostaje czysto
    # techniczne. Brak modułu/pliku CSV = pipeline liczy koherencję bez fizyki.
    if phys is not None:
        total_m = 0
        for lg in LEAGUE_CONFIG:
            m, n = phys.enrich_rows(league_rows[lg["name"]], lg["name"])
            total_m += m
            if n:
                print(f"[fizyka] {lg['name']}: dopasowano {m}/{n} zawodnikow")
        print(f"[fizyka] Razem dopasowano {total_m} zawodnikow do danych SkillCorner.")
 
    # POSSESSION-ADJUSTMENT: RC korzysta teraz z NATYWNYCH metryk StatsBomb per-posiadanie
    # (op_xgbuildup_per_possession, op_xgchain_per_possession, xgbuildup_per_possession) —
    # liczonych na poziomie akcji, więc lepszych niż jakikolwiek proxy/% posiadania drużyny.
    # Stary proxy z op_passes (pola __tpadj) po oczyszczeniu metryk RC nie jest już przez nic
    # czytany, więc go NIE uruchamiamy (funkcja _normalize_team_possession zostaje na wypadek
    # powrotu metryki wolumenowej do RC, ale domyślnie jest wyłączona: TEAM_POSSESSION_ADJUST).
    if os.getenv("TEAM_POSSESSION_ADJUST", "0") not in ("0", "false", "False"):
        _normalize_team_possession(league_rows)
 
    base_rows = league_rows.get(base_name, []) if base_name else []
    if not base_rows:
        print("[uwaga] Brak danych bazowej ligi — poziomy i koherencja będą neutralne.", file=sys.stderr)
 
    # Populacja do normalizacji percentyli: tylko zawodnicy z wystarczającą próbką.
    def _enough_minutes(r):
        m = r.get("player_season_minutes")
        return isinstance(m, (int, float)) and m >= MIN_MINUTES
    base_pop = [r for r in base_rows if _enough_minutes(r)] or base_rows
 
    # --- Statystyki populacji ligi bazowej per ROLA (oś modelu: RC + koherencja) ---
    # Rola = grupa Igora (Bramka/ŚO/Boczny/Skrzydłowy/6-8/10-9), drobniej niż 4 linie.
    base_stats_by_role = {ro: coh.build_league_stats(base_pop, ro) for ro in coh.ROLES}
    # Macierze precyzji (Σ⁻¹) do WYBIELONEGO KOSINUSA w koherencji (Mahalanobis, p.17).
    # None dla roli, gdzie się nie da (mała próba / wyłączone) → coherence spada do kosinusa.
    precision_by_role = {ro: coh.build_precision(base_pop, ro, base_stats_by_role[ro])
                         for ro in coh.ROLES}
    _pc_ok = [ro for ro, p in precision_by_role.items() if p is not None]
    print(f"[koherencja] Metryka: {'Mahalanobis (wybielony kosinus)' if coh.COH_MAHALANOBIS else 'kosinus'}"
          f" · precyzja policzona dla ról: {_pc_ok or '(żadnej — fallback do kosinusa)'}",
          file=sys.stderr)
    # Uniwersalny profil stylu (do koherencji „każdy z każdym" w składzie).
    universal_stats = coh.build_universal_stats(base_pop)
    # Profil DOPASOWANY DO POZYCJI (panel „mocne strony"): populacja bazowa podzielona
    # wg 4 LINII TAKTYCZNYCH (kontrakt frontu: meta.style_labels[line] + profile_pos).
    # To jest oś WYŚWIETLANIA — celowo pozostaje 4-liniowa, niezależnie od ról modelu.
    LINES = ("Bramka", "Obrona", "Pomoc", "Atak")
    base_pop_by_line = {ln: [] for ln in LINES}
    for r in base_pop:
        _mp = POS_TO_LINE.get(r.get("primary_position") or r.get("position"))
        if _mp:
            base_pop_by_line[_mp[1]].append(r)
    pos_style_stats = {ln: coh.build_pos_style_stats(base_pop_by_line[ln], ln) for ln in LINES}
 
    # --- Handicapy lig (bez zmian, realna metoda) ---
    leagues = []
    for lg in LEAGUE_CONFIG:
        rows = league_rows[lg["name"]]
        handicap = league_handicap(rows, base_rows)
        leagues.append({"lg": lg["name"], "base": lg.get("base", False), **handicap})
 
    # --- Skład Rakowa ---
    # ŹRÓDŁO PRAWDY: public/squad.json — kurowany ręcznie przez analityka
    # (generator "wklej skład" z Transfermarktu). RC i profile i tak liczy model
    # ze StatsBomb; squad.json podaje tylko KTO jest w kadrze i na jakiej pozycji.
    # BEZPIECZNIK: gdy squad.json jest pusty/uszkodzony (< 11 zawodników),
    # awaryjnie budujemy skład automatycznie ze StatsBomb (kto zagrał dla Rakowa),
    # żeby aplikacja nigdy nie została bez składu.
    squad_path = OUT.parent / "squad.json"
    base_by_name = _name_index(base_rows)
    squad, rc_from_model = build_squad_from_file(
        squad_path, base_by_name, base_stats_by_role, universal_stats, pos_style_stats)
    src = "squad.json"
    if len(squad) < 11:
        print(f"[skład] squad.json dało tylko {len(squad)} zawodników — "
              f"awaryjnie buduję skład automatycznie ze StatsBomb.", file=sys.stderr)
        squad, rc_from_model = build_squad_from_statsbomb(
            base_rows, base_stats_by_role, universal_stats, pos_style_stats)
        src = "auto-StatsBomb"
 
    # FALLBACK HISTORYCZNY: dolicz RC z poprzedniego sezonu dla zawodników bez danych
    # bieżącego sezonu (oznaczone jako historyczne). Robione PRZED liczeniem puli, bo
    # ustawia _sb odzyskanym zawodnikom → stają się referencją koherencji dla puli.
    rc_hist = 0
    if squad:
        try:
            rc_hist = _apply_historical_fallback(
                sb, creds, squad, base_stats_by_role, universal_stats, pos_style_stats)
        except Exception as e:  # noqa: BLE001
            print(f"[hist] Fallback historyczny pominięty: {e}", file=sys.stderr)
 
    if not squad:
        print("[uwaga] Sklad Rakowa jest pusty — sprawdz public/squad.json / dane StatsBomb.", file=sys.stderr)
    else:
        print(f"Skład Rakowa: {len(squad)} zawodników (źródło: {src}), "
              f"RC z modelu: {rc_from_model}/{len(squad)}"
              f"{f' (+{rc_hist} z danych historycznych)' if rc_hist else ''}.")
 
    # --- Pula kandydatów z lig europejskich: poziom + koherencja ---
    squad_by_pos = {}
    squad_by_line = {}
    squad_by_role = {}
    for s in squad:
        squad_by_pos.setdefault(s["pos"], []).append(s)
        squad_by_line.setdefault(s["line"], []).append(s)
        squad_by_role.setdefault(s.get("role") or coh.role_of(s.get("pos"), s.get("line")), []).append(s)
 
    # Zbiór zawodników Rakowa (po player_id + nazwisku) — do wykluczenia z puli.
    # Solidniej niż _is_rakow_row: łapie też świeży transfer, którego StatsBomb wciąż
    # przypisuje do POPRZEDNIEGO klubu (jak Abraham Ojo), więc nie sugerujemy zawodnika,
    # którego już mamy.
    _squad_ids, _squad_names = set(), set()
    for s in squad:
        sb_row = s.get("_sb")   # NIE nadpisuj parametru `sb` (moduł StatsBomb) — patrz recent/stability niżej
        if sb_row and sb_row.get("player_id") is not None:
            _squad_ids.add(sb_row.get("player_id"))
        _squad_names.add(_norm(s.get("name", "")))
 
    pool = []
    _padj_diag = {}   # pozycja -> [n, suma_adj, suma_raw] do logu wpływu na RC
    _shr_diag = [0, 0.0]   # [ilu ściągniętych, suma delt] — log wpływu shrinkage
    for lg in LEAGUE_CONFIG:
        is_base = lg.get("base")
        for row in league_rows[lg["name"]]:
            # LIGA BAZOWA (Ekstraklasa): bierzemy kandydatów z INNYCH klubów — bez Rakowa.
            # Zawodnicy Rakowa są w składzie, nie w puli sugestii. Handicap Ekstraklasy = 0
            # (to liga odniesienia), więc ich poziom = surowe RC, bez premii/kary.
            if is_base and _is_rakow_row(row):
                continue
            # WYKLUCZENIE ZE SKŁADU (dowolna liga): nie sugeruj zawodnika, którego mamy,
            # nawet jeśli StatsBomb trzyma go pod innym/poprzednim klubem.
            if (row.get("player_id") in _squad_ids
                    or _norm(row.get("player_name", "")) in _squad_names):
                continue
            # FILTR MINUT: pomiń zawodników z małą próbką (zawyżone per-90).
            minutes = row.get("player_season_minutes")
            if not isinstance(minutes, (int, float)) or minutes < MIN_MINUTES:
                continue
 
            raw_pos = row.get("primary_position") or row.get("position")
            mapped = POS_TO_LINE.get(raw_pos)
            if not mapped:
                continue
            pos, line = mapped
            role = coh.role_of(pos, line)
            _lvl_pre = coh.quality_level(row, role, base_stats_by_role[role])  # bez shrink
            level, _shr_d = coh.shrink_rc(_lvl_pre, minutes)                   # shrink wg minut
            if _shr_d:
                _shr_diag[0] += 1
                _shr_diag[1] += _shr_d
            # DIAGNOSTYKA possession-adjustment: policz RC oboma zestawami metryk
            # BEZ shrinkage (żeby izolować sam efekt doboru metryk). Tanie — te same
            # percentyle, inny podzbiór metryk.
            _d = _padj_diag.setdefault(pos, [0, 0.0, 0.0])
            _d[0] += 1
            _d[1] += coh.quality_level(row, role, base_stats_by_role[role],
                                       coh.QUALITY_METRICS_PADJ.get(role))
            _d[2] += coh.quality_level(row, role, base_stats_by_role[role],
                                       coh.QUALITY_METRICS_RAW.get(role))
            # level_estimated: True gdy kandydat NIE ma metryk jakosciowych dla
            # swojej linii — wtedy quality_level zwrocil fallback (nie realny
            # percentyl). Front pokazuje wtedy znacznik "niepelne dane".
            _qm = coh.QUALITY_METRICS.get(role, [])
            _has_metrics = any(
                isinstance(row.get(m), (int, float)) for m in _qm
            )
            level_estimated = not _has_metrics
 
            # Koherencja: najpierw z zawodnikiem Rakowa z tej samej pozycji;
            # jeśli brak — porównaj do zawodników z tej samej LINII (szerszy kubełek).
            refs = squad_by_pos.get(pos) or squad_by_role.get(role, []) or squad_by_line.get(line, [])
            best_coh, best_ref = 0, None
            for s in refs:
                if not s.get("_sb"):
                    continue
                c = coh.coherence(row, s["_sb"], role, base_stats_by_role[role],
                                  precision=precision_by_role.get(role))
                if c > best_coh:
                    best_coh, best_ref = c, s["name"]
 
            pool.append({
                "id": f"pl-{row.get('player_id')}",
                "name": row.get("player_name") if _is_valid_name(row.get("player_name")) else "?",
                "lg": lg["name"], "pos": pos, "line": line, "role": role,
                "team": _row_team_name(row),   # do modułu analizy przeciwnika (grupowanie po drużynie)
                "raw": level,
                "level_estimated": level_estimated,
                "coherence": best_coh,
                "coherence_ref": best_ref,
                "age": _age(row.get("birth_date")),
                "mv": 0.0, "contract": 0,
                # Pola tymczasowe do dopasowania w Scoutastic (usuwane przed zapisem).
                "_bd": (row.get("birth_date") or "")[:10] if isinstance(row.get("birth_date"), str) else "",
                "_ht": row.get("player_height") if isinstance(row.get("player_height"), (int, float)) else 0,
                # Profile stylu: uniwersalny (cross-position) + dopasowany do
                # pozycji (bogatszy) — pod „w czym kandydat lepszy od naszego".
                "profile": coh.style_profile(row, universal_stats),
                "profile_pos": coh.pos_style_profile(row, line, pos_style_stats[line]),
            })
 
    # LOG wpływu possession-adjustment na RC (per pozycja: adj vs raw).
    if _padj_diag:
        mode = "possession-adjusted" if coh.POSSESSION_ADJUST else "SUROWA (raw)"
        print(f"[RC] Aktywny tryb metryk: {mode}. Wpływ korekty o posiadanie na RC "
              f"(średnie per pozycja, adj vs raw):", file=sys.stderr)
        for p in sorted(_padj_diag):
            n, sa, sr = _padj_diag[p]
            if n:
                print(f"      {p:>3}: n={n:<4} adj={sa / n:5.1f}  raw={sr / n:5.1f}  "
                      f"Δ={(sa - sr) / n:+5.1f}", file=sys.stderr)
        if coh.SHRINK:
            nsh, dsum = _shr_diag
            avg = (dsum / nsh) if nsh else 0
            print(f"[RC] Shrinkage małej próby: aktywny (K={coh.SHRINK_K:.0f}, prior={coh.SHRINK_PRIOR:.0f}). "
                  f"Ściągnięto {nsh} zawodników w puli, średnio o {avg:+.1f} pkt RC.", file=sys.stderr)
 
    # Usuń profile metryk ze składu przed zapisem (były tylko do liczenia)
    for s in squad:
        s.pop("_sb", None)
 
    # --- Wartości transferowe: z lokalnego pliku CSV (dane z Kaggle) ---
    # ZMIANA ARCHITEKTURY: wcześniej wartości dociągaliśmy na żywo z publicznego
    # Transfermarkt-api, który bywał niedostępny (HTTP 500) i wieszał workflow na
    # wiele minut. Teraz czytamy je ze STATYCZNEGO pliku scripts/player_values.csv
    # (zrzut z Kaggle, dataset davidcariboo/player-scores). Plik nie może "paść"
    # w trakcie uruchomienia — to plik, nie serwis. Aktualizuje się go ręcznie,
    # wgrywając świeży zrzut co jakiś czas (wartości zmieniają się rzadko).
    #
    # DOPASOWANIE: kandydaci mają nazwiska ze StatsBomb, plik wartości ma nazwiska
    # z Transfermarktu — łączymy po ZNORMALIZOWANYM nazwisku (bez znaków diakryt.,
    # lowercase). Część zawodników się nie dopasuje (inne zapisy, zdrobnienia) —
    # to NIE błąd, zostają z mv=0, tak jak było przy niedostępnym TM.
    values_by_name, values_sur = _load_values_csv(Path(__file__).resolve().parent / "player_values.csv")
    matched = matched_tok = 0
    for c in pool:
        v = values_by_name.get(_norm_ascii(c["name"]))
        if not v:
            v = _match_by_tokens(c["name"], values_sur, lambda x: round(x["mv"], 1))
            if v:
                matched_tok += 1
        if v:
            c["mv"] = v["mv"]           # wartość w mln EUR
            if v.get("age"):
                c["age"] = v["age"]
            if v.get("contract"):
                c["contract"] = v["contract"]
            # Ubogacenie: szczyt wartości + output (gole/asysty/minuty) sezonu.
            if v.get("peak"):
                c["peak"] = v["peak"]
            for k in ("goals", "assists", "minutes"):
                if v.get(k):
                    c[k] = v[k]
            matched += 1
    print(f"Wartości rynkowe: dopasowano {matched}/{len(pool)} kandydatów "
          f"(w tym {matched_tok} dopasowaniem po nazwisku) z player_values.csv")
 
    # Wzbogacenie SKŁADU o wiek/wartość/kontrakt (Kaggle + Scoutastic) — zasila
    # moduły „Priorytety transferowe" i „Czerwone flagi" na froncie.
    _enrich_squad(squad, values_by_name, values_sur)
 
    # --- SCOUTASTIC: oficjalne wartości z Transfermarktu (przez API instancji) ---
    # Włączane obecnością sekretu SCOUTASTIC_TOKEN. Dopasowuje pulę do Scoutastic
    # przez /players/matching/statsbomb (po ID/nazwisku/dacie ur.), potem dociąga
    # marketValue + szczyt + kontrakt. Nadpisuje wartości z Kaggle, gdy dostępne
    # (źródło oficjalne, świeższe). Cache w scripts/scoutastic_cache.json. Błędy
    # nie wywalają runu (fallback = wartości z Kaggle).
    if os.getenv("SCOUTASTIC_TOKEN"):
        try:
            _enrich_values_scoutastic(pool)
        except Exception as e:  # noqa: BLE001
            print(f"[scoutastic] Pominięto (błąd): {e}", file=sys.stderr)
 
    # Sprzątanie pól tymczasowych użytych tylko do dopasowania w Scoutastic.
    for c in pool:
        c.pop("_bd", None)
        c.pop("_ht", None)
    for s in squad:
        s.pop("_bd", None)
 
    # --- OPCJONALNIE: doczytanie wartości z Transfermarktu dla topowych bez ceny ---
    # Włączane flagą TM_ENRICH=1 (publiczne API bywa wolne/limitowane). Pyta TYLKO
    # o kandydatów bez ceny o najwyższej koherencji (limit TM_ENRICH_TOP, domyślnie
    # 150), z cache w scripts/tm_values_cache.json — kolejne uruchomienia nie pytają
    # ponownie. Błędy API nie wywalają runu (fallback = brak ceny).
    if os.getenv("TM_ENRICH") and tm is not None:
        _enrich_values_tm(pool)
 
 
    # Kalibracja cen: mnożniki fee/mv wg wieku (z transfers.csv na Kaggle).
    price_calibration = {}
    try:
        cal_path = Path(__file__).resolve().parent / "price_calibration.json"
        if cal_path.exists():
            price_calibration = json.loads(cal_path.read_text(encoding="utf-8"))
            print(f"Kalibracja cen wczytana: {price_calibration}")
    except Exception as e:  # noqa: BLE001
        print(f"[uwaga] Nie wczytano price_calibration.json: {e}", file=sys.stderr)
 
    return {
        "meta": {
            "source": "statsbomb+kaggle-values",
            "generated": __import__("datetime").date.today().isoformat(),
            "note": ("Poziom = percentyl metryk vs Ekstraklasa. Koherencja = podobieństwo "
                     "profilu gry do zawodnika Rakowa (position-specific similarity). "
                     "Wartość transferowa (Transfermarkt) dociągana tylko dla kandydatów "
                     "pasujących wg modelu (koherencja >= 70%). Dane: StatsBomb + Transfermarkt."),
            # Etykiety atrybutów profilu pozycyjnego (profile_pos) — front czyta
            # je stąd, żeby nie powielać listy. Kolejność == wektor profile_pos.
            "style_labels": {ln: coh.pos_style_labels(ln) for ln in ("Bramka", "Obrona", "Pomoc", "Atak")},
            "price_calibration": price_calibration,
        },
        "squad": squad,
        "leagues": leagues,
        "pool": pool,
        # Zależności formacji = REALNE podobieństwo stylu ról (nie sieć podań).
        "correlations": _formation_style_correlations(pool),
        # Ostatnie mecze Rakowa jako walidator RC/preferencji trenera (defensywnie).
        "recent": _fetch_recent_matches(sb, creds, squad),
        # Stabilność metryk (ICC/test-retest między sezonami) — diagnostyka p.7.
        "stability": _metric_stability(sb, creds, base_rows),
    }
 
 
def _normalize_team_possession(league_rows):
    """Dokończenie possession-adjustment dla metryk wolumenowych bez natywnego wariantu
    per-posiadanie (coh.TEAM_NORM_METRICS: podania kluczowe, do pola karnego, strzały,
    touche w polu karnym). Dla każdej ligi liczymy PROXY posiadania drużyny jako
    minuto-ważoną średnią op_passes_90 jej zawodników, potem współczynnik
    = proxy_drużyny / średnia_ligi (clamp 0.6–1.6), i dzielimy metryki wolumenowe przez
    ten współczynnik. Wynik zapisujemy w polach z sufiksem __tpadj. Liczone W OBRĘBIE
    LIGI (usuwa przewagę wolumenu wynikającą z większego posiadania względem rówieśników
    z tej samej ligi). To PROXY posiadania (z wolumenu podań), nie oficjalny % — świadome
    uproszczenie bez dodatkowego zapytania do API. Wyłączalne: TEAM_POSSESSION_ADJUST=0
    (wtedy __tpadj = wartość surowa, więc RC wraca do niezmienionego wolumenu)."""
    on = os.getenv("TEAM_POSSESSION_ADJUST", "1") not in ("0", "false", "False")
    srcs = coh.TEAM_NORM_METRICS
    suf = coh.TEAM_NORM_SUFFIX
    n_adj, spread = 0, []
    for _lg, rows in league_rows.items():
        num, den = {}, {}
        for r in rows:
            op = r.get("player_season_op_passes_90")
            mn = r.get("player_season_minutes")
            tid = r.get("team_id") or (_row_team_name(r) or None)
            if isinstance(op, (int, float)) and isinstance(mn, (int, float)) and mn > 0 and tid is not None:
                num[tid] = num.get(tid, 0.0) + op * mn
                den[tid] = den.get(tid, 0.0) + mn
        prox = {t: num[t] / den[t] for t in num if den[t] > 0}
        lg_mean = (sum(prox.values()) / len(prox)) if prox else 0.0
        for r in rows:
            tid = r.get("team_id") or (_row_team_name(r) or None)
            if on and lg_mean > 0 and tid in prox:
                f = max(0.6, min(1.6, prox[tid] / lg_mean))
            else:
                f = 1.0
            if on and abs(f - 1.0) > 1e-9:
                spread.append(f)
            for s in srcs:
                v = r.get(s)
                if isinstance(v, (int, float)) and not (math.isnan(v) or math.isinf(v)):
                    r[s + suf] = v / f
                    if on and abs(f - 1.0) > 1e-9:
                        n_adj += 1
    if on:
        lo = min(spread) if spread else 1.0
        hi = max(spread) if spread else 1.0
        print(f"[RC] Normalizacja przez posiadanie drużyny (proxy): aktywna. "
              f"Skorygowano {n_adj} wartości; współczynnik posiadania {lo:.2f}–{hi:.2f}.",
              file=sys.stderr)
    else:
        print("[RC] Normalizacja przez posiadanie drużyny: WYŁĄCZONA (TEAM_POSSESSION_ADJUST=0).",
              file=sys.stderr)
 
 
def _formation_style_correlations(pool):
    """Realne „zależności formacji" jako PODOBIEŃSTWO STYLU ról. Dla każdej pozycji
    liczymy centroid uniwersalnego profilu stylu (z-score vs Ekstraklasa, 17 wymiarów)
    ze WSZYSTKICH zawodników puli na tej pozycji, a potem kosinus między centroidami
    (przeskalowany do 0..1). Wysokie = role o zbliżonym stylu; niskie = uzupełniające
    się. To NIE jest sieć podań (kto z kim gra) — na to trzeba danych zdarzeniowych.
    Zwraca kompaktowy obiekt do data.json['correlations']; front tylko go renderuje."""
    import math
    ORDER = ["GK", "CB", "WB", "WM", "DM", "CM", "AM", "W", "ST"]
    MIN_N = 10
    groups = {}
    for p in pool:
        prof = p.get("profile")
        pos = p.get("pos")
        if isinstance(prof, list) and prof and any(prof):
            groups.setdefault(pos, []).append(prof)
    centroids, counts = {}, {}
    for pos, arr in groups.items():
        if len(arr) < MIN_N:
            continue
        L = len(arr[0])
        centroids[pos] = [sum(v[i] for v in arr) / len(arr) for i in range(L)]
        counts[pos] = len(arr)
 
    def _cos(a, b):
        d = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return d / (na * nb) if na and nb else 0.0
 
    positions = [p for p in ORDER if p in centroids]
    sim = {}
    for a in positions:
        for b in positions:
            sim[f"{a}-{b}"] = round((_cos(centroids[a], centroids[b]) + 1) / 2, 3)
 
    # SPÓJNOŚĆ WEWNĄTRZ POZYCJI (odpowiedź na pytanie o wariancję wewnątrzpozycyjną):
    # średnie podobieństwo zawodnika roli do centroidu tej roli (0..1). Wysokie =
    # rola stylistycznie jednorodna; niskie = duży rozrzut w obrębie roli (np. różne
    # typy stopera). Zestawiamy to z podobieństwem MIĘDZY rolami — jeśli spójność
    # wewnątrz nie jest wyraźnie wyższa niż podobieństwo między rolami, macierz niesie
    # głównie szum. To uczciwy licznik sygnału vs szumu dla tego ekranu.
    cohesion = {}
    for pos in positions:
        c = centroids[pos]
        vals = [(_cos(v, c) + 1) / 2 for v in groups[pos]]
        cohesion[pos] = round(sum(vals) / len(vals), 3) if vals else None
    within = round(sum(cohesion.values()) / len(cohesion), 3) if cohesion else None
    offvals = [sim[f"{a}-{b}"] for a in positions for b in positions if a != b]
    between = round(sum(offvals) / len(offvals), 3) if offvals else None
 
    print(f"[formacja] Podobieństwo stylu dla {len(positions)} pozycji "
          f"(próby: {counts}). Spójność wewnątrz ról śr={within} vs między rolami śr={between}.")
    return {
        "method": "style-centroid-cosine",
        "note": ("Podobieństwo stylu ról: kosinus między średnimi profilami stylu "
                 "(z-score vs Ekstraklasa) pozycji, liczony z całej puli. "
                 "Wysokie = role grają podobnie; niskie = uzupełniają się. "
                 "To nie jest sieć podań."),
        "positions": positions,
        "counts": counts,
        "sim": sim,
        # spójność wewnątrz pozycji + porównanie within vs between (sygnał vs szum)
        "cohesion": cohesion,
        "within": within,
        "between": between,
    }
 
 
# --- Pomocnicze ---
def _is_valid_name(v):
    """True tylko dla sensownych napisów (odrzuca None, NaN, liczby)."""
    if not isinstance(v, str):
        return False
    s = v.strip()
    return len(s) > 0 and s.lower() != "nan"
 
def _norm(name):
    if not isinstance(name, str):
        return ""
    return name.strip().lower()
 
def _norm_ascii(name):
    """Normalizacja do dopasowania nazwisk między StatsBomb a plikiem wartości.
    Usuwa znaki diakrytyczne (Ivanović -> ivanovic), sprowadza do małych liter,
    ścina nadmiarowe spacje. Dzięki temu 'Franjo Ivanović' (SB) dopasuje się do
    'Franjo Ivanovic' (Kaggle)."""
    import unicodedata
    if not isinstance(name, str):
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.strip().lower().split())
 
 
def _tokens(name):
    """Tokeny nazwiska do dopasowania rozmytego (ascii, bez krótkich cząstek)."""
    s = _norm_ascii((name or "").replace("ł", "l").replace("Ł", "l")).replace("-", " ")
    return [t for t in s.split() if len(t) > 1]
 
 
def _surname_index(items):
    """items: [(name, payload)] -> {nazwisko: [(set(tokeny), imie, payload)]}."""
    idx = {}
    for name, payload in items:
        tk = _tokens(name)
        if tk:
            idx.setdefault(tk[-1], []).append((set(tk), tk[0], payload))
    return idx
 
 
def _match_by_tokens(name, idx, dedup_key):
    """Dopasowanie po nazwisku + nakładaniu tokenów. Zwraca payload TYLKO gdy
    jest jednoznaczny (wszystkie trafienia wskazują to samo wg dedup_key),
    inaczej None — lepiej brak dopasowania niż złe."""
    tk = _tokens(name)
    if not tk:
        return None
    cands = []
    for tset, first, payload in idx.get(tk[-1], []):
        shared = len(set(tk) & tset)
        if shared >= 2 or (shared >= 1 and tk[0] == first):
            cands.append(payload)
    if not cands:
        return None
    keys = {dedup_key(p) for p in cands}
    return cands[0] if len(keys) == 1 else None
 
def _load_values_csv(path):
    """Wczytuje wartości rynkowe z lokalnego CSV (zrzut Kaggle) do słownika
    {znormalizowane_nazwisko: {mv, age, contract}}. Wartość przeliczana na mln EUR
    (aplikacja pokazuje '€X.XM'). Gdy plik nie istnieje — zwraca pusty słownik i
    kandydaci zostają z mv=0 (aplikacja działa dalej, po prostu bez cen)."""
    import csv, datetime as _dt
    result = {}
    try:
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = row.get("name_norm") or _norm_ascii(row.get("name", ""))
                if not key:
                    continue
                # Wartość: EUR -> mln EUR
                try:
                    mv_eur = float(row.get("mv_eur") or 0)
                except (ValueError, TypeError):
                    mv_eur = 0.0
                mv_mln = round(mv_eur / 1_000_000.0, 2)
                # Wiek z daty urodzenia
                age = 0
                dob = row.get("dob") or ""
                if len(dob) >= 4 and dob[:4].isdigit():
                    age = max(0, _dt.date.today().year - int(dob[:4]))
                # Rok wygaśnięcia kontraktu
                contract = 0
                con = row.get("contract") or ""
                if len(con) >= 4 and con[:4].isdigit():
                    contract = int(con[:4])
                # Ubogacenie (Kaggle): szczyt wartości + output bieżącego sezonu.
                def _num(x):
                    try:
                        return float(x or 0)
                    except (ValueError, TypeError):
                        return 0.0
                peak_mln = round(_num(row.get("mv_peak_eur")) / 1_000_000.0, 2)
                goals = int(_num(row.get("goals")))
                assists = int(_num(row.get("assists")))
                minutes = int(_num(row.get("minutes")))
                # Gdy nazwisko powtarza się w pliku, bierz wyższą wartość
                # (zwykle to ten "właściwy", aktywny zawodnik).
                prev = result.get(key)
                if prev and prev["mv"] >= mv_mln:
                    continue
                result[key] = {"mv": mv_mln, "age": age, "contract": contract,
                               "peak": peak_mln, "goals": goals, "assists": assists, "minutes": minutes}
    except FileNotFoundError:
        print(f"[uwaga] Nie znaleziono {path} — kandydaci zostaną bez wartości "
              f"rynkowych (mv=0). Wgraj scripts/player_values.csv.", file=sys.stderr)
    except Exception as e:
        print(f"[uwaga] Błąd czytania {path}: {e} — pomijam wartości.", file=sys.stderr)
    # Indeks po nazwisku do dopasowania rozmytego (odzyskuje ceny, gdy nazwa
    # w StatsBomb różni się od pliku — np. dodatkowe imiona).
    sur_index = _surname_index([(k, v) for k, v in result.items()])
    return result, sur_index
 
def _pick_scoutastic(name, dob, results):
    """Wybiera najlepsze trafienie z wyszukiwarki Scoutastic. Wymaga zgodności
    NAZWISKA; przy braku daty ur. wymaga też imienia (mniej fałszywych trafień).
    Punktuje zgodność roku urodzenia i pokrycie tokenów. Zwraca dict albo None."""
    tks = _tokens(name)
    if not tks or not results:
        return None
    surname = tks[-1]
    our_year = dob[:4] if isinstance(dob, str) and len(dob) >= 4 and dob[:4].isdigit() else None
    best, best_score = None, -1
    for r in results:
        full = set(_tokens(f"{r.get('firstName') or ''} {r.get('lastName') or ''}"))
        if surname not in full:
            continue
        rdob = r.get("dateOfBirth") or ""
        year_ok = bool(our_year) and isinstance(rdob, str) and rdob[:4] == our_year
        if not our_year and tks[0] not in full:   # bez daty ur. — wymagaj też imienia
            continue
        score = (3 if year_ok else 0) + len(set(tks) & full)
        if score > best_score:
            best, best_score = r, score
    return best
 
 
def _enrich_squad(squad, values_by_name, values_sur):
    """Dokłada wiek/wartość/kontrakt/szczyt do zawodników SKŁADU Rakowa.
    Najpierw z Kaggle (player_values.csv, po nazwisku), potem — dla braków —
    z wyszukiwarki Scoutastic (jak pula, tylko ~kadra, więc tanio). Cache dzieli
    z pulą (klucze 'rk:<id>'). Zasila moduły Priorytety i Czerwone flagi."""
    import json as _json
    # 1) KAGGLE po nazwisku
    km = 0
    for s in squad:
        v = values_by_name.get(_norm_ascii(s["name"]))
        if not v:
            v = _match_by_tokens(s["name"], values_sur, lambda x: round(x["mv"], 1))
        if v:
            if v.get("mv"):
                s["mv"] = v["mv"]
            if v.get("age") and not s.get("age"):
                s["age"] = v["age"]
            if v.get("contract"):
                s["contract"] = v["contract"]
            if v.get("peak"):
                s["peak"] = v["peak"]
            km += 1
 
    # 2) SCOUTASTIC dla braków (wartość/kontrakt/wiek) — tylko gdy jest token
    sc_fill = 0
    token = os.getenv("SCOUTASTIC_TOKEN")
    if token:
        try:
            import scoutastic as sc
            client = sc.Client(token)
            cache_path = Path(__file__).resolve().parent / "scoutastic_cache.json"
            try:
                cache = _json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                cache = {}
            tol = int(os.getenv("SCOUTASTIC_DOB_TOL_DAYS", "4")) * 86400
            for s in squad:
                if float(s.get("mv") or 0) > 0 and s.get("contract") and s.get("age"):
                    continue                      # komplet — nie pytamy
                if not _is_valid_name(s.get("name")):
                    continue
                key = "rk:" + s["id"]
                rec = cache.get(key)
                if rec is None:
                    dob = s.get("_bd")
                    dob_unix = sc.dob_to_unix(dob)
                    try:
                        results = client.search_player(
                            s["name"], dob_unix=dob_unix,
                            tolerance=(tol if dob_unix else None))
                    except Exception:  # noqa: BLE001
                        results = []
                    best = _pick_scoutastic(s["name"], dob, results)
                    raw = client.get_player(best.get("playerId")) if best else None
                    rec = sc.extract(raw) if raw else {"miss": True}
                    cache[key] = rec
                if rec and not rec.get("miss"):
                    if rec.get("mv"):
                        s["mv"] = rec["mv"]
                    if rec.get("contract"):
                        s["contract"] = rec["contract"]
                    if rec.get("peak"):
                        s["peak"] = rec["peak"]
                    if rec.get("age") and not s.get("age"):
                        s["age"] = rec["age"]
                    sc_fill += 1
            try:
                cache_path.write_text(_json.dumps(cache, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001
            print(f"[skład] Scoutastic enrichment pominięte: {e}", file=sys.stderr)
 
    priced = sum(1 for s in squad if float(s.get("mv") or 0) > 0)
    withc = sum(1 for s in squad if s.get("contract"))
    witha = sum(1 for s in squad if s.get("age"))
    print(f"[skład] Wzbogacono: Kaggle {km}, Scoutastic +{sc_fill}. "
          f"Wartość {priced}/{len(squad)}, kontrakt {withc}/{len(squad)}, "
          f"wiek {witha}/{len(squad)}.")
 
 
def _enrich_values_scoutastic(pool):
    """Dociąga oficjalne wartości rynkowe z Scoutastic (Transfermarkt). Endpoint
    matching (StatsBomb) jest w instancji WYŁĄCZONY, więc idziemy przez WYSZUKIWARKĘ:
    dla kandydata szukamy po nazwisku (+ data ur. jako filtr), wybieramy najlepsze
    trafienie i pobieramy jego marketValue/szczyt/kontrakt. Domyślnie tylko dla
    kandydatów BEZ ceny z Kaggle (uzupełnianie luki). Cache w scoutastic_cache.json —
    kolejne uruchomienia pobierają tylko nowych; limit tury chroni przed rate-limitem."""
    import json as _json
    try:
        import scoutastic as sc
    except Exception as e:  # noqa: BLE001
        print(f"[scoutastic] Brak modułu scoutastic.py ({e}) — pomijam.", file=sys.stderr)
        return
    token = os.getenv("SCOUTASTIC_TOKEN")
    if not token:
        return
    cache_path = Path(__file__).resolve().parent / "scoutastic_cache.json"
    try:
        cache = _json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
 
    def _pid(c):
        return c["id"].split("pl-")[-1]
 
    client = sc.Client(token)
    only_unpriced = os.getenv("SCOUTASTIC_ALL") not in ("1", "true", "True")
 
    targets = []
    for c in pool:
        if _pid(c) in cache or not _is_valid_name(c.get("name")):
            continue
        if only_unpriced and float(c.get("mv") or 0) > 0:
            continue
        targets.append(c)
 
    cap = int(os.getenv("SCOUTASTIC_MAX", "1200"))
    tol = int(os.getenv("SCOUTASTIC_DOB_TOL_DAYS", "4")) * 86400
    print(f"[scoutastic] Szukam wartości dla {len(targets)} kandydatów "
          f"(limit tej tury: {cap}, w cache: {len(cache)}). Tryb: "
          f"{'tylko bez ceny' if only_unpriced else 'wszyscy'}.")
 
    processed = matched = 0
    shown_err = shown_dbg = False
    for c in targets:
        if processed >= cap:
            print(f"[scoutastic] Limit {cap} na turę — resztę dobierze kolejny run.",
                  file=sys.stderr)
            break
        pid = _pid(c)
        dob = c.get("_bd")
        dob_unix = sc.dob_to_unix(dob)
        try:
            results = client.search_player(c["name"], dob_unix=dob_unix,
                                           tolerance=(tol if dob_unix else None))
        except Exception as e:  # noqa: BLE001
            if not shown_err:
                print(f"[scoutastic] search: pierwszy błąd — {e}", file=sys.stderr)
                shown_err = True
            processed += 1           # błąd transportu — bez oznaczania miss (spróbujemy potem)
            continue
        best = _pick_scoutastic(c["name"], dob, results)
        if not best:
            cache[pid] = {"miss": True}
            processed += 1
            continue
        raw = client.get_player(best.get("playerId"))
        if not shown_dbg and isinstance(raw, dict):
            keys = [k for k in raw.keys() if "market" in k.lower() or "contract" in k.lower()]
            print(f"[scoutastic] Przykład pól (weryfikacja): {keys} -> "
                  f"marketValue={raw.get('marketValue')!r}")
            shown_dbg = True
        cache[pid] = sc.extract(raw) if raw else {"miss": True}
        if raw and cache[pid].get("mv"):
            matched += 1
        processed += 1
        if processed % 200 == 0:     # zapis kroczący (odporność na przerwanie)
            try:
                cache_path.write_text(_json.dumps(cache, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
 
    try:
        cache_path.write_text(_json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"[scoutastic] Nie zapisano cache: {e}", file=sys.stderr)
 
    # Nałóż na pulę (oficjalne wartości nadpisują Kaggle).
    applied = 0
    for c in pool:
        v = cache.get(_pid(c))
        if not v or v.get("miss"):
            continue
        if v.get("mv"):
            c["mv"] = v["mv"]
            applied += 1
        if v.get("peak"):
            c["peak"] = v["peak"]
        if v.get("contract"):
            c["contract"] = v["contract"]
    priced = sum(1 for c in pool if float(c.get("mv") or 0) > 0)
    print(f"[scoutastic] Ta tura: przetworzono {processed}, dopasowano z ceną {matched}. "
          f"Wartości w puli od Scoutastic: {applied}. Pokrycie cenami łącznie: {priced}/{len(pool)}.")
 
 
def _enrich_values_tm(pool):
    """Doczytuje wartości z Transfermarktu (przez transfermarkt.py) dla kandydatów
    BEZ ceny, o najwyższej koherencji. Cache w scripts/tm_values_cache.json.
    Bezpieczne: błędy pojedynczych zapytań są pomijane."""
    import json as _json
    cache_path = Path(__file__).resolve().parent / "tm_values_cache.json"
    try:
        cache = _json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    top_n = int(os.getenv("TM_ENRICH_TOP", "150"))
    unpriced = [c for c in pool
                if (float(c.get("mv") or 0) <= 0) and _is_valid_name(c.get("name"))]
    unpriced.sort(key=lambda c: -(float(c.get("coherence") or 0)))
    targets = unpriced[:top_n]
    print(f"[TM] Doczytuję wartości dla {len(targets)} kandydatów bez ceny "
          f"(najwyższa koherencja)…")
    # BEZPIECZNIK: gdy publiczne API TM leży (sypie 500 na każde zapytanie), nie ma
    # sensu mielić przez wszystkie 150 kandydatów po ~14 s każdy (34 min w plecy za
    # 0 wycen). Po serii kolejnych ZAPYTAŃ NA ŻYWO bez ani jednej ceny przerywamy —
    # to prawie na pewno padnięte API, a nie zbieg braków. Próg z env (domyślnie 12).
    break_after = int(os.getenv("TM_BREAK_AFTER", "12"))
    applied = queried = consec_fail = 0
    for c in targets:
        key = _norm_ascii(c["name"])
        v = cache.get(key)
        if v is None:
            try:
                v = tm.fetch_player_value(c["name"]) or {"mv": 0}
            except Exception as e:  # noqa: BLE001
                print(f"[TM] {c['name']}: błąd ({e})", file=sys.stderr)
                v = {"mv": 0}
            cache[key] = v
            queried += 1
            # licznik bezpiecznika tylko dla zapytań NA ŻYWO (cache nie liczy się)
            consec_fail = 0 if float(v.get("mv") or 0) > 0 else consec_fail + 1
        if v and float(v.get("mv") or 0) > 0:
            c["mv"] = v["mv"]
            if v.get("age"):
                c["age"] = v["age"]
            if v.get("contract"):
                c["contract"] = v["contract"]
            applied += 1
        if break_after > 0 and consec_fail >= break_after and applied == 0:
            print(f"[TM] Przerywam — {consec_fail} kolejnych zapytań bez ceny i 0 trafień. "
                  f"API prawdopodobnie niedostępne. (Odpalaj bez tm_enrich, aż wróci.)",
                  file=sys.stderr)
            break
    try:
        cache_path.write_text(_json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"[TM] Nie zapisano cache: {e}", file=sys.stderr)
    print(f"[TM] Zapytań do API: {queried}, uzupełnionych wycen: {applied} "
          f"(reszta bez ceny — brak w TM lub API niedostępne).")
 
 
def _slug(name):
    if not isinstance(name, str) or not name.strip():
        return "x"
    return name.strip().replace(" ", "-").lower()
 
def _name_index(rows):
    """Indeks wierszy po nazwisku i znanym nazwisku (dla dopasowania TM↔SB)."""
    idx = {}
    for r in rows:
        for key in (r.get("player_name"), r.get("player_known_name")):
            if _is_valid_name(key):
                idx[_norm(key)] = r
    return idx
 
def _age(birth_date):
    if not birth_date or not isinstance(birth_date, str) or len(birth_date) < 4:
        return 0
    try:
        import datetime as _dt
        y = int(birth_date[:4])
        return max(0, _dt.date.today().year - y)
    except Exception:
        return 0
 
 
def _sanitize(obj):
    """Rekurencyjnie zamienia NaN / nieskończoności na 0 w całej strukturze.
    KLUCZOWE: Python domyślnie zapisuje NaN do JSON-a, ale przeglądarka NIE
    umie go wczytać (NaN nie jest legalnym JSON-em) — efektem jest czarny
    ekran 'Nie udało się wczytać danych'. Ta funkcja temu zapobiega."""
    if isinstance(obj, float):
        return 0 if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj
 
 
def main():
    creds = get_credentials()
    sb = load_statsbombpy()
    print("Łączę ze StatsBomb i pobieram dane…")
    dataset = build_dataset(sb, creds)
    # ZABEZPIECZENIE: pusty skład = aplikacja się nie wczyta (czarny ekran).
    # Nie nadpisujemy dobrego pliku śmieciem — przerywamy z błędem.
    if not dataset.get("squad"):
        print(
            "[BŁĄD] Skład Rakowa jest pusty.\n"
            "       Plik NIE został zapisany, żeby nie nadpisać działających danych.\n"
            "       Sprawdź public/squad.json (czy istnieje i ma poprawny format).",
            file=sys.stderr,
        )
        sys.exit(1)
    dataset = _sanitize(dataset)  # usuń NaN/inf zanim trafią do pliku
    # allow_nan=False => gdyby coś przeciekło, skrypt krzyknie zamiast po cichu
    # zapisać plik, którego przeglądarka nie wczyta.
    OUT.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    # DIAGNOSTYKA metryk: ile realnie weszlo do liczenia poziomu per linia.
    try:
        import coherence as _c
        if getattr(_c, "DIAG", None):
            print("\n--- DIAGNOSTYKA METRYK (ile z QUALITY_METRICS realnie policzono) ---")
            for line, d in _c.DIAG.items():
                total = len(_c.QUALITY_METRICS.get(line, []))
                print(f"  {line}: zdefiniowano {total} metryk | rozklad uzytych: {d['counts']}")
                if d["used"] is not None:
                    print(f"      przyklad -> uzyte: {d['used']}")
                    print(f"                  brak: {d['missing'] or '(zadnych)'}")
    except Exception as _e:
        print(f"[diag] {_e}")
    print(f"Zapisano: {OUT}")
    print(f"  skład: {len(dataset['squad'])}, ligi: {len(dataset['leagues'])}, pula: {len(dataset['pool'])}")
 
 
if __name__ == "__main__":
    main()
