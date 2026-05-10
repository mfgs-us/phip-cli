"""Output formatting: json (default), yaml, table.

Used by read-side commands (`get`, `history`, `query`, `meta`,
`whoami`, `key list`, `remote list`, `show`).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

VALID_FORMATS = ("json", "yaml", "table")


def add_format_flag(parser: argparse.ArgumentParser) -> None:
    """Standard --format flag plus convenience aliases --table / --yaml."""
    g = parser.add_mutually_exclusive_group()
    g.add_argument(
        "--format",
        choices=VALID_FORMATS,
        default="json",
        help="Output format (default: json).",
    )
    g.add_argument(
        "--table",
        dest="format",
        action="store_const",
        const="table",
        help="Shorthand for --format=table.",
    )
    g.add_argument(
        "--yaml",
        dest="format",
        action="store_const",
        const="yaml",
        help="Shorthand for --format=yaml.",
    )


def emit_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str))


def emit_yaml(obj: Any) -> None:
    import yaml

    print(yaml.safe_dump(obj, sort_keys=False, default_flow_style=False).rstrip())


def emit_table(rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    """Pretty-print a list of dicts as a fixed-width table.

    `columns` controls order + presence; default uses keys from the
    first row in insertion order.
    """
    if not rows:
        print("(no rows)")
        return

    if columns is None:
        columns = list(rows[0].keys())

    def cell(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, default=str)
        return str(value)

    widths = {c: len(c) for c in columns}
    for row in rows:
        for c in columns:
            widths[c] = max(widths[c], len(cell(row.get(c))))

    sep = "  "
    header = sep.join(c.ljust(widths[c]) for c in columns)
    line = sep.join("-" * widths[c] for c in columns)
    print(header)
    print(line)
    for row in rows:
        print(sep.join(cell(row.get(c)).ljust(widths[c]) for c in columns))


def emit(
    obj: Any,
    fmt: str,
    *,
    table_rows: list[dict[str, Any]] | None = None,
    table_columns: list[str] | None = None,
) -> None:
    """Single dispatch: emit `obj` in `fmt`. For table format, pass
    `table_rows` (and optionally `table_columns`) explicitly because
    not every JSON shape projects cleanly to a table."""
    if fmt == "yaml":
        emit_yaml(obj)
    elif fmt == "table":
        if table_rows is None:
            print(
                "warning: this command does not support --table; falling back to json",
                file=sys.stderr,
            )
            emit_json(obj)
        else:
            emit_table(table_rows, table_columns)
    else:
        emit_json(obj)
