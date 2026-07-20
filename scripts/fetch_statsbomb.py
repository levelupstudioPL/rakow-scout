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
    {"name": "Jupiler / inne — dodaj wg potrzeb", "competition_id": None, "season_id": None, "base": False},
]
# Uwaga: ostatni wpis to placeholder-przykład; usuń go albo uzupełnij realnym ID.
LEAGUE_CONFIG = [lg for lg in LEAGUE_CONFIG if lg["competition_id"] is not None]
 
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
 
    # --- Handicapy lig (bez zmian, realna metoda) ---
    leagues = []
    for lg in LEAGUE_CONFIG:
        rows = league_rows[lg["name"]]
        handicap = league_handicap(rows, base_rows)
        leagues.append({"lg": lg["name"], "base": lg.get("base", False), **handicap})
 
    # --- Skład Rakowa: wczytywany ze stałego pliku public/squad.json ---
    # (Wcześniej pobierany ze scrapera Transfermarktu, który bywa niedostępny
    #  i wywalał całą aplikację. Teraz skład jest trwały; Transfermarkt służy
    #  wyłącznie do opcjonalnych wartości rynkowych kandydatów.)
    # Format squad.json: lista {"id","name","pos","line","rc"}.
    # Analityk edytuje ten plik (docelowo przez interfejs w aplikacji).
    squad_path = OUT.parent / "squad.json"
    try:
        static_squad = json.loads(squad_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[BŁĄD] Nie wczytano {squad_path}: {e}", file=sys.stderr)
        static_squad = []
 
    base_by_name = _name_index(base_rows)
 
    squad = []
    rc_from_model = 0
    for pl in static_squad:
        name = pl.get("name")
        pos = pl.get("pos")
        line = pl.get("line")
        if not name or not pos or not line:
            print(f"[uwaga] Pomijam niekompletny wpis skladu: {pl}", file=sys.stderr)
            continue
        # Dociagnij wiersz metryk StatsBomb po nazwisku (potrzebny do koherencji).
        sb_row = base_by_name.get(_norm(name))
        # RC — MODEL PIERWSZY:
        # Poziom liczymy z realnych metryk StatsBomb (coh.quality_level, metoda
        # percentylowa vs Ekstraklasa). To jest "model RC" — ta sama metoda, którą
        # liczona jest pula kandydatów, więc skład i kandydaci są porównywalni.
        #
        # squad.json/"rc" służy już TYLKO jako awaryjny fallback: gdy zawodnik nie
        # ma dopasowanego wiersza w StatsBomb (np. inny zapis nazwiska) albo metryki
        # są puste (typowo bramkarze bez pól gsaa/save_ratio). Wpisana liczba NIE
        # nadpisuje modelu, gdy dane są dostępne.
        #
        # UWAGA (uczciwość modelu): dobór metryk per pozycja (QUALITY_METRICS w
        # coherence.py) to rozsądne domyślne, ale wciąż ZAŁOŻENIE — ktoś znający
        # Ekstraklasę i te ligi powinien je kiedyś zweryfikować. Poziomy traktować
        # jako orientacyjne, nie ostateczne.
        model_rc = coh.quality_level(sb_row, line, base_stats_by_line[line]) if sb_row else None
        if isinstance(model_rc, (int, float)):
            rc = model_rc
            rc_source = "model"
            rc_from_model += 1
        else:
            fallback = pl.get("rc")
            rc = fallback if isinstance(fallback, (int, float)) else 72
            rc_source = "squad.json" if isinstance(fallback, (int, float)) else "domyslne(72)"
            print(f"[RC] {name}: brak metryk StatsBomb — uzyto {rc_source} (rc={rc})",
                  file=sys.stderr)
        squad.append({
            "id": pl.get("id") or f"rk-{_slug(name)}", "name": name,
            "pos": pos, "line": line, "rc": rc, "real": True,
            # rc_estimated = True gdy RC NIE pochodzi z modelu (brak metryk
            # StatsBomb -> fallback ze squad.json lub domyslne 72). Front pokazuje
            # wtedy flage "niepelne dane", zeby nie mylic braku danych z ocena.
            "rc_estimated": (rc_source != "model"),
            "_sb": sb_row,
        })
 
    if not squad:
        print("[uwaga] Sklad Rakowa jest pusty - sprawdz public/squad.json.", file=sys.stderr)
    else:
        print(f"RC skladu: {rc_from_model}/{len(squad)} policzone z modelu "
              f"(reszta = fallback ze squad.json / domyslne).")
 
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
                "lg": lg["name"], "pos": pos,
                "raw": level,
                "level_estimated": level_estimated,
                "coherence": best_coh,
                "coherence_ref": best_ref,
                "age": _age(row.get("birth_date")),
                "mv": 0.0, "contract": 0,
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
    values_by_name = _load_values_csv(Path(__file__).resolve().parent / "player_values.csv")
    matched = 0
    for c in pool:
        v = values_by_name.get(_norm_ascii(c["name"]))
        if v:
            c["mv"] = v["mv"]           # wartość w mln EUR
            if v.get("age"):
                c["age"] = v["age"]
            if v.get("contract"):
                c["contract"] = v["contract"]
            matched += 1
    print(f"Wartości rynkowe: dopasowano {matched}/{len(pool)} kandydatów "
          f"z pliku player_values.csv")
 
    return {
        "meta": {
            "source": "statsbomb+kaggle-values",
            "generated": __import__("datetime").date.today().isoformat(),
            "note": ("Poziom = percentyl metryk vs Ekstraklasa. Koherencja = podobieństwo "
                     "profilu gry do zawodnika Rakowa (position-specific similarity). "
                     "Wartość transferowa (Transfermarkt) dociągana tylko dla kandydatów "
                     "pasujących wg modelu (koherencja >= 70%). Dane: StatsBomb + Transfermarkt."),
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
                # Gdy nazwisko powtarza się w pliku, bierz wyższą wartość
                # (zwykle to ten "właściwy", aktywny zawodnik).
                prev = result.get(key)
                if prev and prev["mv"] >= mv_mln:
                    continue
                result[key] = {"mv": mv_mln, "age": age, "contract": contract}
    except FileNotFoundError:
        print(f"[uwaga] Nie znaleziono {path} — kandydaci zostaną bez wartości "
              f"rynkowych (mv=0). Wgraj scripts/player_values.csv.", file=sys.stderr)
    except Exception as e:
        print(f"[uwaga] Błąd czytania {path}: {e} — pomijam wartości.", file=sys.stderr)
    return result
 
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
    print(f"Zapisano: {OUT}")
    print(f"  skład: {len(dataset['squad'])}, ligi: {len(dataset['leagues'])}, pula: {len(dataset['pool'])}")
 
 
if __name__ == "__main__":
    main()
 
