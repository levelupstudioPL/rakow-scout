#!/usr/bin/env python3
"""
Pobiera AKTUALNY plik wartości rynkowych z Kaggle (dataset
davidcariboo/player-scores, plik players.csv) i buduje z niego
scripts/player_values.csv w formacie, którego używa fetch_statsbomb.py.
 
Dzięki temu wartości odświeżają się z jednego, legalnego źródła (Kaggle),
zamiast żyć w przestarzałym, ręcznie wgranym pliku.
 
WYMAGA sekretów repo (Settings → Secrets and variables → Actions):
    KAGGLE_USERNAME, KAGGLE_KEY
(token z kaggle.com → Account → „Create New API Token" → kaggle.json).
 
players.csv (davidcariboo) ma kolumny m.in.:
    name, date_of_birth, sub_position, market_value_in_eur,
    contract_expiration_date, current_club_name
— czyli wszystko, czego potrzebujemy, bez łączenia tabel.
"""
import csv
import os
import subprocess
import sys
import unicodedata
from pathlib import Path
 
DATASET = "davidcariboo/player-scores"
SRC_FILE = "players.csv"
OUT = Path(__file__).resolve().parent / "player_values.csv"
 
 
def _norm_ascii(name):
    if not isinstance(name, str):
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.strip().lower().split())
 
 
def _download(tmp_dir):
    """Pobiera pojedynczy players.csv z datasetu (bez ważącego zipa całości)."""
    if not (os.getenv("KAGGLE_USERNAME") and os.getenv("KAGGLE_KEY")):
        print("[BŁĄD] Brak sekretów KAGGLE_USERNAME / KAGGLE_KEY. "
              "Dodaj token z kaggle.json w ustawieniach repo.", file=sys.stderr)
        sys.exit(2)
    cmd = ["kaggle", "datasets", "download", "-d", DATASET,
           "-f", SRC_FILE, "-p", str(tmp_dir), "--unzip"]
    print("Pobieram players.csv z Kaggle…")
    subprocess.run(cmd, check=True)
    p = Path(tmp_dir) / SRC_FILE
    if not p.exists():                       # czasem zostaje jako .zip
        import zipfile
        z = Path(tmp_dir) / (SRC_FILE + ".zip")
        if z.exists():
            with zipfile.ZipFile(z) as zf:
                zf.extractall(tmp_dir)
    if not p.exists():
        print(f"[BŁĄD] Nie znaleziono {SRC_FILE} po pobraniu.", file=sys.stderr)
        sys.exit(1)
    return p
 
 
def _year(s):
    s = (s or "").strip()
    return s[:4] if len(s) >= 4 and s[:4].isdigit() else ""
 
 
def main():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        src = _download(tmp)
        rows_in = out = skipped = 0
        with open(src, encoding="utf-8") as f, open(OUT, "w", encoding="utf-8", newline="") as g:
            reader = csv.DictReader(f)
            writer = csv.writer(g)
            writer.writerow(["name", "name_norm", "mv_eur", "dob", "contract", "sub_position", "club"])
            for r in reader:
                rows_in += 1
                name = (r.get("name") or "").strip()
                mv = (r.get("market_value_in_eur") or "").strip()
                if not name or not mv or mv in ("0", "0.0"):
                    skipped += 1
                    continue                 # bez nazwy/wartości nic nie wnosi
                writer.writerow([
                    name, _norm_ascii(name), mv,
                    (r.get("date_of_birth") or "")[:10],
                    _year(r.get("contract_expiration_date")),
                    r.get("sub_position") or "",
                    r.get("current_club_name") or "",
                ])
                out += 1
        print(f"Gotowe: {out} zawodników z wyceną → {OUT} "
              f"(wczytano {rows_in} wierszy, pominięto {skipped} bez nazwy/wartości)")
 
 
if __name__ == "__main__":
    main()
 
