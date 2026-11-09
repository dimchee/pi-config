#!/usr/bin/env node
// Sweep photometa/si location searches IN-PAGE (exact template + cookies).
// Usage: node sweep_tmp.js
// Reads interpolated points, fetches si for each, saves base64 bodies.
import puppeteer from "puppeteer-core";
import fs from "node:fs";

const E = { lat: 43.3120864, lng: 21.9073544 };
const W = { lat: 43.3121061, lng: 21.9060905 };
const N = 16;
const pts = [];
for (let i = 0; i < N; i++) {
  const f = i / (N - 1);
  pts.push({ lat: E.lat + (W.lat - E.lat) * f, lng: E.lng + (W.lng - E.lng) * f });
}

const b = await puppeteer.connect({ browserURL: "http://localhost:9222", defaultViewport: null });
const pages = await b.pages();
const page = pages[pages.length - 1];

const results = await page.evaluate(async (pts) => {
  const entries = performance.getEntriesByType("resource").map(r => r.name);
  const tpl = entries.find(u => u.includes("/maps/photometa/si/v1"));
  if (!tpl) return { error: "no si template found", n: entries.length };
  const out = [];
  for (const p of pts) {
    // replace first 3d<lat> and 4d<lng> occurrences
    let url = tpl.replace(/3d-?\d+(\.\d+)?/, `3d${p.lat}`).replace(/4d-?\d+(\.\d+)?/, `4d${p.lng}`);
    try {
      const r = await fetch(url);
      const buf = await r.arrayBuffer();
      const bytes = new Uint8Array(buf);
      let bin = "";
      for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
      out.push({ lat: p.lat, lng: p.lng, status: r.status, b64: btoa(bin) });
    } catch (e) { out.push({ lat: p.lat, lng: p.lng, status: -1, err: String(e) }); }
    await new Promise(r => setTimeout(r, 700));
  }
  return { template: tpl, out };
}, pts);

fs.writeFileSync("/home/dimchee/Wall/tmp/si_sweep.json", JSON.stringify(results, null, 1));
console.log("template found:", !!results.template);
for (const r of (results.out || [])) {
  const body = r.b64 ? Buffer.from(r.b64, "base64") : Buffer.alloc(0);
  const m = body.toString("latin1").match(/[A-Za-z0-9_-]{22}/g) || [];
  console.log(r.lat.toFixed(7), r.lng.toFixed(7), "st=" + r.status, "len=" + body.length, m.slice(0, 4).join(","));
}
await b.disconnect();
