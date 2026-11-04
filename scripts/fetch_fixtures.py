#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_fixtures.py — odświeża public/fixtures.json terminarzem Rakowa z TheSportsDB.

FILOZOFIA (fail-safe, jak reszta pipeline):
  • BAZA = ręczny public/fixtures.json (pełny sezon 2026/27, 34 mecze). On jest źródłem
    prawdy o rozpisce (rywal + dom/wyjazd). Ten skrypt go NIE zastępuje.
  • TheSportsDB (darmowe API, klucz '3') dokłada tylko: UTWARDZONE daty (gdy liga
    potwierdzi dokładny dzień) oraz WYNIKI rozegranych meczów. Nakłada je na istniejące
    wpisy po dopasowaniu rywala + strony boiska.
  • BEZPIECZNIKI: błąd sieci / brak danych / 0 dopasowań → plik zostaje bez zmian.
    Nigdy nie zapisujemy pustego pliku ani mniejszej liczby meczów niż w bazie.
    Żaden wyjątek nie wywala pipeline (krok i tak jest continue-on-error).

Źródło: https://www.thesportsdb.com/api/v1/json/3/eventslast.php?id=137670 (+ eventsnext).
Env: SPORTSDB_TEAM_ID (domyślnie 137670 = Raków), SPORTSDB_KEY (domyślnie '3').

Użycie:
  python scripts/fetch_fixtures.py            # public/fixtures.json
  python scripts/fetch_fixtures.py plik.json  # test
"""
import json
import os
import sys
import unicodedata
import urllib.request
from datetime import date, datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_HERE, "..", "public", "fixtures.json")
TEAM_ID = os.getenv("SPORTSDB_TEAM_ID", "137670")   # Raków Częstochowa na TheSportsDB
KEY = os.getenv("SPORTSDB_KEY", "3")                 # darmowy publiczny klucz
BASE = f"https://www.thesportsdb.com/api/v1/json/{KEY}"
_FINISHED = {"match finished", "ft", "aet", "after extra time", "pen", "finished"}


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.lower().replace("ł", "l").replace("-", " ").split())


def _toks(s):
    return set(t for t in _norm(s).split() if len(t) > 2)


def _is_rakow(name):
    # Dopasowanie po CAŁYM słowie — „rakow" jest podciągiem „krakow" (Kraków!),
    # więc substring myliłby Wieczystą/Wisłę Kraków z Rakowem. Token = całe słowo.
    return "rakow" in _toks(name)


def _daynum(d):
    try:
        return datetime.strptime(str(d)[:10], "%Y-%m-%d").toordinal()
    except Exception:  # noqa: BLE001
        return 0


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (rakow-scout fixtures)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    # 1) BAZA — ręczny terminarz musi istnieć i mieć mecze.
    try:
        base = json.load(open(OUT, encoding="utf-8"))
        bf = base.get("fixtures") or []
    except Exception as e:  # noqa: BLE001
        print(f"[terminarz] Nie czytam {OUT} ({e}); pomijam.", file=sys.stderr)
        return 0
    if not isinstance(bf, list) or not bf:
        print("[terminarz] Baseline pusty/niepoprawny; nic nie nadpisuję.", file=sys.stderr)
        return 0

    # 2) Pobierz ostatnie + najbliższe mecze.
    events = []
    for ep in (f"eventslast.php?id={TEAM_ID}", f"eventsnext.php?id={TEAM_ID}"):
        try:
            d = _get(f"{BASE}/{ep}")
            ev = (d or {}).get("results") or (d or {}).get("events") or []
            if isinstance(ev, list):
                events += ev
        except Exception as e:  # noqa: BLE001
            print(f"[terminarz] {ep} nieosiągalne ({e}).", file=sys.stderr)
    if not events:
        print("[terminarz] Brak eventów z TheSportsDB; zostawiam ręczny terminarz.", file=sys.stderr)
        return 0

    # 3) Indeks bazy po (tokeny-rywala, dom/wyjazd) — każdy z 34 meczów jest unikalny.
    def key_of(opp, home):
        return (frozenset(_toks(opp)), bool(home))

    idx = {}
    for m in bf:
        idx.setdefault(key_of(m.get("opp"), m.get("home")), []).append(m)

    today = date.today().toordinal()
    date_upd = score_upd = 0
    for e in events:
        if "ekstraklasa" not in _norm(e.get("strLeague")):
            continue
        home_t, away_t = e.get("strHomeTeam"), e.get("strAwayTeam")
        if not (_is_rakow(home_t) or _is_rakow(away_t)):
            continue
        rk_home = _is_rakow(home_t)
        opp = away_t if rk_home else home_t
        ev_date = (e.get("dateEvent") or "")[:10]
        if not ev_date:
            continue

        # Dopasuj do bazy: najpierw dokładny klucz, potem przecięcie tokenów (ta sama strona).
        cands = idx.get(key_of(opp, rk_home)) or []
        if not cands:
            ot = _toks(opp)
            for (ftoks, fhome), lst in idx.items():
                if fhome == rk_home and ot and (ftoks & ot):
                    cands = lst
                    break
        if not cands:
            continue
        m = min(cands, key=lambda x: abs(_daynum(x.get("date")) - _daynum(ev_date)))

        # Utwardzona data.
        if ev_date and m.get("date") != ev_date:
            m["date"] = ev_date
            date_upd += 1

        # Wynik tylko dla faktycznie rozegranych (status FT albo data w przeszłości).
        status = _norm(e.get("strStatus"))
        hs, as_ = e.get("intHomeScore"), e.get("intAwayScore")
        played = (status in _FINISHED) or (_daynum(ev_date) < today)
        if played and hs not in (None, "") and as_ not in (None, ""):
            try:
                rk_g = int(hs) if rk_home else int(as_)
                opp_g = int(as_) if rk_home else int(hs)
            except (TypeError, ValueError):
                rk_g = opp_g = None
            if rk_g is not None:
                m["score"] = f"{rk_g}-{opp_g}"        # z perspektywy Rakowa
                m["res"] = "W" if rk_g > opp_g else ("D" if rk_g == opp_g else "L")
                m["played"] = True
                score_upd += 1

    if date_upd == 0 and score_upd == 0:
        print("[terminarz] 0 dopasowań/zmian; zostawiam bez zmian.", file=sys.stderr)
        return 0

    # 4) Bezpiecznik: liczba meczów się nie zmienia (nakładamy in-place na bazę).
    base["fixtures"] = bf
    base["updated"] = date.today().isoformat()
    base["auto_source"] = "thesportsdb"
    json.dump(base, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[terminarz] TheSportsDB: utwardzono {date_upd} dat, {score_upd} wyników; "
          f"{len(bf)} meczów w terminarzu.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"[terminarz] Nieoczekiwany błąd ({e}); terminarz bez zmian.", file=sys.stderr)
        raise SystemExit(0)
