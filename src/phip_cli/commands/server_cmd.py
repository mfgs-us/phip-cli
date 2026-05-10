"""`phip get|history|push|create|query|whoami` — talk to the configured remote."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from phip import parse_uri

from phip_cli.config import load_config, paths
from phip_cli.http import (
    HTTPError,
    create_object,
    get_history,
    get_meta,
    get_object,
    iter_history,
    push_event,
    query_namespace,
)
from phip_cli.identity import load_identity
from phip_cli.output import add_format_flag, emit
from phip_cli.remote import Remote, load_remote


def _resolve_remote(remote_arg: str | None) -> Remote:
    p = paths()
    name = remote_arg or load_config(p).default_remote
    if not name:
        raise SystemExit(
            "no remote configured. Pass --remote NAME or set one with `phip remote use`."
        )
    return load_remote(p, name)


def add(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    g = sub.add_parser("get", help="Fetch an object from the remote.")
    g.add_argument("uri", help="phip:// URI.")
    g.add_argument("--remote", help="Remote name (defaults to current default).")
    g.add_argument("--history", type=int, default=10, help="History tail length.")
    add_format_flag(g)
    g.set_defaults(func=run_get)

    h = sub.add_parser("history", help="Fetch full event history (paginated).")
    h.add_argument("uri")
    h.add_argument("--remote")
    h.add_argument("--limit", type=int)
    h.add_argument("--cursor")
    h.add_argument(
        "--all", action="store_true", help="Walk every page, not just the first."
    )
    add_format_flag(h)
    h.set_defaults(func=run_history)

    c = sub.add_parser("create", help="Push a signed `created` event to the remote.")
    c.add_argument("event_file", help="Path to a JSON file with the signed event, or - for stdin.")
    c.add_argument("--remote")
    c.set_defaults(func=run_create)

    pu = sub.add_parser("push", help="Push a signed event to the remote.")
    pu.add_argument("event_file", help="Path to a JSON file with the signed event, or - for stdin.")
    pu.add_argument("--remote")
    pu.set_defaults(func=run_push)

    q = sub.add_parser("query", help="Query objects in a namespace on the remote.")
    q.add_argument("namespace")
    q.add_argument("--remote")
    q.add_argument("--type", dest="object_type", help="Filter by object_type.")
    q.add_argument("--state", help="Filter by state.")
    q.add_argument("--prefix", dest="phip_id_prefix", help="Filter by phip_id prefix.")
    q.add_argument("--limit", type=int, default=50)
    add_format_flag(q)
    q.set_defaults(func=run_query)

    m = sub.add_parser("meta", help="Fetch /.well-known/phip/meta from the remote.")
    m.add_argument("--remote")
    add_format_flag(m)
    m.set_defaults(func=run_meta)

    w = sub.add_parser("whoami", help="Show the default identity + default remote.")
    w.set_defaults(func=run_whoami)


def _read_event(path: str) -> dict[str, object]:
    if path == "-":
        raw = sys.stdin.read()
    else:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"event file is not valid JSON: {e}") from e
    if not isinstance(loaded, dict):
        raise SystemExit("event file must contain a JSON object")
    return loaded


def _print_json(obj: object) -> None:
    print(json.dumps(obj, indent=2))


def _wrap_http(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> int:
    try:
        result = fn(*args, **kwargs)
    except HTTPError as e:
        print(
            f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
            file=sys.stderr,
        )
        return 1
    _print_json(result)
    return 0


def _emit_or_error(fn: Callable[..., Any], fmt: str, table_args: dict[str, Any] | None = None,
                   *args: Any, **kwargs: Any) -> int:
    try:
        result = fn(*args, **kwargs)
    except HTTPError as e:
        print(
            f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
            file=sys.stderr,
        )
        return 1
    if table_args is not None:
        emit(result, fmt, **table_args)
    else:
        emit(result, fmt)
    return 0


def run_get(args: argparse.Namespace) -> int:
    rem = _resolve_remote(args.remote)
    table_rows = None
    table_columns = None
    if args.format == "table":
        # For an object response, project the history list as the table.
        try:
            obj = get_object(rem, args.uri, history=args.history)
        except HTTPError as e:
            print(
                f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
                file=sys.stderr,
            )
            return 1
        history = obj.get("history") or []
        table_rows = [
            {
                "ts": ev.get("timestamp", ""),
                "type": ev.get("type", ""),
                "id": str(ev.get("event_id", ""))[:8],
                "actor": ev.get("actor", ""),
            }
            for ev in history
        ]
        table_columns = ["ts", "type", "id", "actor"]
        print(f"{obj.get('phip_id')}")
        print(
            f"  type={obj.get('object_type')} state={obj.get('state')} "
            f"events={obj.get('history_length')}"
        )
        print()
        emit(obj, "table", table_rows=table_rows, table_columns=table_columns)
        return 0
    return _emit_or_error(get_object, args.format, None, rem, args.uri, history=args.history)


def run_history(args: argparse.Namespace) -> int:
    rem = _resolve_remote(args.remote)
    if args.all:
        try:
            events = list(iter_history(rem, args.uri, page_size=args.limit))
        except HTTPError as e:
            print(
                f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
                file=sys.stderr,
            )
            return 1
        body = {"phip_id": args.uri, "history_length": len(events), "events": events}
    else:
        try:
            body = get_history(rem, args.uri, limit=args.limit, cursor=args.cursor)
        except HTTPError as e:
            print(
                f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
                file=sys.stderr,
            )
            return 1

    if args.format == "table":
        rows = [
            {
                "ts": ev.get("timestamp", ""),
                "type": ev.get("type", ""),
                "id": str(ev.get("event_id", ""))[:8],
                "actor": ev.get("actor", ""),
            }
            for ev in body.get("events", [])
        ]
        emit(body, "table", table_rows=rows, table_columns=["ts", "type", "id", "actor"])
    else:
        emit(body, args.format)
    return 0


def run_create(args: argparse.Namespace) -> int:
    rem = _resolve_remote(args.remote)
    event = _read_event(args.event_file)
    phip_id = str(event.get("phip_id", ""))
    if not phip_id:
        print("event has no phip_id", file=sys.stderr)
        return 2
    try:
        parsed = parse_uri(phip_id)
    except ValueError as e:
        print(f"event.phip_id is not a valid PhIP URI: {e}", file=sys.stderr)
        return 2
    return _wrap_http(create_object, rem, parsed.namespace, event)


def run_push(args: argparse.Namespace) -> int:
    rem = _resolve_remote(args.remote)
    event = _read_event(args.event_file)
    phip_id = str(event.get("phip_id", ""))
    if not phip_id:
        print("event has no phip_id", file=sys.stderr)
        return 2
    return _wrap_http(push_event, rem, phip_id, event)


def run_query(args: argparse.Namespace) -> int:
    rem = _resolve_remote(args.remote)
    body: dict[str, object] = {"limit": args.limit}
    if args.object_type:
        body["object_type"] = args.object_type
    if args.state:
        body["state"] = args.state
    if args.phip_id_prefix:
        body["phip_id_prefix"] = args.phip_id_prefix
    try:
        result = query_namespace(rem, args.namespace, body)
    except HTTPError as e:
        print(
            f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
            file=sys.stderr,
        )
        return 1
    if args.format == "table":
        rows = [
            {
                "phip_id": r.get("phip_id", ""),
                "type": r.get("object_type", ""),
                "state": r.get("state", ""),
                "events": r.get("history_length", ""),
            }
            for r in result.get("results", [])
        ]
        emit(result, "table", table_rows=rows, table_columns=["phip_id", "type", "state", "events"])
    else:
        emit(result, args.format)
    return 0


def run_meta(args: argparse.Namespace) -> int:
    rem = _resolve_remote(args.remote)
    try:
        result = get_meta(rem)
    except HTTPError as e:
        print(
            f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
            file=sys.stderr,
        )
        return 1
    emit(result, args.format)
    return 0


def run_whoami(args: argparse.Namespace) -> int:  # noqa: ARG001
    p = paths()
    cfg = load_config(p)
    if cfg.default_identity:
        try:
            ident = load_identity(p, cfg.default_identity)
            print(f"identity: {ident.name}  ({ident.key_id})")
        except (FileNotFoundError, ValueError):
            print(f"identity: {cfg.default_identity}  (file missing!)")
    else:
        print("identity: (none)")

    if cfg.default_remote:
        try:
            rem = load_remote(p, cfg.default_remote)
            print(f"remote:   {rem.name}  -> {rem.url}  ({rem.authority})")
        except (FileNotFoundError, ValueError):
            print(f"remote:   {cfg.default_remote}  (missing!)")
    else:
        print("remote:   (none)")
    return 0
