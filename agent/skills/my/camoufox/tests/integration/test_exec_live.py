"""Live /exec through a real page: awaits, result variable, print capture."""

import pytest

from conftest import new_sid


async def test_exec_awaits_and_result(server, fixture_url):
    sid = await new_sid(server)
    await server.goto(sid, fixture_url)

    out = await server.exec_code(
        sid,
        "title = await page.title()\n"
        "print(f'title was {title}')\n"
        "result = {'len': len(title), 'title': title}",
    )
    assert out["sid"] == sid
    assert "'Camoufox Test Page'" in out["result"]
    assert "title was Camoufox Test Page" in out["logs"]


async def test_exec_one_shot_page(server, fixture_url):
    """No session: throwaway page is navigated and discarded."""
    out = await server.exec_code(
        None,
        f"await page.goto('{fixture_url}')\n"
        "result = await page.title()",
    )
    assert "Test Page" in out["result"]


async def test_exec_error_propagates_with_message(server):
    # Direct call (no HTTP layer): page-level exceptions surface unwrapped.
    with pytest.raises(ZeroDivisionError):
        await server.exec_code(None, "1 / 0")
