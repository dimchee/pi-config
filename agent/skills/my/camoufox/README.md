# Camoufox agent tool

Local HTTP server (`camoufox_tool/server.py`) owning a dynamic pool of stealth
[Camoufox](https://github.com/daijro/camoufox) browsers, plus a CLI
(`camoufox_tool/cli.py`) for agents:

- **Web search** via DuckDuckGo (lite layout, automatic html fallback) →
  markdown output, `--next` token chaining, server-side retries/backoff and a
  rate-limit guard between hits
- **Browsing** sessions with the common Playwright actions (goto/text/click/
  fill/key/eval/screenshot/wait), one-off URL fetches without a session, and
  typed, one-line errors (`{error, code, hint}`) with tracebacks kept in the
  server log
- **Full Playwright API** escape hatch via `cam.py run <snippet>` — code runs
  inside the server with a live `page` object

See [SKILL.md](SKILL.md) for usage. The server starts automatically on first
client call; browser state lives in `~/.local/state/camoufox-server/` (never
in `$HOME`). Run as `python -m camoufox_tool.server` / `... cli`, or via the
flake wrappers (`nix build .#default` → `result/bin/cam`).

Tests: `pytest` runs offline against local fixture pages; `RUN_LIVE=1 pytest`
additionally exercises live DuckDuckGo search.

Fully Nix-packaged: browser binaries, uBlock Origin and GeoIP data are pinned
store paths; see `flake.nix`.
