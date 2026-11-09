"""Central configuration; timeouts overridable via environment."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    host: str = "127.0.0.1"
    port: int = 8931
    max_pages: int = 4
    session_idle: float = 300.0   # seconds before an unused session is dropped
    instance_idle: float = 600.0  # seconds before an idle instance is closed
    exec_timeout: float = 120.0   # hard limit for /exec snippets
    default_max_results: int = 10
    search_timeout: float = 30.0    # seconds for the DDG result wait (P14)
    goto_timeout: float = 45.0      # seconds for page.goto (P14)
    search_retries: int = 2         # extra attempts after the first (P1)
    search_min_interval: float = 8.0  # min seconds between DDG hits (P5)

    @classmethod
    def from_env(cls, **overrides) -> "Config":
        env = os.environ.get

        def num(name: str, default: float) -> float:
            try:
                return float(env(name, default))
            except ValueError:
                return default

        base = dict(
            session_idle=num("CAMOUFOX_SESSION_IDLE", cls.session_idle),
            instance_idle=num("CAMOUFOX_INSTANCE_IDLE", cls.instance_idle),
            exec_timeout=num("CAMOUFOX_EXEC_TIMEOUT", cls.exec_timeout),
            search_timeout=num("CAMOUFOX_SEARCH_TIMEOUT", cls.search_timeout),
            goto_timeout=num("CAMOUFOX_GOTO_TIMEOUT", cls.goto_timeout),
            search_retries=int(num("CAMOUFOX_SEARCH_RETRIES", cls.search_retries)),
            search_min_interval=num("CAMOUFOX_SEARCH_MIN_INTERVAL", cls.search_min_interval),
        )
        base.update(overrides)
        return cls(**base)
