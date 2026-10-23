"""Staff authentication and row access must hold even when bypassing the UI."""

import json

import pytest
from fastapi.testclient import TestClient

from teratai import db

from .conftest import complaint, wait_done

HEADERS = {"X-Requested-With": "teratai"}


def login(client: TestClient, username: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": "000000"}, headers=HEADERS)
    assert r.status_code == 200
    return r.json()


def load_cases(client: TestClient) -> None:
    for cid in ("CMP-00244", "CMP-00165", "CMP-00387", "CMP-00289"):
        assert client.post("/complaints", json=complaint(cid)).status_code == 202
        assert wait_done(client, cid)["status"] == "done"


def test_staff_requires_session(client: TestClient) -> None:
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/cases").status_code == 401
    assert client.get("/api/outbox").status_code == 401
    assert client.get("/api/export/predictions?run_id=live").status_code == 401


@pytest.mark.parametrize("username,role", [("asyraf", "manager"), ("leon", "officer"), ("azri", "fraud")])
def test_login_identity_and_logout(client: TestClient, username: str, role: str) -> None:
    r = client.post("/api/auth/login", json={"username": username, "password": "wrong"}, headers=HEADERS)
    assert r.status_code == 401
    user = login(client, username)
    assert user["username"] == username and user["role"] == role
    assert "password" not in user and "pw_hash" not in user
    assert client.get("/api/me").json() == user
    token = client.cookies.get("teratai_session")
    assert token and "httponly" in client.post(
        "/api/auth/login", json={"username": username, "password": "000000"}, headers=HEADERS
    ).headers["set-cookie"].lower()
    assert client.post("/api/auth/logout", headers=HEADERS).status_code == 204
    assert client.get("/api/me").status_code == 401
    client.cookies.set("teratai_session", token)
    assert client.get("/api/me").status_code == 401
    with db.connect() as con:
        assert con.execute("SELECT pw_hash FROM users WHERE username=?", (username,)).fetchone()[0] != "000000"


@pytest.mark.parametrize("username,allowed,denied", [
    ("leon", {"CMP-00244", "CMP-00165", "CMP-00289"}, "CMP-00387"),
    ("azri", {"CMP-00387"}, "CMP-00244"),
    ("asyraf", {"CMP-00244", "CMP-00165", "CMP-00387", "CMP-00289"}, None),
])
def test_rows_details_checks_and_outbox_scoped(client: TestClient, username: str, allowed: set[str], denied: str | None) -> None:
    load_cases(client)
    login(client, username)
    body = client.get("/api/cases").json()
    assert {c["complaint_id"] for c in body["items"]} == allowed
    assert body["counts"]["all"] == len(allowed)
    assert body["figures"]["manager"]["all"] == len(allowed)
    assert all(item["complaint_id"] in allowed for item in client.get("/api/outbox").json())
    for cid in allowed:
        assert client.get(f"/api/cases/{cid}").status_code == 200
    if denied:
        assert client.get(f"/api/cases/{denied}").status_code == 403
        assert client.post(f"/api/cases/{denied}/check-reply", json={"text": "hello"}, headers=HEADERS).status_code == 403
    if username != "asyraf":
        assert client.get("/api/export/predictions?run_id=live").status_code == 403
        assert client.get("/api/cases?run_id=other").status_code == 403


def test_staff_actions_use_session_identity_and_manager_limit(client: TestClient) -> None:
    load_cases(client)
    login(client, "azri")
    payload = {"action": "approve", "actor": "asyraf"}
    assert client.post("/api/cases/CMP-00244/actions", json=payload, headers=HEADERS).status_code == 403
    login(client, "leon")
    assert client.post("/api/cases/CMP-00289/actions", json=payload, headers=HEADERS).status_code == 403
    detail = client.get("/api/cases/CMP-00289").json()
    assert detail["can_act"] is False and detail["action_block_reason"]
    assert client.post("/api/cases/CMP-00244/actions", json=payload).status_code == 403
    r = client.post("/api/cases/CMP-00244/actions", json=payload, headers=HEADERS)
    assert r.status_code == 200 and r.json()["human_action"]["actor"] == "leon"
    login(client, "asyraf")
    assert client.post("/api/cases/CMP-00289/actions", json=payload, headers=HEADERS).status_code == 200


def test_expired_session_and_csrf(client: TestClient) -> None:
    assert client.post("/api/auth/login", json={"username": "leon", "password": "000000"}).status_code == 403
    login(client, "leon")
    with db.connect() as con:
        con.execute("UPDATE sessions SET expires_at=0")
    assert client.get("/api/me").status_code == 401


def test_pending_case_visible_only_to_submitter_and_manager(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from teratai.api import worker

    monkeypatch.setattr(worker, "submit", lambda *_: None)
    login(client, "leon")
    assert client.post("/api/complaints", json=complaint("CMP-00244"), headers=HEADERS).status_code == 202
    assert client.get("/api/cases/CMP-00244").status_code == 200
    login(client, "azri")
    assert client.get("/api/cases/CMP-00244").status_code == 403
    assert client.get("/api/cases").json()["items"] == []
    login(client, "asyraf")
    assert client.get("/api/cases/CMP-00244").status_code == 200


def test_login_throttled(client: TestClient) -> None:
    for _ in range(10):
        assert client.post("/api/auth/login", json={"username": "leon", "password": "wrong"}, headers=HEADERS).status_code == 401
    assert client.post("/api/auth/login", json={"username": "leon", "password": "000000"}, headers=HEADERS).status_code == 429


def test_decision_stays_immutable_on_authenticated_edit(client: TestClient) -> None:
    load_cases(client)
    login(client, "leon")
    before = client.get("/api/cases/CMP-00244").json()
    r = client.post("/api/cases/CMP-00244/actions", json={
        "action": "edit_approve", "reason": "test", "reply_text": before["reply_text"] + " RM987.65",
    }, headers=HEADERS)
    assert r.status_code == 422
    with db.connect() as con:
        stored = con.execute("SELECT * FROM cases WHERE complaint_id='CMP-00244'").fetchone()
        assert stored["sent"] == 0 and json.loads(stored["agent_decision"])["reply_text"] == before["reply_text"]
