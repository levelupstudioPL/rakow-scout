import React, { useState, useEffect, useMemo } from "react";

// ============================ TOKENS ============================
const C = {
  ink: "#0A0A0B", panel: "#141416", panel2: "#1B1B1E", panelHi: "#232327",
  line: "#2C2C31", bone: "#F2F0EC", steel: "#71767E", steelHi: "#9CA1A9",
  red: "#D6001C", redHi: "#FF2740", redDim: "#8A0012",
  good: "#3ECF8E", warn: "#E8A13A", bad: "#E5544B", proxy: "#E8A13A",
};

const pctToRC = (p) => Math.round((Number(p) || 0) / 10);
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

export default function App() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [view, setView] = useState("twin");
  const [sel, setSel] = useState(null);
  const [loading, setLoading] = useState(false);
  const [sortBy, setSortBy] = useState("coherence");
  const [short, setShort] = useState([]);
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
  const [filters, setFilters] = useState(FILTERS_DEFAULT);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const setF = (patch) => setFilters((f) => ({ ...f, ...patch }));
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
        setData(d);
        setSel(d.squad.find((p) => p.real) || d.squad[0]);
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

  const fmt = (v) => `€${v.toFixed(1)}M`;
  const shortRows = useMemo(() => candidates.filter((c) => short.includes(c.p.id)), [candidates, short]);
  const median = (a) => { if (!a.length) return 0; const s = [...a].sort((x, y) => x - y);
    const m = Math.floor(s.length / 2); return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

  if (err && !data) return <Splash>{err}</Splash>;
  if (!data) return <Splash>Wczytywanie…</Splash>;

  const isLive = data.meta.source && data.meta.source.includes("live");
  const realCount = data.squad.filter((p) => p.real).length;
  const NAV = [
    ["twin", "Skład", "01"], ["match", "Odpowiednicy", "02"],
    ["leagues", "Handicapy", "03"], ["corr", "Formacja", "04"], ["help", "Instrukcja", "—"],
  ];

  return (
    <div style={{ minHeight: "100vh", background: C.ink, color: C.bone,
      fontFamily: "'Inter', system-ui, sans-serif", display: "flex" }} className="shell">
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800;900&family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
        *{box-sizing:border-box;}
        ::selection{background:${C.red};color:#fff;}
        .disp{font-family:'Archivo',sans-serif;font-weight:800;letter-spacing:-0.02em;}
        .mono{font-family:'Space Grotesk',monospace;}
        .navitem{transition:all .15s ease;}
        .navitem:hover{background:${C.panel2};}
        .card{transition:transform .15s ease, border-color .15s ease;}
        .card:hover{border-color:${C.red};transform:translateY(-2px);}
        .rowh:hover{background:${C.panel2};}
        button:focus-visible{outline:2px solid ${C.redHi};outline-offset:2px;}
        @media (prefers-reduced-motion:no-preference){.bar{transition:width .6s cubic-bezier(.2,.8,.2,1);}}
        @media(max-width:820px){.shell{flex-direction:column;} .rail{width:100%!important;min-height:auto!important;position:relative!important;} .railnav{flex-direction:row!important;overflow-x:auto;} .railfoot{display:none!important;}}
      `}</style>

      {/* ===================== LEFT RAIL ===================== */}
      <aside className="rail" style={{ width: 232, minHeight: "100vh", position: "sticky", top: 0,
        background: `linear-gradient(180deg, ${C.panel} 0%, ${C.ink} 100%)`,
        borderRight: `1px solid ${C.line}`, display: "flex", flexDirection: "column",
        padding: "22px 0", flexShrink: 0 }}>
        <div style={{ padding: "0 22px 22px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <img src="/logo-rakow.webp" alt="Herb Raków Częstochowa"
              style={{ width: 34, height: 41, objectFit: "contain", display: "block" }} />
            <div>
              <div className="disp" style={{ fontSize: 15, lineHeight: 1 }}>RAKÓW</div>
              <div className="mono" style={{ fontSize: 9, color: C.steel, letterSpacing: 2, marginTop: 2 }}>SCOUT ENGINE</div>
            </div>
          </div>
        </div>

        <nav className="railnav" style={{ display: "flex", flexDirection: "column", gap: 2, padding: "0 12px" }}>
          {NAV.map(([k, label, n]) => (
            <button key={k} className="navitem" onClick={() => setView(k)} style={{
              display: "flex", alignItems: "center", gap: 12, textAlign: "left",
              background: view === k ? C.red : "transparent", color: view === k ? "#fff" : C.steelHi,
              border: "none", padding: "11px 12px", borderRadius: 8, cursor: "pointer",
              fontSize: 13.5, fontWeight: 600, whiteSpace: "nowrap" }}>
              <span className="mono" style={{ fontSize: 10, opacity: view === k ? 0.8 : 0.5, width: 14 }}>{n}</span>
              {label}
            </button>
          ))}
        </nav>

        <div className="railfoot" style={{ marginTop: "auto", padding: "0 22px" }}>
          <div style={{ fontSize: 10, color: C.steel, lineHeight: 1.6,
            border: `1px solid ${C.line}`, borderRadius: 8, padding: "10px 12px" }}>
            <div className="mono" style={{ letterSpacing: 1, color: C.steelHi, marginBottom: 3 }}>ŹRÓDŁO DANYCH</div>
            {isLive ? <span style={{ color: C.good }}>● live</span> : <span style={{ color: C.proxy }}>● zapis (snapshot)</span>}
          </div>
        </div>
      </aside>

      {/* ===================== MAIN ===================== */}
      <main style={{ flex: 1, minWidth: 0, padding: "0 0 60px" }}>
        <div style={{ position: "relative", overflow: "hidden", borderBottom: `1px solid ${C.line}`,
          background: `linear-gradient(120deg, ${C.panel} 0%, ${C.ink} 60%)` }}>
          <div style={{ position: "absolute", top: 0, right: -80, width: 300, height: "100%",
            background: `linear-gradient(90deg, transparent, ${C.redDim}22)`, transform: "skewX(-14deg)" }} />
          <div style={{ padding: "30px 34px 26px", position: "relative" }}>
            <div className="mono" style={{ fontSize: 10.5, letterSpacing: 3, color: C.red, fontWeight: 700 }}>
              CYFROWY BLIŹNIAK · MVP
            </div>
            <h1 className="disp" style={{ margin: "8px 0 0", fontSize: "clamp(28px, 4vw, 46px)", lineHeight: 0.98 }}>
              {view === "twin" && "Obecny skład"}
              {view === "match" && "Odpowiednicy z Europy"}
              {view === "leagues" && "Handicapy lig"}
              {view === "corr" && "Zależności formacji"}
              {view === "help" && "Jak korzystać"}
            </h1>
            <div style={{ display: "flex", gap: 26, marginTop: 18, flexWrap: "wrap" }}>
              <Stat n={data.squad.length} l="zawodników" />
              <Stat n={realCount} l="realnych profili" accent />
              <Stat n={data.leagues.length - 1} l="lig w puli" />
              <Stat n={data.pool.length} l="kandydatów" />
            </div>
          </div>
        </div>

        {err && <div style={{ margin: "16px 34px 0", fontSize: 12.5, color: C.warn }}>{err}</div>}

        <div style={{ padding: "26px 34px 0", maxWidth: 1180 }}>
          {view === "twin" && <TwinView data={data} sel={sel} setSel={setSel} setView={setView} />}
          {view === "match" && <MatchView {...{ data, sel, setSel, candidates, sortBy, setSortBy,
            short, toggleShort, shortRows, adjusted, fmt, median,
            filters, setF, setFilters, FILTERS_DEFAULT, filtersOpen, setFiltersOpen }} />}
          {view === "leagues" && <LeaguesView data={data} />}
          {view === "corr" && <CorrView data={data} />}
          {view === "help" && <HelpView data={data} setView={setView} />}
        </div>
      </main>
    </div>
  );
}

// ============================ SUBVIEWS ============================
function TwinView({ data, sel, setSel, setView }) {
  const byLine = { Bramka: [], Obrona: [], Pomoc: [], Atak: [] };
  data.squad.forEach((p) => { (byLine[p.line || lineOfPos(p.pos)] || byLine.Pomoc).push(p); });
  const order = ["Atak", "Pomoc", "Obrona", "Bramka"];
  return (
    <div>
      <Lead>Skład ułożony liniami — jak na tablicy taktycznej. Kliknij zawodnika, by znaleźć jego odpowiedników w Europie.</Lead>
      {data.squad.some((p) => p.rc_estimated) && (
        <div style={{ marginTop: 10, display: "inline-flex", alignItems: "center", gap: 7,
          background: `${C.warn}14`, border: `1px solid ${C.warn}44`, borderRadius: 9,
          padding: "7px 12px", fontSize: 12, color: C.steelHi }}>
          <span style={{ color: C.warn, fontSize: 14 }}>⚠</span>
          Znacznik przy RC oznacza <b style={{ color: C.bone }}>niepełne dane</b> — poziom szacowany, bo zawodnik nie ma jeszcze wystarczającej próbki meczowej. Traktuj orientacyjnie.
        </div>
      )}
      <RcExplainer />
      <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 20 }}>
        {order.map((line) => (
          byLine[line].length > 0 && (
          <div key={line}>
            <div className="mono" style={{ fontSize: 10.5, letterSpacing: 2, color: C.steel,
              marginBottom: 8, display: "flex", alignItems: "center", gap: 10 }}>
              {line.toUpperCase()}
              <span style={{ flex: 1, height: 1, background: C.line }} />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(210px,1fr))", gap: 10 }}>
              {byLine[line].map((p) => (
                <button key={p.id} className="card" onClick={() => { setSel(p); setView("match"); }}
                  style={{ textAlign: "left", background: C.panel, border: `1px solid ${sel?.id === p.id ? C.red : C.line}`,
                    borderRadius: 12, padding: "15px 16px", cursor: "pointer", color: C.bone, position: "relative", overflow: "hidden" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div style={{ minWidth: 0 }}>
                      <div className="mono" style={{ fontSize: 10.5, color: C.redHi, fontWeight: 700 }}>{p.pos}</div>
                      <div style={{ fontSize: 14, fontWeight: 600, marginTop: 4, lineHeight: 1.2 }}>{p.name}</div>
                    </div>
                    <div className="disp" style={{ fontSize: 34, lineHeight: 0.8, color: C.bone, flexShrink: 0,
                      display: "flex", alignItems: "flex-start", gap: 3 }}>
                      {p.rc}<span style={{ fontSize: 11, color: C.steel }}> RC</span>
                      {p.rc_estimated && (
                        <span title="Niepełne dane — poziom szacowany (zawodnik nie ma jeszcze wystarczającej próbki meczowej w StatsBomb). Traktuj orientacyjnie."
                          style={{ fontSize: 13, color: C.warn, cursor: "help", lineHeight: 1 }}>⚠</span>
                      )}
                    </div>
                  </div>
                  <div style={{ height: 5, background: C.panel2, borderRadius: 3, overflow: "hidden", marginTop: 12 }}>
                    <div className="bar" style={{ width: `${p.rc}%`, height: "100%",
                      background: p.rc_estimated ? C.warn : C.red }} />
                  </div>
                  {p.real && <div style={{ position: "absolute", top: 0, right: 0, background: C.good,
                    color: C.ink, fontSize: 8.5, fontWeight: 800, padding: "2px 7px", letterSpacing: 0.5 }}>REAL</div>}
                </button>
              ))}
            </div>
          </div>
          )
        ))}
      </div>
    </div>
  );
}

function MatchView({ data, sel, setSel, candidates, sortBy, setSortBy, short, toggleShort, shortRows, adjusted, fmt, median,
  filters, setF, setFilters, FILTERS_DEFAULT, filtersOpen, setFiltersOpen }) {
  if (!sel) return null;
  const totalForPos = data.pool.filter((p) => p.pos === sel.pos).length;
  const activeCount = countActiveFilters(filters, FILTERS_DEFAULT);
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

      <FilterPanel {...{ data, filters, setF, setFilters, FILTERS_DEFAULT,
        filtersOpen, setFiltersOpen, activeCount, shown: candidates.length, total: totalForPos }} />

      {candidates.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 10, marginBottom: 18 }}>
          <Kpi l="Kandydatów" v={candidates.length} />
          <Kpi l="Najtańszy" v={fmt(Math.min(...candidates.map((c) => c.price.est)))} c={C.good} />
          <Kpi l="Mediana" v={fmt(median(candidates.map((c) => c.price.est)))} c={C.proxy} />
          <Kpi l="Najlepsza koh." v={`${Math.round(Math.max(...candidates.map((c) => c.m.coherence)))}%`} c={C.redHi} />
        </div>
      )}

      {candidates.length === 0 && (
        <Empty>
          {activeCount > 0 ? (
            <>Żaden kandydat na pozycji <b className="mono">{sel.pos}</b> nie spełnia ustawionych filtrów
            {totalForPos > 0 ? <> (w puli jest ich {totalForPos})</> : null}.{" "}
            <button onClick={() => setFilters(FILTERS_DEFAULT)}
              style={{ background: "none", border: "none", color: C.redHi, cursor: "pointer",
                fontSize: 13.5, textDecoration: "underline", padding: 0 }}>Wyczyść filtry</button></>
          ) : (
            <>Brak kandydatów na pozycji <b className="mono">{sel.pos}</b> w obecnej puli.</>
          )}
        </Empty>
      )}

      <div style={{ display: "grid", gap: 9 }}>
        {candidates.map(({ p, m, price }) => {
          const a = adjusted(p);
          return (
            <div key={p.id} className="rowh" style={{ background: C.panel, border: `1px solid ${C.line}`,
              borderRadius: 12, padding: "15px 18px", display: "grid",
              gridTemplateColumns: "1.5fr 0.9fr 1fr 1fr auto", gap: 16, alignItems: "center" }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13.5, fontWeight: 600 }}>{p.name && p.name !== "?" ? p.name : p.lg}</div>
                <div style={{ fontSize: 11, color: C.steel, marginTop: 2 }}>{p.lg} · {p.pos} · {p.age} lat · do {p.contract}</div>
              </div>
              <div>
                <div className="disp" style={{ fontSize: 26, lineHeight: 0.9,
                  display: "flex", alignItems: "flex-start", gap: 2 }}>
                  {m.level}
                  {p.level_estimated && (
                    <span title="Niepełne dane — poziom szacowany (brak wystarczającej próbki meczowej)."
                      style={{ fontSize: 11, color: C.warn, cursor: "help", lineHeight: 1 }}>⚠</span>
                  )}
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
              <button onClick={() => toggleShort(p.id)} title="Lista obserwowanych"
                style={{ background: short.includes(p.id) ? C.red : "transparent",
                  color: short.includes(p.id) ? "#fff" : C.steel, border: `1px solid ${short.includes(p.id) ? C.red : C.line}`,
                  borderRadius: 9, width: 38, height: 38, cursor: "pointer", fontSize: 17 }}>
                {short.includes(p.id) ? "★" : "☆"}
              </button>
            </div>
          );
        })}
      </div>

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
      <div style={{ display: "flex", gap: 24, marginTop: 20, flexWrap: "wrap", alignItems: "flex-start" }}>
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
    ["Odpowiednicy", "Kandydaci z lig europejskich na tej samej pozycji. Dwie miary obok siebie: poziom (jak dobry jest zawodnik) i koherencja (jak podobnie gra do zawodnika Rakowa, którego miałby zastąpić). Sortuj po koherencji, poziomie lub cenie."],
    ["Lista obserwowanych", "Gwiazdka przy kandydacie dodaje go do listy na dole. Aplikacja sumuje łączny szacowany koszt zaznaczonych zawodników."],
    ["Handicapy", "Tabela: o ile każda liga różni się od Ekstraklasy, osobno per linia. To te korekty podnoszą lub obniżają surowy poziom kandydata."],
    ["Formacja", "Macierz zależności między pozycjami — które role najsilniej ze sobą współgrają w układzie."],
    ["Dane live", "Przycisk w lewym panelu pobiera świeże dane, gdy źródło jest podpięte. Bez tego działają dane zapisane."],
  ];
  const sources = [
    ["StatsBomb", "Metryki zawodników i podstawa poziomów RC oraz handicapów lig.", C.good],
    ["Wartości rynkowe (Kaggle)", "Wartości rynkowe, wiek i kontrakty kandydatów — ze stabilnego, okresowo aktualizowanego zbioru danych.", C.proxy],
    ["Metoda handicapów", "Porównuje metrykę danej linii z Ekstraklasą i przelicza na skok RC (10% = RC+1).", C.redHi],
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

function FilterPanel({ data, filters, setF, setFilters, FILTERS_DEFAULT,
  filtersOpen, setFiltersOpen, activeCount, shown, total }) {
  const F = filters;
  const leagues = [...new Set(data.pool.map((p) => p.lg))].filter(Boolean).sort();
  const AGE_PRESETS = [["do 23", { ageMin: 16, ageMax: 23 }], ["24-28", { ageMin: 24, ageMax: 28 }],
    ["29+", { ageMin: 29, ageMax: 45 }], ["każdy", { ageMin: 16, ageMax: 45 }]];
  const isPreset = (p) => F.ageMin === p.ageMin && F.ageMax === p.ageMax;

  return (
    <div style={{ marginBottom: 18, background: C.panel, border: `1px solid ${activeCount > 0 ? C.redHi : C.line}`,
      borderRadius: 12, overflow: "hidden" }}>
      <button onClick={() => setFiltersOpen(!filtersOpen)}
        style={{ width: "100%", display: "flex", alignItems: "center", gap: 10, background: "transparent",
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

      {filtersOpen && (
        <div style={{ padding: "4px 16px 16px", borderTop: `1px solid ${C.line}`,
          display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: 18 }}>

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

          {activeCount > 0 && (
            <div style={{ gridColumn: "1 / -1", paddingTop: 4 }}>
              <button onClick={() => setFilters(FILTERS_DEFAULT)}
                style={{ background: "transparent", color: C.redHi, border: `1px solid ${C.red}66`,
                  borderRadius: 8, padding: "7px 14px", fontSize: 12, cursor: "pointer", fontWeight: 600 }}>
                Wyczyść filtry ({activeCount})
              </button>
            </div>
          )}
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
function SectionLabel({ children }) {
  return (
    <div className="mono" style={{ fontSize: 11, letterSpacing: 2, color: C.red, fontWeight: 700,
      margin: "26px 0 12px", display: "flex", alignItems: "center", gap: 10 }}>
      {children.toUpperCase()}<span style={{ flex: 1, height: 1, background: C.line }} />
    </div>
  );
}
