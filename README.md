# Cyfrowy bliźniak składu Rakowa — Scouting MVP

Interaktywny prototyp analityki scoutingowej: cyfrowy bliźniak składu, dopasowanie
odpowiedników z lig europejskich (handicapy), korelacje zależności w formacji.

> **Dane:** rdzeń składu i pozycje są realne (publiczne profile 25/26). Wszystkie
> liczby (RC, handicapy, korelacje, dopasowania) to **proxy** do walidacji logiki
> modelu — oznaczone w UI kolorem bursztynowym. Tryb live podmienia je danymi z FBref.

---

## Szybki start lokalnie

```bash
npm install
npm run dev        # http://localhost:5173
```

Aplikacja od razu działa na snapshocie (`public/data.json`) — bez backendu.

## Build

```bash
npm run build      # → dist/
npm run preview    # podgląd builda
```

---

## Publikacja (darmowy hosting)

### Opcja 1 — Netlify (rekomendacja, obsługuje tryb live)

1. Wrzuć folder na GitHub.
2. Na netlify.com: **Add new site → Import from Git**, wskaż repo.
3. Netlify wykryje `netlify.toml` — build i funkcja serverless wstają same.
4. Gotowe. Przycisk „Pobierz live z FBref" w appce uderza w `/.netlify/functions/fbref`.

### Opcja 2 — Vercel

Import repo na vercel.com — `vercel.json` ustawia build. (Funkcję live trzeba
przepisać do formatu `api/` Vercela; snapshot działa od razu.)

### Opcja 3 — GitHub Pages (tylko snapshot, bez live)

```bash
npm run build
# wrzuć zawartość dist/ na branch gh-pages
```

Tryb live wymaga serwera — na czystym GitHub Pages działa tylko snapshot.
Do prezentacji to wystarcza.

---

## Tryb live z FBref — co trzeba dokończyć

FBref **nie da się** odpytać bezpośrednio z przeglądarki (CORS + limit 10 req/min,
przekroczenie = blokada na dobę). Dlatego dane idą przez serwer:

- **`netlify/functions/fbref.js`** — proxy serverless (omija CORS, cache 6h). Zawiera
  `parseFbrefToModel()` jako **stub** — trzeba dopisać parsowanie tabel FBref
  (uwaga: część tabel jest w komentarzach HTML `<!-- -->`, trzeba je odkomentować).
- **`scripts/fetch_fbref.mjs`** — alternatywa „przy buildzie": pobiera raz, zapisuje
  `data.json`, hosting serwuje statycznie. Pace 7s/request.

Mapowanie metryk → RC (0–100), handicapy per-linia i pula odpowiedników to miejsce,
gdzie wchodzi logika analityka. Struktura `data.json` jest docelowym kontraktem —
parser ma produkować dokładnie ten kształt. Pola `pool[]`: `age`, `mv` (wartość rynkowa
w mln €), `contract` (rok wygaśnięcia) zasilają estymację ceny.

## Estymacja ceny (proxy)

Cena kandydata = wartość rynkowa × mnożniki: poziom skoryg. vs RC, wiek, długość
kontraktu, mnożnik ligi. Zwraca punkt + widełki (−20% / +25%). To **placeholder
logiki** — realnie kalibrowany na zrealizowanych transferach. Wzór jest w `App.jsx`
(`estimatePrice`) i łatwo go podmienić.

## Limit FBref (twardy)

Maks. **10 zapytań/min**. Przekroczenie blokuje sesję na ~dobę. Cache i pauzy w kodzie
są po to celowo — nie usuwaj ich.
