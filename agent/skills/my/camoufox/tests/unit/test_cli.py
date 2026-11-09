"""Unit tests for the CLI surface: new flags (P2/P4/P12/P14) and snippet
path resolution with a clear error (P7). No server is started."""

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from camoufox_tool.cli import _snippet_path, build_parser


class TestParserContract:
    def test_search_has_retry_timeout_engine_flags(self):
        """P1/P5/P14: retries, timeout and engine are first-class flags."""
        a = build_parser().parse_args(
            ["search", "q", "-n", "5", "--retries", "1",
             "--timeout", "45", "--engine", "html"]
        )
        assert a.retries == 1
        assert a.timeout == 45.0
        assert a.engine == "html"

    def test_open_print_sid_and_fail_on_http_error(self):
        """P4/P10: bare sid output + HTTP-error signaling."""
        a = build_parser().parse_args(
            ["open", "https://x.example/", "--print-sid", "--fail-on-http-error"]
        )
        assert a.print_sid and a.fail_on_http_error

    def test_text_accepts_optional_positional_url(self):
        """P2: `text <URL>` must be valid; so must session-less detection."""
        a = build_parser().parse_args(["text", "https://x.example/"])
        assert a.url == "https://x.example/" and a.sid is None

    def test_text_selector_flag(self):
        """P9: extraction can be restricted to a CSS selector."""
        a = build_parser().parse_args(["text", "--selector", "main", "--session", "s"])
        assert a.selector == "main" and a.sid == "s"

    def test_close_all_with_except(self):
        """P4/P11: close-all keeps one session alive."""
        a = build_parser().parse_args(["close-all", "--except", "abc123"])
        assert a.keep_sid == "abc123"

    def test_wait_exposes_timeout_ms(self):
        a = build_parser().parse_args(["wait", ".x", "--timeout-ms", "2500"])
        assert a.timeout_ms == 2500

    def test_debug_flag_exists_everywhere(self):
        """P3: full error payloads are opt-in via --debug."""
        for argv in (["search", "q"], ["sessions"], ["open", "https://x.example/"]):
            a = build_parser().parse_args(argv)
            # --debug lives on the shared parent; parse with it prepended
            a = build_parser().parse_args(["--debug", *argv])
            assert a.debug is True


class TestSnippetPath:
    def test_absolute_existing_file_passes_through(self, tmp_path):
        f = tmp_path / "snippet.py"
        f.write_text("result = 1")
        assert _snippet_path(str(f)) == f

    def test_relative_existing_file_resolves_against_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "s.py").write_text("x")
        assert _snippet_path("s.py") == tmp_path / "s.py"
        assert _snippet_path("./sub/../s.py") == tmp_path / "s.py"

    @settings(max_examples=50,
              suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(name=st.text(alphabet="ab_", min_size=1, max_size=8).filter(
        lambda s: ".." not in s))
    def test_missing_relative_path_error_names_resolved_target(self, name, tmp_path,
                                                               monkeypatch):
        """P7: the confusing failure becomes an explicit, absolute message."""
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "tmp" / f"{name}.py"
        with pytest.raises(FileNotFoundError) as ei:
            _snippet_path(f"./tmp/{name}.py")
        assert str(target) in str(ei.value)
        assert "absolute path" in str(ei.value)

    def test_missing_absolute_path_errors_with_path(self, tmp_path):
        missing = tmp_path / "nope.py"
        with pytest.raises(FileNotFoundError) as ei:
            _snippet_path(str(missing))
        assert str(missing) in str(ei.value)

    def test_tilde_expansion_uses_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        f = tmp_path / "home-snippet.py"
        f.write_text("x")
        assert _snippet_path("~/home-snippet.py") == f
