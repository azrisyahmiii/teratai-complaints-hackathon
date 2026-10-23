# Platform tasks (Dev B, integrator, branch `feat/platform`)

> **Reassigned:** [CURRENT-WORK.md](CURRENT-WORK.md) is the current allocation. Azri owns logs,
> fraud workflow and escalation; Leon owns insights; Asyraf owns integration/SLA and shared wiring.
> The rows below remain a requirements backlog, not authority to edit another person's files.

Owns the live round: intake → async pipeline → write-back → queues → UI, plus all merges. B is the sole owner of the
`web/` structure, layout, shared components and generated API types. File globs are in [contracts.md §4](contracts.md).
Read SPEC §3, §4.1, §4.8, §7–§11, §13 and DEMO.md before starting.

## How to build (every task inherits this)
- **Isolation:** one module per concern; `pipeline.py` only orchestrates the Core stage functions ([contracts §2](contracts.md))
  and never holds rules. I/O happens only in `db.py`, `api/` and `data.py`. Thresholds and limits (workers, SIM_NOW, SLA
  colours, capacity) live in `settings.py` with env overrides, so a demo tweak is one line.
- **Easy to modify:** small typed files, no cleverness. A new queue, status or role means a dict or table entry
  (queue → route/status filter, role → queues), not edits across many files. After changing `api/schemas.py`, regenerate
  the TS types (contracts §3) and commit `web/lib/api/*`. Never hand-write API types. Builders never edit `api/main.py`
  (P1 makes it include every `api/routes_*.py` automatically) or `web/lib/nav.ts` / the layout (the lead adds nav entries at merge).
- **Verify APIs:** typings (`web/node_modules/**/*.d.ts`, `backend/.venv/Lib/site-packages`) → ctx7 → a probe you run.
  Next 16 differs from training data, so read `web/node_modules/next/dist/docs/` for the feature you touch. FastAPI
  SSE: `.venv/Lib/site-packages/fastapi/sse.py`. For other open questions (UX patterns, holiday list, unfamiliar
  errors), web search ≤3 queries and cite the URL.
- **Tests at seams**, with regressions taken from real IDs: LIVE-07 (README row), CMP-00165, CMP-00244, CMP-00387,
  CMP-00289. Money stays `Decimal` server-side and a string in TS; the LLM never decides outcome, refund, route or priority.
- **Scope:** build only what DEMO.md touches and note anything else as cut. After two failed attempts, stop, narrow the
  task and report. The lead commits before spawning worktree builders; a builder commits its task on its worktree branch.
- **Report:** files changed, what is cut, any contract requests, then one `Verified:` line per check (UI = a screenshot
  you opened, at your contracts §6 port and `-s` name).

`B` = `cd backend &&`, `W` = `cd web &&`. `T` = `backend/src/teratai`. Waves run in order; tasks in one wave share no
files (max 3 parallel builders). Web checks always include `W npm run typecheck && npm run lint && npm run build`.

| ID | Task | Files | Out of scope | Depends | Done check (command → expected) | MoSCoW |
|---|---|---|---|---|---|---|
| P1 · W1 | **Walking skeleton:** the LIVE-07 row → `POST /api/complaints/csv` (Python `csv` parsing, validation, idempotency) → stub `process_complaint` → `store` → queue list → case page. `db.py` creates every §10 table and CRUD helper up front | `T/{settings,db,pipeline}.py`, `T/api/{main,schemas,routes_complaints,routes_cases,dump_openapi}.py`, `backend/tests/platform/test_intake.py`, `web/next.config.ts`, `web/lib/api/**`, `web/app/{layout,page}.tsx`, `web/app/{intake,queues,cases}/**` (minimal) | SSE, styling, auth | P4a | `B uv run pytest tests/platform/test_intake.py -q` → LIVE-07 parsed; quoted text with a comma + newline parsed; `CUS-99999` → 422 naming `customer_id`; a resubmit returns the same `case_id`. `curl -s -X POST --data-binary @eval/live07.csv localhost:8000/api/complaints/csv` → `202 {"case_id":…}`. `shots/p1-skeleton.png` shows LIVE-07 in the queue and its case page | Must |
| P2 · W1 | SLA (§4.5 SLA, §2 business days): `ack_due`, `resolve_due`, SLA state (ok / amber 75% / breached) against SIM_NOW; hard-coded 2026 KL holidays from an official source (cite the URL) | `T/ops/{sla,holidays_2026}.py`, `backend/tests/platform/test_sla.py` | per-state calendars | P4a | `B uv run pytest tests/platform/test_sla.py -q` → CMP-00387 (P1, 2026-09-23 21:55) ack_due 23:55 the same day; resolve_due skips weekends and holidays | Must |
| P3 · W1 | Baseline least-loaded assignment (§9 baseline), pure `assign(case, users) -> (username, reason)` | `T/ops/routing.py`, `backend/tests/platform/test_routing.py` | smart routing (P17) | P4a | `B uv run pytest tests/platform/test_routing.py -q` → FRAUD_TEAM → least-loaded online fraud user; offline users skipped; P1 first; reason string present | Should (bonus; DEMO §1 shows the assignee) |
| P4 · W2 | Async worker pool (N from settings) + per-stage `StageEvent` → `case_events` + SSE broadcast; POST returns 202 at once; the `useCaseStream` hook | `T/api/{worker,sse}.py`, `T/pipeline.py`, `web/lib/stream.ts`, `backend/tests/platform/test_stream.py` | — | P1 | `curl -N localhost:8000/api/cases/1/stream` → `event: stage` for understand, resolve, match, decide, draft, check, write-back, then `event: done`; POST answers in < 200 ms | Must |
| P5 · W2 | Queues (§8: tabs per queue, sorted by priority then SLA, badges, countdown, flags) + case trace page: live stage view ("stages light up", via P4's hook) and §13 items 1–6 (timeline, understanding, evidence with the match highlighted, decision card, reply with green/red tokens, tool-call panel) | `web/app/{queues,cases}/**`, `web/components/{queue,case}/**` | audit/agent-vs-human (P16) | P1 (poll until P4 lands) | web checks clean; `shots/p5-queue.png` and `shots/p5-case.png` (CMP-00165: TXN-0115572 highlighted, rule text, RM46.66, MS reply) inspected | Must |
| P6 · W2 | Intake UI (§4.1): **Paste CSV row** tab (default, parsed preview, 422 shown) + **Form** tab (customer picker, channel select, SIM_NOW default) + `GET /api/customers` | `web/app/intake/**`, `web/components/intake/**`, `T/api/routes_customers.py`, `backend/tests/platform/test_customers.py` | customer identification | P1 | `shots/p6-paste.png`: the CMP-00165 row → preview fields → Submit → case page; `shots/p6-422.png`: a bad customer shows the readable message; `B uv run pytest tests/platform/test_customers.py -q` passes | Must |
| P7 · W3 | Write-back (§4.8): status machine; AUTO_RESOLVE → outbox + closed; FRAUD_TEAM → holding reply to outbox + investigating; HUMAN_APPROVAL / NEEDS_INFO wait; WRONG_CUSTOMER → no reply + alert; live cases assigned, eval runs not | `T/pipeline.py`, `backend/tests/platform/test_writeback.py` | — | P2, P3, P4 | `B uv run pytest tests/platform/test_writeback.py -q` → fixtures shaped like CMP-00165 / 00244 / 00387 / 00289 land in closed+outbox / pending / investigating+outbox / pending; `run_id=dev` is never assigned | Must |
| P8 · W3 | Core human gate: `POST /reply` re-runs `check.check_reply`; approve / reject / send-back with reasons (§7.2); Send disabled while the check fails; a single `officer` actor until P13 | `T/api/routes_actions.py`, `backend/tests/platform/test_actions.py`, `web/components/case/{reply-editor,actions}.tsx` | escalation (P14) | P5 | pytest: CMP-00244 reply edited to RM600.00 → `check_ok false, send_enabled false`; approve while failing → 409; approve → outbox row; `shots/p8-flagged.png` shows the red token and Approve disabled | Must |
| P9 · W3 | Export from `agent_decision` only: `GET /api/export/predictions` + `python -m teratai.export --run …` | `T/export.py`, `T/api/routes_export.py`, `backend/tests/platform/test_export.py` | — | P1 | pytest: after a human edit, export still equals `to_csv_row()`; `curl -s "localhost:8000/api/export/predictions?run_id=dev" \| head -2` → the predictions.csv header + one row | Must |
| P10 · W4 | **CP2 run** (integration): merge `feat/core`, 50 train rows with `--persist`, check the queues | none (merge only) | — | P7–P9, Core C8 | `B uv run python -m teratai.batch --ids ../eval/cp2_ids.csv --run cp2 --persist` → 50 stored; `/api/cases?run_id=cp2` counts per route match the labels | Must |
| P11 · W4 | Seed + cached demo: `python -m teratai.seed --demo` (5 users per §7.1, all `online`, ~30 cases from BA's seed spec, SIM_NOW); record the 4 scripted rows live once so `DEMO_MODE=cached` replays them | `T/seed.py`, `backend/tests/platform/test_seed.py` | — | P7, BA seed spec | `B uv run python -m teratai.seed --demo` → `5 users, 30 cases`; with `DEMO_MODE=cached`, pasting CMP-00165 reaches `done` in < 3 s with cache hits in the events | Must |
| P12 · W4 | Metrics (§12, DEMO 3:50): cost per complaint, p50/p95 per stage, self-check first-pass / redraft / template % | `T/api/routes_metrics.py`, `web/app/metrics/**` | charts polish | P4 | `curl -s "localhost:8000/api/metrics?run_id=cp2"` → those fields; `shots/p12-metrics.png` inspected | Should |
| P13 · W5 | Auth (§7.1): bcrypt users, JWT httpOnly cookie, `require_role`, `GET /api/me`, `POST /api/users/{id}/status` (DEMO §0 "users online"), login page, route guard (Next 16 docs) | `T/api/{auth,routes_auth}.py`, `web/app/login/**`, `web/proxy.ts`, `backend/tests/platform/test_auth.py` | SSO, sign-up | CP2 | pytest: a bad password → 401; an officer calling a manager endpoint → 403; `shots/p13-login.png` | Should (bonus) |
| P14 · W5 | Two-tier escalation + manager console (§7.2, DEMO §4) | `T/api/routes_manager.py`, `web/app/manager/**`, `backend/tests/platform/test_escalation.py` | — | P8, P13 | pytest: aina approves CMP-00289 (RM4,687.10) → `escalated`, outbox empty; manager approves with a reason → outbox `authorised_by=manager`; flagged-sensitive cases escalate | Should (bonus) |
| P15 · W5 | Fraud endpoints `/ack`, `/investigation`, `/outcome` for Dev A's workbench (C16) | `T/api/routes_fraud.py`, `backend/tests/platform/test_fraud.py` | the screen (Core C16) | P8 | pytest: ack sets `acknowledged_at`; an outcome appends a `case_events` row with the reason | Should (bonus) |
| P16 · W6 | Resolution desk (§7.2) + audit timeline + agent-vs-human diff (§13 item 7) | `web/app/desk/**`, `web/components/case/audit*.tsx` | — | P14 | `shots/p16-audit.png`: agent decision → aina escalate → manager approve, with the diff highlighted | Should (bonus) |
| P17 · W6 | Smart routing (§9 stretch), fast-forward clock, alerts panel; first to cut | `T/ops/routing.py`, `T/api/routes_admin.py`, `web/components/alerts/**` | — | P14 | `B uv run pytest tests/platform/test_routing.py -q -k smart`; fast-forward 1h → `at_risk` flag + alert visible | Could |
| P18 · freeze | README section: built during the event vs tools used, AI disclosure, screenshots | `README.md` | — | freeze | `grep -n "AI disclosure" README.md` → the section exists | Must |

**Cut order** (§16): P17 → P12 polish → P16 → P13–P15 (fall back to the core-only gate, §7.2). Never cut P1, P6, P8 or P9.
`eval/live07.csv` and `eval/cp2_ids.csv` come from the BA (HOWTO). Until they arrive, write the LIVE-07 row to `$TEMP` and use it.
