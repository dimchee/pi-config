"""Session lifecycle: create/list/close/expiry, unknown-sid errors, DDG extraction."""

import asyncio

import pytest

from camoufox_tool.ddg import decode_token, encode_token
from conftest import make_server, new_sid


async def test_create_list_close(server):
    sid = await new_sid(server)
    assert sid in sorted(server.sessions)
    out = await server.close_session(sid)
    assert out["closed"] == sid
    assert sid not in server.sessions


async def test_unknown_session_is_keyerror(server):
    with pytest.raises(KeyError):
        await server.text("bogus")


async def test_closed_session_releases_instance_for_reuse(server):
    """Closing a session must return its instance to the pool, not leak it."""
    sids = [await new_sid(server) for _ in range(2)]
    assert server.pool.total == 2
    for sid in sids:
        await server.close_session(sid)
    # pool now has 2 free instances; a new session reuses one instead of spawning
    sid3 = await new_sid(server)
    assert server.pool.total == 2
    await server.close_session(sid3)


async def test_idle_session_expired_by_reaper():
    server = make_server(session_idle=0.2)
    await server.start()
    try:
        sid = await new_sid(server)
        total_before = server.pool.total
        await asyncio.sleep(0.5)
        await server.reap_once()
        assert sid not in server.sessions
        # instance returned to the pool, nothing leaked
        assert server.pool.total == total_before
    finally:
        await server.stop()


async def test_ddg_extraction_on_fixture_dom(server, ddg_fixture_url):
    """EXTRACT_JS + filter_results against a local replica of the lite DOM."""
    async def fn(page, _ctx):
        await page.goto(ddg_fixture_url)
        return await server._ddg_extract(page)

    results, next_form = await server.pool.run(fn)

    urls = [r["url"] for r in results]
    assert urls[0] == "https://example.org/a"          # uddg unwrapped
    assert "https://direct.example.net/b" in urls      # direct link kept
    assert all(r["title"].strip() for r in results)    # untitled row filtered
    assert len(results) == 2
    assert results[0]["snippet"] == "first snippet text"

    token = encode_token("lite", next_form)
    assert token
    assert decode_token(token) == ("lite", next_form)
