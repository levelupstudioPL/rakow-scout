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

---

## Podpięcie realnych danych ze StatsBomb

Skrypty w `scripts/` pobierają realne dane i regenerują `public/data.json`.
Aplikacja nie zmienia się — czyta ten sam plik, tylko z realnymi liczbami.

### Bezpieczeństwo poświadczeń

Hasła czytane są **wyłącznie ze zmiennych środowiskowych** — nigdy w kodzie,
nigdy w repo, nigdy w przeglądarce. Ustaw je w swoim terminalu:

```bash
export SB_USERNAME="igor.rybinski@rakow.com"
export SB_PASSWORD="twoje-haslo"
```

> Poświadczenia, które pojawiły się w wiadomości, traktuj jako ujawnione —
> zrotuj hasło w panelu StatsBomb przed realnym użyciem.

### Kroki

```bash
pip install statsbombpy pandas

# 1. Zobacz, do jakich rozgrywek masz dostęp:
python scripts/list_statsbomb_competitions.py

# 2. Wpisz competition_id / season_id do LEAGUE_CONFIG w scripts/fetch_statsbomb.py

# 3. Pobierz i wygeneruj data.json:
python scripts/fetch_statsbomb.py

# 4. Wgraj zmieniony public/data.json do repo — Netlify przebuduje sam.
```

### Do zrobienia przez analityka (logika dziedzinowa)

W `scripts/fetch_statsbomb.py` są dwa miejsca oznaczone jako placeholder:
- `player_rc_from_stats()` — wzór poziomu RC (0-100) z metryk StatsBomb,
- `league_handicap()` — handicap ligi per linia (% vs Ekstraklasa).

To decyzje analityczne (dobór metryk i wag), nie programistyczne — dlatego
zostały wydzielone. Reszta pipeline'u (pobieranie, mapowanie pozycji, zapis)
jest gotowa. Uwaga: StatsBomb nie podaje wartości rynkowej (`mv`) ani kontraktu —
te pola trzeba złączyć z innym źródłem lub uzupełnić ręcznie.

---

## Odświeżanie danych online (GitHub Actions, bez komputera)

Workflow `.github/workflows/refresh-data.yml` pozwala pobrać dane ze StatsBomb
i zregenerować `data.json` **w chmurze, jednym kliknięciem** — nic nie odpalasz
lokalnie.

### Konfiguracja (raz)

1. **Dodaj sekrety** w repo na GitHubie:
   Settings → Secrets and variables → Actions → **New repository secret**
   - `SB_USERNAME` = login StatsBomb (konto klubu)
   - `SB_PASSWORD` = hasło StatsBomb (najlepiej po rotacji)

   Sekrety są zaszyfrowane, niewidoczne w kodzie ani w logach.

2. **Uzupełnij `LEAGUE_CONFIG`** w `scripts/fetch_statsbomb.py` (competition_id /
   season_id) oraz wzory analityka — inaczej skrypt zatrzyma się z komunikatem.

### Uruchomienie (za każdym razem)

Zakładka **Actions** → „Odśwież dane ze StatsBomb" → **Run workflow**.

Akcja pobierze dane, zapisze nowy `public/data.json` do repo, a Netlify
przebuduje aplikację automatycznie. Brak harmonogramu = płatne API odpytywane
tylko wtedy, gdy sam klikniesz.

> Uwaga: umieszczając poświadczenia klubu w sekretach swojego repo, upewnij się,
> że masz na to zgodę klubu. Sekrety są bezpieczne technicznie, ale to dane firmowe.

---

## Handicapy + skład i wartości z Transfermarktu

Doszły trzy moduły w `scripts/`:

- **`handicap.py`** — PEŁNA, przetestowana metoda liczenia handicapów lig
  względem Ekstraklasy. Handicap = % odchylenia metryki danej linii (obrona /
  pomoc / atak) vs Ekstraklasa, przeliczone na skok RC (10% → RC+1). Analityk
  ustala tylko, **która metryka** reprezentuje linię (`LINE_METRICS`); matematyka
  jest gotowa. Test: `python scripts/handicap.py`.
- **`transfermarkt.py`** — pobiera skład Rakowa i wartości rynkowe przez
  publiczny egzemplarz `transfermarkt-api.fly.dev`. Test: `python scripts/transfermarkt.py`.
- **`fetch_statsbomb.py`** — spina wszystko: StatsBomb (metryki + handicapy),
  Transfermarkt (skład + ceny), zapisuje `data.json`.

### Ważne ograniczenia (świadomie zaakceptowane)

- Publiczny egzemplarz Transfermarktu jest **testowy i limitowany** — bywa wolny
  lub chwilowo niedostępny. Gdy zawiedzie, postaw własny (Docker, obraz z repo
  `felipeall/transfermarkt-api`) i podmień `BASE_URL` w `transfermarkt.py`.
- Transfermarkt to scraping (przez cudze API) — nieoficjalny, może przestać
  działać. Wartości rynkowe to nie ceny transakcyjne.
- Nadal jedna decyzja analityka: `LINE_METRICS` (które metryki = które linie)
  i `player_rc_from_stats` (wzór poziomu RC). Reszta pipeline'u jest gotowa.
