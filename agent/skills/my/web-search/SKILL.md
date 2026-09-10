---
name: web-search
description: Web search and content extraction via lightpanda, lightweight headless browser. Use for searching documentation, facts, or any web content.
---

# Lightpanda Web Search

Web search via [lightpanda](https://github.com/Kilian/lightpanda), a lightweight headless browser. This skill adapts [searx](https://github.com/searx/searx) tricks to lightpanda: direct SERP URLs, pre-seeded consent/anti-bot cookies, session persistence via cookie jars, UA suffixes, captcha detection with fail-fast, and rate-limit awareness.

> **Engine availability changes constantly.** Verified 2026-08-04 (residential IP): Brave, Bing, Marginalia work in lightpanda; **DuckDuckGo works via a real browser session** (see DDG section — lightpanda is blocked by DDG's Anomaly wall); Google, Startpage, Ecosia, Mojeek, Qwant, Yep are blocked. Re-test before relying on any engine, and prefer fetching the target site directly when you already know the URL.

## Quick Start

```bash
# Bing (most robust; parse --dump html for real URLs)
lightpanda fetch --dump html --wait-selector 'li.b_algo' --wait-ms 15000 \
  "https://www.bing.com/search?q=<QUERY>&count=10"

# Brave (warm session first, keep cookie jar)
lightpanda fetch --cookie-jar ./brave.cookies.json "https://search.brave.com/"
lightpanda fetch --dump markdown --cookie ./brave.cookies.json --cookie-jar ./brave.cookies.json \
  --wait-selector 'div.snippet' --wait-ms 15000 \
  "https://search.brave.com/search?q=<QUERY>&source=web"

# DuckDuckGo (requires headed Chromium — lightpanda is blocked)
./ddg-search.sh "<QUERY>"
```

## Engines

### Bing
- Results in `<li class="b_algo">` (h2 > a). Use `--dump html`.
- Result hrefs are `u=a1<base64>` redirects — decode with:
  ```python
  import base64, re
  href = re.search(r'[?&]u=(a1[^&]*)', href).group(1)
  print(base64.urlsafe_b64decode(href[2:] + '=' * (-len(href[2:]) % 4)).decode())
  ```
- Pagination: `&first=11`, `&first=21`, …
- Region cookie: `_EDGE_S=mkt=xx-XX&F=1`

### Brave
- Warm session first: `lightpanda fetch --cookie-jar ./brave.cookies.json "https://search.brave.com/"`
- Selectors: `div.snippet`, `.title.search-snippet-title`, `.snippet-url`
- **Fragile under load:** intermittent timeouts after ~20 queries, hard HTTP 429 after ~60–80. Space queries 2–5s, use cookie jar, or switch to Bing.
- Captcha detection: content contains "Verifying you're not a bot" → stop, switch engines.

### Marginalia
- Bot-friendly fallback. Clean HTML, no JS, no captcha, no rate limit.
- Index is small — ~half of realistic queries return zero organic results. Best for mainstream/tech queries.

### DuckDuckGo
- Lightpanda is blocked (HTTP 202, fingerprint-based Anomaly captcha, zero cookies).
- Use `ddg-search.sh` which drives a headed Chromium on `:9222`. The user solves the captcha by hand if it appears.
- Endpoint: `https://lite.duckduckgo.com/lite/?q=…` — server-rendered HTML, results in `a.result-link` rows.
- **Note:** `ddg-search.sh` hardcodes the browser-tools path at `/home/dimchee/.pi/agent/skills/pi-skills/browser-tools`. Adjust if your setup differs.

### SearXNG instances
- `https://<instance>/search?q=<QUERY>` — most public instances block non-browser traffic or disable `format=json`. Test once before building a workflow.

## Blocked Engines — Detect & Fail Fast

| Engine | Block | Detection |
|---|---|---|
| Google | 429 → `/sorry` | http_status 429, URL contains `/sorry` |
| DuckDuckGo (lightpanda) | Anomaly captcha | HTTP 202, "Select all squares" — use `ddg-search.sh` |
| Startpage | Anubis JS PoW | "Verifying your request… Calculating…" |
| Ecosia | Cloudflare Turnstile | 403, "Confirm you're not a robot" |
| Mojeek | ALTCHA | "Verification required … challenge" |
| Qwant | empty SPA | 200 but zero content |
| Yep | hard 403 | "403_yepus2" |

Detect with `--json`:
```bash
lightpanda fetch --json --wait-ms 10000 "<url>" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["http_status"], d["url"])'
```

On detection: stop, switch engines, or sleep — never hammer a challenged engine.

## Recovery Strategy

1. **Check `http_status`** — 429/403/202 with no content → blocked.
2. **Switch engines** — Bing is the most reliable fallback; Marginalia is the most permissive.
3. **Warm the session** — fetch the engine homepage with `--cookie-jar` before retrying.
4. **Space queries** — add `sleep 3` between retries.
5. **Try the target site directly** — if you know the URL, fetch it instead of searching.

## lightpanda Options

| Flag | Values | Default | Description |
|---|---|---|---|
| `--dump` | `html`, `markdown`, `semantic_tree`, `semantic_tree_text` | `markdown` | Output format |
| `--wait-until` | `load`, `domcontentloaded`, `networkidle`, `done` | `done` | Wait strategy |
| `--wait-ms` | milliseconds | `5000` | Max wait time |
| `--strip-mode` | `js`, `css`, `ui`, `invisible`, `full` (comma-separated) | — | Remove tag groups from output |
| `--with-frames` | — | — | Include iframe contents in the dump |
| `--obey-robots` | — | — | Fetch and obey robots.txt |
| `--json` | — | — | Output http_status, final URL, headers, content |
| `--http-cache-dir` | `<dir>` | — | Reuse resources across fetches |
| `--user-agent-suffix` | `<id>` | — | Identify requests (lightpanda refuses UAs containing "Mozilla") |

## Important Notes

- **Search engines block/rate-limit lightpanda aggressively** (browser fingerprinting). Brave works for a handful of queries, then returns a PoW "Verifying you're not a bot" CAPTCHA that lightpanda cannot solve. Mojeek (ALTCHA), Ecosia (Cloudflare), Startpage (Anubis) and SearXNG instances are also blocked. Treat search-engine scraping as unreliable; prefer fetching the target site directly instead.
- **Direct content extraction from target sites works well**, often without login. Example (Facebook groups return title + member count unauthenticated):
  ```bash
  lightpanda fetch --dump markdown \
    "https://www.facebook.com/groups/<slug>/" \
    --wait-ms 15000 --wait-until networkidle
  # -> "# Studenti beogradskih univerziteta - SBU", "44.7K members"
  ```
- **JS-heavy sites** (e.g. Facebook) need `--wait-ms >= 10000` plus `--wait-until networkidle`; the defaults (5s, `done`) often return empty or partial content. Pages can render inconsistently between fetches — retry once before trusting an empty result.
- **Sites like Facebook rate-limit anonymous scraping:** after ~15–20 rapid requests every page returns a login wall. Space requests (2–5s), batch fetches, and detect blocked responses (e.g. grep for "Log into Facebook" or "Verifying you're not a bot") so you can pause/retry.
- **Lightpanda is under heavy development** and may have occasional issues.

## Agent Mode

`lightpanda agent` drives a real page with an LLM or a recorded script: `goto`, `click`, `fill`, `press`, `selectOption`, `waitForSelector`, `evaluate`, `extract`, `detectForms`, …

```bash
lightpanda agent --task "search for '<q>' on search.brave.com and list the top 5 result URLs"
lightpanda agent --no-llm     # manual REPL; /save exports a replayable .js script
```

Needs an LLM provider key or `--no-llm`. Cannot solve image captchas — DDG's Anomaly wall will stop it.

## Worked Example: Search & Extract

```bash
# 1. Search Bing for Rust docs
lightpanda fetch --dump html --wait-selector 'li.b_algo' --wait-ms 15000 \
  "https://www.bing.com/search?q=rust+programming+language+docs&count=10"

# 2. Extract the first result URL, decode the u=a1 base64 redirect

# 3. Fetch the target page directly
lightpanda fetch --dump markdown --wait-until networkidle \
  "https://doc.rust-lang.org/book/"
```

## Reference

For detailed SearX-style tricks (cookie format, proxy rotation, WebBotAuth, pagination, cache), load test results, and verification criteria, see [SEARCH-REFERENCE.md](./SEARCH-REFERENCE.md).
