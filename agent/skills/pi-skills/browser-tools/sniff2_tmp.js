#!/usr/bin/env node
// Load panos by ID via map_action=pano and save FULL photometa response bodies.
// Usage: node sniff2_tmp.js <panoid1> [panoid2 ...]
// Output: /home/dimchee/Wall/tmp/pm_<panoid>.txt (+ .urls.json)
import puppeteer from "puppeteer-core";
import fs from "node:fs";

const OUT = "/home/dimchee/Wall/tmp";
const ids = process.argv.slice(2);
if (!ids.length) { console.error("usage: sniff2_tmp.js <panoid...>"); process.exit(1); }

const b = await puppeteer.connect({ browserURL: "http://localhost:9222", defaultViewport: null });
const page = await b.newPage();
const saved = [];
page.on("response", async (res) => {
  try {
    const u = res.url();
    if (!u.includes("/maps/photometa/")) return;
    const txt = await res.text().catch(() => null);
    if (!txt) return;
    const fn = `${OUT}/pm_${Date.now()}_${Math.floor(Math.random() * 1e6)}.txt`;
    fs.writeFileSync(fn, `URL: ${u}\n\n${txt}`);
    saved.push(fn);
  } catch {}
});

for (const id of ids) {
  const url = `https://www.google.com/maps/@?api=1&map_action=pano&pano=${id}`;
  console.log("loading", id);
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 }).catch(e => console.log("nav err", e.message));
  await new Promise(r => setTimeout(r, 14000));
  console.log("  final:", page.url().slice(0, 120));
}
await b.disconnect();
console.log("saved:", saved.join("\n"));
