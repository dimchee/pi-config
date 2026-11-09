"""Client for the Camoufox agent server.

One entrypoint for everything an agent needs:

    python -m camoufox_tool.cli search "query" [-n N] [--next TOKEN]
    python -m camoufox_tool.cli open URL [--session SID]   # no SID = new session
    python -m camoufox_tool.cli text [URL] [--session SID]  # either works
    ... html/click/fill/key/eval/shot/wait/run/sessions/close-session/close-all

The server is started automatically if it isn't running.

Output discipline: results go to stdout (pure JSON or markdown — safe to
parse); errors go to stderr as one-line structured messages unless --debug
is given. Nix's own warnings also go to stderr.
"""

import argparse
import importlib.util
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATE_DIR = Path.home() / ".local/state/camoufox-server"


def _connected(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def server_command() -> list[str]:
    base = [sys.executable, "-m", "camoufox_tool.server"]
    if importlib.util.find_spec("camoufox") is None:  # outside the nix dev shell
        base = ["nix", "develop", "-c", "python", "-m", "camoufox_tool.server"]
    return base


def ensure_server(host: str, port: int):
    """Start the server detached if it isn't reachable yet."""
    if host not in ("127.0.0.1", "localhost", "::1") or _connected(host, port):
        return

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = open(STATE_DIR / "server.log", "ab")
    subprocess.Popen(
        server_command(),
        cwd=str(REPO),
        stdout=log,
        stderr=log,
        start_new_session=True,
    )

    for _ in range(160):  # cold start incl. browser launch can take ~30s
        if _connected(host, port):
            return
        time.sleep(0.75)
    sys.exit(f"error: server did not come up; see {STATE_DIR / 'server.log'}")


def request(method: str, path: str, payload: dict | None = None,
            params: dict | None = None, host: str = "127.0.0.1", port: int = 8931) -> dict:
    qs = ("?" + "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())) if params else ""
    url = f"http://{host}:{port}{path}{qs}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace").strip()
        try:
            body = json.loads(detail)
        except json.JSONDecodeError:
            body = {"error": detail}
        raise ServerError(e.code, body) from None


class ServerError(RuntimeError):
    """Structured server error: short message + code + hint (ticket P3)."""

    def __init__(self, status: int, body: dict):
        super().__init__(body.get("error", f"HTTP {status}"))
        self.status = status
        self.body = body


def show(payload: dict):
    if "markdown" in payload:
        print(payload["markdown"])
    elif "text" in payload:
        print(payload["text"])
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))


def fail(exc: ServerError | RuntimeError, debug: bool) -> int:
    """One-line error by default; full server payload with --debug."""
    if debug and isinstance(exc, ServerError):
        print(f"error [{exc.status}]: {json.dumps(exc.body, indent=2)}", file=sys.stderr)
    else:
        msg = f"error: {exc}"
        if isinstance(exc, ServerError):
            if exc.body.get("code"):
                msg += f" [{exc.body['code']}]"
            if exc.body.get("hint"):
                msg += f"\nhint: {exc.body['hint']}"
        print(msg, file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--host", default="127.0.0.1")
    common.add_argument("--port", type=int, default=8931)
    common.add_argument("--debug", action="store_true", default=argparse.SUPPRESS,
                        help="show full error payloads/tracebacks")
    parser = argparse.ArgumentParser(description=__doc__, parents=[common])
    sub = parser.add_subparsers(dest="cmd", required=True)

    def s(name, help_):
        sp = sub.add_parser(name, help=help_, parents=[common])
        sp.add_argument("--session", "--sid", dest="sid", metavar="SID")
        return sp

    p = s("search", "DuckDuckGo search (markdown)")
    p.add_argument("query", nargs="?", help="omit when using --next")
    p.add_argument("-n", type=int, default=10)
    p.add_argument("--next", dest="next_token", metavar="TOKEN")
    p.add_argument("--retries", type=int, metavar="N",
                   help="extra attempts after the first (default: server config)")
    p.add_argument("--timeout", type=float, metavar="SEC",
                   help="per-attempt result wait (default 30s)")
    p.add_argument("--engine", choices=["lite", "html"],
                   help="force a DDG layout; default tries lite then falls back")

    p = s("open", "navigate; creates a session unless --session given")
    p.add_argument("url")
    p.add_argument("--print-sid", action="store_true",
                   help="print only the bare session id (for $(...) use)")
    p.add_argument("--timeout", type=float, metavar="SEC", help="navigation timeout")
    p.add_argument("--fail-on-http-error", action="store_true",
                   help="exit non-zero if the page responds with HTTP >= 400")

    p = s("text", "page text of the current session page, or fetch a one-off URL")
    p.add_argument("url", nargs="?", help="fetch without a session")
    p.add_argument("--selector", metavar="CSS",
                   help="restrict extraction to a CSS selector (e.g. 'main')")
    p.add_argument("--timeout", type=float, metavar="SEC", help="URL-fetch nav timeout")
    p = s("html", "page HTML of the current session page, or fetch a one-off URL")
    p.add_argument("url", nargs="?", help="fetch without a session")
    p.add_argument("--timeout", type=float, metavar="SEC", help="URL-fetch nav timeout")

    for name, help_, extra in [
        ("click", "click element", [("selector",)]),
        ("key", "press key (Enter, Escape, ...)", [("key",)]),
        ("eval", "evaluate JS in page context", [("js",)]),
        ("run", "run python snippet (file path or -); full Playwright API via `page`",
         [("source",)]),
    ]:
        p = s(name, help_)
        for arg in extra:
            p.add_argument(arg[0])

    p = s("wait", "wait for selector")
    p.add_argument("selector")
    p.add_argument("--timeout-ms", type=int, default=15000)

    p = s("fill", "set input value")
    p.add_argument("selector")
    p.add_argument("text")

    p = s("shot", "save screenshot")
    p.add_argument("path")
    p.add_argument("--full-page", action="store_true")

    p = s("close-session", "release a session's instance back to the pool")
    p.add_argument("sid")
    p = s("close-all", "force-close ALL sessions (pool stuck / stale clients)")
    p.add_argument("--except", dest="keep_sid", metavar="SID",
                   help="keep this session alive")
    s("sessions", "list active sessions (sid, url, title, age)")
    return parser


def _snippet_path(source: str) -> Path:
    """Resolve a snippet path with a clear error (ticket P7)."""
    path = Path(source).expanduser()
    if not path.is_absolute():
        resolved = (Path.cwd() / path).resolve()
        if not resolved.exists():
            raise FileNotFoundError(
                f"{source}: no such file (resolved to {resolved}); "
                "relative paths resolve against your current directory — pass an absolute path"
            )
        path = resolved
    elif not path.exists():
        raise FileNotFoundError(f"{path}: no such file")
    return path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    debug = bool(getattr(args, "debug", False))
    ensure_server(args.host, args.port)
    kw = dict(host=args.host, port=args.port)

    try:
        sid = getattr(args, "sid", None)
        if args.cmd == "search":
            if not args.query and not args.next_token:
                sys.exit("error: a query or --next TOKEN is required")
            params: dict = {"n": args.n}
            if args.timeout is not None:
                params["timeout_ms"] = int(args.timeout * 1000)
            if args.retries is not None:
                params["retries"] = args.retries
            if args.engine:
                params["engine"] = args.engine
            if args.next_token:
                params["next"] = args.next_token
            else:
                params["q"] = args.query
            show(request("GET", "/search", params=params, **kw))

        elif args.cmd == "open":
            created = None
            if not sid:
                sid = created = request("POST", "/session", {}, **kw)["sid"]
            out = request(
                "POST", "/goto",
                {"url": args.url, "sid": sid,
                 **({"timeout_ms": int(args.timeout * 1000)} if args.timeout else {})},
                **kw,
            )
            out = {"sid": sid, **out}
            if args.fail_on_http_error and isinstance(out.get("status"), int) \
                    and out["status"] >= 400:
                print(json.dumps(out, indent=2, ensure_ascii=False))
                return 2
            if args.print_sid:
                print(sid)
            else:
                show(out)

        elif args.cmd in ("text", "html"):
            if not sid and not getattr(args, "url", None):
                sys.exit(f"error: pass --session SID (create one with: open URL) "
                         f"or a URL to fetch ({args.cmd} https://example.com)")
            params: dict = {}
            if sid:
                params["sid"] = sid
            if getattr(args, "url", None):
                params["url"] = args.url
            if getattr(args, "selector", None):
                params["selector"] = args.selector
            if getattr(args, "timeout", None):
                params["timeout_ms"] = int(args.timeout * 1000)
            show(request("GET", f"/{args.cmd}", params=params, **kw))

        elif args.cmd == "click":
            show(request("POST", "/click", {"selector": args.selector, "sid": sid}, **kw))
        elif args.cmd == "fill":
            show(request("POST", "/fill",
                         {"selector": args.selector, "text": args.text, "sid": sid}, **kw))
        elif args.cmd == "key":
            show(request("POST", "/key", {"key": args.key, "sid": sid}, **kw))
        elif args.cmd == "eval":
            show(request("POST", "/eval", {"js": args.js, "sid": sid}, **kw))
        elif args.cmd == "shot":
            show(request("POST", "/shot",
                         {"path": args.path, "full_page": args.full_page, "sid": sid},
                         **kw))
        elif args.cmd == "wait":
            show(request("POST", "/wait",
                         {"selector": args.selector, "timeout_ms": args.timeout_ms,
                          "sid": sid}, **kw))
        elif args.cmd == "run":
            code = sys.stdin.read() if args.source == "-" \
                else _snippet_path(args.source).read_text()
            show(request("POST", "/exec", {"code": code, "sid": sid}, **kw))
        elif args.cmd == "sessions":
            show(request("GET", "/sessions", **kw))
        elif args.cmd == "close-session":
            show(request("DELETE", "/session", params={"sid": args.sid}, **kw))
        elif args.cmd == "close-all":
            payload = {"except_sid": args.keep_sid} if args.keep_sid else {}
            show(request("POST", "/release", payload, **kw))
    except (ServerError, FileNotFoundError) as exc:
        return fail(exc, debug)
    except RuntimeError as exc:
        return fail(ServerError(500, {"error": str(exc)}), debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
