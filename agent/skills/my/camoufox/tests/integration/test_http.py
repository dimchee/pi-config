"""HTTP plumbing tests: raw sockets against a live listener, no browsers needed.

Uses a pool with a never-called fake spawner, so routes that would touch a
browser are exercised only for their error paths.
"""

import asyncio
import json
import urllib.error
import urllib.request

import pytest

from camoufox_tool.config import Config
from camoufox_tool.pool import BrowserPool
from camoufox_tool.server import SearchServer, handle_client


@pytest.fixture
async def http_server():
    async def boom():
        raise AssertionError("spawner must not be called in HTTP error-path tests")

    cfg = Config(max_pages=1, session_idle=60, instance_idle=60)
    server = SearchServer(cfg, BrowserPool(1, boom))
    tcp = await asyncio.start_server(
        lambda r, w: handle_client(server, r, w), "127.0.0.1", 0
    )
    port = tcp.sockets[0].getsockname()[1]
    task = asyncio.create_task(tcp.serve_forever())
    yield f"http://127.0.0.1:{port}"
    task.cancel()
    tcp.close()


def _http(url: str, method: str = "GET", payload: bytes | None = None):
    """NOTE: called via asyncio.to_thread - blocking I/O must not sit on the
    same loop the test server runs on. Returns (status, parsed-json-or-text)."""
    req = urllib.request.Request(url, data=payload, method=method)

    class NoRedirect(urllib.request.HTTPErrorProcessor):
        def http_response(self, req, resp):
            return resp

    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=10) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return e.code, {"raw": raw.decode(errors="replace")}


async def http_call(url: str, method: str = "GET", payload: bytes | None = None):
    return await asyncio.to_thread(_http, url, method, payload)


async def test_unknown_route_is_404(http_server):
    status, body = await http_call(f"{http_server}/nope")
    assert status == 404
    assert "error" in body


async def test_missing_query_param_is_400(http_server):
    status, body = await http_call(f"{http_server}/search")
    assert status == 400
    assert "missing" in body["error"]


async def test_malformed_json_body_is_400(http_server):
    status, body = await http_call(f"{http_server}/goto", method="POST", payload=b"{not json")
    assert status == 400


async def test_missing_body_field_is_400(http_server):
    status, body = await http_call(
        f"{http_server}/goto", method="POST", payload=json.dumps({}).encode()
    )
    assert status == 400
    assert "url" in body["error"]


async def test_session_routes_shape(http_server):
    # /sessions works without any browser; DELETE of unknown sid -> 404
    status, body = await http_call(f"{http_server}/sessions")
    assert (status, body) == (200, {"sessions": []})
    import urllib.parse
    status, body = await http_call(
        f"{http_server}/session?{urllib.parse.urlencode({'sid': 'zzz'})}",
        method="DELETE",
    )
    assert status == 404
