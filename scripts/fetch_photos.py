#!/usr/bin/env python3
"""
Pobiera DARMOWE (wolne licencyjnie) zdjęcia zawodników kadry Raków z Wikimedia
Commons — przez Wikidata. Zapisuje public/photos.json:
 
    { "Imię Nazwisko": "https://commons.wikimedia.org/.../thumb.jpg", ... }
 
Zasady dopasowania (świadomie zachowawcze — lepiej sylwetka niż CUDZE zdjęcie):
  * kandydat musi mieć zawód "piłkarz" (P106 = Q937857),
  * przy kilku piłkarzach o tym samym imieniu wybieramy tego, który gra w
    Raków Częstochowa (P54, klub o nazwie zawierającej "Raków"),
  * jeśli takiego nie ma i piłkarz jest dokładnie jeden — bierzemy jego,
  * w innym wypadku POMIJAMY (front pokaże sylwetkę).
 
Zdjęcia z Wikimedia Commons są wolne licencyjnie (CC/PD) — legalne do użycia,
przy zachowaniu atrybucji, którą Commons podaje na stronie pliku.
 
Uruchamiane w GitHub Actions (workflow refresh-photos.yml). Zależności: tylko
biblioteka standardowa Pythona.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
 
DATA_PATH = os.environ.get("DATA_PATH", "public/data.json")
OUT_PATH = os.environ.get("PHOTOS_PATH", "public/photos.json")
WD_API = "https://www.wikidata.org/w/api.php"
UA = "RakowScout/1.0 (player photos; https://github.com/levelupstudioPL/rakow-scout)"
FOOTBALLER = "Q937857"   # association football player (occupation P106)
THUMB_W = 320
 
 
def _get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise last
 
 
def search_entities(name):
    q = urllib.parse.urlencode({
        "action": "wbsearchentities", "search": name, "language": "en",
        "uselang": "en", "type": "item", "format": "json", "limit": 12,
    })
    return _get(f"{WD_API}?{q}").get("search", [])
 
 
def get_entities(ids):
    """Batch fetch (max 50 ids per Wikidata call)."""
    out = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        q = urllib.parse.urlencode({
            "action": "wbgetentities", "ids": "|".join(chunk),
            "props": "claims|labels", "languages": "en|pl", "format": "json",
        })
        out.update(_get(f"{WD_API}?{q}").get("entities", {}))
        time.sleep(0.2)
    return out
 
 
def claim_qids(ent, prop):
    ids = []
    for c in ent.get("claims", {}).get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and "id" in v:
            ids.append(v["id"])
    return ids
 
 
def p18_filename(ent):
    for c in ent.get("claims", {}).get("P18", []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, str):
            return v
    return None
 
 
def label_of(ent):
    labs = ent.get("labels", {})
    for lang in ("en", "pl"):
        if lang in labs:
            return labs[lang].get("value", "")
    return next((l.get("value", "") for l in labs.values()), "")
 
 
def commons_thumb(filename, width=THUMB_W):
    fn = filename.replace(" ", "_")
    return ("https://commons.wikimedia.org/wiki/Special:FilePath/"
            + urllib.parse.quote(fn) + f"?width={width}")
 
 
def resolve_photo(name):
    """Zwraca (url, note) — url None gdy brak pewnego dopasowania."""
    cands = search_entities(name)
    if not cands:
        return None, "brak w Wikidata"
    ids = [c["id"] for c in cands]
    ents = get_entities(ids)
 
    footballers = []
    for qid in ids:
        ent = ents.get(qid, {})
        if FOOTBALLER in claim_qids(ent, "P106"):
            footballers.append((qid, ent))
    if not footballers:
        return None, "brak piłkarza"
 
    # Zbierz kluby (P54) i sprawdź który to Raków — po nazwie klubu.
    team_ids = sorted({t for _, e in footballers for t in claim_qids(e, "P54")})
    team_ents = get_entities(team_ids) if team_ids else {}
    # Klub Rakowa: nazwa zawiera "Raków" / "Rakow".
    rakow_teams = {tid for tid, te in team_ents.items()
                   if "raków" in label_of(te).lower() or "rakow" in label_of(te).lower()}
 
    rakow_cands = [(q, e) for q, e in footballers
                   if any(t in rakow_teams for t in claim_qids(e, "P54"))]
 
    if rakow_cands:
        chosen = rakow_cands[0]
        conf = "Raków"
    elif len(footballers) == 1:
        chosen = footballers[0]
        conf = "jedyny piłkarz"
    else:
        return None, f"niejednoznaczne ({len(footballers)} piłkarzy)"
 
    fn = p18_filename(chosen[1])
    if not fn:
        return None, f"{conf}, brak zdjęcia (P18)"
    return commons_thumb(fn), conf
 
 
def main():
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    squad = data.get("squad", [])
    names = [p["name"] for p in squad if p.get("name")]
    print(f"Kadra: {len(names)} zawodników → szukam zdjęć w Wikimedia Commons\n")
 
    photos = {}
    hits, misses = 0, 0
    for name in names:
        try:
            url, note = resolve_photo(name)
        except Exception as e:  # noqa: BLE001
            url, note = None, f"błąd: {e}"
        if url:
            photos[name] = url
            hits += 1
            print(f"  ✓ {name:32s} {note}")
        else:
            misses += 1
            print(f"  · {name:32s} {note}")
        time.sleep(0.3)
 
    os.makedirs(os.path.dirname(OUT_PATH) or ".", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(photos, f, ensure_ascii=False, indent=2, sort_keys=True)
 
    print(f"\nGotowe: {hits}/{len(names)} zdjęć → {OUT_PATH} "
          f"({misses} bez pewnego dopasowania — front pokaże sylwetkę)")
 
 
if __name__ == "__main__":
    sys.exit(main())
