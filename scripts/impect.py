#!/usr/bin/env python3
# =====================================================================
# impect.py — integracja z Impect Customer API (v5) dla rakow-scout.
#
# Uwierzytelnianie: OAuth2 password grant (client_id=api), obsługiwane
# przez oficjalną bibliotekę impectPy (>=2.7.1, wspiera API V5).
#
# BEZPIECZEŃSTWO — WAŻNE:
#   Poświadczenia czytane są WYŁĄCZNIE ze zmiennych środowiskowych:
#       IMPECT_USERNAME, IMPECT_PASSWORD
#   Ustaw je jako sekrety repo (Settings → Secrets → Actions) — nigdy
#   w kodzie, nigdy w repo, nigdy w logach. Token dostępowy NIE jest
#   nigdzie zapisywany na dysk ani commitowany.
#
# Token jest ważny 24h — w obrębie jednego uruchomienia pobierany jest
# RAZ i reużywany do wszystkich zapytań (zgodnie z zaleceniem Impect).
# Limit 8 req/s (429) i backoff obsługuje impectPy.
#
# Tryby (argument w wierszu poleceń):
#   discover                (domyślny) pobiera listę iteracji (ligi/sezony)
#                           dostępnych dla konta → scripts/impect_iterations.csv
#                           + .json. Odpowiada na pytanie: jakie ligi obejmuje
#                           licencja i czy Customer API jest w ogóle aktywne.
#   players <id> [<id>...]  dla podanych iterationId pobiera średnie KPI
#                           zawodników (getPlayerIterationAverages) →
#                           scripts/impect_players_<id>.csv.
#
# Uruchomienie lokalnie:
#   pip install impectPy
#   export IMPECT_USERNAME="..."; export IMPECT_PASSWORD="..."
#   python scripts/impect.py discover
#   python scripts/impect.py players 518 519
#
# W chmurze: workflow .github/workflows/refresh-impect.yml (jednym kliknięciem).
# =====================================================================
 
import os
import sys
import json
from pathlib import Path
 
HERE = Path(__file__).resolve().parent
 
 
# ---------------------------------------------------------------------
# Poświadczenia — tylko z ENV. Bez fallbacku do stałych w kodzie.
# ---------------------------------------------------------------------
def get_credentials():
    user = os.environ.get("IMPECT_USERNAME")
    pwd = os.environ.get("IMPECT_PASSWORD")
    if not user or not pwd:
        die(
            "Brak poświadczeń. Ustaw zmienne środowiskowe IMPECT_USERNAME i "
            "IMPECT_PASSWORD (lokalnie: export ...; w repo: sekrety Actions).\n"
            "Nie wpisuj hasła do kodu ani nie wklejaj tokenu — skrypt pobiera "
            "token sam, na podstawie loginu i hasła z ENV."
        )
    return user, pwd
 
 
def die(msg: str, code: int = 1):
    print(f"[BŁĄD] {msg}", file=sys.stderr)
    sys.exit(code)
 
 
def load_impect():
    """Import impectPy z czytelnym komunikatem, gdy biblioteki brak."""
    try:
        import impectPy as ip  # noqa
        from impectPy.helpers import ForbiddenError, HTTPError  # noqa
        return ip, ForbiddenError, HTTPError
    except ImportError:
        die("Brak biblioteki impectPy. Zainstaluj: pip install impectPy")
 
 
# ---------------------------------------------------------------------
# Logowanie (jeden token na całe uruchomienie)
# ---------------------------------------------------------------------
def make_client():
    """Zwraca (klient Impect, token). Token pobierany raz i reużywany."""
    ip, ForbiddenError, HTTPError = load_impect()
    user, pwd = get_credentials()
 
    client = ip.Impect()
    try:
        client.login(user, pwd)  # POST password grant (client_id=api), ustawia Bearer
    except Exception as e:  # noqa
        die(
            "Uwierzytelnianie nie powiodło się. Sprawdź login/hasło w sekretach "
            f"(nie wklejaj ich tutaj). Szczegół: {type(e).__name__}: {e}"
        )
    print(f"[OK] Zalogowano do Impect jako {user}. Token ważny ~24h (reużywany w tym biegu).")
    return client, ForbiddenError, HTTPError
 
 
# ---------------------------------------------------------------------
# DISCOVER — jakie ligi/sezony (iteracje) są w licencji?
# ---------------------------------------------------------------------
def discover():
    client, ForbiddenError, HTTPError = make_client()
    try:
        iterations = client.getIterations()
    except ForbiddenError:
        die(
            "403 Forbidden na /v5/customerapi/iterations. Uwierzytelnienie działa, "
            "ale konto NIE ma roli do Customer API. To kwestia licencji/uprawnień, "
            "nie kodu.\nCo zrobić: zapytaj opiekuna Impect/Catapult, czy wasza umowa "
            "obejmuje Customer API i jaka rola jest wymagana dla tego konta."
        )
    except HTTPError as e:
        die(f"Błąd API przy pobieraniu iteracji: {e}")
 
    if iterations is None or len(iterations) == 0:
        print("[uwaga] Lista iteracji jest pusta — konto nie ma przypisanych rozgrywek.")
        return
 
    # Zapis pełny (wszystkie kolumny, w tym id-mappingi do innych źródeł)
    out_json = HERE / "impect_iterations.json"
    out_csv = HERE / "impect_iterations.csv"
    iterations.to_json(out_json, orient="records", force_ascii=False, indent=2)
    iterations.to_csv(out_csv, index=False)
 
    # Zwięzła tabela do wglądu w konsoli / logu workflow
    cols = [c for c in ["id", "competitionName", "competitionType", "season",
                        "competitionGender", "competitionCountryName"]
            if c in iterations.columns]
    view = iterations[cols] if cols else iterations
    print(f"\n[OK] Dostępnych iteracji: {len(iterations)}. "
          f"Zapisano: {out_csv.name}, {out_json.name}\n")
    try:
        print(view.to_string(index=False, max_rows=200))
    except Exception:  # noqa
        print(view.head(50))
 
    # Podpowiedź: czy widać ligi z naszego modelu
    wanted = ["Ekstraklasa", "Jupiler", "Eredivisie", "Primeira", "Bundesliga",
              "Superliga", "Czech", "Super League", "1. Liga", "Fortuna"]
    name_col = "competitionName" if "competitionName" in iterations.columns else None
    if name_col:
        hay = " | ".join(str(x) for x in iterations[name_col].tolist())
        hits = sorted({w for w in wanted if w.lower() in hay.lower()})
        print(f"\n[info] Ligi z modelu wykryte w licencji (dopasowanie zgrubne): "
              f"{', '.join(hits) if hits else 'brak oczywistych trafień'}")
    print("\nNastępny krok: wybierz iterationId interesujących lig i uruchom:\n"
          "    python scripts/impect.py players <id> [<id>...]")
 
 
# ---------------------------------------------------------------------
# PLAYERS — średnie KPI zawodników dla wskazanych iteracji
# ---------------------------------------------------------------------
def players(iteration_ids):
    client, ForbiddenError, HTTPError = make_client()
    for raw in iteration_ids:
        try:
            it = int(raw)
        except ValueError:
            print(f"[pomijam] '{raw}' nie jest liczbą (iterationId).", file=sys.stderr)
            continue
        try:
            df = client.getPlayerIterationAverages(iteration=it)
        except ForbiddenError:
            die(f"403 Forbidden dla iteracji {it}. Konto bez dostępu do tej rozgrywki "
                f"lub bez roli Customer API (patrz komunikat z 'discover').")
        except HTTPError as e:
            print(f"[błąd] iteracja {it}: {e}", file=sys.stderr)
            continue
 
        if df is None or len(df) == 0:
            print(f"[uwaga] Iteracja {it}: brak danych zawodników.")
            continue
 
        out_csv = HERE / f"impect_players_{it}.csv"
        df.to_csv(out_csv, index=False)
        n_cols = len(df.columns)
        print(f"[OK] Iteracja {it}: {len(df)} wierszy (zawodnik×pozycja), "
              f"{n_cols} kolumn → {out_csv.name}")
        # pokaż nazwy kilku kolumn KPI, żeby zaplanować mapowanie na nasz model
        preview = [c for c in df.columns][:25]
        print(f"     Kolumny (pierwsze {len(preview)}): {', '.join(map(str, preview))}")
 
 
# ---------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    mode = args[0] if args else "discover"
    if mode == "discover":
        discover()
    elif mode == "players":
        ids = args[1:]
        if not ids:
            die("Podaj co najmniej jeden iterationId: python scripts/impect.py players <id> [...]")
        players(ids)
    else:
        die(f"Nieznany tryb '{mode}'. Użyj: discover  |  players <id> [...]")
 
 
if __name__ == "__main__":
    main()
 
