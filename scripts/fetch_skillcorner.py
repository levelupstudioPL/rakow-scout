#!/usr/bin/env python3
# =====================================================================
# fetch_skillcorner.py — integracja z API SkillCorner dla rakow-scout.
# (nazwa pliku celowo NIE brzmi "skillcorner.py", by nie przesłonić
#  zainstalowanego pakietu `skillcorner` przy imporcie.)
#
# Dane SkillCorner uzupełniają StatsBomb o wymiar, którego tam nie ma:
# fizyka (biegi, sprinty, dystans) oraz Game Intelligence (biegi bez piłki,
# angażowanie przy piłce, opcje podań). Dobre źródło metryk "stylu gry".
#
# Uwierzytelnianie: oficjalny pakiet `skillcorner` używa HTTP Basic Auth
# (login + hasło) czytanych ze zmiennych środowiskowych:
#       SKILLCORNER_USERNAME, SKILLCORNER_PASSWORD
#
# BEZPIECZEŃSTWO — WAŻNE:
#   Poświadczenia TYLKO z ENV / sekretów repo — nigdy w kodzie, nigdy w repo,
#   nigdy w logach. Jeśli SkillCorner dał Ci "API key", zwykle wpisuje się go
#   jako HASŁO (SKILLCORNER_PASSWORD), a login konta jako SKILLCORNER_USERNAME.
#
# Tryby:
#   discover                (domyślny) pobiera competitions / competition_editions /
#                           seasons / teams dostępne dla konta → scripts/skillcorner_*.csv.
#                           Potwierdza, że auth działa, i pokazuje, co obejmuje licencja.
#   physical <edition_id> [group]   pobiera fizykę zagregowaną (domyślnie per zawodnik)
#                           dla danego competition_edition → scripts/skillcorner_physical_<id>.csv.
#
# Uruchomienie lokalnie:
#   pip install skillcorner
#   export SKILLCORNER_USERNAME="..."; export SKILLCORNER_PASSWORD="..."
#   python scripts/fetch_skillcorner.py discover
#   python scripts/fetch_skillcorner.py physical 123
#
# W chmurze: workflow .github/workflows/refresh-skillcorner.yml.
# =====================================================================
 
import os
import sys
import json
from pathlib import Path
 
HERE = Path(__file__).resolve().parent
 
 
def die(msg: str, code: int = 1):
    print(f"[BŁĄD] {msg}", file=sys.stderr)
    sys.exit(code)
 
 
def check_credentials():
    if not os.environ.get("SKILLCORNER_USERNAME") or not os.environ.get("SKILLCORNER_PASSWORD"):
        die(
            "Brak poświadczeń. Ustaw SKILLCORNER_USERNAME i SKILLCORNER_PASSWORD "
            "(lokalnie: export ...; w repo: sekrety Actions).\n"
            "Klucz API SkillCorner wpisuje się zwykle jako SKILLCORNER_PASSWORD, "
            "a login konta jako SKILLCORNER_USERNAME. Nie wpisuj ich do kodu."
        )
 
 
def make_client():
    try:
        from skillcorner.client import SkillcornerClient
    except ImportError:
        die("Brak biblioteki skillcorner. Zainstaluj: pip install skillcorner")
    check_credentials()
    # Klient sam czyta SKILLCORNER_USERNAME/PASSWORD z ENV (Basic Auth).
    return SkillcornerClient()
 
 
def to_frame(data):
    """Zamień odpowiedź API na DataFrame niezależnie od kształtu (lista / {results:[...]})."""
    import pandas as pd
    if data is None:
        return pd.DataFrame()
    if isinstance(data, dict):
        if "results" in data and isinstance(data["results"], list):
            data = data["results"]
        else:
            data = [data]
    try:
        return pd.json_normalize(data)
    except Exception:  # noqa
        return pd.DataFrame(data)
 
 
def _call(client, method_name, **kwargs):
    """Wywołaj metodę klienta z czytelnym błędem auth/uprawnień."""
    fn = getattr(client, method_name)
    try:
        return fn(**kwargs)
    except Exception as e:  # noqa
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (401, 403):
            die(
                f"{status} przy '{method_name}'. Uwierzytelnienie/uprawnienia: "
                f"sprawdź SKILLCORNER_USERNAME/PASSWORD i czy konto ma dostęp do tego zasobu. "
                f"Szczegół: {type(e).__name__}: {e}"
            )
        die(f"Błąd API przy '{method_name}': {type(e).__name__}: {e}")
 
 
# ---------------------------------------------------------------------
def discover():
    client = make_client()
    targets = [
        ("competitions", "get_competitions", {}),
        ("competition_editions", "get_competition_editions", {}),
        ("seasons", "get_seasons", {}),
        ("teams", "get_teams", {}),
    ]
    any_data = False
    for label, method, kwargs in targets:
        data = _call(client, method, **kwargs)
        df = to_frame(data)
        if len(df) == 0:
            print(f"[uwaga] {label}: brak danych / pusto.")
            continue
        any_data = True
        out = HERE / f"skillcorner_{label}.csv"
        df.to_csv(out, index=False)
        cols = ", ".join(map(str, list(df.columns)[:12]))
        print(f"[OK] {label}: {len(df)} wierszy → {out.name}  (kolumny: {cols})")
    if any_data:
        print("\nNastępny krok: wybierz competition_edition (kolumna id w "
              "skillcorner_competition_editions.csv) i uruchom:\n"
              "    python scripts/fetch_skillcorner.py physical <edition_id>")
    else:
        print("\n[uwaga] Auth zadziałało, ale konto nie zwróciło żadnych rozgrywek — "
              "być może licencja nie obejmuje danych API. Zapytaj opiekuna SkillCorner.")
 
 
# ---------------------------------------------------------------------
# Konfiguracja: 8 lig modelu Rakowa, sezon 2025/26 (SkillCorner competition_edition id).
# Etykiety = dokładnie te z data.json ("league"), żeby dane spinały się z modelem.
# UWAGA: id są specyficzne dla SEZONU — przy zmianie sezonu odpal 'discover'
# i zaktualizuj tę mapę.
EDITIONS = {
    1171: "Ekstraklasa (PL)",
    1194: "Jupiler Pro League (BE)",
    1230: "Eredivisie (NL)",
    1265: "Primeira Liga (PT)",
    1212: "2. Bundesliga (DE)",
    1189: "Superliga (DK)",
    1191: "Czech Liga (CZ)",
    1196: "Super League (CH)",
}
 
 
def _pull_physical(client, eid, group="player"):
    """Fizyka jednej edycji jako DataFrame z tagiem edycji/ligi (albo None)."""
    params = {"competition_edition": eid, "group_by": group}
    data = _call(client, "get_physical", params=params)
    df = to_frame(data)
    if len(df) == 0:
        print(f"[uwaga] Edycja {eid}: brak danych fizycznych (group_by={group}).")
        return None
    df.insert(0, "competition_edition", eid)
    df.insert(1, "league", EDITIONS.get(eid, ""))
    return df
 
 
def _maybe_combine(frames):
    """Gdy pobrano >1 ligi, zapisz też jeden plik zbiorczy z tagiem ligi."""
    if len(frames) <= 1:
        return
    import pandas as pd
    combined = pd.concat(frames, ignore_index=True)
    out = HERE / "skillcorner_physical_all.csv"
    combined.to_csv(out, index=False)
    print(f"[OK] Zbiorczo: {len(combined)} wierszy z {len(frames)} lig → {out.name}")
 
 
def physical(edition_ids, group="player"):
    client = make_client()
    frames = []
    for raw in edition_ids:
        try:
            eid = int(raw)
        except (ValueError, TypeError):
            print(f"[pomijam] '{raw}' nie jest liczbą (edition id).", file=sys.stderr)
            continue
        df = _pull_physical(client, eid, group)
        if df is None:
            continue
        out = HERE / f"skillcorner_physical_{eid}.csv"
        df.to_csv(out, index=False)
        frames.append(df)
        print(f"[OK] Fizyka {eid} ({EDITIONS.get(eid, '?')}): "
              f"{len(df)} wierszy, {len(df.columns)} kolumn → {out.name}")
    _maybe_combine(frames)
 
 
def physical_all(group="player"):
    """Pobierz fizykę wszystkich 8 lig modelu (EDITIONS) za jednym razem."""
    physical(list(EDITIONS.keys()), group)
 
 
# ---------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    mode = args[0] if args else "discover"
    if mode == "discover":
        discover()
    elif mode == "physical-all":
        physical_all()
    elif mode == "physical":
        if len(args) < 2:
            die("Podaj co najmniej jeden competition_edition id "
                "(albo użyj trybu 'physical-all').")
        physical(args[1:])
    else:
        die(f"Nieznany tryb '{mode}'. Użyj: discover | physical-all | physical <id> [id...]")
 
 
if __name__ == "__main__":
    main()
 
