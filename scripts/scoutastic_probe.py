#!/usr/bin/env python3
"""
SONDA API Scoutastic — jednorazowa diagnostyka pod walidator „Ostatnie mecze".
 
Cel: sprawdzić, czy Wasza instancja Scoutastic wystawia DANE MECZOWE per zawodnik
(minuty, gole, asysty, mecz/data) — bo tego potrzebuje walidator, a obecny klient
używa tylko danych zawodnika (wartość, kontrakt). Z odpowiedzi zbudujemy adapter
bez zgadywania endpointów.
 
Uruchom (masz token):
    SCOUTASTIC_TOKEN=... python scripts/scoutastic_probe.py
 
Bezpieczeństwo: NIC nie modyfikuje; drukuje tylko kody odpowiedzi i KLUCZE
najwyższego poziomu (nie całe dane, nie token). Token czytany wyłącznie z env.
"""
import json
import os
import sys
import urllib.parse
 
import scoutastic as sc
 
 
def _keys(obj, limit=24):
    if isinstance(obj, dict):
        return sorted(obj.keys())[:limit]
    if isinstance(obj, list):
        return f"lista[{len(obj)}]" + (f", elem klucze: {sorted(obj[0].keys())[:limit]}"
                                       if obj and isinstance(obj[0], dict) else "")
    return type(obj).__name__
 
 
def _load_names():
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        squad = json.load(open(os.path.join(here, "..", "public", "squad.json"), encoding="utf-8"))
        return [p.get("name") for p in squad if p.get("name")]
    except Exception:  # noqa: BLE001
        return ["Stratos Svarnas", "Bogdan Racovițan", "Marko Bulat", "Fran Tudor"]
 
 
def main():
    token = os.getenv("SCOUTASTIC_TOKEN")
    if not token:
        print("[sonda] Brak SCOUTASTIC_TOKEN w środowisku.", file=sys.stderr)
        sys.exit(1)
    c = sc.Client(token)
 
    # --- 1) ustal externalId jednego zawodnika (przez /players/search) ---
    ext, who = None, None
    for name in _load_names():
        try:
            res = c.search_player(name)
        except Exception as e:  # noqa: BLE001
            print(f"[sonda] search '{name}': błąd {e}", file=sys.stderr)
            continue
        if res:
            r0 = res[0]
            print(f"[sonda] search '{name}' -> {len(res)} wyników; klucze wyniku: {_keys(r0)}")
            ext = r0.get("playerId") or r0.get("externalId") or r0.get("id")
            if ext:
                who = f"{r0.get('firstName','')} {r0.get('lastName','')}".strip()
                print(f"[sonda] używam externalId={ext} ({who})")
                break
    if not ext:
        print("[sonda] Nie ustaliłem externalId — sprawdź token/dostęp.", file=sys.stderr)
        sys.exit(2)
 
    # --- 2) pełny obiekt zawodnika: może już zawiera performance/mecze ---
    p = c.get_player(ext)
    if isinstance(p, dict):
        print(f"\n[sonda] GET /players/{ext} -> klucze: {sorted(p.keys())}")
        for k in ("performance", "performances", "matches", "appearances", "stats",
                  "statistics", "currentClub", "seasons", "matchPerformances"):
            if k in p:
                print(f"[sonda]   • zawiera '{k}': {_keys(p[k])}")
 
    # --- 3) próbne endpointy meczowe (kandydaci wg konwencji TM/Scoutastic) ---
    e = urllib.parse.quote(str(ext))
    candidates = [
        f"/players/{e}/performances", f"/players/{e}/performance",
        f"/players/{e}/matches", f"/players/{e}/appearances",
        f"/players/{e}/games", f"/players/{e}/statistics",
        f"/players/{e}/matchperformances", f"/players/{e}/match-performances",
        "/matches", "/competitions", "/seasons",
    ]
    print("\n[sonda] Próbne endpointy meczowe (200 = istnieje):")
    for path in candidates:
        try:
            r = c._request("GET", path)
            print(f"[sonda]   200 {path} -> {_keys(r)}")
        except sc.ApiError as ex:
            print(f"[sonda]   {ex.code} {path}")
        except Exception as ex:  # noqa: BLE001
            print(f"[sonda]   ERR {path}: {ex}")
 
    print("\n[sonda] Gotowe. Wklej mi powyższe linie [sonda] — z nich zbuduję adapter.")
 
 
if __name__ == "__main__":
    main()
 
