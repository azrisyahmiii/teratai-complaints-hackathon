# Leon: insights (metrics API + role-scoped dashboard)

**Platform integration:** merged into `feat/platform`. The platform app registers `/api/metrics`; Insights is in the sidebar, `/metrics` uses the session redirect, and generated API types include the metrics contract. Tests use the production app without registering their own router. Escalation and fraud workflow measurements remain unavailable pending adaptation to the operations events. The remaining sections record the original branch implementation and handoff.

Branch `feat/platform-leon` (from `origin/feat/platform` `a4f0b9b`). Allocation: [CURRENT-WORK.md](CURRENT-WORK.md).
Requirement: the "Insights" section of [bonus_platform.md](../../bonus_platform.md) (dashboard only; no AI chat, no chart
library). Read-only: this feature changes nothing and sends nothing.

**Done means** (CURRENT-WORK): role-scoped backlog, outcomes, refund totals, approval turnaround, latency/cost and
guardrail figures, all computed from stored `cases` / `case_events`; date, category and channel filters work; officer and
fraud users cannot infer the other team's figures; the manager sees both plus a team comparison; a missing measurement
is `null` + a reason, never an invented `0`.

## 0. Ground rules for every agent on this task

- **Do not disturb the judged instance.** It runs from `../teratai-prod` on port 8000 (`fastapi run`, no reload).
  Never use port 8000, never touch `../teratai-prod` or its database, never kill a process you did not start.
  Ports for this task: API **8010**, web **3010**. Point `TERATAI_DB` at a scratch file under `$TEMP`, never at
  `backend/var/teratai.sqlite`.
- **Offline only.** Set `REPLY_MODE=template EXTRACT_MODE=regex INVESTIGATOR=off` for any server you start (no paid LLM calls).
  The test fixtures already do this.
- **Owned files only** (CURRENT-WORK). Anything else is read-only; if you need it changed, say so in your report.

| Agent | Owns |
|---|---|
| Lead (Leon's session) | this file; `backend/src/teratai/api/routes_metrics.py` **models block** (the contract, §2); `backend/src/teratai/ops/__init__.py` (empty; tell Asyraf, he owns `ops/`) |
| **API builder** | `backend/src/teratai/ops/metrics.py`; `backend/src/teratai/api/routes_metrics.py` below the models block; `backend/tests/platform/test_metrics.py` |
| **UI builder** (sole owner of all UI) | `web/app/metrics/**`; `web/components/metrics/**` |

Not ours (request from the owner, never edit): `api/main.py`, `api/auth.py`, `db.py`, `pipeline.py`, `routes_ui.py`,
`web/lib/api/*` (generated), `web/components/desk/sidebar.tsx`, `web/app/globals.css`, `package.json`/locks, `conftest.py`.

- Money: `Decimal` server-side, serialized as a 2-dp string (`routes_agent.money`). TS never `parseFloat`s money for
  maths; bar widths use counts only.
- Verify APIs before use (typings → ctx7 → probe). Next 16: read `web/node_modules/next/dist/docs/` for what you touch.
- Checks: backend `cd backend && uv run pytest tests/platform -q && uv run ruff check && uv run mypy src/teratai/api/routes_metrics.py src/teratai/ops`
  (full `mypy src` has pre-existing NumPy errors in `classify.py`, see AUTH.md; not ours). Web
  `cd web && npm run typecheck && npm run lint` (no `npm run build` in this checkout while anything serves from it).
- Do not commit; the lead commits. Report ≤200 words ending with `Verified:` lines.

## 1. Data available today (read this before writing a query)

- Role boundary: `auth.case_scope(user)` → `(sql, params)` for case alias **`c`**. Officer = route `HUMAN_APPROVAL` or
  `AUTO_RESOLVE`; fraud = `FRAUD_TEAM`; manager = all; plus a user's own still-pending submissions. `auth.require_run(user, run_id)`:
  only the manager may read non-`live` runs. Every query (cases **and** events, via `JOIN cases c`) must apply both.
- `cases`: `row` (ComplaintRow JSON: `received_at`, `channel`, `customer_id`), `status` (`processing|done|error`),
  `agent_decision` (AgentDecision JSON, immutable: `category`, `outcome`, `refund_amount_myr`, `priority`, `route`,
  `reply_language`, `check_ok`, `flags`, `matched_txn_id`, `reply.source` = `llm|redraft|template`), `case_state`
  (`auto_resolved|awaiting_approval|with_fraud_team|approved|rejected`), `sent`, `human_action`
  (`{action: approve|reject|edit_approve, actor, reason, at, reply_text}`), `created_at` (wall clock).
- `case_events`: `actor='agent'` rows carry `stage`, `latency_ms`, `model`, `tokens_in/out`, `cost_usd` (Decimal string).
  **Only live cases have them** (written by `worker.run_job`); `batch --persist` stores cases without events.
  Human actions add rows with `actor=<username>`, `action=<api action>`.
- Reuse, don't duplicate: `routes_ui._row` / `_ack_due` semantics (ack due = `received_at + sla_policy[priority].ack_hours`,
  compared with `settings.sim_now()`); `data.txn(id)` for the disputed amount; `routes_agent.money`. Import them; if an
  import is awkward, copy nothing and ask.
- Not available yet (return `null` + reason in `unavailable`): fraud ack / investigation / recall / outcome and escalation
  (Azri's events, §5); SLA **resolve** adherence (Asyraf's business-day helper, §5); acknowledgement time (needs `acknowledged_at`).

## 2. Contract: `GET /api/metrics` (frozen once the lead commits the models)

Query: `run_id=live`, `date_from`, `date_to` (ISO dates, inclusive, on the complaint's `received_at` date),
`category`, `channel` (exact enum values). Auth: `auth.User` (401 without a session); `require_run` (403).
Filters apply to everything except `options`.

```python
class MetricBucket(BaseModel):        # one row of a breakdown, sorted by count desc (by_day: by key asc)
    key: str                    # raw enum / ISO date; UI maps to labels
    count: int
    amount_myr: str | None = None

class MetricRate(BaseModel):
    numerator: int
    denominator: int
    pct: float | None           # None when denominator == 0 (never 0.0 for "no data"); one decimal

class MetricDuration(BaseModel):
    count: int
    p50_minutes: float | None
    p95_minutes: float | None

class MetricFilters(BaseModel):
    date_from: date | None; date_to: date | None; category: str | None; channel: str | None

class MetricOptions(BaseModel):       # from the role's scoped rows, ignoring filters; feeds the filter dropdowns
    categories: list[str]; channels: list[str]; date_min: date | None; date_max: date | None

class MetricVolume(BaseModel):
    total: int; processing: int; errors: int
    by_day: list[MetricBucket]; by_channel: list[MetricBucket]; by_category: list[MetricBucket]
    by_priority: list[MetricBucket]; by_language: list[MetricBucket]

class MetricOutcomes(BaseModel):
    by_outcome: list[MetricBucket]    # amount_myr = refund total for that outcome
    by_route: list[MetricBucket]
    auto_resolve_rate: MetricRate     # AUTO_RESOLVE routes / decided cases

class MetricMoney(BaseModel):  # officer + manager only
    refunds_paid_myr: str       # outcome REFUND and sent (auto_resolved or approved)
    refunds_paid_count: int
    avg_refund_myr: str | None  # None when count == 0
    awaiting_approval_myr: str  # refunds on awaiting_approval cases
    awaiting_approval_count: int
    refunds_by_category: list[MetricBucket]

class MetricOperations(BaseModel):
    backlog: list[MetricBucket]       # one bucket per effective state; each case counted exactly once (see effective_state)
    ack_overdue: int            # open (awaiting/with fraud) and ack_due < sim_now
    ack_due_2h: int             # open and sim_now <= ack_due <= sim_now + 2h
    turnaround: MetricDuration        # human_action.at - created_at, over human-actioned cases
    human_actions: int

class MetricGuardrails(BaseModel):
    self_check_flagged: MetricRate    # not agent check_ok / decided
    reply_source: list[MetricBucket]  # llm (first pass) / redraft / template
    overrides: MetricRate             # human_action in (edit_approve, reject) / human-actioned
    rejections: MetricRate            # reject / human-actioned
    escalations: MetricRate | None    # None until §5 (Azri)
    injection_suspected: int; degraded: int; needs_info: int; vulnerable: int

class MetricFraud(BaseModel):  # fraud + manager only
    total: int; open: int; p1_open: int; ack_overdue: int
    amount_disputed_myr: str    # sum of matched txn amounts on open fraud cases
    by_category: list[MetricBucket]
    acknowledged: int | None; recall_attempts: int | None; outcomes: list[MetricBucket] | None   # None until §5

class MetricStage(BaseModel):
    stage: str; count: int; p50_ms: int | None; p95_ms: int | None
    cost_usd: str; tokens_in: int; tokens_out: int

class MetricPerformance(BaseModel):
    cases_measured: int         # scoped, filtered cases that have agent events
    latency_p50_ms: int | None; latency_p95_ms: int | None    # per complaint (see §3)
    cost_total_usd: str | None; cost_per_complaint_usd: str | None   # 4 dp; None when cases_measured == 0
    llm_calls: int              # agent events with a model
    stages: list[MetricStage]

class MetricTeam(BaseModel):       # manager only
    team: Literal["approval", "fraud", "auto"]   # route HUMAN_APPROVAL / FRAUD_TEAM / AUTO_RESOLVE
    cases: int; open: int; p1_open: int; ack_overdue: int
    refund_total_myr: str; flagged: int

class MetricsOut(BaseModel):
    role: Literal["manager", "officer", "fraud"]
    run_id: str
    sim_now: datetime
    filters: MetricFilters
    options: MetricOptions
    volume: MetricVolume
    outcomes: MetricOutcomes
    money: MetricMoney | None          # None for fraud
    operations: MetricOperations
    guardrails: MetricGuardrails
    fraud: MetricFraud | None          # None for officer
    performance: MetricPerformance
    teams: list[MetricTeam] | None         # manager only
    unavailable: dict[str, str]         # dotted field path -> reason, e.g. "fraud.acknowledged": "awaiting fraud workflow events"
```

Rules: a section a role may not see is `None` and **never computed** (no leakage through `options`, `stages` or
totals). Empty breakdowns are `[]`. A percentile or average over zero items is `None`, with an `unavailable` entry
when the reason isn't obvious (e.g. `"performance": "no agent events recorded for this run (batch runs store none)"`).

## 3. API builder

1. `ops/metrics.py`, pure (no DB, no FastAPI): `compute(role, cases: list[CaseRecord], events: list[EventRecord],
   sim_now, filters) -> MetricsOut`, where `CaseRecord`/`EventRecord` are small dataclasses parsed from rows.
   One function `effective_state(case) -> str` (`processing`, `error`, or `case_state`) used for every backlog/open
   count, so Azri's escalation state is a one-line change and never double-counts. One table `ROLE_SECTIONS`
   (role → which optional sections) decides visibility. Percentiles: nearest-rank over sorted values.
   Per-complaint latency = sum of `latency_ms` over that case's agent events in the **top-level stages**; read
   `pipeline.py`, `classify.py`, `match.py`, `reply.py` to list which `emit` stages are top level vs nested
   (tool calls, drafts), write the set as a constant with a comment, and report it.
2. `api/routes_metrics.py`: `router = APIRouter(prefix="/api")`, `GET /metrics`. Two queries:
   `SELECT c.* FROM cases c WHERE c.run_id=? AND (<scope>)` and
   `SELECT e.* FROM case_events e JOIN cases c ON c.run_id=e.run_id AND c.complaint_id=e.complaint_id WHERE c.run_id=? AND (<scope>)`.
   Filtering by date/category/channel in Python is fine (≤ 1,750 rows). Validate `category`/`channel` against the
   known enums (422 otherwise); `date_from > date_to` → 422.
3. `tests/platform/test_metrics.py`. `main.py` is Asyraf's, so the test registers the router only if missing:
   `if not any(getattr(r, "path", "") == "/api/metrics" for r in app.routes): app.include_router(routes_metrics.router)`.
   Reuse `conftest.client/complaint/wait_done` and the `login` / `HEADERS` pattern from `test_auth.py` (users
   `asyraf` manager, `leon` officer, `azri` fraud, password `000000`). Load CMP-00244, CMP-00165, CMP-00387, CMP-00289. Assert:
   - no session → 401; officer/fraud with `run_id=evaltest` → 403, manager → 200.
   - **officer**: `volume.total == 3`, `fraud is None`, `teams is None`, no `FRAUD_TEAM` in `by_route`, no
     `UNAUTHORISED_CARD` in `options.categories`, `performance.cases_measured == 3`.
   - **fraud**: `volume.total == 1`, `money is None`, `teams is None`, `fraud.open == 1`, only `FRAUD_TEAM` in `by_route`.
   - **manager**: `volume.total == 4`, team `cases` sum to 4, all sections present.
   - money (DEMO values; if the offline pipeline disagrees, report it, don't edit the expectation): `refunds_paid_myr == "46.66"`
     (CMP-00165 auto), `awaiting_approval_myr == "5237.10"` (550.00 + 4687.10). Leon approves CMP-00244 via
     `POST /api/cases/CMP-00244/actions` → `refunds_paid_myr == "596.66"`, `awaiting_approval_myr == "4687.10"`,
     `operations.turnaround.count == 1`, `guardrails.overrides.denominator == 1`, backlog still sums to `total`.
   - filters: `category=ATM_NOT_DISPENSED` → manager total 1; a `date_from` after every case → total 0,
     `avg_refund_myr is None`, `auto_resolve_rate.pct is None`; bad category → 422.
   - no events: `pipeline.store` a decision under `run_id="evaltest"` (no events) → manager sees `cases_measured == 0`,
     latency/cost `None`, `"performance"` key in `unavailable`.
   - read-only: row counts of `cases`, `case_events`, `outbox` identical before/after several GETs.
   - every `*_myr` field matches `^\d+\.\d{2}$`.

Verified lines: the pytest command for `test_metrics.py` + `tests/platform`, ruff, the scoped mypy, and one curl against
the 8010 server (§4) for each of the three users (paste `volume.total` and which sections are null).

## 4. Running locally (lead and builders)

`main.py` doesn't include our router yet, so use an uncommitted launcher outside the repo:

```bash
mkdir -p "$TEMP/leon" && cat > "$TEMP/leon/metrics_app.py" <<'EOF'
from teratai.api.main import app
from teratai.api import routes_metrics
if not any(getattr(r, "path", "") == "/api/metrics" for r in app.routes):
    app.include_router(routes_metrics.router)
EOF
cd backend && TERATAI_DB="$TEMP/leon/metrics.sqlite" REPLY_MODE=template EXTRACT_MODE=regex INVESTIGATOR=off \
  PYTHONPATH="$TEMP/leon" uv run uvicorn metrics_app:app --port 8010    # background; stop it when done
```
Seed: `POST localhost:8010/complaints` with the four demo rows (see `conftest.complaint`). Web:
`cd web && API_URL=http://localhost:8010 npx next dev -p 3010`. Types for the UI: the lead regenerates locally with the
launcher app (from `backend/`: `PYTHONPATH="$TEMP/leon" uv run python -c "import json,metrics_app; print(json.dumps(metrics_app.app.openapi()))" > ../web/lib/api/openapi.json`,
then `cd ../web && npm run gen:api`). Those generated files are Asyraf's: commit them only if he agrees (§5), otherwise `git restore web/lib/api`.

## 5. UI builder (single owner of every UI file)

Start after the lead has committed the models and regenerated types (§4). Use `Schemas["MetricsOut"]` etc. from
`@/lib/api/client`; never hand-write API types. Read `docs/dev/DESIGN.md` (tokens, §3 status words, §4 formats) and
`web/components/desk/queues.tsx` (figure row, polling, table idiom) first; invoke the `dataviz` skill before drawing bars.

- `web/app/metrics/page.tsx`: `PageHeader title="Insights"`, description by role ("Approval team", "Fraud team",
  "All teams"), renders `<MetricsDashboard />`.
- `web/components/metrics/`: `metrics-dashboard.tsx` (client; `api.GET("/api/metrics", {params:{query}})`, poll every 5 s,
  keep filters in the URL search params so a view can be shared), `filter-bar.tsx` (date from/to inputs, category and
  channel `Select` from `options`, Reset), `figure-row.tsx` (compact figures like Queues: backlog open, ack overdue,
  refunds paid / awaiting (officer, manager), fraud open + P1 + disputed (fraud, manager), self-check flagged, cost per
  complaint), `breakdown-table.tsx` (label | count | share bar (CSS width from count / max) | amount), `stage-table.tsx`
  (stage, count, p50, p95, cost, tokens), `team-table.tsx` (manager only), `unavailable.tsx` (`—` with a `Tooltip` showing
  the reason from `unavailable`).
- Section order. Officer: figures, outcomes, money, operations, guardrails, volume, performance. Fraud: figures, fraud,
  operations, guardrails, volume, performance. Manager: figures, team comparison, then all sections.
  A `None` section is not rendered at all.
- Formats: `formatMoney`, `<Money>`, `categoryLabel` / `outcomeLabel` / `routeLabel` / `flagLabel`, `StatusBadge` for
  states; percentages one decimal; minutes as `1 h 05 min`; ms as `1.2 s`. Raw enums never shown. Tables over tiles;
  right-aligned tabular numbers; no new dependencies; styles as Tailwind classes in our components (no `globals.css`).
- States: loading skeleton, API error banner, empty (`total == 0`: "No complaints match these filters").
- Navigation is Asyraf's: the page works at `/metrics`; the nav entry is requested in the handoff.

Verified lines: `npm run typecheck` and `npm run lint` output; screenshots against 8010/3010 (`playwright-cli -s=leon-ui`,
redirect output to a file) that you opened and inspected: `shots/leon-metrics-manager.png`, `-officer.png`, `-fraud.png`
at 1440 px and `-officer-390.png`; one with a category filter applied; confirm the officer view shows no fraud figures.

## 6. Handoffs (lead)

- **Asyraf:** `app.include_router(routes_metrics.router)` in `main.py`; sidebar entry `{ href: "/metrics", label: "Insights",
  icon: BarChart3 }` for all roles; regenerate `web/lib/api/*` (or agree that this branch commits them in a separate
  `integration:` commit); confirm `T/ops/__init__.py`; publish the business-day resolve-due helper signature.
- **Azri:** final event `action` names and payload keys for escalate, manager approve/reject, fraud ack, investigation/recall
  log and fraud outcome, and how escalation shows on the case (`case_state` value or new column). Until then those metrics
  are `None` + reason. Switching over touches only `ops/metrics.py` (`effective_state`, one `WORKFLOW_EVENTS` table) and tests.
- Handoff note: commit, files, endpoint contract, checks run, deferred items.

## 7. Order and cut line

1. Lead: commit this file + the models block (contract) + `ops/__init__.py`; regenerate types locally. (~15 min)
2. In parallel: API builder (§3), UI builder (§5) against the contract.
3. Lead: run 8010/3010 with the four demo cases, log in as all three users, `reviewer` agent pass against this file.
4. Commit; handoff to Asyraf; adapt to Azri's events when they land.

**Cut first:** p95 columns → by_day → stage table (keep the cost/latency totals) → team comparison polish.
**Never cut:** role scoping and its tests, `null`-not-zero, the read-only guarantee, Decimal money.
**Could (only if time remains):** a customer section (repeat complainers, most-disputed merchants from matched txns);
clicking a breakdown row to open `/queues` filtered.
