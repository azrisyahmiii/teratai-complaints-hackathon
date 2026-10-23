"""GET /api/metrics: role scoping, null-not-zero, read-only, DEMO money values."""

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from teratai import db, pipeline
from teratai.models import ComplaintRow

from .conftest import complaint
from .test_auth import HEADERS, load_cases, login

MONEY = re.compile(r"^\d+\.\d{2}$")


def get(client: TestClient, user: str, **params: str) -> dict[str, Any]:
    login(client, user)
    r = client.get("/api/metrics", params=params)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def keys(buckets: list[dict[str, Any]]) -> set[str]:
    return {b["key"] for b in buckets}


def test_auth_and_run_scope(client: TestClient) -> None:
    assert client.get("/api/metrics").status_code == 401
    for user in ("leon", "azri"):
        login(client, user)
        assert client.get("/api/metrics?run_id=evaltest").status_code == 403
    login(client, "asyraf")
    assert client.get("/api/metrics?run_id=evaltest").status_code == 200


def test_officer_fraud_manager_scoping(client: TestClient) -> None:
    load_cases(client)
    o = get(client, "leon")
    assert o["role"] == "officer" and o["volume"]["total"] == 3
    assert o["fraud"] is None and o["teams"] is None and o["money"] is not None
    assert "FRAUD_TEAM" not in keys(o["outcomes"]["by_route"])
    assert "UNAUTHORISED_CARD" not in o["options"]["categories"]
    assert o["performance"]["cases_measured"] == 3
    f = get(client, "azri")
    assert f["volume"]["total"] == 1 and f["money"] is None and f["teams"] is None
    assert f["fraud"]["open"] == 1 and keys(f["outcomes"]["by_route"]) == {"FRAUD_TEAM"}
    assert f["fraud"]["acknowledged"] is None and "fraud.acknowledged" in f["unavailable"]
    m = get(client, "asyraf")
    assert m["volume"]["total"] == 4 and sum(t["cases"] for t in m["teams"]) == 4
    assert m["money"] is not None and m["fraud"] is not None and m["teams"] is not None


def test_money_and_human_action(client: TestClient) -> None:
    load_cases(client)
    m = get(client, "asyraf")["money"]
    assert m["refunds_paid_myr"] == "46.66" and m["awaiting_approval_myr"] == "5237.10"
    login(client, "leon")
    r = client.post("/api/cases/CMP-00244/actions", json={"action": "approve"}, headers=HEADERS)
    assert r.status_code == 200, r.text
    body = get(client, "asyraf")
    assert body["money"]["refunds_paid_myr"] == "596.66"
    assert body["money"]["awaiting_approval_myr"] == "4687.10"
    assert body["operations"]["turnaround"]["count"] == 1
    assert body["guardrails"]["overrides"]["denominator"] == 1
    assert sum(b["count"] for b in body["operations"]["backlog"]) == body["volume"]["total"]


def test_filters_and_null_not_zero(client: TestClient) -> None:
    load_cases(client)
    assert get(client, "asyraf", category="ATM_NOT_DISPENSED")["volume"]["total"] == 1
    empty = get(client, "asyraf", date_from="2030-01-01")
    assert empty["volume"]["total"] == 0
    assert empty["money"]["avg_refund_myr"] is None
    assert empty["outcomes"]["auto_resolve_rate"]["pct"] is None
    assert empty["performance"]["latency_p50_ms"] is None
    assert client.get("/api/metrics?category=NOPE").status_code == 422
    assert client.get("/api/metrics?channel=Fax").status_code == 422
    assert client.get("/api/metrics?date_from=2026-09-02&date_to=2026-09-01").status_code == 422


def test_run_without_events(client: TestClient) -> None:
    row = ComplaintRow.model_validate(complaint("CMP-00165"))
    decision = pipeline.process_complaint(row, run_id="evaltest")
    pipeline.store(row, decision)
    p = get(client, "asyraf", run_id="evaltest")
    assert p["volume"]["total"] == 1
    perf = p["performance"]
    assert perf["cases_measured"] == 0 and perf["latency_p50_ms"] is None
    assert perf["cost_total_usd"] is None and perf["cost_per_complaint_usd"] is None
    assert "performance" in p["unavailable"]


def test_read_only_and_money_format(client: TestClient) -> None:
    load_cases(client)

    def counts() -> tuple[int, ...]:
        with db.connect() as con:
            return tuple(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("cases", "case_events", "outbox"))

    before = counts()
    for user in ("asyraf", "leon", "azri"):
        body = get(client, user)
        get(client, user, category="DUPLICATE_CHARGE")
        for path, value in _walk(body):
            if path.endswith("_myr") and isinstance(value, str):
                assert MONEY.match(value), (path, value)
        assert datetime.fromisoformat(body["sim_now"])
    assert counts() == before
    assert Decimal(get(client, "asyraf")["fraud"]["amount_disputed_myr"]) == Decimal("2213.95")


def _walk(o: Any, path: str = "") -> list[tuple[str, Any]]:
    if isinstance(o, dict):
        return [x for k, v in o.items() for x in _walk(v, k)]
    if isinstance(o, list):
        return [x for v in o for x in _walk(v, path)]
    return [(path, o)]
