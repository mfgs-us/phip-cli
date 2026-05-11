"""`phip token mint|decode|verify|use` — capability tokens (spec §11.3)."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from phip import encode_token, mint_token, parse_token, public_key_from_jwk, verify_token
from phip.errors import InvalidCapability, InvalidSignature

from phip_cli.config import load_config, paths
from phip_cli.identity import Identity, list_identities, load_identity
from phip_cli.remote import Remote, add_remote, load_remote

_VALID_SCOPES = (
    "push_events",
    "push_state",
    "push_measurements",
    "push_relations",
    "read_state",
    "read_history",
    "read_query",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def add(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("token", help="Mint / decode / verify / use capability tokens (§11.3).")
    s = p.add_subparsers(dest="subcommand", required=True)

    m = s.add_parser("mint", help="Mint a signed capability token.")
    m.add_argument(
        "--scope", required=True, choices=_VALID_SCOPES, help="Scope this token grants."
    )
    m.add_argument(
        "--object",
        required=True,
        dest="object_filter",
        help="Glob over phip_id (`*` is the only wildcard).",
    )
    m.add_argument(
        "--granted-to",
        required=True,
        help="phip:// URI of the actor this token is granted to.",
    )
    m.add_argument(
        "--ttl-hours",
        type=float,
        default=24.0,
        help="Validity window in hours from now (default 24).",
    )
    m.add_argument("--not-before", help="ISO 8601 lower bound. Defaults to now.")
    m.add_argument("--expires", help="ISO 8601 upper bound. Overrides --ttl-hours.")
    m.add_argument(
        "--key",
        help="Identity to sign with (granted_by). Defaults to default identity.",
    )
    m.set_defaults(func=run_mint)

    d = s.add_parser("decode", help="Print a wire-format token as JSON.")
    d.add_argument("token", help="Bearer-form (base64url) or `PhIP-Capability <token>`.")
    d.set_defaults(func=run_decode)

    v = s.add_parser("verify", help="Verify a token's signature + window locally.")
    v.add_argument("token")
    v.add_argument(
        "--against",
        help="phip:// URI of the actor whose JWK should verify it (or any local identity name).",
    )
    v.add_argument(
        "--object",
        dest="requested_object",
        help="Optional requested object — verifier checks object_filter match.",
    )
    v.add_argument(
        "--scope",
        dest="requested_scope",
        help="Optional requested scope — verifier checks coverage.",
    )
    v.add_argument(
        "--actor",
        dest="requesting_actor",
        help="Optional requesting actor — verifier checks granted_to match.",
    )
    v.set_defaults(func=run_verify)

    u = s.add_parser(
        "use",
        help="Store a token as the bearer for a remote (overwrites any existing bearer).",
    )
    u.add_argument("token")
    u.add_argument("--remote", help="Remote name (defaults to current default).")
    u.set_defaults(func=run_use)


# ── implementations ────────────────────────────────────────────────


def run_mint(args: argparse.Namespace) -> int:
    p = paths()
    cfg = load_config(p)
    name = args.key or cfg.default_identity
    if not name:
        print("no key specified and no default identity set", file=sys.stderr)
        return 2
    try:
        ident = load_identity(p, name)
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1

    now = _utc_now()
    nb = args.not_before or _iso(now)
    exp = args.expires or _iso(now + timedelta(hours=args.ttl_hours))

    try:
        token = mint_token(
            granted_by=ident.key_id,
            granted_to=args.granted_to,
            scope=args.scope,
            object_filter=args.object_filter,
            not_before=nb,
            expires=exp,
            private_key=ident.keypair.private,
            key_id=ident.key_id,
            token_id=str(uuid.uuid4()),
        )
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(encode_token(token))
    return 0


def run_decode(args: argparse.Namespace) -> int:
    try:
        token = parse_token(args.token)
    except InvalidCapability as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(token, indent=2))
    return 0


def _find_identity_for_key_id(key_id: str) -> Identity | None:
    """Return the local identity whose key_id matches, or None."""
    for i in list_identities(paths()):
        if i.key_id == key_id:
            return i
    return None


def run_verify(args: argparse.Namespace) -> int:
    try:
        token = parse_token(args.token)
    except InvalidCapability as e:
        print(str(e), file=sys.stderr)
        return 1

    # Resolve the JWK to verify against.
    jwk: dict[str, Any] | None = None
    found: Identity | None = None
    if args.against:
        # Try as a local identity name first, then as a key_id.
        try:
            found = load_identity(paths(), args.against)
        except (FileNotFoundError, ValueError):
            found = _find_identity_for_key_id(args.against)
    else:
        # Try the token's `granted_by` key_id against local identities.
        granted_by = token.get("granted_by")
        if isinstance(granted_by, str):
            found = _find_identity_for_key_id(granted_by)
    if found is not None:
        jwk = found.jwk
    if jwk is None:
        print(
            "could not resolve a JWK to verify against. Pass "
            "--against NAME (local id) or --against <phip-uri> "
            "(matching a local key_id).",
            file=sys.stderr,
        )
        return 1

    public = public_key_from_jwk(jwk)
    try:
        verify_token(
            token,
            public,
            requesting_actor=args.requesting_actor,
            requested_object=args.requested_object,
            requested_scope=args.requested_scope,
        )
    except (InvalidSignature, InvalidCapability) as e:
        print(json.dumps({"verified": False, "reason": str(e)}, indent=2))
        return 1
    print(json.dumps({"verified": True}, indent=2))
    return 0


def run_use(args: argparse.Namespace) -> int:
    p = paths()
    cfg = load_config(p)
    name = args.remote or cfg.default_remote
    if not name:
        print("no remote specified and no default remote set", file=sys.stderr)
        return 2
    try:
        rem = load_remote(p, name)
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    # Validate that the token at least parses.
    try:
        parse_token(args.token)
    except InvalidCapability as e:
        print(f"token does not parse: {e}", file=sys.stderr)
        return 1
    new_rem = Remote(name=rem.name, url=rem.url, authority=rem.authority, token=args.token)
    add_remote(p, new_rem, replace=True)
    print(f"Updated bearer token on remote {name!r}")
    return 0
