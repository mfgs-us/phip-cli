"""`phip completion <shell>` — emit a shell completion script."""

from __future__ import annotations

import argparse
import sys


def add(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser(
        "completion",
        help="Print a shell completion script (source it from your shell rc).",
    )
    p.add_argument("shell", choices=("bash", "zsh", "tcsh"))
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    try:
        import shtab
    except ImportError:
        print(
            "shell completion requires the `shtab` package (it's in our deps; reinstall).",
            file=sys.stderr,
        )
        return 1

    # Build the same parser the dispatcher uses, then ask shtab to render.
    from phip_cli.cli import build_parser

    parser = build_parser()
    print(shtab.complete(parser, shell=args.shell))
    return 0
