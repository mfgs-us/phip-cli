"""`phip schema validate|list|show` — JSON Schema validation against vendored schemas."""

from __future__ import annotations

import argparse
import json
import sys
from importlib import resources
from pathlib import Path

import jsonschema

_SCHEMA_PACKAGE = "phip_cli._schemas"


def _list_schema_files() -> list[str]:
    files = resources.files(_SCHEMA_PACKAGE)
    on_disk = sorted(
        p.name.removesuffix(".json") for p in files.iterdir() if p.name.endswith(".json")
    )
    return sorted({*on_disk, *_ALIASES.keys()})


_ALIASES = {
    # `event` validates a single signed event by lifting core.json's
    # $defs/event into a self-contained schema (refs in the subschema
    # resolve against the embedded $defs map).
    "event": ("core", "event"),
    # `object` is the default reading of `core` — full resolved object
    # with phip_id / object_type / state / history.
    "object": ("core", None),
}


def _load_schema(name: str) -> dict[str, object]:
    files = resources.files(_SCHEMA_PACKAGE)
    if name in _ALIASES:
        base_name, defs_key = _ALIASES[name]
        base = json.loads((files / f"{base_name}.json").read_text(encoding="utf-8"))
        if defs_key is None:
            return base
        defs = base.get("$defs", {})
        if defs_key not in defs:
            raise FileNotFoundError(f"{name} (alias to {base_name}#/$defs/{defs_key}; missing)")
        # Re-export the subschema with the original $defs so internal refs resolve.
        return {**defs[defs_key], "$defs": defs}
    target = files / f"{name}.json"
    if not target.is_file():
        raise FileNotFoundError(name)
    return json.loads(target.read_text(encoding="utf-8"))


def add(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("schema", help="Validate documents against vendored PhIP JSON Schemas.")
    s = p.add_subparsers(dest="subcommand", required=True)

    ls = s.add_parser("list", help="List available schemas.")
    ls.set_defaults(func=run_list)

    sh = s.add_parser("show", help="Print one schema as JSON.")
    sh.add_argument("name")
    sh.set_defaults(func=run_show)

    va = s.add_parser("validate", help="Validate a JSON file against a schema.")
    va.add_argument("input", help="JSON file path or - for stdin.")
    va.add_argument(
        "--schema",
        required=True,
        help=(
            "Schema name (run `phip schema list` to see available). "
            "Common: core, capability-token, bundle-manifest, mechanical, datacenter, software."
        ),
    )
    va.set_defaults(func=run_validate)


def run_list(args: argparse.Namespace) -> int:  # noqa: ARG001
    for name in _list_schema_files():
        print(name)
    return 0


def run_show(args: argparse.Namespace) -> int:
    try:
        s = _load_schema(args.name)
    except FileNotFoundError:
        print(
            f"unknown schema {args.name!r}; run `phip schema list` for available names",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(s, indent=2))
    return 0


def run_validate(args: argparse.Namespace) -> int:
    try:
        schema = _load_schema(args.schema)
    except FileNotFoundError:
        print(
            f"unknown schema {args.schema!r}; run `phip schema list` for available names",
            file=sys.stderr,
        )
        return 1

    raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"input is not valid JSON: {e}", file=sys.stderr)
        return 2

    try:
        jsonschema.validate(instance=doc, schema=schema)
    except jsonschema.ValidationError as e:
        print(f"FAIL: {e.message}", file=sys.stderr)
        if e.path:
            print(f"  at path: {'.'.join(str(p) for p in e.path)}", file=sys.stderr)
        return 1
    except jsonschema.SchemaError as e:
        print(f"schema itself is malformed: {e.message}", file=sys.stderr)
        return 2
    print("OK")
    return 0
