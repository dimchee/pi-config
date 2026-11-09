"""Property-based tests (Hypothesis) for the pure DDG/config logic.

These complement the example-based tests in test_ddg.py by checking
invariants over wide input spaces instead of hand-picked cases.
"""

import re

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from camoufox_tool.config import Config
from camoufox_tool.ddg import (
    _clean,
    build_markdown,
    decode_token,
    encode_token,
    filter_results,
    resolve_url,
)

# json.dumps must UTF-8-encode everything -> exclude lone surrogates.
text = st.text(alphabet=st.characters(codec="utf-8"), max_size=64)
nonempty_text = text.filter(lambda s: s != "")
# encode_token({}) is documented to return None (no next page) - that
# contract is covered by an example test; properties need real payloads.
forms = st.dictionaries(nonempty_text, text, min_size=1, max_size=12)
urls = st.from_regex(r"https://example\.[a-z]+/[\w/%~.-]*", fullmatch=True)

result_items = st.fixed_dictionaries(
    {
        "title": text,
        "href": urls,
        "domain": text,
        "snippet": text,
    }
)


class TestTokenProperties:
    @settings(max_examples=200)
    @given(form=forms, engine=st.sampled_from(["lite", "html"]))
    def test_round_trip(self, form, engine):
        token = encode_token(engine, form)
        assert isinstance(token, str)
        assert decode_token(token) == (engine, form)

    @settings(max_examples=200)
    @given(form=forms)
    def test_token_is_url_safe_without_padding(self, form):
        import base64

        token = encode_token("lite", form)
        assert re.fullmatch(r"[A-Za-z0-9_-]+", token)  # urlsafe alphabet, no '='
        assert "=" not in token
        base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))  # always decodable


class TestResolveUrlProperties:
    @settings(max_examples=300)
    @given(target=urls)
    def test_uddg_wrapping_is_always_unwrapped(self, target):
        from urllib.parse import urlencode

        href = "//duckduckgo.com/l/?" + urlencode({"uddg": target, "rut": "x"})
        assert resolve_url(href) == target

    @settings(max_examples=300)
    @given(url=urls)
    def test_direct_https_links_pass_through(self, url):
        assert resolve_url(url) == url

    @settings(max_examples=300)
    @given(href=st.one_of(st.none(), text))
    def test_never_returns_empty_string(self, href):
        out = resolve_url(href)
        assert out is None or out != ""


class TestFilterResultsProperties:
    @settings(max_examples=200)
    @given(items=st.lists(result_items, max_size=20))
    def test_matches_manual_comprehension(self, items):
        out = filter_results(items)
        expected = [
            {
                "title": r["title"],
                "url": resolve_url(r["href"]),
                "domain": r["domain"],
                "snippet": r["snippet"],
            }
            for r in items
            if resolve_url(r["href"]) and r["title"].strip()
        ]
        assert out == expected

    @settings(max_examples=200)
    @given(items=st.lists(result_items, max_size=20))
    def test_output_invariants(self, items):
        out = filter_results(items)
        assert len(out) <= len(items)
        for r in out:
            assert r["title"].strip()      # no blank titles survive
            assert r["url"]                # no unresolvable links survive
            assert set(r) == {"title", "url", "domain", "snippet"}

    @settings(max_examples=100)
    @given(items=st.lists(result_items, min_size=1, max_size=10))
    def test_all_blank_titles_yields_empty(self, items):
        blanked = [{**r, "title": "   "} for r in items]
        assert filter_results(blanked) == []


class TestMarkdownProperties:
    @settings(max_examples=200)
    @given(
        query=text,
        results=st.lists(result_items, max_size=20),
        has_token=st.booleans(),
        form=forms,
    )
    def test_structure(self, query, results, has_token, form):
        # mirror the production pipeline: filter first, then render
        results = filter_results(results)
        token = encode_token("lite", form) if has_token else None
        md = build_markdown(query if query else "q", results, token)

        lines = md.splitlines()
        # header echoes the query
        assert lines[0].startswith("# DuckDuckGo results for")
        # results are numbered sequentially
        numbered = [ln for ln in lines if re.match(r"^\d+\. \[", ln)]
        assert [f"{i}." for i in range(1, len(results) + 1)] == [
            ln.split(".")[0] + "." for ln in numbered
        ]
        # every cleaned title/url pair appears
        for r in results:
            assert f"[{_clean(r['title'])}]({r['url']})" in md
        # footer contract: token iff more-results line, and it is last
        if token:
            assert lines[-1] == f"More results: cam.py search --next {token}"
        else:
            assert "_No more results._" in lines[-2:]

    @settings(max_examples=200)
    @given(
        results=st.lists(result_items, max_size=20),
    )
    def test_snippets_appear_indented_iff_nonempty(self, results):
        # mirror build_markdown's cleaning (reuse its sanitizer to avoid drift):
        # control/line-boundary chars are removed, then a snippet renders as an
        # indented line iff anything remains.
        from camoufox_tool.ddg import _clean

        results = filter_results(results)
        md_lines = build_markdown("q", results, None).splitlines()
        for r in results:
            snippet = _clean(r["snippet"])
            if snippet.strip():
                assert f"   {snippet}" in md_lines
            else:
                assert f"   {snippet}" not in md_lines


class TestConfigFromEnv:
    @settings(
        max_examples=100,
        # monkeypatch is function-scoped but each generated example overwrites
        # all env vars it cares about, so reuse across examples is safe.
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        session_idle=st.floats(min_value=0.01, max_value=1e6, allow_nan=False),
        instance_idle=st.floats(min_value=0.01, max_value=1e6, allow_nan=False),
        exec_timeout=st.floats(min_value=0.01, max_value=1e6, allow_nan=False),
    )
    def test_numeric_env_strings_are_parsed(self, monkeypatch, session_idle, instance_idle, exec_timeout):
        monkeypatch.setenv("CAMOUFOX_SESSION_IDLE", str(session_idle))
        monkeypatch.setenv("CAMOUFOX_INSTANCE_IDLE", str(instance_idle))
        monkeypatch.setenv("CAMOUFOX_EXEC_TIMEOUT", str(exec_timeout))
        cfg = Config.from_env()
        assert cfg.session_idle == pytest.approx(session_idle)
        assert cfg.instance_idle == pytest.approx(instance_idle)
        assert cfg.exec_timeout == pytest.approx(exec_timeout)

    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        garbage=st.text(
            alphabet=st.characters(codec="utf-8", exclude_characters="\x00"),
            max_size=32,
        ).filter(lambda s: not _is_number(s))
    )
    def test_invalid_env_falls_back_to_defaults(self, monkeypatch, garbage):
        monkeypatch.setenv("CAMOUFOX_SESSION_IDLE", garbage)
        cfg = Config.from_env()
        assert cfg.session_idle == Config.session_idle


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False
