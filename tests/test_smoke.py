"""End-to-end CLI tests: init, key/remote management, plumbing, server."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phip_cli.cli import main


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / "phip-home"
    monkeypatch.setenv("PHIP_HOME", str(h))
    return h


# ── init + key + whoami ──────────────────────────────────────────────


def test_init_default(home: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["init", "--authority", "test.local"]) == 0
    assert (home / "config.json").exists()
    assert (home / "keys" / "default.json").exists()

    capsys.readouterr()
    assert main(["whoami"]) == 0
    out = capsys.readouterr().out
    assert "phip://test.local/keys/default" in out
    assert "remote:   (none)" in out


def test_init_with_remote(home: Path, capsys: pytest.CaptureFixture) -> None:
    assert (
        main(
            [
                "init",
                "--name", "alice",
                "--remote", "https://acme.example:8080",
                "--remote-name", "origin",
                "--token", "shh",
            ]
        )
        == 0
    )
    remotes = json.loads((home / "remotes.json").read_text("utf-8"))
    assert remotes[0]["name"] == "origin"
    assert remotes[0]["authority"] == "acme.example"
    assert remotes[0]["token"] == "shh"

    capsys.readouterr()
    assert main(["whoami"]) == 0
    out = capsys.readouterr().out
    assert "alice" in out
    assert "origin" in out


def test_key_generate_and_list(home: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["init", "--authority", "test.local"]) == 0
    assert main(["key", "generate", "secondary", "--authority", "test.local"]) == 0
    capsys.readouterr()
    assert main(["key", "list"]) == 0
    out = capsys.readouterr().out
    assert "default" in out and "secondary" in out


def test_key_use_switches_default(home: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["init", "--authority", "test.local"]) == 0
    assert main(["key", "generate", "alt", "--authority", "test.local"]) == 0
    assert main(["key", "use", "alt"]) == 0
    capsys.readouterr()
    assert main(["whoami"]) == 0
    assert "alt" in capsys.readouterr().out


# ── remote add/list/show/rm ──────────────────────────────────────────


def test_remote_add_list_rm(home: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["init", "--authority", "test.local"]) == 0
    assert main(["remote", "add", "origin", "https://acme.example"]) == 0
    assert main(["remote", "add", "lab", "http://localhost:8080"]) == 0
    capsys.readouterr()
    assert main(["remote", "list"]) == 0
    out = capsys.readouterr().out
    assert "origin" in out and "lab" in out

    assert main(["remote", "rm", "lab"]) == 0
    capsys.readouterr()
    assert main(["remote", "list"]) == 0
    out = capsys.readouterr().out
    assert "lab" not in out


# ── plumbing: event new/sign/verify/hash ─────────────────────────────


def test_event_new_sign_verify_hash(
    home: Path, capsys: pytest.CaptureFixture
) -> None:
    assert main(["init", "--authority", "test.local"]) == 0

    capsys.readouterr()
    assert (
        main(
            [
                "event", "new",
                "--phip-id", "phip://test.local/parts/widget-001",
                "--type", "created",
                "--previous-hash", "genesis",
                "--payload", '{"object_type":"component","state":"concept"}',
            ]
        )
        == 0
    )
    unsigned_json = capsys.readouterr().out

    # Write to disk and sign.
    unsigned = home / "unsigned.json"
    unsigned.write_text(unsigned_json, encoding="utf-8")
    assert main(["event", "sign", str(unsigned)]) == 0
    signed_json = capsys.readouterr().out
    signed = json.loads(signed_json)
    assert "signature" in signed

    # Save signed event and verify it.
    signed_path = home / "signed.json"
    signed_path.write_text(signed_json, encoding="utf-8")
    capsys.readouterr()
    assert main(["event", "verify", str(signed_path)]) == 0
    assert '"verified": true' in capsys.readouterr().out

    # Hash it.
    capsys.readouterr()
    assert main(["event", "hash", str(signed_path)]) == 0
    h = capsys.readouterr().out.strip()
    assert h.startswith("sha256:")

    # Tamper, verify should fail.
    signed["payload"]["state"] = "qualified"
    signed_path.write_text(json.dumps(signed), encoding="utf-8")
    capsys.readouterr()
    rc = main(["event", "verify", str(signed_path)])
    assert rc == 1
    assert '"verified": false' in capsys.readouterr().out


def test_uri_parse_format(home: Path, capsys: pytest.CaptureFixture) -> None:
    # parse
    capsys.readouterr()
    assert main(["uri", "parse", "phip://acme.example/parts/widget-001"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["authority"] == "acme.example"
    assert parsed["namespace"] == "parts"
    assert parsed["local_id"] == "widget-001"

    # format
    capsys.readouterr()
    assert (
        main(
            [
                "uri", "format",
                "--authority", "acme.example",
                "--namespace", "parts",
                "--local-id", "widget-001",
            ]
        )
        == 0
    )
    assert "phip://acme.example/parts/widget-001" in capsys.readouterr().out


def test_canonicalize_jcs(
    tmp_path: Path, home: Path, capsys: pytest.CaptureFixture
) -> None:
    src = tmp_path / "in.json"
    src.write_text('{"z":1,"a":[2,1],"m":{"y":1,"x":2}}', encoding="utf-8")
    capsys.readouterr()
    assert main(["canonicalize", str(src)]) == 0
    out = capsys.readouterr().out.strip()
    assert out == '{"a":[2,1],"m":{"x":2,"y":1},"z":1}'


# ── server integration (mocked HTTP) ─────────────────────────────────


@pytest.mark.asyncio
async def test_get_calls_server(home: Path, httpx_mock, capsys: pytest.CaptureFixture) -> None:
    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/resolve/parts/widget-001?history=10",
        json={
            "phip_id": "phip://acme.example/parts/widget-001",
            "object_type": "component",
            "state": "concept",
            "history_length": 1,
            "head_hash": "sha256:abc",
            "history": [],
        },
    )
    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0
    capsys.readouterr()
    assert main(["get", "phip://acme.example/parts/widget-001"]) == 0
    out = capsys.readouterr().out
    assert "widget-001" in out
    assert "concept" in out


@pytest.mark.asyncio
async def test_create_pushes_signed_event(
    home: Path, httpx_mock, capsys: pytest.CaptureFixture
) -> None:
    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0

    # Build + sign an event end-to-end.
    capsys.readouterr()
    assert (
        main(
            [
                "event", "new",
                "--phip-id", "phip://acme.example/parts/widget-002",
                "--type", "created",
                "--payload", '{"object_type":"component","state":"concept"}',
            ]
        )
        == 0
    )
    unsigned = home / "ev.json"
    unsigned.write_text(capsys.readouterr().out, encoding="utf-8")
    capsys.readouterr()
    assert main(["event", "sign", str(unsigned)]) == 0
    signed = home / "signed.json"
    signed.write_text(capsys.readouterr().out, encoding="utf-8")

    # Mock create.
    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/objects/parts",
        method="POST",
        json={
            "phip_id": "phip://acme.example/parts/widget-002",
            "head_hash": "sha256:xyz",
            "history_length": 1,
        },
    )
    capsys.readouterr()
    assert main(["create", str(signed)]) == 0
    out = capsys.readouterr().out
    assert "widget-002" in out


@pytest.mark.asyncio
async def test_http_error_surfaces_phip_code(
    home: Path, httpx_mock, capsys: pytest.CaptureFixture
) -> None:
    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/resolve/parts/ghost?history=10",
        status_code=404,
        json={"detail": {"error": {"code": "OBJECT_NOT_FOUND", "message": "nope"}}},
    )
    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0
    rc = main(["get", "phip://acme.example/parts/ghost"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "OBJECT_NOT_FOUND" in err
