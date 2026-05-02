"""arena-bot CLI — manifest dump/validate + tools simulate.

Subcommands:
  manifest dump <hero_module.py>            → emit canonical YAML
                                                from @user_tool / @override
                                                decorated functions
  manifest validate <manifest.yaml>          → run the same validator the
                                                world-api uses, locally
  tools simulate <manifest.yaml>             → expand a tool against a
        --tool <name> --args '{"k": "v"}'    synthetic perception and
                                                print the trace tree
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from arena_bot.tool_dispatch import HeroToolset, expand_tool_call


# ---------------------------------------------------------------------------
# manifest dump
# ---------------------------------------------------------------------------


def cmd_manifest_dump(args: argparse.Namespace) -> int:
    """Import a Python module containing @user_tool / @override decorated
    functions; print the resulting `tools:` YAML to stdout."""
    src = Path(args.path).expanduser().resolve()
    if not src.exists():
        print(f"error: file not found: {src}", file=sys.stderr)
        return 1

    from arena_bot import user_tools as ut
    ut.reset_registry()

    spec = importlib.util.spec_from_file_location("user_tool_module", src)
    if spec is None or spec.loader is None:
        print(f"error: could not load module from {src}", file=sys.stderr)
        return 1
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        print(f"error: import failed: {exc}", file=sys.stderr)
        return 1

    tools = ut.collect_tools()
    if not tools:
        print("# no @user_tool or @override decorated functions found", file=sys.stderr)
        return 0
    print(ut.dump_tools_yaml())
    return 0


# ---------------------------------------------------------------------------
# manifest validate
# ---------------------------------------------------------------------------


def cmd_manifest_validate(args: argparse.Namespace) -> int:
    """Run the local subset of validation: parse the tools[] section and
    check shape, names, expressions. The full validator lives server-
    side; this CLI catches obvious errors before deploy."""
    src = Path(args.path).expanduser().resolve()
    if not src.exists():
        print(f"error: file not found: {src}", file=sys.stderr)
        return 1
    raw = src.read_bytes()
    try:
        doc = yaml.safe_load(raw) or {}
    except Exception as exc:
        print(f"error: yaml parse failed: {exc}", file=sys.stderr)
        return 1
    inner = doc.get("hero") if isinstance(doc.get("hero"), dict) else doc
    raw_tools = (inner or {}).get("tools") or []

    from arena_bot.tool_schema import ToolParseError, parse_tools
    try:
        parsed = parse_tools(raw_tools)
    except ToolParseError as exc:
        print(f"error: {exc.path}: {exc.message}", file=sys.stderr)
        return 1
    print(f"ok: parsed {len(parsed)} tool(s) successfully")
    for t in parsed:
        kind = getattr(t, "kind", "?")
        print(f"  - {kind}: {t.name}")
    return 0


# ---------------------------------------------------------------------------
# tools simulate
# ---------------------------------------------------------------------------


def cmd_tools_simulate(args: argparse.Namespace) -> int:
    """Run the dispatcher against a synthetic perception and print the
    trace tree + resolved action queue. Useful for iterating on a
    composite or override without redeploying.
    """
    src = Path(args.path).expanduser().resolve()
    if not src.exists():
        print(f"error: file not found: {src}", file=sys.stderr)
        return 1
    manifest = yaml.safe_load(src.read_bytes()) or {}
    toolset = HeroToolset.from_manifest(manifest)

    try:
        chosen_args = json.loads(args.args) if args.args else {}
    except Exception as exc:
        print(f"error: --args must be valid JSON: {exc}", file=sys.stderr)
        return 1

    # Synthetic namespace — minimal scalars + helpers always returning
    # safe defaults. Sufficient for dry-run.
    namespace: dict[str, Any] = {
        "hp": 30,
        "gold": 100,
        "zone": "market_square",
        "pos_x": 5,
        "pos_y": 5,
        "mana_current": 10,
        "mana_max": 10,
        "tick_id": 0,
        "in_pvp_zone": lambda: False,
        "hostile_visible": lambda: False,
        "any_hero_adjacent": lambda: False,
        "enemy_in_range": lambda: False,
        "weapon_equipped": lambda: True,
        "armor_equipped": lambda: False,
        "adjacent_to": lambda _slug: False,
        "visible": lambda _slug: False,
        "in_inventory": lambda _slug: False,
        "any_hero_visible": lambda: False,
        "item_at_my_tile": lambda _kind: False,
        "connection": lambda _slug: True,
    }

    events: list[tuple[str, dict]] = []

    def trace(event: str, payload: dict) -> None:
        events.append((event, payload))

    result = expand_tool_call(
        args.tool, chosen_args,
        toolset=toolset, namespace=namespace, trace=trace,
    )

    print(f"tool: {args.tool}({json.dumps(chosen_args)})")
    print(f"ok: {result.ok}")
    if result.reason:
        print(f"reason: {result.reason}")
    print()
    print("trace events:")
    for ev, payload in events:
        print(f"  {ev:30s} {json.dumps(payload)}")
    print()
    print(f"actions ({len(result.actions)}):")
    for i, action in enumerate(result.actions):
        print(f"  {i + 1}. {json.dumps(action)}")
    return 0 if result.ok else 1


# ---------------------------------------------------------------------------
# Argparse wiring
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arena-bot")
    subs = parser.add_subparsers(dest="command", required=True)

    manifest = subs.add_parser("manifest", help="manifest tooling")
    manifest_subs = manifest.add_subparsers(dest="subcommand", required=True)

    dump = manifest_subs.add_parser("dump", help="emit YAML from @user_tool/@override decorators")
    dump.add_argument("path", help="Python module with decorated functions")
    dump.set_defaults(func=cmd_manifest_dump)

    validate = manifest_subs.add_parser("validate", help="local manifest tools[] validation")
    validate.add_argument("path", help="manifest YAML")
    validate.set_defaults(func=cmd_manifest_validate)

    tools = subs.add_parser("tools", help="tools tooling")
    tools_subs = tools.add_subparsers(dest="subcommand", required=True)

    simulate = tools_subs.add_parser("simulate", help="dispatch a tool against a synthetic perception")
    simulate.add_argument("path", help="manifest YAML")
    simulate.add_argument("--tool", required=True, help="tool name to invoke")
    simulate.add_argument("--args", default="{}", help='JSON args, e.g. \'{"retreat_to": "hearthold"}\'')
    simulate.set_defaults(func=cmd_tools_simulate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
