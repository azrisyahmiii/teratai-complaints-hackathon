"""Ops service against the offline core: auth, queues, two-tier approval, fraud steps, audit and trail."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from teratai.api.main import app
from tests.ops.conftest import submit

ALL = ["CMP-00244", "CMP-00289", "CMP-00387", "CMP-00165"]
Login = Callable[[str], TestClient]


def ids(r_items: list[dict[str, object]]) -> set[object]:
    return {i["complaint_id"] for i in r_items}


def test_login_me_and_401(login: Login) -> None:
    anon = TestClient(app, headers={"X-Requested-With": "teratai"})
    assert anon.post("/api/auth/login", json={"username": "leon", "password": "nope"}).status_code == 401
    assert anon.get("/api/me").status_code == 401
    assert anon.get("/api/ops/queue").status_code == 401
    assert anon.get("/api/audit").status_code == 401
    leon = login("leon")
    assert leon.get("/api/me").json() == {
        "username": "leon", "role_label": "Complaints officer", "role": "officer",
        "approval_limit_myr": "2000.00",
    }
    assert login("asyraf").get("/api/me").json()["approval_limit_myr"] is None
    assert leon.post("/api/auth/logout").status_code == 204
    anon.cookies.set("teratai_ops", "leon.9999999999.deadbeef")
    assert anon.get("/api/me").status_code == 401  # old operations cookies grant no access
    assert anon.get("/api/ops/queue").status_code == 401


def test_passthrough_and_health(login: Login) -> None:
    leon = login("leon")
    submit(leon, ["CMP-00244"])
    items = leon.get("/api/cases").json()["items"]
    assert ids(items) == {"CMP-00244"}
    assert leon.get("/health").json() == {"ok": True}
    assert leon.get("/api/cases/CMP-99999").status_code == 404


def test_queues(login: Login) -> None:
    leon, azri = login("leon"), login("azri")
    submit(leon, ALL)
    q = leon.get("/api/ops/queue").json()
    assert ids(q["items"]) == {"CMP-00244", "CMP-00289"}
    assert all(i["assigned_to"] in ("leon", "vincent") for i in q["items"])
    assert {i["assigned_to"] for i in q["items"]} == {"leon", "vincent"}  # least loaded spreads them
    by_id = {i["complaint_id"]: i for i in q["items"]}
    assert by_id["CMP-00289"]["refund_amount_myr"] == "4687.10"
    assert by_id["CMP-00289"]["over_my_limit"] is True and by_id["CMP-00244"]["over_my_limit"] is False
    assert q["counts"]["unassigned"] == 0
    fq = azri.get("/api/ops/queue").json()
    assert ids(fq["items"]) == {"CMP-00387"} and fq["items"][0]["assigned_to"] in ("azri", "nishan")
    mq = login("asyraf").get("/api/ops/queue").json()
    assert ids(mq["items"]) == {"CMP-00244", "CMP-00289", "CMP-00387"}  # auto-resolved is not open work


def test_on_shift_limits_assignment(login: Login, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_ON_SHIFT", "leon,azri,asyraf")
    leon = login("leon")
    submit(leon, ALL)
    assert {i["assigned_to"] for i in leon.get("/api/ops/queue").json()["items"]} == {"leon"}
    assert {i["assigned_to"] for i in login("azri").get("/api/ops/queue").json()["items"]} == {"azri"}


def test_officer_approves_within_limit(login: Login, core_client: TestClient) -> None:
    leon = login("leon")
    submit(leon, ["CMP-00244"])
    r = leon.post("/api/ops/cases/CMP-00244/approve", json={"reason": "Journal confirms the shortfall"})
    assert r.status_code == 200, r.text
    assert r.json()["case_state"] == "approved" and r.json()["sent"] is True and r.json()["ops_state"] == "closed"
    detail = core_client.get("/cases/CMP-00244").json()
    assert detail["case_state"] == "approved" and detail["sent"] is True
    assert detail["human_action"]["actor"] == "leon"
    assert [o["authorised_by"] for o in core_client.get("/api/outbox").json()] == ["leon"]
    rows = leon.get("/api/audit", params={"complaint_id": "CMP-00244"}).json()["items"]
    actions = [(x["actor"], x["action"], x["field"], x["from"], x["to"]) for x in rows]
    assert ("leon", "approve", "case_state", "awaiting_approval", "approved") in actions
    assert ("agent", "agent_decided", "case_state", None, "awaiting_approval") in actions
    assert rows[0]["action"] == "approve" and rows[0]["reason"] == "Journal confirms the shortfall"
    assert leon.post("/api/ops/cases/CMP-00244/approve", json={}).status_code == 409  # no longer awaiting


def test_over_limit_escalation_and_manager(login: Login, core_client: TestClient) -> None:
    leon, manager = login("leon"), login("asyraf")
    submit(leon, ["CMP-00289"])
    owner = leon.get("/api/ops/queue").json()["items"][0]["assigned_to"]
    r = leon.post("/api/ops/cases/CMP-00289/approve", json={"reason": "ok"})
    assert r.status_code == 403
    assert r.json()["detail"] == "RM4,687.10 is over your RM2,000.00 limit. Escalate to a manager."
    assert leon.post("/api/ops/cases/CMP-00289/escalate", json={}).status_code == 422
    e = leon.post("/api/ops/cases/CMP-00289/escalate", json={"reason": "Over my limit, journal checked"})
    assert e.status_code == 200 and e.json()["ops_state"] == "escalated" and e.json()["assigned_to"] == "asyraf"
    assert leon.post("/api/ops/cases/CMP-00289/escalate", json={"reason": "again"}).status_code == 409
    assert core_client.get("/cases/CMP-00289").json()["sent"] is False
    assert core_client.get("/api/outbox").json() == []
    assert "CMP-00289" not in ids(leon.get("/api/ops/queue").json()["items"])
    esc = manager.get("/api/ops/escalations").json()["items"]
    assert [(i["complaint_id"], i["escalated_by"], i["escalation_reason"]) for i in esc] == [
        ("CMP-00289", "leon", "Over my limit, journal checked")
    ]
    assert leon.get("/api/ops/escalations").status_code == 403
    assert manager.post("/api/ops/cases/CMP-00289/manager-approve", json={}).status_code == 422
    m = manager.post("/api/ops/cases/CMP-00289/manager-approve", json={"reason": "Verified with the receiving bank"})
    assert m.status_code == 200 and m.json()["ops_state"] == "closed" and m.json()["case_state"] == "approved"
    obx = core_client.get("/api/outbox").json()
    assert [(o["complaint_id"], o["authorised_by"]) for o in obx] == [("CMP-00289", "asyraf")]
    trail = manager.get("/api/ops/cases/CMP-00289/trail").json()["items"]
    path = [(s["from"], s["to"]) for s in trail]
    assert path == [
        ("Customer", "Agent"), ("Agent", "Approval queue"), ("Approval queue", owner), (owner, "asyraf"),
        ("asyraf", "Customer"),
    ]
    assert trail[1]["action"] == "Decided: Refund RM4,687.10, P1" or trail[1]["action"].startswith("Decided: Refund")
    full = manager.get("/api/ops/cases/CMP-00289").json()
    assert full["trail"] == trail and full["ops"]["escalated_by"] == "leon" and full["case"]["case"]["sent"] is True
    audit = manager.get("/api/audit", params={"complaint_id": "CMP-00289"}).json()["items"]
    assert [(a["action"], a["to"]) for a in audit[:2]] == [("manager_approve", "closed"), ("approve", "approved")]
    assert any(a["action"] == "escalate" and a["from"] == "open" and a["to"] == "escalated" for a in audit)


def test_edit_approve_self_check_blocks(login: Login, core_client: TestClient) -> None:
    leon = login("leon")
    submit(leon, ["CMP-00244"])
    bad = leon.post("/api/ops/cases/CMP-00244/approve", json={"reason": "typo fix", "reply_text":
                    "We have refunded RM600.00 for TXN-0088299."})
    assert bad.status_code == 422
    assert "edited reply failed the self-check" in bad.json()["detail"]
    assert any("RM600.00" in m for m in bad.json()["detail"])
    assert core_client.get("/cases/CMP-00244").json()["sent"] is False
    assert core_client.get("/api/outbox").json() == []
    assert leon.get("/api/ops/cases/CMP-00244").json()["ops"]["ops_state"] == "open"


def test_fraud_steps(login: Login, core_client: TestClient) -> None:
    azri, leon = login("azri"), login("leon")
    submit(azri, ["CMP-00387"])
    assert leon.post("/api/ops/cases/CMP-00387/fraud-ack").status_code == 403
    assert leon.post("/api/ops/cases/CMP-00387/fraud-ack").json()["detail"] == "officer can't do this"
    a = azri.post("/api/ops/cases/CMP-00387/fraud-ack")
    assert a.status_code == 200 and a.json()["ops_state"] == "acknowledged" and a.json()["assigned_to"] == "azri"
    assert azri.post("/api/ops/cases/CMP-00387/fraud-log", json={"note": " "}).status_code == 422
    log = azri.post("/api/ops/cases/CMP-00387/fraud-log", json={"note": "Recall request sent to the receiving bank"})
    assert log.json()["ops_state"] == "investigating"
    assert azri.post("/api/ops/cases/CMP-00387/fraud-outcome", json={"outcome": "bogus"}).status_code == 422
    o = azri.post("/api/ops/cases/CMP-00387/fraud-outcome", json={"outcome": "recall_failed", "reason": "Funds gone"})
    assert o.status_code == 200 and o.json()["ops_state"] == "closed" and o.json()["fraud_outcome"] == "recall_failed"
    assert core_client.get("/cases/CMP-00387").json()["case_state"] == "with_fraud_team"
    assert azri.post("/api/ops/cases/CMP-00387/fraud-ack").status_code == 409  # closed
    assert login("vincent").post("/api/ops/cases/CMP-00244/fraud-ack").status_code == 403
    rows = azri.get("/api/audit", params={"complaint_id": "CMP-00387", "actor": "azri"}).json()["items"]
    assert [r["action"] for r in rows] == ["fraud_outcome", "fraud_log", "fraud_ack"]
    assert (rows[0]["field"], rows[0]["to"], rows[0]["reason"]) == ("fraud_outcome", "recall_failed", "Funds gone")
    steps = azri.get("/api/ops/cases/CMP-00387/trail").json()["items"]
    assert [s["from"] for s in steps][:2] == ["Customer", "Agent"] and steps[1]["to"] == "Fraud queue"
    assert [s["action"] for s in steps[-3:]] == ["Acknowledged", "Investigation logged", "Outcome: recall_failed"]


def test_reject_needs_reason(login: Login, core_client: TestClient) -> None:
    leon = login("leon")
    submit(leon, ["CMP-00244"])
    assert leon.post("/api/ops/cases/CMP-00244/reject", json={}).status_code == 422
    r = leon.post("/api/ops/cases/CMP-00244/reject", json={"reason": "Customer withdrew complaint"})
    assert r.status_code == 200 and r.json()["case_state"] == "rejected" and r.json()["sent"] is False
    assert core_client.get("/api/outbox").json() == []
    last = leon.get("/api/ops/cases/CMP-00244/trail").json()["items"][-1]
    assert (last["from"], last["action"]) == ("leon", "Rejected")


def test_auto_resolved_audit_and_core_down(login: Login, monkeypatch: object) -> None:
    leon = login("leon")
    submit(leon, ["CMP-00165"])
    assert leon.get("/api/ops/queue").json()["items"] == []
    rows = leon.get("/api/audit", params={"complaint_id": "CMP-00165"}).json()["items"]
    assert [(r["actor"], r["action"], r["to"]) for r in rows] == [("agent", "agent_decided", "auto_resolved")]
    t = leon.get("/api/ops/cases/CMP-00165/trail").json()["items"]
    assert [(s["from"], s["to"]) for s in t] == [("Customer", "Agent"), ("Agent", "Customer")]


def test_platform_session_and_team_boundaries(login: Login) -> None:
    manager = login("asyraf")
    submit(manager, ALL)
    for name in ("leon", "vincent"):
        officer = login(name)
        assert officer.get("/api/ops/queue").status_code == 200
        for suffix in ("", "/trail"):
            assert officer.get("/api/ops/cases/CMP-00387" + suffix).status_code == 403
        assert officer.get("/api/audit", params={"complaint_id": "CMP-00387"}).status_code == 403
        assert "CMP-00387" not in ids(officer.get("/api/audit").json()["items"])
    for name in ("azri", "nishan"):
        fraud = login(name)
        assert fraud.get("/api/ops/queue").status_code == 200
        assert fraud.get("/api/ops/cases/CMP-00244").status_code == 403
        assert fraud.post("/api/ops/cases/CMP-00244/approve", json={}).status_code == 403
    officer = login("leon")
    officer.headers.pop("X-Requested-With")
    assert officer.post("/api/ops/cases/CMP-00244/approve", json={}).status_code == 403
    officer.headers["X-Requested-With"] = "teratai"
    assert officer.post("/api/auth/logout").status_code == 204
    assert officer.get("/api/ops/queue").status_code == 401


def test_escalation_blocks_existing_staff_action(login: Login) -> None:
    officer = login("leon")
    submit(officer, ["CMP-00244"])
    assert officer.post("/api/ops/cases/CMP-00244/escalate", json={"reason": "Manager review"}).status_code == 200
    detail = officer.get("/api/cases/CMP-00244").json()
    assert detail["can_act"] is False
    for action in ("approve", "reject", "edit_approve"):
        response = officer.post("/api/cases/CMP-00244/actions", json={"action": action, "reason": "reviewed"})
        assert response.status_code == 403
    manager = login("asyraf")
    assert manager.post("/api/ops/cases/CMP-00244/manager-reject", json={"reason": "Reviewed"}).status_code == 200


def test_legacy_assignment_migration_preserves_history(tmp_path, monkeypatch) -> None:
    import sqlite3

    from teratai.ops import db

    path = tmp_path / "legacy.sqlite"
    monkeypatch.setenv("OPS_DB", str(path))
    with sqlite3.connect(path) as con:
        con.executescript(db.SCHEMA)
        for name in ("aina", "daniel", "siti", "raj", "manager"):
            con.execute("INSERT INTO ops_cases(complaint_id, ops_state, assigned_to, escalated_by) VALUES(?,?,?,?)",
                        (name, "open", name, name))
        con.execute("INSERT INTO events(actor, action) VALUES('aina', 'approve')")
    with db.connect() as con:
        rows = con.execute("SELECT assigned_to, escalated_by FROM ops_cases ORDER BY complaint_id").fetchall()
        assert {tuple(r) for r in rows} == {(n, n) for n in ("leon", "vincent", "azri", "nishan", "asyraf")}
        assert con.execute("SELECT actor FROM events").fetchone()[0] == "aina"


def test_platform_login_is_audited(login: Login) -> None:
    login("leon")
    manager = login("asyraf")
    rows = manager.get("/api/audit", params={"actor": "leon"}).json()["items"]
    assert any(r["action"] == "login" and r["role"] == "officer" for r in rows)
