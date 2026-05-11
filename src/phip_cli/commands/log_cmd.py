"""`phip log <phip-uri> <file> --metric M` — composite ingest.

Walks the boring steps for a measurement event in one command:

  1. Hash the primary file
  2. PUT the blob
  3. (For each --attach) hash + PUT
  4. Fetch current head_hash from the remote
  5. Build the measurement event payload
  6. Sign with the current identity
  7. POST /push

Equivalent to a hand-rolled `phip blob put | phip event new | phip event sign | phip push`,
but matches what `phip-bench log` did so this is the natural ergonomic for the
"I just ran a sweep" workflow.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from phip import sign_event

from phip_cli.commands.blob_cmd import detect_media_type, hash_file
from phip_cli.commands.server_cmd import _resolve_remote
from phip_cli.config import load_config, paths
from phip_cli.http import HTTPError, head_hash_of, push_event, put_blob
from phip_cli.identity import Identity, load_identity
from phip_cli.remote import Remote
from phip_cli.uri import expand


def add(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser(
        "log",
        help="Ingest a file as a signed measurement event on an existing object.",
    )
    p.add_argument("phip_uri", help="phip:// URI of the object being measured.")
    p.add_argument("file", help="Primary measurement file (CSV, image, etc.).")
    p.add_argument("--metric", required=True, help="Metric short name.")
    p.add_argument("--value", type=float, help="Scalar summary value.")
    p.add_argument("--unit", help="Unit for --value.")
    p.add_argument("--method", help="Measurement method (e.g. swept_sine).")
    p.add_argument("--rig", help="Bench rig identifier.")
    p.add_argument("--instrument", help="Instrument identifier.")
    p.add_argument(
        "--measured-with", help="phip:// URI of the fixture/instrument used."
    )
    p.add_argument("--notes", help="Free-form notes.")
    p.add_argument("--at", help="Capture time (ISO 8601 UTC). Defaults to now.")
    p.add_argument(
        "--media-type",
        help="Override the primary file's content-type. Defaults to auto-detect.",
    )
    p.add_argument(
        "--attach", action="append", default=[], help="Additional file to attach (repeatable)."
    )
    p.add_argument("--remote", help="Remote name (defaults to current default).")
    p.add_argument("--key", help="Identity to sign with (defaults to current default).")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Build + sign but don't upload blobs or push; print the signed event.",
    )
    p.set_defaults(func=run)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _measurement_payload(
    args: argparse.Namespace,
    primary: Path,
    primary_hash: str,
    primary_media: str,
    attachments_meta: list[dict[str, object]],
) -> dict[str, object]:
    when = args.at or _utc_now_iso()
    payload: dict[str, object] = {
        "metric": args.metric,
        "as_of": when,
        "external_ref": {
            "content_hash": f"sha256:{primary_hash}",
            "media_type": primary_media,
            "filename": primary.name,
        },
    }
    for k, v in (
        ("value", args.value),
        ("unit", args.unit),
        ("method", args.method),
        ("rig", args.rig),
        ("instrument", args.instrument),
        ("measured_with", args.measured_with),
        ("notes", args.notes),
    ):
        if v is not None:
            payload[k] = v
    if attachments_meta:
        payload["attachments"] = attachments_meta
    return payload


def _run_dry_run(
    args: argparse.Namespace,
    ident: Identity,
    primary: Path,
    phip_uri: str,
) -> int:
    import json as _json

    primary_hash = hash_file(primary)
    primary_media = args.media_type or detect_media_type(primary)
    attachments_meta: list[dict[str, object]] = []
    for att_path in args.attach:
        att = Path(att_path)
        if not att.exists():
            print(f"attachment not found: {att}", file=sys.stderr)
            return 1
        attachments_meta.append(
            {
                "content_hash": f"sha256:{hash_file(att)}",
                "media_type": detect_media_type(att),
                "filename": att.name,
            }
        )
    payload = _measurement_payload(args, primary, primary_hash, primary_media, attachments_meta)
    unsigned: dict[str, object] = {
        "event_id": str(uuid.uuid4()),
        "phip_id": phip_uri,
        "type": "measurement",
        "timestamp": _utc_now_iso(),
        "actor": ident.key_id,
        "previous_hash": "sha256:DRYRUN-NO-NETWORK-FETCH",
        "payload": payload,
    }
    signed = sign_event(unsigned, ident.keypair.private, ident.key_id)
    print(_json.dumps(signed, indent=2))
    return 0


def _ingest_blob(
    remote: Remote, path: Path, media_type: str | None
) -> tuple[str, str]:
    digest = hash_file(path)
    media = media_type or detect_media_type(path)
    put_blob(remote, digest, path.read_bytes(), media_type=media)
    return digest, media


def run(args: argparse.Namespace) -> int:
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
    try:
        remote = _resolve_remote(args.remote)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1

    try:
        phip_uri = expand(args.phip_uri, p, cfg)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 2

    primary = Path(args.file)
    if not primary.exists():
        print(f"file not found: {primary}", file=sys.stderr)
        return 1

    if args.dry_run:
        return _run_dry_run(args, ident, primary, phip_uri)

    try:
        # 1-3. Upload primary + attachments.
        primary_hash, primary_media = _ingest_blob(remote, primary, args.media_type)
        attachments_meta: list[dict[str, object]] = []
        for att_path in args.attach:
            att = Path(att_path)
            if not att.exists():
                print(f"attachment not found: {att}", file=sys.stderr)
                return 1
            att_hash, att_media = _ingest_blob(remote, att, None)
            attachments_meta.append(
                {
                    "content_hash": f"sha256:{att_hash}",
                    "media_type": att_media,
                    "filename": att.name,
                }
            )

        # 4. Fetch current head from server.
        prev = head_hash_of(remote, phip_uri)

        # 5. Build the measurement payload (spec §11.4.2 + attachments extension).
        payload = _measurement_payload(args, primary, primary_hash, primary_media, attachments_meta)

        # 6. Sign.
        unsigned: dict[str, object] = {
            "event_id": str(uuid.uuid4()),
            "phip_id": phip_uri,
            "type": "measurement",
            "timestamp": _utc_now_iso(),
            "actor": ident.key_id,
            "previous_hash": prev,
            "payload": payload,
        }
        signed = sign_event(unsigned, ident.keypair.private, ident.key_id)

        # 7. Push.
        result = push_event(remote, phip_uri, signed)
    except HTTPError as e:
        print(
            f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
            file=sys.stderr,
        )
        return 1

    print(f"Logged {args.metric} on {phip_uri}")
    print(f"  blob:        sha256:{primary_hash[:12]}...")
    if attachments_meta:
        print(f"  attachments: {len(attachments_meta)}")
    print(f"  event:       {signed['event_id']}")
    print(f"  head_hash:   {result.get('head_hash')}")
    return 0
