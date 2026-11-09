#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_fixtures.py — odświeża public/fixtures.json terminarzem Rakowa.

FILOZOFIA (fail-safe, jak reszta pipeline):
  • BAZA = ręczny public/fixtures.json (pełny sezon 2026/27, 34 mecze). On jest źródłem
    prawdy o rozpisce (rywal + dom/wyjazd). Ten skrypt go NIE zastępuje.
  • Źródło danych dokłada tylko: UTWARDZONE daty (gdy liga potwierdzi dokładny dzień)
    oraz WYNIKI rozegranych meczów. Nakłada je na istniejące wpisy po dopasowaniu
    rywala + strony boiska.
  • ŹRÓDŁA (po kolei, pierwsze działające wygrywa):
      1) Sofascore (api.sofascore.com, team 35268) — terminarz + wyniki, czysty JSON.
      2) TheSportsDB (darmowe API, team 137670) — fallback.
    fotmob celowo pominięty: jego /api/ jest zabroniony w robots.txt.
  • BEZPIECZNIKI: błąd sieci / brak danych / 0 dopasowań → plik zostaje bez zmian.
    Nigdy nie zapisujemy pustego pliku ani mniejszej liczby meczów niż w bazie.
    Żaden wyjątek nie wywala pipeline (krok i tak jest continue-on-error).

Env: SOFASCORE_TEAM_ID (domyślnie 35268 = Raków), SPORTSDB_TEAM_ID (137670), SPORTSDB_KEY ('3').

Użycie:
  python scripts/fetch_fixtures.py            # public/fixtures.json
  python scripts/fetch_fixtures.py plik.json  # test
"""
import json
import os
import sys
import unicodedata
import urllib.request
from datetime import date, datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_HERE, "..", "public", "fixtures.json")
TEAM_SOFA = os.getenv("SOFASCORE_TEAM_ID", "35268")   # Raków na Sofascore
TEAM_SDB = os.getenv("SPORTSDB_TEAM_ID", "137670")    # Raków na TheSportsDB
SDB_KEY = os.getenv("SPORTSDB_KEY", "3")
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
_FINISHED = {"match finished", "ft", "aet", "after extra time", "pen", "finished"}


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.lower().replace("ł", "l").replace("-", " ").split())


def _toks(s):
    return set(t for t in _norm(s).split() if len(t) > 2)


def _is_rakow(name):
    # Całe słowo — „rakow" jest podciągiem „krakow" (Kraków!).
    return "rakow" in _toks(name)


def _daynum(d):
    try:
        return datetime.strptime(str(d)[:10], "%Y-%m-%d").toordinal()
    except Exception:  # noqa: BLE001
        return 0


def _get(url, headers=None):
    hdr = {"User-Agent": _UA, "Accept": "application/json"}
    if headers:
        hdr.update(headers)
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


# Ujednolicony event: {league, home, away, date 'YYYY-MM-DD', hs, as, finished}

def _events_sofascore():
    out = []
    got_any = False
    for path in ("events/last/0", "events/next/0"):
        try:
            d = _get(f"https://api.sofascore.com/api/v1/team/{TEAM_SOFA}/{path}",
                     headers={"Referer": "https://www.sofascore.com/"})
            got_any = True
        except Exception as e:  # noqa: BLE001
            print(f"[terminarz] Sofascore {path} nieosiągalne ({e}).", file=sys.stderr)
            continue
        for e in (d or {}).get("events", []) or []:
            trn = e.get("tournament") or {}
            league = (trn.get("uniqueTournament") or {}).get("name") or trn.get("name") or ""
            ts = e.get("startTimestamp")
            dt = ""
            if ts:
                try:
                    dt = datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%d")
                except Exception:  # noqa: BLE001
                    dt = ""
            status = ((e.get("status") or {}).get("type") or "")
            out.append({
                "league": league,
                "home": (e.get("homeTeam") or {}).get("name"),
                "away": (e.get("awayTeam") or {}).get("name"),
                "date": dt,
                "hs": (e.get("homeScore") or {}).get("current"),
                "as": (e.get("awayScore") or {}).get("current"),
                "finished": status == "finished",
            })
    return out if got_any else None


def _events_thesportsdb():
    base = f"https://www.thesportsdb.com/api/v1/json/{SDB_KEY}"
    out = []
    got_any = False
    for ep in (f"eventslast.php?id={TEAM_SDB}", f"eventsnext.php?id={TEAM_SDB}"):
        try:
            d = _get(f"{base}/{ep}")
            got_any = True
        except Exception as e:  # noqa: BLE001
            print(f"[terminarz] TheSportsDB {ep} nieosiągalne ({e}).", file=sys.stderr)
            continue
        for e in ((d or {}).get("results") or (d or {}).get("events") or []) or []:
            status = _norm(e.get("strStatus"))
            out.append({
                "league": e.get("strLeague"),
                "home": e.get("strHomeTeam"),
                "away": e.get("strAwayTeam"),
                "date": (e.get("dateEvent") or "")[:10],
                "hs": e.get("intHomeScore"),
                "as": e.get("intAwayScore"),
                "finished": status in _FINISHED,
            })
    return out if got_any else None


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

    # 2) Pobierz eventy: Sofascore → fallback TheSportsDB.
    events, src = _events_sofascore(), "sofascore"
    if not events:
        events, src = _events_thesportsdb(), "thesportsdb"
    if not events:
        print("[terminarz] Żadne źródło nie oddało eventów; zostawiam ręczny terminarz.", file=sys.stderr)
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
        if "ekstraklasa" not in _norm(e.get("league")):
            continue
        home_t, away_t = e.get("home"), e.get("away")
        if not (_is_rakow(home_t) or _is_rakow(away_t)):
            continue
        rk_home = _is_rakow(home_t)
        opp = away_t if rk_home else home_t
        ev_date = (e.get("date") or "")[:10]
        if not ev_date:
            continue

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

        if ev_date and m.get("date") != ev_date:
            m["date"] = ev_date
            date_upd += 1

        hs, as_ = e.get("hs"), e.get("as")
        played = e.get("finished") or (_daynum(ev_date) < today)
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
        print(f"[terminarz] Źródło {src}: 0 dopasowań/zmian; zostawiam bez zmian.", file=sys.stderr)
        return 0

    # 4) Bezpiecznik: liczba meczów się nie zmienia (nakładamy in-place na bazę).
    base["fixtures"] = bf
    base["updated"] = date.today().isoformat()
    base["auto_source"] = src
    json.dump(base, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[terminarz] Źródło {src}: utwardzono {date_upd} dat, {score_upd} wyników; "
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
