"""`phip object new`, `phip transition`, `phip relate` — composite write commands.

Each one builds the appropriate signed event and pushes it (or prints
it if --dry-run). Shares signing + remote-resolution wiring.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from phip import sign_event

from phip_cli.commands.server_cmd import _resolve_remote
from phip_cli.config import Config, Paths, load_config, paths
from phip_cli.http import HTTPError, create_object, head_hash_of, push_event
from phip_cli.identity import Identity, load_identity
from phip_cli.remote import Remote
from phip_cli.uri import authority_for_new, expand


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_ident_and_remote(
    args: argparse.Namespace,
) -> tuple[Paths, Config, Identity, Remote]:
    p = paths()
    cfg = load_config(p)
    name = args.key or cfg.default_identity
    if not name:
        raise SystemExit("no key specified and no default identity set")
    ident = load_identity(p, name)
    remote = _resolve_remote(args.remote)
    return p, cfg, ident, remote


def _maybe_dry_run(signed: dict[str, Any], dry_run: bool) -> bool:
    """Returns True if the caller should stop (dry-run mode)."""
    if dry_run:
        print(json.dumps(signed, indent=2))
        return True
    return False


def add(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    # ── object new ────────────────────────────────────────────
    obj = sub.add_parser("object", help="Object lifecycle commands.")
    osub = obj.add_subparsers(dest="subcommand", required=True)

    on = osub.add_parser(
        "new", help="Create a new object: build signed `created` event + POST /objects."
    )
    on.add_argument("object_type", help="e.g. component, fixture, lot, actor")
    on.add_argument(
        "id_or_uri",
        help="Local id (expanded against default authority + namespace) or full phip:// URI.",
    )
    on.add_argument(
        "--namespace",
        help="Override default_namespace. Required if the URI is shorthand and no default is set.",
    )
    on.add_argument("--state", default="prototype", help="Initial lifecycle state.")
    on.add_argument(
        "--attributes", help="JSON object for payload.attributes (e.g. namespaced fields)."
    )
    on.add_argument("--notes")
    on.add_argument("--remote")
    on.add_argument("--key")
    on.add_argument(
        "--dry-run",
        action="store_true",
        help="Build + sign but don't POST; print the signed event.",
    )
    on.set_defaults(func=run_object_new)

    # ── transition ───────────────────────────────────────────
    tr = sub.add_parser("transition", help="Push a `transitioned` event for a state change.")
    tr.add_argument("phip_uri_or_id")
    tr.add_argument("--to", required=True, dest="to_state", help="Target lifecycle state.")
    tr.add_argument(
        "--from",
        dest="from_state",
        help="Optional explicit `from` (else the server has it).",
    )
    tr.add_argument("--reason", help="Free-form reason string.")
    tr.add_argument("--remote")
    tr.add_argument("--key")
    tr.add_argument("--dry-run", action="store_true")
    tr.set_defaults(func=run_transition)

    # ── relate ───────────────────────────────────────────────
    rel = sub.add_parser("relate", help="Push a `relation_added` event linking two objects.")
    rel.add_argument("phip_uri_or_id", help="Source object (the one the relation is added to).")
    rel.add_argument("target_uri_or_id", help="Target object the relation points at.")
    rel.add_argument(
        "--type",
        required=True,
        dest="relation_type",
        help="Relation type, e.g. contains, located_at, connected_to, manufactured_by.",
    )
    rel.add_argument("--remote")
    rel.add_argument("--key")
    rel.add_argument("--dry-run", action="store_true")
    rel.set_defaults(func=run_relate)


# ── implementations ────────────────────────────────────────────────


def run_object_new(args: argparse.Namespace) -> int:
    try:
        p, cfg, ident, remote = _load_ident_and_remote(args)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1

    # Compute phip_id. If `id_or_uri` is shorthand, expand against the
    # provided --namespace override or config.default_namespace.
    if args.id_or_uri.startswith("phip://"):
        phip_id = args.id_or_uri
    else:
        ns = args.namespace or cfg.default_namespace
        if not ns:
            print(
                "shorthand id given but --namespace / config.default_namespace is unset",
                file=sys.stderr,
            )
            return 2
        try:
            authority = authority_for_new(p, cfg)
        except SystemExit as e:
            print(str(e), file=sys.stderr)
            return 2
        phip_id = f"phip://{authority}/{ns}/{args.id_or_uri}"

    payload: dict[str, Any] = {"object_type": args.object_type, "state": args.state}
    if args.attributes:
        try:
            payload["attributes"] = json.loads(args.attributes)
        except json.JSONDecodeError as e:
            print(f"--attributes is not valid JSON: {e}", file=sys.stderr)
            return 2
    if args.notes:
        payload["notes"] = args.notes

    unsigned: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "phip_id": phip_id,
        "type": "created",
        "timestamp": _utc_now_iso(),
        "actor": ident.key_id,
        "previous_hash": "genesis",
        "payload": payload,
    }
    signed = sign_event(unsigned, ident.keypair.private, ident.key_id)

    if _maybe_dry_run(signed, args.dry_run):
        return 0

    namespace = phip_id.removeprefix("phip://").split("/", 2)[1]
    try:
        result = create_object(remote, namespace, signed)
    except HTTPError as e:
        print(
            f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
            file=sys.stderr,
        )
        return 1
    print(f"Created {phip_id}")
    print(f"  type:      {args.object_type}")
    print(f"  state:     {args.state}")
    print(f"  head_hash: {result.get('head_hash')}")
    return 0


def run_transition(args: argparse.Namespace) -> int:
    try:
        p, cfg, ident, remote = _load_ident_and_remote(args)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1

    try:
        phip_uri = expand(args.phip_uri_or_id, p, cfg)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 2

    payload: dict[str, Any] = {"to": args.to_state}
    if args.from_state:
        payload["from"] = args.from_state
    if args.reason:
        payload["reason"] = args.reason

    try:
        prev = head_hash_of(remote, phip_uri)
    except HTTPError as e:
        print(
            f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
            file=sys.stderr,
        )
        return 1

    unsigned: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "phip_id": phip_uri,
        "type": "transitioned",
        "timestamp": _utc_now_iso(),
        "actor": ident.key_id,
        "previous_hash": prev,
        "payload": payload,
    }
    signed = sign_event(unsigned, ident.keypair.private, ident.key_id)

    if _maybe_dry_run(signed, args.dry_run):
        return 0

    try:
        result = push_event(remote, phip_uri, signed)
    except HTTPError as e:
        print(
            f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
            file=sys.stderr,
        )
        return 1
    print(f"Transitioned {phip_uri}")
    print(f"  to:        {args.to_state}")
    print(f"  head_hash: {result.get('head_hash')}")
    return 0


def run_relate(args: argparse.Namespace) -> int:
    try:
        p, cfg, ident, remote = _load_ident_and_remote(args)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1

    try:
        src = expand(args.phip_uri_or_id, p, cfg)
        tgt = expand(args.target_uri_or_id, p, cfg)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 2

    try:
        prev = head_hash_of(remote, src)
    except HTTPError as e:
        print(
            f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
            file=sys.stderr,
        )
        return 1

    payload = {"relation": {"type": args.relation_type, "phip_id": tgt}}
    unsigned: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "phip_id": src,
        "type": "relation_added",
        "timestamp": _utc_now_iso(),
        "actor": ident.key_id,
        "previous_hash": prev,
        "payload": payload,
    }
    signed = sign_event(unsigned, ident.keypair.private, ident.key_id)

    if _maybe_dry_run(signed, args.dry_run):
        return 0

    try:
        result = push_event(remote, src, signed)
    except HTTPError as e:
        print(
            f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
            file=sys.stderr,
        )
        return 1
    print(f"Related {src}")
    print(f"  --[{args.relation_type}]--> {tgt}")
    print(f"  head_hash: {result.get('head_hash')}")
    return 0
