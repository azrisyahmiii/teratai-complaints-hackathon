"""Ops tests: the core runs in-process and offline; the ops app reaches it through a monkeypatched `core.client`."""

import csv
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from teratai import config
from teratai.ops import core

FIELDS = ["complaint_id", "customer_id", "received_at", "channel", "subject", "text"]
PASSWORD = "teratai-demo"


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REPLY_MODE", "template")
    monkeypatch.setenv("EXTRACT_MODE", "regex")
    monkeypatch.setenv("INVESTIGATOR", "off")
    monkeypatch.setenv("TERATAI_DB", str(tmp_path / "core.sqlite"))
    monkeypatch.setenv("OPS_DB", str(tmp_path / "ops.sqlite"))
    monkeypatch.setenv("OPS_DEMO_PASSWORD", PASSWORD)


@pytest.fixture
def core_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from teratai.api.main import app

    with TestClient(app) as c:
        monkeypatch.setattr(core, "client", lambda: c)
        yield c


@pytest.fixture
def login(core_client: TestClient) -> Callable[[str], TestClient]:
    from teratai.ops.main import app

    def _login(username: str) -> TestClient:
        c = TestClient(app)
        r = c.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return c

    return _login


def complaint(cid: str) -> dict[str, str]:
    with open(config.DATA_DIR / "complaints.csv", newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r["complaint_id"] == cid:
                return {k: r[k] for k in FIELDS}
    raise KeyError(cid)


def submit(ops: TestClient, cids: list[str], timeout: float = 60) -> None:
    """Post complaints through the ops service's passthrough and wait until the core has decided them."""
    for cid in cids:
        assert ops.post("/complaints", json=complaint(cid)).status_code in (200, 202)
    t0 = time.time()
    for cid in cids:
        while True:
            body: dict[str, Any] = ops.get(f"/cases/{cid}").json()
            if body["status"] in ("done", "error"):
                assert body["status"] == "done", body
                break
            assert time.time() - t0 < timeout, f"{cid} not done"
            time.sleep(0.1)
