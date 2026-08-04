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
 
 
def _squad_entry(name, sb_row, pos, line, rc, est, universal_stats, pos_style_stats):
    return {
        "id": f"rk-{_slug(name)}", "name": name, "pos": pos, "line": line,
        "rc": rc, "real": True, "rc_estimated": est,
        "profile": coh.style_profile(sb_row, universal_stats) if sb_row else None,
        "profile_pos": coh.pos_style_profile(sb_row, line, pos_style_stats[line]) if sb_row else None,
        "_sb": sb_row,
    }
 
 
def build_squad_from_statsbomb(base_rows, base_stats_by_line, universal_stats, pos_style_stats):
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
        model_rc = (coh.quality_level(r, line, base_stats_by_line[line])
                    if _player_minutes(r) >= MIN_MINUTES else None)
        if isinstance(model_rc, (int, float)):
            rc, est = model_rc, False
            rc_from_model += 1
        else:
            rc, est = 72, True   # za mała próbka / brak metryk -> "b.d." na froncie
        squad.append(_squad_entry(r.get("player_name"), r, pos, line, rc, est,
                                  universal_stats, pos_style_stats))
    return squad, rc_from_model
 
 
def build_squad_from_file(squad_path, base_by_name, base_stats_by_line, universal_stats, pos_style_stats):
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
        model_rc = coh.quality_level(sb_row, line, base_stats_by_line[line]) if sb_row else None
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
        entry = _squad_entry(name, sb_row, pos, line, rc, est, universal_stats, pos_style_stats)
        if pl.get("id"):
            entry["id"] = pl["id"]
        squad.append(entry)
    return squad, rc_from_model
 
 
def _apply_historical_fallback(sb, creds, squad, base_stats_by_line,
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
        row = hist_by_name.get(_norm(name)) \
            or _match_by_tokens(name, hist_sur, lambda r: r.get("player_id"))
        if not row or _player_minutes(row) < MIN_MINUTES:
            continue
        rc = coh.quality_level(row, line, base_stats_by_line[line])
        if not isinstance(rc, (int, float)):
            continue
        e["rc"] = rc
        e["rc_estimated"] = False
        e["rc_source"] = "historical"
        e["rc_season"] = HIST_SEASON_LABEL
        e["profile"] = coh.style_profile(row, universal_stats)
        e["profile_pos"] = coh.pos_style_profile(row, line, pos_style_stats[line])
        e["_sb"] = row              # staje się też referencją koherencji dla puli
        recovered += 1
        print(f"[hist] {name}: RC {rc} z sezonu {HIST_SEASON_LABEL} "
              f"({int(_player_minutes(row))} min).")
    print(f"[hist] Odzyskano {recovered}/{len(todo)} zawodników z danych historycznych.")
    return recovered
 
 
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
 
    base_rows = league_rows.get(base_name, []) if base_name else []
    if not base_rows:
        print("[uwaga] Brak danych bazowej ligi — poziomy i koherencja będą neutralne.", file=sys.stderr)
 
    # Populacja do normalizacji percentyli: tylko zawodnicy z wystarczającą próbką.
    def _enough_minutes(r):
        m = r.get("player_season_minutes")
        return isinstance(m, (int, float)) and m >= MIN_MINUTES
    base_pop = [r for r in base_rows if _enough_minutes(r)] or base_rows
 
    # --- Statystyki populacji ligi bazowej per linia (do normalizacji) ---
    base_stats_by_line = {ln: coh.build_league_stats(base_pop, ln)
                          for ln in ("Bramka", "Obrona", "Pomoc", "Atak")}
    # Uniwersalny profil stylu (do koherencji „każdy z każdym" w składzie).
    universal_stats = coh.build_universal_stats(base_pop)
    # Profil DOPASOWANY DO POZYCJI: populacja bazowa podzielona wg linii, żeby
    # z-score liczyć względem rówieśników z tej samej pozycji (position-fair).
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
        squad_path, base_by_name, base_stats_by_line, universal_stats, pos_style_stats)
    src = "squad.json"
    if len(squad) < 11:
        print(f"[skład] squad.json dało tylko {len(squad)} zawodników — "
              f"awaryjnie buduję skład automatycznie ze StatsBomb.", file=sys.stderr)
        squad, rc_from_model = build_squad_from_statsbomb(
            base_rows, base_stats_by_line, universal_stats, pos_style_stats)
        src = "auto-StatsBomb"
 
    # FALLBACK HISTORYCZNY: dolicz RC z poprzedniego sezonu dla zawodników bez danych
    # bieżącego sezonu (oznaczone jako historyczne). Robione PRZED liczeniem puli, bo
    # ustawia _sb odzyskanym zawodnikom → stają się referencją koherencji dla puli.
    rc_hist = 0
    if squad:
        try:
            rc_hist = _apply_historical_fallback(
                sb, creds, squad, base_stats_by_line, universal_stats, pos_style_stats)
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
    for s in squad:
        squad_by_pos.setdefault(s["pos"], []).append(s)
        squad_by_line.setdefault(s["line"], []).append(s)
 
    pool = []
    for lg in LEAGUE_CONFIG:
        if lg.get("base"):
            continue
        for row in league_rows[lg["name"]]:
            # FILTR MINUT: pomiń zawodników z małą próbką (zawyżone per-90).
            minutes = row.get("player_season_minutes")
            if not isinstance(minutes, (int, float)) or minutes < MIN_MINUTES:
                continue
 
            raw_pos = row.get("primary_position") or row.get("position")
            mapped = POS_TO_LINE.get(raw_pos)
            if not mapped:
                continue
            pos, line = mapped
            level = coh.quality_level(row, line, base_stats_by_line[line])
            # level_estimated: True gdy kandydat NIE ma metryk jakosciowych dla
            # swojej linii — wtedy quality_level zwrocil fallback (nie realny
            # percentyl). Front pokazuje wtedy znacznik "niepelne dane".
            _qm = coh.QUALITY_METRICS.get(line, [])
            _has_metrics = any(
                isinstance(row.get(m), (int, float)) for m in _qm
            )
            level_estimated = not _has_metrics
 
            # Koherencja: najpierw z zawodnikiem Rakowa z tej samej pozycji;
            # jeśli brak — porównaj do zawodników z tej samej LINII (szerszy kubełek).
            refs = squad_by_pos.get(pos) or squad_by_line.get(line, [])
            best_coh, best_ref = 0, None
            for s in refs:
                if not s.get("_sb"):
                    continue
                c = coh.coherence(row, s["_sb"], line, base_stats_by_line[line])
                if c > best_coh:
                    best_coh, best_ref = c, s["name"]
 
            pool.append({
                "id": f"pl-{row.get('player_id')}",
                "name": row.get("player_name") if _is_valid_name(row.get("player_name")) else "?",
                "lg": lg["name"], "pos": pos, "line": line,
                "raw": level,
                "level_estimated": level_estimated,
                "coherence": best_coh,
                "coherence_ref": best_ref,
                "age": _age(row.get("birth_date")),
                "mv": 0.0, "contract": 0,
                # Profile stylu: uniwersalny (cross-position) + dopasowany do
                # pozycji (bogatszy) — pod „w czym kandydat lepszy od naszego".
                "profile": coh.style_profile(row, universal_stats),
                "profile_pos": coh.pos_style_profile(row, line, pos_style_stats[line]),
            })
 
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
        "correlations": {},
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
 
