"""Shared fixtures for integration tests (real Camoufox, no network)."""

from pathlib import Path

import pytest

from camoufox_tool.browser import redirect_home, spawn_browser
from camoufox_tool.config import Config
from camoufox_tool.pool import BrowserPool
from camoufox_tool.server import SearchServer

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def fixture_url() -> str:
    return (DATA / "page.html").as_uri()


@pytest.fixture(scope="session")
def ddg_fixture_url() -> str:
    return (DATA / "ddg_like.html").as_uri()


def make_server(max_pages=2, **cfg_overrides) -> SearchServer:
    redirect_home()
    cfg = Config.from_env(
        max_pages=max_pages,
        session_idle=cfg_overrides.pop("session_idle", 60),
        instance_idle=cfg_overrides.pop("instance_idle", 60),
    )
    pool = BrowserPool(cfg.max_pages, spawn_browser)
    return SearchServer(cfg, pool)


@pytest.fixture
async def server():
    s = make_server()
    await s.start()
    yield s
    await s.stop()


async def new_sid(server) -> str:
    return (await server.new_session())["sid"]
