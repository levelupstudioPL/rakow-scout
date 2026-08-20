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
    # Rozszerzenie puli (sezon 2025/26) — etykiety identyczne jak w LEAGUE_CONFIG.
    1215: "1. HNL (HR)",
    1173: "Super Liga (RS)",
    1207: "Liga I (RO)",
    1263: "Super League (GR)",
    1208: "1. SNL (SI)",          # Słowenia 1. SNL 2025/26
    1396: "Eliteserien (NO)",     # Norwegia Eliteserien 2026 (rok kalendarzowy)
    1227: "Bundesliga (AT)",      # Austria Bundesliga 2025/26
    1209: "Niké Liga (SK)",       # Słowacja Niké Liga 2025/26
    # (Bułgaria — brak w SkillCornerze; liga wchodzi do StatsBomb bez fizyki.)
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
    """Przebuduj plik zbiorczy _all ze WSZYSTKICH plików per-edycja na dysku (nie tylko
    z bieżącego uruchomienia). Dzięki temu dobranie pojedynczej ligi (np. Grecji) NIE
    kasuje pozostałych — a to była pułapka: wcześniej _all nadpisywało się tylko tym,
    co akurat pobrano."""
    import glob
    import pandas as pd
    files = [f for f in sorted(glob.glob(str(HERE / "skillcorner_physical_*.csv")))
             if not f.endswith("skillcorner_physical_all.csv")]
    if len(files) <= 1:
        return
    parts = []
    for f in files:
        try:
            parts.append(pd.read_csv(f))
        except Exception as e:  # noqa: BLE001
            print(f"[uwaga] pomijam {f}: {e}", file=sys.stderr)
    if not parts:
        return
    combined = pd.concat(parts, ignore_index=True)
    out = HERE / "skillcorner_physical_all.csv"
    combined.to_csv(out, index=False)
    nlig = combined["league"].nunique() if "league" in combined.columns else len(files)
    print(f"[OK] Zbiorczo (z {len(files)} plików per-edycja, {nlig} lig): "
          f"{len(combined)} wierszy → {out.name}")
 
 
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
# GAME INTELLIGENCE — agregaty sezonowe (styl gry, drugi wymiar obok fizyki).
# Każdy endpoint to osobna rodzina metryk. Zapis: skillcorner_gi_<key>_<eid>.csv
# + zbiorczy skillcorner_gi_<key>_all.csv (z tagiem ligi) do spięcia z modelem.
GI_ENDPOINTS = {
    "off_ball_runs":       "get_metrics_gi_ip_off_ball_runs",       # biegi bez piłki
    "passes":              "get_metrics_gi_ip_passes",              # podania (GI)
    "passing_options":     "get_metrics_gi_ip_passing_options",     # opcje podań
    "possessions":         "get_metrics_gi_ip_player_possessions",  # posiadanie
    "on_ball_engagements": "get_metrics_gi_oop_on_ball_engagements", # angażowanie (bez piłki u rywala)
}
 
 
def _pull_gi(client, method, eid, group="player"):
    """Jeden endpoint GI dla jednej edycji. Błąd auth = stop; inny błąd = pomiń."""
    fn = getattr(client, method, None)
    if fn is None:
        print(f"[uwaga] Klient nie ma metody {method} — pomijam.", file=sys.stderr)
        return None
    try:
        data = fn(params={"competition_edition": eid, "group_by": group})
    except Exception as e:  # noqa
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (401, 403):
            die(f"{status} przy {method}. Sprawdź SKILLCORNER_USERNAME/PASSWORD "
                f"i czy konto ma dostęp do Game Intelligence.")
        print(f"[uwaga] {method} edycja {eid}: {type(e).__name__}: {e}", file=sys.stderr)
        return None
    df = to_frame(data)
    if len(df) == 0:
        return None
    df.insert(0, "competition_edition", eid)
    df.insert(1, "league", EDITIONS.get(eid, ""))
    return df
 
 
def gi(edition_ids, group="player"):
    client = make_client()
    eids = []
    for raw in edition_ids:
        try:
            eids.append(int(raw))
        except (ValueError, TypeError):
            print(f"[pomijam] '{raw}' nie jest liczbą (edition id).", file=sys.stderr)
    for key, method in GI_ENDPOINTS.items():
        frames = []
        for eid in eids:
            df = _pull_gi(client, method, eid, group)
            if df is None:
                print(f"[uwaga] GI {key} edycja {eid}: brak danych/pominięto.")
                continue
            out = HERE / f"skillcorner_gi_{key}_{eid}.csv"
            df.to_csv(out, index=False)
            frames.append(df)
            print(f"[OK] GI {key} {eid} ({EDITIONS.get(eid, '?')}): "
                  f"{len(df)} wierszy, {len(df.columns)} kolumn → {out.name}")
        # Przebuduj _all z WSZYSTKICH plików per-edycja tego endpointu na dysku
        # (nie tylko z bieżącego uruchomienia) — dobranie ligi nie kasuje reszty.
        import glob as _glob
        gfiles = [f for f in sorted(_glob.glob(str(HERE / f"skillcorner_gi_{key}_*.csv")))
                  if not f.endswith(f"skillcorner_gi_{key}_all.csv")]
        if len(gfiles) > 1:
            import pandas as pd
            gparts = []
            for f in gfiles:
                try:
                    gparts.append(pd.read_csv(f))
                except Exception as e:  # noqa: BLE001
                    print(f"[uwaga] pomijam {f}: {e}", file=sys.stderr)
            if gparts:
                comb = pd.concat(gparts, ignore_index=True)
                out = HERE / f"skillcorner_gi_{key}_all.csv"
                comb.to_csv(out, index=False)
                print(f"[OK] GI {key} zbiorczo (z {len(gfiles)} edycji): {len(comb)} wierszy → {out.name}")
 
 
def gi_all(group="player"):
    """Pobierz Game Intelligence dla wszystkich 8 lig modelu (EDITIONS)."""
    gi(list(EDITIONS.keys()), group)
 
 
# ---------------------------------------------------------------------
# ---------------------------------------------------------------------
# OFF-BALL RUN TYPES (In-Possession) — NAZWANE typy biegów bez piłki.
# Zagregowany GI (get_metrics_gi_ip_off_ball_runs) NIE rozbija na typy
# (potwierdzone sondą: group_by nie przyjmuje run_type). Rozbicie jest w
# endpokoncie get_in_possession_off_ball_runs, gdzie run_type to FILTR.
# Robimy po jednym wywołaniu na typ i sklejamy w szeroką tabelę:
#   1 wiersz / zawodnik, kolumna runtype_<typ> = count_runs_per_match tego typu.
# To jest "kategoryzacja biegów" z listy KPI Igora → nowa warstwa stylu koherencji.
RUN_TYPES = [
    "run_in_behind", "cross_receiver_run", "overlap_run", "underlap_run",
    "coming_short_run", "pulling_half_space_run", "run_ahead_of_the_ball",
    "pulling_wide_run", "support_run", "dropping_off_run",
]
RUNTYPE_METRIC = "count_runs_per_match"   # metryka na typ (wolumen biegów danego typu / mecz)
 
 
_RUNTYPE_DIAG = {"done": False}   # jednorazowa diagnostyka kolumn
 
 
def _sc_get_runs(client, params, tries=4):
    """Wywołanie in_possession_off_ball_runs z retry na 5xx (CloudFront 502 bywa
    przejściowy przy wielu zapytaniach). 401/403 = twardy stop."""
    import time
    last = None
    for i in range(tries):
        try:
            return client.get_in_possession_off_ball_runs(params=params)
        except Exception as e:  # noqa: BLE001
            status = getattr(getattr(e, "response", None), "status_code", None)
            # HTTPStatusError z fitrequest bywa tuplą (status, body, ...) w e.args
            if status is None and e.args and isinstance(e.args[0], int):
                status = e.args[0]
            if status in (401, 403):
                die(f"{status} przy get_in_possession_off_ball_runs. "
                    f"Sprawdź SKILLCORNER_USERNAME/PASSWORD i dostęp do In-Possession Off-Ball Runs.")
            last = e
            if status and 500 <= status < 600:
                time.sleep(1.5 * (i + 1))   # backoff na błąd serwera
                continue
            raise
    if last:
        raise last
 
 
def _pick(cols, *cands):
    """Pierwsza pasująca kolumna z listy kandydatów (dokładna albo po fragmencie)."""
    for c in cands:
        if c in cols:
            return c
    for c in cols:
        lc = c.lower()
        if any(k in lc for k in cands):
            return c
    return None
 
 
def _pull_runtypes(client, eid, group="player"):
    """Szeroka tabela typów biegów dla jednej edycji (albo None). Odporna na
    różnice kształtu odpowiedzi (player_id vs player.id, nazwa kolumny metryki)."""
    import time
    base = None
    for rt in RUN_TYPES:
        try:
            data = _sc_get_runs(client, {"competition_edition": eid, "group_by": group, "run_type": rt})
        except Exception as e:  # noqa: BLE001
            print(f"[uwaga] runtype {rt} edycja {eid}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        df = to_frame(data)
        # DIAGNOSTYKA (raz): pokaż realny kształt odpowiedzi filtrowanej po run_type.
        if not _RUNTYPE_DIAG["done"] and len(df):
            _RUNTYPE_DIAG["done"] = True
            print(f"[diag] in_possession(run_type={rt}, ed={eid}): {len(df)} wierszy, "
                  f"kolumny: {list(df.columns)}", file=sys.stderr)
        if len(df) == 0:
            continue
        pid_col = _pick(df.columns, "player_id", "player.id", "id")
        met_col = _pick(df.columns, "count_runs_per_match", "count_runs", "runs_per_match",
                        "count_runs_in_sample")
        if pid_col is None or met_col is None:
            print(f"[uwaga] runtype {rt} edycja {eid}: brak player_id/metryki w kolumnach "
                  f"{list(df.columns)[:12]} — pomijam.", file=sys.stderr)
            time.sleep(0.3)
            continue
        name_col = _pick(df.columns, "player_name", "player.name", "name")
        short_col = _pick(df.columns, "short_name", "player_short_name", "player.short_name")
        keep = {pid_col: "player_id", met_col: f"runtype_{rt}"}
        if name_col:
            keep[name_col] = "player_name"
        if short_col:
            keep[short_col] = "player_short_name"
        sub = df[list(keep)].rename(columns=keep)
        if base is None:
            base = sub
        else:
            base = base.merge(sub[["player_id", f"runtype_{rt}"]], on="player_id", how="outer")
        time.sleep(0.3)   # łagodnie dla API (unikamy 502)
    if base is None or len(base) == 0:
        return None
    base.insert(0, "competition_edition", eid)
    base.insert(1, "league", EDITIONS.get(eid, ""))
    return base
 
 
def runtypes(edition_ids, group="player"):
    client = make_client()
    frames = []
    for raw in edition_ids:
        try:
            eid = int(raw)
        except (ValueError, TypeError):
            print(f"[pomijam] '{raw}' nie jest liczbą (edition id).", file=sys.stderr)
            continue
        df = _pull_runtypes(client, eid, group)
        if df is None:
            print(f"[uwaga] Typy biegów edycja {eid}: brak danych/pominięto.")
            continue
        out = HERE / f"skillcorner_runtypes_{eid}.csv"
        df.to_csv(out, index=False)
        frames.append(df)
        ncols = len([c for c in df.columns if c.startswith("runtype_")])
        print(f"[OK] Typy biegów {eid} ({EDITIONS.get(eid, '?')}): "
              f"{len(df)} zawodników, {ncols} typów → {out.name}")
    # Zbiorczy _all z WSZYSTKICH plików per-edycja (dobranie ligi nie kasuje reszty).
    import glob as _glob
    rfiles = [f for f in sorted(_glob.glob(str(HERE / "skillcorner_runtypes_*.csv")))
              if not f.endswith("skillcorner_runtypes_all.csv")]
    if len(rfiles) > 1:
        import pandas as pd
        parts = []
        for f in rfiles:
            try:
                parts.append(pd.read_csv(f))
            except Exception as e:  # noqa: BLE001
                print(f"[uwaga] pomijam {f}: {e}", file=sys.stderr)
        if parts:
            comb = pd.concat(parts, ignore_index=True)
            out = HERE / "skillcorner_runtypes_all.csv"
            comb.to_csv(out, index=False)
            print(f"[OK] Typy biegów zbiorczo (z {len(rfiles)} edycji): "
                  f"{len(comb)} wierszy → {out.name}")
 
 
def runtypes_all(group="player"):
    """Typy biegów dla wszystkich lig modelu (EDITIONS)."""
    runtypes(list(EDITIONS.keys()), group)
 
 
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
    elif mode == "gi-all":
        gi_all()
    elif mode == "gi":
        if len(args) < 2:
            die("Podaj co najmniej jeden competition_edition id (albo użyj 'gi-all').")
        gi(args[1:])
    elif mode == "runtypes-all":
        runtypes_all()
    elif mode == "runtypes":
        if len(args) < 2:
            die("Podaj co najmniej jeden competition_edition id (albo użyj 'runtypes-all').")
        runtypes(args[1:])
    else:
        die(f"Nieznany tryb '{mode}'. Użyj: discover | physical-all | physical <id> [...] "
            f"| gi-all | gi <id> [...] | runtypes-all | runtypes <id> [...]")
 
 
if __name__ == "__main__":
    main()
 
 
