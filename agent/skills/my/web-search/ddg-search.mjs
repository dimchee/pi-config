#!/usr/bin/env node
// DuckDuckGo search via a real (headed) Chromium session on :9222.
// DDG blocks lightpanda with its Anomaly captcha (HTTP 202, fingerprint-based,
// no cookies involved), but serves real browsers fine. This script drives the
// visible Chromium window: if the Anomaly wall appears, the user solves it by
// hand and the script waits, then extracts results.
//
// Usage: node ddg-search.mjs "<query>"
// Requires: Chromium running with --remote-debugging-port=9222
//   (see ddg-search.sh, which starts it automatically)
import puppeteer from "puppeteer-core";

const query = process.argv[2];
if (!query) {
  console.error("usage: node ddg-search.mjs \"<query>\"");
  process.exit(1);
}

const BROWSER = "http://localhost:9222";
const CAPTCHA_HINTS = ["select all squares", "unfortunately, bots use duckduckgo",
                       "anomaly", "verify your identity", "prove you're human"];
const CAPTCHA_TIMEOUT_MS = 300_000; // give the user 5 min to solve
const RESULT_TIMEOUT_MS = 20_000;

const browser = await puppeteer.connect({ browserURL: BROWSER, defaultViewport: null });

// Reuse an existing DuckDuckGo tab if there is one, otherwise open a new tab.
let page = (await browser.pages()).find(p => p.url().includes("duckduckgo.com"));
if (!page) page = await browser.newPage();

const getPage = async () => {
  // If the user closed the tab, reopen one.
  try { await page.evaluate(() => 1); return page; }
  catch { page = await browser.newPage(); return page; }
};

const url = `https://lite.duckduckgo.com/lite/?q=${encodeURIComponent(query)}`;
await page.goto(url, { waitUntil: "domcontentloaded" });

const readState = async () => {
  const p = await getPage();
  return p.evaluate(() => {
    const rows = Array.from(document.querySelectorAll("a.result-link"))
      .map(a => {
        const tr = a.closest("tr");
        return {
          title: a.textContent.trim(),
          href: a.href,
          snippet: (tr?.querySelector(".result-snippet")?.textContent ?? "").trim(),
        };
      })
      .filter(r => r.title && r.href);
    const captcha = /select all squares|unfortunately, bots use duckduckgo/i.test(document.body.innerText);
    const isError = /no results|we didn't find any results/i.test(document.body.innerText);
    return { rows, captcha, isError, title: document.title, url: location.href };
  });
};

let state = await readState();const t0 = Date.now();

// Wait for results, or for the captcha wall (then ask the user to solve it).
while (state.rows.length === 0 && !state.isError && Date.now() - t0 < RESULT_TIMEOUT_MS) {
  await new Promise(r => setTimeout(r, 1200));
  state = await readState();
}

if (state.rows.length === 0 && (state.captcha || Date.now() - t0 >= RESULT_TIMEOUT_MS)) {
  const dead = state.captcha ? CAPTCHA_TIMEOUT_MS : 5_000;
  const waitUntil = Date.now() + dead;
  if (state.captcha) {
    console.log("ANOMALY_CAPTCHA: please solve it in the Chromium window now.\n");
  } else {
    console.log("No results yet — waiting briefly.\n");
  }
  while (state.rows.length === 0 && Date.now() < waitUntil) {
    await new Promise(r => setTimeout(r, 1500));
    state = await readState();
  }
}

if (state.isError) {
  console.log(`NO_RESULTS: "${query}"`);
  process.exit(0);
}
if (state.rows.length === 0) {
  console.log(state.captcha ? "CAPTCHA_UNSOLVED" : "NO_RESULTS_TIMEOUT");
  console.log(`page: ${state.url} / ${state.title}`);
  process.exit(1);
}

// Emit markdown. DDG wraps hrefs in duckduckgo.com/l/?uddg=<urlencoded>.
const decode = h => {
  const m = h.match(/[?&]uddg=([^&]+)/);
  if (m) { try { return decodeURIComponent(m[1]); } catch { return m[1]; } }
  return h;
};
console.log(`## DuckDuckGo results: ${query}\n`);
state.rows.forEach((r, i) => {
  const u = decode(r.href);
  console.log(`${i + 1}. [${r.title}](${u})`);
  if (r.snippet) console.log(`   ${r.snippet.slice(0, 200)}`);
});
console.log(`\n<!-- ${state.rows.length} results -->`);

await browser.disconnect();
