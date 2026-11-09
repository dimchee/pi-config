"""Typed errors for the Camoufox tool.

Goal (ticket P3/P10): clients get short, structured errors
(``{error, code, hint}``) while full tracebacks stay server-side in the
server log. Raise ``ToolError`` subclasses where the cause is known;
everything else is mapped heuristically by :func:`error_payload`.
"""

import traceback


class ToolError(Exception):
    """An error worth reporting concisely to the CLI user."""

    code = "internal_error"
    http_status = 500

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


class RateLimited(ToolError):
    """DuckDuckGo served an anti-bot / anomaly page."""

    code = "rate_limited"
    http_status = 429

    def __init__(self, message="DuckDuckGo served an anti-bot page (anomaly/captcha)"):
        super().__init__(message, hint="wait 30-60s, then retry")


class SearchFailed(ToolError):
    """Search did not produce usable results within the budget."""

    code = "search_failed"

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message, hint)


# Friendly names for Gecko network error codes that leak through Playwright
# as plain strings (ticket P10).
_GECKO_HINTS = [
    ("NS_ERROR_UNKNOWN_HOST", "dns_error", "domain does not exist or DNS failed"),
    ("NS_ERROR_CONNECTION_REFUSED", "connection_refused", "server refused the connection"),
    ("NS_ERROR_NET_TIMEOUT", "net_timeout", "server did not respond in time"),
    ("NS_ERROR_NET_RESET", "net_reset", "connection was reset by the peer"),
    ("NS_ERROR_REDIRECT_LOOP", "redirect_loop", "too many redirects"),
    ("NS_ERROR_UNKNOWN_PROTOCOL", "unknown_protocol", "URL scheme not supported"),
    ("NS_ERROR_FILE_NOT_FOUND", "file_not_found", "file does not exist"),
    ("NS_ERROR_MALFORMED_URI", "malformed_uri", "URL is malformed"),
    ("SSL_ERROR", "tls_error", "TLS/SSL handshake failed"),
    ("SEC_ERROR", "tls_error", "TLS/SSL certificate rejected"),
]


def _map_exception(exc: Exception) -> tuple[str, str, str]:
    """Map an arbitrary exception to (message, code, hint)."""
    name = type(exc).__name__
    text = f"{exc}"

    for marker, code, hint in _GECKO_HINTS:
        if marker in text:
            return text, code, hint

    if name in ("TimeoutError", "PlaywrightTimeoutError") or (
        "Timeout" in name and "exceeded" in text
    ):
        return (
            text.splitlines()[0],
            "timeout",
            "selector/page never became ready; retry, raise --timeout, or check the page with 'text'",
        )

    if name == "KeyError":
        return text, "unknown_session", "list known ids with 'sessions'"

    return f"{name}: {text}", "internal_error", None


def error_payload(exc: Exception, debug: bool = False) -> tuple[int, dict]:
    """HTTP status + JSON body for an exception.

    Full tracebacks never go over the wire unless ``debug`` (CAMOUFOX_DEBUG
    server env); callers are expected to log them server-side instead.
    """
    if isinstance(exc, ToolError):
        status = exc.http_status
        body = {"error": str(exc), "code": exc.code}
        if exc.hint:
            body["hint"] = exc.hint
    else:
        message, code, hint = _map_exception(exc)
        status = 500
        if isinstance(exc, KeyError):
            status = 404  # e.g. unknown session id
        elif isinstance(exc, (ValueError, TypeError)):
            status = 400  # bad request parameters
        body = {"error": message, "code": code}
        if hint:
            body["hint"] = hint
    if debug:
        body["traceback"] = traceback.format_exc()
    return status, body
