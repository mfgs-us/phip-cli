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


# ── New commands ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_key_register(home: Path, httpx_mock, capsys: pytest.CaptureFixture) -> None:
    """`key register` posts a self-signed bootstrap actor event for the
    default identity. Inspect the captured request body to confirm shape."""
    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0

    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/objects/keys",
        method="POST",
        json={
            "phip_id": "phip://test.local/keys/default",
            "head_hash": "sha256:x",
            "history_length": 1,
        },
    )
    capsys.readouterr()
    assert main(["key", "register"]) == 0

    # Inspect the request body the CLI sent.
    requests = httpx_mock.get_requests(
        url="https://acme.example/.well-known/phip/objects/keys"
    )
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["type"] == "created"
    assert body["actor"] == body["phip_id"] == "phip://test.local/keys/default"
    assert body["previous_hash"] == "genesis"
    assert body["payload"]["object_type"] == "actor"
    assert body["payload"]["state"] == "active"
    assert "phip:keys" in body["payload"]["attributes"]
    assert "signature" in body


@pytest.mark.asyncio
async def test_key_register_already_exists_is_ok(
    home: Path, httpx_mock, capsys: pytest.CaptureFixture
) -> None:
    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0
    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/objects/keys",
        method="POST",
        status_code=409,
        json={"detail": {"error": {"code": "OBJECT_EXISTS", "message": "already there"}}},
    )
    rc = main(["key", "register"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "already registered" in out


# ── blob put / get ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_blob_put_hashes_and_uploads(
    home: Path, tmp_path: Path, httpx_mock, capsys: pytest.CaptureFixture
) -> None:
    import hashlib

    payload = b"hello blob world"
    digest = hashlib.sha256(payload).hexdigest()
    f = tmp_path / "data.bin"
    f.write_bytes(payload)

    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0
    httpx_mock.add_response(
        url=f"https://acme.example/.well-known/phip/blobs/{digest}",
        method="PUT",
        json={
            "sha256": digest,
            "size_bytes": len(payload),
            "media_type": "application/octet-stream",
        },
    )
    capsys.readouterr()
    assert main(["blob", "put", str(f)]) == 0
    assert capsys.readouterr().out.strip() == digest


@pytest.mark.asyncio
async def test_blob_get_writes_content(
    home: Path, tmp_path: Path, httpx_mock, capsys: pytest.CaptureFixture
) -> None:
    payload = b"the bytes"
    digest = "a" * 64  # bogus, server doesn't actually validate on the mocked GET
    httpx_mock.add_response(
        url=f"https://acme.example/.well-known/phip/blobs/{digest}",
        method="GET",
        content=payload,
        headers={"content-type": "application/octet-stream"},
    )
    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0

    out = tmp_path / "got.bin"
    capsys.readouterr()
    assert main(["blob", "get", digest, "--out", str(out)]) == 0
    assert out.read_bytes() == payload


# ── log composite ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_composite(
    home: Path, tmp_path: Path, httpx_mock, capsys: pytest.CaptureFixture
) -> None:
    import hashlib

    sweep = tmp_path / "sweep.csv"
    sweep.write_text("a,b\n1,2\n", encoding="utf-8")
    digest = hashlib.sha256(sweep.read_bytes()).hexdigest()

    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0

    # 1. Blob PUT
    httpx_mock.add_response(
        url=f"https://acme.example/.well-known/phip/blobs/{digest}",
        method="PUT",
        json={"sha256": digest, "size_bytes": 8, "media_type": "text/csv"},
    )
    # 2. Resolve current head
    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/resolve/parts/widget-001?history=0",
        method="GET",
        json={
            "phip_id": "phip://acme.example/parts/widget-001",
            "object_type": "component",
            "state": "concept",
            "head_hash": "sha256:abc123",
            "history_length": 1,
            "history": [],
        },
    )
    # 3. Push the measurement
    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/push/parts/widget-001",
        method="POST",
        json={
            "phip_id": "phip://acme.example/parts/widget-001",
            "head_hash": "sha256:def456",
            "history_length": 2,
        },
    )

    capsys.readouterr()
    assert (
        main(
            [
                "log",
                "phip://acme.example/parts/widget-001",
                str(sweep),
                "--metric", "freq_response",
                "--value", "2.5e6",
                "--unit", "Hz",
                "--rig", "bench-2",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Logged freq_response" in out
    assert "head_hash:   sha256:def456" in out

    # Inspect the push body to confirm the measurement payload shape.
    pushes = httpx_mock.get_requests(
        url="https://acme.example/.well-known/phip/push/parts/widget-001"
    )
    assert len(pushes) == 1
    pushed = json.loads(pushes[0].content)
    assert pushed["type"] == "measurement"
    assert pushed["previous_hash"] == "sha256:abc123"
    assert pushed["payload"]["metric"] == "freq_response"
    assert pushed["payload"]["value"] == 2.5e6
    assert pushed["payload"]["unit"] == "Hz"
    assert pushed["payload"]["rig"] == "bench-2"
    assert pushed["payload"]["external_ref"]["content_hash"] == f"sha256:{digest}"
    assert "signature" in pushed


# ── verify ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_valid_chain(
    home: Path, httpx_mock, capsys: pytest.CaptureFixture
) -> None:
    """Build a real signed chain locally, mock the server returning it,
    and confirm verify walks it cleanly."""
    import uuid
    from datetime import datetime, timezone

    from phip import generate_keypair, hash_event, sign_event

    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0

    kp = generate_keypair()
    actor_uri = "phip://acme.example/keys/alice"
    obj_uri = "phip://acme.example/parts/widget-001"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Bootstrap actor event (self-signed).
    actor_ev = sign_event(
        {
            "event_id": str(uuid.uuid4()),
            "phip_id": actor_uri,
            "type": "created",
            "timestamp": now,
            "actor": actor_uri,
            "previous_hash": "genesis",
            "payload": {
                "object_type": "actor",
                "state": "active",
                "attributes": {
                    "phip:keys": {
                        **kp.jwk,
                        "use": "sig",
                        "key_ops": ["verify"],
                        "not_before": "2020-01-01T00:00:00Z",
                        "not_after": "2099-01-01T00:00:00Z",
                    }
                },
            },
        },
        kp.private,
        actor_uri,
    )

    # Object events: created → measurement, all signed by actor.
    obj_created = sign_event(
        {
            "event_id": str(uuid.uuid4()),
            "phip_id": obj_uri,
            "type": "created",
            "timestamp": now,
            "actor": actor_uri,
            "previous_hash": "genesis",
            "payload": {"object_type": "component", "state": "concept"},
        },
        kp.private,
        actor_uri,
    )
    obj_meas = sign_event(
        {
            "event_id": str(uuid.uuid4()),
            "phip_id": obj_uri,
            "type": "measurement",
            "timestamp": now,
            "actor": actor_uri,
            "previous_hash": hash_event(obj_created),
            "payload": {"metric": "x", "as_of": now, "value": 1.0, "unit": "Hz"},
        },
        kp.private,
        actor_uri,
    )

    # Mock history endpoint (single page).
    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/history/parts/widget-001",
        method="GET",
        json={
            "phip_id": obj_uri,
            "history_length": 2,
            "events": [obj_created, obj_meas],
            "next_cursor": None,
        },
    )
    # Mock the actor lookup (the verify command resolves the signing key).
    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/resolve/keys/alice?history=1",
        method="GET",
        json={
            "phip_id": actor_uri,
            "object_type": "actor",
            "state": "active",
            "head_hash": hash_event(actor_ev),
            "history_length": 1,
            "history": [actor_ev],
        },
    )

    capsys.readouterr()
    assert main(["verify", obj_uri]) == 0
    out = capsys.readouterr().out
    assert "events checked: 2" in out
    assert "events passed:  2" in out
    assert "OK: chain valid" in out


# ── show ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_show_table_format(
    home: Path, httpx_mock, capsys: pytest.CaptureFixture
) -> None:
    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/resolve/parts/widget-001?history=10",
        json={
            "phip_id": "phip://acme.example/parts/widget-001",
            "object_type": "component",
            "state": "concept",
            "history_length": 1,
            "head_hash": "sha256:x",
            "history": [
                {
                    "event_id": "abcd-1234",
                    "type": "created",
                    "timestamp": "2026-05-10T12:00:00Z",
                    "actor": "phip://acme.example/keys/alice",
                    "payload": {"object_type": "component", "state": "concept"},
                }
            ],
        },
    )
    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0
    capsys.readouterr()
    assert main(["show", "phip://acme.example/parts/widget-001", "--table"]) == 0
    out = capsys.readouterr().out
    assert "phip://acme.example/parts/widget-001" in out
    assert "events=1" in out
    assert "ts" in out and "type" in out
    assert "created" in out
    assert "abcd-123" in out  # first 8 chars of event_id "abcd-1234"


# ── bundle round-trip (offline) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_bundle_pack_unpack_verify(
    home: Path, tmp_path: Path, httpx_mock, capsys: pytest.CaptureFixture
) -> None:
    """Pack a real bundle from a server-mocked object, then unpack +
    verify it with no network."""
    import uuid
    from datetime import datetime, timezone

    from phip import hash_event, sign_event

    # Build a small chain that the CLI's identity can sign.
    assert main(["init", "--authority", "acme.example", "--remote", "https://acme.example"]) == 0
    # Reload the identity that init created — pack must use it as producer.
    from phip_cli.config import paths as _paths
    from phip_cli.identity import load_identity

    ident = load_identity(_paths(), "default")

    obj_uri = "phip://acme.example/parts/widget-001"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    obj_created = sign_event(
        {
            "event_id": str(uuid.uuid4()),
            "phip_id": obj_uri,
            "type": "created",
            "timestamp": now,
            "actor": ident.key_id,
            "previous_hash": "genesis",
            "payload": {"object_type": "component", "state": "concept"},
        },
        ident.keypair.private,
        ident.key_id,
    )
    head_hash = hash_event(obj_created)

    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/resolve/parts/widget-001?history=0",
        json={
            "phip_id": obj_uri,
            "object_type": "component",
            "state": "concept",
            "head_hash": head_hash,
            "history_length": 1,
            "history": [],
        },
    )
    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/history/parts/widget-001",
        json={
            "phip_id": obj_uri,
            "history_length": 1,
            "events": [obj_created],
            "next_cursor": None,
        },
    )

    out_bundle = tmp_path / "widget.phip-bundle"
    capsys.readouterr()
    assert main(["bundle", "pack", obj_uri, "--out", str(out_bundle)]) == 0
    assert out_bundle.exists() and out_bundle.stat().st_size > 0

    capsys.readouterr()
    assert main(["bundle", "unpack", str(out_bundle)]) == 0
    out = capsys.readouterr().out
    assert "objects:         1" in out
    assert "events:          1" in out
    assert obj_uri in out

    capsys.readouterr()
    assert main(["bundle", "verify", str(out_bundle)]) == 0
    assert "OK: bundle valid" in capsys.readouterr().out


# ── history --all + format flags ─────────────────────────────────────


@pytest.mark.asyncio
async def test_history_all_walks_pages(
    home: Path, httpx_mock, capsys: pytest.CaptureFixture
) -> None:
    # Page 1
    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/history/parts/widget-001",
        json={
            "phip_id": "phip://acme.example/parts/widget-001",
            "history_length": 5,
            "events": [
                {"event_id": "id1", "type": "created", "timestamp": "t1", "actor": "a"},
                {"event_id": "id2", "type": "measurement", "timestamp": "t2", "actor": "a"},
            ],
            "next_cursor": "2",
        },
    )
    # Page 2
    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/history/parts/widget-001?cursor=2",
        json={
            "phip_id": "phip://acme.example/parts/widget-001",
            "history_length": 5,
            "events": [
                {"event_id": "id3", "type": "measurement", "timestamp": "t3", "actor": "a"},
                {"event_id": "id4", "type": "measurement", "timestamp": "t4", "actor": "a"},
                {"event_id": "id5", "type": "measurement", "timestamp": "t5", "actor": "a"},
            ],
            "next_cursor": None,
        },
    )
    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0
    capsys.readouterr()
    assert main(["history", "phip://acme.example/parts/widget-001", "--all"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert len(payload["events"]) == 5
    assert payload["events"][0]["event_id"] == "id1"
    assert payload["events"][-1]["event_id"] == "id5"


@pytest.mark.asyncio
async def test_query_table(home: Path, httpx_mock, capsys: pytest.CaptureFixture) -> None:
    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/query/parts",
        method="POST",
        json={
            "results": [
                {
                    "phip_id": "phip://acme.example/parts/widget-001",
                    "object_type": "component",
                    "state": "concept",
                    "head_hash": "sha256:x",
                    "history_length": 3,
                },
                {
                    "phip_id": "phip://acme.example/parts/widget-002",
                    "object_type": "component",
                    "state": "qualified",
                    "head_hash": "sha256:y",
                    "history_length": 7,
                },
            ],
            "next_cursor": None,
        },
    )
    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0
    capsys.readouterr()
    assert main(["query", "parts", "--table"]) == 0
    out = capsys.readouterr().out
    # Header line + separator + 2 rows
    assert "phip_id" in out
    assert "widget-001" in out and "widget-002" in out
    assert "concept" in out and "qualified" in out


def test_meta_yaml(home: Path, httpx_mock, capsys: pytest.CaptureFixture) -> None:
    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/meta",
        json={"authority": "acme.example", "protocol_versions": ["0.1.0-draft"]},
    )
    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0
    capsys.readouterr()
    assert main(["meta", "--yaml"]) == 0
    out = capsys.readouterr().out
    assert "authority: acme.example" in out
    assert "protocol_versions:" in out


# ── Round 2: --version, config, object/transition/relate, token, schema, dry-run ──


def test_version(capsys: pytest.CaptureFixture) -> None:
    """`phip --version` exits 0 and prints something with 'phip-cli'."""
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "phip-cli" in out


def test_config_get_set_unset(home: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["init", "--authority", "test.local"]) == 0
    capsys.readouterr()
    assert main(["config", "set", "default_namespace", "parts"]) == 0
    capsys.readouterr()
    assert main(["config", "get", "default_namespace"]) == 0
    assert capsys.readouterr().out.strip() == "parts"
    capsys.readouterr()
    assert main(["config", "list"]) == 0
    out = capsys.readouterr().out
    assert "default_namespace" in out
    assert "parts" in out
    assert main(["config", "unset", "default_namespace"]) == 0
    rc = main(["config", "get", "default_namespace"])
    assert rc == 1


@pytest.mark.asyncio
async def test_object_new_dry_run(home: Path, capsys: pytest.CaptureFixture) -> None:
    """object new --dry-run signs but never POSTs (no httpx_mock needed)."""
    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "object", "new",
                "component",
                "phip://test.local/parts/widget-001",
                "--state", "concept",
                "--dry-run",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    ev = json.loads(out)
    assert ev["type"] == "created"
    assert ev["phip_id"] == "phip://test.local/parts/widget-001"
    assert ev["payload"]["object_type"] == "component"
    assert ev["payload"]["state"] == "concept"
    assert "signature" in ev


@pytest.mark.asyncio
async def test_object_new_with_shorthand(
    home: Path, httpx_mock, capsys: pytest.CaptureFixture
) -> None:
    """Shorthand id is expanded against default authority + namespace."""
    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0
    main(["config", "set", "default_namespace", "parts"])
    capsys.readouterr()

    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/objects/parts",
        method="POST",
        json={
            "phip_id": "phip://acme.example/parts/widget-001",
            "head_hash": "sha256:x",
            "history_length": 1,
        },
    )
    assert main(["object", "new", "component", "widget-001"]) == 0
    out = capsys.readouterr().out
    assert "Created phip://acme.example/parts/widget-001" in out


@pytest.mark.asyncio
async def test_transition_dry_run(home: Path, httpx_mock, capsys: pytest.CaptureFixture) -> None:
    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0

    # Mock the head fetch even though --dry-run.
    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/resolve/parts/widget-001?history=0",
        json={
            "phip_id": "phip://acme.example/parts/widget-001",
            "object_type": "component",
            "state": "concept",
            "head_hash": "sha256:abc",
            "history_length": 1,
            "history": [],
        },
    )
    capsys.readouterr()
    assert (
        main(
            [
                "transition",
                "phip://acme.example/parts/widget-001",
                "--to", "qualified",
                "--reason", "passed FAI",
                "--dry-run",
            ]
        )
        == 0
    )
    ev = json.loads(capsys.readouterr().out)
    assert ev["type"] == "transitioned"
    assert ev["payload"]["to"] == "qualified"
    assert ev["payload"]["reason"] == "passed FAI"
    assert ev["previous_hash"] == "sha256:abc"


@pytest.mark.asyncio
async def test_relate_dry_run(home: Path, httpx_mock, capsys: pytest.CaptureFixture) -> None:
    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0
    httpx_mock.add_response(
        url="https://acme.example/.well-known/phip/resolve/racks/rack-007?history=0",
        json={
            "phip_id": "phip://acme.example/racks/rack-007",
            "object_type": "fixture",
            "state": "deployed",
            "head_hash": "sha256:r",
            "history_length": 1,
            "history": [],
        },
    )
    capsys.readouterr()
    assert (
        main(
            [
                "relate",
                "phip://acme.example/racks/rack-007",
                "phip://quanta.com/servers/Q88421",
                "--type", "contains",
                "--dry-run",
            ]
        )
        == 0
    )
    ev = json.loads(capsys.readouterr().out)
    assert ev["type"] == "relation_added"
    assert ev["payload"]["relation"]["type"] == "contains"
    assert ev["payload"]["relation"]["phip_id"] == "phip://quanta.com/servers/Q88421"


# ── Token suite ──────────────────────────────────────────────────────


def test_token_mint_decode_verify(home: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["init", "--authority", "test.local"]) == 0

    # Mint
    capsys.readouterr()
    assert (
        main(
            [
                "token", "mint",
                "--scope", "read_state",
                "--object", "phip://test.local/parts/*",
                "--granted-to", "phip://test.local/keys/bob",
                "--ttl-hours", "1",
            ]
        )
        == 0
    )
    encoded = capsys.readouterr().out.strip()
    assert encoded  # base64url string

    # Decode
    capsys.readouterr()
    assert main(["token", "decode", encoded]) == 0
    decoded = json.loads(capsys.readouterr().out)
    assert decoded["scope"] == "read_state"
    assert decoded["object_filter"] == "phip://test.local/parts/*"
    assert decoded["granted_to"] == "phip://test.local/keys/bob"
    assert "signature" in decoded

    # Verify (against the local default identity that signed it)
    capsys.readouterr()
    assert main(["token", "verify", encoded, "--against", "default"]) == 0
    out = capsys.readouterr().out
    assert '"verified": true' in out


def test_token_verify_tampered(home: Path, capsys: pytest.CaptureFixture) -> None:
    """Tamper with the b64url payload → verify must fail."""
    import base64

    assert main(["init", "--authority", "test.local"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "token", "mint",
                "--scope", "read_state",
                "--object", "*",
                "--granted-to", "phip://test.local/keys/bob",
            ]
        )
        == 0
    )
    encoded = capsys.readouterr().out.strip()

    # Decode, mutate the granted_to, re-encode without re-signing.
    pad = (-len(encoded)) % 4
    raw = base64.urlsafe_b64decode(encoded + ("=" * pad))
    tok = json.loads(raw.decode("utf-8"))
    tok["granted_to"] = "phip://attacker.example/keys/eve"
    tampered = base64.urlsafe_b64encode(
        json.dumps(tok, separators=(",", ":"), sort_keys=True).encode()
    ).rstrip(b"=").decode()

    capsys.readouterr()
    rc = main(["token", "verify", tampered, "--against", "default"])
    assert rc == 1
    out = capsys.readouterr().out
    assert '"verified": false' in out


def test_token_use_updates_remote_bearer(
    home: Path, capsys: pytest.CaptureFixture
) -> None:
    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0
    # Mint a real-shaped token to install.
    capsys.readouterr()
    main(
        [
            "token", "mint",
            "--scope", "push_events",
            "--object", "*",
            "--granted-to", "phip://test.local/keys/default",
        ]
    )
    encoded = capsys.readouterr().out.strip()

    assert main(["token", "use", encoded, "--remote", "origin"]) == 0
    remotes = json.loads((home / "remotes.json").read_text("utf-8"))
    assert remotes[0]["token"] == encoded


# ── Schema validate ──────────────────────────────────────────────────


def test_schema_list_show(home: Path, capsys: pytest.CaptureFixture) -> None:
    capsys.readouterr()
    assert main(["schema", "list"]) == 0
    out = capsys.readouterr().out
    # We vendored the spec schemas; at least these should be present.
    for name in ("core", "capability-token", "bundle-manifest"):
        assert name in out

    capsys.readouterr()
    assert main(["schema", "show", "core"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema.get("$schema") or schema.get("type") or schema.get("$id")


def test_schema_validate_unknown_schema(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    f = tmp_path / "x.json"
    f.write_text("{}", encoding="utf-8")
    rc = main(["schema", "validate", str(f), "--schema", "no-such-schema"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no-such-schema" in err


# ── --dry-run on push / create ───────────────────────────────────────


@pytest.mark.asyncio
async def test_push_dry_run_does_not_call_server(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """No httpx_mock: dry-run must not make a request, otherwise pytest-httpx will complain."""
    assert main(["init", "--authority", "test.local", "--remote", "https://acme.example"]) == 0
    ev = {
        "event_id": "abc",
        "phip_id": "phip://acme.example/parts/widget-001",
        "type": "measurement",
        "timestamp": "2026-05-10T20:00:00Z",
        "actor": "phip://test.local/keys/default",
        "previous_hash": "sha256:zzz",
        "payload": {"metric": "x", "as_of": "2026-05-10T20:00:00Z"},
        "signature": {
            "algorithm": "Ed25519",
            "key_id": "phip://test.local/keys/default",
            "value": "0" * 88,
        },
    }
    f = tmp_path / "ev.json"
    f.write_text(json.dumps(ev), encoding="utf-8")
    capsys.readouterr()
    assert main(["push", str(f), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "widget-001" in out
    assert "measurement" in out


# ── Shell completion ────────────────────────────────────────────────


def test_completion_bash(capsys: pytest.CaptureFixture) -> None:
    assert main(["completion", "bash"]) == 0
    out = capsys.readouterr().out
    # shtab emits a bash function definition; whatever the exact form,
    # it should at least mention "phip" and "complete" or "compgen".
    assert "phip" in out
    assert ("compgen" in out or "complete" in out or "_phip" in out)
