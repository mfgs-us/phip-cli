"""`phip bundle pack|unpack|verify` — portable, signed exports.

A bundle is a self-contained, verifiable export of one or more
objects + their history (spec §4.3.4). Drop one in a static directory,
serve it from GitHub Pages, and a verifier on the other end can prove
the chain end-to-end without talking to your server.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from phip import make_bundle, pack_bundle, unpack_bundle, verify_bundle

from phip_cli.commands.server_cmd import _resolve_remote
from phip_cli.config import load_config, paths
from phip_cli.http import HTTPError, get_object, iter_history
from phip_cli.identity import load_identity
from phip_cli.uri import expand


def add(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("bundle", help="Pack / unpack / verify portable signed bundles.")
    s = p.add_subparsers(dest="subcommand", required=True)

    pa = s.add_parser("pack", help="Fetch an object's history and emit a signed bundle.")
    pa.add_argument("phip_uri", nargs="+", help="One or more phip:// URIs to include.")
    pa.add_argument("--out", required=True, help="Output bundle path (.phip-bundle).")
    pa.add_argument("--remote")
    pa.add_argument("--key", help="Identity to sign the bundle as producer.")
    pa.set_defaults(func=run_pack)

    un = s.add_parser("unpack", help="Print a bundle's manifest and event counts.")
    un.add_argument("file")
    un.set_defaults(func=run_unpack)

    ve = s.add_parser("verify", help="Full integrity check on a bundle file.")
    ve.add_argument("file")
    ve.set_defaults(func=run_verify)


def run_pack(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone

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

    # Expand shorthand IDs (e.g. `widget-001`) and pull out the
    # source authority — bundles are single-authority per the spec.
    from phip import parse_uri

    try:
        expanded_uris = [expand(u, p, cfg) for u in args.phip_uri]
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 2
    source_authority = parse_uri(expanded_uris[0]).authority

    objects: list[dict[str, object]] = []
    chains: dict[str, list[dict[str, object]]] = {}
    try:
        for uri in expanded_uris:
            obj = get_object(remote, uri, history=0)
            objects.append(
                {
                    "phip_id": obj["phip_id"],
                    "object_type": obj["object_type"],
                    "state": obj["state"],
                    "head_hash": obj["head_hash"],
                    "history_length": obj["history_length"],
                }
            )
            chains[obj["phip_id"]] = list(iter_history(remote, uri))
    except HTTPError as e:
        print(
            f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
            file=sys.stderr,
        )
        return 1

    # Embed the producer's key actor record so verifiers can resolve
    # the manifest signature without any network round-trip.
    producer_actor: dict[str, object] = {
        "phip_id": ident.key_id,
        "object_type": "actor",
        "state": "active",
        "attributes": {"phip:keys": ident.jwk},
    }
    keys_block: dict[str, dict[str, object]] = {ident.key_id: producer_actor}

    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    bundle = make_bundle(
        authority=source_authority,
        created_by=ident.key_id,
        created_at=created_at,
        objects=objects,
        history=chains,
        keys=keys_block,
        private_key=ident.keypair.private,
        key_id=ident.key_id,
    )
    blob = pack_bundle(bundle)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)

    n_events = sum(len(events) for events in chains.values())
    print(f"Wrote {out} ({len(blob)} bytes)")
    print(f"  authority: {source_authority}")
    print(f"  objects:   {len(objects)}")
    print(f"  events:    {n_events}")
    print(f"  producer:  {ident.key_id}")
    return 0


def run_unpack(args: argparse.Namespace) -> int:
    blob = Path(args.file).read_bytes()
    bundle = unpack_bundle(blob)
    print(f"{args.file}")
    print(f"  bundle_version:  {bundle.manifest.get('bundle_version')}")
    print(f"  authority:       {bundle.manifest.get('authority')}")
    print(f"  created_by:      {bundle.manifest.get('created_by')}")
    print(f"  created_at:      {bundle.manifest.get('created_at')}")
    print(f"  objects:         {len(bundle.objects)}")
    n_events = sum(len(evs) for evs in bundle.history.values())
    print(f"  events:          {n_events}")
    for phip_id, obj in bundle.objects.items():
        print(
            f"    - {phip_id}  ({obj.get('object_type', '?')}, "
            f"state={obj.get('state', '?')}, "
            f"history_length={obj.get('history_length', '?')})"
        )
    return 0


def run_verify(args: argparse.Namespace) -> int:
    blob = Path(args.file).read_bytes()
    bundle = unpack_bundle(blob)
    try:
        verify_bundle(bundle)
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: {type(e).__name__}: {e}")
        return 1
    print("OK: bundle valid")
    print(f"  objects:  {len(bundle.objects)}")
    print(f"  events:   {sum(len(e) for e in bundle.history.values())}")
    return 0
