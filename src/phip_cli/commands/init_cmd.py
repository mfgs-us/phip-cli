"""`phip init` — one-shot setup: directory, identity, optional remote."""

from __future__ import annotations

import argparse
import sys

from phip_cli.config import Config, paths, save_config
from phip_cli.identity import generate_identity
from phip_cli.remote import Remote, add_remote


def add(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("init", help="Initialize ~/.phip/, generate a key, optionally add a remote.")
    p.add_argument("--name", default="default", help="Local identity name.")
    p.add_argument(
        "--authority",
        help="Authority for this identity's URI. Defaults to remote authority or localhost.",
    )
    p.add_argument("--remote", help="phip-server URL to register as the default remote.")
    p.add_argument("--remote-name", default="origin", help="Local name for the remote.")
    p.add_argument("--remote-authority", help="The remote's PhIP authority. Defaults to URL host.")
    p.add_argument("--token", help="Bearer token for the remote (writes).")
    p.add_argument("--force", action="store_true", help="Overwrite an existing identity/config.")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    p = paths()
    p.root.mkdir(parents=True, exist_ok=True)
    p.keys_dir.mkdir(parents=True, exist_ok=True)

    # Resolution order: --authority wins for both identity AND remote.
    # If --remote-authority is explicit, it overrides the remote half.
    # If neither --authority nor --remote-authority is given, fall back
    # to the remote URL's hostname.
    from urllib.parse import urlparse

    host = urlparse(args.remote).hostname if args.remote else None
    authority = args.authority or host or "localhost"
    remote_authority: str | None = None
    if args.remote:
        # If the user said --authority X and didn't override --remote-authority,
        # the remote is presumed authoritative for X. This is what 99% of
        # users mean when they `phip init --remote URL --authority X`.
        remote_authority = args.remote_authority or authority

    # Generate (or replace) the identity.
    key_path = p.key_file(args.name)
    if key_path.exists() and not args.force:
        print(
            f"identity {args.name!r} already exists; pass --force to overwrite",
            file=sys.stderr,
        )
        return 1
    if key_path.exists():
        key_path.unlink()
    ident = generate_identity(p, name=args.name, authority=authority)

    # Optionally add a remote.
    if args.remote:
        rem = Remote(
            name=args.remote_name,
            url=args.remote.rstrip("/"),
            authority=remote_authority or "localhost",
            token=args.token,
        )
        try:
            add_remote(p, rem, replace=True)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2

    cfg = Config(
        default_identity=ident.name,
        default_remote=args.remote_name if args.remote else None,
    )
    save_config(cfg, p)

    print(f"Initialized phip at {p.root}")
    print(f"  identity: {ident.key_id}")
    if args.remote:
        print(f"  remote:   {args.remote_name} -> {args.remote.rstrip('/')}")
    return 0
