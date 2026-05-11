"""`phip config get|set|unset|list` — manage ~/.phip/config.json fields."""

from __future__ import annotations

import argparse
import sys

from phip_cli.config import Config, load_config, paths, save_config

_KNOWN = Config.KNOWN_FIELDS


def add(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("config", help="Get/set CLI config fields.")
    s = p.add_subparsers(dest="subcommand", required=True)

    g = s.add_parser("get", help="Print the value of a config field.")
    g.add_argument("key")
    g.set_defaults(func=run_get)

    se = s.add_parser("set", help="Set a config field.")
    se.add_argument("key", help=f"Known fields: {', '.join(_KNOWN)}")
    se.add_argument("value")
    se.set_defaults(func=run_set)

    un = s.add_parser("unset", help="Clear a config field.")
    un.add_argument("key")
    un.set_defaults(func=run_unset)

    ls = s.add_parser("list", help="Print every config field that is set.")
    ls.set_defaults(func=run_list)


def run_get(args: argparse.Namespace) -> int:
    cfg = load_config(paths())
    v = getattr(cfg, args.key) if args.key in _KNOWN else cfg.extras.get(args.key)
    if v is None:
        print("(unset)")
        return 1
    print(v)
    return 0


def run_set(args: argparse.Namespace) -> int:
    p = paths()
    cfg = load_config(p)
    if args.key in _KNOWN:
        setattr(cfg, args.key, args.value)
    else:
        cfg.extras[args.key] = args.value
    save_config(cfg, p)
    print(f"{args.key} = {args.value}")
    return 0


def run_unset(args: argparse.Namespace) -> int:
    p = paths()
    cfg = load_config(p)
    if args.key in _KNOWN:
        setattr(cfg, args.key, None)
    elif args.key in cfg.extras:
        del cfg.extras[args.key]
    else:
        print(f"unknown key: {args.key}", file=sys.stderr)
        return 1
    save_config(cfg, p)
    print(f"unset {args.key}")
    return 0


def run_list(args: argparse.Namespace) -> int:  # noqa: ARG001
    cfg = load_config(paths())
    d = cfg.to_dict()
    if not d:
        print("(no config set)")
        return 0
    for k, v in d.items():
        print(f"{k} = {v}")
    return 0
