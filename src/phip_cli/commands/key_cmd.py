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
