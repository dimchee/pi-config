"""Camoufox agent server: DuckDuckGo search + general browsing API.

Owns a dynamic pool of Camoufox browser instances (headless="virtual") and
serves a small local HTTP API for agents.

Search (markdown output):
    GET  /search?q=<query>&n=<max>[&timeout_ms=&retries=&engine=lite|html][&next=<token>]

Browsing sessions (pin an instance for multi-step flows):
    POST   /session                  -> {sid}
    GET    /sessions                 -> active sessions with url/age
    DELETE /session?sid=
    POST   /release                  -> force-close ALL sessions (pool stuck)

Fixed actions (JSON "sid" / ?sid=; omit sid = throwaway page):
    POST /goto   {url, sid?, timeout_ms?} -> {title, url, status}  # status = HTTP code
    GET  /text   ?sid= | ?url=[&selector=]  -> readable page text
    GET  /html   ?sid= | ?url=              -> raw HTML
    POST /click  {selector, sid?}
    POST /fill   {selector, text, sid?}
    POST /key    {key, sid?}         e.g. "Enter"
    POST /eval   {js, sid?}          JS evaluated in page
    POST /shot   {path, sid?, full_page?}
    POST /wait   {selector, timeout_ms?, sid?}

Full Playwright API escape hatch:
    POST /exec   {code, sid?}        code runs as `async def` with `page`,
                                     `context`, `browser` injected; set a
                                     `result` variable; print() captured.

Run:  python -m camoufox_tool.server [--host H] [--port P] [--pages N]
"""

import argparse
import asyncio
import contextlib
import io
import json
import os
import signal
import sys
import time
import traceback
import urllib.parse
import uuid

from camoufox_tool.browser import redirect_home, spawn_browser
from camoufox_tool.config import Config
from camoufox_tool.ddg import (
    DDG_LITE,
    ENGINES,
    EXTRACT_JS,
    build_markdown,
    decode_token,
    encode_token,
    extract_js_for,
    filter_results,
)
from camoufox_tool.errors import RateLimited, ToolError, error_payload
from camoufox_tool.pool import BrowserPool


def build_exec_src(code: str) -> str:
    """Wrap agent code into an async function that returns its locals."""
    body = "\n".join("    " + line for line in code.splitlines()) or "    pass"
    return (
        "async def __agent_main__():\n"
        + body
        + "\n    return {k: v for k, v in locals().items() if not k.startswith('__')}"
    )


class SearchServer:
    """Request handlers + session management on top of the pool."""

    def __init__(self, config: Config, pool: BrowserPool | None = None):
        self.cfg = config
        self.pool = pool or BrowserPool(config.max_pages, spawn_browser)
        self.sessions: dict[str, dict] = {}
        self._last_ddg_hit = 0.0  # monotonic clock, for search min-interval
        self.debug = bool(os.environ.get("CAMOUFOX_DEBUG"))

    async def _athrottle_ddg(self):
        interval = self.cfg.search_min_interval
        if interval > 0:
            wait = self._last_ddg_hit + interval - time.monotonic()
            if wait > 0:
                print(f"[search] rate-limit guard: sleeping {wait:.1f}s", file=sys.stderr)
                await asyncio.sleep(wait)
        self._last_ddg_hit = time.monotonic()

    async def start(self):
        # Warm exactly one instance so the common case skips cold-start.
        entry = await self.pool.acquire()
        await self.pool.release(entry)

    async def stop(self):
        for sid in list(self.sessions):
            with contextlib.suppress(KeyError):
                await self.close_session(sid)
        await self.pool.stop()

    # ---- sessions ----

    async def new_session(self) -> dict:
        entry = context = page = None
        err: Exception | None = None
        for attempt in (1, 2):
            entry = await self.pool.acquire()
            try:
                context = await asyncio.wait_for(entry["browser"].new_context(), timeout=60)
                page = await asyncio.wait_for(context.new_page(), timeout=60)
                break
            except Exception as exc:
                if context is not None:
                    with contextlib.suppress(Exception):
                        await context.close()
                context = page = None
                await self.pool.close(entry)
                err = exc
        if page is None or entry is None:
            raise RuntimeError(f"could not create session: {err}")
        sid = uuid.uuid4().hex[:12]
        self.sessions[sid] = {
            "sid": sid,
            "entry": entry,
            "context": context,
            "page": page,
            "created": time.time(),
            "last_used": time.time(),
        }
        return {"sid": sid}

    async def list_sessions(self) -> dict:
        """Detailed listing so agents can identify stale sessions (P4)."""
        now = time.time()
        out = []
        for sid, s in sorted(self.sessions.items()):
            info = {
                "sid": sid,
                "url": s["page"].url,
                "age_s": int(now - s["created"]),
                "idle_s": int(now - s["last_used"]),
            }
            with contextlib.suppress(Exception):
                info["title"] = await asyncio.wait_for(s["page"].title(), timeout=2)
            out.append(info)
        return {"sessions": out}

    async def release_all(self, except_sid: str | None = None) -> dict:
        """Force-close every session (pool diagnostics escape hatch, P11)."""
        closed = []
        for sid in list(self.sessions):
            if sid == except_sid:
                continue
            with contextlib.suppress(KeyError):
                await self.close_session(sid)
            closed.append(sid)
        return {"closed": closed}

    def _get_session(self, sid: str | None) -> dict | None:
        if not sid:
            return None
        s = self.sessions.get(sid)
        if not s:
            raise KeyError(f"unknown session {sid}")
        s["last_used"] = time.time()
        return s

    async def close_session(self, sid: str) -> dict:
        s = self.sessions.pop(sid, None)
        if not s:
            raise KeyError(f"unknown session {sid}")
        try:
            await s["context"].close()
        except Exception:
            pass
        await self.pool.release(s["entry"])
        return {"closed": sid}

    @staticmethod
    def _is_closed_error(exc: Exception) -> bool:
        txt = f"{type(exc).__name__}: {exc}"
        return "TargetClosed" in txt or "browser has been closed" in txt

    async def _drop_dead_session(self, sid: str):
        """Remove a session whose browser died; discard (not reuse) its slot."""
        s = self.sessions.pop(sid, None)
        if not s:
            return
        with contextlib.suppress(Exception):
            await s["context"].close()
        await self.pool.close(s["entry"])
        raise KeyError(f"session {sid}: its browser crashed; create a new session")

    async def _call(self, sid: str | None, fn) -> dict:
        """Run fn(page, context) in a session's page or on a throwaway page."""
        s = self._get_session(sid)
        if s:
            try:
                return await fn(s["page"], s["context"])
            except Exception as exc:
                if self._is_closed_error(exc):
                    await self._drop_dead_session(sid)
                raise
            finally:
                s["last_used"] = time.time()
        return await self.pool.run(fn)

    # ---- fixed actions ----

    async def goto(self, sid: str | None, url: str, timeout_ms: int | None = None) -> dict:
        timeout = timeout_ms or int(self.cfg.goto_timeout * 1000)

        async def fn(page, _ctx):
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            status = resp.status if resp else None
            return {"title": await page.title(), "url": page.url, "status": status}

        return await self._call(sid, fn)

    @staticmethod
    def _extract_text_js(selector: str | None) -> str:
        sel = json.dumps(selector)
        return (
            "(() => { const el = "
            + sel
            + " ? document.querySelector(" + sel + ") : document.body;"
            + " return el ? el.innerText : ''; })()"
        )

    async def text(self, sid: str | None, url: str | None = None,
                   selector: str | None = None,
                   timeout_ms: int | None = None) -> dict:
        js = self._extract_text_js(selector)
        if not sid and url:
            # One-off fetch of a URL without a session (ticket P2a).
            async def fetch(page, _ctx):
                resp = await page.goto(
                    url, wait_until="domcontentloaded",
                    timeout=timeout_ms or int(self.cfg.goto_timeout * 1000),
                )
                return {
                    "text": await page.evaluate(js),
                    "url": page.url,
                    "status": resp.status if resp else None,
                }
            return await self.pool.run(fetch)

        async def fn(page, _ctx):
            return {"text": await page.evaluate(js)}
        return await self._call(sid, fn)

    async def html(self, sid: str | None, url: str | None = None,
                   timeout_ms: int | None = None) -> dict:
        if not sid and url:
            async def fetch(page, _ctx):
                await page.goto(
                    url, wait_until="domcontentloaded",
                    timeout=timeout_ms or int(self.cfg.goto_timeout * 1000),
                )
                return {"html": await page.content(), "url": page.url}
            return await self.pool.run(fetch)

        async def fn(page, _ctx):
            return {"html": await page.content()}
        return await self._call(sid, fn)

    async def click(self, sid: str | None, selector: str) -> dict:
        async def fn(page, _ctx):
            await page.click(selector, timeout=15000)
            return {"clicked": selector}
        return await self._call(sid, fn)

    async def fill(self, sid: str | None, selector: str, text: str) -> dict:
        async def fn(page, _ctx):
            await page.fill(selector, text, timeout=15000)
            return {"filled": selector}
        return await self._call(sid, fn)

    async def key(self, sid: str | None, key: str) -> dict:
        async def fn(page, _ctx):
            await page.keyboard.press(key)
            return {"pressed": key}
        return await self._call(sid, fn)

    async def evaluate(self, sid: str | None, js: str) -> dict:
        async def fn(page, _ctx):
            return {"result": repr(await page.evaluate(js))}
        return await self._call(sid, fn)

    async def screenshot(self, sid: str | None, path: str, full_page: bool) -> dict:
        async def fn(page, _ctx):
            await page.screenshot(path=path, full_page=full_page, timeout=30000)
            return {"path": str(path)}
        return await self._call(sid, fn)

    async def wait_for(self, sid: str | None, selector: str, timeout_ms: int) -> dict:
        async def fn(page, _ctx):
            await page.wait_for_selector(selector, timeout=timeout_ms)
            return {"found": selector}
        return await self._call(sid, fn)

    async def exec_code(self, sid: str | None, code: str) -> dict:
        async def fn(page, context):
            buf = io.StringIO()
            glb = {
                "page": page,
                "context": context,
                "browser": context.browser,
                "asyncio": asyncio,
                "sys": sys,
                "json": json,
                "__name__": "__agent__",
            }
            src = build_exec_src(code)
            exec(compile(src, "<agent-code>", "exec"), glb)  # noqa: S102 - local tool
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                local_vars = await asyncio.wait_for(
                    glb["__agent_main__"](), timeout=self.cfg.exec_timeout
                )
            return {
                "sid": sid,
                "result": repr(local_vars.get("result")),
                "logs": buf.getvalue(),
            }
        return await self._call(sid, fn)

    # ---- duckduckgo search ----

    async def _ddg_extract(self, page, engine: str = "lite") -> tuple[list, dict | None]:
        data = await page.evaluate(extract_js_for(engine))
        return filter_results(data["results"]), data["nextForm"]

    @staticmethod
    async def _detect_anomaly(page) -> bool:
        # Organic results present -> not an anti-bot page (snippets may
        # legitimately contain words like "captcha").
        if await page.query_selector("a.result-link"):
            return False
        low = (await page.content()).lower()
        return "anomaly" in low or "captcha" in low

    async def _ddg_attempt(self, engine: str, query: str, timeout_ms: int):
        """One search attempt against one engine. Raises on failure."""
        url = f"{ENGINES[engine]}?{urllib.parse.urlencode({'q': query})}"

        async def fn(page, _ctx):
            await page.goto(url, wait_until="domcontentloaded")
            # state='attached' (not 'visible'): DDG sometimes renders results
            # in a layout table whose first match never becomes visible, which
            # used to guarantee a 30s timeout even though parsing works (P1/P8).
            await page.wait_for_selector(
                "a.result-link, p.info, a.result__a, table",
                state="attached", timeout=timeout_ms,
            )
            if await self._detect_anomaly(page):
                raise RateLimited()
            return await self._ddg_extract(page, engine)

        return await self.pool.run(fn)

    async def search(self, query: str, max_results: int,
                     retries: int | None = None, timeout_ms: int | None = None,
                     engine: str | None = None) -> dict:
        timeout = timeout_ms or int(self.cfg.search_timeout * 1000)
        attempts = max(1, min(5, (self.cfg.search_retries if retries is None else retries) + 1))
        primary = engine if engine in ENGINES else "lite"
        # Engines tried in order; an explicit --engine is tried alone, while
        # the default automatically falls back to the html layout once.
        engines = [primary]
        if engine is None:
            fallback = next((k for k in ENGINES if k != primary), None)
            if fallback:
                engines.append(fallback)

        last_exc: Exception | None = None
        for i, eng in enumerate(engines):
            for attempt in range(attempts):
                await self._athrottle_ddg()
                try:
                    results, next_form = await self._ddg_attempt(eng, query, timeout)
                    token = encode_token(eng, next_form)
                    trimmed = results[:max_results]
                    return {
                        "results": trimmed,
                        "engine": eng,
                        "next_token": token,
                        "markdown": build_markdown(query, trimmed, token),
                    }
                except Exception as exc:
                    last_exc = exc
                    tb = traceback.format_exc()
                    print(f"[search] attempt {attempt + 1}/{attempts} on {eng} failed:"
                          f" {type(exc).__name__}: {exc}\n{tb}", file=sys.stderr)
                    if attempt < attempts - 1:
                        await asyncio.sleep(min(30, 2 ** (2 * attempt + 1)))  # 2s, 8s
        raise last_exc  # mapped to a typed payload by handle_request

    async def more(self, token: str, max_results: int) -> dict:
        engine, next_form = decode_token(token)

        async def fn(page, context):
            await self._athrottle_ddg()
            resp = await context.request.post(ENGINES[engine], form=next_form)
            html = await resp.text()
            # Load into the request's page so we can reuse the same DOM extraction.
            await page.set_content(html)
            if await self._detect_anomaly(page):
                raise RateLimited()
            return await self._ddg_extract(page, engine)

        results, next_form2 = await self.pool.run(fn)
        token2 = encode_token(engine, next_form2)
        trimmed = results[:max_results]
        return {
            "results": trimmed,
            "engine": engine,
            "next_token": token2,
            "markdown": build_markdown(next_form.get("q"), trimmed, token2),
        }

    # ---- maintenance ----

    async def reap_loop(self, stop_event: asyncio.Event):
        """Close expired sessions and shrink the pool when idle."""
        while True:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=15)
                return
            except asyncio.TimeoutError:
                pass
            try:
                await self.reap_once()
            except Exception:
                pass

    async def reap_once(self):
        now = time.time()
        for sid, s in list(self.sessions.items()):
            if now - s["last_used"] > self.cfg.session_idle:
                with contextlib.suppress(Exception, KeyError):
                    await self.close_session(sid)
        await self.pool.shrink(self.cfg.instance_idle)


# ---- HTTP plumbing (stdlib asyncio, no deps) ----


async def handle_request(server: SearchServer, method: str, path: str,
                         query: dict, body: dict) -> tuple[int, dict]:
    route = (method, path.rstrip("/") or "/")

    def need(d: dict, *keys):
        missing = []
        out = []
        for k in keys:
            v = d.get(k)
            # parse_qs gives lists; accept both raw dicts and plain bodies
            if isinstance(v, list):
                v = v[0] if v else None
            if v in (None, ""):
                missing.append(k)
            else:
                out.append(v)
        if missing:
            raise ValueError(f"missing parameter(s): {', '.join(missing)}")
        return iter(out)

    try:
        match route:
            case ("GET", "/search"):
                n = min(int(query.get("n", [server.cfg.default_max_results])[0]), 50)
                token = query.get("next", [None])[0]
                q = query.get("q", [None])[0]
                if token:
                    return 200, await server.more(token, n)
                if q:
                    retries = query.get("retries", [None])[0]
                    timeout_ms = query.get("timeout_ms", [None])[0]
                    return 200, await server.search(
                        q.strip(), n,
                        retries=int(retries) if retries is not None else None,
                        timeout_ms=int(timeout_ms) if timeout_ms is not None else None,
                        engine=query.get("engine", [None])[0],
                    )
                return 400, {"error": "missing 'q' (or 'next') parameter"}

            case ("POST", "/session"):
                return 200, await server.new_session()
            case ("GET", "/sessions"):
                return 200, await server.list_sessions()
            case ("DELETE", "/session"):
                (sid,) = need(query, "sid")
                return 200, await server.close_session(sid)
            case ("POST", "/release"):
                return 200, await server.release_all(body.get("except_sid"))

            case ("POST", "/goto"):
                (url,) = need(body, "url")
                timeout_ms = body.get("timeout_ms")
                return 200, await server.goto(
                    body.get("sid"), url,
                    timeout_ms=int(timeout_ms) if timeout_ms else None,
                )
            case ("GET", "/text"):
                return 200, await server.text(
                    query.get("sid", [None])[0],
                    url=query.get("url", [None])[0],
                    selector=query.get("selector", [None])[0],
                    timeout_ms=int(t) if (t := query.get("timeout_ms", [None])[0]) else None,
                )
            case ("GET", "/html"):
                return 200, await server.html(
                    query.get("sid", [None])[0],
                    url=query.get("url", [None])[0],
                    timeout_ms=int(t) if (t := query.get("timeout_ms", [None])[0]) else None,
                )
            case ("POST", "/click"):
                (sel,) = need(body, "selector")
                return 200, await server.click(body.get("sid"), sel)
            case ("POST", "/fill"):
                (sel, txt) = need(body, "selector", "text")
                return 200, await server.fill(body.get("sid"), sel, txt)
            case ("POST", "/key"):
                (key,) = need(body, "key")
                return 200, await server.key(body.get("sid"), key)
            case ("POST", "/eval"):
                (js,) = need(body, "js")
                return 200, await server.evaluate(body.get("sid"), js)
            case ("POST", "/shot"):
                path = body.get("path") or f"tmp/screenshot-{int(time.time())}.png"
                return 200, await server.screenshot(
                    body.get("sid"), path, bool(body.get("full_page"))
                )
            case ("POST", "/wait"):
                (sel,) = need(body, "selector")
                return 200, await server.wait_for(
                    body.get("sid"), sel, int(body.get("timeout_ms", 15000))
                )
            case ("POST", "/exec"):
                (code,) = need(body, "code")
                return 200, await server.exec_code(body.get("sid"), code)

    except Exception as exc:  # noqa: BLE001 - mapped below
        # Full tracebacks stay server-side (they land in server.log via
        # stderr); clients get short structured errors (tickets P3/P10).
        if not isinstance(exc, ToolError):
            print(f"[error] {method} {path} failed:\n{traceback.format_exc()}",
                  file=sys.stderr)
        return error_payload(exc, debug=server.debug)

    return 404, {"error": f"no route {method} {path}"}


STATUS_TEXT = {200: "OK", 400: "Bad Request", 404: "Not Found",
               405: "Method Not Allowed", 500: "Internal Server Error"}


async def handle_client(server: SearchServer, reader: asyncio.StreamReader,
                        writer: asyncio.StreamWriter):
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=30)
        if not request_line:
            return
        parts = request_line.decode("latin-1").split()
        if len(parts) < 3:
            return
        method, target = parts[0], parts[1]

        content_length = 0
        while True:
            header_line = await reader.readline()
            if header_line in (b"\r\n", b"\n", b""):
                break
            name, _, value = header_line.decode("latin-1").partition(":")
            if name.strip().lower() == "content-length":
                content_length = int(value.strip())

        raw_body = await reader.readexactly(content_length) if content_length else b""
        body: dict = {}
        if raw_body:
            try:
                body = json.loads(raw_body)
            except json.JSONDecodeError:
                writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return

        parsed = urllib.parse.urlparse(target)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        status, payload = await handle_request(server, method, parsed.path, query, body)

        out = json.dumps(payload).encode()
        head = (
            f"HTTP/1.1 {status} {STATUS_TEXT.get(status, 'OK')}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(out)}\r\n"
            f"Connection: close\r\n\r\n"
        )
        writer.write(head.encode() + out)
        await writer.drain()
    except (asyncio.TimeoutError, ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def main(host: str, port: int, max_pages: int):
    redirect_home()
    cfg = Config.from_env(host=host, port=port, max_pages=max_pages)
    server = SearchServer(cfg)
    print(f"[server] starting pool (max {cfg.max_pages} instance(s), warm 1)...", file=sys.stderr)
    await server.start()

    tcp = await asyncio.start_server(lambda r, w: handle_client(server, r, w), host, port)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    print(f"[server] listening on http://{host}:{port}", file=sys.stderr)
    reaper = asyncio.create_task(server.reap_loop(stop_event))
    async with tcp:
        await stop_event.wait()

    reaper.cancel()
    tcp.close()
    await tcp.wait_closed()
    print("[server] shutting down...", file=sys.stderr)
    await server.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Camoufox agent server (search + browsing)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8931)
    parser.add_argument("--pages", type=int, default=4,
                        help="max concurrent browser instances (default 4)")
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port, args.pages))
