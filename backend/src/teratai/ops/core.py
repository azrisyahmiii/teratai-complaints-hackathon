"""HTTP client to the frozen core agent API. Tests monkeypatch `client` to return a TestClient of the core app."""

from typing import Any

import httpx
from fastapi import HTTPException

from teratai.ops import settings

_clients: dict[str, httpx.Client] = {}


def client() -> httpx.Client:
    url = settings.core_url()
    if url not in _clients:
        _clients[url] = httpx.Client(base_url=url, timeout=60)
    return _clients[url]


def send(method: str, path: str, **kw: Any) -> httpx.Response:
    """One call to the core; the response is returned whatever its status. Unreachable core -> 502."""
    try:
        return client().request(method, path, **kw)
    except httpx.TransportError as e:
        raise HTTPException(502, detail=f"Core agent API unreachable at {settings.core_url()}") from e


def call(method: str, path: str, **kw: Any) -> Any:
    """Like `send`, but a core error status is re-raised with the core's own `detail` (422 list, 409, 404)."""
    r = send(method, path, **kw)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise HTTPException(r.status_code, detail=detail)
    return r.json()
