"""`phip show <phip-uri>` — formatted, human-readable history view."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from phip_cli.commands.server_cmd import _resolve_remote
from phip_cli.config import load_config, paths
from phip_cli.http import HTTPError, get_object, iter_history
from phip_cli.output import add_format_flag, emit
from phip_cli.uri import expand


def add(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser(
        "show",
        help="Formatted history view of an object (use --all to walk every page).",
    )
    p.add_argument("phip_uri")
    p.add_argument("--remote")
    p.add_argument(
        "--all", action="store_true", help="Fetch the full history (default: 10 events)."
    )
    p.add_argument(
        "--limit", type=int, default=10, help="Tail length when --all is not used."
    )
    add_format_flag(p)
    p.set_defaults(func=run)


def _summarize(event: dict[str, Any]) -> dict[str, Any]:
    """Compact dict for display."""
    payload = event.get("payload", {}) or {}
    out: dict[str, Any] = {
        "ts": event.get("timestamp", ""),
        "type": event.get("type", ""),
        "id": str(event.get("event_id", ""))[:8],
        "actor": event.get("actor", ""),
    }
    if event.get("type") == "measurement":
        out["metric"] = payload.get("metric", "")
        if "value" in payload:
            out["value"] = payload["value"]
            if "unit" in payload:
                out["unit"] = payload["unit"]
        for k in ("rig", "instrument", "method"):
            if payload.get(k):
                out[k] = payload[k]
        ext = payload.get("external_ref")
        if isinstance(ext, dict) and "content_hash" in ext:
            out["blob"] = str(ext["content_hash"]).removeprefix("sha256:")[:12]
    elif event.get("type") == "created":
        out["object_type"] = payload.get("object_type", "")
        out["state"] = payload.get("state", "")
    if payload.get("notes"):
        out["notes"] = payload["notes"]
    return out


def run(args: argparse.Namespace) -> int:
    p = paths()
    cfg = load_config(p)
    try:
        phip_uri = expand(args.phip_uri, p, cfg)
        remote = _resolve_remote(args.remote)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1

    try:
        if args.all:
            events = list(iter_history(remote, phip_uri))
            obj = get_object(remote, phip_uri, history=0)
        else:
            obj = get_object(remote, phip_uri, history=args.limit)
            events = obj.get("history") or []
    except HTTPError as e:
        print(
            f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
            file=sys.stderr,
        )
        return 1

    summarized = [_summarize(ev) for ev in events]

    if args.format == "table":
        # Build a unified column set across all rows; tables don't sparse well.
        common = ["ts", "type", "id"]
        rest_seen: list[str] = []
        for r in summarized:
            for k in r:
                if k not in common and k not in rest_seen:
                    rest_seen.append(k)
        cols = common + rest_seen
        print(f"{obj.get('phip_id')}")
        print(
            f"  type={obj.get('object_type')} state={obj.get('state')} "
            f"events={obj.get('history_length')}"
        )
        print()
        emit(summarized, "table", table_rows=summarized, table_columns=cols)
    elif args.format == "yaml":
        emit(
            {
                "phip_id": obj.get("phip_id"),
                "object_type": obj.get("object_type"),
                "state": obj.get("state"),
                "history_length": obj.get("history_length"),
                "head_hash": obj.get("head_hash"),
                "history": summarized,
            },
            "yaml",
        )
    else:
        emit(
            {
                "phip_id": obj.get("phip_id"),
                "object_type": obj.get("object_type"),
                "state": obj.get("state"),
                "history_length": obj.get("history_length"),
                "head_hash": obj.get("head_hash"),
                "history": summarized,
            },
            "json",
        )
    return 0
