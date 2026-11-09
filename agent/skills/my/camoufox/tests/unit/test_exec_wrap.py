"""Unit tests: /exec code wrapping (the async-locals capture)."""

import asyncio

from camoufox_tool.server import build_exec_src


def run_snippet(code: str) -> dict:
    """Mirror of exec_code's core, without a browser."""
    glb = {"asyncio": asyncio}
    exec(compile(build_exec_src(code), "<agent-code>", "exec"), glb)  # noqa: S102
    return asyncio.run(glb["__agent_main__"]())


def test_returns_locals_minus_dunders():
    out = run_snippet("result = 41 + 1")
    assert out["result"] == 42


def test_await_works_at_top_level():
    out = run_snippet(
        "await asyncio.sleep(0)\n"
        "result = 'done'"
    )
    assert out["result"] == "done"


def test_print_is_not_captured_here_only_vars():
    # print capture happens in exec_code via redirect_stdout; here we only
    # verify locals collection is unaffected by prints.
    out = run_snippet("print('hi')\nresult = 1")
    assert out["result"] == 1


def test_empty_code_is_valid_noop():
    out = run_snippet("")
    assert isinstance(out, dict)


def test_multiline_and_helper_functions():
    code = (
        "async def helper():\n"
        "    return 7\n"
        "result = await helper()"
    )
    assert run_snippet(code)["result"] == 7


def test_generated_source_is_compilable_for_arbitrary_code():
    src = build_exec_src("x = 1\ny = x + 1")
    compile(src, "<test>", "exec")  # must not raise
