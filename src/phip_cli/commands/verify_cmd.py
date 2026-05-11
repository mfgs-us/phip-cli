"""`phip verify <phip-uri>` — fetch an object's full chain and re-validate it client-side.

Walks every event:
  - previous_hash linkage
  - signature against the resolved actor JWK
  - bootstrap (self-signed) actors accepted as a special case

Actor JWKs are resolved by re-fetching the actor object from the same
remote. (Cross-authority resolution is federation work and not yet
wired in here.)
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from phip import hash_event, public_key_from_jwk, verify_event

from phip_cli.commands.server_cmd import _resolve_remote
from phip_cli.config import load_config, paths
from phip_cli.http import HTTPError, get_object, iter_history
from phip_cli.remote import Remote
from phip_cli.uri import expand


def add(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser(
        "verify",
        help="Fetch an object's full chain and re-validate signatures + linkage client-side.",
    )
    p.add_argument("phip_uri")
    p.add_argument("--remote")
    p.set_defaults(func=run)


def _resolve_actor_jwk(
    remote: Remote, key_id: str, *, signed: dict[str, Any], cache: dict[str, dict[str, Any] | None]
) -> dict[str, Any] | None:
    """Look up `key_id`'s JWK on the remote (memoized).

    Bootstrap shortcut: if `signed` is itself a self-signed `created` event
    where actor == phip_id == sig_key_id, the JWK is in its own payload
    and we don't need an extra round-trip.
    """
    if key_id in cache:
        return cache[key_id]
    sig = signed.get("signature") or {}
    if (
        signed.get("type") == "created"
        and signed.get("phip_id") == signed.get("actor") == sig.get("key_id")
        and signed.get("previous_hash") == "genesis"
    ):
        keys = signed.get("payload", {}).get("attributes", {}).get("phip:keys")
        if isinstance(keys, dict) and "x" in keys:
            cache[key_id] = keys
            return keys
    try:
        actor_obj = get_object(remote, key_id, history=1)
    except HTTPError:
        cache[key_id] = None
        return None
    history = actor_obj.get("history") or []
    if not history:
        cache[key_id] = None
        return None
    payload = history[-1].get("payload", {})
    keys = payload.get("attributes", {}).get("phip:keys")
    if isinstance(keys, dict) and "x" in keys:
        cache[key_id] = keys
        return keys
    cache[key_id] = None
    return None


def run(args: argparse.Namespace) -> int:
    p = paths()
    cfg = load_config(p)
    try:
        phip_uri = expand(args.phip_uri, p, cfg)
        remote = _resolve_remote(args.remote)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1

    failures: list[str] = []
    checked = 0
    expected_prev = "genesis"
    cache: dict[str, dict[str, Any] | None] = {}

    try:
        events = list(iter_history(remote, phip_uri))
    except HTTPError as e:
        print(
            f"server returned {e.status_code} {e.code or ''}: {e.message}".strip(),
            file=sys.stderr,
        )
        return 1

    for i, ev in enumerate(events):
        checked += 1
        ev_short = str(ev.get("event_id", ""))[:8]

        # Chain link.
        if ev.get("previous_hash") != expected_prev:
            failures.append(
                f"event #{i} ({ev_short}): previous_hash mismatch "
                f"(want {expected_prev!r}, got {ev.get('previous_hash')!r})"
            )

        # Recomputed event hash for next iteration's expected_prev.
        recomputed = hash_event(ev)
        expected_prev = recomputed

        # Signature.
        sig = ev.get("signature") or {}
        sig_key_id = sig.get("key_id")
        if not isinstance(sig_key_id, str):
            failures.append(f"event #{i} ({ev_short}): missing signature.key_id")
            continue
        jwk = _resolve_actor_jwk(remote, sig_key_id, signed=ev, cache=cache)
        if jwk is None:
            failures.append(
                f"event #{i} ({ev_short}): could not resolve key {sig_key_id!r}"
            )
            continue
        public = public_key_from_jwk(jwk)
        if not verify_event(ev, public):
            failures.append(
                f"event #{i} ({ev_short}): signature verification failed"
            )

    print(f"{phip_uri}")
    print(f"  events checked: {checked}")
    print(f"  events passed:  {checked - len(failures)}")
    if failures:
        print(f"  FAILURES ({len(failures)}):")
        for f in failures:
            print(f"    - {f}")
        return 1
    if checked == 0:
        print("  (no events on chain)")
        return 0
    print("  OK: chain valid")
    return 0
