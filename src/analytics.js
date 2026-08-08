// ============================================================================
// analytics.js — czysta logika modułów decyzyjnych (BEZ Reacta, testowalna w node)
//
// Trzy moduły:
//   • computePriorities  — priorytety transferowe (luki w składzie wg 3-4-3)
//   • computeOkazje      — jakość za euro + lista okazji (percentyl jakości − ceny)
//   • computeRedFlags    — czerwone flagi składu (dla trenera / dyr. sportowego)
//
// Wszystkie funkcje działają na obiekcie `data` = { squad, pool, leagues, meta }
// dokładnie w formacie public/data.json. Pola wieku/kontraktu/wartości w SKŁADZIE
// są opcjonalne — funkcje degradują się łagodnie, gdy ich nie ma (pojawią się po
// wzbogaceniu składu w pipeline).
// ============================================================================
 
// --- mapy pomocnicze (spójne z App.jsx) ---
const LINE_MAP = { GK: "Bramka", RCB: "Obrona", CCB: "Obrona", LCB: "Obrona",
  RWB: "Obrona", LWB: "Obrona", DM: "Pomoc", CM: "Pomoc", AM: "Pomoc", ST: "Atak" };
 
export function lineOfPos(pos) {
  if (LINE_MAP[pos]) return LINE_MAP[pos];
  const s = String(pos || "").toUpperCase();
  if (s.includes("GK")) return "Bramka";
  if (/B$/.test(s) || s.includes("CB") || s === "RB" || s === "LB") return "Obrona";
  if (s.includes("ST") || s.includes("CF") || s === "FW") return "Atak";
  if (/[LR]?W$/.test(s) || s.includes("M")) return "Pomoc";
  return "Pomoc";
}
 
const pctToRC = (p) => Math.round((Number(p) || 0) / 10);
const num = (x) => (typeof x === "number" && isFinite(x) ? x : 0);
const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
 
// Rok odniesienia (kontrakty/wiek). Bierzemy z meta.generated, inaczej 2026.
export function currentYear(data) {
  const g = data && data.meta && data.meta.generated;
  const y = g && /^\d{4}/.test(g) ? parseInt(g.slice(0, 4), 10) : NaN;
  return Number.isFinite(y) ? y : 2026;
}
 
// Indeks handicapów lig → { [lg]: {Bramka,Obrona,Pomoc,Atak} }
function leaguesIndex(leagues) {
  const idx = {};
  for (const l of leagues || []) idx[l.lg] = l;
  return idx;
}
 
// Poziom skorygowany o handicap ligi (mirror App.adjusted): raw + pctToRC(hc)*2
export function adjLevel(p, lgIdx) {
  const line = lineOfPos(p.pos);
  const lg = lgIdx[p.lg];
  const hc = num(lg ? lg[line] : 0);
  return num(p.raw) + pctToRC(hc) * 2;
}
 
// ============================================================================
// GRUPY POTRZEB — z formacji 3-4-3. `starters` = ilu pierwszoskładowych wymaga
// układ na danej pozycji. `pos` = kody pozycji kwalifikujące do grupy.
// ============================================================================
export const POS_NEEDS = [
  { key: "GK", label: "Bramkarz",            line: "Bramka", pos: ["GK"],        starters: 1 },
  { key: "CB", label: "Środkowy obrońca",    line: "Obrona", pos: ["CB"],        starters: 3 },
  { key: "WB", label: "Wahadłowy",           line: "Obrona", pos: ["WB", "WM"],  starters: 2 },
  { key: "CM", label: "Środkowy pomocnik",   line: "Pomoc",  pos: ["DM", "CM"],  starters: 2 },
  { key: "AM", label: "Ofensywny pomocnik",  line: "Pomoc",  pos: ["AM"],        starters: 1 },
  { key: "W",  label: "Skrzydłowy",          line: "Pomoc",  pos: ["W"],         starters: 2 },
  { key: "ST", label: "Napastnik",           line: "Atak",   pos: ["ST"],        starters: 1 },
];
 
// Progi wieku „schyłkowego" per linia (orientacyjne).
const AGE_DECLINE = { Bramka: 34, Obrona: 31, Pomoc: 30, Atak: 30 };
// Poziom RC uznawany za „pewny pierwszy skład". Poniżej — luka jakościowa.
const QUALITY_TARGET = 55;
 
// ---------------------------------------------------------------------------
// PRIORYTETY TRANSFEROWE
// Dla każdej grupy potrzeb liczymy pilność (0-100) z 4 składowych:
//   • braki   — ilu PEWNYCH (nie b.d.) zawodników brakuje do liczby miejsc,
//   • jakość  — o ile najlepszy poziom w grupie jest poniżej progu,
//   • niepewność — udział zawodników bez danych (b.d.),
//   • ryzyko  — udział zawodników z wygasającym kontraktem / w wieku schyłkowym
//               (liczone tylko, gdy skład ma pola wiek/kontrakt).
// Zwraca listę grup posortowaną malejąco po pilności, z powodami i propozycjami.
// ---------------------------------------------------------------------------
export function computePriorities(data, opts = {}) {
  const { squad = [], pool = [], leagues = [] } = data;
  const lgIdx = leaguesIndex(leagues);
  const cur = currentYear(data);
  const maxTargets = opts.maxTargets || 4;
  const targetMaxAge = opts.targetMaxAge || 27;
 
  const W = { shortage: 40, quality: 25, uncertainty: 20, risk: 15 };
  const hasContract = squad.some((s) => s.contract);
  const hasAge = squad.some((s) => s.age);
 
  const rows = POS_NEEDS.map((g) => {
    const members = squad.filter((s) => g.pos.includes(s.pos));
    const reliable = members.filter((s) => !s.rc_estimated);
    const estimated = members.filter((s) => s.rc_estimated);
    const bestRc = reliable.length ? Math.max(...reliable.map((s) => num(s.rc))) : null;
 
    // składowe (0..1)
    const shortage = clamp((g.starters - reliable.length) / g.starters, 0, 1);
    const qualityGap = bestRc == null ? 0.5 : clamp((QUALITY_TARGET - bestRc) / 25, 0, 1);
    const uncertainty = members.length ? estimated.length / members.length : 1;
 
    // ryzyko kontrakt/wiek — tylko gdy skład wzbogacony
    let risky = [];
    if (hasContract || hasAge) {
      risky = members.filter((s) =>
        (s.contract && s.contract <= cur + 1) ||
        (s.age && s.age >= (AGE_DECLINE[g.line] || 31)));
    }
    const risk = members.length ? risky.length / members.length : 0;
 
    const urgency = Math.round(
      100 * (W.shortage * shortage + W.quality * qualityGap +
             W.uncertainty * uncertainty + W.risk * risk) /
      (W.shortage + W.quality + W.uncertainty + W.risk));
 
    // powody (czytelne)
    const reasons = [];
    if (reliable.length < g.starters)
      reasons.push({ sev: "high",
        text: `Tylko ${reliable.length} pewnych zawodników na ${g.starters} miejsc w składzie` });
    if (bestRc != null && bestRc < QUALITY_TARGET)
      reasons.push({ sev: "med", text: `Najwyższy poziom w grupie to ${bestRc} — poniżej progu pierwszego składu` });
    if (bestRc == null)
      reasons.push({ sev: "med", text: `Brak zawodnika z policzonym poziomem — jakości nie da się ocenić` });
    if (estimated.length)
      reasons.push({ sev: "low", text: `${estimated.length} zawodnik(ów) bez danych meczowych (b.d.)` });
    if (risky.length)
      reasons.push({ sev: "med",
        text: `${risky.length} zawodnik(ów) z wygasającym kontraktem lub w wieku schyłkowym` });
 
    // propozycje z puli: ta sama pozycja, młodsi, najlepszy skorygowany poziom
    const targets = pool
      .filter((p) => g.pos.includes(p.pos) && p.name && p.name !== "?" && !p.level_estimated)
      .filter((p) => !p.age || p.age <= targetMaxAge)
      .map((p) => ({ p, adj: adjLevel(p, lgIdx) }))
      .sort((a, b) => b.adj - a.adj)
      .slice(0, maxTargets)
      .map(({ p, adj }) => ({
        id: p.id, name: p.name, lg: p.lg, pos: p.pos, age: p.age || null,
        mv: num(p.mv), contract: p.contract || null, adj, coherence: num(p.coherence),
      }));
 
    return {
      key: g.key, label: g.label, line: g.line, starters: g.starters,
      depth: members.length, reliableDepth: reliable.length, estimatedDepth: estimated.length,
      bestRc, urgency, reasons, targets,
      members: members.map((s) => ({
        id: s.id, name: s.name, pos: s.pos, rc: s.rc, rc_estimated: !!s.rc_estimated,
        age: s.age || null, contract: s.contract || null, mv: num(s.mv) || null,
      })),
    };
  });
 
  rows.sort((a, b) => b.urgency - a.urgency);
  return { rows, hasContract, hasAge, cur };
}
 
// ---------------------------------------------------------------------------
// JAKOŚĆ ZA EURO / OKAZJE
// W obrębie każdej pozycji liczymy percentyl JAKOŚCI (skorygowany poziom) oraz
// percentyl CENY (wartość rynkowa). Okazja = jakość wysoka + cena niska:
//   okazjaScore = qPct − pPct   (zakres −100..100; im wyżej, tym lepszy stosunek)
// Dodatkowo: vfm = poziom na 1 mln € oraz znacznik wygasającego kontraktu.
// ---------------------------------------------------------------------------
export function computeOkazje(data, opts = {}) {
  const { pool = [], leagues = [] } = data;
  const lgIdx = leaguesIndex(leagues);
  const cur = currentYear(data);
  const minLevel = opts.minLevel || 0;
 
  // tylko wycenieni, z realnym poziomem i nazwą
  const priced = pool.filter((p) =>
    num(p.mv) > 0 && num(p.raw) > 0 && !p.level_estimated && p.name && p.name !== "?");
 
  // percentyle liczymy w obrębie pozycji (porównujemy jak z jak)
  const byPos = {};
  for (const p of priced) (byPos[p.pos] || (byPos[p.pos] = [])).push(p);
 
  const pctRank = (sortedVals, v) => {
    // percentyl (0..100) wartości v w posortowanej rosnąco tablicy
    if (sortedVals.length <= 1) return 50;
    let lo = 0;
    for (const x of sortedVals) { if (x < v) lo++; else break; }
    // liczba mniejszych / (n-1)
    let less = 0, equal = 0;
    for (const x of sortedVals) { if (x < v) less++; else if (x === v) equal++; }
    return clamp(((less + equal / 2) / sortedVals.length) * 100, 0, 100);
  };
 
  const out = [];
  for (const pos of Object.keys(byPos)) {
    const grp = byPos[pos];
    const adjs = grp.map((p) => adjLevel(p, lgIdx)).sort((a, b) => a - b);
    const mvs = grp.map((p) => num(p.mv)).sort((a, b) => a - b);
    for (const p of grp) {
      const adj = adjLevel(p, lgIdx);
      if (adj < minLevel) continue;
      const qPct = pctRank(adjs, adj);
      const pPct = pctRank(mvs, num(p.mv));
      const okazja = Math.round(qPct - pPct);
      out.push({
        id: p.id, name: p.name, lg: p.lg, pos: p.pos, age: p.age || null,
        mv: num(p.mv), contract: p.contract || null,
        raw: num(p.raw), adj: Math.round(adj),
        coherence: num(p.coherence), coherence_ref: p.coherence_ref || null,
        qPct: Math.round(qPct), pPct: Math.round(pPct), okazja,
        vfm: num(p.mv) > 0 ? adj / num(p.mv) : 0,
        expiring: !!(p.contract && p.contract <= cur + 1),
      });
    }
  }
  out.sort((a, b) => b.okazja - a.okazja || b.adj - a.adj);
  return out;
}
 
// Wygasające kontrakty — potencjalnie tani/wolni zawodnicy (do 1 rok do końca).
// Sortowane po skorygowanym poziomie. Zwraca też nieco droższych, ale w ostatnim roku.
export function computeExpiring(data, opts = {}) {
  const { pool = [], leagues = [] } = data;
  const lgIdx = leaguesIndex(leagues);
  const cur = currentYear(data);
  const minLevel = opts.minLevel || 0;
  return pool
    .filter((p) => p.contract && p.contract <= cur + 1 && !p.level_estimated
      && p.name && p.name !== "?")
    .map((p) => ({
      id: p.id, name: p.name, lg: p.lg, pos: p.pos, age: p.age || null,
      mv: num(p.mv), contract: p.contract,
      adj: Math.round(adjLevel(p, lgIdx)), raw: num(p.raw),
      free: p.contract <= cur, // kończy się w tym roku → potencjalnie wolny transfer
    }))
    .filter((r) => r.adj >= minLevel)
    .sort((a, b) => b.adj - a.adj);
}
 
// ---------------------------------------------------------------------------
// CZERWONE FLAGI SKŁADU (dla trenera / dyrektora sportowego)
// Per zawodnik składu zbieramy flagi ryzyka:
//   • contract  — wygasający kontrakt (do 1 rok),
//   • age       — wiek schyłkowy per linia,
//   • level     — poziom wyraźnie poniżej mediany swojej linii,
//   • nodata    — brak danych meczowych (b.d.) → nie można ocenić,
//   • valuedrop — wartość rynkowa mocno poniżej szczytu (jeśli znany).
// Zwraca zawodników z ≥1 flagą, posortowanych po wadze flag.
// ---------------------------------------------------------------------------
const SEV_W = { high: 3, med: 2, low: 1 };
 
export function computeRedFlags(data, opts = {}) {
  const { squad = [], leagues = [] } = data;
  const cur = currentYear(data);
  const valueDropRatio = opts.valueDropRatio || 0.6;
 
  // mediana poziomu (RC) pewnych zawodników per linia — benchmark „poniżej średniej"
  const lineRc = {};
  for (const s of squad) {
    if (s.rc_estimated) continue;
    (lineRc[s.line] || (lineRc[s.line] = [])).push(num(s.rc));
  }
  const median = (a) => {
    if (!a.length) return null;
    const x = [...a].sort((p, q) => p - q); const m = Math.floor(x.length / 2);
    return x.length % 2 ? x[m] : (x[m - 1] + x[m]) / 2;
  };
  const lineMed = {};
  for (const k of Object.keys(lineRc)) lineMed[k] = median(lineRc[k]);
 
  const hasContract = squad.some((s) => s.contract);
  const hasAge = squad.some((s) => s.age);
  const hasPeak = squad.some((s) => s.peak);
 
  const players = [];
  for (const s of squad) {
    const flags = [];
    const line = s.line || lineOfPos(s.pos);
 
    if (s.contract && s.contract <= cur + 1) {
      flags.push({ code: "contract", sev: s.contract <= cur ? "high" : "med",
        label: "Wygasający kontrakt",
        detail: `Umowa do ${s.contract}${s.contract <= cur ? " — ostatni rok, decyzja pilna" : ""}` });
    }
    if (s.age && s.age >= (AGE_DECLINE[line] || 31)) {
      flags.push({ code: "age", sev: s.age >= (AGE_DECLINE[line] || 31) + 2 ? "high" : "med",
        label: "Wiek schyłkowy",
        detail: `${s.age} lat — planuj następcę / monitoruj spadek formy` });
    }
    const benchmark = lineMed[line];
    if (!s.rc_estimated && benchmark != null && num(s.rc) < benchmark - 8) {
      flags.push({ code: "level", sev: "med", label: "Poziom poniżej linii",
        detail: `Poziom ${s.rc} vs mediana linii ${Math.round(benchmark)} — obserwuj formę` });
    }
    if (s.rc_estimated) {
      flags.push({ code: "nodata", sev: "low", label: "Brak danych meczowych",
        detail: "Za mała próbka — poziomu nie policzono; monitoruj po zebraniu minut" });
    }
    if (s.peak && s.mv && num(s.mv) < num(s.peak) * valueDropRatio) {
      flags.push({ code: "valuedrop", sev: "med", label: "Spadek wartości",
        detail: `Wartość €${num(s.mv).toFixed(1)}M vs szczyt €${num(s.peak).toFixed(1)}M` });
    }
 
    if (flags.length) {
      const score = flags.reduce((a, f) => a + (SEV_W[f.sev] || 1), 0);
      players.push({
        id: s.id, name: s.name, pos: s.pos, line, rc: s.rc, rc_estimated: !!s.rc_estimated,
        age: s.age || null, contract: s.contract || null, mv: num(s.mv) || null,
        peak: num(s.peak) || null, flags, score,
      });
    }
  }
  players.sort((a, b) => b.score - a.score || b.flags.length - a.flags.length);
 
  // podsumowanie liczbowe (do kafelków)
  const counts = { contract: 0, age: 0, level: 0, nodata: 0, valuedrop: 0 };
  for (const p of players) for (const f of p.flags) counts[f.code]++;
 
  return { players, counts, hasContract, hasAge, hasPeak, cur, total: squad.length };
}
 
// ---------------------------------------------------------------------------
// MULTIKOLINEARNOŚĆ metryk stylu (odpowiedź na audyt, p. 6)
// Korelacja (Pearson) 17 wymiarów profilu stylu, liczona z profili WSZYSTKICH
// zawodników puli, PARAMI, z pominięciem strukturalnych zer (brak fizyki/GI = 0,
// nie zaniża sztucznie). Zwraca macierz r, próby, klastry redundancji (|r|>=thr)
// i najsilniejsze pary. Wszystko liczone na froncie z data.json — bez pipeline.
// ---------------------------------------------------------------------------
export const STYLE_DIM_LABELS = [
  "Podania (wol.)", "Celność podań", "Podania do przodu", "Podania w tercji at.",
  "Odbiory+przechwyty", "Gra w powietrzu", "Drybling", "Podania kluczowe", "xA",
  "xG", "xGChain", "Dystans/intens.", "Sprinty", "Prędkość maks.", "Biegi bez piłki",
  "Śr. dł. podania", "Zaang. z piłką",
];
 
export function computeStyleCorrelations(pool, opts = {}) {
  const N = STYLE_DIM_LABELS.length;
  const minN = opts.minN || 50;
  const thr = opts.thr || 0.7;
  const vecs = (pool || []).map((p) => p.profile).filter((v) => Array.isArray(v) && v.length === N);
  const M = Array.from({ length: N }, () => Array(N).fill(null));
  const NN = Array.from({ length: N }, () => Array(N).fill(0));
  for (let i = 0; i < N; i++) {
    for (let j = i; j < N; j++) {
      if (i === j) { M[i][j] = 1; NN[i][j] = vecs.length; continue; }
      const xs = [], ys = [];
      for (const v of vecs) { const a = v[i], b = v[j]; if (a !== 0 && b !== 0) { xs.push(a); ys.push(b); } }
      const n = xs.length; NN[i][j] = NN[j][i] = n;
      if (n < minN) continue;
      const mx = xs.reduce((s, x) => s + x, 0) / n, my = ys.reduce((s, y) => s + y, 0) / n;
      let sx = 0, sy = 0, cov = 0;
      for (let k = 0; k < n; k++) { const dx = xs[k] - mx, dy = ys[k] - my; sx += dx * dx; sy += dy * dy; cov += dx * dy; }
      M[i][j] = M[j][i] = (sx > 0 && sy > 0) ? cov / Math.sqrt(sx * sy) : null;
    }
  }
  // klastry redundancji = spójne składowe grafu par |r|>=thr
  const adj = Array.from({ length: N }, () => new Set());
  for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
    const r = M[i][j]; if (r !== null && Math.abs(r) >= thr) { adj[i].add(j); adj[j].add(i); }
  }
  const seen = new Set(), clusters = [];
  for (let i = 0; i < N; i++) {
    if (seen.has(i) || adj[i].size === 0) continue;
    const comp = [], stack = [i];
    while (stack.length) {
      const x = stack.pop(); if (comp.includes(x)) continue;
      comp.push(x); seen.add(x); for (const y of adj[x]) if (!comp.includes(y)) stack.push(y);
    }
    if (comp.length > 1) clusters.push(comp.sort((a, b) => a - b));
  }
  const pairs = [];
  for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
    const r = M[i][j]; if (r !== null) pairs.push({ i, j, r, ar: Math.abs(r) });
  }
  pairs.sort((a, b) => b.ar - a.ar);
  return { N, labels: STYLE_DIM_LABELS, M, NN, clusters, topPairs: pairs.slice(0, 10), count: vecs.length };
}
 
// ============================================================================
// WALIDACJA NA OSTATNICH MECZACH — mecz jako walidator RC i preferencji trenera.
// Wejście: data.recent (z pipeline'u) + data.squad. Zasada uczciwości:
//   • MINUTY = ujawniona preferencja trenera (kto realnie gra). To główny walidator.
//   • OUTPUT per 90 = miękka walidacja RC (mała próba → tylko sygnał, nie wyrok).
//   • KOHERENCJI mecz NIE waliduje wprost (to podobieństwo stylu MIĘDZY zawodnikami,
//     nie wielkość meczowa) — walidujemy ją pośrednio: XI, które trener realnie
//     wystawia, to właśnie zestaw opisywany przez nasz ekran koherencji składu.
// Zwraca gotowe do renderu: per-zawodnik role+sygnały+werdykt oraz rekomendacje
// (rotacje / punkty do obserwacji). Czysta funkcja — testowalna w node.
// ============================================================================
 
// Progi udziału minut (share = minuty / (n_meczów*90)).
const SHARE_CORE = 0.6;   // filar
const SHARE_ROT = 0.25;   // rotacja (poniżej = rezerwa)
const RC_GOOD = 65;       // "wysoki RC" — model uważa za jakość
const RC_WEAK = 55;       // "niski RC"
 
function _sig(type, sev, text) { return { type, sev, text }; }
 
export function computeRecentValidation(data, opts = {}) {
  const rec = data && data.recent;
  if (!rec || rec.available === false || !Array.isArray(rec.players) || !rec.players.length) {
    return { available: false, reason: (rec && rec.reason) || "no_data" };
  }
  const nM = rec.n_matches || (Array.isArray(rec.matches) ? rec.matches.length : 5);
  const avail = num(rec.team && rec.team.minutes_available) || nM * 90;
 
  // Indeks składu po id/nazwie — dołączamy RC/wiek/pozycję, gdyby pipeline nie dołączył.
  const squad = Array.isArray(data.squad) ? data.squad : [];
  const byId = {}, byName = {};
  for (const s of squad) {
    if (s.id) byId[s.id] = s;
    byName[(s.name || "").toLowerCase()] = s;
  }
 
  const players = rec.players.map((p) => {
    const s = (p.id && byId[p.id]) || byName[(p.name || "").toLowerCase()] || null;
    const rc = num(p.rc != null ? p.rc : (s ? s.rc : 0));
    const rcEst = p.rc_estimated != null ? p.rc_estimated : (s ? !!s.rc_estimated : false);
    const line = p.line || (s ? s.line : lineOfPos(p.pos));
    const mins = num(p.minutes);
    const share = num(p.share != null ? p.share : (avail ? mins / avail : 0));
    const st = p.stats || {};
    const per90 = (v) => (mins > 0 ? (num(v) / mins) * 90 : 0);
    const gc = num(st.goals) + num(st.assists);            // realne gole+asysty
    const gc90 = per90(gc);
    const xgi90 = per90(num(st.np_xg) + num(st.xa));        // oczekiwane zaangażowanie
    const def90 = per90(num(st.tackles) + num(st.interceptions));
 
    const role = share >= SHARE_CORE ? "filar" : (share >= SHARE_ROT ? "rotacja" : "rezerwa");
    const offensive = line === "Atak" || ["AM", "W", "ST"].includes(p.pos);
    const defensive = line === "Obrona" || p.pos === "DM";
    const enoughMin = mins >= 180; // ~2 pełne mecze — minimum, by w ogóle komentować output
 
    const signals = [];
    // --- Zgodność modelu (RC) z preferencją trenera (minuty) ---
    if (rc >= RC_GOOD && role === "filar" && !rcEst) {
      signals.push(_sig("confirmed", "ok",
        "Model i trener zgodni — wysoki RC i pełne minuty. Filar potwierdzony."));
    }
    if (rc >= RC_GOOD && share < SHARE_ROT && !rcEst) {
      signals.push(_sig("underused", "med",
        "Wysoki RC, a mało minut — kandydat do większej roli / punkt do obserwacji."));
    }
    if (role === "filar" && (rcEst || rc < RC_WEAK)) {
      signals.push(_sig("trusted", "med",
        rcEst
          ? "Trener stawia na niego mimo braku pewnego RC (mała próba) — model może go niedoszacowywać."
          : "Trener ufa mimo niskiego RC — sprawdź, czy model nie pomija jego roli w systemie."));
    }
    // --- Miękka walidacja RC realnym outputem (tylko przy sensownej próbie) ---
    if (enoughMin && offensive) {
      if (gc90 <= 0 && xgi90 < 0.25 && rc >= RC_GOOD) {
        signals.push(_sig("output_low", "med",
          "Wysoki RC, ale zero realnej produkcji ofensywnej w ostatnich meczach — obserwuj formę."));
      } else if (gc90 >= 0.6) {
        signals.push(_sig("output_high", "ok",
          "Mocna produkcja ofensywna (g+a/90) — realny output potwierdza RC."));
      } else if (gc90 >= 0.4 && rc < RC_GOOD) {
        signals.push(_sig("output_over", "ok",
          "Produkcja wyższa, niż sugeruje RC — obserwuj, czy to trend, czy krótka forma."));
      }
    }
    if (enoughMin && defensive && def90 >= 4 && rc < RC_GOOD) {
      signals.push(_sig("output_over", "ok",
        "Wysoka aktywność obronna (odbiory+przechwyty/90) mimo umiarkowanego RC — obserwuj."));
    }
 
    // Werdykt jednym słowem do etykiety na froncie.
    let verdict = "neutral";
    if (signals.some((x) => x.type === "confirmed" || x.type === "output_high")) verdict = "ok";
    if (signals.some((x) => x.type === "underused" || x.type === "output_low")) verdict = "watch";
    if (signals.some((x) => x.type === "trusted")) verdict = "trusted";
 
    return {
      name: p.name, id: p.id, pos: p.pos, line, rc, rcEstimated: rcEst,
      minutes: Math.round(mins), matchesPlayed: p.matches_played || 0,
      starts: p.starts || 0, share, role,
      gc: Math.round(gc), gc90: +gc90.toFixed(2), xgi90: +xgi90.toFixed(2),
      def90: +def90.toFixed(2), stats: st, inSquad: p.in_squad !== false && !!s,
      signals, verdict,
    };
  });
 
  players.sort((a, b) => b.minutes - a.minutes);
 
  // --- Rekomendacje: rotacje (obciążenie) + obserwacje (rozjazd model↔trener) ---
  const rotate = [], observe = [];
  for (const pl of players) {
    const s = (pl.id && byId[pl.id]) || byName[(pl.name || "").toLowerCase()];
    const age = s && s.age ? num(s.age) : 0;
    // Rotacja: pełne obciążenie we WSZYSTKICH meczach (>=90% minut, komplet startów).
    if (pl.share >= 0.9 && pl.starts >= nM) {
      const heavy = age >= 30;
      rotate.push({
        name: pl.name, pos: pl.pos, minutes: pl.minutes,
        reason: heavy
          ? `Komplet minut (${pl.starts}/${nM}) przy wieku ${age} — rozważ rotację dla świeżości.`
          : `Komplet minut (${pl.starts}/${nM}) — brak oddechu, monitoruj obciążenie.`,
        sev: heavy ? "med" : "low",
      });
    }
    // Obserwacje: rozjazd między RC a rolą.
    for (const sig of pl.signals) {
      if (sig.type === "underused" || sig.type === "trusted" || sig.type === "output_low" || sig.type === "output_over") {
        observe.push({ name: pl.name, pos: pl.pos, rc: pl.rc, reason: sig.text, sev: sig.sev });
        break;
      }
    }
  }
 
  const team = rec.team || {};
  const points = num(team.points), ppg = nM ? +(points / nM).toFixed(2) : 0;
  return {
    available: true,
    generated: rec.generated || (data.meta && data.meta.generated) || "",
    nMatches: nM,
    matches: Array.isArray(rec.matches) ? rec.matches : [],
    team: { ...team, ppg },
    players,
    recommendations: { rotate, observe },
    note: rec.note || "",
  };
}
 
 
