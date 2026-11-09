"""Integration regression tests for ticket painpoints (real browser,
local fixtures, no network).

Covers: P2 (text <URL> without a session), P4 (session listing metadata),
P8/P1 (attached-state wait survives hidden layout tables), P9 (selector
extraction), P10 (HTTP status surfaced), P11 (release-all escape hatch),
and extraction for the html.duckduckgo.com fallback layout (P1#4).
"""

from pathlib import Path

import pytest

from conftest import new_sid

DATA = Path(__file__).parent / "data"
TABLE_FIXTURE = (DATA / "ddg_table_like.html").as_uri()
HTML_FIXTURE = (DATA / "ddg_html_like.html").as_uri()


# ---- P10: HTTP status surfaced by goto ----

async def test_goto_reports_http_status(server, fixture_url):
    out = await server.goto(None, fixture_url)
    assert "status" in out
    assert out["status"] is None or isinstance(out["status"], int)


# ---- P2: text/html fetch a URL without a session ----

async def test_text_fetches_url_without_session(server, fixture_url):
    """P2a: `text <URL>` must work as a one-off fetch."""
    out = await server.text(None, url=fixture_url)
    assert "hello fixture" in out["text"]
    assert out["url"].startswith("file://")


async def test_html_fetches_url_without_session(server, fixture_url):
    out = await server.html(None, url=fixture_url)
    assert '<a id="link"' in out["html"]


# ---- P9: selector-restricted extraction ----

async def test_text_with_selector_restricts_extraction(server, fixture_url):
    sid = await new_sid(server)
    await server.goto(sid, fixture_url)
    out = await server.text(sid, selector="h1")
    assert out["text"].strip() == "hello fixture"


async def test_text_selector_missing_selector_gives_empty(server, fixture_url):
    sid = await new_sid(server)
    await server.goto(sid, fixture_url)
    assert (await server.text(sid, selector="#does-not-exist"))["text"] == ""


# ---- P4: session listing carries identity metadata ----

async def test_sessions_listing_has_metadata(server, fixture_url):
    sid = await new_sid(server)
    await server.goto(sid, fixture_url)
    out = await server.list_sessions()
    entry = next(e for e in out["sessions"] if e["sid"] == sid)
    assert entry["url"].startswith("file://")
    assert entry["age_s"] >= 0
    assert entry["idle_s"] <= 60
    assert entry.get("title") == "Camoufox Test Page"


async def test_empty_sessions_listing_shape(server):
    assert (await server.list_sessions())["sessions"] == []


# ---- P4/P11: release-all escape hatch ----

async def test_release_all_closes_every_session(server):
    sids = [await new_sid(server) for _ in range(2)]
    out = await server.release_all()
    assert set(out["closed"]) == set(sids)
    assert server.sessions == {}


async def test_release_all_can_keep_one_alive(server):
    keep, close = await new_sid(server), await new_sid(server)
    out = await server.release_all(except_sid=keep)
    assert out["closed"] == [close]
    assert keep in server.sessions and close not in server.sessions


# ---- P1/P8: hidden layout table no longer hangs the result wait ----

async def test_hidden_table_layout_still_extracts_results(server):
    """The exact DDG variant that caused six timeouts: results inside a
    never-visible layout table. attached-state + parsing must succeed."""

    async def fn(page, _ctx):
        await page.goto(TABLE_FIXTURE)
        await page.wait_for_selector(
            "a.result-link, p.info, a.result__a, table",
            state="attached", timeout=5000,
        )
        return await server._ddg_extract(page)

    results, next_form = await server.pool.run(fn)
    assert [r["url"] for r in results] == ["https://example.org/a"]
    assert results[0]["snippet"] == "snippet from hidden table layout"
    assert next_form and next_form["s"] == "10"


async def test_old_visible_state_wait_would_have_hung(server):
    """Proves the fixture reproduces the original hang: a visibility wait
    on the same DOM cannot succeed (it timed out in production)."""

    async def fn(page, _ctx):
        await page.goto(TABLE_FIXTURE)
        await page.wait_for_selector("table", state="visible", timeout=800)

    with pytest.raises(Exception):
        await server.pool.run(fn)


# ---- P1#4: html-engine (html.duckduckgo.com) extraction ----

async def test_html_engine_extraction_on_fixture_dom(server):
    async def fn(page, _ctx):
        await page.goto(HTML_FIXTURE)
        return await server._ddg_extract(page, "html")

    results, next_form = await server.pool.run(fn)
    urls = [r["url"] for r in results]
    assert urls[0] == "https://example.org/a"          # uddg unwrapped
    assert "https://direct.example.net/b" in urls      # direct link kept
    assert len(results) == 2                           # blank title filtered
    assert results[0]["snippet"] == "first snippet text"
    assert next_form and next_form["s"] == "20"
