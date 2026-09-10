#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archiwizacja wycen rynkowych w czasie — do modułu „Monitoring wartości".

Czyta zbudowany public/data.json i dopisuje snapshot {id: wartość_mln_eur}
do public/value_history.json (jedna pozycja na dzień). NIE dotyka modelu RC —
zapisuje wyłącznie pole `mv`, które już jest w danych (Transfermarkt/Scoutastic).

Uruchamiać PO wygenerowaniu data.json (na końcu pipeline / w GitHub Action).
Idempotentny w obrębie dnia: drugi zapis tego samego dnia nadpisuje wpis z tą datą.
Trzyma ostatnie MAX_SNAPSHOTS migawek (starsze przycina), żeby plik był lekki.

Użycie:
    python scripts/archive_values.py            # domyślne ścieżki w public/
    python scripts/archive_values.py <data.json> <value_history.json>
"""
import json
import os
import sys
from datetime import date, datetime, timezone

MAX_SNAPSHOTS = 30  # ~pół roku przy tygodniowym odświeżaniu


def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def build_snapshot(data):
    """Zwraca {id: mv} dla wszystkich zawodników z dodatnią wyceną (squad + pula)."""
    values = {}
    for bucket in ("squad", "pool"):
        for p in data.get(bucket, []) or []:
            pid = p.get("id")
            mv = p.get("mv")
            try:
                mv = float(mv)
            except (TypeError, ValueError):
                continue
            if pid and mv and mv > 0:
                values[pid] = round(mv, 3)
    return values


def main():
    args = sys.argv[1:]
    data_path = args[0] if len(args) > 0 else os.path.join("public", "data.json")
    hist_path = args[1] if len(args) > 1 else os.path.join("public", "value_history.json")

    data = _load(data_path, None)
    if data is None:
        print(f"[archive_values] Brak lub błędny {data_path} — pomijam.", file=sys.stderr)
        return 1

    snapshot = build_snapshot(data)
    if not snapshot:
        print("[archive_values] Brak wycen (mv) w danych — nic nie zapisuję.", file=sys.stderr)
        return 0

    today = date.today().isoformat()
    hist = _load(hist_path, {"snapshots": []})
    if not isinstance(hist, dict) or "snapshots" not in hist:
        hist = {"snapshots": []}

    # Nadpisz wpis z dzisiejszą datą (idempotencja) albo dołóż nowy.
    snaps = [s for s in hist["snapshots"] if s.get("date") != today]
    snaps.append({"date": today, "values": snapshot})
    snaps.sort(key=lambda s: s.get("date", ""))
    snaps = snaps[-MAX_SNAPSHOTS:]

    hist["snapshots"] = snaps
    hist["updated"] = datetime.now(timezone.utc).isoformat()

    os.makedirs(os.path.dirname(hist_path) or ".", exist_ok=True)
    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, separators=(",", ":"))

    print(f"[archive_values] Zapisano snapshot {today}: {len(snapshot)} wycen, "
          f"{len(snaps)} migawek w historii ({hist_path}).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
