// scripts/fetch_fbref.mjs
// Build-time data fetch (Mode B). Run locally or in CI to regenerate
// public/data.json from FBref, then redeploy the static site.
//
// Usage:  node scripts/fetch_fbref.mjs
//
// RATE LIMIT: FBref allows max 10 requests/minute. Exceeding it jails your
// IP/session for up to a day. This script paces requests with a 7s gap and
// caches aggressively. Do NOT remove the delay.

import { writeFile } from "node:fs/promises";

const OUT = new URL("../public/data.json", import.meta.url);
const DELAY_MS = 7000; // ~8.5 req/min, safely under the 10/min cap
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const TARGETS = [
  // Add the FBref squad/season URLs you need. Keep the list short.
  // { name: "rakow", url: "https://fbref.com/en/squads/<id>/Rakow-Stats" },
];

async function getHtml(url) {
  const res = await fetch(url, {
    headers: { "User-Agent": "Mozilla/5.0 (scout-mvp build script)" },
  });
  if (res.status === 429) throw new Error("Rate limited (429) — odczekaj ~1h, zmniejsz częstotliwość.");
  if (!res.ok) throw new Error(`HTTP ${res.status} dla ${url}`);
  return res.text();
}

// Implement the same mapping logic as the serverless parser.
function parseFbrefToModel(htmlByName) {
  // FBref tables are often inside HTML comments — strip them first:
  //   const clean = html.replaceAll("<!--", "").replaceAll("-->", "");
  // Then extract tables (e.g. id="stats_standard"), read pos + metrics,
  // normalise to RC 0-100, build squad / leagues / pool / correlations.
  return null; // until implemented
}

async function main() {
  if (TARGETS.length === 0) {
    console.log("Brak celów w TARGETS — uzupełnij URL-e FBref. Pozostawiam snapshot bez zmian.");
    return;
  }
  const htmlByName = {};
  for (const t of TARGETS) {
    console.log("Pobieram:", t.url);
    htmlByName[t.name] = await getHtml(t.url);
    await sleep(DELAY_MS);
  }
  const model = parseFbrefToModel(htmlByName);
  if (!model) {
    console.log("Parser nie zaimplementowany — nie nadpisuję data.json.");
    return;
  }
  model.meta = { source: "fbref-build", generated: new Date().toISOString().slice(0, 10),
    note: "Dane pobrane z FBref przy buildzie." };
  await writeFile(OUT, JSON.stringify(model, null, 2));
  console.log("Zapisano public/data.json");
}

main().catch((e) => { console.error(e); process.exit(1); });
