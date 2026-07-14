#!/usr/bin/env python3
# =====================================================================
# transfermarkt.py — pobiera skład i wartości rynkowe z Transfermarktu
# przez PUBLICZNY egzemplarz felipeall/transfermarkt-api.
#
# UWAGA: publiczna instancja (transfermarkt-api.fly.dev) jest testowa i ma
# WŁĄCZONY rate limiting. Może być wolna, limitowana lub czasowo niedostępna.
# Gdy zacznie zawodzić, postaw własny egzemplarz (Docker) i podmień BASE_URL —
# reszta kodu działa bez zmian.
#
# To rozwiązanie opiera się na web scrapingu Transfermarktu (przez cudze API).
# Świadomie zaakceptowane jako mniej pewne; nieoficjalne i może przestać działać.
# =====================================================================
 
import time
import sys
import urllib.request
import urllib.parse
import json
 
# Publiczny egzemplarz. Podmień na własny (np. https://twoj-egzemplarz.onrender.com)
# gdy publiczny zacznie limitować.
BASE_URL = "https://transfermarkt-api.fly.dev"
 
# ID klubu Raków Częstochowa na Transfermarkcie (do potwierdzenia w profilu klubu).
# Zostaw None, by wyszukać po nazwie automatycznie.
RAKOW_CLUB_ID = None
RAKOW_NAME_QUERY = "Raków Częstochowa"
 
# Grzeczne odstępy między zapytaniami (publiczna instancja ma limit).
REQUEST_DELAY_S = 3.0
 
 
def _get(path: str, params: dict = None, retries: int = 3):
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            wait = REQUEST_DELAY_S * attempt
            print(f"[TM] próba {attempt}/{retries} nieudana ({e}). Czekam {wait:.0f}s…", file=sys.stderr)
            time.sleep(wait)
    print(f"[TM] Nie udało się pobrać {path} po {retries} próbach.", file=sys.stderr)
    return None
 
 
def find_rakow_club_id():
    """Wyszukuje ID klubu Rakowa po nazwie, jeśli nie podano ręcznie."""
    if RAKOW_CLUB_ID:
        return RAKOW_CLUB_ID
    data = _get("/clubs/search/" + urllib.parse.quote(RAKOW_NAME_QUERY))
    time.sleep(REQUEST_DELAY_S)
    if not data or not data.get("results"):
        print("[TM] Nie znaleziono klubu po nazwie. Ustaw RAKOW_CLUB_ID ręcznie.", file=sys.stderr)
        return None
    club = data["results"][0]
    print(f"[TM] Znaleziono klub: {club.get('name')} (id={club.get('id')})")
    return club.get("id")
 
 
def _parse_mv_to_millions(mv):
    """Zamienia wartość rynkową na mln EUR (float).
    Obsługuje: liczby (euro), '€3.50m', '€800k', '50.00 Mio. €', '500 Tsd. €'."""
    if mv is None:
        return 0.0
    # felipeall API zwraca marketValue jako LICZBĘ w euro (np. 3500000)
    if isinstance(mv, (int, float)):
        v = float(mv)
        return round(v / 1_000_000, 2) if v > 10000 else round(v, 2)
    s = str(mv).strip().lower()
    s = s.replace("€", "").replace("\u20ac", "").replace("eur", "")
    s = s.replace("mio.", "m").replace("mio", "m").replace("tsd.", "k").replace("tsd", "k")
    s = s.replace(",", ".").replace(" ", "").strip()
    if not s:
        return 0.0
    try:
        if s.endswith("m"):
            return round(float(s[:-1]), 2)
        if s.endswith("k"):
            return round(float(s[:-1]) / 1000, 3)
        v = float(s)
        return round(v / 1_000_000, 2) if v > 10000 else round(v, 2)
    except ValueError:
        return 0.0
 
 
def fetch_rakow_squad():
    """
    Zwraca listę zawodników Rakowa z Transfermarktu:
    [{name, pos, age, mv (mln EUR), contract (rok)}].
    """
    club_id = find_rakow_club_id()
    if not club_id:
        return []
    data = _get(f"/clubs/{club_id}/players")
    time.sleep(REQUEST_DELAY_S)
    if not data or not data.get("players"):
        print("[TM] Brak listy zawodników w odpowiedzi.", file=sys.stderr)
        return []
 
    squad = []
    for p in data["players"]:
        contract = p.get("contract") or p.get("contractExpiryDate") or ""
        year = 0
        if isinstance(contract, str) and len(contract) >= 4:
            for token in contract.replace("-", " ").replace(".", " ").split():
                if token.isdigit() and len(token) == 4:
                    year = int(token)
                    break
        squad.append({
            "name": p.get("name", "?"),
            "pos": p.get("position", ""),
            "age": int(p.get("age") or 0),
            "mv": _parse_mv_to_millions(p.get("marketValue")),
            "contract": year,
        })
    print(f"[TM] Pobrano {len(squad)} zawodników Rakowa.")
    return squad
 
 
def fetch_club_market_values(club_id: str):
    """Zwraca słownik {nazwa_zawodnika: wartość_mln} dla dowolnego klubu (pula odpowiedników)."""
    data = _get(f"/clubs/{club_id}/players")
    time.sleep(REQUEST_DELAY_S)
    out = {}
    if data and data.get("players"):
        for p in data["players"]:
            out[p.get("name", "?")] = _parse_mv_to_millions(p.get("marketValue"))
    return out
 
 
def fetch_player_value(player_name: str):
    """
    Wyszukuje zawodnika po nazwisku (search -> ID -> profile) i zwraca:
    {mv (mln EUR), age, contract (rok)} lub None.
 
    felipeall/transfermarkt-api:
      - GET /players/search/{name}  -> {"results": [{"id","name","marketValue",...}]}
      - GET /players/{id}/profile   -> pełny profil z marketValue, dateOfBirth, club{contractExpiryDate}
    Bierzemy profil, bo daje ustrukturyzowaną wartość i kontrakt.
    """
    if not player_name or player_name == "?":
        return None
 
    # 1) Szukaj ID po nazwisku
    search = _get("/players/search/" + urllib.parse.quote(player_name))
    time.sleep(REQUEST_DELAY_S)
    results = (search or {}).get("results") or []
    if not results:
        return None
    pid = results[0].get("id")
    if not pid:
        # Brak ID — spróbuj wyciągnąć wartość wprost z wyniku wyszukiwania.
        return {"mv": _parse_mv_to_millions(results[0].get("marketValue")), "age": 0, "contract": 0}
 
    # 2) Pobierz profil po ID (pełne, ustrukturyzowane dane)
    prof = _get(f"/players/{pid}/profile")
    time.sleep(REQUEST_DELAY_S)
    if not prof:
        return {"mv": _parse_mv_to_millions(results[0].get("marketValue")), "age": 0, "contract": 0}
 
    mv = _parse_mv_to_millions(prof.get("marketValue"))
 
    # Wiek z daty urodzenia
    age = 0
    dob = prof.get("dateOfBirth") or ""
    if isinstance(dob, str) and len(dob) >= 4:
        try:
            import datetime as _dt
            age = max(0, _dt.date.today().year - int(dob[:4]))
        except Exception:
            age = int(prof.get("age") or 0)
    else:
        age = int(prof.get("age") or 0)
 
    # Rok wygaśnięcia kontraktu (może być w club{} albo bezpośrednio)
    contract_str = ""
    club = prof.get("club")
    if isinstance(club, dict):
        contract_str = club.get("contractExpiryDate") or ""
    if not contract_str:
        contract_str = prof.get("contractExpiryDate") or prof.get("contract") or ""
    year = 0
    if isinstance(contract_str, str):
        for token in contract_str.replace("-", " ").replace(".", " ").replace(",", " ").split():
            if token.isdigit() and len(token) == 4:
                year = int(token)
                break
 
    return {"mv": mv, "age": age, "contract": year}
 
 
if __name__ == "__main__":
    # Szybki test: wypisz skład Rakowa.
    for pl in fetch_rakow_squad():
        print(f"  {pl['pos']:<22} {pl['name']:<28} {pl['age']} lat  €{pl['mv']}M  do {pl['contract']}")
