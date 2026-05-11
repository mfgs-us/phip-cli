"""Shorthand URI expansion.

`phip get widget-001` → expand against (default_authority, default_namespace) →
`phip://acme.example/parts/widget-001`. Full `phip://...` URIs pass through
untouched.

Resolution order for authority:
    1. config.default_authority if set
    2. authority of config.default_remote if set
    3. authority of default identity if set
    4. (fail with a helpful message)

Resolution order for namespace:
    1. config.default_namespace if set
    2. (fail with a helpful message)
"""

from __future__ import annotations

from phip_cli.config import Config, Paths
from phip_cli.identity import load_identity
from phip_cli.remote import load_remote


def _resolve_authority(p: Paths, cfg: Config) -> str | None:
    if cfg.default_authority:
        return cfg.default_authority
    if cfg.default_remote:
        try:
            return load_remote(p, cfg.default_remote).authority
        except (FileNotFoundError, ValueError):
            pass
    if cfg.default_identity:
        try:
            ident = load_identity(p, cfg.default_identity)
            # key_id is phip://<authority>/keys/<name>
            after_scheme = ident.key_id.removeprefix("phip://")
            return after_scheme.split("/", 1)[0]
        except (FileNotFoundError, ValueError):
            pass
    return None


def expand(s: str, p: Paths, cfg: Config) -> str:
    """If `s` is already a phip:// URI, return as-is. Otherwise expand
    against (default_authority, default_namespace, s) and raise SystemExit
    with a helpful error if either default is missing."""
    if s.startswith("phip://"):
        return s
    authority = _resolve_authority(p, cfg)
    if not authority:
        raise SystemExit(
            f"shorthand URI {s!r} given but no default authority is set. "
            "Either pass a full phip:// URI, or "
            "set one with `phip config set default_authority <name>`."
        )
    namespace = cfg.default_namespace
    if not namespace:
        raise SystemExit(
            f"shorthand URI {s!r} given but no default namespace is set. "
            "Either pass a full phip:// URI, or "
            "set one with `phip config set default_namespace <name>`."
        )
    return f"phip://{authority}/{namespace}/{s}"


def authority_for_new(p: Paths, cfg: Config) -> str:
    """Best-effort authority for newly-created URIs. Raises SystemExit
    if none can be determined."""
    a = _resolve_authority(p, cfg)
    if not a:
        raise SystemExit(
            "no default authority. Pass --authority or "
            "`phip config set default_authority <name>`."
        )
    return a
