#!/usr/bin/env node
// Log exact method/headers/body of photometa requests made by Maps.
import puppeteer from "puppeteer-core";
import fs from "node:fs";

const url = process.argv[2];
const b = await puppeteer.connect({ browserURL: "http://localhost:9222", defaultViewport: null });
const page = await b.newPage();
const logs = [];
// CDP session for full request detail
const cdp = await page.createCDPSession();
await cdp.send("Network.enable");
cdp.on("Network.requestWillBeSent", (e) => {
  if (e.request.url.includes("/maps/photometa/")) {
    logs.push({ url: e.request.url, method: e.request.method, headers: e.request.headers, postData: (e.request.postData || "").slice(0, 500) });
  }
});
await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
await new Promise(r => setTimeout(r, 16000));
fs.writeFileSync("/home/dimchee/Wall/tmp/pm_requests.json", JSON.stringify(logs, null, 1));
console.log("photometa requests:", logs.length);
for (const l of logs.slice(0, 6)) console.log(l.method, l.url.slice(0, 130));
await b.disconnect();
