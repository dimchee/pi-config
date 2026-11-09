"""HTTP-level regression tests for ticket painpoints P3 (structured errors,
no tracebacks over the wire) and P11 (/release route), against a live
listener with a never-called fake spawner."""

import asyncio
import json
import urllib.parse

import pytest

from camoufox_tool.config import Config
from camoufox_tool.pool import BrowserPool
from camoufox_tool.server import SearchServer, handle_client

from test_http import http_call


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


async def test_unknown_session_error_is_structured_404(http_server):
    """P3: no traceback strings; code + hint guide the caller."""
    status, body = await http_call(
        f"{http_server}/session?{urllib.parse.urlencode({'sid': 'zzz'})}",
        method="DELETE",
    )
    assert status == 404
    assert body["code"] == "unknown_session"
    assert "sessions" in body["hint"]
    assert "Traceback" not in json.dumps(body)


async def test_bad_timeout_parameter_is_400(http_server):
    status, body = await http_call(
        f"{http_server}/search?{urllib.parse.urlencode({'q': 'x', 'timeout_ms': 'abc'})}"
    )
    assert status == 400
    assert "error" in body and "traceback" not in body


async def test_release_route_exists(http_server):
    """P11: force-release endpoint answers even with zero sessions."""
    status, body = await http_call(f"{http_server}/release", method="POST",
                                   payload=b"{}")
    assert status == 200
    assert body == {"closed": []}


async def test_infra_errors_never_leak_tracebacks(http_server):
    """Any 500 must come back short; tracebacks stay in server-side logs."""
    status, body = await http_call(
        f"{http_server}/text?{urllib.parse.urlencode({'url': 'https://x.example/'})}"
    )
    assert status == 500
    flat = json.dumps(body)
    assert "Traceback (most recent call last)" not in flat
    assert body["error"] and body["code"]
