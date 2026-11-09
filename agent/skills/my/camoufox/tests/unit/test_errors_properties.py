"""Property-based tests for typed error payloads (tickets P3/P10).

Invariant under test: any exception maps to a short structured body
({error, code[, hint]}) with a sane HTTP status; tracebacks never leak
unless debug mode is on; Gecko network codes get friendly codes/hints.
"""

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from camoufox_tool.errors import (
    _GECKO_HINTS,
    RateLimited,
    SearchFailed,
    ToolError,
    error_payload,
)

# json.dumps must UTF-8-encode everything -> exclude lone surrogates.
text = st.text(alphabet=st.characters(codec="utf-8"), max_size=64)


def raise_and_map(exc, **kw):
    try:
        raise exc
    except Exception as e:
        return error_payload(e, **kw)


class TestPayloadShapeProperties:
    @settings(max_examples=200)
    @given(msg=text)
    def test_arbitrary_exception_gives_structured_body(self, msg):
        class Weird(RuntimeError):
            pass

        status, body = raise_and_map(Weird(f"prefix {msg} suffix"))
        assert status == 500
        assert set(body) >= {"error", "code"}
        assert "Traceback (most recent call last)" not in body["error"]
        assert isinstance(body["code"], str) and body["code"]

    @settings(max_examples=200)
    @given(msg=text)
    def test_traceback_only_in_debug_mode(self, msg):
        _, plain = raise_and_map(ValueError(msg))
        _, dbg = raise_and_map(ValueError(msg), debug=True)
        assert "traceback" not in plain
        assert "Traceback (most recent call last)" in dbg["traceback"]
        # the message itself is identical in both modes
        assert plain["error"] == dbg["error"] == f"ValueError: {msg}"

    @settings(max_examples=100)
    @given(msg=text)
    def test_rate_limited_is_typed_with_backoff_hint(self, msg):
        """P5: callers must be able to recognize rate limiting and back off."""
        status, body = raise_and_map(RateLimited(msg))
        assert status == 429
        assert body["code"] == "rate_limited"
        assert "wait" in body["hint"].lower()
        assert body["error"] == msg

    @settings(max_examples=100)
    @given(msg=text)
    def test_search_failed_keeps_message(self, msg):
        err = SearchFailed(msg or "no results", hint="relax the query")
        status, body = raise_and_map(err)
        assert status == 500
        assert body == {"error": msg or "no results",
                        "code": "search_failed", "hint": "relax the query"}

    @settings(max_examples=100)
    @given(msg=text)
    def test_custom_tool_error_defaults(self, msg):
        status, body = raise_and_map(ToolError(msg))
        assert status == 500
        assert body == {"error": msg, "code": "internal_error"}


class TestStatusMapping:
    def test_keyerror_is_404_unknown_session(self):
        """Unknown session ids stay a 404 with a pointer to 'sessions'."""
        status, body = raise_and_map(KeyError("unknown session zzz"))
        assert status == 404
        assert body["code"] == "unknown_session"
        assert "sessions" in body["hint"]

    def test_valueerror_is_400(self):
        status, body = raise_and_map(ValueError("missing parameter(s): url"))
        assert status == 400

    def test_typeerror_is_400(self):
        status, body = raise_and_map(TypeError("bad payload"))
        assert status == 400


class TestTimeoutMappingProperties:
    @settings(max_examples=100)
    @given(ms=st.integers(1, 10**6), sel=text.filter(lambda s: s != ""))
    def test_playwright_timeouts_map_to_timeout_code(self, ms, sel):
        """The exact failure shape from ticket P1 must map to code=timeout."""
        exc = TimeoutError(
            f'Page.wait_for_selector: Timeout {ms}ms exceeded.\n'
            f'waiting for locator("{sel}")'
        )
        status, body = raise_and_map(exc)
        assert status == 500
        assert body["code"] == "timeout"
        assert body["hint"]          # actionable: retry / --timeout
        assert "\n" not in body["error"]  # one-line by default


class TestGeckoMappingProperties:
    @settings(max_examples=60,
              suppress_health_check=[HealthCheck.filter_too_much])
    @given(
        prefix=text.filter(lambda s: not any(m in s for m, _, _ in _GECKO_HINTS)),
        suffix=text.filter(lambda s: not any(m in s for m, _, _ in _GECKO_HINTS)),
        marker_code_hint=st.sampled_from(_GECKO_HINTS),
    )
    def test_each_gecko_marker_maps_to_friendly_error(self, prefix, suffix, marker_code_hint):
        """P10: raw NS_ERROR_*/SSL strings become (code, hint) pairs."""
        marker, code, hint = marker_code_hint
        exc = RuntimeError(f"page.goto: {prefix}{marker}{suffix}")
        _, body = raise_and_map(exc)
        assert body["code"] == code
        assert body["hint"] == hint

    @settings(max_examples=50)
    @given(target=st.from_regex(r"https://[a-z]+\.(example|test)/[\w/-]*", fullmatch=True))
    def test_unknown_host_is_dns_error(self, target):
        """The dead-domain case from ticket P10 gets a dns_error hint."""
        exc = RuntimeError(
            f"page.goto: net::NS_ERROR_UNKNOWN_HOST at {target}"
        )
        _, body = raise_and_map(exc)
        assert body["code"] == "dns_error"
        assert "does not exist" in body["hint"]
