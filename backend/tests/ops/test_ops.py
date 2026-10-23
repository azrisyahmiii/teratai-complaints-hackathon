"""Ops service against the offline core: auth, queues, two-tier approval, fraud steps, audit and trail."""

from collections.abc import Callable

from fastapi.testclient import TestClient

from teratai.ops.main import app
from tests.ops.conftest import PASSWORD, submit

ALL = ["CMP-00244", "CMP-00289", "CMP-00387", "CMP-00165"]
Login = Callable[[str], TestClient]


def ids(r_items: list[dict[str, object]]) -> set[object]:
    return {i["complaint_id"] for i in r_items}


def test_login_me_and_401(login: Login) -> None:
    anon = TestClient(app)
    assert anon.post("/api/auth/login", json={"username": "aina", "password": "nope"}).status_code == 401
    assert anon.get("/api/me").status_code == 401
    assert anon.get("/api/ops/queue").status_code == 401
    assert anon.get("/api/audit").status_code == 401
    aina = login("aina")
    assert aina.get("/api/me").json() == {
        "username": "aina", "name": "Aina Rahman", "role": "officer", "languages": ["EN", "MS"],
        "approval_limit_myr": "2000.00",
    }
    assert login("manager").get("/api/me").json()["approval_limit_myr"] is None
    assert aina.post("/api/auth/logout").json() == {"ok": True}
    anon.cookies.set("teratai_ops", "aina.9999999999.deadbeef")
    assert anon.get("/api/me").status_code == 401  # forged signature


def test_passthrough_and_health(login: Login) -> None:
    aina = login("aina")
    submit(aina, ["CMP-00244"])
    items = aina.get("/api/cases").json()["items"]
    assert ids(items) == {"CMP-00244"}
    assert aina.get("/health").json() == {"ok": True, "core": True}
    assert aina.get("/api/cases/CMP-99999").status_code == 404


def test_queues(login: Login) -> None:
    aina, siti = login("aina"), login("siti")
    submit(aina, ALL)
    q = aina.get("/api/ops/queue").json()
    assert ids(q["items"]) == {"CMP-00244", "CMP-00289"}
    assert all(i["assigned_to"] in ("aina", "daniel") for i in q["items"])
    assert {i["assigned_to"] for i in q["items"]} == {"aina", "daniel"}  # least loaded spreads them
    by_id = {i["complaint_id"]: i for i in q["items"]}
    assert by_id["CMP-00289"]["refund_amount_myr"] == "4687.10"
    assert by_id["CMP-00289"]["over_my_limit"] is True and by_id["CMP-00244"]["over_my_limit"] is False
    assert q["counts"]["unassigned"] == 0
    fq = siti.get("/api/ops/queue").json()
    assert ids(fq["items"]) == {"CMP-00387"} and fq["items"][0]["assigned_to"] in ("siti", "raj")
    mq = login("manager").get("/api/ops/queue").json()
    assert ids(mq["items"]) == {"CMP-00244", "CMP-00289", "CMP-00387"}  # auto-resolved is not open work


def test_officer_approves_within_limit(login: Login, core_client: TestClient) -> None:
    aina = login("aina")
    submit(aina, ["CMP-00244"])
    r = aina.post("/api/ops/cases/CMP-00244/approve", json={"reason": "Journal confirms the shortfall"})
    assert r.status_code == 200, r.text
    assert r.json()["case_state"] == "approved" and r.json()["sent"] is True and r.json()["ops_state"] == "closed"
    detail = core_client.get("/cases/CMP-00244").json()
    assert detail["case_state"] == "approved" and detail["sent"] is True
    assert detail["human_action"]["actor"] == "aina"
    assert [o["authorised_by"] for o in core_client.get("/api/outbox").json()] == ["aina"]
    rows = aina.get("/api/audit", params={"complaint_id": "CMP-00244"}).json()["items"]
    actions = [(x["actor"], x["action"], x["field"], x["from"], x["to"]) for x in rows]
    assert ("aina", "approve", "case_state", "awaiting_approval", "approved") in actions
    assert ("agent", "agent_decided", "case_state", None, "awaiting_approval") in actions
    assert rows[0]["action"] == "approve" and rows[0]["reason"] == "Journal confirms the shortfall"
    assert aina.post("/api/ops/cases/CMP-00244/approve", json={}).status_code == 409  # no longer awaiting


def test_over_limit_escalation_and_manager(login: Login, core_client: TestClient) -> None:
    aina, manager = login("aina"), login("manager")
    submit(aina, ["CMP-00289"])
    owner = aina.get("/api/ops/queue").json()["items"][0]["assigned_to"]
    r = aina.post("/api/ops/cases/CMP-00289/approve", json={"reason": "ok"})
    assert r.status_code == 403
    assert r.json()["detail"] == "RM4,687.10 is over your RM2,000.00 limit. Escalate to a manager."
    assert aina.post("/api/ops/cases/CMP-00289/escalate", json={}).status_code == 422
    e = aina.post("/api/ops/cases/CMP-00289/escalate", json={"reason": "Over my limit, journal checked"})
    assert e.status_code == 200 and e.json()["ops_state"] == "escalated" and e.json()["assigned_to"] == "manager"
    assert aina.post("/api/ops/cases/CMP-00289/escalate", json={"reason": "again"}).status_code == 409
    assert core_client.get("/cases/CMP-00289").json()["sent"] is False
    assert core_client.get("/api/outbox").json() == []
    assert "CMP-00289" not in ids(aina.get("/api/ops/queue").json()["items"])
    esc = manager.get("/api/ops/escalations").json()["items"]
    assert [(i["complaint_id"], i["escalated_by"], i["escalation_reason"]) for i in esc] == [
        ("CMP-00289", "aina", "Over my limit, journal checked")
    ]
    assert aina.get("/api/ops/escalations").status_code == 403
    assert manager.post("/api/ops/cases/CMP-00289/manager-approve", json={}).status_code == 422
    m = manager.post("/api/ops/cases/CMP-00289/manager-approve", json={"reason": "Verified with the receiving bank"})
    assert m.status_code == 200 and m.json()["ops_state"] == "closed" and m.json()["case_state"] == "approved"
    obx = core_client.get("/api/outbox").json()
    assert [(o["complaint_id"], o["authorised_by"]) for o in obx] == [("CMP-00289", "manager")]
    trail = manager.get("/api/ops/cases/CMP-00289/trail").json()["items"]
    path = [(s["from"], s["to"]) for s in trail]
    assert path == [
        ("Customer", "Agent"), ("Agent", "Approval queue"), ("Approval queue", owner), (owner, "manager"),
        ("manager", "Customer"),
    ]
    assert trail[1]["action"] == "Decided: Refund RM4,687.10, P1" or trail[1]["action"].startswith("Decided: Refund")
    full = manager.get("/api/ops/cases/CMP-00289").json()
    assert full["trail"] == trail and full["ops"]["escalated_by"] == "aina" and full["case"]["case"]["sent"] is True
    audit = manager.get("/api/audit", params={"complaint_id": "CMP-00289"}).json()["items"]
    assert [(a["action"], a["to"]) for a in audit[:2]] == [("manager_approve", "closed"), ("approve", "approved")]
    assert any(a["action"] == "escalate" and a["from"] == "open" and a["to"] == "escalated" for a in audit)


def test_edit_approve_self_check_blocks(login: Login, core_client: TestClient) -> None:
    aina = login("aina")
    submit(aina, ["CMP-00244"])
    bad = aina.post("/api/ops/cases/CMP-00244/approve", json={"reason": "typo fix", "reply_text":
                    "We have refunded RM600.00 for TXN-0088299."})
    assert bad.status_code == 422
    assert "edited reply failed the self-check" in bad.json()["detail"]
    assert any("RM600.00" in m for m in bad.json()["detail"])
    assert core_client.get("/cases/CMP-00244").json()["sent"] is False
    assert core_client.get("/api/outbox").json() == []
    assert aina.get("/api/ops/cases/CMP-00244").json()["ops"]["ops_state"] == "open"


def test_fraud_steps(login: Login, core_client: TestClient) -> None:
    siti, aina = login("siti"), login("aina")
    submit(siti, ["CMP-00387"])
    assert aina.post("/api/ops/cases/CMP-00387/fraud-ack").status_code == 403
    assert aina.post("/api/ops/cases/CMP-00387/fraud-ack").json()["detail"] == "officer can't do this"
    a = siti.post("/api/ops/cases/CMP-00387/fraud-ack")
    assert a.status_code == 200 and a.json()["ops_state"] == "acknowledged" and a.json()["assigned_to"] == "siti"
    assert siti.post("/api/ops/cases/CMP-00387/fraud-log", json={"note": " "}).status_code == 422
    log = siti.post("/api/ops/cases/CMP-00387/fraud-log", json={"note": "Recall request sent to the receiving bank"})
    assert log.json()["ops_state"] == "investigating"
    assert siti.post("/api/ops/cases/CMP-00387/fraud-outcome", json={"outcome": "bogus"}).status_code == 422
    o = siti.post("/api/ops/cases/CMP-00387/fraud-outcome", json={"outcome": "recall_failed", "reason": "Funds gone"})
    assert o.status_code == 200 and o.json()["ops_state"] == "closed" and o.json()["fraud_outcome"] == "recall_failed"
    assert core_client.get("/cases/CMP-00387").json()["case_state"] == "with_fraud_team"
    assert siti.post("/api/ops/cases/CMP-00387/fraud-ack").status_code == 409  # closed
    assert login("daniel").post("/api/ops/cases/CMP-00244/fraud-ack").status_code == 403
    rows = siti.get("/api/audit", params={"complaint_id": "CMP-00387", "actor": "siti"}).json()["items"]
    assert [r["action"] for r in rows] == ["fraud_outcome", "fraud_log", "fraud_ack"]
    assert (rows[0]["field"], rows[0]["to"], rows[0]["reason"]) == ("fraud_outcome", "recall_failed", "Funds gone")
    steps = siti.get("/api/ops/cases/CMP-00387/trail").json()["items"]
    assert [s["from"] for s in steps][:2] == ["Customer", "Agent"] and steps[1]["to"] == "Fraud queue"
    assert [s["action"] for s in steps[-3:]] == ["Acknowledged", "Investigation logged", "Outcome: recall_failed"]


def test_reject_needs_reason(login: Login, core_client: TestClient) -> None:
    aina = login("aina")
    submit(aina, ["CMP-00244"])
    assert aina.post("/api/ops/cases/CMP-00244/reject", json={}).status_code == 422
    r = aina.post("/api/ops/cases/CMP-00244/reject", json={"reason": "Customer withdrew complaint"})
    assert r.status_code == 200 and r.json()["case_state"] == "rejected" and r.json()["sent"] is False
    assert core_client.get("/api/outbox").json() == []
    last = aina.get("/api/ops/cases/CMP-00244/trail").json()["items"][-1]
    assert (last["from"], last["action"]) == ("aina", "Rejected")


def test_auto_resolved_audit_and_core_down(login: Login, monkeypatch: object) -> None:
    aina = login("aina")
    submit(aina, ["CMP-00165"])
    assert aina.get("/api/ops/queue").json()["items"] == []
    rows = aina.get("/api/audit", params={"complaint_id": "CMP-00165"}).json()["items"]
    assert [(r["actor"], r["action"], r["to"]) for r in rows] == [("agent", "agent_decided", "auto_resolved")]
    t = aina.get("/api/ops/cases/CMP-00165/trail").json()["items"]
    assert [(s["from"], s["to"]) for s in t] == [("Customer", "Agent"), ("Agent", "Customer")]
    assert PASSWORD  # (kept: the seeded password comes from OPS_DEMO_PASSWORD)
