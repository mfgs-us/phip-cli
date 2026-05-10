"""`phip key generate|list|show|use` — local identity management."""

from __future__ import annotations

import argparse
import json
import sys

from phip_cli.config import load_config, paths, save_config
from phip_cli.identity import generate_identity, list_identities, load_identity


def add(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("key", help="Manage local identities (Ed25519 keypairs).")
    s = p.add_subparsers(dest="subcommand", required=True)

    g = s.add_parser("generate", help="Generate a new keypair.")
    g.add_argument("name")
    g.add_argument("--authority", required=True, help="Authority part of the key URI.")
    g.set_defaults(func=run_generate)

    ls = s.add_parser("list", help="List local identities.")
    ls.set_defaults(func=run_list)

    sh = s.add_parser("show", help="Show a key's JWK + URI.")
    sh.add_argument("name")
    sh.set_defaults(func=run_show)

    use = s.add_parser("use", help="Set the default identity.")
    use.add_argument("name")
    use.set_defaults(func=run_use)

    reg = s.add_parser(
        "register",
        help="Push the bootstrap actor event for an identity to a remote.",
    )
    reg.add_argument(
        "name",
        nargs="?",
        help="Identity to register. Defaults to the default identity.",
    )
    reg.add_argument("--remote", help="Remote name. Defaults to the default remote.")
    reg.set_defaults(func=run_register)


def run_generate(args: argparse.Namespace) -> int:
    p = paths()
    p.root.mkdir(parents=True, exist_ok=True)
    try:
        ident = generate_identity(p, name=args.name, authority=args.authority)
    except (FileExistsError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"Generated {ident.key_id}")
    return 0


def run_list(args: argparse.Namespace) -> int:  # noqa: ARG001
    p = paths()
    cfg = load_config(p)
    idents = list_identities(p)
    if not idents:
        print("(no identities)")
        return 0
    for i in idents:
        marker = "*" if i.name == cfg.default_identity else " "
        print(f"{marker} {i.name:<20}  {i.key_id}")
    return 0


def run_show(args: argparse.Namespace) -> int:
    p = paths()
    try:
        ident = load_identity(p, args.name)
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps({"name": ident.name, "key_id": ident.key_id, "jwk": ident.jwk}, indent=2))
    return 0


def run_use(args: argparse.Namespace) -> int:
    p = paths()
    try:
        load_identity(p, args.name)
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    cfg = load_config(p)
    cfg.default_identity = args.name
    save_config(cfg, p)
    print(f"Default identity set to {args.name!r}")
    return 0


def run_register(args: argparse.Namespace) -> int:
    """Push the self-signed bootstrap actor event for an identity to a remote.

    The server's chain validator (see phip-server services/chain.py) accepts
    a `created` event where actor == phip_id == sig_key_id and
    previous_hash == "genesis", with the JWK in payload.attributes['phip:keys'].
    Once registered, subsequent pushes signed by this key resolve against
    this actor object.
    """
    import uuid
    from datetime import datetime, timezone

    from phip import parse_uri, sign_event

    from phip_cli.commands.server_cmd import _resolve_remote
    from phip_cli.http import HTTPError, create_object

    p = paths()
    cfg = load_config(p)
    name = args.name or cfg.default_identity
    if not name:
        print("no identity specified and no default identity set", file=sys.stderr)
        return 2
    try:
        ident = load_identity(p, name)
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    try:
        remote = _resolve_remote(args.remote)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1

    try:
        parsed = parse_uri(ident.key_id)
    except ValueError as e:
        print(f"identity has malformed key_id: {e}", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    event: dict[str, object] = {
        "event_id": str(uuid.uuid4()),
        "phip_id": ident.key_id,
        "type": "created",
        "timestamp": now,
        "actor": ident.key_id,
        "previous_hash": "genesis",
        "payload": {
            "object_type": "actor",
            "state": "active",
            "attributes": {"phip:keys": ident.jwk},
        },
    }
    signed = sign_event(event, ident.keypair.private, ident.key_id)

    try:
        result = create_object(remote, parsed.namespace, signed)
    except HTTPError as e:
        if e.code == "OBJECT_EXISTS":
            print(f"already registered: {ident.key_id} on {remote.name}")
            return 0
        print(
            f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
            file=sys.stderr,
        )
        return 1
    print(f"Registered {ident.key_id} on {remote.name}")
    print(f"  head_hash: {result.get('head_hash')}")
    return 0
