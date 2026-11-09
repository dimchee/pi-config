"""Live DuckDuckGo search + --next chaining. Opt in with RUN_LIVE=1."""

import os

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("RUN_LIVE"),
        reason="live network test; set RUN_LIVE=1 to enable",
    ),
]


async def test_search_returns_results(server):
    data = await server.search("linux kernel", 5)
    assert len(data["results"]) >= 3
    for r in data["results"]:
        assert r["url"].startswith("http")
        assert r["title"]
    assert "DuckDuckGo results for" in data["markdown"]


async def test_search_next_chain(server):
    page1 = await server.search("linux kernel", 3)
    token = page1.get("next_token")
    if not token:
        pytest.skip("DDG served no pagination token")
    page2 = await server.more(token, 3)
    urls1 = {r["url"] for r in page1["results"]}
    urls2 = {r["url"] for r in page2["results"]}
    assert page2["results"], "next page must have results"
    assert not (urls1 & urls2), "pages must not overlap"
