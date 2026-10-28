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
import os
import re
import sys
import urllib.request
import urllib.parse
import json
 
# Publiczny egzemplarz. Podmień na własny (np. https://twoj-egzemplarz.onrender.com)
# gdy publiczny zacznie limitować — wystarczy ustawić zmienną TM_API_BASE (bez zmian w kodzie).
BASE_URL = os.getenv("TM_API_BASE") or "https://transfermarkt-api.fly.dev"

# Bezpośredni odczyt ze strony klubu na Transfermarkcie (łączna wartość składu =
# „Total market value" / „Gesamtmarktwert"). Omija pośrednika (felipeall API).
# Można nadpisać domenę (np. transfermarkt.pl / .de) zmienną TM_WEB_BASE.
TM_WEB_BASE = os.getenv("TM_WEB_BASE") or "https://www.transfermarkt.com"
TM_WEB_DELAY_S = float(os.getenv("TM_WEB_DELAY_S") or "2.0")
_BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,pl;q=0.8",
}
 
# ID klubu Raków Częstochowa na Transfermarkcie: 9644
# (z profilu klubu: /rakow-czestochowa/startseite/verein/9644).
# Uwaga: 41149 to rezerwy "Raków II" — NIE używać.
# Można nadpisać zmienną środowiskową RAKOW_CLUB_ID (bez zmiany kodu).
RAKOW_CLUB_ID = os.getenv("RAKOW_CLUB_ID", "9644")
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
    s = s.replace("mrd.", "b").replace("mrd", "b").replace("mld", "b").replace("bn", "b")
    s = s.replace("mio.", "m").replace("mio", "m").replace("tsd.", "k").replace("tsd", "k")
    s = s.replace(",", ".").replace(" ", "").strip()
    if not s:
        return 0.0
    try:
        if s.endswith("b"):   # miliardy -> mln
            return round(float(s[:-1]) * 1000, 2)
        if s.endswith("m"):
            return round(float(s[:-1]), 2)
        if s.endswith("k"):
            return round(float(s[:-1]) / 1000, 3)
        v = float(s)
        return round(v / 1_000_000, 2) if v > 10000 else round(v, 2)
    except ValueError:
        return 0.0
 
 
def _get_html(url: str, retries: int = 3):
    """Surowy HTML strony (z nagłówkami przeglądarki — TM odrzuca gołe python-urllib)."""
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("latin-1", "ignore")
        except Exception as e:  # noqa: BLE001
            wait = TM_WEB_DELAY_S * attempt
            print(f"[TM-web] próba {attempt}/{retries} nieudana ({e}). Czekam {wait:.0f}s…", file=sys.stderr)
            time.sleep(wait)
    print(f"[TM-web] Nie udało się pobrać {url} po {retries} próbach.", file=sys.stderr)
    return None


def _money_from_text(text: str):
    """Pierwszy token walutowy w tekście -> mln EUR (0.0 gdy brak).
    Obsługuje: '€45.30m', '€1.25bn', '45,30 Mio. €', '1,25 Mrd. €', '45.30m €'."""
    if not text:
        return 0.0
    t = re.sub(r"\s+", " ", text)
    pats = [
        r"€\s*[\d.,]+\s*(?:bn|mrd|mld|mio|m|k|tsd)?",          # €45.30m / €1.25bn
        r"[\d.,]+\s*(?:bn|mrd|mld|mio|m|k|tsd)\.?\s*€",        # 45,30 Mio. € / 45.30m €
    ]
    for p in pats:
        mm = re.search(p, t, re.I)
        if mm:
            v = _parse_mv_to_millions(mm.group(0))
            if v and v > 0:
                return v
    return 0.0


def fetch_club_total_value(club_id: str):
    """Łączna wartość rynkowa składu klubu WPROST ze strony TM (/verein/{id}).
    Zwraca {'total': mln EUR, 'squad': liczba_zawodników|None} albo None.
    Nie weryfikowane na żywo przy pisaniu (sandbox blokuje TM) — wzorce są
    defensywne, a przy porażce logujemy fragment strony do przeglądu."""
    url = f"{TM_WEB_BASE}/-/startseite/verein/{urllib.parse.quote(str(club_id))}"
    html = _get_html(url)
    if not html:
        return None
    val = 0.0
    # 1) Nagłówkowy „market-value-wrapper" — wartość jest tam pierwsza.
    m = re.search(r'data-header__market-value-wrapper[^>]*>(.*?)</a>', html, re.S | re.I)
    if m:
        val = _money_from_text(re.sub(r"<[^>]+>", " ", m.group(1)))
    # 2) Fallback: okno PRZED etykietą „Total market value"/„Gesamtmarktwert".
    if not val:
        m2 = re.search(r'(.{0,160})(?:total market value|gesamtmarktwert)', html, re.S | re.I)
        if m2:
            val = _money_from_text(re.sub(r"<[^>]+>", " ", m2.group(1)))
    if not val or val <= 0:
        snippet = re.sub(r"<[^>]+>", " ", (m.group(1) if m else html[:400]))
        print(f"[TM-web] klub {club_id}: nie wyłuskałem wartości. Fragment: "
              f"{re.sub(r' +', ' ', snippet)[:160]!r}", file=sys.stderr)
        return None
    # Liczebność kadry (opcjonalnie) — „Squad size"/„Kadergröße".
    squad = None
    ms = re.search(r'(?:squad size|kadergr[oö]ße|kadergroesse)\D{0,40}?(\d{1,2})', html, re.I)
    if ms:
        try:
            squad = int(ms.group(1))
        except ValueError:
            squad = None
    return {"total": round(val, 1), "squad": squad}


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
