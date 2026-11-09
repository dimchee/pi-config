"""Property-based tests for server-side search orchestration (tickets P1/P5).

Uses a SearchServer whose `_ddg_attempt` is stubbed, so retry budgets,
backoff shape, engine fallback and the rate-limit guard are exercised
without any network or browser.
"""

import asyncio
import time

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from camoufox_tool.config import Config
from camoufox_tool.ddg import DDG_HTML, DDG_LITE, decode_token, encode_token
from camoufox_tool.errors import RateLimited
from camoufox_tool.server import SearchServer


def make_server(**cfg_overrides) -> SearchServer:
    cfg = Config(
        search_retries=cfg_overrides.pop("retries", 2),
        search_min_interval=cfg_overrides.pop("min_interval", 0.0),
        search_timeout=0.05,
    )
    return SearchServer(cfg)


class Recorder:
    """Stub for _ddg_attempt: replays scripted outcomes per call."""

    def __init__(self, script=None, router=None):
        self.hits: list[tuple[float, str]] = []
        self._script = list(script or [])
        self._router = router  # optional engine -> outcome mapping

    async def __call__(self, engine: str, query: str, timeout_ms: int):
        self.hits.append((time.monotonic(), engine))
        if self._router is not None:
            outcome = self._router[engine]
        else:
            outcome = self._script[min(len(self.hits) - 1, len(self._script) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


OK_RESULT = ([{"title": "T", "url": "https://a.example/", "domain": "",
               "snippet": "s"}], {"q": "q", "s": "10"})


@pytest.fixture
def instant_sleep(monkeypatch):
    """Make backoff sleeps instantaneous but observable."""
    delays: list[float] = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return delays


class TestRetryProperties:
    @settings(max_examples=50,
              suppress_health_check=[HealthCheck.too_slow,
                                     HealthCheck.function_scoped_fixture])
    @given(
        failures=st.integers(0, 4),
        retries=st.integers(0, 2),
    )
    async def test_success_within_budget_failure_beyond(self, failures, retries,
                                                        instant_sleep):
        """P1: k transient failures succeed iff k <= retry budget."""
        instant_sleep.clear()
        srv = make_server(retries=retries)
        rec = Recorder(script=[TimeoutError("boom")] * failures + [OK_RESULT])
        srv._ddg_attempt = rec

        budget = min(5, retries + 1)
        if failures <= retries:
            out = await srv.search("query", 10, engine="lite")
            assert out["results"][0]["url"] == "https://a.example/"
            assert len(rec.hits) == failures + 1
        else:
            with pytest.raises(TimeoutError):
                await srv.search("query", 10, engine="lite")
            assert len(rec.hits) == budget  # never exceeds the budget

    @settings(max_examples=30,
              suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(extra_failures=st.integers(1, 3))
    async def test_backoff_delays_grow_and_are_capped(self, extra_failures,
                                                      instant_sleep):
        """Backoff is exponential-ish (2s, 8s) and never above 30s."""
        instant_sleep.clear()
        srv = make_server(retries=3)
        rec = Recorder(script=[RateLimited()] * extra_failures + [OK_RESULT])
        srv._ddg_attempt = rec
        await srv.search("q", 10, engine="lite")
        assert all(0 < d <= 30 for d in instant_sleep)
        assert instant_sleep == sorted(instant_sleep)  # monotonically growing

    @settings(max_examples=30)
    @given(msg=st.text(min_size=1, max_size=32))
    async def test_anomaly_pages_raise_typed_rate_limit(self, msg):
        """P1#3/P5: an anti-bot page becomes a typed error, not a traceback."""
        srv = make_server(retries=0)
        rec = Recorder(script=[RateLimited(msg)])
        srv._ddg_attempt = rec
        with pytest.raises(RateLimited) as ei:
            await srv.search("q", 10, engine="lite")
        assert msg in str(ei.value)


class TestEngineFallbackProperties:
    async def test_default_falls_back_to_html_engine_on_failure(self):
        """P1#4: lite failing once -> html engine answers automatically."""
        srv = make_server(retries=0)
        rec = Recorder(router={"lite": TimeoutError("hang"),
                               "html": OK_RESULT})
        srv._ddg_attempt = rec
        out = await srv.search("fallback q", 10)
        assert out["engine"] == "html"
        assert out["next_token"]  # pagination keeps working on the fallback
        assert decode_token(out["next_token"]) == ("html", {"q": "q", "s": "10"})
        assert [eng for _, eng in rec.hits] == ["lite", "html"]

    async def test_explicit_engine_is_not_second_guessed(self):
        """--engine html means html only: no silent switch back to lite."""
        srv = make_server(retries=1)
        rec = Recorder(script=[TimeoutError("down")])
        srv._ddg_attempt = rec
        with pytest.raises(TimeoutError):
            await srv.search("q", 10, engine="html")
        assert {eng for _, eng in rec.hits} == {"html"}

    async def test_fallback_only_when_primary_exhausted(self):
        """Fallback runs after (not instead of) the primary's full budget."""
        srv = make_server(retries=1)
        rec = Recorder(router={"lite": TimeoutError("x"), "html": OK_RESULT})
        srv._ddg_attempt = rec
        await srv.search("q", 10)
        assert [eng for _, eng in rec.hits] == ["lite", "lite", "html"]

    async def test_both_engines_down_raises_last_error(self):
        srv = make_server(retries=0)
        rec = Recorder(script=[RateLimited()])
        srv._ddg_attempt = rec
        with pytest.raises(RateLimited):
            await srv.search("q", 10)


class TestThrottleProperties:
    @settings(max_examples=15, deadline=None,
              suppress_health_check=[HealthCheck.filter_too_much])
    @given(interval=st.sampled_from([0.02, 0.04]))
    async def test_consecutive_searches_are_spaced_out(self, interval):
        """P5: the server enforces a minimum interval between DDG hits."""
        srv = make_server(min_interval=interval)
        rec = Recorder(script=[OK_RESULT])
        srv._ddg_attempt = rec
        for _ in range(3):
            await srv.search("q", 10, engine="lite")
        gaps = [b[0] - a[0] for a, b in zip(rec.hits, rec.hits[1:])]
        assert gaps and all(g >= interval * 0.9 for g in gaps)

    async def test_first_search_is_never_delayed(self):
        srv = make_server(min_interval=60.0)
        rec = Recorder(script=[OK_RESULT])
        srv._ddg_attempt = rec
        start = time.monotonic()
        await srv.search("q", 10, engine="lite")
        assert time.monotonic() - start < 1.0  # no artificial wait up front


class TestMorePagination:
    class FakeRequest:
        def __init__(self, ctx):
            self.ctx = ctx

        async def post(self, url, form=None):
            self.ctx.posted.append((url, form))
            return self

        async def text(self):
            return "<html><body>page</body></html>"

    class FakeContext:
        def __init__(self):
            self.posted = []
            self.request = TestMorePagination.FakeRequest(self)

    class FakePage:
        url = "about:blank"

        async def set_content(self, html):
            pass

        async def query_selector(self, sel):
            return None

        async def content(self):
            return "<html></html>"

        async def evaluate(self, js):
            return {"results": [], "nextForm": None}

    class FakePool:
        def __init__(self):
            self.ctx = TestMorePagination.FakeContext()

        async def run(self, fn):
            return await fn(TestMorePagination.FakePage(), self.ctx)

    async def test_next_posts_to_the_tokens_engine(self):
        """--next tokens remember which engine produced them (P12/P1#4)."""
        srv = make_server()
        pool = self.FakePool()
        srv.pool = pool
        token = encode_token("html", {"q": "pag q", "s": "10"})
        out = await srv.more(token, 5)
        assert pool.ctx.posted[0][0] == DDG_HTML
        assert pool.ctx.posted[0][1] == {"q": "pag q", "s": "10"}
        assert out["results"] == []
        assert "_No results found._" in out["markdown"]
        assert 'for "pag q"' in out["markdown"]

    async def test_legacy_tokens_still_hit_lite(self):
        srv = make_server()
        pool = self.FakePool()
        srv.pool = pool
        token = encode_token("lite", {"q": "old"})
        await srv.more(token, 5)
        assert pool.ctx.posted[0][0] == DDG_LITE

    async def test_anomaly_in_more_raises_rate_limited(self):
        srv = make_server()
        outer = self

        class AnomalyPage(self.FakePage):
            async def content(self):
                return "unfortunately, an anomaly was detected"

        class Pool(self.FakePool):
            async def run(self, fn):
                return await fn(AnomalyPage(), outer.FakeContext())

        srv.pool = Pool()
        with pytest.raises(RateLimited):
            await srv.more(encode_token("lite", {"q": "x"}), 5)


class TestConfigEnvOverrides:
    def test_timeouts_and_retries_are_env_tunable(self, monkeypatch):
        """P14: hard-coded timeouts become configuration."""
        monkeypatch.setenv("CAMOUFOX_SEARCH_TIMEOUT", "11.5")
        monkeypatch.setenv("CAMOUFOX_GOTO_TIMEOUT", "60")
        monkeypatch.setenv("CAMOUFOX_SEARCH_RETRIES", "3")
        monkeypatch.setenv("CAMOUFOX_SEARCH_MIN_INTERVAL", "0")
        cfg = Config.from_env()
        assert cfg.search_timeout == 11.5
        assert cfg.goto_timeout == 60.0
        assert cfg.search_retries == 3
        assert cfg.search_min_interval == 0.0

    def test_defaults_keep_previous_behavior_plus_guard(self, monkeypatch):
        monkeypatch.delenv("CAMOUFOX_SEARCH_TIMEOUT", raising=False)
        monkeypatch.delenv("CAMOUFOX_GOTO_TIMEOUT", raising=False)
        cfg = Config.from_env()
        assert cfg.search_timeout == 30.0
        assert cfg.goto_timeout == 45.0
