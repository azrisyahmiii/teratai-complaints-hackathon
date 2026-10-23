# Core → Platform handoff (read this first on `feat/core`)

For Dev B (integrator). It covers what `feat/core` contains, how to merge it, what Platform must build next, and how
to check it. Status: Core C1–C12 and C17–C19 are done. C13 (the final run) waits on your P8. C16 (the fraud screen)
waits on your P15. The organisers changed the brief, and the live round now goes through a fixed API:
read [brief-changes review](../reviews/2026-10-23-brief-changes.md) first (10 min).

## 1. Your order of work
1. **Merge** (§2): `main` (contracts + the organisers' upstream) → `feat/core`, then your `feat/platform`.
2. **Organiser API, exactly as `docs/api.md`** (on `main` from upstream): `POST /complaints`, `GET /cases/{complaint_id}`,
   `POST /cases/{complaint_id}/actions`, `GET /health`. This is a **CP2 gate**: `scoring/api_check.py` must pass, and the
   organisers must reach it from their laptop. Without it the hidden test (15 pts) and the human gate (10 pts) score 0.
   The field mapping is in [contract-proposals.md](contract-proposals.md) ("API alignment").
3. **Pipeline changes** (`pipeline.py`, yours): carry the flags, pass `is_complaint`, and reuse
   `Understanding.language`. See §4.
4. **Joint `contracts:` commit:** `FactSheet.state`, `Reply.flags`, and the §2/§3/§4 text edits in
   [contract-proposals.md](contract-proposals.md). After it lands, Core spends about 10 minutes switching over.
5. **Reachability:** bind `--host 0.0.0.0`, keep a tunnel ready as the fallback, and keep it up from 15:00 to the end of our demo.
6. **UI:** cases POSTed by a judge appear on their own (polling or SSE), and the Approve and Reject buttons call
   `POST /cases/{id}/actions`.
7. **P8** (`--persist` + export) so Core can run C13 before 14:30. The 15:00 PR needs the freeze commit hash and the API URL.

## 2. Merge `feat/core`
```bash
git switch main && git pull                      # has 552f8ec contracts + upstream 89332b5 (docs/api.md, scoring/api_check.py)
git merge --no-ff origin/feat/core               # no conflicts expected: Core touched only its globs (contracts §4)
cd backend && uv sync && uv run pytest -q && uv run mypy src && uv run ruff check
```
Expected: about 2,425 passed and 1 skipped, offline (no network even with a key in `.env`; see §6). Files outside
Core's globs that Core changed:
- `backend/tests/conftest.py`, an autouse fixture setting `REPLY_MODE=template` and `EXTRACT_MODE=regex` so tests never
  call the LLM. Please make it **Both**-owned in contracts §4.
- New `docs/dev/reviews/`, `docs/dev/tasks/contract-proposals.md`, and this file.

## 3. What Core gives you (stable seams, contracts §2)
| Call | Use it for |
|---|---|
| `pipeline.process_complaint(row, run_id, emit)` → `AgentDecision` | Your job worker. `run_id="live"` = live mode (LLM extract, investigator, Sonnet reply). About 2–6 s per case, about $0.003. |
| `AgentDecision.to_csv_row()` | The decision fields of `GET /cases/{id}` and the predictions export. Never from human edits. |
| `check.check_reply(text, facts)` → `CheckResult` | `edit_approve` and `POST /cases/{id}/reply`: on failure, return **422** and send nothing (api.md). `facts` = `agent_decision.facts`. |
| `check.token_verdicts(text, facts)` | Green and red token highlighting in the reply editor (SPEC §13.5). |
| `StageEvent`s via `emit` | The case timeline (`case_events`): stage, model, tokens, cost, latency, `tool_name`. Payloads carry `degraded`, `check_flagged`, `not_complaint`, `category_disagreement`, and match `reason`. |
| `tools.tool_specs()`, `tools.handlers(customer_id)` | Only if you build a tool panel. Handlers are **scoped to the case customer**. Prefer reading the logged events. |
| `python -m teratai.batch --ids … --run … --out … [--persist] [--dist] [--replies llm\|template]` | The 750 run. `--persist` calls `pipeline.store(row, decision)` per row, including resumed rows, so **`store` must be idempotent by `complaint_id`**. |
| `python -m teratai.evaluate --set messy_dev --mode live` | The messy-text score (108 rows). The blind hold-out needs `--i-am-scoring-the-holdout`; don't tune against it. |

### Decisions your API and `store()` must reflect
- Route → state, before any action: `AUTO_RESOLVE` → `auto_resolved` and sent. `HUMAN_APPROVAL` → `awaiting_approval`, `sent: false`.
  `FRAUD_TEAM` → `with_fraud_team` (holding reply allowed).
- **WRONG_CUSTOMER:** a non-empty verification reply that names no txn, amount or payee, from a template with no LLM call.
  The route is **FRAUD_TEAM** for SCAM_TRANSFER/UNAUTHORISED_CARD (this avoids a missed-fraud critical), otherwise
  **HUMAN_APPROVAL**. Never auto-send it, and raise the manager alert.
- **NEEDS_INFO** (no unique match): refund 0, txn `""`, INVESTIGATE + FRAUD_TEAM for fraud categories, else DECLINE + HUMAN_APPROVAL.
- **Unknown `customer_id`:** return 4xx at intake. `process_complaint` raises `KeyError` on an unknown customer, so validate first with `data.has_customer`.
- **Same `complaint_id` twice:** return the existing case and never re-run.
- `reply_text` is **never empty**: an empty reply now fails `check_reply`.
- `self_check` = `"passed"` if `agent_decision.check_ok`, else `"flagged"`.

## 4. `pipeline.py` changes (yours)
```python
facts = reply.build_facts(row, issue.category, m, d, u.is_complaint,  # optional args already exist
                          [i.category for i in u.issues[1:]])          # C20: other problems -> noted in the reply
flags = sorted({*events_flags,                    # until Reply.flags lands: read the final stage="reply" payload
                *(["multi_issue"] if len(u.issues) > 1 else []),  # C20: show it; an officer answers the other issue
                *(["injection_suspected"] if u.injection_suspected else []),
                *(["check_flagged"] if not r.check.ok else []),
                *(["wrong_customer"] if m.status == "WRONG_CUSTOMER" else []),
                *(["needs_info"] if d.needs_info else []),
                *(["vulnerable"] if d.inputs.get("vulnerable_bump") == "yes" else [])})
```
Use `u.language` for `reply_language` instead of recomputing it. Core memoises `lang.reply_language` meanwhile.

C20 additions (one line each):
- **API startup:** call `classify.warm()` in the FastAPI lifespan. The loaders are now thread-safe either way (20 cold
  concurrent complaints: 59.5 s → 3.7 s), so this only moves the ~2 s load out of the first request.
- **`multi_issue`:** the reply already tells the customer "we have also noted your question about a fee … we will reply
  separately", so the flag must reach a person, even on AUTO_RESOLVE (a queue badge or a manager alert).
- **Card and IC numbers:** Core masks them before any LLM call (`extract.mask_sensitive`). Use the same helper if you
  store or display the complaint text.
Full flag table: [contract-proposals.md](contract-proposals.md) §1.

## 5. Check it
```bash
cd backend && uv run fastapi dev src/teratai/api/main.py          # or: uvicorn … --host 0.0.0.0 --port 8000
python ../scoring/api_check.py http://localhost:8000 --n 30       # all probes PASS; "case_state and sent match the route: 30/30"
python ../scoring/api_check.py http://localhost:8000 --complaints tests/core/fixtures/messy_dev.csv \
       --labels tests/core/fixtures/messy_dev_labels.csv --all  # the messy dev set through your API (≈ 99 expected)
```
Core's current numbers, for comparison:

| Run | Score | Criticals |
|---|---|---|
| Train, LLM mode | 100.00 | 0 |
| Train, regex mode | 100.00 | 0 |
| Messy dev (live) | 99.03 | 0 |
| Blind hold-out (live) | 98.27 | 0 |

Latency is about 1.5 s per extract and about 2 s per Sonnet reply.

## 6. Gotchas
- **`.env`** (repo root, gitignored) holds `ANTHROPIC_API_KEY`. Copy it into any worktree. Never commit it.
- **Port 8000** on Dev A's laptop was taken by an unrelated Docker container (`phoenix-backend`). Check with
  `Get-NetTCPConnection -LocalPort 8000` if `/health` answers something odd.
- **Runtime files** live in `backend/var/` (gitignored): `llm_cache.sqlite` (identical prompts replay for free),
  `classifier.joblib` (retrains in about 5 s if missing), `batch/<run>.jsonl` checkpoints (a code or mode change refuses to resume
  without `--fresh`).
- **Env switches** (in `config.py` and `llm/settings.py`):
  - `DEMO_MODE=cached` replays only, and is the Wi-Fi fallback.
  - `EXTRACT_MODE=llm|regex`.
  - `REPLY_MODE=llm|template`.
  - `INVESTIGATOR=off`.
  - `LLM_TIMEOUT_S` (10), `LLM_BREAKER_SECONDS` (60): after an outage the first case is slow, later ones fall back in under 0.1 s.
- **Builder worktrees** created by the Agent tool can start from `origin/main` instead of your branch. Check
  `git log feat/x..worktree-branch` before merging, and cherry-pick the task commit if the base is wrong.
- **Contacts in replies:** only the verified allow-list (`check.py`: NSRC 997, FMOS, BNMLINK 1-300-88-5465). Any other
  phone number or URL fails the check.

Questions about Core: ask Dev A. The design and why: [robustness review](../reviews/2026-10-23-robustness.md) §0,
[SPEC](../SPEC.md).
