#!/usr/bin/env python3
"""
Pobiera OFICJALNE zdjęcia zawodników z własnej strony Rakowa
(https://www.rakow.com/pl/sklad) i zapisuje public/photos.json:
 
    { "Imię Nazwisko": "https://rakow-c2-cdn.stellis.one/.../<uuid>", ... }
 
To zdjęcia klubowe — Raków ma do nich prawa, więc użycie jest legalne
(w przeciwieństwie do zdjęć z Transfermarktu). Strona jest renderowana
serwerowo, więc wystarczy pobrać HTML i wyłuskać znaczniki:
 
    <img ... class="img-player " ... src="…/documents/3036269/<uuid>" alt="Imię Nazwisko">
 
Front dopasowuje te nazwiska do składu po nakładaniu się tokenów (bez ogonków),
więc drobne różnice w pisowni („Efstratios Svarnas" vs „Stratos Svarnas") nie
przeszkadzają.
 
Uruchamiane w GitHub Actions (refresh-photos.yml). Zależności: tylko biblioteka
standardowa Pythona.
"""
import html as _html
import json
import os
import re
import sys
import urllib.request
 
URL = os.environ.get("RAKOW_SQUAD_URL", "https://www.rakow.com/pl/sklad")
OUT_PATH = os.environ.get("PHOTOS_PATH", "public/photos.json")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36 RakowScout/1.0")
PORTRAIT_MARKER = "documents/3036269/"   # katalog portretów zawodników na CDN klubu
 
IMG_TAG = re.compile(r"<img\b[^>]*\bimg-player\b[^>]*>", re.IGNORECASE)
SRC_RE = re.compile(r'src\s*=\s*"([^"]+)"', re.IGNORECASE)
ALT_RE = re.compile(r'alt\s*=\s*"([^"]*)"', re.IGNORECASE)
 
 
def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        raw = r.read()
    for enc in ("utf-8", "iso-8859-2", "cp1250"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")
 
 
def main():
    try:
        page = fetch_html(URL)
    except Exception as e:  # noqa: BLE001
        print(f"[BŁĄD] Nie pobrano {URL}: {e}", file=sys.stderr)
        return 1
 
    photos = {}
    for tag in IMG_TAG.findall(page):
        src = SRC_RE.search(tag)
        alt = ALT_RE.search(tag)
        if not src or not alt:
            continue
        url = src.group(1).split("?")[0].strip()
        name = _html.unescape(alt.group(1)).strip()
        if not name or PORTRAIT_MARKER not in url:
            continue
        photos.setdefault(name, url)   # pierwsze wystąpienie (pełny rozmiar 'm')
 
    if len(photos) < 11:
        print(f"[uwaga] Znaleziono tylko {len(photos)} zdjęć na {URL} — "
              f"strona mogła zmienić strukturę. Nie nadpisuję istniejącego photos.json.",
              file=sys.stderr)
        return 1
 
    os.makedirs(os.path.dirname(OUT_PATH) or ".", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(photos, f, ensure_ascii=False, indent=2, sort_keys=True)
 
    print(f"Gotowe: {len(photos)} oficjalnych zdjęć z rakow.com → {OUT_PATH}")
    for n in sorted(photos):
        print(f"  ✓ {n}")
    return 0
 
 
if __name__ == "__main__":
    sys.exit(main())
