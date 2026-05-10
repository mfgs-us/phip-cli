"""Thin httpx wrapper for talking to a phip-server.

Uses phip-py's URI helpers to translate between phip:// URIs and
HTTPS endpoints; handles bearer auth; surfaces PhIP error envelopes
as Python exceptions.
"""

from __future__ import annotations

from typing import Any

import httpx
from phip import parse_uri

from phip_cli.remote import Remote


class HTTPError(Exception):
    """Raised when a phip-server returns a non-2xx response."""

    def __init__(self, status_code: int, code: str | None, message: str, body: Any) -> None:
        super().__init__(f"{status_code}: {code or '?'}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.body = body


def _check(resp: httpx.Response) -> Any:
    if resp.status_code < 400:
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.content
    body: Any
    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    code = None
    msg = resp.text
    if isinstance(body, dict):
        err = body.get("detail", {}).get("error") if "detail" in body else body.get("error")
        if isinstance(err, dict):
            code = err.get("code")
            msg = err.get("message") or msg
    raise HTTPError(resp.status_code, code, msg, body)


def _auth_headers(remote: Remote, *, write: bool) -> dict[str, str]:
    if write and remote.token:
        return {"Authorization": f"Bearer {remote.token}"}
    return {}


def get_meta(remote: Remote) -> dict[str, Any]:
    with httpx.Client(base_url=remote.url, timeout=10.0) as client:
        return _check(client.get("/.well-known/phip/meta"))

def get_object(remote: Remote, phip_uri: str, *, history: int = 10) -> dict[str, Any]:
    parsed = parse_uri(phip_uri)
    path = f"/.well-known/phip/resolve/{parsed.namespace}/{parsed.local_id}"
    with httpx.Client(base_url=remote.url, timeout=15.0) as client:
        return _check(client.get(path, params={"history": history}))

def get_history(
    remote: Remote, phip_uri: str, *, limit: int | None = None, cursor: str | None = None
) -> dict[str, Any]:
    parsed = parse_uri(phip_uri)
    path = f"/.well-known/phip/history/{parsed.namespace}/{parsed.local_id}"
    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if cursor is not None:
        params["cursor"] = cursor
    with httpx.Client(base_url=remote.url, timeout=30.0) as client:
        return _check(client.get(path, params=params))

def create_object(remote: Remote, namespace: str, signed_event: dict[str, Any]) -> dict[str, Any]:
    path = f"/.well-known/phip/objects/{namespace}"
    with httpx.Client(base_url=remote.url, timeout=15.0) as client:
        return _check(
            client.post(path, json=signed_event, headers=_auth_headers(remote, write=True))
        )


def push_event(remote: Remote, phip_uri: str, signed_event: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_uri(phip_uri)
    path = f"/.well-known/phip/push/{parsed.namespace}/{parsed.local_id}"
    with httpx.Client(base_url=remote.url, timeout=15.0) as client:
        return _check(
            client.post(path, json=signed_event, headers=_auth_headers(remote, write=True))
        )


def query_namespace(remote: Remote, namespace: str, body: dict[str, Any]) -> dict[str, Any]:
    path = f"/.well-known/phip/query/{namespace}"
    with httpx.Client(base_url=remote.url, timeout=15.0) as client:
        return _check(client.post(path, json=body))

def put_blob(
    remote: Remote, sha256_hex: str, data: bytes, *, media_type: str = "application/octet-stream"
) -> dict[str, Any]:
    path = f"/.well-known/phip/blobs/{sha256_hex}"
    with httpx.Client(base_url=remote.url, timeout=30.0) as client:
        return _check(            client.put(
                path,
                content=data,
                headers={
                    **_auth_headers(remote, write=True),
                    "content-type": media_type,
                },
            )
        )


def get_blob(remote: Remote, sha256_hex: str) -> bytes:
    path = f"/.well-known/phip/blobs/{sha256_hex}"
    with httpx.Client(base_url=remote.url, timeout=30.0) as client:
        resp = client.get(path)
        if resp.status_code >= 400:
            _check(resp)
        return resp.content
