# The API your agent must expose

Every team exposes the same small HTTP API, so the live round treats every team the same way. JSON in, JSON out. Use any framework (FastAPI, Flask, Express…); [`build_guide.md`](build_guide.md#the-api) has a working FastAPI example.

Test yours at any time with the same script the organisers use:

```bash
python scoring/api_check.py http://localhost:8000
```

| Endpoint | What it does |
|---|---|
| `POST /complaints` | Hand the agent one new complaint |
| `GET /cases/{complaint_id}` | The case: the agent's decision, where the case is in the workflow, and any human action |
| `POST /cases/{complaint_id}/actions` | A human approves, rejects, or edits and approves a case that is waiting for approval |
| `GET /health` | `200` when the service is up |

## `POST /complaints`

The body is the six fields of a `complaints.csv` row:

```json
{
  "complaint_id": "CMP-00244",
  "customer_id": "CUS-02394",
  "received_at": "2026-07-20 22:32",
  "channel": "Email",
  "subject": "ATM did not dispense cash",
  "text": "Hello, the machine did not dispense all of the cash when I withdrew about RM1,500 last Friday, but the whole amount was deducted. Please resolve this quickly."
}
```

- Return `202` (or `200`/`201`) with `{"complaint_id": "...", "status": "processing"}` and process in the background. You may also decide synchronously and return `"status": "done"`, but answer within 120 seconds.
- Missing or empty required fields (`complaint_id`, `customer_id`, `received_at`, `text`): return `400` or `422`, never a `5xx`.
- The same `complaint_id` posted again must not create a second case or change the decision: return the existing case's status (`200` or `409`).
- A `customer_id` that isn't in the data must not crash the service. Reject it with a `4xx`, or accept it and flag the case.
- Use `received_at` from the complaint, not today's date, for "yesterday", "last Friday" and so on.

## `GET /cases/{complaint_id}`

Return the case, or `404` if you have never seen that ID. While the agent is working:

```json
{"complaint_id": "CMP-00244", "status": "processing"}
```

When it has decided (`"status": "done"`), every field below is required. This example is a refund over RM 500, so it waits for an officer:

```json
{
  "complaint_id": "CMP-00244",
  "status": "done",
  "category": "ATM_NOT_DISPENSED",
  "matched_txn_id": "TXN-0088211",
  "outcome": "REFUND",
  "refund_amount_myr": "550.00",
  "priority": "P2",
  "reply_language": "EN",
  "route": "HUMAN_APPROVAL",
  "reply_text": "Dear customer, ...",
  "self_check": "passed",
  "case_state": "awaiting_approval",
  "sent": false,
  "human_action": null
}
```

| Field | Values |
|---|---|
| `status` | `processing`, `done`, or `error` (the agent failed; say why in an `error` field) |
| `category`, `matched_txn_id`, `outcome`, `refund_amount_myr`, `priority`, `reply_language`, `route`, `reply_text` | **The agent's decision**, as in `predictions.csv` ([`scoring.md`](scoring.md)). `matched_txn_id` is `""` when there is none. These never change after the agent decides, whatever a human does later |
| `self_check` | `passed` or `flagged`: the result of your code check that every transaction ID and amount in the reply is in the evidence |
| `case_state` | Where the case is now (table below) |
| `sent` | `true` once a reply has gone to the customer (your outbox), `false` until then |
| `human_action` | `null` until a human acts; then what they did (see `POST /cases/{id}/actions`) |

### Case states (human in the loop)

| `case_state` | When | `sent` |
|---|---|---|
| `auto_resolved` | The agent routed it `AUTO_RESOLVE` and the reply went out | `true` |
| `awaiting_approval` | Routed `HUMAN_APPROVAL`: a decline, or a refund over RM 500. Waiting for an officer; **nothing has reached the customer** | `false` |
| `with_fraud_team` | Routed `FRAUD_TEAM`. With the fraud team; at most a holding reply (no decision, no money) has gone out | either |
| `approved` | An officer approved it (as drafted, or edited); the reply went out | `true` |
| `rejected` | An officer rejected the agent's decision; nothing from the agent went out, and the officer handles the case | `false` |

## `POST /cases/{complaint_id}/actions`

A human acts on a case in `awaiting_approval`:

```json
{"action": "approve", "actor": "Aina (complaints officer)", "reason": "Journal confirms RM950 dispensed of RM1,500"}
```

| Field | Values |
|---|---|
| `action` | `approve` (send the drafted reply), `reject` (send nothing), or `edit_approve` (send `reply_text` instead) |
| `actor` | Required: who acted. A typed name is enough; no logins are needed for the main ranking |
| `reason` | A short reason (required for `reject` and `edit_approve`) |
| `reply_text` | Only for `edit_approve`: the edited reply. **Run your self-check on it**: if it mentions a transaction ID or amount that isn't in the evidence, refuse with `422` and send nothing |

Return the updated case (`200`). After an action, `case_state` is `approved` or `rejected`, `sent` follows the table above, and `human_action` holds the action, the actor, the reason, the time and the reply that went out:

```json
"human_action": {"action": "approve", "actor": "Aina (complaints officer)", "reason": "...", "at": "2026-10-23 15:41:07", "reply_text": "Dear customer, ..."}
```

Errors: `404` for an unknown case; `409` if the case isn't `awaiting_approval` (for example, auto-resolved or already approved); `422` for a missing actor, an unknown action, or an edited reply that fails the self-check. The agent's decision fields never change.

Your own UI can call this endpoint for its Approve and Reject buttons. That way the live round and your demo use the same path.

## Being reachable in the live round

The organisers' laptop calls your API right after the 15:00 freeze (the hidden test) and again in your demo (the human gate), so keep it running from 15:00 until your demo ends and put its URL in your submission PR. Either:
- run it on your laptop on the venue Wi-Fi, listening on all interfaces (for example `uvicorn app:app --host 0.0.0.0 --port 8000`), and give us `http://<your-laptop-ip>:8000`; or
- put it behind a tunnel (ngrok, Cloudflare Tunnel) and give us that URL.

We check that we can reach you at Checkpoint 2 on Day 2. Keep API keys for your LLM on your side; our calls carry no credentials.

## What the organisers' test checks

`scoring/api_check.py` sends all its complaints at once, polls each case until it is `done` (120 seconds allowed per complaint), checks every field against this contract, and scores the answers exactly like the leaderboard. It also checks that each case's `case_state` and `sent` match its route, and runs robustness probes:
- **Service:** `/health`, an unknown case ID (`404`), a complaint without text (`4xx`), an unknown customer (no `5xx`), the same complaint posted twice (no change, no duplicate).
- **Human in the loop**, on one case that is waiting for approval: it is `awaiting_approval` with `sent: false`; an edited reply with an invented amount is refused (`422`) and nothing is sent; an approval moves it to `approved` with `sent: true` and records the actor, without changing the agent's decision.

Probe results and timing go to the judges as part of the engineering score.
