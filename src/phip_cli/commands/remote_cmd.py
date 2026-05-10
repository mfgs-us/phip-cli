"""`phip remote add|list|show|rm|use` — manage phip-server endpoints."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import urlparse

from phip_cli.config import load_config, paths, save_config
from phip_cli.remote import Remote, add_remote, delete_remote, list_remotes, load_remote


def add(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("remote", help="Manage phip-server endpoints.")
    s = p.add_subparsers(dest="subcommand", required=True)

    a = s.add_parser("add", help="Register a remote.")
    a.add_argument("name")
    a.add_argument("url")
    a.add_argument("--authority", help="Remote PhIP authority. Defaults to URL host.")
    a.add_argument("--token", help="Bearer token for write operations.")
    a.add_argument("--replace", action="store_true")
    a.set_defaults(func=run_add)

    ls = s.add_parser("list", help="List remotes.")
    ls.set_defaults(func=run_list)

    sh = s.add_parser("show", help="Show one remote's config.")
    sh.add_argument("name")
    sh.set_defaults(func=run_show)

    rm = s.add_parser("rm", help="Delete a remote.")
    rm.add_argument("name")
    rm.set_defaults(func=run_rm)

    use = s.add_parser("use", help="Set the default remote.")
    use.add_argument("name")
    use.set_defaults(func=run_use)


def run_add(args: argparse.Namespace) -> int:
    p = paths()
    p.root.mkdir(parents=True, exist_ok=True)
    authority = args.authority or (urlparse(args.url).hostname or "localhost")
    rem = Remote(name=args.name, url=args.url.rstrip("/"), authority=authority, token=args.token)
    try:
        add_remote(p, rem, replace=args.replace)
    except (FileExistsError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"Added remote {args.name!r} -> {rem.url} (authority: {rem.authority})")
    return 0


def run_list(args: argparse.Namespace) -> int:  # noqa: ARG001
    p = paths()
    cfg = load_config(p)
    remotes = list_remotes(p)
    if not remotes:
        print("(no remotes)")
        return 0
    for r in remotes:
        marker = "*" if r.name == cfg.default_remote else " "
        token_flag = "  [token set]" if r.token else ""
        print(f"{marker} {r.name:<14}  {r.url}  ({r.authority}){token_flag}")
    return 0


def run_show(args: argparse.Namespace) -> int:
    p = paths()
    try:
        rem = load_remote(p, args.name)
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    out = {"name": rem.name, "url": rem.url, "authority": rem.authority}
    if rem.token:
        out["token"] = "***redacted***"
    print(json.dumps(out, indent=2))
    return 0


def run_rm(args: argparse.Namespace) -> int:
    p = paths()
    try:
        delete_remote(p, args.name)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"Removed remote {args.name!r}")
    return 0


def run_use(args: argparse.Namespace) -> int:
    p = paths()
    try:
        load_remote(p, args.name)
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    cfg = load_config(p)
    cfg.default_remote = args.name
    save_config(cfg, p)
    print(f"Default remote set to {args.name!r}")
    return 0
