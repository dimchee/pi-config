#!/usr/bin/env node
// Walk Street View westward with ArrowUp keypresses, recording panoids.
// Usage: node walk_tmp.js
import puppeteer from "puppeteer-core";
import fs from "node:fs";

const EAST = { pano: "5jmIqfCz3a_bV_fEkFHNaw", lat: 43.3120864, lng: 21.9073544 };
const WEST = { lng: 21.9060905, lat: 43.3121061 };
const OUT = "/home/dimchee/Wall/tmp/walk.json";

const url = `https://www.google.com/maps/@${EAST.lat},${EAST.lng},3a,75y,270h,90t/data=!3m6!1e1!3m4!1s${EAST.pano}!2e0`;
const b = await puppeteer.connect({ browserURL: "http://localhost:9222", defaultViewport: null });
const page = await b.newPage();
await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
await new Promise(r => setTimeout(r, 15000));

const seen = [];
for (let step = 0; step < 24; step++) {
  const href = page.url();
  const mPano = href.match(/!1s([A-Za-z0-9_-]{22})/);
  const mLL = href.match(/@(-?\d+\.\d+),(-?\d+\.\d+)/);
  const rec = { step, pano: mPano && mPano[1], lat: mLL && +mLL[1], lng: mLL && +mLL[2] };
  console.log(JSON.stringify(rec));
  if (rec.pano && !seen.find(s => s.pano === rec.pano)) seen.push(rec);
  fs.writeFileSync(OUT, JSON.stringify(seen, null, 1));
  if (rec.lng && rec.lng <= WEST.lng + 0.00003) { console.log("REACHED west end"); break; }
  // focus canvas and step forward
  await page.evaluate(() => {
    const c = document.querySelector("canvas");
    if (c) { c.focus(); c.click(); }
    else document.body.click();
  });
  await page.keyboard.press("ArrowUp");
  await new Promise(r => setTimeout(r, 9000));
  const href2 = page.url();
  if (href2 === href) {
    console.log("no move, trying ArrowDown once to unstick / or done");
    // try clicking any forward chevron
    const clicked = await page.evaluate(() => {
      const btns = [...document.querySelectorAll("button")];
      const fwd = btns.find(x => /forward|napred|naprijed/i.test(x.getAttribute("aria-label") || "") && x.offsetParent);
      if (fwd) { fwd.click(); return true; }
      return false;
    });
    console.log("chevron clicked:", clicked);
    await new Promise(r => setTimeout(r, 9000));
    if (page.url() === href2 && !clicked) { console.log("STUCK, stop"); break; }
  }
}
await b.disconnect();
console.log("done, unique panos:", seen.length);
