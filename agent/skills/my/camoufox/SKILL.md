---
name: camoufox
description: Web search (DuckDuckGo, markdown) and anti-bot browsing via Camoufox. Use when a page blocks plain HTTP fetches or shows captcha/anti-bot pages, for web searches, or any browsing task needing a real browser fingerprint. Exposes search plus a large part of the Playwright API.
---

# Camoufox browsing & search tool

A local server (`camoufox_tool/server.py`) owns a pool of stealth Firefox
instances (Camoufox). The client `camoufox_tool/cli.py` is the only thing you
need to call. The server **starts automatically** on first use — never manage
its lifecycle.

Everything is Nix-packaged; always invoke through nix so the right Python,
libraries and pinned browser binaries are used.

**All paths in this file are relative to the directory containing this
SKILL.md (the flake repo). Resolve them against that directory, then run all
commands from there:**

    cd <skill-dir>               # the directory this SKILL.md lives in
    nix run .#cam -- <cmd> ...

## Output discipline (safe to script)

- **stdout is pure** JSON or markdown — safe to capture/pipe.
- The nix `Git tree is dirty` warning goes to **stderr** (it appears whenever
  the repo has uncommitted changes; it is harmless and never pollutes stdout).
- Errors go to stderr as **one line**: `error: <message> [code]` plus a
  `hint:` line when there is an obvious next step (e.g. rate-limited →
  "wait 30-60s"). Exit code is 1. Add `--debug` to any command to dump the
  full structured error payload instead.
- First call builds the wrapper (~10s if cached); subsequent calls are fast.
- Shorthands below assume you are in the skill dir and use `nix run .#cam --`.

## Web search — start here

```sh
nix run .#cam -- search "linux kernel" -n 5
```

Output: markdown list of title/link/snippet, footer carries `--next TOKEN`.

Useful flags:
- `-n 3..10` — prefer small sets; large ones are slower.
- `--timeout SEC` — per-attempt result wait (default 30).
- `--retries N` — extra attempts after the first (default 2; backoff 2s/8s).
- `--engine lite|html` — force a DDG layout. By default the tool tries the
  `lite` layout and **automatically falls back to the `html` layout**, so
  transient DDG weirdness usually heals without your intervention.

Rate limiting is handled for you: the server enforces a minimum interval
(8 s) between DuckDuckGo hits and retries transient failures internally.
You no longer need manual `sleep`s between searches. If DDG still serves an
anti-bot page you get a typed error:

    error: DuckDuckGo served an anti-bot page (anomaly/captcha) [rate_limited]
    hint: wait 30-60s, then retry

To get MORE results, take the token from the footer:

```sh
nix run .#cam -- search --next <TOKEN>
```

The token remembers which engine produced it — just copy it verbatim.

## Browsing sessions

Stateful flows use a session id (SID); each SID pins one browser instance.

```sh
SKILL=<skill-dir>                     # resolve against this SKILL.md's location
mkdir -p ./tmp && SCRATCH=$PWD/tmp    # workspace scratch dir for downloads/shots
cd "$SKILL"
nix run .#cam -- open https://example.com          # prints {sid, title, url, status}
SID=$(nix run .#cam -- open https://example.com --print-sid)   # bare id form
nix run .#cam -- text --session $SID               # readable text of current page
nix run .#cam -- click "#login-button" --session $SID
nix run .#cam -- fill "input[name=q]" "query" --session $SID
nix run .#cam -- key Enter --session $SID
nix run .#cam -- shot "$SCRATCH/shot.png" --full-page --session $SID
nix run .#cam -- eval "document.querySelectorAll('a').length" --session $SID
nix run .#cam -- wait ".results" --session $SID    # default timeout 15s (--timeout-ms)
nix run .#cam -- close-session $SID                # free the instance immediately
```

One-off pages don't need a session at all:

```sh
nix run .#cam -- text https://example.com            # fetch + extract, no SID
nix run .#cam -- text https://example.com --selector main   # main content only
nix run .#cam -- html https://example.com            # raw HTML variant
```

Session management:

```sh
nix run .#cam -- sessions          # sid, url, title, age/idle seconds
nix run .#cam -- close-all         # pool stuck? force-release every session
nix run .#cam -- close-all --except $SID
```

Rules of thumb:
- `open` without `--session` creates a NEW session (one per logical task);
  its JSON contains `"status"` (HTTP code) — use `--fail-on-http-error` to
  make 404s/dead domains exit non-zero instead of returning page content.
- Always `close-session` when done; sessions idle out after 5 min anyway,
  but explicit closing frees capacity for parallel tasks.
- `open`, `text`, `html`, `shot`, `eval`, ... also handle `file://` URLs
  (handy for reviewing local HTML).

## Full Playwright API escape hatch

Anything not covered above: write a Python snippet using the real Playwright
API. `page`, `context`, `browser` (and `asyncio`) are injected; the code runs
inside an async function, so `await` works (`eval` takes plain JavaScript,
also executed in page context). Set a variable named `result` and/or use
`print()`:

```sh
# from a scratch dir under the workspace (./tmp)
cat > snippet.py <<'EOF'
result = []
for link in await page.query_selector_all("a[href]"):
    result.append(await link.get_attribute("href"))
print(f"found {len(result)} links")
EOF
cd <skill-dir>
nix run .#cam -- run "$OLDPWD/snippet.py" --session $SID
# -> {"sid": "...", "result": "[...]", "logs": "found 23 links"}
```

Snippet files are plain Python executed by the server — no extra deps needed;
write them in a workspace scratch dir (e.g. `./tmp`) and pass an **absolute
path** (relative paths resolve against your current directory, and the CLI
tells you the resolved path when a file is missing).

Useful patterns:
- Locators: `page.locator("td:has-text('price')").first.inner_text()`
- Screenshots to bytes: `await page.screenshot(path="/abs/p.png")`
- Reading tables: `await page.eval_on_selector_all("tr", "els => els.map(e => e.innerText)")`
- Timeout errors mean the selector never appeared — check the page with
  `text` before retrying blindly.

## JSON shapes (for scripting)

```jsonc
// open  -> single JSON object (sid included when a new session was created)
{"sid": "9d1a5e7bda6e", "title": "...", "url": "https://...", "status": 200}

// search -> markdown printed; full payload available as JSON:
{"results": [{"title","url","domain","snippet"}], "engine": "lite",
 "next_token": "...|null", "markdown": "..."}

// sessions
{"sessions": [{"sid", "url", "title", "age_s", "idle_s"}]}

// text/html -> {"text"| "html": "...", ...}; click/fill/key/eval/shot/wait
// echo what happened; errors are {"error", "code", "hint"?}
```

The JSON API is also directly reachable at http://127.0.0.1:8931 — see the
`camoufox_tool/server.py` docstring for all endpoints (incl. `POST /release`
to force-close all sessions).

## Limits & gotchas

- Max concurrent browsers: 4 (server `--pages`). Sessions and one-off
  commands share this pool. If commands hang: another agent may hold all
  instances — check `sessions`, close stale ones or `close-all`; the server
  log shows `[pool] all N instance(s) busy; waiting...` lines.
- Never run your own Playwright/Camoufox instance alongside: it would create
  `~/camoufox` junk dirs; the server's HOME is redirected to
  `~/.local/state/camoufox-server`.
- Server log (tracebacks land here, not on your terminal):
  `~/.local/state/camoufox-server/server.log`.
- Timeouts/retries/rate-guard are tunable via env on the server:
  `CAMOUFOX_SEARCH_TIMEOUT`, `CAMOUFOX_GOTO_TIMEOUT`,
  `CAMOUFOX_SEARCH_RETRIES`, `CAMOUFOX_SEARCH_MIN_INTERVAL`.
- Tests: run `nix develop -c pytest` from this skill's directory (offline,
  uses local fixture pages); add `RUN_LIVE=1` to also exercise live DuckDuckGo.
- Server binary (only if manual restart is ever required):
  `nix run .#camoufox-server` from the skill dir — normally never touched,
  it auto-starts on first CLI call.

## Troubleshooting

| Symptom | Meaning / fix |
|---|---|
| `error: ... [rate_limited]` | DDG anti-bot page survived retries → wait 30–60 s, retry |
| `search` returns `_No results found._` | query genuinely empty, or DDG served an odd layout → retry once; try `--engine html` |
| `[code: timeout]` on open/search | slow site → raise `--timeout` (open/search) |
| `unknown_session` | session died (browser crash) or wrong id → `sessions`, then re-open |
| Commands hang ~30s+ then fail | pool exhausted by another client → `sessions`, close stale, or `close-all` |
| HTTP 404 content returned happily | expected; pass `--fail-on-http-error` to `open` if you want exit≠0 |
