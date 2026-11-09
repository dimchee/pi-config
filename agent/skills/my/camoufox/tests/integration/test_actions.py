"""Fixed actions (goto/text/click/fill/key/eval/wait/shot) on a local fixture page."""

import pytest

from conftest import new_sid


async def test_goto_returns_title_and_url(server, fixture_url):
    out = await server.goto(None, fixture_url)
    assert "Test Page" in out["title"]
    assert out["url"].startswith("file://")


async def test_text_extracts_body(server, fixture_url):
    sid = await new_sid(server)
    await server.goto(sid, fixture_url)
    assert "hello fixture" in (await server.text(sid))["text"]


async def test_html_contains_markup(server, fixture_url):
    sid = await new_sid(server)
    await server.goto(sid, fixture_url)
    assert '<a id="link"' in (await server.html(sid))["html"]


async def test_fill_click_eval_flow(server, fixture_url):
    sid = await new_sid(server)
    await server.goto(sid, fixture_url)
    await server.fill(sid, "#name", "agent")
    await server.click(sid, "#go")
    out = await server.evaluate(sid, "document.getElementById('out').textContent")
    assert "agent" in out["result"]


async def test_wait_for_selector(server, fixture_url):
    sid = await new_sid(server)
    await server.goto(sid, fixture_url)
    assert (await server.wait_for(sid, "h1", 5000))["found"] == "h1"


async def test_wait_timeout_raises(server, fixture_url):
    from camoufox_tool.server import handle_request

    sid = await new_sid(server)
    with pytest.raises(Exception):
        await server.wait_for(sid, "#nonexistent", timeout_ms=200)


async def test_screenshot_writes_file(server, fixture_url, tmp_path):
    target = tmp_path / "shot.png"
    out = await server.screenshot(None, str(target), full_page=False)
    assert out["path"] == str(target)
    assert target.stat().st_size > 1000


async def test_throwaway_page_needs_no_session(server, fixture_url):
    """Omitting sid must work: one-shot acquire -> act -> release."""
    out = await server.goto(None, fixture_url)
    assert out["url"].endswith("page.html")
