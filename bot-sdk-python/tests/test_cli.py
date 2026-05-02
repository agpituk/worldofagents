"""arena-bot CLI smoke tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arena_bot.cli import build_parser


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    args = build_parser().parse_args(argv)
    rc = int(args.func(args) or 0)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_manifest_dump_emits_yaml(tmp_path: Path, capsys) -> None:
    src = tmp_path / "my_tools.py"
    src.write_text(
        "from arena_bot.user_tools import user_tool, param\n"
        "@user_tool(description='look then gather', parameters=[])\n"
        "def safe_gather():\n"
        "    yield {'do': 'look'}\n"
        "    yield {'do': 'gather'}\n"
    )
    rc, out, _ = _run(["manifest", "dump", str(src)], capsys)
    assert rc == 0
    assert "safe_gather" in out
    assert "look" in out


def test_manifest_validate_accepts_valid(tmp_path: Path, capsys) -> None:
    src = tmp_path / "manifest.yaml"
    src.write_text(
        "hero:\n"
        "  tools:\n"
        "    - name: safe_gather\n"
        "      description: x\n"
        "      steps:\n"
        "        - do: look\n"
        "        - do: gather\n"
    )
    rc, out, _ = _run(["manifest", "validate", str(src)], capsys)
    assert rc == 0
    assert "1 tool" in out


def test_manifest_validate_rejects_invalid(tmp_path: Path, capsys) -> None:
    src = tmp_path / "manifest.yaml"
    src.write_text(
        "hero:\n"
        "  tools:\n"
        "    - name: BadName\n"  # bad regex
        "      description: x\n"
        "      steps: [{do: look}]\n"
    )
    rc, _, err = _run(["manifest", "validate", str(src)], capsys)
    assert rc == 1
    assert "name" in err


def test_tools_simulate_runs_composite(tmp_path: Path, capsys) -> None:
    src = tmp_path / "manifest.yaml"
    src.write_text(
        "hero:\n"
        "  tools:\n"
        "    - name: safe_gather\n"
        "      description: x\n"
        "      steps:\n"
        "        - do: look\n"
        "        - do: gather\n"
    )
    rc, out, _ = _run(
        ["tools", "simulate", str(src), "--tool", "safe_gather", "--args", "{}"],
        capsys,
    )
    assert rc == 0
    assert "actions (2)" in out
    assert "look" in out
    assert "gather" in out
