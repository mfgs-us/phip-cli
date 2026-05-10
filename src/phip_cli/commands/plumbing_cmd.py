"""`phip event sign|verify|hash|new`, `phip uri parse|format`, `phip canonicalize`."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone

from phip import (
    canonical_bytes,
    format_uri,
    hash_event,
    parse_uri,
    public_key_from_jwk,
    sign_event,
    verify_event,
)

from phip_cli.config import load_config, paths
from phip_cli.identity import list_identities, load_identity


def add(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    e = sub.add_parser("event", help="Event plumbing — sign / verify / hash / new.")
    es = e.add_subparsers(dest="subcommand", required=True)

    en = es.add_parser("new", help="Build an unsigned event scaffold from CLI args.")
    en.add_argument("--phip-id", required=True)
    en.add_argument("--type", required=True, dest="type_")
    en.add_argument(
        "--actor", help="Defaults to the default identity's key_id if not given."
    )
    en.add_argument("--previous-hash", default="genesis")
    en.add_argument("--payload", required=True, help="JSON object for the payload.")
    en.set_defaults(func=run_event_new)

    es_sign = es.add_parser("sign", help="Sign an event JSON file (or - for stdin).")
    es_sign.add_argument("input")
    es_sign.add_argument("--key", help="Identity name. Defaults to the default identity.")
    es_sign.set_defaults(func=run_event_sign)

    es_verify = es.add_parser(
        "verify", help="Verify an event signature against a known public key."
    )
    es_verify.add_argument("input")
    es_verify.add_argument(
        "--key", help="Identity name to verify against (uses its public key)."
    )
    es_verify.set_defaults(func=run_event_verify)

    es_hash = es.add_parser("hash", help="Compute the canonical event hash.")
    es_hash.add_argument("input")
    es_hash.set_defaults(func=run_event_hash)

    u = sub.add_parser("uri", help="PhIP URI helpers.")
    us = u.add_subparsers(dest="subcommand", required=True)

    up = us.add_parser("parse", help="Print URI components as JSON.")
    up.add_argument("uri")
    up.set_defaults(func=run_uri_parse)

    uf = us.add_parser("format", help="Build a phip:// URI from components.")
    uf.add_argument("--authority", required=True)
    uf.add_argument("--namespace", required=True)
    uf.add_argument("--local-id", required=True)
    uf.set_defaults(func=run_uri_format)

    c = sub.add_parser("canonicalize", help="JCS-canonicalize a JSON file (RFC 8785).")
    c.add_argument("input")
    c.set_defaults(func=run_canonicalize)


def _read_json(path: str) -> object:
    if path == "-":
        raw = sys.stdin.read()
    else:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    return json.loads(raw)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_identity_name(name: str | None) -> str:
    if name:
        return name
    p = paths()
    cfg = load_config(p)
    if cfg.default_identity:
        return cfg.default_identity
    idents = list_identities(p)
    if len(idents) == 1:
        return idents[0].name
    raise SystemExit(
        "no key specified and no default identity set. "
        "Use --key NAME or set one with `phip key use NAME`."
    )


def run_event_new(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(args.payload)
    except json.JSONDecodeError as e:
        print(f"--payload is not valid JSON: {e}", file=sys.stderr)
        return 2
    actor = args.actor
    if not actor:
        try:
            ident_name = _resolve_identity_name(None)
            actor = load_identity(paths(), ident_name).key_id
        except SystemExit:
            print("--actor required when no default identity is set", file=sys.stderr)
            return 2
    event = {
        "event_id": str(uuid.uuid4()),
        "phip_id": args.phip_id,
        "type": args.type_,
        "timestamp": _utc_now_iso(),
        "actor": actor,
        "previous_hash": args.previous_hash,
        "payload": payload,
    }
    print(json.dumps(event, indent=2))
    return 0


def run_event_sign(args: argparse.Namespace) -> int:
    try:
        event = _read_json(args.input)
    except json.JSONDecodeError as e:
        print(f"input is not valid JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(event, dict):
        print("input must be a JSON object", file=sys.stderr)
        return 2

    try:
        ident = load_identity(paths(), _resolve_identity_name(args.key))
    except (FileNotFoundError, ValueError, SystemExit) as e:
        print(str(e), file=sys.stderr)
        return 1
    signed = sign_event(event, ident.keypair.private, ident.key_id)
    print(json.dumps(signed, indent=2))
    return 0


def run_event_verify(args: argparse.Namespace) -> int:
    try:
        event = _read_json(args.input)
    except json.JSONDecodeError as e:
        print(f"input is not valid JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(event, dict):
        print("input must be a JSON object", file=sys.stderr)
        return 2

    if args.key:
        ident = load_identity(paths(), args.key)
        jwk = ident.jwk
    else:
        sig = event.get("signature") or {}
        sig_key_id = sig.get("key_id")
        if not isinstance(sig_key_id, str):
            print("event has no signature.key_id and --key not provided", file=sys.stderr)
            return 2
        # Best-effort: search local identities for one whose key_id matches.
        for i in list_identities(paths()):
            if i.key_id == sig_key_id:
                jwk = i.jwk
                break
        else:
            print(
                f"could not find a local identity for {sig_key_id!r}; pass --key NAME",
                file=sys.stderr,
            )
            return 1

    public = public_key_from_jwk(jwk)
    ok = verify_event(event, public)
    print(json.dumps({"verified": ok}, indent=2))
    return 0 if ok else 1


def run_event_hash(args: argparse.Namespace) -> int:
    try:
        event = _read_json(args.input)
    except json.JSONDecodeError as e:
        print(f"input is not valid JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(event, dict):
        print("input must be a JSON object", file=sys.stderr)
        return 2
    print(hash_event(event))
    return 0


def run_uri_parse(args: argparse.Namespace) -> int:
    try:
        u = parse_uri(args.uri)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "scheme": "phip",
                "authority": u.authority,
                "namespace": u.namespace,
                "local_id": u.local_id,
            },
            indent=2,
        )
    )
    return 0


def run_uri_format(args: argparse.Namespace) -> int:
    try:
        uri = format_uri(args.authority, args.namespace, args.local_id)
    except (ValueError, TypeError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(uri)
    return 0


def run_canonicalize(args: argparse.Namespace) -> int:
    try:
        obj = _read_json(args.input)
    except json.JSONDecodeError as e:
        print(f"input is not valid JSON: {e}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(canonical_bytes(obj))
    sys.stdout.buffer.write(b"\n")
    return 0
