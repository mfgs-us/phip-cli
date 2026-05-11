"""`phip` — top-level dispatcher."""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys

from phip_cli import __version__
from phip_cli.commands import (
    blob_cmd,
    bundle_cmd,
    completion_cmd,
    config_cmd,
    init_cmd,
    key_cmd,
    log_cmd,
    object_cmd,
    plumbing_cmd,
    remote_cmd,
    schema_cmd,
    server_cmd,
    show_cmd,
    token_cmd,
    verify_cmd,
)


def _force_utf8_stdio() -> None:
    """Windows consoles default to cp1252; reconfigure stdio to UTF-8 so
    we can print box characters / non-ASCII without UnicodeEncodeError."""
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if callable(reconfig):
            with contextlib.suppress(LookupError, ValueError):
                reconfig(encoding="utf-8")


def _phip_py_version() -> str:
    try:
        import phip

        return getattr(phip, "__version__", "?")
    except ImportError:
        return "(missing)"


def _setup_verbose(verbose: int) -> None:
    """`-v` enables INFO logging, `-vv` enables DEBUG (incl. httpx wire).
    No flag = WARNING (httpx silent)."""
    level = logging.WARNING
    if verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    if verbose >= 2:
        # Show httpx request/response wire details.
        logging.getLogger("httpx").setLevel(logging.DEBUG)
        logging.getLogger("httpcore").setLevel(logging.INFO)


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
    p.add_argument(
        "--version",
        action="version",
        version=f"phip-cli {__version__} (phip-py {_phip_py_version()})",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity. -v = INFO; -vv = DEBUG (includes httpx wire logs).",
    )

    sub = p.add_subparsers(dest="command", required=True)

    init_cmd.add(sub)
    key_cmd.add(sub)
    remote_cmd.add(sub)
    config_cmd.add(sub)
    server_cmd.add(sub)
    blob_cmd.add(sub)
    log_cmd.add(sub)
    # object_cmd registers `object`, `transition`, `relate` as siblings.
    object_cmd.add(sub)
    token_cmd.add(sub)
    verify_cmd.add(sub)
    show_cmd.add(sub)
    bundle_cmd.add(sub)
    schema_cmd.add(sub)
    plumbing_cmd.add(sub)
    completion_cmd.add(sub)

    return p


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_verbose(getattr(args, "verbose", 0))
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
