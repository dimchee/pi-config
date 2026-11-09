"""Unit tests: pure DDG logic (tokens, URL unwrapping, markdown)."""

import pytest

from camoufox_tool.ddg import (
    decode_token,
    encode_token,
    filter_results,
    build_markdown,
    resolve_url,
)


class TestTokens:
    def test_round_trip(self):
        form = {"q": "test query", "s": "10", "vqd": "4-abc", "kl": "wt-wt"}
        token = encode_token("html", form)
        assert token and "=" not in token  # urlsafe, padding stripped
        assert decode_token(token) == ("html", form)

    def test_empty_form_gives_no_token(self):
        assert encode_token("lite", {}) is None
        assert encode_token("lite", None) is None

    def test_decode_accepts_missing_padding(self):
        import base64
        raw = base64.urlsafe_b64encode(b'{"a": "1"}').decode().rstrip("=")
        # pre-engine legacy tokens decode as the lite engine
        assert decode_token(raw) == ("lite", {"a": "1"})

    def test_decode_garbage_raises(self):
        with pytest.raises(Exception):
            decode_token("!!!not-base64!!!")


class TestResolveUrl:
    def test_unwraps_uddg_redirect(self):
        href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fkernel.org%2F&rut=abc"
        assert resolve_url(href) == "https://kernel.org/"

    def test_direct_link_passthrough(self):
        assert resolve_url("https://example.net/page") == "https://example.net/page"

    def test_protocol_relative(self):
        assert resolve_url("//example.org/x") == "https://example.org/x"

    def test_empty_is_none(self):
        assert resolve_url("") is None
        assert resolve_url(None) is None


class TestFilterResults:
    def test_drops_untitled_and_unresolvable(self):
        items = [
            {"title": "ok", "href": "https://a.example/", "domain": "a", "snippet": "s"},
            {"title": "", "href": "https://b.example/", "domain": "b", "snippet": ""},
            {"title": "no link", "href": "", "domain": "c", "snippet": ""},
        ]
        out = filter_results(items)
        assert [r["url"] for r in out] == ["https://a.example/"]

    def test_preserves_snippet_and_domain(self):
        out = filter_results([{"title": "t", "href": "//x.example/y",
                               "domain": "x.example", "snippet": "snip"}])
        assert out[0]["domain"] == "x.example"
        assert out[0]["snippet"] == "snip"


class TestMarkdown:
    RESULTS = [
        {"title": "One", "url": "https://one.example/", "snippet": "first"},
        {"title": "Two", "url": "https://two.example/", "snippet": ""},
    ]

    def test_numbered_items_and_indentation(self):
        md = build_markdown("q", self.RESULTS, None)
        assert '1. [One](https://one.example/)' in md
        assert '   first' in md                      # snippet indented
        assert '2. [Two](https://two.example/)' in md

    def test_no_snippet_means_no_indent_line(self):
        md = build_markdown("q", [self.RESULTS[1]], None)
        assert "   " not in md.split("\n")[1]

    def test_more_results_line_contains_token(self):
        token = encode_token("lite", {"s": "10"})
        md = build_markdown("q", self.RESULTS, token)
        line = md.splitlines()[-1]
        assert line == f"More results: cam.py search --next {token}"

    def test_end_marker_without_token(self):
        md = build_markdown("q", self.RESULTS, None)
        assert "_No more results._" in md

    def test_empty_results(self):
        md = build_markdown("q", [], None)
        assert "_No results found._" in md
