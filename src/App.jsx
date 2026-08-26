import React, { useState, useEffect, useMemo } from "react";
import { computePriorities, computeOkazje, computeExpiring, computeRedFlags, computeStyleCorrelations, computeRecentValidation, adjLevel } from "./analytics.js";

// ============================ TOKENS ============================
const C = {
  // Paleta w duchu rakow.com — głęboki granat + czerwień + biel.
  ink: "#081733", panel: "#0E2246", panel2: "#14315F", panelHi: "#1B406F",
  line: "#23426F", bone: "#F3F6FB", steel: "#7C90B0", steelHi: "#AAB9D4",
  red: "#E4022B", redHi: "#FF2D4E", redDim: "#3A0A1C",
  good: "#37D08A", warn: "#E8A13A", bad: "#E5544B", proxy: "#E8C15A",
  blue: "#1F5FCE", blueHi: "#3E7BEC",
};

const pctToRC = (p) => Math.round((Number(p) || 0) / 10);
const tmUrl = (name) => `https://www.transfermarkt.com/schnellsuche/ergebnis/schnellsuche?query=${encodeURIComponent(name || "")}`;
// Mnożnik poziomu rynkowego ligi do estymacji ceny (heurystyka: droższe ligi = wyższy
// mnożnik). Nazwy MUSZĄ zgadzać się z LEAGUE_CONFIG (wcześniej były nieaktualne —
// „Championship (EN)"/„Liga Portugalska" — przez co mnożnik dla większości lig = 1).
const LIG_TIER = {
  "Eredivisie (NL)": 1.15, "Primeira Liga (PT)": 1.15, "Jupiler Pro League (BE)": 1.10,
  "2. Bundesliga (DE)": 1.05, "Super League (CH)": 1.00, "Bundesliga (AT)": 0.95,
  "Ekstraklasa (PL)": 0.95, "Superliga (DK)": 0.95, "Czech Liga (CZ)": 0.90,
  "Eliteserien (NO)": 0.90, "Super League (GR)": 0.90, "Liga I (RO)": 0.85,
  "1. HNL (HR)": 0.85, "Super Liga (RS)": 0.80, "Niké Liga (SK)": 0.78,
  "1. SNL (SI)": 0.75, "First League (BG)": 0.75,
};

// ============================ WATCHLISTA (localStorage) ============================
// Trwała lista obserwowanych — per przeglądarka (nie współdzielona; upgrade do backendu
// możliwy później bez utraty danych). Wpis: id -> {s:status, n:notatka, nm,pos,lg,mv,ts}.
// Statusy: "obserwowany" | "sprawdzic" | "odrzucony". To ich własna apka (nie artefakt),
// więc localStorage działa normalnie.
const WATCH_KEY = "rk_watch_v1";
const WATCH_STATUSES = {
  obserwowany: { label: "Obserwowany", short: "obs.", icon: "★" },
  sprawdzic:   { label: "Do sprawdzenia", short: "sprawdź", icon: "?" },
  odrzucony:   { label: "Odrzucony", short: "odrzuc.", icon: "✕" },
};
function _loadWatch() {
  try { return JSON.parse(localStorage.getItem(WATCH_KEY)) || {}; } catch { return {}; }
}
function useWatchlist() {
  const [wl, setWl] = useState(_loadWatch);
  useEffect(() => {
    try { localStorage.setItem(WATCH_KEY, JSON.stringify(wl)); } catch { /* quota/prywatny tryb */ }
  }, [wl]);
  // item = {id, name, pos, lg, mv}; status=null usuwa wpis.
  const setStatus = (item, status) => setWl((w) => {
    const id = item.id; if (!id) return w;
    const next = { ...w };
    if (!status) { delete next[id]; return next; }
    const prev = next[id] || {};
    next[id] = { ...prev, s: status,
      nm: item.name || prev.nm || "", pos: item.pos || prev.pos || "",
      lg: item.lg || prev.lg || "", mv: Number(item.mv) || prev.mv || 0,
      ts: Date.now() };
    return next;
  });
  const setNote = (id, note) => setWl((w) => (w[id] ? { ...w, [id]: { ...w[id], n: note } } : w));
  return { wl, setStatus, setNote };
}
const LINE_MAP = { GK: "Bramka", RCB: "Obrona", CCB: "Obrona", LCB: "Obrona", RWB: "Obrona",
  LWB: "Obrona", DM: "Pomoc", CM: "Pomoc", AM: "Pomoc", ST: "Atak" };
const lineOfPos = (pos) => {
  if (LINE_MAP[pos]) return LINE_MAP[pos];
  const s = String(pos || "").toUpperCase();
  if (s.includes("GK")) return "Bramka";
  if (/B$/.test(s) || s.includes("CB") || s === "RB" || s === "LB") return "Obrona";
  if (s.includes("ST") || s.includes("CF") || s === "FW") return "Atak";
  if (/[LR]?W$/.test(s) || s.includes("M")) return "Pomoc";
  return "Pomoc";
};
const mean = (a) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : 0);

// Dopasowanie nazwisk zdjęć (photos.json z rakow.com) do nazwisk w składzie.
// Klub bywa pełniejszy ("Efstratios Svarnas" vs "Stratos Svarnas",
// "Jean Carlos Silva Rocha" vs "Jean Carlos Silva"), więc dopasowujemy po
// nakładaniu się tokenów (bez ogonków), a nie po dokładnym stringu.
function _nameTokens(s) {
  return (s || "")
    .replace(/[łŁ]/g, "l").replace(/[øØ]/g, "o")
    .replace(/[đðĐ]/g, "d").replace(/ß/g, "ss")
    .replace(/[æÆ]/g, "ae").replace(/[œŒ]/g, "oe")
    .normalize("NFD").replace(/[̀-ͯ]/g, "")
    .toLowerCase().replace(/[^a-z\s-]/g, " ").split(/[\s-]+/).filter(Boolean);
}
function makePhotoResolver(photos) {
  const entries = Object.entries(photos || {}).map(([name, url]) => ({ url, tk: _nameTokens(name) }));
  return (name) => {
    if (!name) return null;
    if (photos && photos[name]) return photos[name];
    const pn = _nameTokens(name);
    if (!pn.length) return null;
    const plast = pn[pn.length - 1];
    let best = null, bestScore = 0;
    for (const e of entries) {
      const set = new Set(e.tk);
      let shared = 0;
      for (const t of pn) if (set.has(t)) shared++;
      const lastEq = e.tk[e.tk.length - 1] === plast;
      const single = pn.length === 1 && set.has(pn[0]);
      if (!(shared >= 2 || lastEq || single)) continue;
      const score = shared + (lastEq ? 0.5 : 0) + (single ? 0.25 : 0);
      if (score > bestScore) { bestScore = score; best = e.url; }
    }
    return best;
  };
}

// Etykiety profilu stylu — KOLEJNOŚĆ musi zgadzać się z UNIVERSAL_STYLE
// w scripts/coherence.py (wektor "profile" w data.json). Wartości to z-score
// względem Ekstraklasy: >0 = powyżej średniej ligi, <0 = poniżej.
const STYLE_LABELS = [
  "Podania (wolumen)", "Celność podań", "Podania do przodu", "Podania w tercji ataku",
  "Odbiory i przechwyty", "Gra w powietrzu", "Drybling", "Podania kluczowe",
  "Asysty oczekiwane (xA)", "Groźność pod bramką (xG)", "Udział w akcjach (xGChain)",
  "Dystans / intensywność", "Liczba sprintów", "Prędkość maksymalna", "Biegi bez piłki",
  "Śr. długość podania", "Zaangażowanie z piłką",
];

// Formacja 3-4-3. Kolejność = priorytet obsadzania (najpierw najwęższe pule:
// bramka, środek obrony, napastnik). x/y = pozycja na boisku w % (y: 0=góra/atak).
const FORMATION_343 = [
  { id: "GK",  label: "GK",  line: "Bramka", pos: ["GK"],        x: 50, y: 90 },
  { id: "LCB", label: "LCB", line: "Obrona", pos: ["CB"],        x: 27, y: 70 },
  { id: "CCB", label: "CB",  line: "Obrona", pos: ["CB"],        x: 50, y: 73 },
  { id: "RCB", label: "RCB", line: "Obrona", pos: ["CB"],        x: 73, y: 70 },
  { id: "ST",  label: "ST",  line: "Atak",   pos: ["ST"],        x: 50, y: 13 },
  { id: "LWB", label: "LWB", line: "Obrona", pos: ["WB", "WM"],  x: 10, y: 45 },
  { id: "RWB", label: "RWB", line: "Obrona", pos: ["WB", "WM"],  x: 90, y: 45 },
  { id: "LCM", label: "CM",  line: "Pomoc",  pos: ["DM", "CM"],  x: 37, y: 49 },
  { id: "RCM", label: "CM",  line: "Pomoc",  pos: ["CM", "DM", "AM"], x: 63, y: 49 },
  { id: "LW",  label: "LW",  line: "Pomoc",  pos: ["W", "AM"],   x: 21, y: 23 },
  { id: "RW",  label: "RW",  line: "Pomoc",  pos: ["W", "AM"],   x: 79, y: 23 },
];

export default function App() {
  const [data, setData] = useState(null);
  const [photos, setPhotos] = useState({});   // { "Imię Nazwisko": url } z public/photos.json
  const [navOpen, setNavOpen] = useState(false);   // szuflada menu na mobile
  const [err, setErr] = useState(null);
  const [view, setView] = useState("twin");
  const [sel, setSel] = useState(null);
  const [loading, setLoading] = useState(false);
  const [sortBy, setSortBy] = useState("coherence");
  // Watchlista (localStorage). „short" = obserwowani (zgodność ze starą gwiazdką).
  const { wl, setStatus, setNote } = useWatchlist();
  const short = useMemo(() => Object.keys(wl).filter((id) => wl[id].s === "obserwowany"), [wl]);
  // toggleShort przyjmuje OBIEKT zawodnika (żeby zapisać meta do watchlisty offline).
  const toggleShort = (item) => setStatus(item, wl[item.id] && wl[item.id].s === "obserwowany" ? null : "obserwowany");
  const [query, setQuery] = useState("");   // wyszukiwarka ręczna (po nazwisku, cała pula)
  // --- FILTRY kandydatów (widok "Odpowiednicy") ---
  const FILTERS_DEFAULT = {
    ageMin: 16, ageMax: 45,
    priceMax: 50,          // mln EUR; 50 = bez ograniczenia
    showUnpriced: true,    // wariant C: pokazywać kandydatów bez wyceny
    cohMin: 0,             // minimalna koherencja %
    levelMin: 0,           // minimalny poziom
    onlyReliable: false,   // ukryj kandydatów z niepełnymi danymi
    leagues: [],           // [] = wszystkie
  };
  // Filtry aplikowane na przycisk „Szukaj": draft = edycja, filters = zastosowane.
  const [filters, setFilters] = useState(FILTERS_DEFAULT);
  const [draft, setDraft] = useState(FILTERS_DEFAULT);
  const [filtersOpen, setFiltersOpen] = useState(true);   // filtry (wiek/cena) widoczne od razu
  const setF = (patch) => setDraft((f) => ({ ...f, ...patch }));
  const applyFilters = () => setFilters(draft);
  const resetFilters = () => { setDraft(FILTERS_DEFAULT); setFilters(FILTERS_DEFAULT); };
  const filtersDirty = JSON.stringify(draft) !== JSON.stringify(filters);

  useEffect(() => { loadData("data.json"); }, []);

  function loadData(url, live = false) {
    setLoading(true); setErr(null);
    fetch(url)
      .then((r) => {
        const ct = r.headers.get("content-type") || "";
        if (!r.ok || !ct.includes("json")) throw new Error(`Zła odpowiedź (${r.status})`);
        return r.json();
      })
      .then((d) => {
        const ok = d && Array.isArray(d.squad) && d.squad.length > 0
          && Array.isArray(d.leagues) && Array.isArray(d.pool)
          && d.correlations && typeof d.correlations === "object";
        if (!ok) throw new Error("Niekompletne dane");
        // Deduplikacja puli: ten sam zawodnik potrafi wystąpić w dwóch ligach
        // (transfer w trakcie sezonu) → zostawiamy jeden wpis, z wyższym poziomem
        // (a przy remisie — ten z wyceną). Naprawia duplikaty kandydatów.
        const seen = new Map();
        for (const p of d.pool) {
          const prev = seen.get(p.id);
          const rNew = Number(p.raw) || 0, rOld = prev ? (Number(prev.raw) || 0) : -1;
          const better = !prev || rNew > rOld
            || (rNew === rOld && (Number(p.mv) || 0) > (Number(prev.mv) || 0));
          if (better) seen.set(p.id, p);
        }
        const dd = { ...d, pool: [...seen.values()] };
        setData(dd);
        setSel(dd.squad.find((p) => p.real) || dd.squad[0]);
        // Zdjęcia kadry (wolne licencyjnie, Wikimedia) — best-effort, nie blokują danych.
        fetch("photos.json")
          .then((r) => (r.ok && (r.headers.get("content-type") || "").includes("json") ? r.json() : {}))
          .then((pm) => setPhotos(pm && typeof pm === "object" ? pm : {}))
          .catch(() => {});
      })
      .catch(() => {
        setErr(live
          ? "Tryb live jest jeszcze niedostępny — zostają dane zapisane."
          : "Nie udało się wczytać danych.");
      })
      .finally(() => setLoading(false));
  }


  const adjusted = (p) => {
    const lg = data.leagues.find((l) => l.lg === p.lg);
    const line = lineOfPos(p.pos);
    const hc = Number(lg ? lg[line] : 0) || 0;
    const raw = Number(p.raw) || 0;
    return { adj: raw + pctToRC(hc) * 2, hcRC: pctToRC(hc), pct: hc, line };
  };
  const matchScore = (player, p) => {
    if (p.pos !== player.pos) return null;
    const { adj } = adjusted(p);
    const rc = Number(player.rc) || 0;
    const diff = adj - rc;
    const coherence = typeof p.coherence === "number" ? p.coherence
      : Math.max(0, 100 - Math.abs(diff) * 7);
    const level = typeof p.raw === "number" ? p.raw : adj;
    return { adj, diff, level, coherence, ref: p.coherence_ref || null,
             fit: coherence };
  };
  // Kalibracja: mediana fee/wartość z REALNYCH transferów (transfers.csv na Kaggle),
  // rozbita wg wieku. Gdy jest — używamy jej zamiast ręcznego mnożnika wieku, więc
  // wycena jest oparta na rzeczywistych kwotach, a nie na zgadywaniu.
  const CAL = (data && data.meta && data.meta.price_calibration) || null;
  const calAgeMult = (age) => {
    const bucket = age <= 21 ? "u21" : age <= 25 ? "a22_25" : age <= 29 ? "a26_29" : "a30p";
    if (CAL && typeof CAL[bucket] === "number") return CAL[bucket];
    if (CAL && typeof CAL.all === "number") return CAL.all;
    // Fallback (brak kalibracji): dawny ręczny mnożnik.
    return age <= 23 ? 1.25 : age <= 26 ? 1.05 : age <= 29 ? 0.85 : 0.65;
  };
  const estimatePrice = (player, p) => {
    const { adj } = adjusted(p);
    const base = Number(p.mv) || 0;
    const rc = Number(player.rc) || 0;
    const levelF = 1 + Math.max(-0.3, (adj - rc) * 0.04);
    const ageF = calAgeMult(Number(p.age) || 0);
    const yearsLeft = Math.max(0, (p.contract || 2026) - 2026);
    const contractF = yearsLeft >= 3 ? 1.2 : yearsLeft === 2 ? 1.0 : yearsLeft === 1 ? 0.75 : 0.5;
    const ligF = LIG_TIER[p.lg] || 1;
    const est = base * levelF * ageF * contractF * ligF;
    return { est, lo: est * 0.8, hi: est * 1.25, calibrated: !!CAL };
  };

  // Skuteczność / forma: percentyl G+A na 90 minut W OBRĘBIE POZYCJI, liczony na
  // CAŁEJ puli. Świadomie ODDZIELONY od RC (RC zostaje czyste, jednoźródłowe). Tylko
  // dla zawodników z wiarygodną próbką minut — poniżej per-90 to szum. Pozycje z małą
  // liczbą zawodników z outputem (n<6) pomijamy — percentyl byłby niereprezentatywny.
  const FORM_MIN_MINUTES = 450;
  const formIndex = useMemo(() => {
    if (!data) return {};
    const byPos = {};
    for (const p of data.pool) {
      const mn = Number(p.minutes) || 0;
      if (mn < FORM_MIN_MINUTES) continue;
      const ga = (Number(p.goals) || 0) + (Number(p.assists) || 0);
      (byPos[p.pos] = byPos[p.pos] || []).push({ id: p.id, ga90: ga / (mn / 90) });
    }
    const out = {};
    for (const pos in byPos) {
      const arr = byPos[pos].sort((a, b) => a.ga90 - b.ga90);
      const n = arr.length;
      if (n < 6) continue;
      arr.forEach((x, i) => { out[x.id] = { ga90: x.ga90, pct: Math.round((i / (n - 1)) * 100), n }; });
    }
    return out;
  }, [data]);

  const candidates = useMemo(() => {
    if (!data || !sel) return [];
    let rows = data.pool.map((p) => ({ p, m: matchScore(sel, p) }))
      .filter((x) => x.m).map((x) => ({ ...x, price: estimatePrice(sel, x.p), form: formIndex[x.p.id] || null }));
    // --- filtrowanie ---
    const F = filters;
    rows = rows.filter(({ p, m, price }) => {
      const age = Number(p.age) || 0;
      if (age > 0 && (age < F.ageMin || age > F.ageMax)) return false;
      // Cena: kandydaci BEZ wyceny (mv=0) traktowani osobno — wariant C.
      const hasPrice = Number(p.mv) > 0;
      if (!hasPrice && !F.showUnpriced) return false;
      if (hasPrice && F.priceMax < 50 && price.est > F.priceMax) return false;
      if (m.coherence < F.cohMin) return false;
      if (m.level < F.levelMin) return false;
      if (F.onlyReliable && p.level_estimated) return false;
      if (F.leagues.length > 0 && !F.leagues.includes(p.lg)) return false;
      return true;
    });
    const fpct = (r) => (r.form ? r.form.pct : -1);   // bez formy = na koniec
    const s = { fit: (a, b) => b.m.coherence - a.m.coherence,
      coherence: (a, b) => b.m.coherence - a.m.coherence,
      price: (a, b) => a.price.est - b.price.est,
      price_desc: (a, b) => b.price.est - a.price.est,
      form: (a, b) => fpct(b) - fpct(a),
      level: (a, b) => b.m.level - a.m.level };
    return rows.sort(s[sortBy] || s.coherence);
  }, [data, sel, sortBy, filters, formIndex]);

  // Wyszukiwarka ręczna: po nazwisku, w CAŁEJ puli (niezależnie od pozycji).
  const searchResults = useMemo(() => {
    if (!data || !query.trim()) return null;
    const q = query.trim().toLowerCase();
    return data.pool
      .filter((p) => p.name && p.name !== "?" && p.name.toLowerCase().includes(q))
      .sort((a, b) => (Number(b.coherence) || 0) - (Number(a.coherence) || 0))
      .slice(0, 60);
  }, [data, query]);

  const fmt = (v) => `€${v.toFixed(1)}M`;
  const shortRows = useMemo(() => candidates.filter((c) => short.includes(c.p.id)), [candidates, short]);
  const photoOf = useMemo(() => makePhotoResolver(photos), [photos]);   // przed early-return (Rules of Hooks)
  const median = (a) => { if (!a.length) return 0; const s = [...a].sort((x, y) => x - y);
    const m = Math.floor(s.length / 2); return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

  // (Drużyna cieni liczona jest wewnątrz ShadowView — obsługuje ręczny skład.)

  if (err && !data) return <Splash>{err}</Splash>;
  if (!data) return <Splash>Wczytywanie…</Splash>;

  const isLive = data.meta.source && data.meta.source.includes("live");
  const realCount = data.squad.filter((p) => p.real).length;
  // Szacowana wartość rynkowa kadry = suma mv zawodników (Scoutastic/Transfermarkt + Kaggle).
  // Uczciwie: to suma po WYCENIONYCH; część zawodników może nie mieć ceny w bazie.
  const squadPriced = data.squad.filter((p) => Number(p.mv) > 0);
  const squadValue = squadPriced.reduce((s, p) => s + (Number(p.mv) || 0), 0);
  // Nawigacja jak na rakow.com: 4 sekcje w górnym pasku, szczegóły w „pigułkach".
  const SECTIONS = [
    { id: "kadra",    label: "Kadra",    views: [["twin", "Skład"], ["mecze", "Ostatnie mecze"], ["flags", "Czerwone flagi"]] },
    { id: "skauting", label: "Skauting", views: [["match", "Odpowiednicy"], ["priorities", "Priorytety"], ["okazje", "Okazje"], ["search", "Szukaj"], ["watch", "Watchlista"], ["raport", "Raport / PDF"]] },
    { id: "taktyka",  label: "Taktyka",  views: [["shadow", "Drużyna cieni"], ["corr", "Zależności"], ["opponent", "Przeciwnik"]] },
    { id: "model",    label: "Model",    views: [["leagues", "Handicapy lig"], ["metrics", "Multikolinearność"], ["stability", "Stabilność metryk"], ["help", "Jak to działa"]] },
  ];
  const curSection = SECTIONS.find((s) => s.views.some(([k]) => k === view)) || SECTIONS[0];

  return (
    <div style={{ minHeight: "100vh", background: C.ink, color: C.bone,
      fontFamily: "'Barlow', system-ui, sans-serif", display: "flex" }} className="shell">
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=Barlow:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
        *{box-sizing:border-box;}
        ::selection{background:${C.red};color:#fff;}
        .disp{font-family:'Barlow Condensed',sans-serif;font-weight:800;letter-spacing:.01em;}
        .cond{font-family:'Barlow Condensed',sans-serif;text-transform:uppercase;letter-spacing:.04em;}
        .mono{font-family:'Space Grotesk',monospace;}
        .navq{transition:all .12s ease;}
        .navq:hover{background:${C.panel2};color:#fff;}
        .card{transition:transform .15s ease, border-color .15s ease;}
        .card:hover{border-color:${C.red};transform:translateY(-2px);}
        .rowh:hover{background:${C.panel2};}
        .trow:hover{background:${C.panel2};}
        button:focus-visible{outline:2px solid ${C.redHi};outline-offset:2px;}
        @media (prefers-reduced-motion:no-preference){.bar{transition:width .6s cubic-bezier(.2,.8,.2,1);}}
        /* Subtelna klubowa tekstura pod treścią (prześwituje ~8% spod granatu). */
        .bgwall{position:fixed;inset:0;z-index:0;pointer-events:none;
          background:url('/bg-rakow.webp') center/cover no-repeat;opacity:.08;filter:saturate(.75);}
        .shell > .mobabar, .shell > .rail, .shell > main{position:relative;z-index:1;}
        .mobabar{display:none;}
        .hscroll{overflow-x:auto;-webkit-overflow-scrolling:touch;}
        @media(max-width:900px){
          .shell{flex-direction:column;}
          .mobabar{display:flex;}
          .rail{position:static!important;width:100%!important;min-height:auto!important;
            border-right:none!important;border-bottom:1px solid ${C.line};}
          .rail.closed{display:none!important;}
          .pagehead{padding:16px 18px 14px!important;}
          .content{padding:18px 18px 0!important;}
          h1.disp{font-size:26px!important;}
        }
        @media(max-width:480px){ .content{padding:14px 14px 0!important;} }
        /* DRUK / EKSPORT PDF: chowamy chrome aplikacji, zostaje sam raport. */
        @media print {
          .rail, .mobabar, .pagehead, .bgwall, .noprint { display:none !important; }
          .shell, .content, main { display:block !important; padding:0 !important; margin:0 !important; background:#fff !important; }
          .report-print { color:#111 !important; }
          .report-print .rp-muted { color:#444 !important; }
          .report-print .rp-card { border:1px solid #ccc !important; break-inside:avoid; }
          .report-print .rp-section { break-inside:avoid; }
          * { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
          @page { margin:12mm; size:A4; }
        }
      `}</style>

      <div className="bgwall" aria-hidden="true" />

      {/* ===================== MOBILE TOP BAR (hamburger) ===================== */}
      <div className="mobabar" style={{ position: "sticky", top: 0, zIndex: 40,
        background: "linear-gradient(180deg, #0A1D40, #081733)", borderBottom: `1px solid ${C.line}`,
        alignItems: "center", gap: 12, padding: "10px 16px" }}>
        <button onClick={() => setNavOpen((o) => !o)} aria-label="Menu" style={{
          background: C.panel2, border: `1px solid ${C.line}`, color: C.bone, borderRadius: 8,
          width: 40, height: 40, cursor: "pointer", fontSize: 18, lineHeight: 1 }}>{navOpen ? "✕" : "☰"}</button>
        <img src="/logo-rakow.webp" alt="Herb Raków" style={{ width: 26, height: 32, objectFit: "contain" }} />
        <div className="cond" style={{ fontWeight: 800, fontSize: 17 }}>RAKÓW</div>
        <span className="cond" style={{ marginLeft: "auto", fontSize: 12, color: C.steelHi, letterSpacing: 1 }}>{curSection.label}</span>
      </div>

      {/* ===================== LEFT SIDEBAR (styl Football Manager) ===================== */}
      <aside className={"rail" + (navOpen ? "" : " closed")} style={{ width: 224, flexShrink: 0, minHeight: "100vh", position: "sticky", top: 0,
        background: "linear-gradient(180deg, #0A1D40, #081733)", borderRight: `1px solid ${C.line}`,
        display: "flex", flexDirection: "column", padding: "18px 0" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 18px 16px",
          borderBottom: `1px solid ${C.line}`, marginBottom: 12 }}>
          <img src="/logo-rakow.webp" alt="Herb Raków Częstochowa"
            style={{ width: 32, height: 39, objectFit: "contain", display: "block" }} />
          <div>
            <div className="cond" style={{ fontWeight: 800, fontSize: 17, lineHeight: 1 }}>RAKÓW</div>
            <div className="mono" style={{ fontSize: 8.5, color: C.steel, letterSpacing: 2, marginTop: 2 }}>SCOUT ENGINE</div>
          </div>
        </div>
        <nav className="railnav" style={{ padding: "0 10px", display: "flex", flexDirection: "column", gap: 2 }}>
          {SECTIONS.map((s) => (
            <div key={s.id} style={{ marginBottom: 8 }}>
              <div className="cond" style={{ fontSize: 10, letterSpacing: 2, color: C.steel, padding: "6px 10px 4px", fontWeight: 700 }}>{s.label}</div>
              {s.views.map(([k, label]) => {
                const on = view === k;
                return (
                  <button key={k} className="navq" onClick={() => { setView(k); setNavOpen(false); }} style={{
                    display: "flex", alignItems: "center", width: "100%", textAlign: "left",
                    background: on ? C.panel2 : "transparent", color: on ? "#fff" : C.steelHi,
                    border: "none", borderLeft: `3px solid ${on ? C.red : "transparent"}`,
                    padding: "9px 11px", borderRadius: "0 7px 7px 0", cursor: "pointer",
                    fontSize: 13.5, fontWeight: on ? 700 : 500 }}>
                    {label}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>
        <div style={{ marginTop: "auto", padding: "12px 18px 0" }}>
          <span className="mono" style={{ fontSize: 10, letterSpacing: 1 }}>{isLive
            ? <span style={{ color: C.good }}>● live</span>
            : <span style={{ color: C.proxy }}>● snapshot (zapis)</span>}</span>
        </div>
      </aside>

      {/* ===================== MAIN ===================== */}
      <main style={{ flex: 1, minWidth: 0, padding: "0 0 60px" }}>
        <div className="pagehead" style={{ borderBottom: `1px solid ${C.line}`, background: C.panel, padding: "20px 30px 18px" }}>
          <div className="cond" style={{ fontSize: 11, letterSpacing: ".18em", color: C.redHi, fontWeight: 700 }}>{curSection.label}</div>
          <h1 className="disp" style={{ margin: "3px 0 0", fontSize: "clamp(24px, 3vw, 34px)", lineHeight: 1 }}>
            {view === "twin" && "Obecny skład"}
            {view === "mecze" && "Ostatnie mecze — walidator"}
            {view === "match" && "Odpowiednicy z Europy"}
            {view === "priorities" && "Priorytety transferowe"}
            {view === "okazje" && "Okazje — jakość za euro"}
            {view === "flags" && "Czerwone flagi składu"}
            {view === "leagues" && "Handicapy lig"}
            {view === "metrics" && "Multikolinearność metryk stylu"}
            {view === "stability" && "Stabilność metryk (test-retest)"}
            {view === "corr" && "Zależności formacji"}
            {view === "opponent" && "Analiza przeciwnika"}
            {view === "shadow" && "Drużyna cieni · 3-4-3"}
            {view === "search" && "Wyszukiwarka zawodników"}
            {view === "watch" && "Watchlista skauta"}
            {view === "raport" && "Raport skautingowy"}
            {view === "help" && "Jak korzystać"}
          </h1>
          <div style={{ display: "flex", gap: 22, marginTop: 14, flexWrap: "wrap" }}>
            <Stat n={data.squad.length} l="zawodników" />
            <Stat n={realCount} l="realnych profili" accent />
            <Stat n={data.leagues.length} l="lig w puli" />
            <Stat n={data.pool.length} l="kandydatów" />
            {squadValue > 0 && (
              <Stat n={`~€${squadValue.toFixed(1)}M`}
                l={squadPriced.length < data.squad.length
                  ? `wartość kadry (${squadPriced.length}/${data.squad.length})`
                  : "wartość kadry"} />
            )}
          </div>
        </div>

        {err && <div style={{ margin: "16px 34px 0", fontSize: 12.5, color: C.warn }}>{err}</div>}

        <div className="content" style={{ padding: "26px 34px 0", maxWidth: 1180, margin: "0 auto" }}>
          {view === "twin" && <TwinView data={data} photoOf={photoOf} sel={sel} setSel={setSel} setView={setView} />}
          {view === "mecze" && <RecentView data={data} setSel={setSel} setView={setView} />}
          {view === "match" && <MatchView {...{ data, photoOf, sel, setSel, candidates, sortBy, setSortBy,
            short, toggleShort, shortRows, adjusted, fmt, median,
            filters: draft, applied: filters, setF, applyFilters, resetFilters, filtersDirty,
            FILTERS_DEFAULT, filtersOpen, setFiltersOpen }} />}
          {view === "priorities" && <PrioritiesView {...{ data, setSel, setView, fmt }} />}
          {view === "okazje" && <OkazjeView {...{ data, fmt, short, toggleShort, setSel, setView }} />}
          {view === "flags" && <FlagsView {...{ data, setSel, setView }} />}
          {view === "search" && <SearchView {...{ data, query, setQuery, searchResults, short, toggleShort, fmt }} />}
          {view === "watch" && <WatchlistView {...{ data, wl, setStatus, setNote, setSel, setView, fmt }} />}
          {view === "raport" && <ReportView {...{ data, wl, fmt }} />}
          {view === "shadow" && <ShadowView {...{ data, photoOf, fmt, estimatePrice, matchScore, adjusted, filters, setSel, setView }} />}
          {view === "leagues" && <LeaguesView data={data} />}
          {view === "metrics" && <MetricsView data={data} />}
          {view === "stability" && <StabilityView data={data} />}
          {view === "corr" && <CorrView data={data} />}
          {view === "opponent" && <OpponentView data={data} />}
          {view === "help" && <HelpView data={data} setView={setView} />}
        </div>
      </main>
    </div>
  );
}

// ============================ SUBVIEWS ============================
function TwinView({ data, photoOf = () => null, sel, setSel, setView }) {
  const byLine = { Bramka: [], Obrona: [], Pomoc: [], Atak: [] };
  data.squad.forEach((p) => { (byLine[p.line || lineOfPos(p.pos)] || byLine.Pomoc).push(p); });
  // Sortowanie wg RC malejąco (jak tabela składu w FM). „b.d." na dół.
  Object.values(byLine).forEach((arr) => arr.sort((a, b) =>
    (a.rc_estimated - b.rc_estimated) || ((Number(b.rc) || 0) - (Number(a.rc) || 0))));
  const order = ["Bramka", "Obrona", "Pomoc", "Atak"];
  // Atrybut, w którym zawodnik najbardziej wyróżnia się nad średnią Ekstraklasy.
  const topStrength = (p) => {
    const labs = data.meta && data.meta.style_labels ? data.meta.style_labels[p.line] : null;
    const usePos = labs && labs.length && Array.isArray(p.profile_pos);
    const vec = usePos ? p.profile_pos : p.profile;
    const L = usePos ? labs : STYLE_LABELS;
    if (!Array.isArray(vec)) return null;
    let bi = -1, bv = 0.5;
    for (let i = 0; i < vec.length; i++) { const z = Number(vec[i]) || 0; if (z > bv) { bv = z; bi = i; } }
    return bi >= 0 ? L[bi] : null;
  };
  const COLS = "54px 1.5fr 58px 108px 1.3fr 26px";
  return (
    <div>
      <Lead>Skład ułożony liniami — jak na tablicy taktycznej. Kliknij zawodnika, by znaleźć jego odpowiedników w Europie.</Lead>
      {data.squad.some((p) => p.rc_estimated) && (
        <div style={{ marginTop: 10, display: "inline-flex", alignItems: "center", gap: 7,
          background: `${C.warn}14`, border: `1px solid ${C.warn}44`, borderRadius: 9,
          padding: "7px 12px", fontSize: 12, color: C.steelHi }}>
          <span style={{ color: C.warn, fontSize: 14 }}>⚠</span>
          <b style={{ color: C.warn }}>b.d.</b>&nbsp;w miejscu RC oznacza <b style={{ color: C.bone }}>brak dostatecznych danych</b> — zawodnik nie ma wystarczającej próbki meczowej, więc poziomu nie da się policzyć.
        </div>
      )}
      {data.squad.some((p) => p.rc_source === "historical") && (
        <div style={{ marginTop: 10, display: "inline-flex", alignItems: "center", gap: 7,
          background: `${C.blueHi}14`, border: `1px solid ${C.blueHi}44`, borderRadius: 9,
          padding: "7px 12px", fontSize: 12, color: C.steelHi }}>
          <b className="mono" style={{ color: C.blueHi, fontSize: 11 }}>hist.</b>
          &nbsp;oznacza RC policzone z <b style={{ color: C.bone }}>danych poprzedniego sezonu</b> — zawodnik nie ma jeszcze próbki w bieżącym, więc ocena jest orientacyjna.
        </div>
      )}
      <RcExplainer />
      <div style={{ display: "flex", flexDirection: "column", gap: 18, marginTop: 18 }}>
        {order.map((line) => (
          byLine[line].length > 0 && (
          <div key={line}>
            <div className="cond" style={{ fontSize: 12, letterSpacing: 2, color: C.steelHi, fontWeight: 700,
              marginBottom: 8, display: "flex", alignItems: "center", gap: 10 }}>
              {line}<span style={{ color: C.steel, fontWeight: 400 }}>· {byLine[line].length}</span>
              <span style={{ flex: 1, height: 1, background: C.line }} />
            </div>
            <div className="hscroll"><div style={{ minWidth: 560, border: `1px solid ${C.line}`, borderRadius: 10, overflow: "hidden" }}>
              <div className="cond" style={{ display: "grid", gridTemplateColumns: COLS, gap: 12,
                padding: "8px 14px", background: C.panel, borderBottom: `1px solid ${C.line}`,
                fontSize: 10.5, letterSpacing: 1, color: C.steel, fontWeight: 700 }}>
                <div>Poz.</div><div>Zawodnik</div><div style={{ textAlign: "center" }}>RC</div>
                <div>Forma</div><div>Wyróżnia się</div><div />
              </div>
              {byLine[line].map((p) => {
                const est = p.rc_estimated;
                const tc = est ? C.steel : tierColor(p.rc);
                const seld = sel?.id === p.id;
                const ts = topStrength(p);
                return (
                  <button key={p.id} className="trow" onClick={() => { setSel(p); setView("match"); }}
                    style={{ display: "grid", gridTemplateColumns: COLS, gap: 12, alignItems: "center",
                      width: "100%", textAlign: "left", color: C.bone, cursor: "pointer",
                      background: seld ? C.panel2 : "transparent", border: "none",
                      borderBottom: `1px solid ${C.line}`, borderLeft: `3px solid ${seld ? C.red : "transparent"}`,
                      padding: "9px 14px 9px 11px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap" }}>
                      <span className="cond" style={{ fontSize: 11.5, fontWeight: 800, color: "#fff",
                        background: C.red, borderRadius: 4, padding: "1px 7px" }}>{p.pos}</span>
                      {roleName(p) && (
                        <span className="cond" title="Rola w modelu (RC + koherencja)"
                          style={{ fontSize: 10, fontWeight: 700, color: C.steelHi, background: "transparent",
                            border: `1px solid ${C.line}`, borderRadius: 4, padding: "0px 5px" }}>{roleName(p)}</span>
                      )}
                      {Array.isArray(p.alt_pos) && p.alt_pos.length > 0 && (
                        <span className="cond" title={`Gra też na: ${p.alt_pos.join(", ")} (pozycja alternatywna)`}
                          style={{ fontSize: 10, fontWeight: 700, color: C.steelHi, background: "transparent",
                            border: `1px solid ${C.line}`, borderRadius: 4, padding: "0px 5px", cursor: "help" }}>
                          {p.alt_pos.join("/")}
                        </span>
                      )}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                      <Face name={p.name} src={photoOf(p.name)} size={32} ring={tc} />
                      <span style={{ fontWeight: 600, fontSize: 13.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{p.name}</span>
                    </div>
                    <div style={{ textAlign: "center" }}>
                      {est ? <span className="mono" title="Brak dostatecznych danych — zawodnik nie ma wystarczającej próbki meczowej, więc poziomu nie da się policzyć."
                        style={{ fontSize: 11, color: C.warn, fontWeight: 700, cursor: "help" }}>b.d.</span>
                        : <span className="disp" style={{ fontSize: 22, color: tc }}>{p.rc}</span>}
                      {p.rc_source === "historical" && <div style={{ marginTop: 2 }}><HistBadge p={p} fontSize={8} ml={0} /></div>}
                    </div>
                    <div style={{ height: 6, background: C.panel2, borderRadius: 3, overflow: "hidden" }}>
                      <div className="bar" style={{ width: est ? "0%" : `${p.rc}%`, height: "100%", background: est ? C.warn : C.red }} />
                    </div>
                    <div style={{ fontSize: 12.5, color: C.steelHi, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {ts || <span style={{ color: C.steel }}>—</span>}
                    </div>
                    <div style={{ textAlign: "center", color: C.steel }}>›</div>
                  </button>
                );
              })}
            </div></div>
          </div>
          )
        ))}
      </div>
    </div>
  );
}

// Chipy: output bieżącego sezonu (G/A/min z appearances.csv) + sygnał „OKAZJA",
// gdy szczyt wartości kariery (highest_market_value) jest istotnie wyższy niż
// obecna wycena — zawodnik po spadku ceny, potencjalne odbicie. Dane z Kaggle.
function OutputChips({ p, fmt, form = null }) {
  const g = Number(p.goals) || 0, as = Number(p.assists) || 0, mn = Number(p.minutes) || 0;
  const peak = Number(p.peak) || 0, mv = Number(p.mv) || 0;
  const okazja = peak > 0 && mv > 0 && peak >= mv * 1.6 && (peak - mv) >= 1.5;
  const hasOut = mn > 0 || g > 0 || as > 0;
  const fc = form ? (form.pct >= 70 ? C.good : form.pct >= 45 ? C.warn : C.steelHi) : null;
  if (!hasOut && !okazja && !form) return null;
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 5, alignItems: "center" }}>
      {hasOut && (
        <span className="mono" title="Output w bieżącym sezonie: gole · asysty · rozegrane minuty (dane meczowe)."
          style={{ fontSize: 10.5, color: C.steelHi, background: C.panel2, borderRadius: 5, padding: "2px 7px" }}>
          {g}G · {as}A · {mn}′
        </span>
      )}
      {form && (
        <span className="mono"
          title={`Skuteczność: ${form.ga90.toFixed(2)} G+A na 90 min — wyżej niż ${form.pct}% zawodników na tej pozycji (próba ${form.n}). Liczone osobno, NIE wchodzi do RC.`}
          style={{ fontSize: 10.5, color: fc, background: `${fc}1c`, border: `1px solid ${fc}55`,
            borderRadius: 5, padding: "2px 7px", fontWeight: 700 }}>
          forma {form.pct}%
        </span>
      )}
      {okazja && (
        <span className="mono" title={`Szczyt wyceny w karierze ${fmt(peak)}, teraz ${fmt(mv)}. Możliwa okazja — cena po spadku, potencjał odbicia.`}
          style={{ fontSize: 10.5, color: C.good, background: `${C.good}1c`, border: `1px solid ${C.good}55`,
            borderRadius: 5, padding: "2px 7px", fontWeight: 700 }}>
          OKAZJA · szczyt {fmt(peak)}
        </span>
      )}
    </div>
  );
}

function MatchView({ data, photoOf = () => null, sel, setSel, candidates, sortBy, setSortBy, short, toggleShort, shortRows, adjusted, fmt, median,
  filters, applied, setF, applyFilters, resetFilters, filtersDirty, FILTERS_DEFAULT, filtersOpen, setFiltersOpen }) {
  const [openCmp, setOpenCmp] = useState(null);   // id kandydata z rozwiniętym porównaniem
  if (!sel) return null;
  const totalForPos = data.pool.filter((p) => p.pos === sel.pos).length;
  const activeCount = countActiveFilters(applied, FILTERS_DEFAULT);
  // Etykiety atrybutów dopasowanych do pozycji (z data.json). Wektor profile_pos
  // ma tę samą kolejność. Brak (stare dane) → panele użyją profilu uniwersalnego.
  const posLabels = data.meta && data.meta.style_labels ? data.meta.style_labels[sel.line] : null;
  const selVec = (Array.isArray(sel.profile_pos) && posLabels && posLabels.length) ? sel.profile_pos : sel.profile;
  const selLabs = (Array.isArray(sel.profile_pos) && posLabels && posLabels.length) ? posLabels : STYLE_LABELS;
  return (
    <div>
      <Lead>Kandydaci z lig europejskich na pozycji <b className="mono" style={{ color: C.redHi }}>{sel.pos}</b>. Poziom = surowy + handicap ligi. Cena to estymacja.</Lead>
      <RcExplainer compact />

      {/* Wybrany zawodnik — twarz + tożsamość (dla kogo szukamy następcy) */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, margin: "16px 0 4px",
        background: `linear-gradient(120deg, ${C.panel}, ${C.ink})`, border: `1px solid ${C.line}`,
        borderRadius: 14, padding: "12px 16px" }}>
        <Face name={sel.name} src={photoOf(sel.name)} size={64}
          ring={sel.rc_estimated ? C.line : tierColor(sel.rc)} />
        <div style={{ minWidth: 0 }}>
          <div className="mono" style={{ fontSize: 10.5, letterSpacing: 1.5, color: C.steel }}>SZUKAMY NASTĘPCY DLA</div>
          <div style={{ fontSize: 18, fontWeight: 700, lineHeight: 1.15 }}>{sel.name}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 3 }}>
            <span className="cond" style={{ fontSize: 12, fontWeight: 800, color: "#fff", background: C.red, borderRadius: 4, padding: "1px 7px" }}>{sel.pos}</span>
            {roleName(sel) && (
              <span className="cond" title="Rola w modelu — na niej liczone są RC i koherencja (dobór KPI wg analityków)"
                style={{ fontSize: 11, fontWeight: 700, color: C.steelHi, background: C.panel2,
                  border: `1px solid ${C.line}`, borderRadius: 4, padding: "1px 6px", cursor: "help" }}>{roleName(sel)}</span>
            )}
            {Array.isArray(sel.alt_pos) && sel.alt_pos.length > 0 && (
              <span className="cond" title={`Gra też na: ${sel.alt_pos.join(", ")} (pozycja alternatywna)`}
                style={{ fontSize: 11, fontWeight: 700, color: C.steelHi, border: `1px solid ${C.line}`,
                  borderRadius: 4, padding: "1px 6px", cursor: "help" }}>{sel.alt_pos.join("/")}</span>
            )}
            {sel.rc_estimated
              ? <span className="mono" title="Brak dostatecznych danych" style={{ fontSize: 11, color: C.warn, fontWeight: 700 }}>b.d.</span>
              : <span className="disp" style={{ fontSize: 20, color: tierColor(sel.rc) }}>{sel.rc}<span style={{ fontSize: 10, color: C.steel }}> RC</span></span>}
            <HistBadge p={sel} fontSize={10} />
          </div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, margin: "14px 0", flexWrap: "wrap", alignItems: "center" }}>
        <select value={sel.id} onChange={(e) => setSel(data.squad.find((p) => p.id === e.target.value))}
          style={{ background: C.panel, color: C.bone, border: `1px solid ${C.line}`, borderRadius: 9,
            padding: "10px 13px", fontSize: 13, fontWeight: 600 }}>
          {data.squad.map((p) => <option key={p.id} value={p.id}>{p.pos} — {p.name}</option>)}
        </select>
        <div style={{ display: "flex", gap: 5, marginLeft: "auto", alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: 11, color: C.steel }}>sortuj</span>
          {[["coherence", "koherencja"], ["level", "poziom"], ["form", "forma"]].map(([k, l]) => (
            <button key={k} onClick={() => setSortBy(k)} style={{ background: sortBy === k ? C.panelHi : "transparent",
              color: sortBy === k ? C.bone : C.steel, border: `1px solid ${sortBy === k ? C.redHi : C.line}`,
              padding: "7px 12px", borderRadius: 8, cursor: "pointer", fontSize: 12, fontWeight: 600 }}>{l}</button>
          ))}
          {(() => {
            const active = sortBy === "price" || sortBy === "price_desc";
            const next = sortBy === "price" ? "price_desc" : "price";
            const arrow = sortBy === "price_desc" ? " ↓" : sortBy === "price" ? " ↑" : " ↑";
            return (
              <button onClick={() => setSortBy(next)}
                title={sortBy === "price" ? "Od najtańszego — kliknij, by odwrócić" : sortBy === "price_desc" ? "Od najdroższego — kliknij, by odwrócić" : "Sortuj po cenie"}
                style={{ background: active ? C.panelHi : "transparent",
                  color: active ? C.bone : C.steel, border: `1px solid ${active ? C.redHi : C.line}`,
                  padding: "7px 12px", borderRadius: 8, cursor: "pointer", fontSize: 12, fontWeight: 600 }}>
                cena<span className="mono" style={{ marginLeft: 3 }}>{arrow}</span>
              </button>
            );
          })()}
        </div>
      </div>

      <SectionLabel>{`W czym ${sel.name} jest mocny`}</SectionLabel>
      <StrengthsPanel profile={selVec} labels={selLabs} name={sel.name} />

      <FilterPanel {...{ data, filters, setF, applyFilters, resetFilters, filtersDirty, FILTERS_DEFAULT,
        filtersOpen, setFiltersOpen, activeCount, shown: candidates.length, total: totalForPos }} />

      {candidates.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 10, marginBottom: 18 }}>
          <Kpi l="Kandydatów" v={candidates.length} />
          <Kpi l="Najtańszy" v={fmt(Math.min(...candidates.map((c) => c.price.est)))} c={C.good} />
          <Kpi l="Mediana" v={fmt(median(candidates.map((c) => c.price.est)))} c={C.proxy} />
          <Kpi l="Najlepsza koh." v={`${Math.round(Math.max(...candidates.map((c) => c.m.coherence)))}%`} c={C.redHi} />
        </div>
      )}

      {candidates.length > 0 && (
        <Top5Panel candidates={candidates} sel={sel} short={short} toggleShort={toggleShort} fmt={fmt} />
      )}

      {candidates.length === 0 && (
        <Empty>
          {activeCount > 0 ? (
            <>Żaden kandydat na pozycji <b className="mono">{sel.pos}</b> nie spełnia ustawionych filtrów
            {totalForPos > 0 ? <> (w puli jest ich {totalForPos})</> : null}.{" "}
            <button onClick={resetFilters}
              style={{ background: "none", border: "none", color: C.redHi, cursor: "pointer",
                fontSize: 13.5, textDecoration: "underline", padding: 0 }}>Wyczyść filtry</button></>
          ) : (
            <>Brak kandydatów na pozycji <b className="mono">{sel.pos}</b> w obecnej puli.</>
          )}
        </Empty>
      )}

      <div className="hscroll"><div style={{ display: "grid", gap: 9, minWidth: 680 }}>
        {candidates.map(({ p, m, price, form }) => {
          const a = adjusted(p);
          const open = openCmp === p.id;
          return (
           <div key={p.id} style={{ background: C.panel, border: `1px solid ${open ? `${C.redHi}88` : C.line}`,
             borderRadius: 12, overflow: "hidden" }}>
            <div className="rowh" style={{ padding: "15px 18px", display: "grid",
              gridTemplateColumns: "1.5fr 0.9fr 1fr 1fr auto", gap: 16, alignItems: "center" }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13.5, fontWeight: 600 }}>{p.name && p.name !== "?" ? p.name : p.lg}</div>
                <div style={{ fontSize: 11, color: C.steel, marginTop: 2 }}>{p.lg} · {p.pos}{roleName(p) ? ` · ${roleName(p)}` : ""} · {p.age} lat · do {p.contract}</div>
                {p.name && p.name !== "?" && (
                  <a href={tmUrl(p.name)} target="_blank" rel="noopener noreferrer"
                    style={{ fontSize: 10.5, color: C.steelHi, textDecoration: "none", marginTop: 3, display: "inline-block" }}>
                    Transfermarkt ↗
                  </a>
                )}
                <OutputChips p={p} fmt={fmt} form={form} />
              </div>
              <div>
                <div className="disp" style={{ fontSize: 26, lineHeight: 0.9,
                  display: "flex", alignItems: "flex-start", gap: 2 }}>
                  {p.level_estimated ? (
                    <span className="mono" title="Brak dostatecznych danych — brak wystarczającej próbki meczowej, poziomu nie da się policzyć."
                      style={{ fontSize: 13, color: C.warn, cursor: "help", fontWeight: 700 }}>b.d.</span>
                  ) : m.level}
                </div>
                <div style={{ fontSize: 10, color: C.steel }}>poziom</div>
              </div>
              <div>
                <div style={{ fontSize: 11.5, color: C.steel, marginBottom: 5 }}>
                  koherencja{m.ref ? <span style={{ color: C.steelHi }}> · {m.ref}</span> : ""}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <div style={{ flex: 1, height: 5, background: C.panel2, borderRadius: 3, overflow: "hidden" }}>
                    <div className="bar" style={{ width: `${m.coherence}%`, height: "100%",
                      background: m.coherence > 70 ? C.good : m.coherence > 45 ? C.warn : C.bad }} />
                  </div>
                  <span className="mono" style={{ fontSize: 11, fontWeight: 700,
                    color: m.coherence > 70 ? C.good : m.coherence > 45 ? C.warn : C.bad }}>{Math.round(m.coherence)}%</span>
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                {Number(p.mv) > 0 ? (
                  <>
                    <div className="disp" style={{ fontSize: 22, color: C.proxy, lineHeight: 0.9 }}>{fmt(price.est)}</div>
                    <div style={{ fontSize: 10, color: C.steel }}>{fmt(price.lo)}–{fmt(price.hi)}</div>
                  </>
                ) : (
                  <>
                    <div style={{ fontSize: 12.5, color: C.steel, lineHeight: 1.2 }}>brak wyceny</div>
                    <div style={{ fontSize: 10, color: C.steel, opacity: 0.7 }}>nie w bazie</div>
                  </>
                )}
              </div>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <button onClick={() => setOpenCmp(open ? null : p.id)} title="W czym lepszy/słabszy od naszego zawodnika"
                  style={{ background: open ? C.panelHi : "transparent", color: open ? C.bone : C.steelHi,
                    border: `1px solid ${open ? C.redHi : C.line}`, borderRadius: 9, height: 38, padding: "0 11px",
                    cursor: "pointer", fontSize: 12, fontWeight: 700, whiteSpace: "nowrap" }}>
                  vs {surnameU(sel.name)}
                </button>
                <button onClick={() => toggleShort(p)} title="Lista obserwowanych"
                  style={{ background: short.includes(p.id) ? C.red : "transparent",
                    color: short.includes(p.id) ? "#fff" : C.steel, border: `1px solid ${short.includes(p.id) ? C.red : C.line}`,
                    borderRadius: 9, width: 38, height: 38, cursor: "pointer", fontSize: 17 }}>
                  {short.includes(p.id) ? "★" : "☆"}
                </button>
              </div>
            </div>
            {open && <ComparePanel sel={sel} cand={p} labels={posLabels} />}
           </div>
          );
        })}
      </div></div>

      {shortRows.length > 0 && (
        <div style={{ marginTop: 20, background: `linear-gradient(120deg, ${C.panel}, ${C.ink})`,
          border: `1px solid ${C.red}`, borderRadius: 14, padding: "18px 20px" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
            <span className="disp" style={{ fontSize: 17, color: C.redHi }}>★ LISTA OBSERWOWANYCH</span>
            <span className="mono" style={{ fontSize: 12, color: C.steel }}>{shortRows.length} zawodn.</span>
            <span style={{ marginLeft: "auto", fontSize: 12, color: C.steel }}>
              łączny koszt <b className="disp" style={{ fontSize: 20, color: C.proxy }}>
                {fmt(shortRows.reduce((s, c) => s + c.price.est, 0))}</b>
            </span>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {shortRows.map((c) => (
              <span key={c.p.id} style={{ fontSize: 12, background: C.panel2, border: `1px solid ${C.line}`,
                borderRadius: 8, padding: "6px 11px" }}>
                {c.p.name && c.p.name !== "?" ? c.p.name : c.p.lg} · <b style={{ color: C.proxy }}>{fmt(c.price.est)}</b>
              </span>
            ))}
          </div>
        </div>
      )}

      <Note>Cena to estymacja: wartość rynkowa korygowana o poziom vs RC, wiek, długość kontraktu i mnożnik ligi. Kalibrowana docelowo na zrealizowanych transferach.</Note>
    </div>
  );
}

function SearchView({ data, query, setQuery, searchResults, short, toggleShort, fmt }) {
  const cohColor = (v) => (v > 70 ? C.good : v > 45 ? C.warn : C.bad);
  return (
    <div>
      <Lead>Wyszukaj dowolnego zawodnika po nazwisku — w całej puli, niezależnie od pozycji. Poziom i koherencja pochodzą z modelu; „Transfermarkt" otwiera profil.</Lead>
      <div style={{ display: "flex", gap: 10, margin: "18px 0", alignItems: "center", flexWrap: "wrap" }}>
        <input value={query} onChange={(e) => setQuery(e.target.value)} autoFocus
          placeholder="Wpisz nazwisko zawodnika…"
          style={{ flex: "1 1 320px", background: C.panel, color: C.bone, border: `1px solid ${C.line}`,
            borderRadius: 9, padding: "11px 14px", fontSize: 14 }} />
        {query && (
          <button onClick={() => setQuery("")}
            style={{ background: "transparent", color: C.steel, border: `1px solid ${C.line}`,
              borderRadius: 8, padding: "9px 14px", cursor: "pointer", fontSize: 12 }}>Wyczyść</button>
        )}
      </div>

      {!query.trim() && <Empty>Zacznij pisać, by wyszukać zawodnika po nazwisku.</Empty>}
      {query.trim() && searchResults && searchResults.length === 0 && (
        <Empty>Brak zawodnika „{query}" w puli {data.pool.length} kandydatów.</Empty>
      )}

      {searchResults && searchResults.length > 0 && (
        <>
          <div className="mono" style={{ fontSize: 11, color: C.steel, marginBottom: 10 }}>
            {searchResults.length}{searchResults.length === 60 ? "+" : ""} wynik(ów)
          </div>
          <div className="hscroll"><div style={{ display: "grid", gap: 9, minWidth: 640 }}>
            {searchResults.map((p) => (
              <div key={p.id} className="rowh" style={{ background: C.panel, border: `1px solid ${C.line}`,
                borderRadius: 12, padding: "14px 18px", display: "grid",
                gridTemplateColumns: "1.6fr 0.7fr 1fr 1fr auto", gap: 14, alignItems: "center" }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 600 }}>{p.name}</div>
                  <div style={{ fontSize: 11, color: C.steel, marginTop: 2 }}>{p.lg} · {p.pos} · {p.age} lat · do {p.contract}</div>
                  <a href={tmUrl(p.name)} target="_blank" rel="noopener noreferrer"
                    style={{ fontSize: 10.5, color: C.steelHi, textDecoration: "none", marginTop: 3, display: "inline-block" }}>Transfermarkt ↗</a>
                </div>
                <div>
                  <div className="disp" style={{ fontSize: 24, lineHeight: 0.9, display: "flex", gap: 2 }}>
                    {p.level_estimated ? (
                      <span className="mono" title="Brak dostatecznych danych — brak wystarczającej próbki meczowej, poziomu nie da się policzyć."
                        style={{ fontSize: 12, color: C.warn, cursor: "help", fontWeight: 700 }}>b.d.</span>
                    ) : p.raw}
                  </div>
                  <div style={{ fontSize: 10, color: C.steel }}>poziom</div>
                </div>
                <div>
                  <div style={{ fontSize: 11.5, color: C.steel, marginBottom: 5 }}>
                    koherencja{p.coherence_ref ? <span style={{ color: C.steelHi }}> · {p.coherence_ref}</span> : ""}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    <div style={{ flex: 1, height: 5, background: C.panel2, borderRadius: 3, overflow: "hidden" }}>
                      <div style={{ width: `${p.coherence || 0}%`, height: "100%", background: cohColor(p.coherence || 0) }} />
                    </div>
                    <span className="mono" style={{ fontSize: 11, fontWeight: 700, color: cohColor(p.coherence || 0) }}>{Math.round(p.coherence || 0)}%</span>
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  {Number(p.mv) > 0
                    ? <div className="disp" style={{ fontSize: 20, color: C.proxy }}>{fmt(Number(p.mv))}</div>
                    : <div style={{ fontSize: 12, color: C.steel }}>brak wyceny</div>}
                  <div style={{ fontSize: 10, color: C.steel }}>wartość rynkowa</div>
                </div>
                <button onClick={() => toggleShort(p)} title="Lista obserwowanych"
                  style={{ background: short.includes(p.id) ? C.red : "transparent",
                    color: short.includes(p.id) ? "#fff" : C.steel, border: `1px solid ${short.includes(p.id) ? C.red : C.line}`,
                    borderRadius: 9, width: 38, height: 38, cursor: "pointer", fontSize: 17 }}>
                  {short.includes(p.id) ? "★" : "☆"}
                </button>
              </div>
            ))}
          </div></div>
        </>
      )}
    </div>
  );
}

// ============================ RAPORT / EKSPORT PDF ============================
// Drukowalny raport skautingowy. Źródło: watchlista (obserwowani + do sprawdzenia)
// albo TOP per pozycja z puli. „Zapisz jako PDF" = window.print() + CSS @media print
// (czysty, zaznaczalny tekst, bez zależności). Układ jasny (na biały papier).
const RP_POS = ["GK", "CB", "WB", "DM", "CM", "AM", "WM", "W", "ST"];
function ReportView({ data, wl, fmt }) {
  const [source, setSource] = useState("watch");
  const [topN, setTopN] = useState(3);
  const lgIdx = useMemo(() => Object.fromEntries((data.leagues || []).map((l) => [l.lg, l])), [data]);
  const byId = useMemo(() => {
    const m = {}; for (const p of data.pool || []) m[p.id] = p; for (const s of data.squad || []) m[s.id] = s; return m;
  }, [data]);
  const today = (data.meta && data.meta.generated) || "";

  // Wiersze raportu, pogrupowane wg pozycji.
  const sections = useMemo(() => {
    const grp = {};
    if (source === "watch") {
      for (const id of Object.keys(wl)) {
        const e = wl[id]; if (e.s === "odrzucony") continue;
        const live = byId[id];
        const pos = (live && live.pos) || e.pos || "—";
        const rc = live ? (typeof live.raw === "number" ? Math.round(adjLevel(live, lgIdx)) : live.rc) : null;
        const coh = live && typeof live.coherence === "number" ? Math.round(live.coherence) : null;
        (grp[pos] = grp[pos] || []).push({
          name: e.nm || id, pos, lg: (live && live.lg) || e.lg || "", age: live && live.age,
          rc, coh, mv: Number((live && live.mv) || e.mv) || 0, note: e.n || "",
          status: e.s, ref: live && live.coherence_ref,
        });
      }
    } else {
      const byPos = {};
      for (const p of data.pool || []) {
        if (!p.pos || typeof p.raw !== "number") continue;
        (byPos[p.pos] = byPos[p.pos] || []).push(p);
      }
      for (const pos of Object.keys(byPos)) {
        const top = byPos[pos].map((p) => ({ p, adj: adjLevel(p, lgIdx) }))
          .sort((a, b) => b.adj - a.adj).slice(0, topN);
        grp[pos] = top.map(({ p, adj }) => ({
          name: p.name, pos, lg: p.lg, age: p.age, rc: Math.round(adj),
          coh: typeof p.coherence === "number" ? Math.round(p.coherence) : null,
          mv: Number(p.mv) || 0, note: "", ref: p.coherence_ref,
        }));
      }
    }
    return RP_POS.filter((pos) => grp[pos] && grp[pos].length).map((pos) => ({ pos, rows: grp[pos] }));
  }, [source, topN, wl, data, byId, lgIdx]);

  const total = sections.reduce((s, x) => s + x.rows.length, 0);

  return (
    <div>
      {/* Pasek narzędzi — NIE drukuje się */}
      <div className="noprint" style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 6 }}>
          {[["watch", "Z watchlisty"], ["top", "TOP per pozycja"]].map(([k, lab]) => (
            <button key={k} onClick={() => setSource(k)}
              style={{ background: source === k ? C.red : "transparent", color: source === k ? "#fff" : C.steelHi,
                border: `1px solid ${source === k ? C.red : C.line}`, borderRadius: 9, padding: "8px 14px", fontSize: 13, cursor: "pointer", fontWeight: 600 }}>
              {lab}
            </button>
          ))}
        </div>
        {source === "top" && (
          <label className="mono" style={{ fontSize: 12, color: C.steel, display: "flex", alignItems: "center", gap: 7 }}>
            TOP
            <select value={topN} onChange={(e) => setTopN(Number(e.target.value))}
              style={{ background: C.panel, color: C.bone, border: `1px solid ${C.line}`, borderRadius: 7, padding: "5px 8px" }}>
              {[3, 5, 8].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
            per pozycja
          </label>
        )}
        <button onClick={() => window.print()}
          style={{ marginLeft: "auto", background: C.red, color: "#fff", border: "none", borderRadius: 9,
            padding: "9px 18px", fontSize: 13.5, cursor: "pointer", fontWeight: 700 }}>
          ⭳ Zapisz jako PDF
        </button>
      </div>
      <div className="noprint" style={{ fontSize: 12, color: C.steel, marginBottom: 14 }}>
        Podgląd raportu (jasny — pod druk). „Zapisz jako PDF" otwiera okno drukowania — wybierz „Zapisz jako PDF" jako drukarkę. {source === "watch" && "Bierze obserwowanych i do sprawdzenia z watchlisty (bez odrzuconych)."}
      </div>

      {/* DOKUMENT (drukowalny) */}
      <div className="report-print" style={{ background: "#fff", color: "#111", borderRadius: 8, padding: "28px 30px", maxWidth: 900 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", borderBottom: "2px solid #E4022B", paddingBottom: 12, marginBottom: 18 }}>
          <div>
            <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: ".01em" }}>Raków Częstochowa — raport skautingowy</div>
            <div className="rp-muted" style={{ fontSize: 12.5, marginTop: 3 }}>
              {source === "watch" ? "Lista obserwowanych (watchlista)" : `TOP ${topN} kandydatów per pozycja`} · {total} zawodników{today ? ` · dane: ${today}` : ""}
            </div>
          </div>
          <div style={{ fontSize: 11, color: "#E4022B", fontWeight: 800, letterSpacing: 1 }}>RAKÓW SCOUT</div>
        </div>

        {total === 0 && (
          <div className="rp-muted" style={{ fontSize: 13 }}>
            {source === "watch" ? "Watchlista jest pusta — oznacz zawodników gwiazdką, żeby weszli do raportu." : "Brak kandydatów w puli."}
          </div>
        )}

        {sections.map(({ pos, rows }) => (
          <div key={pos} className="rp-section" style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 800, color: "#E4022B", borderBottom: "1px solid #eee", paddingBottom: 4, marginBottom: 8 }}>
              {POS_LABEL[pos] || pos} <span style={{ color: "#999", fontWeight: 600 }}>· {rows.length}</span>
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ color: "#666", textAlign: "left", fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".04em" }}>
                  <th style={{ padding: "3px 6px" }}>Zawodnik</th><th style={{ padding: "3px 6px" }}>Liga</th>
                  <th style={{ padding: "3px 6px" }}>Wiek</th><th style={{ padding: "3px 6px" }}>RC</th>
                  <th style={{ padding: "3px 6px" }}>Koh.</th><th style={{ padding: "3px 6px" }}>Wycena</th>
                  {source === "watch" && <th style={{ padding: "3px 6px" }}>Notatka</th>}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} style={{ borderTop: "1px solid #f0f0f0" }}>
                    <td style={{ padding: "4px 6px", fontWeight: 600 }}>
                      {r.name}{r.status === "sprawdzic" ? <span className="rp-muted" style={{ fontWeight: 400 }}> (do sprawdzenia)</span> : ""}
                    </td>
                    <td className="rp-muted" style={{ padding: "4px 6px" }}>{r.lg}</td>
                    <td className="rp-muted" style={{ padding: "4px 6px" }}>{r.age || "—"}</td>
                    <td style={{ padding: "4px 6px", fontWeight: 700 }}>{r.rc != null ? r.rc : "—"}</td>
                    <td style={{ padding: "4px 6px" }}>{r.coh != null ? `${r.coh}%` : "—"}</td>
                    <td style={{ padding: "4px 6px" }}>{r.mv > 0 ? fmt(r.mv) : "—"}</td>
                    {source === "watch" && <td className="rp-muted" style={{ padding: "4px 6px", fontStyle: r.note ? "normal" : "italic" }}>{r.note || "—"}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}

        <div className="rp-muted" style={{ fontSize: 10, marginTop: 18, borderTop: "1px solid #eee", paddingTop: 8 }}>
          RC = poziom skorygowany o handicap ligi (percentyl vs Ekstraklasa). Koh. = dopasowanie stylu do zawodnika Rakowa{sections[0] && sections[0].rows[0] && sections[0].rows[0].ref ? "" : ""}. Wycena = wartość rynkowa (Transfermarkt/Scoutastic). Raport generowany z narzędzia skautingowego Rakowa.
        </div>
      </div>
    </div>
  );
}

// ============================ WATCHLISTA — WIDOK ============================
const WATCH_COL = { obserwowany: "#E4022B", sprawdzic: "#E8A13A", odrzucony: "#7C90B0" };
function WatchlistView({ data, wl, setStatus, setNote, setSel, setView, fmt }) {
  // Indeks żywych danych (pula + skład) do odświeżenia RC/koherencji.
  const byId = useMemo(() => {
    const m = {};
    for (const p of data.pool || []) m[p.id] = p;
    for (const s of data.squad || []) m[s.id] = s;
    return m;
  }, [data]);
  const ids = Object.keys(wl);
  const entries = ids.map((id) => ({ id, ...wl[id], live: byId[id] || null }))
    .sort((a, b) => (b.ts || 0) - (a.ts || 0));
  const order = ["obserwowany", "sprawdzic", "odrzucony"];
  const groups = order.map((st) => ({ st, items: entries.filter((e) => e.s === st) }));
  const jump = (e) => {
    if (!e.live) return;
    const cand = data.pool.find((p) => p.id === e.id);
    if (cand) { setSel(cand); setView("match"); }
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
        <Lead>Twoja lista obserwowanych — zapisywana lokalnie w tej przeglądarce (nie współdzielona między osobami). Gwiazdką w „Odpowiednikach", „Okazjach" i „Szukaj" dodajesz zawodnika; tu zmieniasz status i dopisujesz notatki. RC i koherencja odświeżają się z aktualnych danych.</Lead>
        {Object.keys(wl).length > 0 && (
          <button onClick={() => setView("raport")}
            style={{ flexShrink: 0, background: "transparent", color: C.redHi, border: `1px solid ${C.red}66`,
              borderRadius: 9, padding: "8px 14px", fontSize: 13, cursor: "pointer", fontWeight: 600, whiteSpace: "nowrap" }}>
            ⭳ Eksportuj do PDF
          </button>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10, margin: "16px 0 8px" }}>
        {order.map((st) => (
          <Kpi key={st} l={WATCH_STATUSES[st].label} v={groups.find((g) => g.st === st).items.length}
            c={groups.find((g) => g.st === st).items.length ? WATCH_COL[st] : C.steel} />
        ))}
      </div>

      {ids.length === 0 && <Empty>Watchlista jest pusta. Oznacz zawodników gwiazdką ☆ w Odpowiednikach / Okazjach / Szukaj — pojawią się tutaj.</Empty>}

      {groups.map(({ st, items }) => items.length > 0 && (
        <div key={st}>
          <SectionLabel>{WATCH_STATUSES[st].label} · {items.length}</SectionLabel>
          <div style={{ display: "grid", gap: 9 }}>
            {items.map((e) => {
              const rc = e.live ? (typeof e.live.raw === "number" ? Math.round(e.live.raw) : e.live.rc) : null;
              const coh = e.live && typeof e.live.coherence === "number" ? Math.round(e.live.coherence) : null;
              const mv = Number((e.live && e.live.mv) || e.mv) || 0;
              return (
                <div key={e.id} style={{ background: C.panel, border: `1px solid ${WATCH_COL[st]}44`, borderRadius: 12, padding: "13px 16px" }}>
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 14, flexWrap: "wrap" }}>
                    <div style={{ flex: "1 1 220px", minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 14.5, fontWeight: 600, color: C.bone }}>{e.nm || e.id}</span>
                        {e.pos && <span className="mono" style={{ fontSize: 10.5, color: C.redHi, fontWeight: 700 }}>{e.pos}</span>}
                        {e.lg && <span style={{ fontSize: 11, color: C.steel }}>{e.lg}</span>}
                        {!e.live && <span className="mono" style={{ fontSize: 10.5, color: C.warn }}>poza pulą</span>}
                      </div>
                      <div className="mono" style={{ display: "flex", gap: 14, marginTop: 6, fontSize: 11.5, color: C.steel }}>
                        {rc != null && <span>RC <b style={{ color: C.bone }}>{rc}</b></span>}
                        {coh != null && <span>koh. <b style={{ color: C.bone }}>{coh}%</b></span>}
                        {mv > 0 && <span>{fmt(mv)}</span>}
                      </div>
                      <textarea value={e.n || ""} onChange={(ev) => setNote(e.id, ev.target.value)}
                        placeholder="Notatka skauta…" rows={2}
                        style={{ width: "100%", marginTop: 9, background: C.ink, color: C.bone,
                          border: `1px solid ${C.line}`, borderRadius: 8, padding: "7px 10px",
                          fontSize: 12.5, fontFamily: "inherit", resize: "vertical" }} />
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6, flexShrink: 0 }}>
                      <div style={{ display: "flex", gap: 5 }}>
                        {order.map((s2) => (
                          <button key={s2} onClick={() => setStatus({ id: e.id, name: e.nm, pos: e.pos, lg: e.lg, mv }, s2)}
                            title={WATCH_STATUSES[s2].label}
                            style={{ background: e.s === s2 ? WATCH_COL[s2] : "transparent",
                              color: e.s === s2 ? "#fff" : C.steel, border: `1px solid ${e.s === s2 ? WATCH_COL[s2] : C.line}`,
                              borderRadius: 8, padding: "5px 9px", fontSize: 12, cursor: "pointer", fontWeight: 700 }}>
                            {WATCH_STATUSES[s2].icon}
                          </button>
                        ))}
                      </div>
                      <div style={{ display: "flex", gap: 5 }}>
                        {e.live && (
                          <button onClick={() => jump(e)} style={{ flex: 1, background: "transparent", color: C.redHi,
                            border: `1px solid ${C.red}66`, borderRadius: 8, padding: "5px 9px", fontSize: 11.5, cursor: "pointer", fontWeight: 600 }}>
                            Odpowiednicy →
                          </button>
                        )}
                        <button onClick={() => setStatus({ id: e.id }, null)} title="Usuń z watchlisty"
                          style={{ background: "transparent", color: C.steel, border: `1px solid ${C.line}`,
                            borderRadius: 8, padding: "5px 10px", fontSize: 11.5, cursor: "pointer" }}>
                          Usuń
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}

      <Note>Dane zapisane lokalnie w przeglądarce (klucz <span className="mono">{WATCH_KEY}</span>) — nie synchronizują się między osobami ani urządzeniami. Gdy dopniemy backend, przeniesiemy je do wersji współdzielonej bez utraty notatek. „poza pulą" = zawodnik wypadł z bieżących danych (np. za mało minut po odświeżeniu) — notatka zostaje, RC/koherencji chwilowo brak.</Note>
    </div>
  );
}

function ShadowView({ data, photoOf = () => null, fmt, estimatePrice, matchScore = () => null, adjusted = () => ({ adj: 0 }), filters = {}, setSel, setView }) {
  const squad = data.squad, pool = data.pool;
  const [lineup, setLineup] = useState({});   // slotId -> playerId (ręczny wybór)
  const [excluded, setExcluded] = useState([]);   // id zawodników wykluczonych ze składu (np. na wylocie)
  const [inserted, setInserted] = useState({});   // slotId -> true: wstaw cień (transfer) zamiast naszego zawodnika
  const toggleInsert = (id) => setInserted((m) => { const n = { ...m }; if (n[id]) delete n[id]; else n[id] = true; return n; });
  // Domyślny budżet cienia: filtr z „Odpowiedników" jeśli ustawiony, inaczej
  // rozsądny pułap klubowy (5 mln €) — żeby cienie od razu były w realiach Rakowa,
  // nie €20M+. Suwak niżej pozwala zmienić aż do „bez limitu".
  const [budget, setBudget] = useState(
    Number.isFinite(filters.priceMax) && filters.priceMax < 50 ? filters.priceMax : 5);
  const cohColor = (v) => (v > 70 ? C.good : v > 45 ? C.warn : C.bad);
  const surname = (nm) => { const t = String(nm || "").trim().split(" "); return t[t.length - 1]; };
  const isExcluded = (id) => excluded.includes(id);
  const toggleExclude = (id) => setExcluded((e) => e.includes(id) ? e.filter((x) => x !== id) : [...e, id]);

  // Cień musi TRZYMAĆ SIĘ FILTRÓW (budżet + aktywne filtry z „Odpowiedników").
  const passes = (p, price) => {
    const F = filters;
    const age = Number(p.age) || 0;
    if (age > 0 && ((F.ageMin && age < F.ageMin) || (F.ageMax && age > F.ageMax))) return false;
    const hasPrice = Number(p.mv) > 0;
    if (!hasPrice && F.showUnpriced === false) return false;
    if (hasPrice && budget < 50 && price.est > budget) return false;     // budżet cienia
    if (F.cohMin && (Number(p.coherence) || 0) < F.cohMin) return false;
    if (F.levelMin && (Number(p.raw) || 0) < F.levelMin) return false;
    if (F.onlyReliable && p.level_estimated) return false;
    if (Array.isArray(F.leagues) && F.leagues.length > 0 && !F.leagues.includes(p.lg)) return false;
    return true;
  };

  const xi = useMemo(() => {
    const used = new Set();
    const byRc = (a, b) => (a.rc_estimated ? 1 : 0) - (b.rc_estimated ? 1 : 0) || (b.rc - a.rc);
    const chosen = {};
    for (const slot of FORMATION_343) {
      const p = lineup[slot.id] && squad.find((s) => s.id === lineup[slot.id]);
      if (p && !used.has(p.id) && !isExcluded(p.id)) { chosen[slot.id] = p; used.add(p.id); }
    }
    // AUTO: najpierw na pozycji PODSTAWOWEJ zawodnika, a jeśli brak — na jego
    // pozycji ALTERNATYWNEJ (alt_pos, np. Fran WB→CB). Wciąż bez wpadania po całej
    // linii, więc stoper nie ląduje na wahadle. Brak pasującego = pusty slot.
    const pickAuto = (slot) => {
      const free = squad.filter((p) => !used.has(p.id) && !isExcluded(p.id));
      for (const pos of slot.pos) { const c = free.filter((p) => p.pos === pos).sort(byRc); if (c.length) return c[0]; }
      for (const pos of slot.pos) { const c = free.filter((p) => (p.alt_pos || []).includes(pos)).sort(byRc); if (c.length) return c[0]; }
      return null;
    };
    const usedShadows = new Set();
    return FORMATION_343.map((slot) => {
      let starter = chosen[slot.id];
      if (!starter && !(slot.id in lineup)) { starter = pickAuto(slot); if (starter) used.add(starter.id); }
      let shadow = null, price = null;
      if (starter) {
        const cands = pool
          .filter((p) => p.pos === starter.pos && typeof p.coherence === "number" && !usedShadows.has(p.id))
          .map((p) => ({ p, price: estimatePrice(starter, p) }))
          .filter(({ p, price }) => passes(p, price));
        const pref = cands.filter(({ p }) => p.coherence_ref === starter.name);
        const list = (pref.length ? pref : cands).sort((a, b) => b.p.coherence - a.p.coherence);
        if (list[0]) { shadow = list[0].p; price = list[0].price; usedShadows.add(shadow.id); }
      }
      return { slot, starter, shadow, price, ins: !!inserted[slot.id] && !!shadow };
    });
  }, [data, lineup, excluded, budget, filters, inserted]);

  const filled = xi.filter((s) => s.starter);
  const real = filled.filter((s) => !s.starter.rc_estimated);
  const shadows = xi.filter((s) => s.shadow);
  const avgCoh = shadows.length ? Math.round(mean(shadows.map((s) => s.shadow.coherence))) : null;
  const totalCost = shadows.reduce((a, s) => a + (s.price ? s.price.est : 0), 0);
  const isManual = Object.keys(lineup).length > 0;

  // --- WSTAWIANIE ODPOWIEDNIKA: efektywny skład (nasz zawodnik lub wstawiony cień) ---
  // Poziom cienia liczony jako poziom surowy + handicap ligi (adjusted), żeby był
  // porównywalny z RC naszych zawodników.
  const effWho = (s) => (s.ins && s.shadow) ? s.shadow : s.starter;
  const effLevel = (s) => (s.ins && s.shadow) ? Math.round(adjusted(s.shadow).adj)
    : (s.starter && !s.starter.rc_estimated ? s.starter.rc : null);
  const effProfile = (s) => { const w = effWho(s); return Array.isArray(w && w.profile) ? w.profile : null; };
  const nowLevels = xi.map(effLevel).filter((v) => typeof v === "number");
  const avgNow = nowLevels.length ? Math.round(mean(nowLevels)) : null;
  const baseLevels = real.map((s) => s.starter.rc);
  const avgBase = baseLevels.length ? Math.round(mean(baseLevels)) : null;
  const avgRC = avgBase;
  const nIns = xi.filter((s) => s.ins).length;
  const insCost = xi.filter((s) => s.ins && s.price).reduce((a, s) => a + s.price.est, 0);
  const lvlDelta = (avgNow != null && avgBase != null) ? avgNow - avgBase : 0;
  // Lista wyboru: najpierw zawodnicy NA pozycję slotu (podstawową LUB alternatywną),
  // potem pozostali (można wstawić kogo się chce — np. Tudora na wahadło). Bramkarze
  // tylko na GK. „Na pozycji" uwzględnia alt_pos, więc Fran wejdzie też do slotu CB.
  const playsSlot = (p, slot) => slot.pos.includes(p.pos)
    || (p.alt_pos || []).some((a) => slot.pos.includes(a))
    || (slot.line === "Bramka" && p.pos === "GK");
  const onPos = (slot) => squad.filter((p) => !isExcluded(p.id) && playsSlot(p, slot));
  const offPos = (slot) => squad.filter((p) => !isExcluded(p.id) && p.pos !== "GK" && !playsSlot(p, slot));
  const excludedPlayers = squad.filter((p) => isExcluded(p.id));

  // --- macierz koherencji (podobieństwo stylu) między zawodnikami pola ---
  // Używa EFEKTYWNEGO zawodnika (naszego lub wstawionego cienia), więc wprowadzenie
  // transferu zmienia też koherencję zespołu.
  const wp = xi.map((s) => ({ slot: s.slot, who: effWho(s), prof: effProfile(s), ins: s.ins }))
    .filter((x) => x.slot.line !== "Bramka" && x.who && Array.isArray(x.prof) && x.prof.some((v) => v !== 0));
  const cos = (a, b) => { let d = 0, na = 0, nb = 0; for (let i = 0; i < a.length; i++) { d += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i]; } if (!na || !nb) return 50; return Math.round((d / (Math.sqrt(na) * Math.sqrt(nb)) + 1) / 2 * 100); };
  const hasProfiles = wp.length >= 2;
  const pairSim = (i, j) => cos(wp[i].prof, wp[j].prof);
  const avgWith = (i) => { const o = []; for (let j = 0; j < wp.length; j++) if (j !== i) o.push(pairSim(i, j)); return o.length ? Math.round(mean(o)) : 0; };
  let teamCoh = null;
  if (hasProfiles) { const ps = []; for (let i = 0; i < wp.length; i++) for (let j = i + 1; j < wp.length; j++) ps.push(pairSim(i, j)); teamCoh = ps.length ? Math.round(mean(ps)) : null; }

  const selStyle = { background: C.panel2, color: C.bone, border: `1px solid ${C.line}`, borderRadius: 6,
    padding: "3px 4px", fontSize: 11, fontWeight: 600, width: "100%", cursor: "pointer" };

  return (
    <div>
      <Lead>Skład Rakowa w formacji <b className="mono" style={{ color: C.redHi }}>3-4-3</b> — ustaw go ręcznie (rozwijane listy na kartach), a pod każdym zawodnikiem zobaczysz jego najlepszy <b style={{ color: C.bone }}>cień</b>. Niżej macierz koherencji: jak podobnie stylem grają wybrani zawodnicy względem siebie.</Lead>

      <div style={{ display: "flex", alignItems: "center", gap: 14, margin: "14px 0 4px", flexWrap: "wrap" }}>
        <span className="mono" style={{ fontSize: 11, letterSpacing: 1, color: C.steel }}>
          SKŁAD: <b style={{ color: isManual ? C.redHi : C.steelHi }}>{isManual ? "ręczny" : "automatyczny"}</b>
        </span>
        {isManual && (
          <button onClick={() => setLineup({})} style={{ background: "transparent", color: C.redHi,
            border: `1px solid ${C.red}66`, borderRadius: 8, padding: "5px 12px", fontSize: 12, cursor: "pointer", fontWeight: 600 }}>
            Przywróć automatyczny
          </button>
        )}
        {/* Budżet cienia — cienie trzymają się tego limitu (plus aktywne filtry) */}
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: C.steelHi }}>
          <span className="mono" style={{ fontSize: 11, letterSpacing: 1, color: C.steel }}>BUDŻET CIENIA</span>
          <input type="range" min={0} max={50} step={0.5} value={budget}
            onChange={(e) => setBudget(+e.target.value)} style={{ width: 130 }} />
          <b style={{ color: C.proxy, minWidth: 62 }}>{budget >= 50 ? "bez limitu" : `≤ €${budget}M`}</b>
        </label>
      </div>

      {excludedPlayers.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", margin: "6px 0 2px" }}>
          <span className="mono" style={{ fontSize: 10.5, letterSpacing: 1, color: C.steel }}>USUNIĘCI ZE SKŁADU:</span>
          {excludedPlayers.map((p) => (
            <button key={p.id} onClick={() => toggleExclude(p.id)} title="Przywróć do składu"
              style={{ background: C.panel2, border: `1px solid ${C.line}`, color: C.steelHi, borderRadius: 8,
                padding: "3px 9px", fontSize: 11.5, cursor: "pointer" }}>
              {surname(p.name)} <span style={{ color: C.good }}>↺</span>
            </button>
          ))}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10, margin: "12px 0 12px" }}>
        <Kpi l={nIns > 0 ? "Poziom XI (z transferami)" : "Śr. poziom XI"}
          v={avgNow != null ? `${avgNow}${nIns > 0 && lvlDelta !== 0 ? ` (${lvlDelta > 0 ? "+" : ""}${lvlDelta})` : ""}` : "—"}
          c={nIns > 0 && lvlDelta !== 0 ? (lvlDelta > 0 ? C.good : C.bad) : undefined} />
        <Kpi l="Koherencja składu" v={teamCoh != null ? `${teamCoh}%` : "—"} c={C.redHi} />
        <Kpi l="Śr. koherencja cieni" v={avgCoh != null ? `${avgCoh}%` : "—"} c={C.proxy} />
        <Kpi l="Koszt cieni (łącznie)" v={fmt(totalCost)} c={C.proxy} />
      </div>

      {nIns > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", margin: "0 0 16px",
          background: `${C.blue}1A`, border: `1px solid ${C.blueHi}55`, borderRadius: 12, padding: "10px 15px" }}>
          <span className="cond" style={{ fontSize: 12, letterSpacing: 1, color: C.blueHi, fontWeight: 800 }}>SYMULACJA TRANSFERÓW</span>
          <span style={{ fontSize: 13, color: C.steelHi }}>
            Wprowadzono <b style={{ color: C.bone }}>{nIns}</b>, poziom XI <b style={{ color: C.bone }}>{avgBase}</b> →{" "}
            <b style={{ color: lvlDelta >= 0 ? C.good : C.bad }}>{avgNow}</b>{" "}
            <b style={{ color: lvlDelta >= 0 ? C.good : C.bad }}>({lvlDelta > 0 ? "+" : ""}{lvlDelta})</b>,
            koszt <b style={{ color: C.proxy }}>{fmt(insCost)}</b>
          </span>
          <button onClick={() => setInserted({})} style={{ marginLeft: "auto", background: "transparent",
            color: C.blueHi, border: `1px solid ${C.blueHi}66`, borderRadius: 8, padding: "5px 12px",
            fontSize: 12, cursor: "pointer", fontWeight: 600 }}>Wyczyść transfery</button>
        </div>
      )}

      <div style={{ overflowX: "auto" }}>
        <div style={{ position: "relative", width: "100%", minWidth: 660, maxWidth: 940, margin: "0 auto",
          aspectRatio: "10 / 12", background: "linear-gradient(180deg,#0f2018,#0a140e)",
          border: `1px solid ${C.line}`, borderRadius: 16, overflow: "hidden" }}>
          <div style={{ position: "absolute", left: 0, right: 0, top: "50%", height: 1, background: `${C.bone}16` }} />
          <div style={{ position: "absolute", left: "50%", top: "50%", width: 120, height: 120, marginLeft: -60, marginTop: -60, border: `1px solid ${C.bone}12`, borderRadius: "50%" }} />
          <div style={{ position: "absolute", left: "26%", right: "26%", top: 0, height: "13%", border: `1px solid ${C.bone}12`, borderTop: "none" }} />
          <div style={{ position: "absolute", left: "26%", right: "26%", bottom: 0, height: "13%", border: `1px solid ${C.bone}12`, borderBottom: "none" }} />

          {xi.map(({ slot, starter, shadow, price, ins }) => {
            const effCand = ins && shadow;   // po „wstaw" na karcie widać KANDYDATA, nie naszego
            const effName = effCand ? shadow.name : (starter ? starter.name : null);
            const effLvl = effCand ? Math.round(adjusted(shadow).adj)
              : (starter && !starter.rc_estimated ? starter.rc : null);
            return (
            <div key={slot.id} style={{ position: "absolute", left: `${slot.x}%`, top: `${slot.y}%`,
              transform: "translate(-50%,-50%)", width: 172, background: ins ? `${C.blue}22` : `${C.panel}F2`,
              border: `1px solid ${ins ? C.blueHi : (starter && !starter.rc_estimated ? `${tierColor(starter.rc)}66` : C.line)}`,
              borderRadius: 11, padding: "8px 10px", color: C.bone }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                <span className="mono" style={{ fontSize: 9, fontWeight: 800, color: "#fff", background: C.red, borderRadius: 4, padding: "1px 5px", flexShrink: 0 }}>{slot.label}</span>
                <select value={starter ? starter.id : ""} title="Zmień zawodnika (dowolny z kadry)"
                  onChange={(e) => setLineup((l) => ({ ...l, [slot.id]: e.target.value || "" }))}
                  style={selStyle}>
                  <option value="">— puste —</option>
                  <optgroup label={`Na pozycję (${slot.label})`}>
                    {onPos(slot).map((p) => {
                      const viaAlt = !slot.pos.includes(p.pos) && p.pos !== "GK";
                      return (
                        <option key={p.id} value={p.id}>
                          {p.pos}{viaAlt ? `→${slot.label}` : ""} {surname(p.name)} · {p.rc_estimated ? "b.d." : p.rc}
                        </option>
                      );
                    })}
                  </optgroup>
                  <optgroup label="Inne pozycje">
                    {offPos(slot).map((p) => (
                      <option key={p.id} value={p.id}>{p.pos} {surname(p.name)} · {p.rc_estimated ? "b.d." : p.rc}</option>
                    ))}
                  </optgroup>
                </select>
                {starter && (
                  <button onClick={() => toggleExclude(starter.id)} title="Usuń zawodnika ze składu"
                    style={{ background: "transparent", color: C.steel, border: `1px solid ${C.line}`,
                      borderRadius: 6, width: 20, height: 20, lineHeight: 1, fontSize: 11, cursor: "pointer", flexShrink: 0 }}>✕</button>
                )}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <Face name={effName || ""} src={effCand ? photoOf(shadow.name) : (starter ? photoOf(starter.name) : null)}
                  size={40} ring={effCand ? C.blueHi : (starter && !starter.rc_estimated ? tierColor(starter.rc) : C.line)} />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                    color: effCand ? C.blueHi : C.bone }}>
                    {effName ? surname(effName) : "—"}
                  </div>
                  <span className="disp" style={{ fontSize: 15 }}>
                    {effCand
                      ? <>{effLvl}<span style={{ fontSize: 9, color: C.steel }}> poz.</span></>
                      : (starter ? (starter.rc_estimated
                        ? <span className="mono" title="Brak dostatecznych danych" style={{ fontSize: 10, color: C.warn }}>b.d.</span>
                        : <>{starter.rc}<span style={{ fontSize: 9, color: C.steel }}> RC</span>{!effCand && <HistBadge p={starter} fontSize={8} ml={4} />}</>) : "")}
                  </span>
                </div>
                {starter && (
                  <button onClick={() => { setSel(starter); setView("match"); }}
                    style={{ background: "transparent", color: C.steelHi, border: `1px solid ${C.line}`,
                      borderRadius: 6, padding: "2px 7px", fontSize: 10, cursor: "pointer", flexShrink: 0 }}>odp. →</button>
                )}
              </div>
              <div style={{ height: 1, background: C.line, margin: "0 0 6px" }} />
              {shadow ? (
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                    <span className="mono" style={{ fontSize: 8.5, letterSpacing: 1, color: ins ? C.blueHi : C.steel, textTransform: "uppercase" }}>
                      {ins ? "✓ w składzie" : "cień"}
                    </span>
                    {starter && !starter.rc_estimated && (
                      <span className="mono" style={{ fontSize: 9, color: (Math.round(adjusted(shadow).adj) - starter.rc) >= 0 ? C.good : C.bad }}>
                        {(() => { const d = Math.round(adjusted(shadow).adj) - starter.rc; return `${starter.rc}→${Math.round(adjusted(shadow).adj)} (${d > 0 ? "+" : ""}${d})`; })()}
                      </span>
                    )}
                    <button onClick={() => toggleInsert(slot.id)} title={ins ? "Cofnij transfer" : "Wstaw ten transfer do składu i przelicz poziom zespołu"}
                      style={{ marginLeft: "auto", background: ins ? C.blue : "transparent", color: ins ? "#fff" : C.blueHi,
                        border: `1px solid ${C.blueHi}${ins ? "" : "77"}`, borderRadius: 5, padding: "1px 6px", fontSize: 9.5, cursor: "pointer", fontWeight: 700, flexShrink: 0 }}>
                      {ins ? "cofnij" : "wstaw ⇄"}
                    </button>
                  </div>
                  <a href={tmUrl(shadow.name)} target="_blank" rel="noopener noreferrer" title="Otwórz profil w Transfermarkt"
                    style={{ fontSize: 11.5, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                      display: "block", color: C.bone, textDecoration: "none" }}
                    onMouseOver={(e) => { e.currentTarget.style.color = C.redHi; e.currentTarget.style.textDecoration = "underline"; }}
                    onMouseOut={(e) => { e.currentTarget.style.color = C.bone; e.currentTarget.style.textDecoration = "none"; }}>
                    {shadow.name} <span style={{ fontSize: 9, color: C.steel }}>↗</span>
                  </a>
                  <div style={{ fontSize: 9.5, color: C.steel, margin: "1px 0 0" }}>{shadow.lg} · {shadow.age || "?"} lat</div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 3 }}>
                    <span className="mono" style={{ fontSize: 11, fontWeight: 700, color: cohColor(shadow.coherence) }}>{Math.round(shadow.coherence)}%</span>
                    <span style={{ fontSize: 10, color: C.steel }}>koh.</span>
                    <span style={{ marginLeft: "auto", fontSize: 11, color: C.proxy }}>
                      {price ? fmt(price.est) : (Number(shadow.mv) > 0 ? fmt(Number(shadow.mv)) : "—")}
                    </span>
                  </div>
                </div>
              ) : (
                <div style={{ fontSize: 10.5, color: C.steel }}>brak cienia w puli</div>
              )}
            </div>
            );
          })}
        </div>
      </div>

      <SectionLabel>Koherencja składu — podobieństwo stylu</SectionLabel>
      {!hasProfiles ? (
        <Empty>Macierz włączy się po najbliższym odświeżeniu danych ze StatsBomb — pipeline dołoży wtedy profile stylu zawodników do <span className="mono">data.json</span>. Na razie brak profili.</Empty>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", fontSize: 11 }}>
            <thead>
              <tr>
                <th></th>
                {wp.map((s) => <th key={s.slot.id} className="mono" style={{ padding: 6, color: s.ins ? C.blueHi : C.steel, fontWeight: 700 }} title={s.who.name}>{s.slot.label}</th>)}
                <th className="mono" style={{ padding: 6, color: C.steelHi }}>śr.</th>
              </tr>
            </thead>
            <tbody>
              {wp.map((s, i) => (
                <tr key={s.slot.id}>
                  <td className="mono" style={{ padding: "6px 8px", color: C.steelHi, whiteSpace: "nowrap", fontWeight: 600 }} title={s.who.name}>
                    <span style={{ color: s.ins ? C.blueHi : C.redHi }}>{s.slot.label}</span> {surname(s.who.name)}{s.ins ? " ⇄" : ""}
                  </td>
                  {wp.map((_, j) => {
                    const v = i === j ? 100 : pairSim(i, j);
                    return (
                      <td key={j} className="mono" title={`${surname(wp[i].who.name)} ↔ ${surname(wp[j].who.name)}: ${v}`}
                        style={{ width: 40, height: 34, textAlign: "center", fontWeight: 600,
                          background: i === j ? C.panelHi : `rgba(214,0,28,${0.08 + (v / 100) * 0.7})`,
                          color: i === j ? C.steel : (v > 55 ? "#fff" : C.steelHi), border: `2px solid ${C.ink}`, borderRadius: 4 }}>
                        {i === j ? "—" : v}
                      </td>
                    );
                  })}
                  <td className="mono" style={{ padding: "6px 8px", textAlign: "center", fontWeight: 700, color: C.proxy }}>{avgWith(i)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Note>Podobieństwo stylu (0-100) liczone z profilu ruchu i akcji (StatsBomb + SkillCorner), znormalizowanego względem Ekstraklasy. Wysokie = zawodnicy grają podobnie; niskie = uzupełniają się rolami. To podgląd spójności stylistycznej składu, nie ocena jakości. Bramkarz pominięty (metryki nieporównywalne). „Koszt cieni" = suma estymacji cen.</Note>
    </div>
  );
}

function LeaguesView({ data }) {
  return (
    <div>
      <Lead>Ile dana liga różni się poziomem od Ekstraklasy — osobno dla każdej linii. Te korekty przeliczają surowy poziom kandydata. Przykład: pomoc +10% = RC+1.</Lead>
      <div style={{ marginTop: 20, display: "flex", flexDirection: "column", gap: 8 }}>
        {data.leagues.map((l) => (
          <div key={l.lg} style={{ background: l.base ? `linear-gradient(90deg, ${C.redDim}33, ${C.panel})` : C.panel,
            border: `1px solid ${l.base ? C.red : C.line}`, borderRadius: 12, padding: "16px 20px",
            display: "grid", gridTemplateColumns: "1.4fr repeat(4, 1fr)", gap: 14, alignItems: "center" }}>
            <div style={{ fontWeight: 700, fontSize: 14 }}>
              {l.lg}
              {l.base && <span style={{ marginLeft: 8, fontSize: 9, fontWeight: 800, color: C.redHi,
                border: `1px solid ${C.red}`, borderRadius: 4, padding: "2px 6px" }}>BAZA</span>}
            </div>
            {["Bramka", "Obrona", "Pomoc", "Atak"].map((k) => (
              <div key={k} style={{ textAlign: "center" }}>
                <div className="mono" style={{ fontSize: 9, color: C.steel, letterSpacing: 1, marginBottom: 3 }}>{k.toUpperCase()}</div>
                {l.base ? <span style={{ color: C.steel }}>—</span> : (
                  <div>
                    <span className="disp" style={{ fontSize: 20, color: l[k] > 0 ? C.bone : C.steel }}>
                      {l[k] > 0 ? "+" : ""}{l[k]}<span style={{ fontSize: 10, color: C.steel }}>%</span>
                    </span>
                    <div className="mono" style={{ fontSize: 9.5, color: C.proxy }}>RC+{pctToRC(l[k])}</div>
                  </div>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
      <Note>Handicapy liczy metoda porównująca metrykę danej linii z Ekstraklasą (moduł handicap.py). Wybór metryki reprezentującej linię ustala analityk.</Note>
    </div>
  );
}

const POS_LABEL = { GK: "Bramkarz", CB: "Środek obrony", WB: "Wahadło", WM: "Pomoc boczna",
  DM: "Defen. pomoc", CM: "Środek pomocy", AM: "Ofens. pomoc", W: "Skrzydło", ST: "Napastnik" };

// ROLA MODELU (6 grup wg KPI Igora) — oś, na której liczone są RC i koherencja.
// Etykieta czytelna dla skauta; klucz = pole player.role z data.json.
const ROLE_LABEL = { "Bramka": "Bramka", "ŚO": "Środkowy obrońca", "Boczny": "Boczny / wahadło",
  "Skrzydłowy": "Skrzydłowy", "6-8": "Środek pola (6/8)", "10-9": "Ofensywa (10/9)" };
// Awaryjne mapowanie (gdy starszy data.json bez pola role) — lustro ROLE_OF_POS z modelu.
const ROLE_OF_POS = { GK: "Bramka", CB: "ŚO", WB: "Boczny", W: "Skrzydłowy", WM: "Skrzydłowy",
  DM: "6-8", CM: "6-8", AM: "10-9", ST: "10-9" };
const roleKey = (p) => (p && p.role) || (p && ROLE_OF_POS[p.pos]) || null;
const roleName = (p) => { const k = roleKey(p); return k ? (ROLE_LABEL[k] || k) : null; };

function CorrView({ data }) {
  const corr = (data && data.correlations) || {};
  const positions = Array.isArray(corr.positions) ? corr.positions : [];
  const sim = corr.sim || {};
  const counts = corr.counts || {};
  const cohesion = corr.cohesion || {};
  const within = corr.within, between = corr.between;
  const val = (a, b) => (a === b ? 1 : (sim[`${a}-${b}`] ?? sim[`${b}-${a}`] ?? null));

  // Fallback: brak policzonych zależności (stare data.json sprzed odświeżenia).
  if (positions.length < 2) {
    return (
      <div>
        <Lead>Podobieństwo stylu między pozycjami — jak blisko stylistycznie grają role w układzie.</Lead>
        <Empty>Zależności policzą się po najbliższym odświeżeniu danych — pipeline dołoży macierz podobieństwa stylu do <span className="mono">data.json</span>. Na razie brak danych do wyświetlenia.</Empty>
      </div>
    );
  }

  // Kontrast koloru: normalizacja po zakresie wartości POZA przekątną (czytelność).
  const off = [];
  for (const a of positions) for (const b of positions) if (a !== b) { const v = val(a, b); if (v != null) off.push(v); }
  const lo = Math.min(...off), hi = Math.max(...off);
  const shade = (v) => (hi > lo ? (v - lo) / (hi - lo) : 0.5);

  // Insighty liczone z macierzy: najbardziej zbliżone i najbardziej odrębne role.
  let hiPair = null, loPair = null;
  for (let i = 0; i < positions.length; i++)
    for (let j = i + 1; j < positions.length; j++) {
      const v = val(positions[i], positions[j]); if (v == null) continue;
      if (!hiPair || v > hiPair.v) hiPair = { a: positions[i], b: positions[j], v };
      if (!loPair || v < loPair.v) loPair = { a: positions[i], b: positions[j], v };
    }
  // Pozycja najbardziej odrębna stylistycznie (najniższa średnia do reszty).
  let outlier = null;
  for (const a of positions) {
    const others = positions.filter((b) => b !== a).map((b) => val(a, b)).filter((x) => x != null);
    if (!others.length) continue;
    const avg = others.reduce((s, x) => s + x, 0) / others.length;
    if (!outlier || avg < outlier.avg) outlier = { a, avg };
  }
  const nm = (p) => POS_LABEL[p] || p;
  const cards = [];
  if (hiPair) cards.push(["Najbardziej zbliżone role", `${hiPair.a} ↔ ${hiPair.b}`, hiPair.v.toFixed(2),
    `${nm(hiPair.a)} i ${nm(hiPair.b)} mają najbardziej podobny profil stylu — grają najbliżej siebie rolą.`]);
  if (loPair) cards.push(["Najbardziej odrębne", `${loPair.a} ↔ ${loPair.b}`, loPair.v.toFixed(2),
    `${nm(loPair.a)} i ${nm(loPair.b)} najmocniej się różnią — role wyraźnie się uzupełniają.`]);
  if (outlier) cards.push(["Najbardziej wyjątkowa rola", outlier.a, outlier.avg.toFixed(2),
    `${nm(outlier.a)} stylistycznie najbardziej odstaje od reszty układu.`]);

  return (
    <div>
      <Lead>Podobieństwo stylu między pozycjami — policzone z profili stylu wszystkich zawodników puli. Ciemniejsze pole = role o zbliżonym stylu; jasne = role, które się uzupełniają.</Lead>
      <div style={{ display: "flex", gap: 24, marginTop: 20, flexWrap: "wrap", alignItems: "flex-start" }}>
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse" }}>
            <thead><tr><th></th>{positions.map((p) => (
              <th key={p} className="mono"
                title={`${nm(p)} · n=${counts[p] ?? "?"}${cohesion[p] != null ? ` · spójność roli ${cohesion[p].toFixed(2)}` : ""}`}
                style={{ padding: 7, color: C.steel, fontSize: 11 }}>{p}</th>
            ))}</tr></thead>
            <tbody>
              {positions.map((a) => (
                <tr key={a}>
                  <td className="mono" title={nm(a)} style={{ padding: 7, color: C.steelHi, fontSize: 11, fontWeight: 700 }}>{a}</td>
                  {positions.map((b) => {
                    const v = val(a, b);
                    const self = a === b;
                    const sh = self ? 1 : (v == null ? 0 : shade(v));
                    return (
                      <td key={b} title={`${nm(a)} ↔ ${nm(b)}: ${v == null ? "—" : v.toFixed(2)}`} className="mono"
                        style={{ width: 52, height: 46, textAlign: "center", fontSize: 12, fontWeight: 600,
                          background: self ? C.panelHi : `rgba(228,2,43,${0.08 + sh * 0.82})`,
                          color: sh > 0.55 ? "#fff" : C.steelHi, border: `2px solid ${C.ink}`, borderRadius: 4 }}>
                        {self ? "—" : (v == null ? "" : v.toFixed(2))}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mono" style={{ fontSize: 10, color: C.steel, marginTop: 8 }}>
            0 = style odrębne · 1 = identyczny profil stylu. Kolor skalowany po zakresie macierzy dla czytelności.
          </div>
          {within != null && between != null && (
            <div style={{ marginTop: 10, background: C.panel, border: `1px solid ${C.line}`, borderRadius: 10,
              padding: "10px 13px", fontSize: 11.5, color: C.steelHi, maxWidth: 520, lineHeight: 1.5 }}>
              <b style={{ color: C.bone }}>Sygnał vs szum.</b> Spójność stylu wewnątrz ról śr.{" "}
              <b className="mono" style={{ color: within > between ? C.good : C.warn }}>{within.toFixed(2)}</b>,
              podobieństwo między rolami śr. <b className="mono" style={{ color: C.steelHi }}>{between.toFixed(2)}</b>.
              {within > between + 0.05
                ? " Role są wewnętrznie spójniejsze, niż podobne do siebie nawzajem — macierz niesie sygnał."
                : " Różnice między rolami są niewielkie względem rozrzutu wewnątrz nich — czytaj ostrożnie (dużo szumu)."}
              {" "}Najazd na nagłówek pozycji pokazuje jej spójność i próbę.
            </div>
          )}
        </div>
        <div style={{ flex: "1 1 260px", display: "flex", flexDirection: "column", gap: 10 }}>
          {cards.map(([t, pair, v, d]) => (
            <div key={t} style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 12, padding: "14px 16px" }}>
              <div className="mono" style={{ fontSize: 9.5, color: C.steel, letterSpacing: 1, textTransform: "uppercase" }}>{t}</div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 10, margin: "5px 0 6px" }}>
                <span className="disp" style={{ fontSize: 17, color: C.redHi }}>{pair}</span>
                <span className="mono" style={{ fontSize: 13, color: C.proxy }}>{v}</span>
              </div>
              <div style={{ fontSize: 12, color: C.steel, lineHeight: 1.5 }}>{d}</div>
            </div>
          ))}
        </div>
      </div>
      <Note>Podobieństwo stylu ról = kosinus między średnimi profilami stylu pozycji (z-score względem Ekstraklasy, 17 wymiarów: podania, odbiory, gra w powietrzu, drybling, xG/xA, fizyka…), liczony z całej puli lig. To mapa <b>stylistycznego pokrewieństwa ról</b>, nie sieć podań — „kto z kim realnie gra" wymaga danych zdarzeniowych (pas po pasie) i jest naturalnym kolejnym krokiem, skoro dostęp do eventów StatsBomb jest.</Note>
    </div>
  );
}

// ============================ ANALIZA PRZECIWNIKA ============================
// Profil stylu drużyny rywala per linia/rola + przewidywalność + mapa jakości/luk
// + wskazówki matchup, liczone NA ŻYWO z puli (Ekstraklasa). Wszystko z danych,
// które już są w data.json: profile_pos (styl vs Ekstraklasa), raw (RC), team.
// UCZCIWOŚĆ: to wsparcie analityczne, nie automatyczne ustawienie — trener decyduje.
const _mean = (a) => (a.length ? a.reduce((s, x) => s + (Number(x) || 0), 0) / a.length : 0);
const _cos = (a, b) => {
  let d = 0, na = 0, nb = 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) { const x = Number(a[i]) || 0, y = Number(b[i]) || 0; d += x * y; na += x * x; nb += y * y; }
  return (na && nb) ? d / Math.sqrt(na * nb) : 0;
};
const OPP_ROLE_ORDER = ["Bramka", "ŚO", "Boczny", "Skrzydłowy", "6-8", "10-9"];

function OpponentView({ data }) {
  const BASE = "Ekstraklasa (PL)";
  const pool = Array.isArray(data.pool) ? data.pool : [];
  const labelsFor = (line) => (data.meta && data.meta.style_labels ? data.meta.style_labels[line] : null);

  const teams = useMemo(() => {
    const s = new Set();
    pool.forEach((p) => { if (p.lg === BASE && p.team && !/rak[oó]w/i.test(p.team)) s.add(p.team); });
    return Array.from(s).sort((a, b) => a.localeCompare(b));
  }, [pool]);

  const [teamSel, setTeamSel] = useState("");
  const team = teams.includes(teamSel) ? teamSel : (teams[0] || "");
  const players = useMemo(() => pool.filter((p) => p.lg === BASE && p.team === team), [pool, team]);

  const an = useMemo(() => {
    if (!players.length) return null;
    const byLine = {}, byRole = {};
    players.forEach((p) => {
      (byLine[p.line] = byLine[p.line] || []).push(p);
      const r = p.role || p.line; (byRole[r] = byRole[r] || []).push(p);
    });
    // Jakość per rola (RC = raw; Ekstraklasa ma handicap 0, więc raw = RC)
    const roleRC = Object.entries(byRole).map(([role, ps]) => ({
      role, n: ps.length, rc: Math.round(_mean(ps.map((x) => x.raw))),
    })).sort((a, b) => (OPP_ROLE_ORDER.indexOf(a.role) - OPP_ROLE_ORDER.indexOf(b.role)));
    const rankByRC = [...roleRC].filter((r) => r.n >= 1).sort((a, b) => a.rc - b.rc);
    const weakest = rankByRC[0] || null;
    const strongest = rankByRC[rankByRC.length - 1] || null;
    const overallRC = Math.round(_mean(players.map((p) => p.raw)));

    // Styl (DNA) per linia: średni profile_pos, dominujące tendencje (nad/pod średnią Ekstraklasy)
    const lineStyle = Object.entries(byLine).map(([line, ps]) => {
      const labs = labelsFor(line);
      const vecs = ps.map((x) => x.profile_pos).filter((v) => Array.isArray(v) && labs && v.length === labs.length);
      if (!labs || !vecs.length) return { line, n: ps.length, hi: [], lo: [], predict: null };
      const avg = labs.map((_, i) => _mean(vecs.map((v) => v[i])));
      const ranked = labs.map((l, i) => ({ l, z: avg[i] })).sort((a, b) => b.z - a.z);
      const hi = ranked.filter((x) => x.z > 0.3).slice(0, 3);
      const lo = ranked.filter((x) => x.z < -0.3).slice(-3).reverse();
      // przewidywalność linii = średnie podobieństwo par profili (wysokie = jednorodni)
      let sim = null;
      if (vecs.length >= 2) {
        const ps2 = [];
        for (let i = 0; i < vecs.length; i++) for (let j = i + 1; j < vecs.length; j++) ps2.push(_cos(vecs[i], vecs[j]));
        sim = _mean(ps2);
      }
      return { line, n: ps.length, hi, lo, predict: sim };
    }).sort((a, b) => (["Bramka", "Obrona", "Pomoc", "Atak"].indexOf(a.line) - ["Bramka", "Obrona", "Pomoc", "Atak"].indexOf(b.line)));

    const predVals = lineStyle.map((l) => l.predict).filter((v) => v != null);
    const predictability = predVals.length ? _mean(predVals) : null;

    // Wskazówki (matchup) — generowane z danych, nie z powietrza.
    const tips = [];
    if (weakest) tips.push({ k: "luka", t: `Najsłabsze ogniwo: rola ${roleName({ role: weakest.role }) || weakest.role} (śr. RC ${weakest.rc}, ${weakest.n} zaw.). Naturalny kierunek gry.` });
    if (strongest && strongest.rc - (weakest ? weakest.rc : 0) >= 6) tips.push({ k: "uwaga", t: `Najmocniejsza rola: ${roleName({ role: strongest.role }) || strongest.role} (RC ${strongest.rc}) — tu unikać strat i pojedynków 1v1.` });
    lineStyle.forEach((ls) => {
      if (ls.hi.length && ls.lo.length) {
        tips.push({ k: "tendencja", t: `${ls.line}: dużo „${ls.hi.map((h) => h.l).join(", ")}", mało „${ls.lo.map((h) => h.l).join(", ")}" — przestrzeń tam, gdzie robią mało.` });
      }
      if (ls.predict != null && ls.predict > 0.6 && ls.n >= 2) {
        tips.push({ k: "przewidywalnosc", t: `${ls.line} bardzo jednorodna (podobieństwo ${Math.round(ls.predict * 100)}%) — styl przewidywalny, łatwiejszy do rozpracowania.` });
      }
    });

    return { roleRC, weakest, strongest, overallRC, lineStyle, predictability, tips };
  }, [players]);

  const tipColor = (k) => (k === "luka" ? C.good : k === "uwaga" ? C.warn : k === "przewidywalnosc" ? C.blueHi : C.steelHi);
  const barRC = (rc) => `${Math.max(4, Math.min(100, rc))}%`;

  return (
    <div>
      <Lead>Profil stylu rywala liczony na żywo z danych Ekstraklasy: jak grają per linia, gdzie mają jakość, gdzie lukę i jak przewidywalny jest ich styl. Wskazówki są <b>obserwacjami z danych</b> — ustawienie zostaje po stronie sztabu.</Lead>

      <div style={{ display: "flex", alignItems: "center", gap: 12, margin: "18px 0 6px", flexWrap: "wrap" }}>
        <span className="mono" style={{ fontSize: 11, letterSpacing: 1.5, color: C.steel }}>PRZECIWNIK</span>
        <select value={team} onChange={(e) => setTeamSel(e.target.value)}
          style={{ background: C.panel, color: C.bone, border: `1px solid ${C.line}`, borderRadius: 9, padding: "9px 13px", fontSize: 13.5, minWidth: 240 }}>
          {teams.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <span style={{ fontSize: 12, color: C.steel }}>{players.length} zawodników w danych</span>
      </div>

      {!an ? (
        <div style={{ marginTop: 16 }}>
          <Empty>Brak danych dla tej drużyny w bieżącej puli (za mało zawodników z wystarczającą próbką minut).</Empty>
        </div>
      ) : (
        <>
          {/* Kafle podsumowania */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10, margin: "16px 0 6px" }}>
            <Tile label="Średnie RC drużyny" val={an.overallRC} color={tierColor(an.overallRC)} />
            <Tile label="Przewidywalność stylu" val={an.predictability != null ? `${Math.round(an.predictability * 100)}%` : "—"}
              color={an.predictability != null && an.predictability > 0.6 ? C.blueHi : C.steelHi}
              hint="Podobieństwo stylu w liniach — wysokie = jednorodni, przewidywalni." />
            <Tile label="Najsłabsza rola" val={an.weakest ? (roleName({ role: an.weakest.role }) || an.weakest.role) : "—"}
              sub={an.weakest ? `RC ${an.weakest.rc}` : ""} color={C.good} />
            <Tile label="Najmocniejsza rola" val={an.strongest ? (roleName({ role: an.strongest.role }) || an.strongest.role) : "—"}
              sub={an.strongest ? `RC ${an.strongest.rc}` : ""} color={C.warn} />
          </div>

          <SectionLabel>Jakość per rola (RC)</SectionLabel>
          <div style={{ display: "grid", gap: 7, maxWidth: 620 }}>
            {an.roleRC.map((r) => (
              <div key={r.role} style={{ display: "grid", gridTemplateColumns: "130px 1fr 64px", alignItems: "center", gap: 12 }}>
                <span style={{ fontSize: 12.5, color: C.bone }}>{roleName({ role: r.role }) || r.role}
                  <span style={{ color: C.steel, fontSize: 11 }}> · {r.n}</span></span>
                <div style={{ height: 10, background: C.panel2, borderRadius: 5, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: barRC(r.rc), background: tierColor(r.rc) }} />
                </div>
                <span className="disp" style={{ fontSize: 15, color: tierColor(r.rc) }}>{r.rc}</span>
              </div>
            ))}
          </div>

          <SectionLabel>Styl gry per linia (vs średnia Ekstraklasy)</SectionLabel>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(260px,1fr))", gap: 12 }}>
            {an.lineStyle.map((ls) => (
              <div key={ls.line} style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 11, padding: "13px 15px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
                  <b style={{ fontSize: 13.5, color: C.bone }}>{ls.line}</b>
                  {ls.predict != null && (
                    <span className="mono" style={{ fontSize: 10.5, color: ls.predict > 0.6 ? C.blueHi : C.steel }}>
                      przewid. {Math.round(ls.predict * 100)}%</span>
                  )}
                </div>
                {ls.hi.length ? (
                  <div style={{ fontSize: 12, color: C.steelHi, marginBottom: 4 }}>
                    <span style={{ color: C.good, fontWeight: 700 }}>dużo:</span> {ls.hi.map((h) => h.l).join(", ")}
                  </div>
                ) : null}
                {ls.lo.length ? (
                  <div style={{ fontSize: 12, color: C.steelHi }}>
                    <span style={{ color: C.bad, fontWeight: 700 }}>mało:</span> {ls.lo.map((h) => h.l).join(", ")}
                  </div>
                ) : null}
                {!ls.hi.length && !ls.lo.length ? (
                  <div style={{ fontSize: 12, color: C.steel }}>Profil zbliżony do średniej ligi.</div>
                ) : null}
              </div>
            ))}
          </div>

          <SectionLabel>Wskazówki (z danych — sztab decyduje)</SectionLabel>
          <div style={{ display: "grid", gap: 8, maxWidth: 820 }}>
            {an.tips.length ? an.tips.map((tp, i) => (
              <div key={i} style={{ display: "flex", gap: 10, alignItems: "flex-start", background: C.panel,
                border: `1px solid ${C.line}`, borderLeft: `3px solid ${tipColor(tp.k)}`, borderRadius: 9, padding: "10px 13px" }}>
                <span style={{ color: tipColor(tp.k), fontSize: 14, flexShrink: 0 }}>▸</span>
                <span style={{ fontSize: 13, color: C.bone, lineHeight: 1.5 }}>{tp.t}</span>
              </div>
            )) : <Empty>Za mało sygnału, by wygenerować wskazówki dla tej drużyny.</Empty>}
          </div>

          <Note>RC = jakość względem Ekstraklasy (percentyl metryk per rola). „Dużo/mało" = odchylenie stylu (z-score) danej linii od średniej ligi — nazwy atrybutów z modelu. „Przewidywalność" = podobieństwo stylu zawodników w linii; wysokie oznacza jednorodność, nie słabość. To analiza opisowa rywala i punkty zaczepienia — wybór formacji i składu zostaje przy trenerze.</Note>
        </>
      )}
    </div>
  );
}

// Kafel statystyki (podsumowanie przeciwnika)
function Tile({ label, val, sub, color = C.bone, hint }) {
  return (
    <div title={hint || ""} style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 11, padding: "12px 14px" }}>
      <div className="mono" style={{ fontSize: 10, letterSpacing: 1, color: C.steel, textTransform: "uppercase" }}>{label}</div>
      <div className="disp" style={{ fontSize: 22, color, marginTop: 4, lineHeight: 1.1 }}>{val}</div>
      {sub ? <div style={{ fontSize: 11, color: C.steel, marginTop: 2 }}>{sub}</div> : null}
    </div>
  );
}

function MetricsView({ data }) {
  const cr = useMemo(() => computeStyleCorrelations(data.pool), [data]);
  const { labels, M, NN, clusters, count } = cr;
  const mix = (a, b, t) => a.map((x, i) => Math.round(x + (b[i] - x) * t));
  const surf = [20, 49, 95], red = [228, 2, 43], blue = [62, 123, 236];
  const cellBg = (r) => { if (r === null) return "#0b1a33"; const t = Math.min(1, Math.abs(r)); return `rgb(${mix(surf, r >= 0 ? red : blue, t).join(",")})`; };
  const fmtR = (r) => (r === null ? "" : r.toFixed(2).replace("0.", ".").replace("-0.", "-."));
  const maxr = (c) => { let m = 0; for (let a = 0; a < c.length; a++) for (let b = a + 1; b < c.length; b++) { const r = Math.abs(M[c[a]][c[b]]); if (r > m) m = r; } return m; };
  return (
    <div>
      <Lead>Które metryki stylu w praktyce mierzą to samo (odpowiedź na pytanie o multikolinearność). Korelacja 17 wymiarów profilu, liczona z profili <b className="mono" style={{ color: C.redHi }}>{count}</b> zawodników puli — parami, bez strukturalnych zer. Czerwień = korelacja dodatnia (dublują się), niebieski = ujemna, ciemne = niezależne. Najedź na pole: para, r i próba.</Lead>
      <div style={{ display: "flex", gap: 24, marginTop: 18, flexWrap: "wrap", alignItems: "flex-start" }}>
        <div className="hscroll">
          <table style={{ borderCollapse: "separate", borderSpacing: 2 }}>
            <thead><tr><th></th>{labels.map((l, j) => (
              <th key={j} style={{ height: 116, verticalAlign: "bottom" }}>
                <div style={{ writingMode: "vertical-rl", transform: "rotate(180deg)", color: C.steel, fontSize: 10, fontWeight: 600, whiteSpace: "nowrap" }}>{l}</div>
              </th>))}</tr></thead>
            <tbody>
              {labels.map((l, i) => (
                <tr key={i}>
                  <td className="mono" style={{ color: C.steelHi, fontSize: 10.5, textAlign: "right", paddingRight: 8, whiteSpace: "nowrap", fontWeight: 600 }}>{l}</td>
                  {labels.map((_, j) => {
                    const r = M[i][j], self = i === j, t = r === null ? 0 : Math.abs(r);
                    return (
                      <td key={j}>
                        <div title={`${l} ↔ ${labels[j]}:  r=${r === null ? "—" : r.toFixed(2)}  (n=${NN[i][j]})`}
                          className="mono" style={{ width: 32, height: 32, borderRadius: 4, textAlign: "center", lineHeight: "32px",
                            fontSize: 9.5, fontWeight: 700, color: "#fff", background: cellBg(r), opacity: (self || t > 0.45) ? 1 : 0.66 }}>
                          {self ? "1" : fmtR(r)}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mono" style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 12, fontSize: 11, color: C.steel }}>
            <span>−1</span>
            <span style={{ height: 12, width: 180, borderRadius: 3, background: "linear-gradient(90deg,#3E7BEC,#14315F 50%,#E4022B)" }} />
            <span>+1</span><span style={{ marginLeft: 8 }}>korelacja (r)</span>
          </div>
        </div>
        <div style={{ flex: "1 1 300px", maxWidth: 440 }}>
          <SectionLabel>Klastry redundancji (|r| ≥ 0,70)</SectionLabel>
          <div style={{ display: "grid", gap: 8 }}>
            {clusters.map((c, k) => (
              <div key={k} style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 9, padding: "9px 12px", fontSize: 13 }}>
                <b style={{ color: C.bone }}>{c.map((x) => labels[x]).join(" + ")}</b>
                <span className="mono" style={{ color: C.proxy, fontSize: 11, marginLeft: 8 }}>r≈{maxr(c).toFixed(2)}</span>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 14, background: `${C.warn}12`, border: `1px solid ${C.warn}44`, borderRadius: 12, padding: "14px 16px", fontSize: 12.5, color: C.steelHi, lineHeight: 1.55 }}>
            <b style={{ color: C.bone }}>Wniosek.</b> Część wymiarów zwija się do grup mierzących ten sam sygnał. Koherencja (kosinus na z-score) podwójnie waży te czynniki — np. „kreacja" (podania w tercji + kluczowe + xA) liczy się kilka razy, a niezależna „gra w powietrzu" tylko raz.<br /><br />
            <b style={{ color: C.bone }}>Kierunek naprawy.</b> Przyciąć duplikaty (po jednym reprezentancie na klaster) albo przejść koherencję na dystans Mahalanobisa, który sam odważa skorelowane wymiary przez macierz kowariancji.
          </div>
        </div>
      </div>
      <Note>Korelacja liczona parami, tylko po zawodnikach z niezerową wartością obu metryk (brak fizyki/GI = 0 nie zaniża sztucznie). Dotyczy przestrzeni profilu stylu (koherencja i „Zależności formacji"). Analogiczna diagnostyka dla metryk RC wymaga surowych wartości — do dołożenia jako log pipeline.</Note>
    </div>
  );
}

// ============================ STABILNOŚĆ METRYK (ICC / test-retest) ============================
const STAB_TIER = {
  stable:   { c: C.good,  label: "stabilna" },
  moderate: { c: C.proxy, label: "umiarkowana" },
  noisy:    { c: C.bad,   label: "szumna" },
};
function StabilityView({ data }) {
  const S = data.stability;
  if (!S || S.available === false || !Array.isArray(S.metrics) || !S.metrics.length) {
    return (
      <div>
        <Lead>Stabilność metryk wejściowych: mierzymy powtarzalność każdej metryki między sezonami (test-retest). Metryki niepowtarzalne wnoszą do modelu głównie szum — to kandydaci do obniżenia wagi albo usunięcia.</Lead>
        <InfoBanner>
          Analiza pojawi się po najbliższym odświeżeniu — pipeline liczy ją z zestawienia sezonu bieżącego i historycznego Ekstraklasy (<span className="mono">STABILITY</span>). Jeśli sezon historyczny nie jest dostępny, ekran pozostaje pusty, a reszta aplikacji działa bez zmian.
        </InfoBanner>
        <div style={{ marginTop: 16 }}>
          <Empty>Brak danych stabilności{S && S.reason ? ` (${S.reason})` : ""}. Uruchom odświeżenie danych.</Empty>
        </div>
      </div>
    );
  }
  const { metrics, summary, n_players, seasons } = S;
  const barW = (r) => `${Math.round(Math.max(0, Math.min(1, r)) * 100)}%`;

  return (
    <div>
      <Lead>Które metryki są <b>powtarzalne</b> (odpowiedź na p.7 audytu). Dla każdej metryki liczymy korelację rang (Spearman) tej samej wartości między sezonem bieżącym a poprzednim, na <b className="mono" style={{ color: C.redHi }}>{n_players}</b> zawodnikach Ekstraklasy z ≥{S.min_minutes} min w obu sezonach. Wysoka = sygnał (metryka mówi o zawodniku, nie o kontekście); niska = szum — kandydat do odchudzenia modelu.</Lead>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 10, margin: "16px 0 18px" }}>
        <Kpi l="Stabilne (≥0,60)" v={summary.stable} c={summary.stable ? C.good : C.steel} />
        <Kpi l="Umiarkowane" v={summary.moderate} c={summary.moderate ? C.proxy : C.steel} />
        <Kpi l="Szumne (<0,40)" v={summary.noisy} c={summary.noisy ? C.bad : C.steel} />
        <Kpi l="Zawodnicy" v={n_players} />
      </div>

      <div style={{ display: "grid", gap: 7 }}>
        {metrics.map((m) => {
          const t = STAB_TIER[m.tier] || STAB_TIER.moderate;
          return (
            <div key={m.key} style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 10, padding: "10px 14px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                <div style={{ flex: "1 1 220px", minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 13.5, fontWeight: 600, color: C.bone }}>{m.label}</span>
                    {(m.lines || []).map((ln) => (
                      <span key={ln} className="mono" style={{ fontSize: 9.5, color: C.steel, border: `1px solid ${C.line}`, borderRadius: 4, padding: "0 5px" }}>{ln}</span>
                    ))}
                  </div>
                </div>
                <div style={{ flex: "2 1 260px", display: "flex", alignItems: "center", gap: 10, minWidth: 200 }}>
                  <div style={{ flex: 1, height: 8, background: C.ink, borderRadius: 5, overflow: "hidden" }}>
                    <div style={{ width: barW(m.rho), height: "100%", background: t.c, borderRadius: 5 }} />
                  </div>
                  <span className="mono" style={{ fontSize: 12.5, fontWeight: 700, color: t.c, width: 46, textAlign: "right" }}>
                    {m.rho.toFixed(2).replace("0.", ".").replace("-0.", "-.")}
                  </span>
                  <span className="mono" style={{ fontSize: 10, color: t.c, background: `${t.c}18`, borderRadius: 5, padding: "1px 6px", width: 82, textAlign: "center" }}>{t.label}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ marginTop: 18, background: `${C.warn}12`, border: `1px solid ${C.warn}44`, borderRadius: 12, padding: "14px 16px", fontSize: 12.5, color: C.steelHi, lineHeight: 1.55, maxWidth: 820 }}>
        <b style={{ color: C.bone }}>Wniosek.</b> Metryki „szumne" (niskie ρ) słabo powtarzają się między sezonami — w równoważonym modelu RC wnoszą tyle samo, co stabilne, mimo że mierzą głównie kontekst/wariancję. To one są kandydatami do obniżenia wagi lub usunięcia.<br /><br />
        <b style={{ color: C.bone }}>Kierunek naprawy.</b> Zważyć metryki przez ich stabilność (albo odciąć poniżej progu ρ) — analogicznie do korekty multikolinearności. Zmiana jest zaplanowana jako przełączalna, żeby zwalidować wpływ na zgodność z ocenami trenerów przed włączeniem na stałe.
      </div>

      <Note>Test-retest MIĘDZY sezonami ({seasons ? `${seasons.previous_label} → bieżący` : "poprzedni → bieżący"}). To miara uczciwa, ale miesza prawdziwą niestabilność metryki z realną zmianą zawodnika (forma, rola, drużyna, wiek), więc bezwzględne wartości ρ traktujemy jako orientacyjne, a ranking metryk jako sygnał. Ściślejszy split-half w obrębie sezonu (po meczach) to naturalny, cięższy upgrade — wymaga danych meczowych całej populacji.</Note>
    </div>
  );
}

function HelpView({ data, setView }) {
  const steps = [
    ["Skład", "Zakładka „Skład” to obecny zespół ułożony liniami, jak na tablicy taktycznej. Każda karta ma poziom RC (Ekstraklasa = baza). Klik przenosi do odpowiedników."],
    ["Odpowiednicy", "Kandydaci z lig europejskich na tej samej pozycji. Dwie miary obok siebie: poziom (jak dobry jest zawodnik) i koherencja (jak podobnie gra do zawodnika Rakowa). Filtry (wiek, cena, koherencja, ligi) oraz preset Fragmentator (≤3 mln €, ≤26 lat) zatwierdzasz przyciskiem Szukaj — wyniki nie odświeżają się, dopóki nie klikniesz."],
    ["Szukaj", "Wyszukiwarka ręczna: wpisz nazwisko, a znajdziesz dowolnego zawodnika w całej puli, niezależnie od pozycji — z poziomem, koherencją, wartością rynkową i linkiem do Transfermarktu."],
    ["Lista obserwowanych", "Gwiazdka przy kandydacie dodaje go do listy na dole. Aplikacja sumuje łączny szacowany koszt zaznaczonych zawodników."],
    ["Handicapy", "Tabela: o ile każda liga różni się od Ekstraklasy, osobno per linia. To te korekty podnoszą lub obniżają surowy poziom kandydata."],
    ["Zależności", "Macierz podobieństwa stylu między pozycjami — liczona z profili stylu całej puli (kosinus centroidów). Ciemne = role grają podobnie, jasne = uzupełniają się. To pokrewieństwo stylu, nie sieć podań."],
    ["Dane live", "Przycisk w lewym panelu pobiera świeże dane, gdy źródło jest podpięte. Bez tego działają dane zapisane."],
  ];
  const sources = [
    ["StatsBomb", "Metryki techniczne zawodników — podstawa poziomów RC, handicapów lig i profilu koherencji.", C.good],
    ["SkillCorner", "Fizyka (dystans, sprinty, prędkość, dynamika) i Game Intelligence (biegi bez piłki, styl podań, pressing). Zasila koherencję (styl gry), NIE poziom RC.", C.redHi],
    ["Wartości rynkowe (Kaggle)", "Wartości rynkowe, wiek i kontrakty kandydatów — ze stabilnego, okresowo aktualizowanego zbioru danych.", C.proxy],
  ];
  const defs = [
    ["RC / poziom", "Skala 0–100. Percentyl metryk jakościowych zawodnika względem Ekstraklasy (baza). Wyższy = mocniejszy. Liczony automatycznie z metryk StatsBomb."],
    ["Poziom surowy vs skorygowany", "Surowy — poziom liczony w lidze zawodnika. Skorygowany — surowy podniesiony/obniżony o handicap jego ligi względem Ekstraklasy."],
    ["Handicap ligi", "O ile dana liga jest mocniejsza/słabsza od Ekstraklasy, osobno per linia (bramka/obrona/pomoc/atak). Reguła: 10% różnicy = RC ± 1."],
    ["Koherencja", "Skala 0–100. Jak podobnie kandydat GRA do konkretnego zawodnika Rakowa (podobieństwo profili). Obejmuje technikę (StatsBomb), fizykę i taktykę ruchu (SkillCorner). Nie myl z poziomem — to podobieństwo stylu, nie jakość."],
    ["Fizyka (SkillCorner)", "Dystans, biegi wysokiej intensywności, sprinty, prędkość szczytowa, przyspieszenia, zwroty. Wchodzi do koherencji (styl), nie do RC."],
    ["Game Intelligence (SkillCorner)", "Biegi bez piłki, styl i zasięg podań, oferowanie się, prowadzenie pod presją, pressing/odbiory. Wchodzi do koherencji (styl), nie do RC."],
    ["b.d. (brak danych)", "W miejscu poziomu/RC pojawia się b.d., gdy zawodnik nie ma wystarczającej próbki meczowej — poziomu nie da się policzyć. To nie ocena negatywna, tylko brak danych."],
    ["Cena (estymacja)", "Wartość rynkowa skorygowana o poziom vs RC, wiek, długość kontraktu i mnożnik ligi. Zwraca punkt i widełki (−20% / +25%). Placeholder do kalibracji na zrealizowanych transferach."],
  ];
  return (
    <div>
      <Lead>Krótki przewodnik po narzędziu i po tym, skąd biorą się liczby.</Lead>

      <SectionLabel>Ekrany</SectionLabel>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))", gap: 12 }}>
        {steps.map(([t, d], i) => (
          <div key={t} style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 12, padding: "16px 18px", display: "flex", gap: 13 }}>
            <div className="disp" style={{ flexShrink: 0, fontSize: 20, color: C.red, width: 26 }}>{String(i + 1).padStart(2, "0")}</div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>{t}</div>
              <div style={{ fontSize: 12.5, color: C.steel, lineHeight: 1.5 }}>{d}</div>
            </div>
          </div>
        ))}
      </div>

      <SectionLabel>Skąd biorą się dane</SectionLabel>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(260px,1fr))", gap: 12 }}>
        {sources.map(([t, d, c]) => (
          <div key={t} style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 12, padding: "16px 18px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: c }} />
              <span style={{ fontSize: 14, fontWeight: 700 }}>{t}</span>
            </div>
            <div style={{ fontSize: 12.5, color: C.steel, lineHeight: 1.5 }}>{d}</div>
          </div>
        ))}
      </div>

      <SectionLabel>Definicje</SectionLabel>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))", gap: 10 }}>
        {defs.map(([t, d]) => (
          <div key={t} style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 12, padding: "14px 16px" }}>
            <div style={{ fontSize: 13.5, fontWeight: 700, marginBottom: 4, color: C.bone }}>{t}</div>
            <div style={{ fontSize: 12.5, color: C.steel, lineHeight: 1.5 }}>{d}</div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 18, background: `${C.proxy}12`, border: `1px solid ${C.proxy}44`, borderRadius: 12, padding: "16px 18px" }}>
        <b style={{ color: C.proxy, fontSize: 13 }}>Jak czytać liczby.</b>
        <span style={{ fontSize: 13, color: C.steelHi }}> Poziom RC jest liczony automatycznie z realnych metryk StatsBomb (percentyl względem Ekstraklasy) — to działający model, nie wpisywane ręcznie wartości. Dobór metryk oceniających zawodnika na danej pozycji to jednak przyjęte założenie, które warto potwierdzić od strony sportowej. Zawodnicy bez wystarczającej próbki meczowej mają poziom szacowany (znacznik ⚠). Wszystkie ekrany liczą się z realnych danych. Traktuj liczby jako mocną wersję roboczą, nie ostateczną.</span>
      </div>

      <SectionLabel>Status i ograniczenia modelu</SectionLabel>
      <div style={{ fontSize: 12.5, color: C.steel, lineHeight: 1.55, marginBottom: 12, maxWidth: 760 }}>
        Uczciwie o tym, czemu można ufać dziś, a co jest świadomie w wersji roboczej. Nic tu nie jest jeszcze zwalidowane pod <b style={{ color: C.steelHi }}>automatyczne</b> decyzje — to mocne wsparcie do zawężania i stawiania hipotez.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(300px,1fr))", gap: 12 }}>
        <div style={{ background: C.panel, border: `1px solid ${C.good}44`, borderRadius: 12, padding: "14px 16px" }}>
          <div className="cond" style={{ fontSize: 12, letterSpacing: 1, color: C.good, fontWeight: 700, marginBottom: 8 }}>DZIAŁA</div>
          {[
            "Poziom RC — percentyl metryk StatsBomb vs Ekstraklasa (≥540 min)",
            "Possession-adjustment RC — metryki per-posiadanie (obrona, pomoc) + normalizacja wolumenu przez posiadanie drużyny",
            "Shrinkage RC — mała próba minut ściągana w stronę średniej",
            "Koherencja stylu — wybielony kosinus (Mahalanobis): odważa skorelowane metryki",
            "Handicapy lig — korekta poziomu o siłę ligi per linia",
            "Zależności formacji — podobieństwo stylu ról, z miarą sygnał/szum",
          ].map((t, i) => (
            <div key={i} style={{ fontSize: 12.5, color: C.steelHi, lineHeight: 1.5, marginBottom: 5, display: "flex", gap: 7 }}>
              <span style={{ color: C.good }}>✓</span><span>{t}</span></div>
          ))}
        </div>
        <div style={{ background: C.panel, border: `1px solid ${C.warn}44`, borderRadius: 12, padding: "14px 16px" }}>
          <div className="cond" style={{ fontSize: 12, letterSpacing: 1, color: C.warn, fontWeight: 700, marginBottom: 8 }}>W TOKU / ŚWIADOME OGRANICZENIA</div>
          {[
            "Brak analizy stabilności (ICC / test-retest) — powtarzalność metryk między połowami sezonu",
            "Handicap: jedna metryka reprezentuje linię (miesza tempo z jakością)",
            "„Spadek formy” w flagach: na razie migawka, bez okna czasowego",
            "Estymacja ceny: placeholder do kalibracji na realnych transferach",
            "Walidacja na ocenach trenerów: wstępna, mała próba",
          ].map((t, i) => (
            <div key={i} style={{ fontSize: 12.5, color: C.steelHi, lineHeight: 1.5, marginBottom: 5, display: "flex", gap: 7 }}>
              <span style={{ color: C.warn }}>•</span><span>{t}</span></div>
          ))}
        </div>
      </div>

      <button onClick={() => setView("twin")} style={{ marginTop: 18, background: C.red, color: "#fff",
        border: "none", padding: "11px 20px", borderRadius: 9, cursor: "pointer", fontSize: 13, fontWeight: 700 }}>
        Zacznij od składu →
      </button>
    </div>
  );
}

// ============================ FILTRY ============================
function countActiveFilters(f, d) {
  let n = 0;
  if (f.ageMin !== d.ageMin || f.ageMax !== d.ageMax) n++;
  if (f.priceMax !== d.priceMax) n++;
  if (f.showUnpriced !== d.showUnpriced) n++;
  if (f.cohMin !== d.cohMin) n++;
  if (f.levelMin !== d.levelMin) n++;
  if (f.onlyReliable !== d.onlyReliable) n++;
  if (f.leagues.length > 0) n++;
  return n;
}

function FilterPanel({ data, filters, setF, applyFilters, resetFilters, filtersDirty, FILTERS_DEFAULT,
  filtersOpen, setFiltersOpen, activeCount, shown, total }) {
  const F = filters;
  const leagues = [...new Set(data.pool.map((p) => p.lg))].filter(Boolean).sort();
  const AGE_PRESETS = [["do 23", { ageMin: 16, ageMax: 23 }], ["24-28", { ageMin: 24, ageMax: 28 }],
    ["29+", { ageMin: 29, ageMax: 45 }], ["każdy", { ageMin: 16, ageMax: 45 }]];
  const isPreset = (p) => F.ageMin === p.ageMin && F.ageMax === p.ageMax;

  return (
    <div style={{ marginBottom: 18, background: C.panel, border: `1px solid ${activeCount > 0 ? C.redHi : C.line}`,
      borderRadius: 12, overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "stretch" }}>
        <button onClick={() => setFiltersOpen(!filtersOpen)}
          style={{ flex: 1, display: "flex", alignItems: "center", gap: 10, background: "transparent",
            border: "none", color: C.bone, padding: "12px 16px", cursor: "pointer", fontSize: 13, fontWeight: 600 }}>
          <span className="mono" style={{ fontSize: 11, letterSpacing: 1.5, color: activeCount > 0 ? C.redHi : C.steel }}>
            FILTRY
          </span>
          {activeCount > 0 && (
            <span className="mono" style={{ fontSize: 10, fontWeight: 800, background: C.red, color: "#fff",
              borderRadius: 20, padding: "2px 8px" }}>{activeCount}</span>
          )}
          <span style={{ marginLeft: "auto", fontSize: 12, color: C.steel, fontWeight: 500 }}>
            {shown} z {total} kandydatów
          </span>
          <span className="mono" style={{ fontSize: 11, color: C.steel }}>{filtersOpen ? "▲" : "▼"}</span>
        </button>
        {filtersDirty && (
          <button onClick={applyFilters} title="Zastosuj zmienione filtry"
            style={{ background: C.red, color: "#fff", border: "none", padding: "0 18px",
              cursor: "pointer", fontSize: 13, fontWeight: 700, whiteSpace: "nowrap" }}>
            Szukaj ↵
          </button>
        )}
      </div>

      {filtersOpen && (
        <div style={{ padding: "4px 16px 16px", borderTop: `1px solid ${C.line}`,
          display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: 18 }}>

          {/* PRESETY */}
          <div style={{ gridColumn: "1 / -1", display: "flex", flexWrap: "wrap", gap: 8,
            alignItems: "center", paddingTop: 12 }}>
            <span className="mono" style={{ fontSize: 10, letterSpacing: 1, color: C.steel, textTransform: "uppercase" }}>Preset</span>
            <button onClick={() => setF({ ageMin: 16, ageMax: 26, priceMax: 3, showUnpriced: true })}
              style={{ background: C.red, color: "#fff", border: "none", borderRadius: 8,
                padding: "6px 12px", fontSize: 12, cursor: "pointer", fontWeight: 700 }}>
              Fragmentator · ≤3 mln € · ≤26 lat
            </button>
            <span style={{ fontSize: 11, color: C.steel }}>ustawia filtry — zatwierdź „Szukaj"</span>
          </div>

          {/* WIEK */}
          <div style={{ paddingTop: 14 }}>
            <FLabel>Wiek: <b style={{ color: C.bone }}>{F.ageMin > 16 ? `${F.ageMin}-${F.ageMax}` : `do ${F.ageMax}`}</b> lat</FLabel>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginBottom: 9 }}>
              {AGE_PRESETS.map(([lbl, p]) => (
                <button key={lbl} onClick={() => setF(p)} style={{
                  background: isPreset(p) ? C.red : "transparent", color: isPreset(p) ? "#fff" : C.steel,
                  border: `1px solid ${isPreset(p) ? C.red : C.line}`, borderRadius: 7,
                  padding: "4px 10px", fontSize: 11.5, cursor: "pointer", fontWeight: 600 }}>{lbl}</button>
              ))}
            </div>
            {/* Jeden suwak — górna granica wieku (dwa nakładające się rozjeżdżały się). */}
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <input type="range" min={16} max={45} value={F.ageMax}
                onChange={(e) => setF({ ageMax: Math.max(+e.target.value, F.ageMin) })}
                style={{ flex: 1, accentColor: C.red }} />
              <span className="mono" style={{ fontSize: 12, color: C.steelHi, width: 48, textAlign: "right" }}>{F.ageMax} lat</span>
            </div>
          </div>

          {/* CENA */}
          <div style={{ paddingTop: 14 }}>
            <FLabel>Cena maks.: <b style={{ color: C.bone }}>
              {F.priceMax >= 50 ? "bez limitu" : `€${F.priceMax}M`}</b></FLabel>
            <input type="range" min={0} max={50} step={0.5} value={F.priceMax}
              onChange={(e) => setF({ priceMax: +e.target.value })}
              style={{ width: "100%", accentColor: C.red, marginBottom: 8 }} />
            <label style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12,
              color: C.steelHi, cursor: "pointer" }}>
              <input type="checkbox" checked={F.showUnpriced}
                onChange={(e) => setF({ showUnpriced: e.target.checked })}
                style={{ accentColor: C.red, cursor: "pointer" }} />
              Pokaż też bez wyceny
            </label>
            <div style={{ fontSize: 10.5, color: C.steel, marginTop: 4, lineHeight: 1.4 }}>
              Część kandydatów nie ma wartości rynkowej w bazie — filtr ceny ich nie dotyczy.
            </div>
          </div>

          {/* KOHERENCJA + POZIOM */}
          <div style={{ paddingTop: 14 }}>
            <FLabel>Min. koherencja: <b style={{ color: C.bone }}>{F.cohMin}%</b></FLabel>
            <input type="range" min={0} max={100} value={F.cohMin}
              onChange={(e) => setF({ cohMin: +e.target.value })}
              style={{ width: "100%", accentColor: C.red, marginBottom: 12 }} />
            <FLabel>Min. poziom: <b style={{ color: C.bone }}>{F.levelMin}</b></FLabel>
            <input type="range" min={0} max={100} value={F.levelMin}
              onChange={(e) => setF({ levelMin: +e.target.value })}
              style={{ width: "100%", accentColor: C.red }} />
          </div>

          {/* JAKOSC DANYCH + LIGI */}
          <div style={{ paddingTop: 14 }}>
            <FLabel>Jakość danych</FLabel>
            <label style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12,
              color: C.steelHi, cursor: "pointer", marginBottom: 12 }}>
              <input type="checkbox" checked={F.onlyReliable}
                onChange={(e) => setF({ onlyReliable: e.target.checked })}
                style={{ accentColor: C.red, cursor: "pointer" }} />
              Tylko pełne dane (bez ⚠)
            </label>
            <FLabel>Ligi {F.leagues.length > 0 && <span style={{ color: C.redHi }}>({F.leagues.length})</span>}</FLabel>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5, maxHeight: 108, overflowY: "auto" }}>
              {leagues.map((lg) => {
                const on = F.leagues.includes(lg);
                return (
                  <button key={lg} onClick={() => setF({
                    leagues: on ? F.leagues.filter((x) => x !== lg) : [...F.leagues, lg] })}
                    title={lg} style={{ background: on ? C.red : "transparent", color: on ? "#fff" : C.steel,
                      border: `1px solid ${on ? C.red : C.line}`, borderRadius: 7, padding: "4px 9px",
                      fontSize: 11, cursor: "pointer", fontWeight: 600, maxWidth: 190,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{lg}</button>
                );
              })}
            </div>
          </div>

          <div style={{ gridColumn: "1 / -1", paddingTop: 4, display: "flex", gap: 10,
            alignItems: "center", flexWrap: "wrap" }}>
            <button onClick={applyFilters} disabled={!filtersDirty}
              style={{ background: filtersDirty ? C.red : C.panel2, color: filtersDirty ? "#fff" : C.steel,
                border: `1px solid ${filtersDirty ? C.red : C.line}`, borderRadius: 8, padding: "8px 20px",
                fontSize: 13, cursor: filtersDirty ? "pointer" : "default", fontWeight: 700 }}>
              Szukaj
            </button>
            {activeCount > 0 && (
              <button onClick={resetFilters}
                style={{ background: "transparent", color: C.redHi, border: `1px solid ${C.red}66`,
                  borderRadius: 8, padding: "8px 14px", fontSize: 12, cursor: "pointer", fontWeight: 600 }}>
                Wyczyść ({activeCount})
              </button>
            )}
            {filtersDirty && (
              <span style={{ fontSize: 11.5, color: C.warn }}>
                Zmieniono filtry — kliknij „Szukaj", by zastosować.
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
function FLabel({ children }) {
  return <div className="mono" style={{ fontSize: 10, letterSpacing: 1, color: C.steel,
    textTransform: "uppercase", marginBottom: 7 }}>{children}</div>;
}

// ============================ PRIMITIVES ============================
function Splash({ children }) {
  return (
    <div style={{ minHeight: "100vh", background: C.ink, color: C.steel, display: "flex",
      alignItems: "center", justifyContent: "center", fontFamily: "'Inter',system-ui", fontSize: 14,
      padding: 24, textAlign: "center" }}>{children}</div>
  );
}
function Stat({ n, l, accent }) {
  return (
    <div>
      <div className="disp" style={{ fontSize: 30, lineHeight: 0.9, color: accent ? C.redHi : C.bone }}>{n}</div>
      <div className="mono" style={{ fontSize: 10, color: C.steel, letterSpacing: 1, marginTop: 3 }}>{l}</div>
    </div>
  );
}
function Kpi({ l, v, c }) {
  return (
    <div style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 11, padding: "12px 15px" }}>
      <div className="mono" style={{ fontSize: 9.5, color: C.steel, letterSpacing: 1, textTransform: "uppercase" }}>{l}</div>
      <div className="disp" style={{ fontSize: 22, marginTop: 3, color: c || C.bone }}>{v}</div>
    </div>
  );
}
function Lead({ children }) {
  return <p style={{ fontSize: 14.5, color: C.steelHi, lineHeight: 1.55, maxWidth: 760, margin: 0 }}>{children}</p>;
}
function Note({ children }) {
  return <p style={{ fontSize: 11.5, color: C.steel, lineHeight: 1.55, marginTop: 18, maxWidth: 760 }}>{children}</p>;
}
function RcExplainer({ compact }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: compact ? 12 : 16, maxWidth: 760 }}>
      <button onClick={() => setOpen((o) => !o)}
        style={{ display: "inline-flex", alignItems: "center", gap: 8, background: `${C.red}14`,
          border: `1px solid ${C.red}44`, borderRadius: 9, padding: "8px 13px", cursor: "pointer",
          color: C.bone, fontSize: 12.5, fontWeight: 600 }}>
        <span className="mono" style={{ fontSize: 10, fontWeight: 800, color: C.redHi,
          border: `1px solid ${C.red}`, borderRadius: 4, padding: "1px 5px" }}>RC</span>
        Co oznacza RC?
        <span className="mono" style={{ fontSize: 11, color: C.steel }}>{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div style={{ marginTop: 8, background: C.panel, border: `1px solid ${C.line}`, borderRadius: 12,
          padding: "15px 17px", fontSize: 13, color: C.steelHi, lineHeight: 1.6 }}>
          <b style={{ color: C.bone }}>RC (Rating Class)</b> to poziom zawodnika w skali 0–100, gdzie punktem
          odniesienia jest <b style={{ color: C.bone }}>Ekstraklasa</b> — polska liga stanowi bazę (handicap 0%).
          Im wyższe RC, tym mocniejszy zawodnik.
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
            <div>· <b style={{ color: C.bone }}>Surowy RC</b> — poziom zawodnika liczony w jego własnej lidze.</div>
            <div>· <b style={{ color: C.bone }}>Handicap ligi</b> — o ile dana liga jest mocniejsza/słabsza od Ekstraklasy,
              osobno per linia (bramka / obrona / pomoc / atak).</div>
            <div>· <b style={{ color: C.bone }}>Poziom skorygowany</b> — surowy RC podniesiony lub obniżony o handicap.
              Reguła: <span className="mono" style={{ color: C.proxy }}>10% różnicy ligi = RC+1</span>.</div>
          </div>
          {!compact && (
            <div style={{ marginTop: 10, fontSize: 12, color: C.steel }}>
              Przykład: zawodnik z RC 55 w lidze o handicapie pomocy +10% ma poziom skorygowany 57 względem Ekstraklasy.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
function Empty({ children }) {
  return (
    <div style={{ background: C.panel, border: `1px dashed ${C.line}`, borderRadius: 12, padding: 24,
      color: C.steel, fontSize: 13.5, lineHeight: 1.5 }}>{children}</div>
  );
}
// Kolor "tieru" karty (FIFA-like): złoto / srebro / brąz wg poziomu RC.
function tierColor(rc) {
  const v = Number(rc);
  if (!Number.isFinite(v)) return C.steel;
  if (v >= 72) return "#E8C15A";   // złoto
  if (v >= 58) return "#C7CBD1";   // srebro
  return "#C58A5A";                // brąz
}
// Znacznik „ocena z danych historycznych" — dla zawodników, których RC policzono
// z poprzedniego sezonu (brak wystarczającej próbki w bieżącym). Odróżnia realną
// ocenę na świeżych danych od tej dociągniętej z historii.
function HistBadge({ p, fontSize = 9, ml = 5 }) {
  if (!p || p.rc_source !== "historical") return null;
  const s = p.rc_season || "poprz. sezonu";
  return (
    <span className="mono"
      title={`Ocena policzona na danych z sezonu ${s} — zawodnik nie ma jeszcze wystarczającej próbki meczowej w bieżącym sezonie.`}
      style={{ fontSize, color: C.blueHi, background: `${C.blueHi}1c`, border: `1px solid ${C.blueHi}66`,
        borderRadius: 4, padding: "1px 5px", fontWeight: 700, marginLeft: ml, whiteSpace: "nowrap", cursor: "help" }}>
      hist. {s}
    </span>
  );
}
// Pojedynczy słupek atrybutu (z-score → szerokość, kolor wg znaku).
function AttrBar({ label, z, better }) {
  const col = better === false ? C.bad : better === true ? C.good : (z >= 0 ? C.good : C.bad);
  const w = Math.min(Math.abs(z) / 3, 1) * 100;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
      <span style={{ fontSize: 11.5, color: C.steelHi, width: 152, flexShrink: 0,
        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }} title={label}>{label}</span>
      <div style={{ flex: 1, height: 6, background: C.panel2, borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${w}%`, height: "100%", background: col }} />
      </div>
      <span className="mono" style={{ fontSize: 10.5, color: col, width: 34, textAlign: "right", flexShrink: 0 }}>
        {z > 0 ? "+" : ""}{z.toFixed(1)}
      </span>
    </div>
  );
}
// Mocne strony zawodnika — top atrybuty wg profilu stylu (z-score vs Ekstraklasa).
function StrengthsPanel({ profile, name, labels }) {
  if (!Array.isArray(profile) || profile.length === 0) {
    return <Empty>Profil stylu <b>{name}</b> pojawi się po najbliższym odświeżeniu danych ze StatsBomb (pipeline dokłada wektor atrybutów do <span className="mono">data.json</span>).</Empty>;
  }
  const L = (Array.isArray(labels) && labels.length) ? labels : STYLE_LABELS;
  const items = profile
    .map((z, i) => ({ label: L[i], z: Number(z) || 0 }))
    .filter((x) => x.label && x.z !== 0 && Math.abs(x.z) >= 0.5);
  const strong = items.filter((x) => x.z > 0).sort((a, b) => b.z - a.z).slice(0, 6);
  const weak = items.filter((x) => x.z < 0).sort((a, b) => a.z - b.z).slice(0, 4);
  if (!strong.length && !weak.length) {
    return <Empty>Profil <b>{name}</b> jest blisko średniej Ekstraklasy we wszystkich atrybutach — brak wyraźnych wychyleń.</Empty>;
  }
  return (
    <div style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 12, padding: "16px 18px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))", gap: "8px 28px" }}>
        <div>
          <div className="mono" style={{ fontSize: 10.5, letterSpacing: 1.5, color: C.good, fontWeight: 700, marginBottom: 10 }}>MOCNE STRONY</div>
          {strong.length ? strong.map((x) => <AttrBar key={x.label} label={x.label} z={x.z} />)
            : <div style={{ fontSize: 12, color: C.steel }}>brak wyraźnych atutów nad średnią ligi</div>}
        </div>
        {weak.length > 0 && (
          <div>
            <div className="mono" style={{ fontSize: 10.5, letterSpacing: 1.5, color: C.bad, fontWeight: 700, marginBottom: 10 }}>DO POPRAWY</div>
            {weak.map((x) => <AttrBar key={x.label} label={x.label} z={x.z} />)}
          </div>
        )}
      </div>
      <div style={{ fontSize: 10.5, color: C.steel, marginTop: 10 }}>
        Skala: z-score względem Ekstraklasy (0 = średnia ligi). Atrybuty fizyczne (bieg, sprinty, prędkość) tylko dla zawodników z danymi SkillCorner.
      </div>
    </div>
  );
}
// "W czym kandydat lepszy od naszego" — różnica profili metryka po metryce.
// Preferuje profil dopasowany do pozycji (profile_pos + etykiety z data.json),
// z fallbackiem do profilu uniwersalnego, gdy danych pozycyjnych brak.
function ComparePanel({ sel, cand, labels }) {
  const usePos = Array.isArray(labels) && labels.length
    && Array.isArray(sel?.profile_pos) && Array.isArray(cand?.profile_pos);
  const a = usePos ? sel.profile_pos : (Array.isArray(sel?.profile) ? sel.profile : null);
  const b = usePos ? cand.profile_pos : (Array.isArray(cand?.profile) ? cand.profile : null);
  const L = usePos ? labels : STYLE_LABELS;
  if (!a || !b) {
    return (
      <div style={{ background: C.panel2, borderTop: `1px solid ${C.line}`, borderRadius: "0 0 12px 12px", padding: "12px 18px", fontSize: 12, color: C.steel }}>
        Porównanie atrybutów włączy się po najbliższym odświeżeniu danych ze StatsBomb — pipeline dokłada profil stylu {!a ? "naszego zawodnika" : "kandydata"} do <span className="mono">data.json</span>.
      </div>
    );
  }
  const diffs = L
    .map((label, i) => ({ label, d: (Number(b[i]) || 0) - (Number(a[i]) || 0), any: (Number(a[i]) || 0) !== 0 || (Number(b[i]) || 0) !== 0 }))
    .filter((x) => x.any && Math.abs(x.d) >= 0.4);
  const better = diffs.filter((x) => x.d > 0).sort((x, y) => y.d - x.d).slice(0, 4);
  const worse = diffs.filter((x) => x.d < 0).sort((x, y) => x.d - y.d).slice(0, 4);
  return (
    <div style={{ background: C.panel2, borderTop: `1px solid ${C.line}`, borderRadius: "0 0 12px 12px", padding: "14px 18px" }}>
      {(!better.length && !worse.length) ? (
        <div style={{ fontSize: 12, color: C.steel }}>Profile stylu obu zawodników są bardzo zbliżone — brak wyraźnych różnic w atrybutach.</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))", gap: "8px 28px" }}>
          <div>
            <div className="mono" style={{ fontSize: 10.5, letterSpacing: 1.5, color: C.good, fontWeight: 700, marginBottom: 10 }}>LEPSZY OD {surnameU(sel.name)}</div>
            {better.length ? better.map((x) => <AttrBar key={x.label} label={x.label} z={x.d} better={true} />)
              : <div style={{ fontSize: 12, color: C.steel }}>w żadnym atrybucie wyraźnie nie przewyższa</div>}
          </div>
          <div>
            <div className="mono" style={{ fontSize: 10.5, letterSpacing: 1.5, color: C.bad, fontWeight: 700, marginBottom: 10 }}>SŁABSZY</div>
            {worse.length ? worse.map((x) => <AttrBar key={x.label} label={x.label} z={x.d} better={false} />)
              : <div style={{ fontSize: 12, color: C.steel }}>nie ustępuje w żadnym istotnym atrybucie</div>}
          </div>
        </div>
      )}
      <div style={{ fontSize: 10.5, color: C.steel, marginTop: 10 }}>Różnica z-score: kandydat − {sel.name}. Porównywane tylko atrybuty z realną próbką.</div>
    </div>
  );
}
const surnameU = (nm) => { const t = String(nm || "").trim().split(" "); return (t[t.length - 1] || "").toUpperCase(); };
// TOP5 do obserwacji — najlepszy kompromis jakość / cena.
// skill = mieszanka poziomu i koherencji (dopasowania do naszego zawodnika),
// wartość = skill / pierwiastek z ceny (kara za cenę maleje przy droższych).
// Bramka jakości (skill>=62, luzowana), żeby nie promować taniej przypadkowości.
function Top5Panel({ candidates, sel, short, toggleShort, fmt }) {
  // Domyślny profil obserwacji: młodzi (≤25 lat) i tani (≤3 mln €).
  const AGE_CAP = 25, PRICE_CAP = 3;
  const scored = candidates
    .filter((c) => !c.p.level_estimated && c.price && c.price.est > 0
      && c.price.est <= PRICE_CAP && (Number(c.p.age) || 99) <= AGE_CAP)
    .map((c) => {
      const skill = 0.45 * (Number(c.m.level) || 0) + 0.55 * (Number(c.m.coherence) || 0);
      const value = skill / Math.sqrt(Math.max(c.price.est, 0.5));
      return { ...c, skill, value };
    });
  if (!scored.length) return (
    <div style={{ margin: "4px 0 20px", background: `linear-gradient(120deg, ${C.panel}, ${C.ink})`,
      border: `1px solid ${C.proxy}66`, borderRadius: 14, padding: "16px 18px" }}>
      <span className="disp" style={{ fontSize: 17, color: C.proxy }}>◆ TOP 5 DO OBSERWACJI</span>
      <div style={{ fontSize: 12.5, color: C.steel, marginTop: 8 }}>
        Brak kandydatów na pozycji <b className="mono" style={{ color: C.steelHi }}>{sel.pos}</b> spełniających profil obserwacji (do {AGE_CAP} lat, do €{PRICE_CAP}M z wyceną). Poszerz kryteria w filtrach powyżej.
      </div>
    </div>
  );
  const gate = (f) => scored.filter((c) => c.skill >= f).sort((a, b) => b.value - a.value);
  let ranked = gate(62);
  if (ranked.length < 5) ranked = gate(52);
  if (ranked.length < 3) ranked = [...scored].sort((a, b) => b.value - a.value);
  const top = ranked.slice(0, 5);
  const maxV = Math.max(...top.map((c) => c.value)) || 1;
  const cohCol = (v) => (v > 70 ? C.good : v > 45 ? C.warn : C.bad);
  return (
    <div style={{ margin: "4px 0 20px", background: `linear-gradient(120deg, ${C.panel}, ${C.ink})`,
      border: `1px solid ${C.proxy}66`, borderRadius: 14, padding: "16px 18px" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
        <span className="disp" style={{ fontSize: 17, color: C.proxy }}>◆ TOP 5 DO OBSERWACJI</span>
        <span style={{ fontSize: 12, color: C.steel }}>kompromis jakość / cena na pozycji <b className="mono" style={{ color: C.steelHi }}>{sel.pos}</b> · profil: <b style={{ color: C.steelHi }}>do 25 lat, do €3M</b></span>
      </div>
      <div className="hscroll"><div style={{ display: "grid", gap: 7, minWidth: 600 }}>
        {top.map((c, i) => (
          <div key={c.p.id} style={{ display: "grid", gridTemplateColumns: "22px 1.5fr 0.7fr 0.8fr 0.9fr 1.1fr auto",
            gap: 12, alignItems: "center", background: C.panel, border: `1px solid ${C.line}`, borderRadius: 10, padding: "10px 13px" }}>
            <span className="disp" style={{ fontSize: 18, color: C.proxy, textAlign: "center" }}>{i + 1}</span>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {c.p.name && c.p.name !== "?" ? c.p.name : c.p.lg}
              </div>
              <div style={{ fontSize: 10.5, color: C.steel, marginTop: 1 }}>{c.p.lg} · {c.p.age} lat · do {c.p.contract}</div>
            </div>
            <div style={{ textAlign: "center" }}>
              <div className="disp" style={{ fontSize: 18, lineHeight: 0.9 }}>{c.m.level}</div>
              <div style={{ fontSize: 9, color: C.steel }}>poziom</div>
            </div>
            <div style={{ textAlign: "center" }}>
              <div className="mono" style={{ fontSize: 13, fontWeight: 700, color: cohCol(c.m.coherence) }}>{Math.round(c.m.coherence)}%</div>
              <div style={{ fontSize: 9, color: C.steel }}>koh.</div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div className="disp" style={{ fontSize: 16, color: C.proxy, lineHeight: 0.9 }}>{fmt(c.price.est)}</div>
              <div style={{ fontSize: 9, color: C.steel }}>cena</div>
            </div>
            <div title="Wskaźnik obserwacji = (0,45·poziom + 0,55·koherencja) / √cena">
              <div style={{ height: 6, background: C.panel2, borderRadius: 3, overflow: "hidden" }}>
                <div style={{ width: `${(c.value / maxV) * 100}%`, height: "100%", background: C.proxy }} />
              </div>
              <div style={{ fontSize: 9, color: C.steel, marginTop: 3 }}>wsk. obs.</div>
            </div>
            <button onClick={() => toggleShort(c.p)} title="Lista obserwowanych"
              style={{ background: short.includes(c.p.id) ? C.red : "transparent",
                color: short.includes(c.p.id) ? "#fff" : C.steel, border: `1px solid ${short.includes(c.p.id) ? C.red : C.line}`,
                borderRadius: 9, width: 34, height: 34, cursor: "pointer", fontSize: 15 }}>
              {short.includes(c.p.id) ? "★" : "☆"}
            </button>
          </div>
        ))}
      </div></div>
      <div style={{ fontSize: 10.5, color: C.steel, marginTop: 10 }}>
        Wskaźnik obserwacji = (0,45·poziom + 0,55·koherencja) / √cena — łączy jakość i dopasowanie stylu, karząc za cenę. To NIE to samo co „Okazja" (percentyl jakości minus percentyl ceny, w zakładce Okazje) ani „wycena" (wartość rynkowa). Podpowiedź do obserwacji, nie ostateczny ranking.
      </div>
    </div>
  );
}
// Twarz zawodnika: zdjęcie (Wikimedia) jeśli jest, w innym wypadku sylwetka.
function Face({ name, src, size = 44, ring = C.line }) {
  const [broken, setBroken] = useState(false);
  const show = src && !broken;
  return (
    <div style={{ width: size, height: size, borderRadius: 10, overflow: "hidden", flexShrink: 0,
      background: `linear-gradient(160deg, ${C.panelHi}, ${C.panel2})`, border: `1.5px solid ${ring}`,
      display: "flex", alignItems: "center", justifyContent: "center", position: "relative" }}>
      {show ? (
        <img src={src} alt={name || ""} onError={() => setBroken(true)}
          style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "top center" }} />
      ) : (
        <svg viewBox="0 0 24 24" width={size * 0.66} height={size * 0.66} aria-hidden="true"
          style={{ opacity: 0.42 }}>
          <circle cx="12" cy="8.2" r="3.9" fill={C.steelHi} />
          <path d="M4.2 20.5c0-4.3 3.5-6.8 7.8-6.8s7.8 2.5 7.8 6.8z" fill={C.steelHi} />
        </svg>
      )}
    </div>
  );
}
function SectionLabel({ children }) {
  // Odporność: children bywa tablicą węzłów (interpolacja `{...}`), a nie stringiem.
  const flat = Array.isArray(children) ? children : [children];
  const content = flat.every((c) => typeof c === "string")
    ? flat.join("").toUpperCase() : children;
  return (
    <div className="mono" style={{ fontSize: 11, letterSpacing: 2, color: C.red, fontWeight: 700,
      margin: "26px 0 12px", display: "flex", alignItems: "center", gap: 10 }}>
      {content}<span style={{ flex: 1, height: 1, background: C.line }} />
    </div>
  );
}

// ======================= MODUŁY DECYZYJNE =======================
// wspólny baner „dane pojawią się po odświeżeniu"
function InfoBanner({ children }) {
  return (
    <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 9,
      background: `${C.warn}14`, border: `1px solid ${C.warn}55`, borderRadius: 9,
      padding: "9px 13px", fontSize: 12.5, color: C.steelHi, maxWidth: 820 }}>
      <span style={{ color: C.warn, fontSize: 15, flexShrink: 0 }}>⚠</span>
      <span>{children}</span>
    </div>
  );
}
const sevColor = (s) => (s === "high" ? C.redHi : s === "med" ? C.warn : C.steel);

// ============================ PRIORYTETY TRANSFEROWE ============================
function PrioritiesView({ data, setSel, setView, fmt }) {
  const { rows, hasContract, hasAge } = useMemo(() => computePriorities(data), [data]);
  const jump = (squadId) => { const s = data.squad.find((x) => x.id === squadId); if (s) { setSel(s); setView("match"); } };
  const uColor = (u) => (u >= 30 ? C.redHi : u >= 15 ? C.warn : C.steel);
  const uLabel = (u) => (u >= 30 ? "pilne" : u >= 15 ? "warto" : "spokojnie");
  const urgent = rows.filter((r) => r.urgency >= 30).length;
  const fmtMv = (v) => (v > 0 ? fmt(v) : "—");

  return (
    <div>
      <Lead>Które pozycje najpilniej wzmocnić — z modelu: głębokość składu, poziom zawodników, braki danych{(hasContract || hasAge) ? ", wygasające kontrakty i wiek" : ""}. Pod każdą pozycją propozycje z puli. Klik „kandydaci" przenosi do Odpowiedników.</Lead>
      {!(hasContract && hasAge) && (
        <InfoBanner>
          Pełna pilność (wygasające kontrakty i wiek zawodników Rakowa) włączy się po najbliższym odświeżeniu — pipeline dołoży te pola do składu. Na razie liczymy z głębokości, poziomu i braków danych.
        </InfoBanner>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10, margin: "16px 0 18px" }}>
        <Kpi l="Pozycji pilnych" v={urgent} c={urgent > 0 ? C.redHi : C.good} />
        <Kpi l="Najpilniejsza" v={rows[0] ? rows[0].label : "—"} c={C.redHi} />
        <Kpi l="Analizowane pozycje" v={rows.length} />
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {rows.map((r) => (
          <div key={r.key} style={{ background: C.panel, border: `1px solid ${r.urgency >= 30 ? C.red : C.line}`,
            borderRadius: 14, padding: "16px 18px" }}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 14, flexWrap: "wrap" }}>
              <div style={{ minWidth: 0, flex: "1 1 220px" }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 9, flexWrap: "wrap" }}>
                  <span className="disp" style={{ fontSize: 20 }}>{r.label}</span>
                  <span className="mono" style={{ fontSize: 10.5, color: C.steel, letterSpacing: 1 }}>{r.line.toUpperCase()}</span>
                </div>
                <div style={{ fontSize: 12, color: C.steel, marginTop: 4 }}>
                  pewnych <b style={{ color: C.bone }}>{r.reliableDepth}</b>/{r.starters} miejsc
                  {r.estimatedDepth > 0 && <> · <span style={{ color: C.warn }}>b.d. {r.estimatedDepth}</span></>}
                  {r.bestRc != null && <> · najlepszy poziom <b style={{ color: C.bone }}>{r.bestRc}</b></>}
                </div>
              </div>
              <div style={{ textAlign: "right", flexShrink: 0 }}>
                <div className="disp" style={{ fontSize: 30, lineHeight: 0.9, color: uColor(r.urgency) }}>{r.urgency}</div>
                <div className="mono" style={{ fontSize: 9.5, letterSpacing: 1, color: uColor(r.urgency), textTransform: "uppercase" }}>{uLabel(r.urgency)}</div>
              </div>
            </div>

            {r.reasons.length > 0 && (
              <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginTop: 12 }}>
                {r.reasons.map((rs, i) => (
                  <span key={i} style={{ fontSize: 11.5, color: C.steelHi, background: `${sevColor(rs.sev)}14`,
                    border: `1px solid ${sevColor(rs.sev)}44`, borderRadius: 7, padding: "4px 10px" }}>
                    {rs.text}
                  </span>
                ))}
              </div>
            )}

            {r.targets.length > 0 && (
              <div style={{ marginTop: 14, borderTop: `1px solid ${C.line}`, paddingTop: 12 }}>
                <div className="mono" style={{ fontSize: 9.5, letterSpacing: 1, color: C.steel, textTransform: "uppercase", marginBottom: 8 }}>
                  Propozycje z puli
                </div>
                <div style={{ display: "grid", gap: 6 }}>
                  {r.targets.map((t) => (
                    <div key={t.id} style={{ display: "grid", gridTemplateColumns: "1.4fr 0.6fr 0.7fr auto", gap: 10,
                      alignItems: "center", fontSize: 12.5 }}>
                      <div style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        <b style={{ fontWeight: 600 }}>{t.name}</b>
                        <span style={{ color: C.steel }}> · {t.lg}{t.age ? ` · ${t.age} lat` : ""}</span>
                      </div>
                      <div><span className="disp" style={{ fontSize: 16 }}>{t.adj}</span><span style={{ fontSize: 9, color: C.steel }}> poz.</span></div>
                      <div style={{ color: t.mv > 0 ? C.proxy : C.steel }}>{fmtMv(t.mv)}</div>
                      <a href={tmUrl(t.name)} target="_blank" rel="noopener noreferrer"
                        style={{ fontSize: 10.5, color: C.steelHi, textDecoration: "none", whiteSpace: "nowrap" }}>TM ↗</a>
                    </div>
                  ))}
                </div>
                {r.members.length > 0 && (
                  <button onClick={() => jump(r.members[0].id)}
                    style={{ marginTop: 12, background: "transparent", color: C.redHi, border: `1px solid ${C.red}66`,
                      borderRadius: 8, padding: "7px 13px", fontSize: 12, cursor: "pointer", fontWeight: 600 }}>
                    Wszyscy kandydaci na tę pozycję →
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <Note>Pilność 0-100 = ważona suma: braki obsady (40%), luka jakości względem progu poziomu 55 (25%), brak danych/b.d. (20%), ryzyko kontraktu i wieku (15%). Propozycje: zawodnicy z puli na tej pozycji, do 27 lat, wg skorygowanego poziomu (surowy + handicap ligi). Model potrzeb oparty na formacji 3-4-3.</Note>
    </div>
  );
}

// ============================ OKAZJE / JAKOŚĆ ZA EURO ============================
function OkazjeView({ data, fmt, short, toggleShort, setSel, setView }) {
  const [tab, setTab] = useState("okazje");     // okazje | expiring
  const [posF, setPosF] = useState("all");
  const [minLevel, setMinLevel] = useState(55);
  const [maxAge, setMaxAge] = useState(45);
  const okazje = useMemo(() => computeOkazje(data, { minLevel }), [data, minLevel]);
  const expiring = useMemo(() => computeExpiring(data, { minLevel }), [data, minLevel]);
  const positions = useMemo(() => [...new Set(data.pool.map((p) => p.pos))].filter(Boolean).sort(), [data]);
  const base = tab === "okazje" ? okazje : expiring;
  const rows = base.filter((r) => (posF === "all" || r.pos === posF) && (!r.age || r.age <= maxAge)).slice(0, 60);
  const oColor = (o) => (o >= 40 ? C.good : o >= 15 ? C.proxy : o >= -15 ? C.steelHi : C.bad);
  const chip = (on) => ({ background: on ? C.red : "transparent", color: on ? "#fff" : C.steel,
    border: `1px solid ${on ? C.red : C.line}`, borderRadius: 7, padding: "5px 11px", fontSize: 12, cursor: "pointer", fontWeight: 600 });

  return (
    <div>
      <Lead>Zawodnicy, których model ceni wyżej, niż wskazywałaby ich cena. „Okazja" = percentyl jakości minus percentyl ceny w obrębie pozycji. Zakładka „Wygasające" to potencjalnie tani lub wolni zawodnicy w ostatnim roku kontraktu.</Lead>
      <div className="mono" style={{ marginTop: 8, fontSize: 10.5, color: C.steel, lineHeight: 1.5, maxWidth: 720 }}>
        Wartości i kontrakty to snapshot (zrzut Kaggle + oficjalne wartości Scoutastic), a nie dane pobierane na żywo — mogą odbiegać od aktualnego Transfermarktu. Link „Transfermarkt ↗" prowadzi do wersji live.
      </div>

      <div style={{ display: "flex", gap: 6, margin: "16px 0 14px", flexWrap: "wrap" }}>
        {[["okazje", "Jakość za euro"], ["expiring", "Wygasające kontrakty"]].map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} style={{ background: tab === k ? C.panelHi : "transparent",
            color: tab === k ? C.bone : C.steel, border: `1px solid ${tab === k ? C.redHi : C.line}`,
            padding: "8px 15px", borderRadius: 9, cursor: "pointer", fontSize: 13, fontWeight: 600 }}>{l}</button>
        ))}
      </div>

      <div style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 12, padding: "14px 16px", marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
          <span className="mono" style={{ fontSize: 10, letterSpacing: 1, color: C.steel, textTransform: "uppercase", marginRight: 4 }}>Pozycja</span>
          <button onClick={() => setPosF("all")} style={chip(posF === "all")}>wszystkie</button>
          {positions.map((p) => <button key={p} onClick={() => setPosF(p)} style={chip(posF === p)}>{p}</button>)}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 16 }}>
          <div>
            <FLabel>Min. poziom: <b style={{ color: C.bone }}>{minLevel}</b></FLabel>
            <input type="range" min={0} max={90} value={minLevel} onChange={(e) => setMinLevel(+e.target.value)} style={{ width: "100%", accentColor: C.red }} />
          </div>
          <div>
            <FLabel>Maks. wiek: <b style={{ color: C.bone }}>{maxAge >= 45 ? "bez limitu" : `${maxAge} lat`}</b></FLabel>
            <input type="range" min={17} max={45} value={maxAge} onChange={(e) => setMaxAge(+e.target.value)} style={{ width: "100%", accentColor: C.red }} />
          </div>
        </div>
      </div>

      <div className="mono" style={{ fontSize: 11, color: C.steel, marginBottom: 10 }}>
        {rows.length}{base.length > rows.length ? ` z ${base.length}` : ""} zawodnik(ów)
      </div>

      {rows.length === 0 && <Empty>Brak zawodników spełniających filtry. Obniż „min. poziom" albo zmień pozycję.</Empty>}

      <div className="hscroll"><div style={{ display: "grid", gap: 9, minWidth: 640 }}>
        {rows.map((r) => (
          <div key={r.id} className="rowh" style={{ background: C.panel, border: `1px solid ${C.line}`,
            borderRadius: 12, padding: "14px 18px", display: "grid",
            gridTemplateColumns: "1.5fr 0.7fr 0.9fr 1fr auto", gap: 14, alignItems: "center" }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 13.5, fontWeight: 600 }}>{r.name}</div>
              <div style={{ fontSize: 11, color: C.steel, marginTop: 2 }}>
                {r.lg} · {r.pos}{r.age ? ` · ${r.age} lat` : ""} · do {r.contract || "?"}
                {r.expiring && <span style={{ color: C.warn }}> · wygasa</span>}
                {r.free && <span style={{ color: C.good }}> · wolny</span>}
              </div>
              <a href={tmUrl(r.name)} target="_blank" rel="noopener noreferrer"
                style={{ fontSize: 10.5, color: C.steelHi, textDecoration: "none", marginTop: 3, display: "inline-block" }}>Transfermarkt ↗</a>
            </div>
            <div>
              <div className="disp" style={{ fontSize: 24, lineHeight: 0.9 }}>{r.adj}</div>
              <div style={{ fontSize: 10, color: C.steel }}>poziom</div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div className="disp" style={{ fontSize: 19, color: C.proxy, lineHeight: 0.9 }}>{r.mv > 0 ? fmt(r.mv) : "—"}</div>
              <div style={{ fontSize: 10, color: C.steel }}>wartość</div>
            </div>
            {tab === "okazje" ? (
              <div>
                <div style={{ fontSize: 11, color: C.steel, marginBottom: 4 }}>okazja</div>
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <div style={{ flex: 1, height: 6, background: C.panel2, borderRadius: 3, overflow: "hidden" }}>
                    <div style={{ width: `${Math.max(0, r.okazja)}%`, height: "100%", background: oColor(r.okazja) }} />
                  </div>
                  <span className="mono" style={{ fontSize: 12, fontWeight: 700, color: oColor(r.okazja) }}>
                    {r.okazja > 0 ? "+" : ""}{r.okazja}
                  </span>
                </div>
              </div>
            ) : (
              <div style={{ textAlign: "center" }}>
                <div className="disp" style={{ fontSize: 17, color: r.free ? C.good : C.warn }}>{r.contract}</div>
                <div style={{ fontSize: 10, color: C.steel }}>{r.free ? "wolny" : "ost. rok"}</div>
              </div>
            )}
            <button onClick={() => toggleShort(r)} title="Lista obserwowanych"
              style={{ background: short.includes(r.id) ? C.red : "transparent",
                color: short.includes(r.id) ? "#fff" : C.steel, border: `1px solid ${short.includes(r.id) ? C.red : C.line}`,
                borderRadius: 9, width: 38, height: 38, cursor: "pointer", fontSize: 17 }}>
              {short.includes(r.id) ? "★" : "☆"}
            </button>
          </div>
        ))}
      </div></div>

      <Note>{tab === "okazje"
        ? "Okazja (−100…+100) = percentyl skorygowanego poziomu minus percentyl wartości rynkowej, liczony w obrębie pozycji. Dodatni = zawodnik gra powyżej swojej ceny. Bardzo niska cena przy wysokim poziomie bywa też sygnałem małej próbki — zweryfikuj minuty."
        : "Wygasające = kontrakt kończy się w tym lub przyszłym roku (potencjalnie tani lub wolny transfer). Sortowane po skorygowanym poziomie. Wolny = umowa do bieżącego roku."}</Note>
    </div>
  );
}

// ============================ CZERWONE FLAGI (dla trenera) ============================
function FlagsView({ data, setSel, setView }) {
  const { players, counts, hasAge, hasContract } = useMemo(() => computeRedFlags(data), [data]);
  const jump = (squadId) => { const s = data.squad.find((x) => x.id === squadId); if (s) { setSel(s); setView("match"); } };
  const FLAG_META = {
    contract: { label: "Kontrakt" }, age: { label: "Wiek" }, level: { label: "Poziom" },
    nodata: { label: "Brak danych" }, valuedrop: { label: "Wartość" },
  };
  const KPIS = [["contract", C.redHi], ["age", C.warn], ["level", C.warn], ["nodata", C.steel], ["valuedrop", C.proxy]];

  return (
    <div>
      <Lead>Zawodnicy Rakowa, których warto mieć na oku — pogrupowani wg ryzyka. Dla trenera i dyrektora sportowego: gdzie planować następcę, z kim rozmawiać o kontrakcie, czyją formę monitorować. Klik zawodnika przenosi do jego odpowiedników w Europie.</Lead>
      {!(hasAge || hasContract) && (
        <InfoBanner>
          Flagi wieku, kontraktu i spadku wartości włączą się po najbliższym odświeżeniu — pipeline dołoży wiek/kontrakt/wartość do składu. Na razie widać flagi z modelu (poziom i braki danych).
        </InfoBanner>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 10, margin: "16px 0 18px" }}>
        {KPIS.map(([k, c]) => (
          <Kpi key={k} l={FLAG_META[k].label} v={counts[k] || 0} c={(counts[k] || 0) > 0 ? c : C.steel} />
        ))}
      </div>

      {players.length === 0 && <Empty>Brak czerwonych flag w składzie — albo dane składu nie są jeszcze wzbogacone.</Empty>}

      <div style={{ display: "grid", gap: 9 }}>
        {players.map((p) => (
          <div key={p.id} className="rowh" style={{ background: C.panel,
            border: `1px solid ${p.score >= 6 ? C.red : p.score >= 3 ? `${C.warn}66` : C.line}`,
            borderRadius: 12, padding: "14px 18px" }}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 14, flexWrap: "wrap" }}>
              <div style={{ minWidth: 0, flex: "1 1 200px" }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 14, fontWeight: 600 }}>{p.name}</span>
                  <span className="mono" style={{ fontSize: 10.5, color: C.redHi, fontWeight: 700 }}>{p.pos}</span>
                  {p.rc_estimated
                    ? <span className="mono" style={{ fontSize: 11, color: C.warn }}>b.d.</span>
                    : <span className="mono" style={{ fontSize: 11, color: C.steel }}>poziom {p.rc}</span>}
                  {p.age && <span style={{ fontSize: 11, color: C.steel }}>· {p.age} lat</span>}
                  {p.contract && <span style={{ fontSize: 11, color: C.steel }}>· do {p.contract}</span>}
                </div>
                <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginTop: 9 }}>
                  {p.flags.map((f, i) => (
                    <span key={i} title={f.detail} style={{ fontSize: 11.5, color: C.bone, background: `${sevColor(f.sev)}18`,
                      border: `1px solid ${sevColor(f.sev)}55`, borderRadius: 7, padding: "4px 10px", cursor: "help" }}>
                      <b style={{ color: sevColor(f.sev) }}>{f.label}</b>
                      <span style={{ color: C.steelHi }}> — {f.detail}</span>
                    </span>
                  ))}
                </div>
              </div>
              <button onClick={() => jump(p.id)}
                style={{ flexShrink: 0, background: "transparent", color: C.redHi, border: `1px solid ${C.red}66`,
                  borderRadius: 8, padding: "7px 13px", fontSize: 12, cursor: "pointer", fontWeight: 600, whiteSpace: "nowrap" }}>
                Znajdź następcę →
              </button>
            </div>
          </div>
        ))}
      </div>

      <Note>Flagi: wygasający kontrakt (do 1 rok), wiek schyłkowy (bramka 34+, obrona 31+, pomoc/atak 30+), poziom &gt;8 pkt poniżej mediany swojej linii, brak danych meczowych (b.d.), spadek wartości poniżej 60% szczytu. To migawka bieżącego ryzyka — śledzenie zmian w czasie dołożymy, gdy pipeline zacznie zapisywać historię odświeżeń.</Note>
    </div>
  );
}

// ============================ OSTATNIE MECZE (WALIDATOR) ============================
const RES_COLOR = { W: C.good, D: C.proxy, L: C.bad };
// Herb klubu z Transfermarktu po id (id = externalId ze Scoutastic = TM). Jeśli się
// nie załaduje (hotlink/404), obrazek chowamy w onError i zostaje sama nazwa.
const crestUrl = (id) => (id ? `https://tmssl.akamaized.net/images/wappen/head/${id}.png` : null);
function Crest({ id, size = 18 }) {
  if (!id) return null;
  return (
    <img src={crestUrl(id)} alt="" width={size} height={size} loading="lazy"
      onError={(e) => { e.currentTarget.style.display = "none"; }}
      style={{ objectFit: "contain", flexShrink: 0, verticalAlign: "middle" }} />
  );
}
const VERDICT_META = {
  ok:      { label: "zgodne", c: C.good },
  watch:   { label: "obserwuj", c: C.warn },
  trusted: { label: "wybór trenera", c: C.blueHi },
  neutral: { label: "—", c: C.steel },
};
const ROLE_META = {
  filar:   { label: "filar", c: C.redHi },
  rotacja: { label: "rotacja", c: C.proxy },
  rezerwa: { label: "rezerwa", c: C.steel },
};

function RecentView({ data, setSel, setView }) {
  const V = useMemo(() => computeRecentValidation(data), [data]);
  const jump = (id) => { const s = data.squad.find((x) => x.id === id); if (s) { setSel(s); setView("match"); } };

  if (!V.available) {
    const seasons = (V.seasonsUsed || []).map((s) => s.season_id).join(", ");
    return (
      <div>
        <Lead>Ostatnie mecze Rakowa jako walidator modelu: zestawiamy <b>minuty</b> (kogo trener realnie wystawia) i <b>realny output</b> z naszym RC, i wskazujemy rozjazdy — kandydatów do rotacji oraz punkty do obserwacji.</Lead>
        {V.provisional ? (
          <>
            <div style={{ marginTop: 14, display: "flex", alignItems: "flex-start", gap: 10,
              background: `${C.red}14`, border: `1px solid ${C.red}66`, borderRadius: 10, padding: "12px 15px",
              fontSize: 13, color: C.steelHi, lineHeight: 1.55, maxWidth: 860 }}>
              <span style={{ color: C.redHi, fontSize: 16, flexShrink: 0 }}>■</span>
              <span>
                <b style={{ color: C.bone }}>Walidacja wstrzymana — feed StatsBomb nowego sezonu jest niespójny.</b> Wykryliśmy wpisy niemożliwe dla realnego terminarza (dwa mecze Rakowa tego samego dnia, wyniki/mecze, których nie było{seasons ? `; sezon(y): ${seasons}` : ""}). Świadomie <b>nie pokazujemy</b> tych meczów ani rekomendacji, żeby nie walidować modelu na zmyślonych danych.
                <br /><br />
                Gdy StatsBomb zbierze poprawnie bieżący sezon, ekran zadziała automatycznie. Można też wskazać właściwy sezon ręcznie: <span className="mono">RECENT_SEASON_ID=&lt;id&gt;</span> (a <span className="mono">RECENT_DEBUG=1</span> wypisze w logu listę sezonów i surowe mecze do zidentyfikowania poprawnego id).
              </span>
            </div>
          </>
        ) : (
          <>
            <InfoBanner>
              Dane meczowe pojawią się po najbliższym odświeżeniu pipeline'u (moduł „ostatnie mecze" pobiera je ze StatsBomb — <span className="mono">RECENT_MATCHES</span>). Jeśli endpoint meczowy nie jest dostępny na koncie, ten ekran pozostaje pusty, a reszta aplikacji działa bez zmian.
            </InfoBanner>
            <div style={{ marginTop: 16 }}>
              <Empty>Brak pobranych meczów{V.reason ? ` (${V.reason})` : ""}. Uruchom odświeżenie danych, żeby zasilić walidację.</Empty>
            </div>
          </>
        )}
      </div>
    );
  }

  const t = V.team || {};
  const form = (t.form || "").split("");
  const { rotate, observe } = V.recommendations;

  return (
    <div>
      <Lead>Ostatnie <b className="mono" style={{ color: C.redHi }}>{V.nMatches}</b> meczów Rakowa jako walidator. <b>Minuty</b> to ujawniona preferencja trenera — kto realnie gra. Zestawiamy je z RC i realnym outputem, żeby wyłapać rozjazdy: wysoki RC bez minut (do obserwacji), zaufanie trenera mimo niskiego RC (model może niedoszacowywać), oraz pełne obciążenie (do rotacji). Klik zawodnika → jego odpowiednicy w Europie.</Lead>

      {V.stale && (
        <InfoBanner>
          Uwaga: najświeższy zebrany mecz to <b>{V.newestDate}</b>{V.daysSince != null ? ` (${V.daysSince} dni temu)` : ""} — to końcówka poprzedniego sezonu. StatsBomb nie zebrał jeszcze meczów nowego sezonu, więc walidacja pokazuje ostatnie dostępne spotkania i będzie niemiarodajna dla bieżącej formy, dopóki nie pojawią się dane nowego sezonu. Odśwież po pierwszych kolejkach.
        </InfoBanner>
      )}
      {!V.stale && V.smallSample && (
        <InfoBanner>
          Nowy sezon ma dopiero <b>{V.nMatches}</b> {V.nMatches === 1 ? "mecz" : "mecze"} — próba jest mała. Minuty (kto gra) są już czytelne, ale output i formę traktuj ostrożnie; pełniejszy obraz po kilku kolejkach.
        </InfoBanner>
      )}

      {/* Podsumowanie drużyny */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 10, margin: "16px 0 14px" }}>
        <div style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 11, padding: "12px 15px" }}>
          <div className="mono" style={{ fontSize: 9.5, color: C.steel, letterSpacing: 1, textTransform: "uppercase" }}>Forma</div>
          <div className="disp" style={{ fontSize: 22, marginTop: 4, display: "flex", gap: 5 }}>
            {form.length ? form.map((r, i) => (
              <span key={i} style={{ color: RES_COLOR[r] || C.steel, width: 20, height: 20, lineHeight: "20px",
                textAlign: "center", fontSize: 13, fontWeight: 800, borderRadius: 5, background: `${RES_COLOR[r] || C.steel}1e` }}>{r}</span>
            )) : <span style={{ color: C.steel }}>—</span>}
          </div>
        </div>
        <Kpi l="Punkty" v={`${t.points ?? 0} / ${V.nMatches * 3}`} />
        <Kpi l="Pkt / mecz" v={t.ppg ?? 0} c={t.ppg >= 2 ? C.good : t.ppg >= 1.3 ? C.proxy : C.bad} />
        <Kpi l="Bilans bramek" v={`${t.gf ?? 0}:${t.ga ?? 0}`} c={(t.gf ?? 0) >= (t.ga ?? 0) ? C.good : C.bad} />
      </div>

      {/* Pasek meczów */}
      <div className="hscroll" style={{ display: "flex", gap: 8, marginBottom: 6 }}>
        {V.matches.map((m, i) => (
          <div key={i} style={{ flex: "0 0 auto", background: C.panel, border: `1px solid ${C.line}`,
            borderLeft: `3px solid ${RES_COLOR[m.result] || C.line}`, borderRadius: 9, padding: "8px 12px", minWidth: 120 }}>
            <div className="mono" style={{ fontSize: 10, color: C.steel }}>{m.home ? "dom" : "wyjazd"} · {m.date || ""}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, margin: "2px 0" }}>
              <Crest id={m.opp_id} size={18} />
              <span style={{ fontSize: 13, fontWeight: 600, color: C.bone, whiteSpace: "nowrap" }}>{m.opponent || "—"}</span>
            </div>
            <div className="mono" style={{ fontSize: 12, color: RES_COLOR[m.result] || C.steel, fontWeight: 700 }}>
              {m.result || "?"} {m.gf != null ? `${m.gf}:${m.ga}` : ""}
            </div>
          </div>
        ))}
      </div>

      {/* Rekomendacje */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(300px,1fr))", gap: 14, marginTop: 20 }}>
        <div>
          <SectionLabel>Do rotacji · obciążenie</SectionLabel>
          {rotate.length === 0
            ? <Empty>Nikt nie gra kompletu minut we wszystkich meczach — obciążenie rozłożone.</Empty>
            : <div style={{ display: "grid", gap: 8 }}>
                {rotate.map((r, i) => (
                  <div key={i} style={{ background: C.panel, border: `1px solid ${sevColor(r.sev)}55`, borderRadius: 10, padding: "10px 13px" }}>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                      <b style={{ fontSize: 13.5, color: C.bone }}>{r.name}</b>
                      <span className="mono" style={{ fontSize: 10.5, color: C.redHi, fontWeight: 700 }}>{r.pos}</span>
                    </div>
                    <div style={{ fontSize: 12, color: C.steelHi, marginTop: 4, lineHeight: 1.5 }}>{r.reason}</div>
                  </div>
                ))}
              </div>}
        </div>
        <div>
          <SectionLabel>Punkty do obserwacji</SectionLabel>
          {observe.length === 0
            ? <Empty>Model i wybory trenera są zgodne — brak wyraźnych rozjazdów do obserwacji.</Empty>
            : <div style={{ display: "grid", gap: 8 }}>
                {observe.map((o, i) => (
                  <div key={i} style={{ background: C.panel, border: `1px solid ${sevColor(o.sev)}55`, borderRadius: 10, padding: "10px 13px" }}>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                      <b style={{ fontSize: 13.5, color: C.bone }}>{o.name}</b>
                      <span className="mono" style={{ fontSize: 10.5, color: C.redHi, fontWeight: 700 }}>{o.pos}</span>
                      {o.rc != null && <span className="mono" style={{ fontSize: 10.5, color: C.steel }}>RC {o.rc}</span>}
                    </div>
                    <div style={{ fontSize: 12, color: C.steelHi, marginTop: 4, lineHeight: 1.5 }}>{o.reason}</div>
                  </div>
                ))}
              </div>}
        </div>
      </div>

      {/* Tabela zawodników: minuty vs RC */}
      <SectionLabel>Zawodnicy · minuty vs RC</SectionLabel>
      <div style={{ display: "grid", gap: 7 }}>
        {V.players.map((p) => {
          const vm = VERDICT_META[p.verdict] || VERDICT_META.neutral;
          const rm = ROLE_META[p.role] || ROLE_META.rezerwa;
          const pct = Math.round(Math.min(1, p.share) * 100);
          return (
            <div key={p.id || p.name} className="rowh" style={{ background: C.panel,
              border: `1px solid ${p.verdict === "watch" ? `${C.warn}66` : p.verdict === "trusted" ? `${C.blueHi}55` : C.line}`,
              borderRadius: 11, padding: "12px 15px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
                <div style={{ minWidth: 0, flex: "1 1 210px" }}>
                  <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 14, fontWeight: 600, color: C.bone }}>{p.name}</span>
                    {p.pos && <span className="mono" style={{ fontSize: 10.5, color: C.redHi, fontWeight: 700 }}>{p.pos}</span>}
                    {p.rcEstimated
                      ? <span className="mono" style={{ fontSize: 11, color: C.warn }}>b.d.</span>
                      : <span className="mono" style={{ fontSize: 11, color: C.steel }}>RC {p.rc}</span>}
                    <span className="mono" style={{ fontSize: 10, color: rm.c, border: `1px solid ${rm.c}55`, borderRadius: 5, padding: "1px 6px" }}>{rm.label}</span>
                    <span className="mono" style={{ fontSize: 10, color: vm.c, background: `${vm.c}18`, borderRadius: 5, padding: "1px 6px" }}>{vm.label}</span>
                  </div>
                  {/* pasek udziału minut */}
                  <div style={{ display: "flex", alignItems: "center", gap: 9, marginTop: 8 }}>
                    <div style={{ flex: "1 1 120px", maxWidth: 200, height: 6, background: C.ink, borderRadius: 4, overflow: "hidden" }}>
                      <div style={{ width: `${pct}%`, height: "100%", background: rm.c, borderRadius: 4 }} />
                    </div>
                    <span className="mono" style={{ fontSize: 10.5, color: C.steel, whiteSpace: "nowrap" }}>
                      {p.minutes}′ · {pct}% · {p.starts}/{V.nMatches} w wyjściowym
                    </span>
                  </div>
                  {p.signals.length > 0 && (
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                      {p.signals.map((s, i) => (
                        <span key={i} style={{ fontSize: 11.5, color: C.steelHi, background: `${s.sev === "ok" ? C.good : s.sev === "med" ? C.warn : C.steel}15`,
                          border: `1px solid ${s.sev === "ok" ? C.good : s.sev === "med" ? C.warn : C.steel}44`, borderRadius: 7, padding: "3px 9px" }}>{s.text}</span>
                      ))}
                    </div>
                  )}
                </div>
                {p.inSquad && p.id && (
                  <button onClick={() => jump(p.id)}
                    style={{ flexShrink: 0, background: "transparent", color: C.redHi, border: `1px solid ${C.red}66`,
                      borderRadius: 8, padding: "7px 13px", fontSize: 12, cursor: "pointer", fontWeight: 600, whiteSpace: "nowrap" }}>
                    Odpowiednicy →
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <Note>Źródło danych meczowych: <b>{V.source === "scoutastic" ? "Scoutastic / Transfermarkt" : "StatsBomb"}</b>{V.source === "scoutastic" ? " (minuty, gole, asysty — bez xG/xA)" : ""}; RC i koherencja liczone ze StatsBomb. Walidator opiera się na tym, co odporne: <b>minuty</b> (ujawniona preferencja trenera) i <b>realny output</b> (miękko, bo próba {V.nMatches} meczów jest mała — traktujemy jako sygnał, nie wyrok). <b>Koherencji ten ekran nie waliduje wprost</b> — koherencja to podobieństwo stylu między zawodnikami, nie wielkość meczowa; walidujemy ją pośrednio przez to, że XI realnie wystawiane przez trenera to zestaw opisywany przez ekran „Zależności formacji". Output ofensywny komentujemy dopiero od ~180 minut.</Note>
    </div>
  );
}
