# Ops platform: split and API contract (Day 2, 15:00–16:30)

The bonus ops platform ([docs/bonus_platform.md](../../bonus_platform.md)). Building stops at **16:30**.

## Who does what
| | Dev B (Azri) | Dev C |
|---|---|---|
| Owns | `backend/src/teratai/ops/**`, `backend/tests/ops/**`, this file | everything in `web/` except `web/lib/api/*`; `docs/dev/DESIGN.md` (his design wins) |
| Builds | the ops service below: login, escalation (U5), fraud steps, audit log (U7), case trail | login page (U4), all screens, the design |
| Branch | `feat/ops-api` | `feat/ops-ui` |

Dev B merges both into `main`. Dev C never edits `backend/`; Dev B never edits pages or styles. Until an endpoint
lands, build the screen on placeholder data shaped exactly like the JSON below.

## How it runs
```
browser ── Next (Dev C's UI, built with API_URL=http://localhost:8001)
              │  /api/*  and  /agent/*
              ▼
   ops service :8001 (this laptop)   own SQLite: users, ops state, audit events
              │  reads cases, sends approve / reject / edit_approve
              ▼
   core agent API :8000 (Dev A's laptop, FROZEN at 15:00)   http://10.0.30.214:8000
```
- Start: `cd backend && CORE_URL=http://10.0.30.214:8000 uv run fastapi run src/teratai/ops/main.py --port 8001`
- Never restart or change the core API on :8000. The ops service only calls it.
- `next build` fixes the API address at build time: always build the UI with `API_URL=http://localhost:8001`.
- The judges' live complaints land on the core API, so they appear in the ops platform as well.

## Contract (frozen at 15:20: add fields, never rename)
All bodies are JSON. Money is a string `"550.00"`. Times are `"2026-09-30 12:04:51"` (MYT). Errors are
`{"detail": "<readable message>"}` with the status codes listed.

### Passed through from the core API (same shapes as today, see `web/lib/api/schema.d.ts`)
`GET /api/cases` · `GET /api/cases/{id}` · `POST /api/cases/{id}/check-reply` · `GET /api/outbox` ·
`POST /complaints` · `GET /cases/{id}` · `POST /cases/{id}/actions` (the UI's `/agent/*` rewrite reaches these).

### Auth (U4)
Session cookie `teratai_ops` (httpOnly). Every `/api/ops/*` and `/api/audit` call needs it: `401` without.
| Call | Body | Returns |
|---|---|---|
| `POST /api/auth/login` | `{"username": "aina", "password": "…"}` | `200` `Me` and sets the cookie · `401` wrong login |
| `POST /api/auth/logout` | – | `200 {"ok": true}` |
| `GET /api/me` | – | `200` `Me` · `401` |

`Me` = `{"username": "aina", "name": "Aina Rahman", "role": "officer" | "fraud" | "manager", "languages": ["EN","MS"], "approval_limit_myr": "2000.00" | null}`

Seeded users (password in `.env` as `OPS_DEMO_PASSWORD`, same for all): `aina` and `daniel` (officer, RM2,000),
`siti` and `raj` (fraud, RM2,000), `manager` (no limit).

### Queues and case view
`GET /api/ops/queue` → the signed-in user's work, sorted by priority then received time:
```json
{"items": [OpsCase], "counts": {"mine": 3, "unassigned": 1, "escalated": 1}}
```
- officer: `awaiting_approval` cases not escalated · fraud: `with_fraud_team` cases · manager: escalated cases first, then everything open.

`OpsCase` = the core `CaseRow` (same fields as `/api/cases` items) plus:
```json
{"ops_state": "open" | "escalated" | "acknowledged" | "investigating" | "closed",
 "assigned_to": "aina" | null, "escalated_by": "aina" | null, "escalation_reason": "…" | null,
 "fraud_outcome": "confirmed_fraud" | "not_fraud" | "recall_succeeded" | "recall_failed" | null,
 "over_my_limit": true}
```
`GET /api/ops/cases/{id}` → `{"case": <core CaseDetail>, "ops": <the OpsCase extra fields>, "trail": [TrailStep]}`

### Officer and manager (U5: two-tier approval)
| Call | Who | Body | Result |
|---|---|---|---|
| `POST /api/ops/cases/{id}/approve` | officer, manager | `{"reason": "…", "reply_text": "…" (optional: edit)}` | Calls core `/actions` (`approve`, or `edit_approve` when `reply_text` is set) as this user. `200` updated `OpsCase` · `403 "RM4,687.10 is over your RM2,000.00 limit. Escalate to a manager."` · `422` failed self-check (core's detail list) · `409` not awaiting |
| `POST /api/ops/cases/{id}/reject` | officer, manager | `{"reason": "…"}` (required) | Core `reject`. `200` · `422` no reason · `409` |
| `POST /api/ops/cases/{id}/escalate` | officer | `{"reason": "…"}` (required) | `ops_state` → `escalated`, assigned to `manager`. Nothing is sent. `200` · `409` already escalated |
| `GET /api/ops/escalations` | manager | – | `{"items": [OpsCase]}` with `escalated_by` and `escalation_reason` |
| `POST /api/ops/cases/{id}/manager-approve` | manager | `{"reason": "…"}` (required) | Core `approve` with actor `manager`; `ops_state` → `closed`. The reply goes to the outbox with `authorised_by: "manager"` |
| `POST /api/ops/cases/{id}/manager-reject` | manager | `{"reason": "…"}` (required) | Core `reject`; `ops_state` → `closed` |

The core `/cases/{id}/actions` is untouched (no login, no limit): the limit check lives only here.

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
{"items": [{"ts": "2026-09-30 12:04:51", "complaint_id": "CMP-00244", "actor": "aina", "role": "officer",
  "action": "approve" | "reject" | "edit_approve" | "escalate" | "manager_approve" | "manager_reject" |
            "fraud_ack" | "fraud_log" | "fraud_outcome" | "assign" | "login" | "agent_decided",
  "field": "case_state" | "ops_state" | "assigned_to" | "reply_text" | null,
  "from": "awaiting_approval", "to": "approved", "reason": "Journal confirms the shortfall"}]}
```
Append-only. Show `from` and `to` as two plain columns (DESIGN.md: no strikethrough).

### Case trail: from whom to whom
`GET /api/ops/cases/{id}/trail` (also inside `GET /api/ops/cases/{id}`) → oldest first:
```json
{"items": [
  {"ts": "…", "from": "Customer", "to": "Agent", "action": "Complaint received", "note": "App chat"},
  {"ts": "…", "from": "Agent", "to": "Approval queue", "action": "Decided: Refund RM550.00, P2", "note": "Human approval: refund above RM500.00"},
  {"ts": "…", "from": "Approval queue", "to": "aina", "action": "Assigned", "note": "Officer, least loaded"},
  {"ts": "…", "from": "aina", "to": "manager", "action": "Escalated", "note": "Over aina's RM2,000.00 limit"},
  {"ts": "…", "from": "manager", "to": "Customer", "action": "Approved and sent", "note": "Reason: …"}]}
```

## Priorities (cut from the bottom)
1. Login + `GET /api/ops/queue` + officer approve / reject
2. Escalate + manager approve / reject (bonus doc case 2)
3. Fraud ack / log / outcome (bonus doc case 3)
4. Audit log page
5. Case trail view
6. Agent decision vs human action panel (from the core `CaseDetail`: decision fields vs `human_action`)

## Demo (minutes 11–15)
Three cases end to end (bonus doc "What to show"): CMP-00244 within aina's limit (edit → self-check catches
RM600.00 → revert → approve); CMP-00289 over the limit (aina escalates → manager approves → outbox shows
`authorised_by: manager`); CMP-00387 fraud (siti acknowledges, logs the recall, records the outcome; the customer
only saw the holding reply). Then the audit log and a trail.
