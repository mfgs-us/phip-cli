"""`phip` — top-level dispatcher."""

from __future__ import annotations

import argparse
import contextlib
import sys

from phip_cli.commands import init_cmd, key_cmd, plumbing_cmd, remote_cmd, server_cmd


def _force_utf8_stdio() -> None:
    """Windows consoles default to cp1252; reconfigure stdio to UTF-8 so
    we can print box characters / non-ASCII without UnicodeEncodeError."""
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if callable(reconfig):
            with contextlib.suppress(LookupError, ValueError):
                reconfig(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="phip",
        description=(
            "Command-line interface for the Physical Information Protocol. "
            "Talks to phip-server, manages local identities and remotes, and "
            "exposes protocol primitives (sign/verify/hash/canonicalize/parse-URI) "
            "as plumbing commands."
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)

    init_cmd.add(sub)
    key_cmd.add(sub)
    remote_cmd.add(sub)
    server_cmd.add(sub)
    plumbing_cmd.add(sub)

    return p


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
