"""Dynamic pool of exclusive Camoufox instances.

Instances spawn lazily via the injected `spawn` callable (async, returns
{"browser", "close"}) up to `max`, are handed out exclusively, and can be
shrunk back by the idle reaper (one instance stays warm). NOTE: parallel
navigation inside ONE shared browser wedges after its first completed search
(observed with this Camoufox build), hence exclusive hand-out.
"""

import asyncio
import contextlib
import sys
import time

PROBE_TIMEOUT = 60.0  # seconds for new_context/new_page liveness probes


class BrowserPool:
    def __init__(self, max_instances: int, spawn):
        self.max = max_instances
        self.spawn = spawn
        self.free: list[dict] = []   # {"browser", "close", "last_used", "closed"}
        self.total = 0
        self._cond = asyncio.Condition()
        self._all: list[dict] = []

    async def acquire(self) -> dict:
        """Hand out a free instance or spawn one; block at capacity."""
        # Reserve a slot outside the condition lock (spawning takes seconds).
        reserved = False
        async with self._cond:
            waited = False
            while True:
                if self.free:
                    entry = self.free.pop(0)
                    entry["last_used"] = time.time()
                    return entry
                if self.total < self.max:
                    self.total += 1
                    reserved = True
                    break
                # Pool exhaustion must be visible somewhere (ticket P11):
                # stderr goes to server.log; clients see it via 'sessions'.
                if not waited:
                    print(
                        f"[pool] all {self.max} instance(s) busy; "
                        "waiting for a free slot...",
                        file=sys.stderr,
                    )
                    waited = True
                await self._cond.wait()
        if not reserved:
            raise RuntimeError("unreachable")
        try:
            entry = await self.spawn()
            entry["last_used"] = time.time()
            entry["closed"] = False
            self._all.append(entry)
            return entry
        except BaseException:
            async with self._cond:
                self.total -= 1
                self._cond.notify_all()
            raise

    async def release(self, entry: dict):
        if entry.get("closed"):
            return
        entry["last_used"] = time.time()
        async with self._cond:
            self.free.append(entry)
            self._cond.notify_all()

    async def close(self, entry: dict):
        """Discard an instance permanently (dead browser or pool shrink)."""
        if entry.get("closed"):
            return
        entry["closed"] = True
        with contextlib.suppress(Exception):
            await entry["close"]()
        async with self._cond:
            self.total -= 1
            self._cond.notify_all()

    async def run(self, fn):
        """Run fn(page, context) on an exclusive instance.

        Probes the browser first (a crashed browser would otherwise wedge the
        pool); on infra failure the instance is discarded and ONE fresh attempt
        is made. Errors raised by fn are page-level problems and propagate
        untouched.
        """
        err = None
        for attempt in (1, 2):
            entry = await self.acquire()
            try:
                context = await asyncio.wait_for(entry["browser"].new_context(), timeout=PROBE_TIMEOUT)
                page = await asyncio.wait_for(context.new_page(), timeout=PROBE_TIMEOUT)
            except Exception as exc:
                await self.close(entry)
                err = exc
                continue
            try:
                return await fn(page, context)
            finally:
                with contextlib.suppress(Exception):
                    await context.close()
                await self.release(entry)
        raise err

    async def shrink(self, idle_seconds: float):
        """Close idle instances; keep exactly one warm."""
        now = time.time()
        while self.total > 1 and self.free:
            oldest = min(self.free, key=lambda e: e["last_used"])
            if now - oldest["last_used"] <= idle_seconds:
                break
            self.free.remove(oldest)
            await self.close(oldest)

    async def stop(self):
        for entry in self._all:
            await self.close(entry)
