# Integrated platform operations

Operations run in `teratai.api.main:app` alongside the existing staff API. Start the backend on port 8000 and keep the frontend's `API_URL=http://localhost:8000`. No separate operations server, `CORE_URL`, shared service credential, or internal HTTP connection is needed. The old `teratai.ops.main:app` entry point aliases this same app for compatibility.

## Authentication and storage

All staff routes, including `/api/ops/*` and `/api/audit`, use the revocable `teratai_session` cookie. Every POST requires `X-Requested-With: teratai`; the frontend API client already supplies it. Login and logout use the existing `/api/auth/login` and `/api/auth/logout` routes (logout returns 204). `/api/me` keeps the platform shape: username, role, role_label, approval_limit_myr.

The existing five IDs use password `000000`: `asyraf` (manager), `leon` and `vincent` (officer, RM2,000 limit), `azri` and `nishan` (fraud). General and fraud staff can only access cases in their own team, including detail, trail and audit endpoints. Session identity supplies the action actor.

Platform users and sessions stay in `TERATAI_DB`; workflow state and history stay in `OPS_DB` (default `backend/var/ops.sqlite`). Existing data is retained. On opening an older operations database, ownership and escalation references migrate: aina to leon, daniel to vincent, siti to azri, raj to nishan, manager to asyraf. Historical event actors remain unchanged. The old operations users table, if present, is unused; no old password or cookie grants access.

`OPS_ON_SHIFT=leon,azri,asyraf` can limit new assignments to those IDs. Without it, assignment uses all platform users of the appropriate role, choosing the least loaded and breaking ties by username.

## API contract

All bodies are JSON. Money is a string. Errors use `{"detail": ...}`. Existing staff list, detail, reply-check, outbox and intake endpoints remain in the platform.

### Queues and case view
`GET /api/ops/queue` → the signed-in user's work, sorted by priority then received time:
```json
{"items": [OpsCase], "counts": {"mine": 3, "unassigned": 1, "escalated": 1}}
```
- officer: `awaiting_approval` cases not escalated · fraud: `with_fraud_team` cases · manager: escalated cases first, then everything open.

`OpsCase` = the core `CaseRow` (same fields as `/api/cases` items) plus:
```json
{"ops_state": "open" | "escalated" | "acknowledged" | "investigating" | "closed",
 "assigned_to": "leon" | null, "escalated_by": "leon" | null, "escalation_reason": "…" | null,
 "fraud_outcome": "confirmed_fraud" | "not_fraud" | "recall_succeeded" | "recall_failed" | null,
 "over_my_limit": true}
```
`GET /api/ops/cases/{id}` → `{"case": <core CaseDetail>, "ops": <the OpsCase extra fields>, "trail": [TrailStep]}`

### Officer and manager (U5: two-tier approval)
| Call | Who | Body | Result |
|---|---|---|---|
| `POST /api/ops/cases/{id}/approve` | officer, manager | `{"reason": "…", "reply_text": "…" (optional: edit)}` | Calls core `/actions` (`approve`, or `edit_approve` when `reply_text` is set) as this user. `200` updated `OpsCase` · `403 "RM4,687.10 is over your RM2,000.00 limit. Escalate to a manager."` · `422` failed self-check (core's detail list) · `409` not awaiting |
| `POST /api/ops/cases/{id}/reject` | officer, manager | `{"reason": "…"}` (required) | Core `reject`. `200` · `422` no reason · `409` |
| `POST /api/ops/cases/{id}/escalate` | officer | `{"reason": "…"}` (required) | `ops_state` → `escalated`, assigned to `asyraf`. Nothing is sent. `200` · `409` already escalated |
| `GET /api/ops/escalations` | manager | – | `{"items": [OpsCase]}` with `escalated_by` and `escalation_reason` |
| `POST /api/ops/cases/{id}/manager-approve` | manager | `{"reason": "…"}` (required) | Core `approve` with the signed-in manager ID; `ops_state` → `closed`. The reply goes to the outbox with `authorised_by: "asyraf"` |
| `POST /api/ops/cases/{id}/manager-reject` | manager | `{"reason": "…"}` (required) | Core `reject`; `ops_state` → `closed` |

Staff actions reuse the platform handler, including team scope, sensitive-case restrictions, approval limits and reply self-checks. Escalation also blocks officer actions through the original staff endpoint. The organiser API remains unchanged and is not proxied by the frontend.

### Fraud analyst (fraud workbench)
| Call | Body | Result |
|---|---|---|
| `POST /api/ops/cases/{id}/fraud-ack` | – | `ops_state` → `acknowledged`, assigned to the analyst |
| `POST /api/ops/cases/{id}/fraud-log` | `{"note": "Recall request sent to the receiving bank"}` | `ops_state` → `investigating`; note goes to the audit log |
| `POST /api/ops/cases/{id}/fraud-outcome` | `{"outcome": "confirmed_fraud" \| "not_fraud" \| "recall_succeeded" \| "recall_failed", "reason": "…"}` | `ops_state` → `closed` |
All need role `fraud` (or `manager`), `409` when the case is not `with_fraud_team`. The customer only ever sees the holding reply.

### Audit log (U7)
`GET /api/audit?complaint_id=&actor=&limit=200` → newest first:
```json
{"items": [{"ts": "2026-09-30 12:04:51", "complaint_id": "CMP-00244", "actor": "leon", "role": "officer",
  "action": "approve" | "reject" | "edit_approve" | "escalate" | "manager_approve" | "manager_reject" |
            "fraud_ack" | "fraud_log" | "fraud_outcome" | "assign" | "login" | "agent_decided",
  "field": "case_state" | "ops_state" | "assigned_to" | "reply_text" | null,
  "from": "awaiting_approval", "to": "approved", "reason": "Journal confirms the shortfall"}]}
```
Audit results are scoped to cases visible to the session, before applying the result limit. A case from another team returns 403. Managers see all operations events.

Append-only. Also `field: "fraud_outcome"` (to = the outcome), `login` rows (no complaint_id, manager only) and `agent` `assign` rows. Show `from` and `to` as two plain columns (DESIGN.md: no strikethrough).

### Case trail: from whom to whom
`GET /api/ops/cases/{id}/trail` (also inside `GET /api/ops/cases/{id}`) → oldest first:
```json
{"items": [
  {"ts": "…", "from": "Customer", "to": "Agent", "action": "Complaint received", "note": "App chat"},
  {"ts": "…", "from": "Agent", "to": "Approval queue", "action": "Decided: Refund RM550.00, P2", "note": "Human approval: refund above RM500.00"},
  {"ts": "…", "from": "Approval queue", "to": "leon", "action": "Assigned", "note": "Officer, least loaded"},
  {"ts": "…", "from": "leon", "to": "asyraf", "action": "Escalated", "note": "Over leon's RM2,000.00 limit"},
  {"ts": "…", "from": "asyraf", "to": "Customer", "action": "Approved and sent", "note": "Reason: …"}]}
```
