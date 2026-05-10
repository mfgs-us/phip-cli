"""`phip blob put|get|head` — surface the server's blob endpoints."""

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import sys
from pathlib import Path

from phip_cli.commands.server_cmd import _resolve_remote
from phip_cli.http import HTTPError, get_blob, put_blob

_EXT_OVERRIDES: dict[str, str] = {
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".s1p": "application/x-touchstone",
    ".s2p": "application/x-touchstone",
    ".s3p": "application/x-touchstone",
    ".s4p": "application/x-touchstone",
    ".npy": "application/x-numpy",
    ".npz": "application/x-numpy",
    ".parquet": "application/x-parquet",
    ".pkl": "application/x-pickle",
    ".h5": "application/x-hdf5",
    ".hdf5": "application/x-hdf5",
}


def detect_media_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _EXT_OVERRIDES:
        return _EXT_OVERRIDES[ext]
    guess, _ = mimetypes.guess_type(str(path))
    return guess or "application/octet-stream"


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def add(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("blob", help="Upload/download content-addressed blobs.")
    s = p.add_subparsers(dest="subcommand", required=True)

    put = s.add_parser("put", help="Hash + upload a file; prints the sha256 hex digest.")
    put.add_argument("file")
    put.add_argument("--remote")
    put.add_argument(
        "--media-type",
        help="Override the content-type sent to the server. Defaults to auto-detect by extension.",
    )
    put.set_defaults(func=run_put)

    get = s.add_parser("get", help="Download a blob by sha256.")
    get.add_argument("sha256")
    get.add_argument("--remote")
    get.add_argument("--out", help="Write to a file instead of stdout.")
    get.set_defaults(func=run_get)


def run_put(args: argparse.Namespace) -> int:
    try:
        remote = _resolve_remote(args.remote)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1
    src = Path(args.file)
    if not src.exists():
        print(f"file not found: {src}", file=sys.stderr)
        return 1
    media = args.media_type or detect_media_type(src)
    digest = hash_file(src)
    try:
        result = put_blob(remote, digest, src.read_bytes(), media_type=media)
    except HTTPError as e:
        print(
            f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
            file=sys.stderr,
        )
        return 1
    print(result["sha256"])
    return 0


def run_get(args: argparse.Namespace) -> int:
    try:
        remote = _resolve_remote(args.remote)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1
    try:
        data = get_blob(remote, args.sha256)
    except HTTPError as e:
        print(
            f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
            file=sys.stderr,
        )
        return 1
    if args.out:
        Path(args.out).write_bytes(data)
        print(f"wrote {len(data)} bytes to {args.out}", file=sys.stderr)
    else:
        sys.stdout.buffer.write(data)
    return 0
