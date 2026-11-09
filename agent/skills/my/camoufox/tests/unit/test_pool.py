"""Unit tests: BrowserPool logic with fake browsers (no Camoufox needed)."""

import asyncio

import pytest

from camoufox_tool.pool import BrowserPool


class FakeContext:
    def __init__(self, fail_page=False):
        self.fail_page = fail_page
        self.closed = False

    async def new_page(self):
        if self.fail_page:
            raise RuntimeError("page creation failed")
        return object()

    async def close(self):
        self.closed = True


class FakeBrowser:
    """Fake instance; `broken` simulates a crashed browser."""

    def __init__(self, name, broken=False, fail_page=False):
        self.name = name
        self.broken = broken
        self.fail_page = fail_page
        self.closed = False
        self.contexts = 0

    async def new_context(self):
        if self.broken:
            raise RuntimeError("browser is dead")
        self.contexts += 1
        return FakeContext(fail_page=self.fail_page)


def make_pool(max_instances, specs):
    """specs: list of (name, kwargs) consumed per spawn; recycles the last."""
    created = []

    def spawn_factory():
        async def spawn():
            idx = min(len(created), len(specs) - 1)
            name, kw = specs[idx]
            b = FakeBrowser(name, **kw)
            created.append(b)

            async def close():
                b.closed = True

            return {"browser": b, "close": close}
        return spawn
    return BrowserPool(max_instances, spawn_factory()), created


async def test_exclusive_handout_and_blocking():
    pool, _ = make_pool(1, [("b1", {})])

    e1 = await pool.acquire()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(pool.acquire(), timeout=0.05)
    await pool.release(e1)
    e2 = await pool.acquire()
    assert e2 is e1  # reused warm instance


async def test_spawns_up_to_max():
    pool, created = make_pool(2, [("b1", {}), ("b2", {})])
    e1 = await pool.acquire()
    e2 = await pool.acquire()   # no free instance -> spawns second
    assert e1["browser"] is not e2["browser"]
    assert len(created) == 2


async def test_dead_browser_discarded_and_retried():
    # first spawn is broken, second works
    pool, created = make_pool(4, [("dead", {"broken": True}), ("good", {})])

    async def fn(page, ctx):
        return "ok"

    assert await pool.run(fn) == "ok"
    assert created[0].closed          # broken one discarded...
    assert not created[1].closed      # ...replacement used and released alive
    assert pool.total == 1


async def test_page_creation_failure_counts_as_infra_failure():
    pool, created = make_pool(4, [("bad-page", {"fail_page": True}), ("good", {})])

    async def fn(page, ctx):
        return "ok"

    assert await pool.run(fn) == "ok"
    assert created[0].closed


async def test_fn_errors_propagate_without_discarding():
    pool, created = make_pool(1, [("b1", {})])

    async def fn(page, ctx):
        raise ValueError("page-level problem")

    with pytest.raises(ValueError):
        await pool.run(fn)
    assert not created[0].closed      # browser itself is fine
    assert pool.total == 1


async def test_shrink_keeps_one_warm_instance():
    pool, created = make_pool(3, [("b1", {}), ("b2", {})])
    e1 = await pool.acquire()
    e2 = await pool.acquire()          # forces a second spawn
    assert pool.total == 2
    await pool.release(e1)
    await pool.release(e2)
    e1["last_used"] -= 999             # age both artificially (release re-stamps,
    e2["last_used"] -= 999             # so age AFTER releasing)
    await pool.shrink(idle_seconds=60)
    assert pool.total == 1
    assert created[0].closed or created[1].closed
    # the survivor must be usable
    entry = await pool.acquire()
    await pool.release(entry)


async def test_shrink_respects_fresh_instances():
    pool, _ = make_pool(2, [("b1", {})])
    entry = await pool.acquire()
    await pool.release(entry)         # last_used = now
    await pool.shrink(idle_seconds=600)
    assert pool.total == 1            # fresh enough to stay warm
