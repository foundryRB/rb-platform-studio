"""The docs' MCP tool table and the server's registered tools, held equal.

Attests INT-DOCS-001. The tool table is the consumer's contract; the
@server.tool() registrations are what the door serves; neither moves alone.
The same discipline the events page carries against the publisher's
constants, applied to the tool roster.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from pytest_intent import intent

_ROOT = Path(__file__).resolve().parents[3]
_SERVER = _ROOT / "studio-backend/studio/adapters/inbound/mcp/server.py"
_PAGE = _ROOT / "docs/src/content/docs/reference/architecture.md"
_START = "## MCP tools"
_END = "## Platform settings"


def _registered_tools() -> set[str]:
    tree = ast.parse(_SERVER.read_text(encoding="utf-8"))
    tools: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            func = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(func, ast.Attribute) and func.attr == "tool":
                tools.add(node.name)
    return tools


def _stated_tools() -> set[str]:
    text = _PAGE.read_text(encoding="utf-8")
    section = text[text.index(_START) : text.index(_END)]
    stated: set[str] = set()
    for line in section.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        first_cell = line.split("|")[1]
        stated.update(
            token
            for token in re.findall(r"`([^`]+)`", first_cell)
            if re.fullmatch(r"[a-z][a-z0-9_]*", token)
        )
    return stated


@intent("INT-DOCS-001")
def test_the_tool_table_states_exactly_the_tools_the_server_registers() -> None:
    """INT-DOCS-001: the docs' tool table and the adapter's registrations agree."""
    registered = _registered_tools()
    assert registered, "the server registers no tools"
    stated = _stated_tools()
    assert stated == registered, (
        f"documented but not registered: {sorted(stated - registered)}; "
        f"registered but not documented: {sorted(registered - stated)}"
    )
