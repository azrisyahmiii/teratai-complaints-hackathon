import pytest
from fastapi.testclient import TestClient

from .conftest import complaint, wait_done

# CMP-00244: ATM shortfall, refund 550.00 → awaiting approval. CMP-00165: duplicate 46.66 → auto-resolved.
# CMP-00387: 3DS-OTP card payment → with fraud team, P1, received 23 Sep (ack overdue on the 30 Sep clock).
CASES = ("CMP-00244", "CMP-00165", "CMP-00387")


@pytest.fixture(autouse=True)
def _staff_session(client: TestClient) -> None:
    client.headers.update({"X-Requested-With": "teratai"})
    assert client.post("/api/auth/login", json={"username": "asyraf", "password": "000000"}).status_code == 200


def _load(client: TestClient) -> None:
    for cid in CASES:
        assert client.post("/complaints", json=complaint(cid)).status_code == 202
    for cid in CASES:
        assert wait_done(client, cid)["status"] == "done"


def test_list_counts_figures_and_filter(client: TestClient) -> None:
    _load(client)
    body = client.get("/api/cases").json()
    assert body["counts"] == {"all": 3, "awaiting_approval": 1, "auto_resolved": 1, "with_fraud_team": 1}
    assert [c["priority"] for c in body["items"]] == sorted(c["priority"] for c in body["items"])
    atm = next(c for c in body["items"] if c["complaint_id"] == "CMP-00244")
    assert atm["customer_name"] and atm["refund_amount_myr"] == "550.00" and atm["disputed_amount_myr"] == "1500.00"
    assert atm["self_check"] == "passed" and atm["ack_due"] is not None

    f = body["figures"]
    assert f["officer"]["waiting"] == 1 and f["officer"]["oldest"]["complaint_id"] == "CMP-00244"
    assert f["fraud"] == {"open": 1, "p1_open": 1, "ack_overdue": 1, "amount_disputed_myr": "2213.95"}
    assert f["manager"]["all"] == 3 and f["manager"]["errors"] == 0 and f["manager"]["processing"] == 0

    only = client.get("/api/cases", params={"state": "with_fraud_team"}).json()
    assert [c["complaint_id"] for c in only["items"]] == ["CMP-00387"]
    assert only["counts"]["all"] == 3  # counts and figures ignore the filter


def test_detail_has_decision_evidence_tokens_and_trace(client: TestClient) -> None:
    _load(client)
    d = client.get("/api/cases/CMP-00244").json()
    assert d["case"]["case_state"] == "awaiting_approval"
    assert d["decision"]["outcome"] == "REFUND" and d["decision"]["calc"]
    matched = [e for e in d["evidence"] if e["role"] == "matched"]
    assert len(matched) == 1 and matched[0]["txn_id"] == client.get("/cases/CMP-00244").json()["matched_txn_id"]
    assert d["atm_journal"]["requested_myr"] == "1500.00" and d["atm_journal"]["dispensed_myr"] == "950.00"
    assert d["tokens"] and all(t["verified"] for t in d["tokens"])
    assert {"understand", "decide"} <= {e["stage"] for e in d["events"]}
    assert d["outbox"] == []


def test_detail_unknown_is_404(client: TestClient) -> None:
    assert client.get("/api/cases/NOPE-1").status_code == 404


def test_check_reply_flags_wrong_amount_and_changes_nothing(client: TestClient) -> None:
    _load(client)
    reply = client.get("/api/cases/CMP-00244").json()["reply_text"]
    bad = client.post("/api/cases/CMP-00244/check-reply", json={"text": reply.replace("550.00", "600.00")}).json()
    assert bad["self_check"] == "flagged"
    assert any("600.00" in i["message"] for i in bad["issues"])
    assert any(t["text"].endswith("600.00") and not t["verified"] for t in bad["tokens"])
    ok = client.post("/api/cases/CMP-00244/check-reply", json={"text": reply}).json()
    assert ok["self_check"] == "passed"
    assert client.get("/cases/CMP-00244").json()["case_state"] == "awaiting_approval"


def test_outbox_newest_first_with_names(client: TestClient) -> None:
    _load(client)
    r = client.post("/cases/CMP-00244/actions", json={"action": "approve", "actor": "Aina", "reason": "ok"})
    assert r.status_code == 200
    items = client.get("/api/outbox").json()
    assert items[0]["complaint_id"] == "CMP-00244" and items[0]["authorised_by"] == "Aina"
    assert {i["complaint_id"] for i in items} == set(CASES)  # auto + fraud holding reply + approved
    assert all(i["customer_name"] for i in items)
