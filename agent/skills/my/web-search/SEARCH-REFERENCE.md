# Web Search — Detailed Reference

Supplementary technical details for the lightpanda web search skill. See [SKILL.md](./SKILL.md) for the essential usage guide.

---

## SearX-Style Tricks

### Cookie & Session Management

**Pre-seed consent / anti-bot cookies** (`--cookie`)

Searx sets cookies per engine (`CONSENT=PENDING+<rand>` for Google, `SRCHHPGUSR` for Bing, `kl` region for DDG). Lightpanda loads cookies from a JSON file in the **CDP Network.Cookie format** (same as Puppeteer/Playwright):

```json
[
  {"name": "CONSENT", "value": "PENDING+0.37", "domain": ".google.com", "path": "/", "secure": false, "httpOnly": false}
]
```

`name`, `value`, `domain`, `path` required; `expires` (float), `secure`, `httpOnly`, `sameSite` optional. Read-only load: `--cookie <file>`. Session persistence: `--cookie-jar <file>` (writes all session cookies on exit).

**Warm up the homepage before querying**

Searx scrapes tokens/cookies from an engine's homepage (e.g. Startpage's `sc` timestamp) before searching. With lightpanda: `--cookie-jar` a fetch of the engine homepage first, then reuse the jar for queries (verified with Brave — seeds its captcha token cookies).

### Detection & Rate Limiting

**Detect captcha, fail fast, switch**

Mirror searx's `SearxEngineCaptchaException` behavior: on a challenge, stop and switch engines (or fetch the target site directly). Keep a per-session list of engines that challenged and avoid re-testing them.

**Rate limiting & spacing**

Space queries 2–5s. Rapid bursts trigger PoW/captchas (verified: Brave) and login walls (verified: Facebook after ~15–20 requests). Batch with sleeps:

```bash
for q in "query1" "query2" "query3"; do
  lightpanda fetch --dump markdown --wait-ms 10000 \
    "https://search.brave.com/search?q=$q&source=web"
  sleep 3
done
```

### Proxies & Identification

**Proxy rotation**

Searx uses pools of proxies. Lightpanda: `--http-proxy <URL>` (HTTP/SOCKS), `--proxy-bearer-token <token>` for authenticated proxies. Rotate when an engine blocks the current IP. Also `--http-max-concurrent` / `--http-max-host-open` to tune request parallelism.

**WebBotAuth — identify as a bot instead of hiding**

Lightpanda can sign requests with an Ed25519 key (`--web-bot-auth-key-file`, `--web-bot-auth-keyid`, `--web-bot-auth-domain`). For sites that support bot-identification this is a legitimate alternative to UA spoofing — the anti-blocking approach searx can't offer.

**UA suffixes**

Lightpanda **refuses any UA containing "Mozilla"** (`--user-agent` must not impersonate other browsers; the browser still sends its own Sec-Ch-Ua). So the searx UA-rotation trick is unavailable — rely on cookies, warm-up, spacing, and proxies instead. Use `--user-agent-suffix "<id>"` (mirrors searx's `useragent_suffix`) only to identify your requests. Engines that hard-fingerprint the UA will block lightpanda; skip them.

### Pagination, Cache & Noise Reduction

**Pagination & filters**

- Bing: `&first=<1 + 10*(page-1)>` (verified)
- Google-style recency `tbs=qdr:d|w|m|y` and DDG `df=` (searx time-range params; relevant if those engines ever open up)
- Brave pagination is JS-driven — use page 1 or the agent mode to click "next"

**Cache & strip noise**

- `--http-cache-dir <dir>` — reuse resources across fetches (fewer requests → fewer blocks)
- `--strip-mode js,css,ui` — smaller dumps (values: `js`, `css`, `ui`, `invisible`, `full`)
- `--wait-selector <sel>` — dump only once results render (Brave `div.snippet`, Bing `li.b_algo`)

**`--json` flag** — gives http_status, final URL, headers, content. Useful for debugging blocks and verifying results:

```bash
lightpanda fetch --json --wait-ms 10000 "<url>"
```

---

## Load Test (200 requests, 2026-08-04)

Ran 200 real searches through the skill's recipes — Brave 80, Bing 80, Marginalia 40, in parallel per-engine pools, with homepage cookie-jar warm-up, 2–4s spacing per engine, `--wait-selector`, and `--json` + marker detection.

| Engine | Req | OK | Failures | Median/req | Results per query |
|---|---|---|---|---|---|
| Bing | 80 | 80 (100%) | 0 | 0.6s | 9-10 results |
| Marginalia | 40 | 40 (100%) | 0 | ~6s (wait cap) | 80-107 links on ~half; 0-3 on niche |
| Brave | 80 | 67 (84%) | 13 timeouts, then hard 429 | 0.8s | 40-88 links |
| **Total** | **200** | **187 (93.5%)** | 13 | | |

**Findings:**
- **No challenge pages were served during the test** — blocks were connection-level (8s wait-cap timeouts with no output, then HTTP 429). The PoW/Anubis/ALTCHA/Anomaly/Turnstile walls appear only on engines that block lightpanda outright (Google, DDG, Startpage, Ecosia, Mojeek).
- **Bing is the workhorse for volume:** 100% at 0.6s/req, still healthy (200, 10 results) immediately after the test. Use `--dump html` + `b_algo` parse + `u=a1` base64 URL decode.
- **Brave is fragile under load:** first ~20 requests flawless, then intermittent exactly-at-wait-cap failures from ~#21, hard 429 after ~6 min / ~80 requests. Cookie jar works (seeds `sku#brave-search-captcha` tokens) but does not prevent the ceiling.
- **Session persistence validated:** jars grew real session cookies (Bing: MUID, `_EDGE_S`, SRCHD; Brave: captcha tokens; Marginalia: `sst-SE`).
- **Marginalia:** 100% uptime but ~half the queries returned no organic results (footer links only) — small index, prefer mainstream queries.

Replay: `python3 tmp/loadtest.py` (logs every request to `tmp/loadtest.jsonl`).

---

## Verification

A "working" engine means: http_status 200, final URL stays on the engine's domain (not a challenge domain like `/sorry`, `challenges.cloudflare.com`), and content contains real result markers (Brave `div.snippet` or links to non-engine domains; Bing `b_algo` count > 0; Marginalia result list). Treat anything else as blocked.
