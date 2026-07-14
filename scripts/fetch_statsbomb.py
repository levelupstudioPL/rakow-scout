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
from pathlib import Path
 
# Nowe moduły: handicapy, Transfermarkt, koherencja profili.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import handicap as hc
import transfermarkt as tm
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
POS_TO_LINE = {
    "Goalkeeper": ("GK", "Bramka"),
    # Obrona środkowa
    "Center Back": ("CB", "Obrona"), "Centre Back": ("CB", "Obrona"),
    "Right Center Back": ("CB", "Obrona"), "Left Center Back": ("CB", "Obrona"),
    # Obrona boczna / wahadła
    "Right Wing Back": ("WB", "Obrona"), "Left Wing Back": ("WB", "Obrona"),
    "Right Back": ("WB", "Obrona"), "Left Back": ("WB", "Obrona"),
    "Wing Back": ("WB", "Obrona"),
    # Pomoc defensywna / centralna
    "Center Defensive Midfield": ("DM", "Pomoc"),
    "Right Defensive Midfield": ("DM", "Pomoc"), "Left Defensive Midfield": ("DM", "Pomoc"),
    "Center Midfield": ("CM", "Pomoc"), "Right Center Midfield": ("CM", "Pomoc"),
    "Left Center Midfield": ("CM", "Pomoc"),
    "Right Midfielder": ("WM", "Pomoc"), "Left Midfielder": ("WM", "Pomoc"),
    "Right Midfield": ("WM", "Pomoc"), "Left Midfield": ("WM", "Pomoc"),
    # Pomoc ofensywna / skrzydła
    "Center Attacking Midfield": ("AM", "Pomoc"),
    "Right Attacking Midfield": ("AM", "Pomoc"), "Left Attacking Midfield": ("AM", "Pomoc"),
    "Right Wing": ("W", "Pomoc"), "Left Wing": ("W", "Pomoc"),
    "Right Winger": ("W", "Pomoc"), "Left Winger": ("W", "Pomoc"),
    # Atak
    "Center Forward": ("ST", "Atak"), "Striker": ("ST", "Atak"),
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
 
    # --- Skład Rakowa: nazwiska/wartości z TM, profile metryk ze StatsBomb ---
    tm_squad = tm.fetch_rakow_squad()
    # Mapowanie pozycji Transfermarktu -> te same kubełki co model (CB/WB/DM/CM/WM/AM/W/ST).
    tm_pos_map = {
        "Goalkeeper": ("GK", "Bramka"),
        "Centre-Back": ("CB", "Obrona"), "Center-Back": ("CB", "Obrona"),
        "Right-Back": ("WB", "Obrona"), "Left-Back": ("WB", "Obrona"),
        "Defensive Midfield": ("DM", "Pomoc"), "Central Midfield": ("CM", "Pomoc"),
        "Attacking Midfield": ("AM", "Pomoc"),
        "Right Midfield": ("WM", "Pomoc"), "Left Midfield": ("WM", "Pomoc"),
        "Right Winger": ("W", "Pomoc"), "Left Winger": ("W", "Pomoc"),
        "Centre-Forward": ("ST", "Atak"), "Second Striker": ("ST", "Atak"),
    }
    base_by_name = _name_index(base_rows)
 
    squad = []
    for pl in tm_squad:
        sb_row = base_by_name.get(_norm(pl["name"]))
        # Preferuj pozycję ze StatsBomb (spójna z kandydatami); TM jako zapas.
        pos, line = None, None
        if sb_row:
            sb_pos = sb_row.get("primary_position") or sb_row.get("position")
            m = POS_TO_LINE.get(sb_pos)
            if m:
                pos, line = m
        if not pos:
            m = tm_pos_map.get(pl["pos"])
            if m:
                pos, line = m
        if not pos:
            continue  # pozycja nierozpoznana z obu źródeł
        rc = coh.quality_level(sb_row, line, base_stats_by_line[line]) if sb_row else 72
        squad.append({
            "id": f"rk-{_slug(pl['name'])}", "name": pl["name"],
            "pos": pos, "line": line, "rc": rc, "real": True,
            "_sb": sb_row,
        })
 
    if not squad:
        print("[uwaga] Nie pobrano składu Rakowa z Transfermarktu.", file=sys.stderr)
 
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
                "coherence": best_coh,
                "coherence_ref": best_ref,
                "age": _age(row.get("birth_date")),
                "mv": 0.0, "contract": 0,
            })
 
    # Usuń profile metryk ze składu przed zapisem (były tylko do liczenia)
    for s in squad:
        s.pop("_sb", None)
 
    # --- Wartości transferowe: TYLKO dla pasujących wg modelu (próg koherencji) ---
    # Model liczy koherencję dla całej puli ze StatsBomb (stabilnie). Cenę z
    # Transfermarktu dociągamy oszczędnie — jedynie dla kandydatów >= progu,
    # więc liczba zapytań jest mała (garstka, nie setki).
    COHERENCE_THRESHOLD = 70
    to_price = [c for c in pool if c.get("coherence", 0) >= COHERENCE_THRESHOLD]
    # Ogranicznik bezpieczeństwa, by nie przeciążyć publicznego TM-api.
    MAX_LOOKUPS = 40
    if len(to_price) > MAX_LOOKUPS:
        to_price = sorted(to_price, key=lambda c: c["coherence"], reverse=True)[:MAX_LOOKUPS]
 
    print(f"Dociągam wartości TM dla {len(to_price)} kandydatów (koherencja >= {COHERENCE_THRESHOLD}%)…")
    for c in to_price:
        try:
            val = tm.fetch_player_value(c["name"])
        except Exception as e:
            print(f"[TM] {c['name']}: {e}", file=sys.stderr)
            val = None
        if val:
            c["mv"] = val.get("mv", 0.0)
            if val.get("age"):
                c["age"] = val["age"]
            if val.get("contract"):
                c["contract"] = val["contract"]
 
    return {
        "meta": {
            "source": "statsbomb+transfermarkt",
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
 
 
def main():
    creds = get_credentials()
    sb = load_statsbombpy()
    print("Łączę ze StatsBomb i pobieram dane…")
    dataset = build_dataset(sb, creds)
    OUT.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Zapisano: {OUT}")
    print(f"  skład: {len(dataset['squad'])}, ligi: {len(dataset['leagues'])}, pula: {len(dataset['pool'])}")
 
 
if __name__ == "__main__":
    main()
 
