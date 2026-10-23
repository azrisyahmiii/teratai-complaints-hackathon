import csv
import json
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from teratai import config, db

from .conftest import complaint, wait_done

REQUIRED = {
    "complaint_id", "status", "category", "matched_txn_id", "outcome", "refund_amount_myr", "priority",
    "reply_language", "route", "reply_text", "self_check", "case_state", "sent", "human_action",
}
DECISION = ("category", "matched_txn_id", "outcome", "refund_amount_myr", "priority", "reply_language", "route",
            "reply_text")


def _example() -> dict[str, str]:
    path = config.BACKEND_DIR.parent / "examples" / "live_complaint_example.json"
    d: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return d


def _outbox(cid: str) -> int:
    with db.connect() as con:
        return int(con.execute("SELECT COUNT(*) FROM outbox WHERE complaint_id=?", (cid,)).fetchone()[0])


def test_example_flow(client: TestClient) -> None:
    r = client.post("/complaints", json=_example())
    assert r.status_code == 202
    assert r.json() == {"complaint_id": "CMP-00244", "status": "processing"}
    case = wait_done(client, "CMP-00244")
    assert REQUIRED <= set(case)
    assert case["refund_amount_myr"] == "550.00"
    assert case["route"] == "HUMAN_APPROVAL"
    assert case["case_state"] == "awaiting_approval" and case["sent"] is False
    assert case["human_action"] is None
    assert _outbox("CMP-00244") == 0
    assert client.get("/health").json() == {"ok": True}


def test_duplicate_post_unchanged(client: TestClient) -> None:
    client.post("/complaints", json=_example())
    before = wait_done(client, "CMP-00244")
    r = client.post("/complaints", json=_example())
    assert r.status_code == 200
    assert r.json()["status"] == "done"
    assert client.get("/cases/CMP-00244").json() == before


def test_rejections(client: TestClient) -> None:
    bad = {k: v for k, v in _example().items() if k != "text"}
    assert client.post("/complaints", json=bad).status_code == 422
    unknown = {**_example(), "complaint_id": "PROBE-X", "customer_id": "CUS-99999"}
    r = client.post("/complaints", json=unknown)
    assert r.status_code == 422 and "customer_id" in r.text
    assert client.get("/cases/NOPE").status_code == 404
    assert client.get("/cases/PROBE-X").status_code == 404


def test_empty_channel_accepted(client: TestClient) -> None:
    r = client.post("/complaints", json={**_example(), "channel": ""})
    assert r.status_code == 202
    assert wait_done(client, "CMP-00244")["status"] == "done"


def test_auto_resolved_and_fraud(client: TestClient) -> None:
    client.post("/complaints", json=complaint("CMP-00165"))
    client.post("/complaints", json=complaint("CMP-00387"))
    a = wait_done(client, "CMP-00165")
    f = wait_done(client, "CMP-00387")
    assert a["case_state"] == "auto_resolved" and a["sent"] is True
    assert _outbox("CMP-00165") == 1
    assert f["case_state"] == "with_fraud_team" and f["route"] == "FRAUD_TEAM"
    assert client.post("/cases/CMP-00165/actions", json={"action": "approve", "actor": "x"}).status_code == 409


def test_actions(client: TestClient) -> None:
    client.post("/complaints", json=_example())
    before = wait_done(client, "CMP-00244")
    url = "/cases/CMP-00244/actions"
    bad = {"action": "edit_approve", "actor": "Aina", "reason": "tidy",
           "reply_text": before["reply_text"] + " We have also credited RM987.65 to your account."}
    r = client.post(url, json=bad)
    assert r.status_code == 422
    still = client.get("/cases/CMP-00244").json()
    assert still["case_state"] == "awaiting_approval" and still["sent"] is False
    assert client.post(url, json={"action": "reject", "actor": "Aina", "reason": " "}).status_code == 422
    assert client.post(url, json={"action": "bogus", "actor": "Aina"}).status_code == 422
    assert client.post(url, json={"action": "approve", "actor": ""}).status_code == 422
    r = client.post(url, json={"action": "approve", "actor": "Aina", "reason": "ok"})
    assert r.status_code == 200
    after = r.json()
    assert after["case_state"] == "approved" and after["sent"] is True
    assert after["human_action"]["actor"] == "Aina"
    assert all(after[k] == before[k] for k in DECISION)
    assert _outbox("CMP-00244") == 1
    assert client.post(url, json={"action": "approve", "actor": "Aina"}).status_code == 409


def test_twenty_concurrent(client: TestClient) -> None:
    with open(config.DATA_DIR / "complaints.csv", newline="", encoding="utf-8-sig") as fh:
        ids = [r["complaint_id"] for r in csv.DictReader(fh)][:20]
    rows = [complaint(i) for i in ids]
    with ThreadPoolExecutor(20) as ex:
        codes = list(ex.map(lambda r: client.post("/complaints", json=r).status_code, rows))
    assert all(c == 202 for c in codes)
    for i in ids:
        assert wait_done(client, i)["status"] == "done"
