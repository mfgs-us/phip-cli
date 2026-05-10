"""Filesystem layout for ~/.phip/.

    ~/.phip/
    ├── config.json           # default identity, default remote
    ├── keys/<name>.json      # private keypairs (chmod 600 on POSIX)
    └── remotes.json          # registered phip-server endpoints

The root can be overridden with PHIP_HOME for tests.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_root() -> Path:
    override = os.environ.get("PHIP_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".phip"


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def config_file(self) -> Path:
        return self.root / "config.json"

    @property
    def keys_dir(self) -> Path:
        return self.root / "keys"

    @property
    def remotes_file(self) -> Path:
        return self.root / "remotes.json"

    def key_file(self, name: str) -> Path:
        return self.keys_dir / f"{name}.json"


def paths() -> Paths:
    return Paths(root=_default_root())


@dataclass
class Config:
    """Top-level CLI state. Persisted as config.json."""

    default_identity: str | None = None
    default_remote: str | None = None
    extras: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {}
        if self.default_identity is not None:
            out["default_identity"] = self.default_identity
        if self.default_remote is not None:
            out["default_remote"] = self.default_remote
        out.update(self.extras)
        return out

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> Config:
        return cls(
            default_identity=d.get("default_identity"),  # type: ignore[arg-type]
            default_remote=d.get("default_remote"),  # type: ignore[arg-type]
            extras={k: v for k, v in d.items() if k not in {"default_identity", "default_remote"}},
        )


def load_config(p: Paths | None = None) -> Config:
    p = p or paths()
    if not p.config_file.exists():
        return Config()
    return Config.from_dict(json.loads(p.config_file.read_text("utf-8")))


def save_config(cfg: Config, p: Paths | None = None) -> None:
    p = p or paths()
    p.root.mkdir(parents=True, exist_ok=True)
    p.config_file.write_text(json.dumps(cfg.to_dict(), indent=2) + "\n", encoding="utf-8")
