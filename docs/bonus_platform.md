# Bonus: the ops platform

**This is an optional, separately scored part of the final ranking: the "Best Ops Platform" criterion, worth 25 of the 150 points. It is judged on its own and does not change your leaderboard/accuracy score.** Build it only once your core agent works — a team that skips it simply forgoes these 25 points and competes for the other 125. The agent and its API freeze at 15:00 on Day 2, but you can keep building this platform right up to the 16:30 demo ([README.md](../README.md)).

The core brief already defines the human-in-the-loop API ([`api.md`](api.md)): every case has a `case_state`, a `sent` flag and a `human_action`, and people act on cases through `POST /cases/{id}/actions` (`approve`, `reject`, `edit_approve`). For the main ranking that can be driven from a thin UI or even curl. **This bonus turns that same contract into a real back-office system:** the people a case is routed to sign in, see only their cases, and act on them through screens built for their job.

## Built on the core API

Don't invent a second workflow. The platform is a richer front end (and database) over the endpoints in [`api.md`](api.md):

- The cases your staff see are the same ones served by `GET /cases/{id}`; store the agent's decision fields, `self_check`, `case_state`, `sent` and `human_action` exactly as the API defines them.
- Your Approve / Reject / Edit-&-approve buttons call `POST /cases/{id}/actions` — the same endpoint the live round uses — so the platform and the hidden test exercise one code path. `scoring/api_check.py` must still pass.
- The platform *adds* what the main ranking deliberately leaves out: sign-in and roles, a second approval tier, a fraud investigation workbench, an audit trail and dashboards. Everything below is on top of the API, not a replacement for it.

**Keep role and limit enforcement in the platform layer, not in the frozen endpoint.** `scoring/api_check.py` grabs any `awaiting_approval` case and sends a plain `approve` with a typed actor, expecting `200` → `approved` / `sent: true` ([api.md](api.md#what-the-organisers-test-checks)). The core `POST /cases/{id}/actions` must still accept that — no logins, no limit check — or you lose hidden-test and engineering points. Put "this officer may only clear up to RM 5,000, escalate otherwise" in your UI and its own authorization, so the frozen contract the organisers call stays exactly as `api.md` specifies.

## The idea

Your agent writes each case to a database (the store behind `GET /cases/{id}`). On top of that database you build a small web app where bank staff resolve the cases the agent couldn't close on its own:

```
POST /complaints ─► agent ─► case in DB ─► queue ─► staff sign in ─► POST /cases/{id}/actions ─► DB updated ─► outbox
                                             │
          auto_resolved ─────────────────────┤ (no human; shown for audit only)
          awaiting_approval ─────────────────┤ officer (first tier): approve / edit_approve / reject
          with_fraud_team ───────────────────┘ fraud analyst (first tier): acknowledge / investigate / record outcome
                                             │
                                             └─ over a limit or sensitive ──► manager (admin): second-tier approval
```

## Roles

There are two frontline teams and a manager who oversees and second-tier-approves for both.

| Role | Sees | Can do |
|---|---|---|
| **Complaints officer** (first tier) | `awaiting_approval` queue | `approve`, `edit_approve`, or `reject` (the three API actions) — up to their refund approval limit. Anything above the limit is escalated to the manager instead. |
| **Fraud analyst** (first tier) | `with_fraud_team` queue | Acknowledge, record investigation / recall attempt, set an outcome. The customer gets the holding reply, not a resolution. Sensitive or high-value calls are escalated to the manager. |
| **Manager** (admin) | Both queues, the escalation queue, the audit log and metrics | Everything the two tiers can see, plus **second-tier approval for both**: clears escalated cases, reassigns, and oversees. The manager is the only one who sees both frontline queues. |

Keep auth simple: seeded users and a `role` column are enough. The point is that a fraud analyst sees only fraud cases and an officer sees only approval cases — not production-grade identity. Don't let sign-in eat your two days.

### Two-tier approval

The API models a single approval gate (`awaiting_approval` → `approved`/`rejected`). The platform extends it into two tiers. The core rule is that refunds over RM 500 need approval ([README.md](../README.md)); split that further:

- **First tier** — the officer (approval queue) or analyst (fraud queue) clears cases up to their `approval_limit_myr` (e.g. RM 5,000).
- **Second tier** — anything above the limit, or flagged sensitive, is escalated to the **manager (admin)**, who approves or rejects it. The same manager handles escalations from both queues.

A case stays `awaiting_approval` with `sent: false` until the tier that owns it approves — a first-tier action above the limit escalates rather than sends. Only the final approval flips it to `approved` / `sent: true`. Keep the agent's decision fields untouched throughout, exactly as the API requires.

## What the platform must do (MVP)

1. **Sign in and see your queue.** A signed-in user sees only the cases their role is responsible for, sorted by priority and SLA due time.
2. **Act on a case.** Approve / edit & approve / reject (officer) or acknowledge / investigate / record outcome (fraud) — the officer buttons call `POST /cases/{id}/actions`. Every reject or edit captures a one-line **reason**, as the API already requires.
3. **Re-run the self-check on edits.** On `edit_approve`, re-run the self-check (`starter/check_reply.py`) before anything sends. An edited reply that invents a transaction ID or amount is refused with `422` and nothing goes out — the API mandates this; the UI just surfaces it. See [README.md](../README.md) point 5 and [`api.md`](api.md#post-casescomplaint_idactions).
4. **Write the action back.** The action, actor, reason and time land in `human_action`; `case_state` and `sent` update per [`api.md`](api.md#case-states-human-in-the-loop). Nothing `awaiting_approval` or `with_fraud_team` reaches the outbox until a human has acted.
5. **Keep an audit trail.** An append-only log of who did what, when, and old value → new value — richer than the single `human_action` the API stores.

## Two interfaces, one platform (advice)

The fraud and approval teams do different jobs, so give them different screens rather than one generic case view. They share the same database, audit log and self-check — only the layout and the verbs differ.

**Complaints officer — a resolution desk.** The job is to get a correct reply to the customer quickly. Lead with the drafted `reply_text` (editable), the decision and refund amount, and an evidence panel to verify the matched transaction. Primary actions map to the API: **approve / edit & approve / reject**. Show the officer's remaining approval headroom, and when a refund exceeds the limit, replace "approve" with "escalate to manager." Cases here are short-lived — one decision and they close.

**Fraud analyst — an investigation workbench.** The customer only ever gets the holding reply, so do *not* centre this screen on reply prose. Lead with the suspicious transaction and its `auth_method` (3DS-OTP, chip & PIN, or none — the fact that decides unauthorised-card cases), related transactions on the account, and a **case timeline**. Primary actions: **acknowledge → log investigation / recall attempt → record outcome** (confirmed fraud / not fraud / recall succeeded / recall failed). These cases are long-lived and stateful, so status and history matter more than a single approve button.

**Manager — an oversight + escalation console.** One dashboard across both queues (throughput, SLA, override rate) plus a **second-tier approval queue** that merges escalations from both teams. Each escalation shows what the first tier already did and why it was escalated; the manager approves or rejects with a reason. This is the only screen that spans both case types.

Keep the shared mechanics identical everywhere: the self-check re-runs on any reply edit, every action is appended to the audit log, and the agent's original decision is never overwritten.

## Insights: a dashboard, a chat, or both

A bank runs on numbers, so give staff a way to see them. Build a metrics **dashboard**, a natural-language **chat** over the case data, or both. Everything here only reads — from the cases your agent wrote plus the source CSVs; it changes nothing and sends nothing.

Most of these come straight from the case records; a few join back to the data:

| Group | Examples |
|---|---|
| **Volume** | complaints over time; by `channel`, `category`, `priority`, `reply_language` |
| **Outcomes** | REFUND / DECLINE / INVESTIGATE / INFO_ONLY split; auto-resolve rate; route mix |
| **Money** | total and average refund paid; value awaiting approval; wrongful-refund near-misses |
| **Operations** | approval turnaround (`awaiting_approval` → `approved`); SLA adherence and breaches (`data/sla_policy.csv`); backlog by queue |
| **Guardrails** | self-check flag rate; **override rate** (`human_action` differs from the agent); rejection and escalation rates |
| **Fraud** | fraud volume, P1 count, recall attempts and their outcomes |
| **Customer** (source data) | complaint rate by `segment` or location; repeat complainers; most-disputed merchants |

**Dashboard.** Charts and tiles, filterable by date, category and channel — fast for the questions people ask every day. (If you build charts, keep them legible in light and dark.)

**AI chat.** Ask in plain English: *"how many duplicate-charge refunds today?"*, *"total paid out this week?"*. One hard rule, the same principle as the agent — **code does the numbers, the LLM does the language**: the chat must answer by running a query (SQL or a tool) over the data, never by guessing, and should show the query or figures it used so a judge can trust the answer. Keep it **read-only**: no approvals or edits through chat — actions stay on `POST /cases/{id}/actions` with their audit trail.

**Who sees what.** Either is fine for the bonus; a shared view for everyone is acceptable. Recommended, though, is to **scope insights to the role**, reusing the same boundary as the queues: an officer sees approval-queue stats, a fraud analyst sees fraud stats, and the manager sees everything plus cross-queue comparisons — the only full-picture view, as with the queues. Define one metric catalogue and filter it by role rather than building three pipelines; for the chat, scope the data it can query the same way.

## Integrity: the agent's decision vs the human's action

The API already draws this line, and the platform must keep it:

- **The agent's decision fields** (`category`, `matched_txn_id`, `outcome`, `refund_amount_myr`, `priority`, `reply_language`, `route`, `reply_text`) — immutable, exactly what the agent produced. They **never change after the agent decides, whatever a human does** ([`api.md`](api.md)). **This is what the leaderboard scores.**
- **`human_action`** — what staff actually did (action, actor, reason, time, the reply that went out) and, with your audit log, the full history.

The exported `submissions/<team-name>/predictions.csv` and the scorer are unchanged: they always reflect the **agent's autonomous output**, never the human-corrected version. This keeps the ground rule intact — your workflow produces the answers, no hand-labelling ([README.md](../README.md), Ground rules). The gap between the agent's decision and what staff did is not scored; it is one of the most interesting things you can show a judge.

## Suggested data model

Use any database and schema you like; this is a starting point. The `cases` table is the store behind `GET /cases/{id}`, so its columns mirror the API fields plus a few the platform adds.

| Table | Key columns |
|---|---|
| `cases` | `complaint_id`, agent fields (`category`, `matched_txn_id`, `outcome`, `refund_amount_myr`, `priority`, `reply_language`, `route`, `reply_text`), `self_check` (`passed`/`flagged`), `case_state` (API: `auto_resolved` / `awaiting_approval` / `with_fraud_team` / `approved` / `rejected`; platform adds `escalated`, `investigating`, `closed`), `sent`, `human_action` (JSON), `evidence` (JSON), `assigned_to`, `sla_due_at` |
| `case_events` | `complaint_id`, `actor`, `action`, `field`, `old_value`, `new_value`, `reason`, `created_at` — append-only |
| `users` | `username`, `role` (`officer` / `fraud` / `manager`), `approval_limit_myr` (manager has no limit) |

Keep the agent's decision fields immutable on `cases`; record every change as a row in `case_events`.

## Stretch ideas

- **SLA clocks.** `data/sla_policy.csv` has acknowledge/resolve targets by priority. Show each case's due time and flag overdue cases; sort queues by SLA + priority.
- **Deeper analytics.** On top of the insights above: trends over time, anomaly flags (a spike in one category or merchant), or a drill-down from any dashboard tile to the underlying cases.
- **Outbound log.** The API already has an outbox and a `sent` flag; record each sent message with its timestamp and who authorised it — the proof nothing reached the customer without approval.
- **Notifications.** Alert a role when a new case lands in its queue.

## How it's judged

The 25-point "Business ops platform" criterion in the final ranking, scored independently of your leaderboard/accuracy score:

- **Does the human gate actually hold?** Approval-needed cases wait; fraud cases land with the fraud team; escalations wait for the manager; nothing is sent without a human.
- **Role separation.** Officers, analysts and the manager each see only what they should, through interfaces fitted to their job.
- **Two-tier approval.** First tier clears within its limit; over-limit or sensitive cases escalate to the manager and wait.
- **Guardrail on edits.** The self-check re-runs on human-edited replies.
- **Auditability.** You can show who did what and why, and the agent-vs-human gap.
- **Insights.** Staff can see the numbers that matter, and any chat answers come from real queries over the data, not guesses.
- **Would a bank actually use it.** Clarity and realism of the workflow.

## What to show

In your demo, drive three cases end to end:

1. A `HUMAN_APPROVAL` case **within** the officer's limit — officer approves (or edits, triggering the self-check) and it sends.
2. A `HUMAN_APPROVAL` case **over** the limit — officer escalates, the manager second-tier-approves, then it sends.
3. A `FRAUD_TEAM` case — the analyst acknowledges and logs the investigation on the fraud workbench; the customer sees only the holding reply.

Show the audit log and the agent-vs-human record across them. The leaderboard submission (`predictions.csv`) is produced and scored exactly as in the core brief.
