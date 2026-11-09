#!/usr/bin/env node
// Sniff Google Maps Street View network traffic for neighboring panoid tokens.
// Usage: node sniff_pano.js "<maps-pano-url>" [out.json]
import puppeteer from "puppeteer-core";
import fs from "node:fs";

const url = process.argv[2];
const outFile = process.argv[3] || "./tmp/sniff.json";
if (!url) { console.error("usage: sniff_pano.js <url> [out]"); process.exit(1); }

const b = await puppeteer.connect({ browserURL: "http://localhost:9222", defaultViewport: null });
const page = await b.newPage();
const hits = {}; // token -> {count, sampleUrls:Set, ctx}

page.on("response", async (res) => {
  try {
    const rurl = res.url();
    if (!/google\.com|ggpht|googleapis/i.test(rurl)) return;
    if (/\.(png|jpg|jpeg|gif|webp|ico|css|woff2?)(\?|$)/i.test(rurl)) return;
    const ct = res.headers()["content-type"] || "";
    if (/image|font|css/i.test(ct)) return;
    let txt = "";
    try { txt = await res.text(); } catch { return; }
    if (txt.length < 50 || txt.length > 2000000) return;
    // panoid-like tokens: 22 chars base64url (allow 20-24)
    const re = /[A-Za-z0-9_-]{22}/g;
    let m;
    const seen = new Set();
    while ((m = re.exec(txt))) {
      const tok = m[0];
      if (seen.has(tok)) continue;
      seen.add(tok);
      if (!hits[tok]) hits[tok] = { count: 0, urls: [] };
      hits[tok].count++;
      if (hits[tok].urls.length < 3) hits[tok].urls.push(rurl.slice(0, 160));
    }
  } catch {}
});

await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
await new Promise(r => setTimeout(r, 18000));
const finalUrl = page.url();
await b.disconnect();

// filter out obvious non-panoid noise (long hex, pure-alpha words)
const out = { finalUrl, tokens: {} };
for (const [tok, v] of Object.entries(hits)) {
  if (/^[0-9]+$/.test(tok)) continue;
  if (/^[A-Z_]+$/.test(tok)) continue;
  out.tokens[tok] = v;
}
fs.writeFileSync(outFile, JSON.stringify(out, null, 1));
const toks = Object.keys(out.tokens);
console.log("finalUrl:", finalUrl.slice(0, 200));
console.log("token count:", toks.length);
for (const t of toks.slice(0, 60)) console.log(t, "x" + out.tokens[t].count);
