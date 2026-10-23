# Upstream brief changes (origin/main 89332b5): impact and re-plan

For Dev A, Dev B and the BA. Read it before the stand-up. The organisers changed the brief after our SPEC was written
(10 commits since 552f8ec). New files: `docs/api.md`, `scoring/api_check.py`, `examples/live_complaint_example.*`. Changed:
`README.md`, `docs/scoring.md`, `docs/build_guide.md`. Nothing in `data/` changed. Our code is not merged with these
changes yet: the stand-up step `git merge origin/main` into each feature branch brings in the new files, and no file
we own conflicts.

## 1. What changed

| # | Change | Where | Before (our SPEC/DEMO) |
|---|---|---|---|
| 1 | **The live round goes through a fixed HTTP API.** `POST /complaints`, `GET /cases/{complaint_id}`, `POST /cases/{complaint_id}/actions` and `GET /health`, with exact field names and status codes | `docs/api.md` | We designed our own `/api/...` paths, an int `case_id`, CSV paste intake, and judges typing rows into our UI |
| 2 | **Live round = 25%, split into a hidden test (15) and a human gate (10).** Right after the 15:00 freeze, a script sends **20 unseen, messily written complaints** (typos, SMS short forms, emoji, mixed EN/MS) all at once. Each must be `done` within 120 s, and they are scored like the leaderboard × 0.15. | README, `scoring.md` | 2–3 rows typed in during the demo, scored by judges as "agent design" |
| 3 | **Human gate (10):** in the demo, judges send 3 complaints one at a time through the API and tick a checklist. The case appears on its own; right txn, decision and refund; right route; approval holds; fraud lands in the fraud queue; reply language and consistency; self-check visible. A waiting case must show `case_state: awaiting_approval` and `sent: false` via the API. | README, `scoring.md` | DEMO §1–§2 paste flow |
| 4 | **Case state and human action in the API.** `case_state` ∈ {`auto_resolved`, `awaiting_approval`, `with_fraud_team`, `approved`, `rejected`}, plus `sent`, `self_check` (`passed`/`flagged`) and `human_action`. Actions are `approve` / `reject` / `edit_approve` with `actor` and `reason`. An edited reply that fails the self-check → `422`, nothing sent. Not awaiting → `409`. The agent's decision fields never change. | `api.md` | Our `agent_decision` (immutable) + `final_action`, `/approve`, `/reject` endpoints: same idea, different shape |
| 5 | **Robustness probes, which feed the engineering score:**<br>- `/health` → 200<br>- unknown case → 404<br>- missing text → 4xx<br>- unknown customer → no 5xx<br>- same complaint twice → no change, no duplicate<br>- timing per complaint | `api_check.py` | Partly in SPEC §4.1 |
| 6 | **`reply_text` must never be empty.** `api_check.py` flags an empty reply as a contract problem. The organisers also auto-check **all** replies in `predictions.csv`: empty, wrong language, IDs or amounts not in evidence, and a refund reply must state the amount. | `api_check.py`, `scoring.md` | SPEC §6: WRONG_CUSTOMER gets **no** reply (`""`) |
| 7 | **Schedule.**<br>- **CP2 (12:00):** adds `api_check.py` passing against our API, and the organisers reaching it from their laptop.<br>- **15:00:** agent + API freeze. The PR carries predictions, the **freeze commit hash** and the **API URL**, and the API must stay up until our demo ends.<br>- **15:00–16:30:** UI and ops platform work continues.<br>- **16:30:** demos (~10 min). | README | Freeze 13:30, PR ≤14:30, demos 15:15 |
| 8 | **Bonus ops platform:** can be built until 16:30 | README | After CP2, before 15:00 |

## 2. Where we stand (measured)
- **Leaderboard path:** done. Train 100.00, 0 critical (OOF). Safety-net test predictions are pushed (`submissions/teratai-dm/predictions.csv`, 750 rows, no empty replies).
- **Messy text (the new 15 points):** measured by two independent reviewers on 109 messy rewrites of gold complaints, in live mode.
  - Score ≈ **85.6**, so about 12.8 / 15. Plausible range at n = 20 is 76–93.
  - **0 criticals.** Category and priority were 109 / 109.
  - The losses are almost all lost txns:
    - `k`, spaced and word amounts
    - approximation short forms (`abt`, `lebih krg`)
    - the LLM counterparty vetoing correct matches
    - unparsed SMS dates
    - SMS-Malay language detection
  - The 100.00 train score is template recall: 19.5% of test texts are identical to a train text after masking, and the honest group-K-fold classifier accuracy is ≈ 90–99%.
  - Details, evidence and the fix plan are in **[robustness review](2026-10-23-robustness.md)**.
- **API:** not built. `api/main.py` is still the P4a stub (`/api/...` paths, `case_id=0`, no store). This is Dev B's, and it is now a CP2 gate.

## 3. Strategy: re-plan now, don't finish the old plan first
Most of the plan stands: the pipeline, the policy, the self-check, replies, the safety net, C13 and the bonus platform.
What changed is **what is scored and when**, so re-order instead of rebuilding:

1. **The API is the live round (Dev B, CP2 gate).** Implement `docs/api.md` exactly, on top of `process_complaint` + `store`. Without it the hidden test scores 0 (15% of the total) and the human gate can't run. The SPEC §11 `/api/...` routes stay for our own UI. The organiser routes are added alongside, or the UI moves to them.
2. **Messy-text robustness (Dev A, the new top Core task).** It is worth up to 15 points. Train accuracy is saturated, and this is where the points are now.
3. **Keep:** C13 final run, the safety net, and C16 / the bonus platform, which now has until 16:30.
4. **Change:** the WRONG_CUSTOMER reply (§4 below). Contract alignment is folded into [contract-proposals.md](../tasks/contract-proposals.md).
5. **Cut first if behind:** C14, C15, then smart routing (unchanged order). Never cut the API contract or messy-text robustness.

## 4. Task changes

### Core (Dev A): added to [core.md](../tasks/core.md), the source of truth
- **C17:** an honest messy eval harness (the 109-row dev set, a blind BA-reviewed hold-out, live mode, bootstrap interval).
- **C18:** LLM reads, code verifies, code decides ([robustness review](2026-10-23-robustness.md) §0). Messy-dev ≥ 92 with 0 criticals, and train stays at 100.00.
- **C19:** a non-empty wrong-customer reply, held for approval.
- **C13:** must finish before 14:30, because the 15:00 PR needs the freeze commit hash.

### Platform (Dev B)
| Task | Done check |
|---|---|
| **P-API: organiser API per `docs/api.md`.** `POST /complaints` (202, background job, idempotent by `complaint_id`, 4xx on missing fields or unknown customer). `GET /cases/{complaint_id}` (`processing` / `done` / `error` and every required field: decision from the immutable `agent_decision`, `self_check` from `check_ok`, `case_state` and `sent` from route and actions, `human_action`). `POST /cases/{complaint_id}/actions` (approve / reject / edit_approve; `edit_approve` re-runs `check.check_reply` and returns 422 on failure; 409 when not awaiting; 404 when unknown). `GET /health` → 200. Concurrency: 20 at once. | `python scoring/api_check.py http://localhost:8000 --n 30`: every probe PASSes, `case_state and sent match the route: 30/30`, median < 15 s |
| **P-REACH: reachability.** Bind `--host 0.0.0.0`. Prepare a tunnel (ngrok or Cloudflare) as the fallback. Keep it up from 15:00 to the end of the demo, with the laptop on power and sleep off. | The organisers reach it at CP2 |
| **UI** reads cases that arrive via the API on its own (polling or SSE), and its Approve / Reject buttons call `POST /cases/{id}/actions`, so the demo and the hidden test use the same path. | A judge's POST shows up in the right queue without a click |
| `case_state` mapping: `with_fraud_team` for FRAUD_TEAM (holding reply allowed, `sent` either way). Our extra internal states (`escalated`, `needs_info`, `investigating`) must map onto the five API states. | Unit test per route and action |

### BA
- Review the C17 messy set: realistic Malaysian SMS style, and correct `reply_language` labels.
- **Rewrite DEMO.md §1–§2.** Judges POST to our API, so the paste-CSV flow becomes the backup. Show the case arriving on its own, the approval holding (`awaiting_approval`, `sent: false` via `curl`), and the fraud queue.
- Rehearse with `python scoring/api_check.py` and a second laptop on the venue Wi-Fi.

## 5. SPEC and DEMO sections now stale
- **SPEC §4.1 intake:** the judged path is a JSON `POST /complaints` with a required `complaint_id`. CSV paste stays as a UI convenience only.
- **SPEC §6 "Wrong customer":** the reply is non-empty and held for approval (C19).
- **SPEC §11 API:** add the organiser routes and fields. Keep ours for the UI, or migrate the UI to them.
- **SPEC §15 timeline and §16 MoSCoW:** freeze 15:00, demos 16:30. The API contract and messy robustness become **Must, never cut**.
- **DEMO.md §0–§2, §5:** the live round goes through the API. The fallback for a judge's POST failing is to show `curl` against `/cases/{id}`. The bonus platform is shown inside the ~10 min slot.

## 6. Questions for the organisers (GitHub issue)
1. Does the hidden test's `reply_language` label follow the same rule (complaint language; mixed or staff note → preferred language)?
2. Do hidden complaints use `complaint_id`s that could collide with training IDs (we key idempotency on `complaint_id`)?
3. Is a WRONG_CUSTOMER-style complaint possible in the hidden 20? If so, what label do they expect: category plus empty txn?
