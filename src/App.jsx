import React, { useState, useEffect, useMemo } from "react";

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
  { id: "LCB", label: "CB",  line: "Obrona", pos: ["CB"],        x: 27, y: 70 },
  { id: "CCB", label: "CB",  line: "Obrona", pos: ["CB"],        x: 50, y: 73 },
  { id: "RCB", label: "CB",  line: "Obrona", pos: ["CB"],        x: 73, y: 70 },
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
  const [short, setShort] = useState([]);
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
  const [filtersOpen, setFiltersOpen] = useState(false);
  const setF = (patch) => setDraft((f) => ({ ...f, ...patch }));
  const applyFilters = () => setFilters(draft);
  const resetFilters = () => { setDraft(FILTERS_DEFAULT); setFilters(FILTERS_DEFAULT); };
  const filtersDirty = JSON.stringify(draft) !== JSON.stringify(filters);
  const toggleShort = (id) => setShort((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id]);

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
  const estimatePrice = (player, p) => {
    const { adj } = adjusted(p);
    const base = Number(p.mv) || 0;
    const rc = Number(player.rc) || 0;
    const levelF = 1 + Math.max(-0.3, (adj - rc) * 0.04);
    const ageF = p.age <= 23 ? 1.25 : p.age <= 26 ? 1.05 : p.age <= 29 ? 0.85 : 0.65;
    const yearsLeft = Math.max(0, (p.contract || 2026) - 2026);
    const contractF = yearsLeft >= 3 ? 1.2 : yearsLeft === 2 ? 1.0 : yearsLeft === 1 ? 0.75 : 0.5;
    const ligF = { "Championship (EN)": 1.3, "Eredivisie (NL)": 1.15, "Liga Portugalska": 1.2,
      "Liga Belgijska": 1.1, "2. Bundesliga (DE)": 1.05, "Superliga (DK)": 0.95 }[p.lg] || 1;
    const est = base * levelF * ageF * contractF * ligF;
    return { est, lo: est * 0.8, hi: est * 1.25 };
  };

  const candidates = useMemo(() => {
    if (!data || !sel) return [];
    let rows = data.pool.map((p) => ({ p, m: matchScore(sel, p) }))
      .filter((x) => x.m).map((x) => ({ ...x, price: estimatePrice(sel, x.p) }));
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
    const s = { fit: (a, b) => b.m.coherence - a.m.coherence,
      coherence: (a, b) => b.m.coherence - a.m.coherence,
      price: (a, b) => a.price.est - b.price.est,
      price_desc: (a, b) => b.price.est - a.price.est,
      level: (a, b) => b.m.level - a.m.level };
    return rows.sort(s[sortBy] || s.coherence);
  }, [data, sel, sortBy, filters]);

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
  // Nawigacja jak na rakow.com: 4 sekcje w górnym pasku, szczegóły w „pigułkach".
  const SECTIONS = [
    { id: "kadra",    label: "Kadra",    views: [["twin", "Skład"]] },
    { id: "skauting", label: "Skauting", views: [["match", "Odpowiednicy"], ["search", "Szukaj"]] },
    { id: "taktyka",  label: "Taktyka",  views: [["shadow", "Drużyna cieni"], ["corr", "Zależności"]] },
    { id: "model",    label: "Model",    views: [["leagues", "Handicapy lig"], ["help", "Jak to działa"]] },
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
      `}</style>

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
            {view === "match" && "Odpowiednicy z Europy"}
            {view === "leagues" && "Handicapy lig"}
            {view === "corr" && "Zależności formacji"}
            {view === "shadow" && "Drużyna cieni · 3-4-3"}
            {view === "search" && "Wyszukiwarka zawodników"}
            {view === "help" && "Jak korzystać"}
          </h1>
          <div style={{ display: "flex", gap: 22, marginTop: 14, flexWrap: "wrap" }}>
            <Stat n={data.squad.length} l="zawodników" />
            <Stat n={realCount} l="realnych profili" accent />
            <Stat n={data.leagues.length - 1} l="lig w puli" />
            <Stat n={data.pool.length} l="kandydatów" />
          </div>
        </div>

        {err && <div style={{ margin: "16px 34px 0", fontSize: 12.5, color: C.warn }}>{err}</div>}

        <div className="content" style={{ padding: "26px 34px 0", maxWidth: 1180, margin: "0 auto" }}>
          {view === "twin" && <TwinView data={data} photoOf={photoOf} sel={sel} setSel={setSel} setView={setView} />}
          {view === "match" && <MatchView {...{ data, sel, setSel, candidates, sortBy, setSortBy,
            short, toggleShort, shortRows, adjusted, fmt, median,
            filters: draft, applied: filters, setF, applyFilters, resetFilters, filtersDirty,
            FILTERS_DEFAULT, filtersOpen, setFiltersOpen }} />}
          {view === "search" && <SearchView {...{ data, query, setQuery, searchResults, short, toggleShort, fmt }} />}
          {view === "shadow" && <ShadowView {...{ data, photoOf, fmt, estimatePrice, setSel, setView }} />}
          {view === "leagues" && <LeaguesView data={data} />}
          {view === "corr" && <CorrView data={data} />}
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
                    <div><span className="cond" style={{ fontSize: 11.5, fontWeight: 800, color: "#fff",
                      background: C.red, borderRadius: 4, padding: "1px 7px" }}>{p.pos}</span></div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                      <Face name={p.name} src={photoOf(p.name)} size={32} ring={tc} />
                      <span style={{ fontWeight: 600, fontSize: 13.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{p.name}</span>
                    </div>
                    <div style={{ textAlign: "center" }}>
                      {est ? <span className="mono" title="Brak dostatecznych danych — zawodnik nie ma wystarczającej próbki meczowej, więc poziomu nie da się policzyć."
                        style={{ fontSize: 11, color: C.warn, fontWeight: 700, cursor: "help" }}>b.d.</span>
                        : <span className="disp" style={{ fontSize: 22, color: tc }}>{p.rc}</span>}
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

function MatchView({ data, sel, setSel, candidates, sortBy, setSortBy, short, toggleShort, shortRows, adjusted, fmt, median,
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
      <div style={{ display: "flex", gap: 10, margin: "18px 0", flexWrap: "wrap", alignItems: "center" }}>
        <select value={sel.id} onChange={(e) => setSel(data.squad.find((p) => p.id === e.target.value))}
          style={{ background: C.panel, color: C.bone, border: `1px solid ${C.line}`, borderRadius: 9,
            padding: "10px 13px", fontSize: 13, fontWeight: 600 }}>
          {data.squad.map((p) => <option key={p.id} value={p.id}>{p.pos} — {p.name}</option>)}
        </select>
        <div style={{ display: "flex", gap: 5, marginLeft: "auto", alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: 11, color: C.steel }}>sortuj</span>
          {[["coherence", "koherencja"], ["level", "poziom"]].map(([k, l]) => (
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
        {candidates.map(({ p, m, price }) => {
          const a = adjusted(p);
          const open = openCmp === p.id;
          return (
           <div key={p.id} style={{ background: C.panel, border: `1px solid ${open ? `${C.redHi}88` : C.line}`,
             borderRadius: 12, overflow: "hidden" }}>
            <div className="rowh" style={{ padding: "15px 18px", display: "grid",
              gridTemplateColumns: "1.5fr 0.9fr 1fr 1fr auto", gap: 16, alignItems: "center" }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13.5, fontWeight: 600 }}>{p.name && p.name !== "?" ? p.name : p.lg}</div>
                <div style={{ fontSize: 11, color: C.steel, marginTop: 2 }}>{p.lg} · {p.pos} · {p.age} lat · do {p.contract}</div>
                {p.name && p.name !== "?" && (
                  <a href={tmUrl(p.name)} target="_blank" rel="noopener noreferrer"
                    style={{ fontSize: 10.5, color: C.steelHi, textDecoration: "none", marginTop: 3, display: "inline-block" }}>
                    Transfermarkt ↗
                  </a>
                )}
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
                <button onClick={() => toggleShort(p.id)} title="Lista obserwowanych"
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
                <button onClick={() => toggleShort(p.id)} title="Lista obserwowanych"
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

function ShadowView({ data, photoOf = () => null, fmt, estimatePrice, setSel, setView }) {
  const squad = data.squad, pool = data.pool;
  const [lineup, setLineup] = useState({});   // slotId -> playerId (ręczny wybór)
  const cohColor = (v) => (v > 70 ? C.good : v > 45 ? C.warn : C.bad);
  const surname = (nm) => { const t = String(nm || "").trim().split(" "); return t[t.length - 1]; };

  const xi = useMemo(() => {
    const used = new Set();
    const byRc = (a, b) => (a.rc_estimated ? 1 : 0) - (b.rc_estimated ? 1 : 0) || (b.rc - a.rc);
    const chosen = {};
    for (const slot of FORMATION_343) {
      const p = lineup[slot.id] && squad.find((s) => s.id === lineup[slot.id]);
      if (p && !used.has(p.id)) { chosen[slot.id] = p; used.add(p.id); }
    }
    const pickAuto = (slot) => {
      const free = squad.filter((p) => !used.has(p.id));
      for (const pos of slot.pos) { const c = free.filter((p) => p.pos === pos).sort(byRc); if (c.length) return c[0]; }
      return free.filter((p) => (p.line || lineOfPos(p.pos)) === slot.line).sort(byRc)[0] || null;
    };
    const usedShadows = new Set();
    return FORMATION_343.map((slot) => {
      let starter = chosen[slot.id];
      if (!starter) { starter = pickAuto(slot); if (starter) used.add(starter.id); }
      let shadow = null;
      if (starter) {
        const same = pool.filter((p) => p.pos === starter.pos && typeof p.coherence === "number" && !usedShadows.has(p.id));
        const pref = same.filter((p) => p.coherence_ref === starter.name);
        const list = (pref.length ? pref : same).sort((a, b) => b.coherence - a.coherence);
        shadow = list[0] || null; if (shadow) usedShadows.add(shadow.id);
      }
      const price = starter && shadow ? estimatePrice(starter, shadow) : null;
      return { slot, starter, shadow, price };
    });
  }, [data, lineup]);

  const filled = xi.filter((s) => s.starter);
  const real = filled.filter((s) => !s.starter.rc_estimated);
  const shadows = xi.filter((s) => s.shadow);
  const avgRC = real.length ? Math.round(mean(real.map((s) => s.starter.rc))) : null;
  const avgCoh = shadows.length ? Math.round(mean(shadows.map((s) => s.shadow.coherence))) : null;
  const totalCost = shadows.reduce((a, s) => a + (s.price ? s.price.est : 0), 0);
  const isManual = Object.keys(lineup).length > 0;
  const eligible = (slot) => squad.filter((p) => (slot.line === "Bramka" ? p.pos === "GK" : (p.line || lineOfPos(p.pos)) === slot.line));

  // --- macierz koherencji (podobieństwo stylu) między zawodnikami pola ---
  const wp = xi.filter((s) => s.starter && s.slot.line !== "Bramka"
    && Array.isArray(s.starter.profile) && s.starter.profile.some((v) => v !== 0));
  const cos = (a, b) => { let d = 0, na = 0, nb = 0; for (let i = 0; i < a.length; i++) { d += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i]; } if (!na || !nb) return 50; return Math.round((d / (Math.sqrt(na) * Math.sqrt(nb)) + 1) / 2 * 100); };
  const hasProfiles = wp.length >= 2;
  const pairSim = (i, j) => cos(wp[i].starter.profile, wp[j].starter.profile);
  const avgWith = (i) => { const o = []; for (let j = 0; j < wp.length; j++) if (j !== i) o.push(pairSim(i, j)); return o.length ? Math.round(mean(o)) : 0; };
  let teamCoh = null;
  if (hasProfiles) { const ps = []; for (let i = 0; i < wp.length; i++) for (let j = i + 1; j < wp.length; j++) ps.push(pairSim(i, j)); teamCoh = ps.length ? Math.round(mean(ps)) : null; }

  const selStyle = { background: C.panel2, color: C.bone, border: `1px solid ${C.line}`, borderRadius: 6,
    padding: "3px 4px", fontSize: 11, fontWeight: 600, width: "100%", cursor: "pointer" };

  return (
    <div>
      <Lead>Skład Rakowa w formacji <b className="mono" style={{ color: C.redHi }}>3-4-3</b> — ustaw go ręcznie (rozwijane listy na kartach), a pod każdym zawodnikiem zobaczysz jego najlepszy <b style={{ color: C.bone }}>cień</b>. Niżej macierz koherencji: jak podobnie stylem grają wybrani zawodnicy względem siebie.</Lead>

      <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "14px 0 4px", flexWrap: "wrap" }}>
        <span className="mono" style={{ fontSize: 11, letterSpacing: 1, color: C.steel }}>
          SKŁAD: <b style={{ color: isManual ? C.redHi : C.steelHi }}>{isManual ? "ręczny" : "automatyczny"}</b>
        </span>
        {isManual && (
          <button onClick={() => setLineup({})} style={{ background: "transparent", color: C.redHi,
            border: `1px solid ${C.red}66`, borderRadius: 8, padding: "5px 12px", fontSize: 12, cursor: "pointer", fontWeight: 600 }}>
            Przywróć automatyczny
          </button>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10, margin: "12px 0 18px" }}>
        <Kpi l="Śr. poziom XI" v={avgRC ?? "—"} />
        <Kpi l="Koherencja składu" v={teamCoh != null ? `${teamCoh}%` : "—"} c={C.redHi} />
        <Kpi l="Śr. koherencja cieni" v={avgCoh != null ? `${avgCoh}%` : "—"} c={C.proxy} />
        <Kpi l="Koszt cieni (łącznie)" v={fmt(totalCost)} c={C.proxy} />
      </div>

      <div style={{ overflowX: "auto" }}>
        <div style={{ position: "relative", width: "100%", minWidth: 660, maxWidth: 940, margin: "0 auto",
          aspectRatio: "10 / 12", background: "linear-gradient(180deg,#0f2018,#0a140e)",
          border: `1px solid ${C.line}`, borderRadius: 16, overflow: "hidden" }}>
          <div style={{ position: "absolute", left: 0, right: 0, top: "50%", height: 1, background: `${C.bone}16` }} />
          <div style={{ position: "absolute", left: "50%", top: "50%", width: 120, height: 120, marginLeft: -60, marginTop: -60, border: `1px solid ${C.bone}12`, borderRadius: "50%" }} />
          <div style={{ position: "absolute", left: "26%", right: "26%", top: 0, height: "13%", border: `1px solid ${C.bone}12`, borderTop: "none" }} />
          <div style={{ position: "absolute", left: "26%", right: "26%", bottom: 0, height: "13%", border: `1px solid ${C.bone}12`, borderBottom: "none" }} />

          {xi.map(({ slot, starter, shadow, price }) => (
            <div key={slot.id} style={{ position: "absolute", left: `${slot.x}%`, top: `${slot.y}%`,
              transform: "translate(-50%,-50%)", width: 172, background: `${C.panel}F2`,
              border: `1px solid ${starter && !starter.rc_estimated ? `${tierColor(starter.rc)}66` : C.line}`,
              borderRadius: 11, padding: "8px 10px", color: C.bone }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                <span className="mono" style={{ fontSize: 9, fontWeight: 800, color: "#fff", background: C.red, borderRadius: 4, padding: "1px 5px", flexShrink: 0 }}>{slot.label}</span>
                <select value={starter ? starter.id : ""} title="Zmień zawodnika"
                  onChange={(e) => setLineup((l) => ({ ...l, [slot.id]: e.target.value || undefined }))}
                  style={selStyle}>
                  {!starter && <option value="">—</option>}
                  {eligible(slot).map((p) => (
                    <option key={p.id} value={p.id}>{p.pos} {surname(p.name)} · {p.rc_estimated ? "b.d." : p.rc}</option>
                  ))}
                </select>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <Face name={starter ? starter.name : ""} src={starter ? photoOf(starter.name) : null}
                  size={40} ring={starter && !starter.rc_estimated ? tierColor(starter.rc) : C.line} />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {starter ? surname(starter.name) : "—"}
                  </div>
                  <span className="disp" style={{ fontSize: 15 }}>
                    {starter ? (starter.rc_estimated
                      ? <span className="mono" title="Brak dostatecznych danych" style={{ fontSize: 10, color: C.warn }}>b.d.</span>
                      : <>{starter.rc}<span style={{ fontSize: 9, color: C.steel }}> RC</span></>) : ""}
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
                  <div className="mono" style={{ fontSize: 8.5, letterSpacing: 1, color: C.steel, textTransform: "uppercase", marginBottom: 2 }}>cień</div>
                  <div style={{ fontSize: 11.5, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{shadow.name}</div>
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
          ))}
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
                {wp.map((s) => <th key={s.slot.id} className="mono" style={{ padding: 6, color: C.steel, fontWeight: 700 }} title={s.starter.name}>{s.slot.label}</th>)}
                <th className="mono" style={{ padding: 6, color: C.steelHi }}>śr.</th>
              </tr>
            </thead>
            <tbody>
              {wp.map((s, i) => (
                <tr key={s.slot.id}>
                  <td className="mono" style={{ padding: "6px 8px", color: C.steelHi, whiteSpace: "nowrap", fontWeight: 600 }} title={s.starter.name}>
                    <span style={{ color: C.redHi }}>{s.slot.label}</span> {surname(s.starter.name)}
                  </td>
                  {wp.map((_, j) => {
                    const v = i === j ? 100 : pairSim(i, j);
                    return (
                      <td key={j} className="mono" title={`${surname(wp[i].starter.name)} ↔ ${surname(wp[j].starter.name)}: ${v}`}
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

function CorrView({ data }) {
  const POS = ["DM", "CM", "AM", "ST", "LWB", "RWB", "CCB"];
  const corrOf = (a, b) => a === b ? 1 : data.correlations[`${a}-${b}`] ?? data.correlations[`${b}-${a}`] ?? 0.15;
  const insights = [
    ["Najsilniejsza para", "AM ↔ ST", "0.81", "Ofensywny pomocnik i napastnik — rdzeń powtarzalnej zależności ataku."],
    ["Oś środka", "DM–CM–AM", "0.72→0.78", "Stabilny kręgosłup formacji, spójny łańcuch zależności."],
    ["Słaby link", "RWB ↔ ST", "0.29", "Skrzydło i napastnik słabo skorelowane w tym układzie."],
  ];
  return (
    <div>
      <Lead>Które pozycje najsilniej współzależą w układzie. Ciemniejsze pole = silniejsza zależność między parą pozycji.</Lead>
      <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 8,
        background: `${C.warn}14`, border: `1px solid ${C.warn}66`, borderRadius: 9,
        padding: "9px 13px", fontSize: 12.5, color: C.steelHi, maxWidth: 760 }}>
        <span style={{ color: C.warn, fontSize: 15 }}>⚠</span>
        <span><b style={{ color: C.warn }}>DANE PRZYKŁADOWE.</b> Wartości w tej macierzy są poglądowe — pokazują, jak sekcja będzie działać. Realne korelacje wymagają policzenia ze współwystępowania akcji w danych meczowych (osobny etap). Nie interpretuj tych liczb jako faktycznych zależności.</span>
      </div>
      <div style={{ position: "relative", display: "flex", gap: 24, marginTop: 20, flexWrap: "wrap",
        alignItems: "flex-start", opacity: 0.5, filter: "grayscale(0.4)" }}>
        <span style={{ position: "absolute", top: -10, left: 8, zIndex: 2, background: C.warn, color: C.ink,
          fontSize: 9, fontWeight: 800, letterSpacing: 1, padding: "2px 8px", borderRadius: 4 }}>PRZYKŁADOWE</span>
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse" }}>
            <thead><tr><th></th>{POS.map((p) => <th key={p} className="mono" style={{ padding: 7, color: C.steel, fontSize: 11 }}>{p}</th>)}</tr></thead>
            <tbody>
              {POS.map((a) => (
                <tr key={a}>
                  <td className="mono" style={{ padding: 7, color: C.steel, fontSize: 11, fontWeight: 700 }}>{a}</td>
                  {POS.map((b) => {
                    const v = corrOf(a, b);
                    return (
                      <td key={b} title={`${a}↔${b}: ${v.toFixed(2)}`} className="mono"
                        style={{ width: 50, height: 46, textAlign: "center", fontSize: 12, fontWeight: 600,
                          background: a === b ? C.panelHi : `rgba(214,0,28,${0.1 + v * 0.85})`,
                          color: v > 0.5 ? "#fff" : C.steelHi, border: `2px solid ${C.ink}`, borderRadius: 4 }}>
                        {v.toFixed(2)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ flex: "1 1 260px", display: "flex", flexDirection: "column", gap: 10 }}>
          {insights.map(([t, pair, val, d]) => (
            <div key={t} style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 12, padding: "14px 16px" }}>
              <div className="mono" style={{ fontSize: 9.5, color: C.steel, letterSpacing: 1, textTransform: "uppercase" }}>{t}</div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 10, margin: "5px 0 6px" }}>
                <span className="disp" style={{ fontSize: 17, color: C.redHi }}>{pair}</span>
                <span className="mono" style={{ fontSize: 13, color: C.proxy }}>{val}</span>
              </div>
              <div style={{ fontSize: 12, color: C.steel, lineHeight: 1.5 }}>{d}</div>
            </div>
          ))}
        </div>
      </div>
      <Note>Korelacje liczone docelowo ze współwystępowania akcji (wspólne sekwencje podań) z danych meczowych — osobny krok po walidacji modelu.</Note>
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
    ["Formacja", "Macierz zależności między pozycjami — które role najsilniej ze sobą współgrają w układzie."],
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
        <span style={{ fontSize: 13, color: C.steelHi }}> Poziom RC jest liczony automatycznie z realnych metryk StatsBomb (percentyl względem Ekstraklasy) — to działający model, nie wpisywane ręcznie wartości. Dobór metryk oceniających zawodnika na danej pozycji to jednak przyjęte założenie, które warto potwierdzić od strony sportowej. Zawodnicy bez wystarczającej próbki meczowej mają poziom szacowany (znacznik ⚠). Macierz „Formacja" zawiera na razie dane przykładowe. Traktuj liczby jako mocną wersję roboczą, nie ostateczną.</span>
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
            <FLabel>Wiek: <b style={{ color: C.bone }}>{F.ageMin}-{F.ageMax}</b> lat</FLabel>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginBottom: 9 }}>
              {AGE_PRESETS.map(([lbl, p]) => (
                <button key={lbl} onClick={() => setF(p)} style={{
                  background: isPreset(p) ? C.red : "transparent", color: isPreset(p) ? "#fff" : C.steel,
                  border: `1px solid ${isPreset(p) ? C.red : C.line}`, borderRadius: 7,
                  padding: "4px 10px", fontSize: 11.5, cursor: "pointer", fontWeight: 600 }}>{lbl}</button>
              ))}
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input type="range" min={16} max={45} value={F.ageMin}
                onChange={(e) => setF({ ageMin: Math.min(+e.target.value, F.ageMax) })}
                style={{ flex: 1, accentColor: C.red }} />
              <input type="range" min={16} max={45} value={F.ageMax}
                onChange={(e) => setF({ ageMax: Math.max(+e.target.value, F.ageMin) })}
                style={{ flex: 1, accentColor: C.red }} />
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
  const scored = candidates
    .filter((c) => !c.p.level_estimated && c.price && c.price.est > 0)
    .map((c) => {
      const skill = 0.45 * (Number(c.m.level) || 0) + 0.55 * (Number(c.m.coherence) || 0);
      const value = skill / Math.sqrt(Math.max(c.price.est, 0.5));
      return { ...c, skill, value };
    });
  if (!scored.length) return null;
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
        <span style={{ fontSize: 12, color: C.steel }}>najlepszy kompromis jakość / cena na pozycji <b className="mono" style={{ color: C.steelHi }}>{sel.pos}</b></span>
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
            <div title="Wskaźnik wartości = jakość / cena">
              <div style={{ height: 6, background: C.panel2, borderRadius: 3, overflow: "hidden" }}>
                <div style={{ width: `${(c.value / maxV) * 100}%`, height: "100%", background: C.proxy }} />
              </div>
              <div style={{ fontSize: 9, color: C.steel, marginTop: 3 }}>wartość</div>
            </div>
            <button onClick={() => toggleShort(c.p.id)} title="Lista obserwowanych"
              style={{ background: short.includes(c.p.id) ? C.red : "transparent",
                color: short.includes(c.p.id) ? "#fff" : C.steel, border: `1px solid ${short.includes(c.p.id) ? C.red : C.line}`,
                borderRadius: 9, width: 34, height: 34, cursor: "pointer", fontSize: 15 }}>
              {short.includes(c.p.id) ? "★" : "☆"}
            </button>
          </div>
        ))}
      </div></div>
      <div style={{ fontSize: 10.5, color: C.steel, marginTop: 10 }}>
        Wartość = (0,45·poziom + 0,55·koherencja) / √cena. Tylko kandydaci z wyceną i policzonym poziomem. To podpowiedź do obserwacji, nie ostateczny ranking.
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
