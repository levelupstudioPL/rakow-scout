// Netlify serverless function — FBref proxy.
// Runs server-side, so it bypasses browser CORS. Respects FBref's hard limit
// (max 10 req/min — exceeding it jails the session for up to a day), so this
// fetches sparingly and is meant to be paired with caching, not hammered.
//
// IMPORTANT: This is a SKELETON. It currently returns the proxy snapshot shape
// with a parsing stub. To go fully live you must implement the HTML table
// parsing for the specific FBref pages you target (squad + per-position metrics)
// and map those metrics onto the rc / handicap / pool fields.
//
// Deploy: place in netlify/functions/. Netlify auto-exposes it at
// /.netlify/functions/fbref

const FBREF_BASE = "https://fbref.com";

// Minimal in-memory cache (per warm lambda instance). For production use a
// durable store (Netlify Blobs, KV) so the 10/min limit is never approached.
let CACHE = { at: 0, payload: null };
const TTL_MS = 1000 * 60 * 60 * 6; // 6h — well within rate limits

export async function handler(event) {
  const headers = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json; charset=utf-8",
  };

  try {
    if (CACHE.payload && Date.now() - CACHE.at < TTL_MS) {
      return { statusCode: 200, headers, body: JSON.stringify(CACHE.payload) };
    }

    // --- FBref fetch (server-side, no CORS issue) ---
    // Example target — replace with the squad/season URLs you need.
    // Keep the number of requests per invocation LOW (ideally 1).
    const url = `${FBREF_BASE}/en/squads/`; // placeholder path
    const res = await fetch(url, {
      headers: { "User-Agent": "Mozilla/5.0 (scout-mvp; contact: you@example.com)" },
    });

    if (!res.ok) {
      // 429 = you hit the rate limit / got jailed. Fall back to snapshot.
      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({
          meta: { source: "snapshot-proxy", generated: new Date().toISOString().slice(0, 10),
            note: `FBref zwrócił ${res.status}. Zwrócono snapshot. Sprawdź limit (10/min).` },
          // The client already has data.json; returning an error flag is enough,
          // but to keep the app working we signal it stays on snapshot.
          fallback: true,
        }),
      };
    }

    const html = await res.text();
    const payload = parseFbrefToModel(html); // <-- implement this

    CACHE = { at: Date.now(), payload };
    return { statusCode: 200, headers, body: JSON.stringify(payload) };
  } catch (e) {
    return {
      statusCode: 200,
      headers,
      body: JSON.stringify({ fallback: true, error: String(e) }),
    };
  }
}

// =====================================================================
// PARSING STUB — implement per your target FBref pages.
// FBref serves static HTML tables; many are inside HTML comments, so you
// often need to strip "<!--" / "-->" before parsing with a DOM/regex tool.
// Map raw metrics → rc (0-100), build leagues handicaps, build pool, etc.
// =====================================================================
function parseFbrefToModel(html) {
  // 1. Uncomment hidden tables: html.replaceAll("<!--", "").replaceAll("-->", "")
  // 2. Extract the relevant <table> (e.g. id="stats_standard").
  // 3. For each player row pull pos + the metrics that feed your RC formula.
  // 4. Normalise to 0-100, attach league, position line.
  // Until implemented, signal fallback so the app keeps the snapshot.
  return { fallback: true, meta: { source: "snapshot-proxy", note: "parser nie zaimplementowany — snapshot." } };
}
