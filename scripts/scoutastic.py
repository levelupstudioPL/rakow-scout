#!/usr/bin/env python3
"""
Klient REST API Scoutastic (instancja rakow.scoutastic.com).
 
Po co: oficjalne wartości rynkowe z Transfermarktu (marketValue), szczyt wartości
(marketValueHistory) i kontrakt — legalnie i stabilnie, w miejsce kruchego,
publicznego API TM i niepełnego zrzutu z Kaggle.
 
Jak: najpierw dopasowujemy naszych zawodników StatsBomb do Scoutastic przez
POST /players/matching/statsbomb (zwraca externalId per offline_player_id), potem
GET /players/{externalId} po dane. Autoryzacja: token Bearer w nagłówku
Authorization (sekret SCOUTASTIC_TOKEN — NIGDY w kodzie).
 
Bezpieczne: pojedyncze błędy zapytań są łapane; brak danych = zawodnik zostaje z
wartością z Kaggle (albo bez ceny), pipeline nie pada.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
 
BASE_URL = os.getenv("SCOUTASTIC_BASE_URL", "https://rakow.scoutastic.com/api/v1")
TIMEOUT = 30
RETRIES = 3
REQUEST_DELAY_S = float(os.getenv("SCOUTASTIC_DELAY_S", "0.2"))
 
 
class ApiError(Exception):
    """Błąd HTTP z treścią odpowiedzi serwera (żeby było widać DLACZEGO)."""
    def __init__(self, code, body):
        self.code = code
        self.body = body
        super().__init__(f"HTTP {code}: {body}")
 
 
class Client:
    def __init__(self, token):
        self.token = (token or "").strip()
        # Nagłówek Authorization. Domyślnie prefiks "Bearer " (schemat z docs:
        # „Bearer (apiKey)"). Gdyby instancja chciała surowy token — SCOUTASTIC_AUTH_RAW=1.
        if os.getenv("SCOUTASTIC_AUTH_RAW") in ("1", "true", "True"):
            self._auth = self.token
        elif self.token.lower().startswith("bearer "):
            self._auth = self.token
        else:
            self._auth = f"Bearer {self.token}"
 
    # --- niskopoziomowe ---
    def _request(self, method, path, params=None, body=None):
        url = f"{BASE_URL}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        for attempt in range(1, RETRIES + 1):
            try:
                req = urllib.request.Request(url, data=data, method=method)
                req.add_header("Authorization", self._auth)
                req.add_header("Accept", "application/json")
                if data is not None:
                    req.add_header("Content-Type", "application/json")
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    raw = resp.read().decode("utf-8")
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as e:
                # przejściowe: ponów; reszta: rzuć z treścią odpowiedzi (diagnostyka).
                if e.code in (429, 500, 502, 503) and attempt < RETRIES:
                    time.sleep(REQUEST_DELAY_S * attempt * 3)
                    continue
                try:
                    err_body = e.read().decode("utf-8")[:300]
                except Exception:  # noqa: BLE001
                    err_body = "(brak treści)"
                raise ApiError(e.code, err_body)
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < RETRIES:
                    time.sleep(REQUEST_DELAY_S * attempt * 3)
                    continue
                raise ApiError(0, str(e))
        return None
 
    # --- endpointy ---
    def match_statsbomb(self, players, gender="male", chunk=200):
        """players: lista dictów {player_name, player_birth_date, offline_player_id,
        live_player_id, player_height}. Zwraca {offline_player_id: externalId}."""
        out = {}
        shown = False
        for i in range(0, len(players), chunk):
            batch = players[i:i + chunk]
            try:
                res = self._request("POST", "/players/matching/statsbomb",
                                    params={"gender": gender}, body=batch) or {}
            except Exception as e:  # noqa: BLE001
                # Pierwszy błąd pokaż SZCZEGÓŁOWO (kod + treść serwera) — to mówi DLACZEGO.
                if not shown:
                    print(f"[scoutastic] match: pierwszy błąd — {e}", file=sys.stderr)
                    print(f"[scoutastic]   przykład wysłanego rekordu: {batch[0] if batch else '(pusto)'}",
                          file=sys.stderr)
                    shown = True
                else:
                    print(f"[scoutastic] match: błąd partii {i // chunk + 1} "
                          f"({getattr(e, 'code', '?')})", file=sys.stderr)
                continue
            for m in (res.get("successfulMatches") or []):
                off = str(m.get("offline_player_id"))
                ext = m.get("externalId")
                if off and ext:
                    out[off] = str(ext)
            time.sleep(REQUEST_DELAY_S)
        return out
 
    def get_player(self, external_id):
        """GET /players/{id} -> surowy obiekt zawodnika (albo None)."""
        try:
            return self._request("GET", f"/players/{urllib.parse.quote(str(external_id))}")
        except Exception as e:  # noqa: BLE001
            print(f"[scoutastic] get_player {external_id}: błąd ({e})", file=sys.stderr)
            return None
 
 
# --- normalizacja pól (marketValue bywa liczbą EUR albo obiektem) ---
def _num(x):
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.replace(",", "").strip()
        try:
            return float(s)
        except ValueError:
            return 0.0
    if isinstance(x, dict):
        for k in ("value", "amount", "marketValue", "eur", "valueEur"):
            if k in x:
                return _num(x[k])
    return 0.0
 
 
def to_millions(raw):
    """EUR -> mln EUR (nasza apka pokazuje €X.XM). Odporne na liczbę/obiekt/string."""
    v = _num(raw)
    if v <= 0:
        return 0.0
    # Jeżeli wartość jest już „mała" (podana w mln), nie dziel ponownie.
    return round(v / 1_000_000.0, 2) if v >= 10_000 else round(v, 2)
 
 
def peak_from_history(hist):
    """marketValueHistory -> szczyt (mln EUR). Obsługuje listę liczb lub obiektów."""
    if not isinstance(hist, list):
        return 0.0
    best = 0.0
    for h in hist:
        val = _num(h.get("value") if isinstance(h, dict) else h)
        if val > best:
            best = val
    return to_millions(best)
 
 
def contract_year(player):
    for k in ("contractExpires", "contractThereExpires"):
        v = player.get(k)
        if isinstance(v, str) and len(v) >= 4 and v[:4].isdigit():
            return int(v[:4])
        if isinstance(v, (int, float)) and v > 1900:
            return int(v)
    return 0
 
 
def extract(player):
    """Z surowego obiektu Scoutastic wyciąga to, czego używa model."""
    if not isinstance(player, dict):
        return {}
    return {
        "mv": to_millions(player.get("marketValue")),
        "peak": peak_from_history(player.get("marketValueHistory")),
        "contract": contract_year(player),
    }
 
