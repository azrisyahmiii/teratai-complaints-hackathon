# Contracts (frozen after P4a)

> **Current ownership override:** [CURRENT-WORK.md](CURRENT-WORK.md) assigns exclusive files to
> Azri (workflow), Leon (insights) and Asyraf (integration/SLA). Its ownership and handoff rules
> supersede section 4 and the old joint-edit instructions for the remaining work. Preserve the
> organiser API and current generated schemas; historical shapes below are not instructions to revert them.

Owned by both devs. Change it (and `models.py`) only through a proposal in a report, then a joint commit on `main`
titled `contracts: …`, after which both devs merge `main`. Paths are real: the package is `backend/src/teratai/`
(SPEC §14 shows it without `src/`). Commands run from `backend/` or `web/` unless they say otherwise.

## 1. `models.py` (pydantic v2): stage data. Money is `Decimal`; JSON sends it as a string (`"46.66"`)
```python
Category = Literal["DUPLICATE_CHARGE", "FAILED_TRANSFER", "ATM_NOT_DISPENSED", "UNAUTHORISED_CARD",
                   "SCAM_TRANSFER", "FEE_DISPUTE", "SERVICE_QUALITY"]
Outcome = Literal["REFUND", "DECLINE", "INVESTIGATE", "INFO_ONLY"];  Priority = Literal["P1", "P2", "P3"]
Lang = Literal["EN", "MS"];  Route = Literal["AUTO_RESOLVE", "HUMAN_APPROVAL", "FRAUD_TEAM"];  Mode = Literal["live", "batch"]
Channel = Literal["App chat", "Email", "Call centre note", "Branch form", "Social media DM"]

class ComplaintRow:  complaint_id: str | None; customer_id: str; received_at: datetime; channel: Channel
                     subject: str = ""; text: str                                           # one complaints.csv row
class Issue:         category: Category; amount: Decimal | None; amount_approx: bool; counterparty: str | None
                     date_phrase: str | None; card_last4: str | None; fee_month: str | None; card_in_possession: bool | None
                     fee_type: Literal["monthly_service", "debit_annual", "cc_annual"] | None        # §4.2 schema
class Understanding: issues: list[Issue]; top3: list[tuple[Category, float]]; source: Literal["rules", "classifier", "llm"]
                     language: Lang; language_reason: str; is_complaint: bool; injection_suspected: bool; scam_cue: bool
class DateWindow:    start: date; end: date; exact_day: date | None; phrase: str | None                  # §4.3
class Candidate:     txn_id: str; score: int; breakdown: dict[str, int]                                   # §4.4 tie-break
class MatchResult:   status: Literal["UNIQUE", "NONE", "AMBIGUOUS", "WRONG_CUSTOMER", "NO_TXN"]; txn_id: str | None
                     window: DateWindow; candidates: list[Candidate]; related: dict[str, str]   # sibling/reversal/journal ids
                     source: Literal["matcher", "investigator"]
class Decision:      outcome: Outcome; refund_myr: Decimal; priority: Priority; route: Route; needs_info: bool
                     rule_id: str; rule_text: str; inputs: dict[str, str]; calc: str | None      # "1500.00 − 950.00 = 550.00"
class FactSheet:     customer_name: str; honorific: str; language: Lang; category: Category; outcome: Outcome
                     refund_myr: Decimal; ids: dict[str, str]; amounts: dict[str, Decimal]; dates: dict[str, date]; sla_days: int
class CheckIssue:    code: Literal["TXN_ID", "AMOUNT", "OUTCOME", "LANGUAGE", "HYGIENE", "PHONE_URL", "DATE"]
                     message: str; token: str | None        # e.g. "amount RM600.00 is not in this case's evidence"
class CheckResult:   ok: bool; issues: list[CheckIssue]
class Reply:         text: str; source: Literal["llm", "redraft", "template"]; check: CheckResult; drafts: list[str]
class StageEvent:    stage: str; ok: bool; latency_ms: int; model: str | None; tokens_in: int = 0; tokens_out: int = 0
                     cost_usd: Decimal = 0; tool_name: str | None = None; payload: dict[str, Any]         # one case_events row
class AgentDecision(frozen=True):   # immutable, §4.8. The predictions.csv row comes only from this
    complaint_id: str; run_id: str; customer_id: str; category: Category; category_conf: float
    matched_txn_id: str  # "" when none
    outcome: Outcome; refund_amount_myr: Decimal; priority: Priority; reply_language: Lang; route: Route
    reply_text: str; check_ok: bool; flags: list[str]
    understanding: Understanding; match: MatchResult; decision: Decision; facts: FactSheet; reply: Reply
    def to_csv_row(self) -> dict[str, str]: ...   # predictions.csv columns, refund formatted "46.66"
    # WRONG_CUSTOMER (§6): match.status says so, flags has "wrong_customer", reply_text ""; CSV row uses the §6 NEEDS_INFO defaults
Emit = Callable[[StageEvent], None]
```

## 2. Stage signatures (pure functions; P4a stubs return the CMP-00165 gold answer)
| Function (file, owner) | SPEC | Stub returns |
|---|---|---|
| `classify.understand(row, mode, emit) -> Understanding` (A) | §4.2 | DUPLICATE_CHARGE, conf 1.0, MS, amount 46.66, "hari Selasa lepas" |
| `dates.resolve_window(phrase, received_at) -> DateWindow` (A) | §4.3 | 2026-08-17 → 08-19, exact 08-18 |
| `match.match_case(row, u, window, emit) -> MatchResult` (A; calls `investigate` itself) | §4.4, 4.4b | UNIQUE, TXN-0115572 |
| `policy.decide(row, category, m) -> Decision` (A) | §4.5, §6 | REFUND 46.66, P2, AUTO_RESOLVE |
| `reply.build_facts(row, category, m, d) -> FactSheet` (A) | §4.6 | facts for TXN-0115572 |
| `reply.write_reply(facts, mode, emit) -> Reply` (A; draft → check → redraft → template) | §4.6–4.7 | fixed MS text, check ok |
| `check.check_reply(text, facts) -> CheckResult` (A; also used by `POST /reply`) | §4.7 | ok unless the text has an unknown RM/TXN |
| `pipeline.process_complaint(row, run_id, emit=None) -> AgentDecision` (B; no DB; `mode = "live" if run_id == "live" else "batch"`) | §3 | chains the stubs above |
| `pipeline.store(row, decision) -> int` (B; write-back, status, queue, assignment) | §4.8 | no-op, returns 0 |

`backend/tests/test_contracts.py` (joint): `process_complaint(CMP-00165).to_csv_row()` equals its `labels_train.csv` row
(all columns but `reply_text`). It must stay green on every branch, with the stubs and with the real code.

## 3. API shapes (`api/schemas.py`, owner B; endpoints and paths exactly as SPEC §11)
| Endpoint group | Request → response |
|---|---|
| `POST /api/complaints`, `/api/complaints/csv` | `ComplaintRow` JSON (complaint_id optional) or a raw CSV line → 202 `CaseCreated{case_id, complaint_id, existing}`; 422 `{detail}` naming the field |
| `GET /api/cases`, `/api/cases/{id}` | `list[CaseSummary{id, complaint_id, run_id, customer_id, category, priority, route, status, refund_amount_myr, reply_language, assigned_to, ack_due, resolve_due, flags}]`; `CaseDetail` = summary + `row, agent_decision, final_action, check_ok, check_issues, events: list[CaseEvent]` |
| `GET /api/cases/{id}/stream` | SSE (`fastapi.sse`, built in): event `stage` → `StageEvent`, event `done` → `CaseSummary` |
| `POST /api/cases/{id}/reply` | `{text}` → `ReplyCheckOut{check_ok, issues: list[CheckIssue], send_enabled}` |
| officer / fraud / manager actions | `ActionIn{reason_code: WRONG_TXN\|GOODWILL\|POLICY_EXCEPTION\|CUSTOMER_PROVIDED_INFO\|OTHER \| None, note}` → `CaseDetail`; 409 when the check fails or the refund is over the limit (§7.2) |
| customers, auth, metrics, clock, export | as §11; export streams `to_csv_row()` of the stored `agent_decision` |

**TS types are generated, never hand-written** (ctx7 `/openapi-ts/openapi-typescript`):
`cd backend && uv run python -m teratai.api.dump_openapi ../web/lib/api/openapi.json`, then `cd web && npm run gen:api`
(= `openapi-typescript lib/api/openapi.json -o lib/api/schema.d.ts`). The client is `openapi-fetch`'s
`createClient<paths>()` in `web/lib/api/client.ts`. Money is a `string` in TS: display it, never `parseFloat` it for maths.
The web calls `/api/*`, which a `next.config.ts` rewrite proxies to `API_URL` (default `http://localhost:8000`).

## 4. File ownership (per file, no overlap; root-relative globs; `T = backend/src/teratai`)
| Owner | Globs |
|---|---|
| Both (joint commit only) | `T/models.py`, `docs/dev/tasks/contracts.md`, `backend/tests/test_contracts.py`, `docs/dev/SPEC.md` |
| Core, Dev A | `T/{config,data,dates,classify,lang,extract,match,tools,investigate,policy,reply,check,batch}.py`, `T/templates/**`, `T/llm/**`, `backend/tests/core/**`, `submissions/**`, `docs/dev/tasks/core.md`, `web/app/fraud/**` (from CP2) |
| Platform, Dev B (integrator) | `T/{__init__,settings,pipeline,db,seed,export}.py`, `T/api/**`, `T/ops/**`, `backend/tests/{__init__.py,platform/**}`, `backend/pyproject.toml`, `backend/uv.lock`, `web/**` except `web/app/fraud/**`, `README.md`, `.gitignore`, `.claude/**`, `CLAUDE.md`, `docs/dev/tasks/{platform,HOWTO}.md` |
| BA | `eval/**`, `docs/dev/DEMO.md` |
| Nobody | `starter/**`, `scoring/**`, `data/**` |

Packages: only the integrator runs `uv add` or `npm i`. Builders name what they need in their report. Runtime files
go in `backend/var/` (gitignored): `teratai.sqlite` (env `TERATAI_DB`), `llm_cache.sqlite` (the §10 `llm_cache` table,
in its own file so `llm/` doesn't depend on `db.py`), and `classifier.joblib`. Thresholds: Core in `config.py`,
Platform in `settings.py`, each read from env with a default.

## 5. Upfront packages (added once in P4a)
Already present: `anthropic`, `fastapi[standard]` (includes `fastapi.sse` and `TestClient`), `scikit-learn` (+ `joblib`),
`python-dotenv`, `pytest`, `mypy`, `ruff`. Add: `uv add bcrypt pyjwt` (§7.1) and `npm i openapi-fetch`,
`npm i -D openapi-typescript`, and `npx shadcn@latest add button card badge table tabs textarea input label select
dialog tooltip separator scroll-area`. Cut: `openai` and `openai_provider.py`, `dateparser` (DEMO.md doesn't use them).

## 6. Ports and browser sessions (one laptop per dev; builders share it)
| Who | API | Web | `playwright-cli -s=` |
|---|---|---|---|
| Dev A lead / builders a1–a4 / reviewer | 8000 / 8021–8024 / 8029 | 3000 / 3021–3024 / 3029 | `a0` / `a1`–`a4` / `reviewer-a` |
| Dev B lead / builders b1–b4 / reviewer | 8000 / 8011–8014 / 8019 | 3000 / 3011–3014 / 3019 | `b0` / `b1`–`b4` / `reviewer-b` |

Start: `uv run fastapi dev src/teratai/api/main.py --port 8011` and `API_URL=http://localhost:8011 npm run dev -- -p 3011`.
A fresh worktree has no `.venv`, `node_modules` or `.env`, so first run `uv sync`, `npm ci` and copy `.env` from the main checkout.
Set `TEAM=<team slug>` in your shell; commands below use `$TEAM`.

## 7. Merge points (the integrator merges; see HOWTO)
**CP1** D1 16:00 · **stand-up** D2 09:00 · **CP2** D2 12:00 · **freeze** D2 13:30 · PR ≤ 14:30 (SPEC §15).
