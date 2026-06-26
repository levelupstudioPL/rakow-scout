import React, { useState, useEffect, useMemo } from "react";

const C = {
  bg: "#0E1412", panel: "#161E1B", panel2: "#1C2723", line: "#2A3A34",
  ink: "#E8EDE9", dim: "#8FA39B", red: "#C8102E", redSoft: "#E03A52",
  proxy: "#D9A441", good: "#4FB286", warn: "#D98C3F", bad: "#C5615A",
};

const pctToRC = (p) => Math.round(p / 10);
const lineOfPos = (pos) =>
  ({ GK: "Bramka", RCB: "Obrona", CCB: "Obrona", LCB: "Obrona", RWB: "Obrona",
     LWB: "Obrona", DM: "Pomoc", CM: "Pomoc", AM: "Pomoc", ST: "Atak" }[pos]);

function Tag({ children, color }) {
  return (
    <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase",
      padding: "2px 7px", borderRadius: 4, color, border: `1px solid ${color}55`,
      background: `${color}14`, whiteSpace: "nowrap" }}>{children}</span>
  );
}

export default function App() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [tab, setTab] = useState("twin");
  const [sel, setSel] = useState(null);
  const [loading, setLoading] = useState(false);
  const [sortBy, setSortBy] = useState("fit"); // fit | price | level
  const [short, setShort] = useState([]); // shortlist of pool ids
  const toggleShort = (id) => setShort((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id]);

  // Load snapshot on mount
  useEffect(() => { loadData("data.json"); }, []);

  function loadData(url, live = false) {
    setLoading(true); setErr(null);
    fetch(url)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((d) => {
        setData(d);
        setSel(d.squad.find((p) => p.real) || d.squad[0]);
      })
      .catch((e) => setErr(live
        ? "Tryb live niedostępny — brak funkcji serverless na tym hostingu. Zostaję na snapshocie."
        : `Nie udało się wczytać danych: ${e.message}`))
      .finally(() => setLoading(false));
  }

  // Live fetch hits the serverless proxy (only works on Netlify/Vercel deploy)
  function fetchLive() {
    loadData("/.netlify/functions/fbref?team=rakow", true);
  }

  const adjusted = (p) => {
    const lg = data.leagues.find((l) => l.lg === p.lg);
    const line = lineOfPos(p.pos);
    const hc = lg ? lg[line] : 0;
    return { adj: p.raw + pctToRC(hc) * 2, hcRC: pctToRC(hc), pct: hc, line };
  };
  const matchScore = (player, p) => {
    if (p.pos !== player.pos) return null;
    const { adj } = adjusted(p);
    const diff = adj - player.rc;
    return { adj, diff, fit: Math.max(0, 100 - Math.abs(diff) * 7) };
  };

  // PROXY estymacja ceny transferu. Baza = wartość rynkowa (mv, mln €),
  // korygowana o: poziom skoryg. vs RC, wiek, długość kontraktu, mnożnik ligi.
  // To placeholder logiki — realnie kalibrowane na zrealizowanych transferach.
  const estimatePrice = (player, p) => {
    const { adj } = adjusted(p);
    const base = p.mv || 0;
    const levelF = 1 + Math.max(-0.3, (adj - player.rc) * 0.04); // wyższy poziom → drożej
    const ageF = p.age <= 23 ? 1.25 : p.age <= 26 ? 1.05 : p.age <= 29 ? 0.85 : 0.65;
    const yearsLeft = Math.max(0, (p.contract || 2026) - 2026);
    const contractF = yearsLeft >= 3 ? 1.2 : yearsLeft === 2 ? 1.0 : yearsLeft === 1 ? 0.75 : 0.5;
    const ligF = { "Championship (EN)": 1.3, "Eredivisie (NL)": 1.15, "Liga Portugalska": 1.2,
      "Liga Belgijska": 1.1, "2. Bundesliga (DE)": 1.05, "Superliga (DK)": 0.95 }[p.lg] || 1;
    const est = base * levelF * ageF * contractF * ligF;
    const lo = est * 0.8, hi = est * 1.25;
    return { est, lo, hi, ageF, contractF, yearsLeft };
  };

  const candidates = useMemo(() => {
    if (!data || !sel) return [];
    const rows = data.pool.map((p) => ({ p, m: matchScore(sel, p) }))
      .filter((x) => x.m)
      .map((x) => ({ ...x, price: estimatePrice(sel, x.p) }));
    const sorters = {
      fit: (a, b) => b.m.fit - a.m.fit,
      price: (a, b) => a.price.est - b.price.est,
      level: (a, b) => b.m.adj - a.m.adj,
    };
    return rows.sort(sorters[sortBy]);
  }, [data, sel, sortBy]);

  const fmt = (v) => `€${v.toFixed(1)}M`;
  const shortRows = useMemo(() => candidates.filter((c) => short.includes(c.p.id)), [candidates, short]);
  const median = (arr) => {
    if (!arr.length) return 0;
    const s = [...arr].sort((a, b) => a - b);
    const m = Math.floor(s.length / 2);
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  };

  if (err && !data) return <Centered>{err}</Centered>;
  if (!data) return <Centered>Wczytywanie danych…</Centered>;

  const POSREL = ["DM", "CM", "AM", "ST", "LWB", "RWB", "CCB"];
  const corrOf = (a, b) =>
    a === b ? 1 : data.correlations[`${a}-${b}`] ?? data.correlations[`${b}-${a}`] ?? 0.15;
  const isLive = data.meta.source !== "snapshot-proxy";

  const tabs = [["twin", "Cyfrowy bliźniak"], ["match", "Odpowiednicy"],
    ["leagues", "Handicapy lig"], ["corr", "Korelacje formacji"]];

  return (
    <div style={{ minHeight: "100vh", background: C.bg, color: C.ink,
      fontFamily: "'Inter', system-ui, sans-serif", paddingBottom: 60 }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap');
        *{box-sizing:border-box;}
        .mono{font-family:'Space Grotesk',monospace;}
        .row:hover{background:${C.panel2};}
        button:focus-visible{outline:2px solid ${C.redSoft};outline-offset:2px;}
        @media (prefers-reduced-motion: no-preference){.bar{transition:width .5s cubic-bezier(.2,.7,.2,1);}}
      `}</style>

      <header style={{ borderBottom: `1px solid ${C.line}`,
        background: `linear-gradient(180deg, ${C.panel} 0%, ${C.bg} 100%)`, padding: "26px 32px 22px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <div style={{ width: 8, height: 38, background: C.red, borderRadius: 2 }} />
          <div>
            <div style={{ fontSize: 11, letterSpacing: 3, color: C.dim, textTransform: "uppercase", fontWeight: 600 }}>
              Scouting Analytics · Prototyp MVP
            </div>
            <h1 className="mono" style={{ margin: "2px 0 0", fontSize: 26, fontWeight: 700 }}>
              Cyfrowy bliźniak składu <span style={{ color: C.redSoft }}>Rakowa</span>
            </h1>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <Tag color={C.good}>● realne</Tag>
            <Tag color={C.proxy}>● proxy</Tag>
            <button onClick={fetchLive} disabled={loading} style={{
              background: isLive ? C.good : "transparent", color: isLive ? "#04140D" : C.dim,
              border: `1px solid ${isLive ? C.good : C.line}`, padding: "7px 13px",
              borderRadius: 8, cursor: "pointer", fontSize: 12, fontWeight: 700 }}>
              {loading ? "…" : isLive ? "● LIVE (FBref)" : "Pobierz live z FBref"}
            </button>
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 12, flexWrap: "wrap" }}>
          <Tag color={isLive ? C.good : C.proxy}>
            Źródło: {isLive ? "FBref live" : "snapshot (proxy)"}
          </Tag>
          <span style={{ fontSize: 11.5, color: C.dim }}>{data.meta.note}</span>
        </div>
        {err && <div style={{ marginTop: 10, fontSize: 12, color: C.warn }}>{err}</div>}
      </header>

      <nav style={{ display: "flex", gap: 4, padding: "16px 32px 0", flexWrap: "wrap" }}>
        {tabs.map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)} style={{
            background: tab === k ? C.red : "transparent", color: tab === k ? "#fff" : C.dim,
            border: `1px solid ${tab === k ? C.red : C.line}`, padding: "8px 16px",
            borderRadius: 8, cursor: "pointer", fontSize: 13, fontWeight: 600 }}>{label}</button>
        ))}
      </nav>

      <main style={{ padding: "22px 32px 0", maxWidth: 1100 }}>
        {tab === "twin" && (
          <div>
            <SectionTitle n="01" t="Obecny skład → cyfrowy bliźniak"
              s="Każdy gracz ma poziom RC (Ekstraklasa = baza). Kliknij, by analizować odpowiedników." />
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(230px,1fr))", gap: 10 }}>
              {data.squad.map((p) => (
                <button key={p.id} className="row" onClick={() => { setSel(p); setTab("match"); }}
                  style={{ textAlign: "left", background: C.panel,
                    border: `1px solid ${sel.id === p.id ? C.red : C.line}`, borderRadius: 10,
                    padding: "13px 14px", cursor: "pointer", color: C.ink }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span className="mono" style={{ fontSize: 11, fontWeight: 700, color: C.redSoft }}>{p.pos}</span>
                    {p.real ? <Tag color={C.good}>realny</Tag> : <Tag color={C.dim}>rola</Tag>}
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 600, margin: "6px 0 8px" }}>{p.name}</div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <div style={{ flex: 1, height: 6, background: C.panel2, borderRadius: 3, overflow: "hidden" }}>
                      <div className="bar" style={{ width: `${p.rc}%`, height: "100%", background: C.red }} />
                    </div>
                    <span className="mono" style={{ fontSize: 13, fontWeight: 700, color: C.proxy }}>RC {p.rc}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {tab === "match" && sel && (
          <div>
            <SectionTitle n="02" t={`Odpowiednicy dla: ${sel.name}`}
              s={`Pozycja ${sel.pos} · poziom RC ${sel.rc}. Poziom kandydata = surowy + handicap ligi. Cena = estymacja proxy.`} />
            <div style={{ display: "flex", gap: 10, marginBottom: 14, flexWrap: "wrap", alignItems: "center" }}>
              <select value={sel.id} onChange={(e) => setSel(data.squad.find((p) => p.id === e.target.value))}
                style={{ background: C.panel, color: C.ink, border: `1px solid ${C.line}`, borderRadius: 8,
                  padding: "8px 12px", fontSize: 13 }}>
                {data.squad.map((p) => <option key={p.id} value={p.id}>{p.pos} — {p.name}</option>)}
              </select>
              <div style={{ display: "flex", gap: 6, marginLeft: "auto", alignItems: "center" }}>
                <span style={{ fontSize: 11, color: C.dim }}>sortuj:</span>
                {[["fit", "dopasowanie"], ["price", "cena"], ["level", "poziom"]].map(([k, l]) => (
                  <button key={k} onClick={() => setSortBy(k)} style={{
                    background: sortBy === k ? C.panel2 : "transparent", color: sortBy === k ? C.ink : C.dim,
                    border: `1px solid ${sortBy === k ? C.redSoft : C.line}`, padding: "6px 11px",
                    borderRadius: 7, cursor: "pointer", fontSize: 12, fontWeight: 600 }}>{l}</button>
                ))}
              </div>
            </div>

            {candidates.length > 0 && (
              <div style={{ display: "flex", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
                <MiniStat label="Kandydatów" value={candidates.length} />
                <MiniStat label="Najtańszy" value={fmt(Math.min(...candidates.map((c) => c.price.est)))} color={C.good} />
                <MiniStat label="Mediana ceny" value={fmt(median(candidates.map((c) => c.price.est)))} color={C.proxy} />
                <MiniStat label="Najlepsze dop." value={`${Math.round(Math.max(...candidates.map((c) => c.m.fit)))}%`} color={C.redSoft} />
              </div>
            )}

            {candidates.length === 0 && (
              <div style={{ background: C.panel, border: `1px dashed ${C.line}`, borderRadius: 10,
                padding: 22, color: C.dim, fontSize: 14 }}>
                Brak odpowiedników na pozycji <b className="mono">{sel.pos}</b> w puli. W trybie live pula
                pochodzi z FBref dla danej pozycji.
              </div>
            )}

            <div style={{ display: "grid", gap: 8 }}>
              {candidates.map(({ p, m, price }) => {
                const a = adjusted(p);
                return (
                  <div key={p.id} className="row" style={{ background: C.panel, border: `1px solid ${C.line}`,
                    borderRadius: 10, padding: "14px 16px", display: "grid",
                    gridTemplateColumns: "1.5fr 1fr 1fr 1.1fr auto", gap: 14, alignItems: "center" }}>
                    {/* tożsamość + meta */}
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600 }}>{p.lg} <span className="mono" style={{ color: C.dim }}>· {p.pos}</span></div>
                      <div style={{ fontSize: 11, color: C.dim, marginTop: 2 }}>
                        {p.age} lat · kontrakt do {p.contract} · MV {fmt(p.mv)}
                      </div>
                    </div>
                    {/* poziom */}
                    <div style={{ fontSize: 12, color: C.dim }}>
                      poziom <b style={{ color: C.proxy }} className="mono">{m.adj}</b>
                      <div style={{ fontSize: 10 }}>handicap RC+{a.hcRC} · surowy {p.raw}</div>
                    </div>
                    {/* delta + dopasowanie */}
                    <div>
                      <div style={{ fontSize: 12, color: m.diff >= 0 ? C.good : C.warn }}>
                        Δ vs RC: <b className="mono">{m.diff >= 0 ? "+" : ""}{m.diff}</b>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
                        <div style={{ flex: 1, height: 5, background: C.panel2, borderRadius: 3, overflow: "hidden" }}>
                          <div className="bar" style={{ width: `${m.fit}%`, height: "100%",
                            background: m.fit > 70 ? C.good : m.fit > 45 ? C.warn : C.bad }} />
                        </div>
                        <span className="mono" style={{ fontSize: 11, fontWeight: 700,
                          color: m.fit > 70 ? C.good : m.fit > 45 ? C.warn : C.bad }}>{Math.round(m.fit)}%</span>
                      </div>
                    </div>
                    {/* cena */}
                    <div style={{ textAlign: "right" }}>
                      <div className="mono" style={{ fontSize: 18, fontWeight: 700, color: C.proxy }}>{fmt(price.est)}</div>
                      <div style={{ fontSize: 10, color: C.dim }}>widełki {fmt(price.lo)}–{fmt(price.hi)}</div>
                    </div>
                    {/* shortlist */}
                    <div style={{ textAlign: "right", minWidth: 28 }}>
                      <button onClick={() => toggleShort(p.id)} title="Dodaj do listy"
                        style={{ background: short.includes(p.id) ? C.red : "transparent",
                          color: short.includes(p.id) ? "#fff" : C.dim, border: `1px solid ${short.includes(p.id) ? C.red : C.line}`,
                          borderRadius: 7, width: 30, height: 30, cursor: "pointer", fontSize: 15, fontWeight: 700 }}>
                        {short.includes(p.id) ? "★" : "☆"}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>

            {short.length > 0 && (
              <div style={{ marginTop: 18, background: C.panel, border: `1px solid ${C.red}`, borderRadius: 12, padding: "14px 16px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                  <span className="mono" style={{ fontSize: 13, fontWeight: 700, color: C.redSoft }}>★ Lista obserwowanych ({short.length})</span>
                  <span style={{ fontSize: 12, color: C.dim, marginLeft: "auto" }}>
                    łączny koszt (est.): <b className="mono" style={{ color: C.proxy }}>
                      {fmt(shortRows.reduce((s, c) => s + c.price.est, 0))}</b>
                  </span>
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {shortRows.map((c) => (
                    <span key={c.p.id} style={{ fontSize: 12, background: C.panel2, border: `1px solid ${C.line}`,
                      borderRadius: 7, padding: "5px 10px" }}>
                      {c.p.lg} · {c.p.pos} · <b style={{ color: C.proxy }}>{fmt(c.price.est)}</b>
                    </span>
                  ))}
                </div>
              </div>
            )}

            <p style={{ fontSize: 11.5, color: C.dim, marginTop: 14 }}>
              <b style={{ color: C.proxy }}>Cena to estymacja proxy:</b> baza = wartość rynkowa, korygowana o poziom vs RC,
              wiek, długość kontraktu i mnożnik ligi. Realnie kalibrowana na zrealizowanych transferach.
            </p>
          </div>
        )}

        {tab === "leagues" && (
          <div>
            <SectionTitle n="03" t="Tabela handicapów lig"
              s="Odchylenie % danej linii vs poziom Ekstraklasy → skok RC. Przykład: Pomoc +10% = RC+1." />
            <div style={{ overflowX: "auto", border: `1px solid ${C.line}`, borderRadius: 12 }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, minWidth: 560 }}>
                <thead>
                  <tr style={{ background: C.panel2, color: C.dim }}>
                    {["Liga", "Bramka", "Obrona", "Pomoc", "Atak"].map((h) => (
                      <th key={h} style={{ textAlign: h === "Liga" ? "left" : "center", padding: "11px 14px", fontWeight: 600 }}>{h}</th>))}
                  </tr>
                </thead>
                <tbody>
                  {data.leagues.map((l) => (
                    <tr key={l.lg} className="row" style={{ borderTop: `1px solid ${C.line}`,
                      background: l.base ? `${C.red}10` : "transparent" }}>
                      <td style={{ padding: "11px 14px", fontWeight: 600 }}>{l.lg} {l.base && <Tag color={C.red}>baza</Tag>}</td>
                      {["Bramka", "Obrona", "Pomoc", "Atak"].map((k) => (
                        <td key={k} style={{ textAlign: "center", padding: "11px 14px" }}>
                          {l.base ? <span style={{ color: C.dim }}>—</span> : (
                            <span><span className="mono" style={{ color: C.proxy, fontWeight: 700 }}>+{l[k]}%</span>
                            <span style={{ fontSize: 10, color: C.dim }}> RC+{pctToRC(l[k])}</span></span>)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {tab === "corr" && (
          <div>
            <SectionTitle n="04" t="Powtarzalność zależności w formacji"
              s="Macierz korelacji między pozycjami — jak silnie współzależą w obrębie układu." />
            <div style={{ overflowX: "auto" }}>
              <table style={{ borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr><th style={{ padding: 8 }}></th>
                    {POSREL.map((p) => <th key={p} className="mono" style={{ padding: 8, color: C.dim, fontWeight: 700 }}>{p}</th>)}</tr>
                </thead>
                <tbody>
                  {POSREL.map((a) => (
                    <tr key={a}>
                      <td className="mono" style={{ padding: 8, color: C.dim, fontWeight: 700 }}>{a}</td>
                      {POSREL.map((b) => {
                        const v = corrOf(a, b);
                        return (
                          <td key={b} title={`${a}↔${b}: ${v.toFixed(2)}`} className="mono"
                            style={{ width: 52, height: 44, textAlign: "center",
                              background: a === b ? C.panel2 : `rgba(200,16,46,${0.12 + v * 0.78})`,
                              color: v > 0.55 ? "#fff" : C.ink, fontWeight: 600, border: `1px solid ${C.bg}` }}>
                            {v.toFixed(2)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ display: "flex", gap: 18, marginTop: 16, flexWrap: "wrap" }}>
              <Insight t="Najsilniejsza para" v="AM ↔ ST · 0.81" d="Ofensywny pomocnik i napastnik — rdzeń powtarzalnej zależności ataku." />
              <Insight t="Spójność osi środka" v="DM–CM–AM" d="Łańcuch 0.72 → 0.78 sugeruje stabilny kręgosłup formacji." />
              <Insight t="Słaby link" v="RWB ↔ ST · 0.29" d="Skrzydło i napastnik słabo skorelowane w tym układzie." />
            </div>
          </div>
        )}
      </main>

      <footer style={{ marginTop: 40, padding: "18px 32px", borderTop: `1px solid ${C.line}`,
        color: C.dim, fontSize: 11.5, maxWidth: 1100 }}>
        Prototyp koncepcyjny. Realne: rdzeń składu i pozycje. Liczby (RC, handicapy, korelacje) — proxy
        do walidacji logiki modelu. Tryb live podpina realne metryki z FBref przez funkcję serverless.
      </footer>
    </div>
  );
}

function Centered({ children }) {
  return (
    <div style={{ minHeight: "100vh", background: C.bg, color: C.dim, display: "flex",
      alignItems: "center", justifyContent: "center", fontFamily: "system-ui",
      fontSize: 14, padding: 24, textAlign: "center" }}>{children}</div>
  );
}

function MiniStat({ label, value, color }) {
  return (
    <div style={{ background: "#161E1B", border: "1px solid #2A3A34", borderRadius: 10,
      padding: "9px 14px", minWidth: 100 }}>
      <div style={{ fontSize: 10, color: "#8FA39B", textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <div className="mono" style={{ fontSize: 16, fontWeight: 700, color: color || "#E8EDE9", marginTop: 2 }}>{value}</div>
    </div>
  );
}

function SectionTitle({ n, t, s }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <span className="mono" style={{ fontSize: 13, color: C.red, fontWeight: 700 }}>{n}</span>
        <h2 className="mono" style={{ margin: 0, fontSize: 19, fontWeight: 700 }}>{t}</h2>
      </div>
      <p style={{ margin: "6px 0 0 25px", color: C.dim, fontSize: 13 }}>{s}</p>
    </div>
  );
}

function Insight({ t, v, d }) {
  return (
    <div style={{ flex: "1 1 220px", background: C.panel, border: `1px solid ${C.line}`, borderRadius: 10, padding: "13px 15px" }}>
      <div style={{ fontSize: 11, color: C.dim, textTransform: "uppercase", letterSpacing: 0.6 }}>{t}</div>
      <div className="mono" style={{ fontSize: 16, fontWeight: 700, color: C.redSoft, margin: "4px 0 6px" }}>{v}</div>
      <div style={{ fontSize: 12, color: C.dim, lineHeight: 1.45 }}>{d}</div>
    </div>
  );
}
