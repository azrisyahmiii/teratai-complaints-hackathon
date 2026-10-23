"""Offline platform tests: template replies, regex extraction, no investigator, a fresh SQLite file per test."""

import csv
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from teratai import config

FIELDS = ["complaint_id", "customer_id", "received_at", "channel", "subject", "text"]


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REPLY_MODE", "template")
    monkeypatch.setenv("EXTRACT_MODE", "regex")
    monkeypatch.setenv("INVESTIGATOR", "off")
    monkeypatch.setenv("TERATAI_DB", str(tmp_path / "t.sqlite"))


@pytest.fixture
def client() -> Iterator[TestClient]:
    from teratai.api.main import app

    with TestClient(app) as c:
        yield c


def complaint(cid: str) -> dict[str, str]:
    with open(config.DATA_DIR / "complaints.csv", newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r["complaint_id"] == cid:
                return {k: r[k] for k in FIELDS}
    raise KeyError(cid)


def wait_done(client: TestClient, cid: str, timeout: float = 30) -> dict[str, Any]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        body: dict[str, Any] = client.get(f"/cases/{cid}").json()
        if body["status"] in ("done", "error"):
            return body
        time.sleep(0.1)
    raise AssertionError(f"{cid} not done in {timeout}s")
