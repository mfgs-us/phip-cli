"""Local keypair store under ~/.phip/keys/."""

from __future__ import annotations

import base64
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from phip import Keypair, generate_keypair

from phip_cli.config import Paths

_VALID_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


@dataclass(frozen=True)
class Identity:
    name: str
    key_id: str
    keypair: Keypair
    jwk: dict[str, Any]


def _b64url_nopad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _years_from_now_iso(years: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=365 * years)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_name(name: str) -> None:
    if not _VALID_NAME.match(name):
        raise ValueError(
            f"identity name {name!r} must match [a-zA-Z0-9_-]{{1,64}}"
        )


def generate_identity(
    paths: Paths,
    *,
    name: str,
    authority: str,
    validity_years: int = 10,
) -> Identity:
    _validate_name(name)
    paths.keys_dir.mkdir(parents=True, exist_ok=True)
    key_path = paths.key_file(name)
    if key_path.exists():
        raise FileExistsError(f"identity {name!r} already exists at {key_path}")

    kp = generate_keypair()
    key_id = f"phip://{authority}/keys/{name}"
    jwk: dict[str, Any] = {
        **kp.jwk,
        "use": "sig",
        "key_ops": ["verify"],
        "not_before": _now_iso(),
        "not_after": _years_from_now_iso(validity_years),
    }

    key_path.write_text(
        json.dumps(
            {
                "name": name,
                "key_id": key_id,
                "jwk": jwk,
                "private_key_b64url": _b64url_nopad(kp.private.private_bytes_raw()),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if os.name == "posix":
        os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)

    return Identity(name=name, key_id=key_id, keypair=kp, jwk=jwk)


def load_identity(paths: Paths, name: str) -> Identity:
    _validate_name(name)
    key_path = paths.key_file(name)
    if not key_path.exists():
        raise FileNotFoundError(f"no identity named {name!r} at {key_path}")
    data = json.loads(key_path.read_text("utf-8"))
    seed = _b64url_decode(data["private_key_b64url"])
    priv = Ed25519PrivateKey.from_private_bytes(seed)
    kp = Keypair(private=priv, public=priv.public_key())
    return Identity(
        name=data.get("name", name),
        key_id=data["key_id"],
        keypair=kp,
        jwk=data["jwk"],
    )


def list_identities(paths: Paths) -> list[Identity]:
    if not paths.keys_dir.exists():
        return []
    out: list[Identity] = []
    for p in sorted(paths.keys_dir.glob("*.json")):
        try:
            out.append(load_identity(paths, p.stem))
        except (FileNotFoundError, ValueError, KeyError):
            continue
    return out
