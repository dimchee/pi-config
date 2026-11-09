"""Real Camoufox browser spawning.

`redirect_home` must run BEFORE importing/launching camoufox (the browser
derives state dirs from $HOME and would otherwise drop ~/camoufox and
~/.camoufox into the real home). Kept separate from pool.py so tests can
inject fake spawners and never import camoufox at all.
"""

import os
from pathlib import Path


def redirect_home(state_dir: str | os.PathLike | None = None) -> Path:
    """Point $HOME at a dedicated state dir; keep the real cache reachable.

    XDG_CACHE_HOME must keep pointing at the REAL cache: that's where the
    nix-managed browser binaries, fonts and geoip DBs are symlinked (see
    flake.nix shellHook).
    """
    real_home = Path.home()
    state = Path(
        state_dir or os.environ.get("CAMOUFOX_SERVER_HOME", real_home / ".local/state/camoufox-server")
    )
    state.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(state)
    os.environ.setdefault("XDG_CACHE_HOME", str(real_home / ".cache"))
    return state


async def spawn_browser() -> dict:
    """Launch one Camoufox instance. Returns {"browser", "close"}."""
    from camoufox.async_api import AsyncCamoufox  # lazy: after redirect_home()

    cm = AsyncCamoufox(headless="virtual")
    browser = await cm.__aenter__()

    async def close():
        await cm.__aexit__(None, None, None)

    return {"browser": browser, "close": close}
