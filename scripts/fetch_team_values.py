#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_team_values.py — REALNA wartość CAŁEGO składu każdej drużyny Ekstraklasy do
public/data.json jako meta.team_values = { "<drużyna>": {"total": <mln €>, "n": <zaw.>,
"src": "manual"|"transfermarkt-web"|"transfermarkt-api"} }.

ŹRÓDŁA (w tej kolejności):
  1) RĘCZNE: scripts/team_values.csv (team, club_id, value_mln, squad). Automatyczny
     scraping TM jest blokowany przez anti-bot (AWS WAF), a publiczne API felipeall bywa
     niedostępne — dlatego główną, PEWNĄ ścieżką jest ten plik wypełniany ręcznie
     (wartość zmienia się rzadko). Czytamy go NAJPIERW.
  2) Best-effort fallback dla klubów bez wpisu w CSV: strona klubu na TM, a potem
     felipeall API. Gdy oba padną — klub po prostu zostaje bez wartości (kafel spada do
     „Wartości próbki"), nic się nie psuje.

BEZPIECZEŃSTWO: uruchamiane PO fetch_statsbomb.py; tylko DOPISUJE meta.team_values
(merge ze starymi); przy zerze wyników zostawia data.json bez zmian; żaden wyjątek nie
wycieka na zewnątrz (pipeline leci dalej).

Użycie:
  python scripts/fetch_team_values.py            # public/data.json
  python scripts/fetch_team_values.py plik.json  # test
"""
import csv
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_HERE, "..", "public", "data.json")
CSV_PATH = os.path.join(_HERE, "team_values.csv")


def load_manual():
    """scripts/team_values.csv -> {team: {total, n?}} (tylko wiersze z liczbą)."""
    out = {}
    if not os.path.exists(CSV_PATH):
        return out
    try:
        with open(CSV_PATH, encoding="utf-8") as f:
            rows = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
        for r in csv.DictReader(rows):
            team = (r.get("team") or "").strip()
            raw = (r.get("value_mln") or "").strip().replace(",", ".")
            if not team or not raw:
                continue
            try:
                total = round(float(raw), 1)
            except ValueError:
                continue
            if total <= 0:
                continue
            rec = {"total": total, "src": "manual"}
            sq = (r.get("squad") or "").strip()
            if sq.isdigit():
                rec["n"] = int(sq)
            out[team] = rec
    except Exception as e:  # noqa: BLE001
        print(f"[team-values] Nie mogę odczytać {CSV_PATH} ({e}). Pomijam ręczne.", file=sys.stderr)
    return out


def main():
    try:
        import time
        from transfermarkt import fetch_club_total_value, fetch_club_market_values, TM_WEB_DELAY_S
    except Exception as e:  # noqa: BLE001
        fetch_club_total_value = fetch_club_market_values = None
        TM_WEB_DELAY_S = 0.0
        print(f"[team-values] transfermarkt.py niedostępny ({e}) — tylko ręczny CSV.", file=sys.stderr)

    try:
        data = json.load(open(OUT, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[team-values] Nie mogę wczytać {OUT} ({e}). Pomijam.", file=sys.stderr)
        return 0

    meta = data.get("meta") or {}
    crests = meta.get("ekstra_crests") or {}
    if not crests:
        print("[team-values] Brak meta.ekstra_crests. Pomijam.", file=sys.stderr)
        return 0

    manual = load_manual()
    if manual:
        print(f"[team-values] Z pliku ręcznego (team_values.csv): {len(manual)} drużyn.")

    existing = dict(meta.get("team_values") or {})   # MERGE ze starymi
    ok, fail = 0, 0
    for team, cid in crests.items():
        cid = str(cid or "").strip()
        # 1) RĘCZNE — pewne, wygrywa.
        if team in manual:
            existing[team] = manual[team]
            ok += 1
            print(f"[team-values] {team}: €{manual[team]['total']}M (ręczne).")
            continue
        if not cid or not fetch_club_total_value:
            fail += 1
            continue
        got = None
        # 2) Strona klubu TM (bywa blokowana przez WAF).
        try:
            res = fetch_club_total_value(cid)
        except Exception as e:  # noqa: BLE001
            print(f"[team-values] {team} (id {cid}): błąd strony TM ({e}).", file=sys.stderr)
            res = None
        if res and res.get("total", 0) > 0:
            got = {"total": round(float(res["total"]), 1), "src": "transfermarkt-web"}
            if res.get("squad"):
                got["n"] = int(res["squad"])
            print(f"[team-values] {team}: €{got['total']}M (strona TM).")
        else:
            # 3) Fallback felipeall API.
            try:
                vals = fetch_club_market_values(cid)
            except Exception as e:  # noqa: BLE001
                print(f"[team-values] {team} (id {cid}): fallback API błąd ({e}).", file=sys.stderr)
                vals = {}
            priced = [v for v in (vals or {}).values() if isinstance(v, (int, float)) and v > 0]
            if priced:
                got = {"total": round(sum(priced), 1), "n": len(priced), "src": "transfermarkt-api"}
                print(f"[team-values] {team}: €{got['total']}M z {len(priced)} zaw. (API).")

        if got:
            existing[team] = got
            ok += 1
        else:
            print(f"[team-values] {team} (id {cid}): brak wartości — pomijam.", file=sys.stderr)
            fail += 1
        try:
            time.sleep(TM_WEB_DELAY_S)
        except Exception:  # noqa: BLE001
            pass

    if ok == 0:
        print(f"[team-values] Żadnej wartości ({fail} prób). Zostawiam data.json bez zmian.", file=sys.stderr)
        return 0

    meta["team_values"] = existing
    data["meta"] = meta
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[team-values] Zapisano wartości dla {ok} drużyn (pominięto {fail}) do {OUT}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"[team-values] Nieoczekiwany błąd ({e}). Pomijam.", file=sys.stderr)
        raise SystemExit(0)
