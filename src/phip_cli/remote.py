"""Remote phip-server endpoints — name → URL + optional bearer token."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from phip_cli.config import Paths

_VALID_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


@dataclass(frozen=True)
class Remote:
    name: str
    url: str  # base URL, e.g. https://acme.example
    authority: str  # the authority this remote claims (defaults to URL host)
    token: str | None = None  # bearer token for write ops

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "url": self.url, "authority": self.authority}
        if self.token is not None:
            out["token"] = self.token
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Remote:
        return cls(
            name=d["name"],
            url=d["url"].rstrip("/"),
            authority=d["authority"],
            token=d.get("token"),
        )


def _validate_name(name: str) -> None:
    if not _VALID_NAME.match(name):
        raise ValueError(f"remote name {name!r} must match [a-zA-Z0-9_-]{{1,64}}")


def list_remotes(paths: Paths) -> list[Remote]:
    if not paths.remotes_file.exists():
        return []
    data = json.loads(paths.remotes_file.read_text("utf-8"))
    if not isinstance(data, list):
        return []
    return [Remote.from_dict(d) for d in data]


def load_remote(paths: Paths, name: str) -> Remote:
    _validate_name(name)
    for r in list_remotes(paths):
        if r.name == name:
            return r
    raise FileNotFoundError(f"no remote named {name!r}")


def save_remotes(paths: Paths, remotes: list[Remote]) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.remotes_file.write_text(
        json.dumps([r.to_dict() for r in remotes], indent=2) + "\n", encoding="utf-8"
    )


def add_remote(paths: Paths, remote: Remote, *, replace: bool = False) -> None:
    _validate_name(remote.name)
    remotes = list_remotes(paths)
    existing = next((r for r in remotes if r.name == remote.name), None)
    if existing is not None and not replace:
        raise FileExistsError(f"remote {remote.name!r} already exists")
    remotes = [r for r in remotes if r.name != remote.name]
    remotes.append(remote)
    save_remotes(paths, remotes)


def delete_remote(paths: Paths, name: str) -> None:
    _validate_name(name)
    remotes = [r for r in list_remotes(paths) if r.name != name]
    save_remotes(paths, remotes)
