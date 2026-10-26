#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_team_values.py — dolicza REALNĄ wartość CAŁEGO składu każdej drużyny
Ekstraklasy z Transfermarktu i zapisuje ją do public/data.json jako
meta.team_values = { "<nazwa drużyny>": {"total": <mln €>, "n": <zaw. z ceną>,
"n_all": <wszyscy>, "src": "transfermarkt"} }.

PO CO: na zakładce „Przeciwnik"/„Porównanie" wartość liczona z próbki (~10–15
zawodników z danymi StatsBomb) jest MOCNO zaniżona. Tu bierzemy pełny skład
klubu z Transfermarktu (przez felipeall/transfermarkt-api) i sumujemy wyceny.

JAK dopasowujemy klub: id klubu na TM = id herbu, który trzymamy już w
meta.ekstra_crests (np. Raków = 9644, Wisła Kraków = 422). Iterujemy po tej
mapie: nazwa drużyny -> club_id.

BEZPIECZEŃSTWO (żeby zły/limitowany przebieg nie zepsuł danych):
  • uruchamiane PO fetch_statsbomb.py — tylko DOPISUJE meta.team_values,
    niczego innego nie rusza;
  • błąd pojedynczego klubu = pomijamy ten klub (zostaje poprzednia wartość,
    jeśli była); cały skrypt nigdy nie wyrzuca wyjątku na zewnątrz;
  • wynik MERGE'owany ze starym meta.team_values — częściowy sukces się kumuluje
    między przebiegami (jak cache Scoutastica);
  • gdy API nie zwróci nic dla ŻADNEGO klubu, zostawiamy data.json bez zmian.

Źródło TM jest nieoficjalne (web scraping przez cudze API) i bywa limitowane —
gdy publiczny egzemplarz pada, ustaw TM_API_BASE na własny (patrz transfermarkt.py).

Użycie:
  python scripts/fetch_team_values.py            # public/data.json
  python scripts/fetch_team_values.py plik.json  # inny plik (test)
"""
import json
import os
import sys

# transfermarkt.py leży obok — dołóż katalog skryptu do ścieżki importów.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = sys.argv[1] if len(sys.argv) > 1 else (
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "data.json"))


def main():
    try:
        from transfermarkt import fetch_club_market_values
    except Exception as e:  # noqa: BLE001
        print(f"[team-values] Nie mogę zaimportować transfermarkt.py ({e}). Pomijam.", file=sys.stderr)
        return 0

    try:
        data = json.load(open(OUT, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[team-values] Nie mogę wczytać {OUT} ({e}). Pomijam.", file=sys.stderr)
        return 0

    meta = data.get("meta") or {}
    crests = meta.get("ekstra_crests") or {}
    if not crests:
        print("[team-values] Brak meta.ekstra_crests (nazwa->id klubu TM). Pomijam.", file=sys.stderr)
        return 0

    existing = dict(meta.get("team_values") or {})   # MERGE: zachowaj poprzednie wartości
    ok, fail = 0, 0
    for team, cid in crests.items():
        cid = str(cid or "").strip()
        if not cid:
            continue
        try:
            vals = fetch_club_market_values(cid)   # {nazwa: mln €}
        except Exception as e:  # noqa: BLE001
            print(f"[team-values] {team} (id {cid}): błąd pobrania ({e}) — pomijam.", file=sys.stderr)
            fail += 1
            continue
        if not vals:
            print(f"[team-values] {team} (id {cid}): brak danych z TM — pomijam.", file=sys.stderr)
            fail += 1
            continue
        priced = [v for v in vals.values() if isinstance(v, (int, float)) and v > 0]
        total = round(sum(priced), 1)
        existing[team] = {"total": total, "n": len(priced), "n_all": len(vals), "src": "transfermarkt"}
        ok += 1
        print(f"[team-values] {team}: €{total}M z {len(priced)}/{len(vals)} zawodników.")

    if ok == 0:
        print(f"[team-values] Żaden klub nie zwrócił danych ({fail} prób). "
              f"Zostawiam data.json bez zmian.", file=sys.stderr)
        return 0

    meta["team_values"] = existing
    data["meta"] = meta
    # Ten sam format co fetch_statsbomb.py (indent=2), żeby diff w repo był czysty.
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[team-values] Zapisano wartości dla {ok} drużyn (pominięto {fail}) do {OUT}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — nic nie może wyciec na zewnątrz i wywalić pipeline
        print(f"[team-values] Nieoczekiwany błąd ({e}). Pomijam, pipeline leci dalej.", file=sys.stderr)
        raise SystemExit(0)
