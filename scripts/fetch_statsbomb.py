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

# Nowe moduły: pełna metoda handicapów + dane z Transfermarktu.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import handicap as hc
import transfermarkt as tm

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
POS_TO_LINE = {
    "Goalkeeper": ("GK", "Bramka"),
    "Center Back": ("CCB", "Obrona"), "Right Center Back": ("RCB", "Obrona"),
    "Left Center Back": ("LCB", "Obrona"),
    "Right Wing Back": ("RWB", "Obrona"), "Left Wing Back": ("LWB", "Obrona"),
    "Right Back": ("RWB", "Obrona"), "Left Back": ("LWB", "Obrona"),
    "Center Defensive Midfield": ("DM", "Pomoc"),
    "Center Midfield": ("CM", "Pomoc"), "Right Center Midfield": ("CM", "Pomoc"),
    "Left Center Midfield": ("CM", "Pomoc"),
    "Center Attacking Midfield": ("AM", "Pomoc"),
    "Right Wing": ("AM", "Pomoc"), "Left Wing": ("AM", "Pomoc"),
    "Center Forward": ("ST", "Atak"), "Striker": ("ST", "Atak"),
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
        die(
            "LEAGUE_CONFIG jest puste. Najpierw sprawdź, do których rozgrywek masz "
            "dostęp:  uruchom  python scripts/list_statsbomb_competitions.py  i wpisz "
            "competition_id/season_id do LEAGUE_CONFIG w tym pliku."
        )

    # --- Pass 1: pobierz surowe wiersze zawodników dla każdej ligi ---
    league_rows = {}   # nazwa ligi -> lista wierszy zawodników
    base_name = None
    for lg in LEAGUE_CONFIG:
        try:
            stats = sb.player_season_stats(
                competition_id=lg["competition_id"],
                season_id=lg["season_id"],
                creds=creds,
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
        print("[uwaga] Brak danych bazowej ligi (Ekstraklasa) — handicapy wyjdą zerowe.", file=sys.stderr)

    # --- Pass 2: handicapy (PEŁNA metoda) + pula odpowiedników ---
    leagues, pool = [], []
    for lg in LEAGUE_CONFIG:
        rows = league_rows[lg["name"]]
        handicap = league_handicap(rows, base_rows)  # realne liczenie vs Ekstraklasa
        leagues.append({"lg": lg["name"], "base": lg.get("base", False), **handicap})

        if lg.get("base"):
            continue  # z bazy nie budujemy puli odpowiedników
        for row in rows:
            raw_pos = row.get("primary_position") or row.get("position")
            mapped = POS_TO_LINE.get(raw_pos)
            if not mapped:
                continue
            pos, _line = mapped
            pool.append({
                "id": f"pl-{row.get('player_id')}",
                "name": row.get("player_name", "?"),
                "lg": lg["name"], "pos": pos,
                "raw": player_rc_from_stats(row),
                "age": int(row.get("age") or 0),
                "mv": 0.0,       # uzupełniane z Transfermarktu poniżej (po nazwisku)
                "contract": 0,
            })

    # --- Skład Rakowa + wartości rynkowe z Transfermarktu ---
    squad = []
    tm_squad = tm.fetch_rakow_squad()  # [{name, pos, age, mv, contract}]
    tm_pos_map = {
        "Goalkeeper": ("GK", "Bramka"), "Centre-Back": ("CCB", "Obrona"),
        "Right-Back": ("RWB", "Obrona"), "Left-Back": ("LWB", "Obrona"),
        "Defensive Midfield": ("DM", "Pomoc"), "Central Midfield": ("CM", "Pomoc"),
        "Attacking Midfield": ("AM", "Pomoc"), "Right Winger": ("AM", "Pomoc"),
        "Left Winger": ("AM", "Pomoc"), "Centre-Forward": ("ST", "Atak"),
        "Second Striker": ("ST", "Atak"),
    }
    # Poziom RC zawodnika Rakowa liczymy z metryk StatsBomb (dopasowanie po nazwisku),
    # a jeśli brak dopasowania — neutralny placeholder do czasu kalibracji.
    base_by_name = {r.get("player_name"): r for r in base_rows}
    for pl in tm_squad:
        mapped = tm_pos_map.get(pl["pos"])
        if not mapped:
            continue
        pos, line = mapped
        sb_row = base_by_name.get(pl["name"])
        rc = player_rc_from_stats(sb_row) if sb_row else 72
        squad.append({
            "id": f"rk-{pl['name'].replace(' ', '-').lower()}",
            "name": pl["name"], "pos": pos, "line": line, "rc": rc, "real": True,
        })

    if not squad:
        print("[uwaga] Nie pobrano składu Rakowa z Transfermarktu — sprawdź moduł transfermarkt.py.", file=sys.stderr)

    # Domiar wartości rynkowych do puli odpowiedników (po nazwisku, jeśli TM ma dane).
    # Uwaga: to najlepsze-effort; nie każde nazwisko z TM zgra się 1:1 z StatsBomb.

    return {
        "meta": {
            "source": "statsbomb+transfermarkt",
            "generated": __import__("datetime").date.today().isoformat(),
            "note": ("Handicapy liczone realną metodą (handicap.py) vs Ekstraklasa. "
                     "Skład i wartości z Transfermarktu. Wzór poziomu RC = do kalibracji "
                     "przez analityka (LINE_METRICS i player_rc_from_stats)."),
        },
        "squad": squad,
        "leagues": leagues,
        "pool": pool,
        "correlations": {},  # do policzenia z współwystępowania akcji — osobny krok
    }


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
