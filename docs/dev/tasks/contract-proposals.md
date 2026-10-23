# Contract proposal: case flags, fact-sheet state, wrong-customer reply

From Dev A (Core), for the stand-up integration. Status: **proposed**. Nothing here is committed. Per
[contracts.md](contracts.md) §1, it lands as one joint `contracts: …` commit on `main`, then both devs merge `main`.

## Why
`feat/core` (b6fb0fc) fits the current contract: every §2 signature matches, `tests/test_contracts.py` passes, and
`models.py`, `pipeline.py`, `api/` and `web/` are unchanged. Three gaps remain, and fixing them crosses the boundary:

| # | Gap | Effect today | SPEC |
|---|---|---|---|
| 1 | `Reply` has no flags. `degraded`, `check_flagged` and `not_complaint` exist only in the final `stage="reply"` event payload. The pipeline builds `check_flagged` from `not r.check.ok`, which is never true after a template fallback (the template always passes). | Queue badges and the officer's "check failed / degraded" signals never show; sampling of non-complaints is impossible | §4.7, §6, §8 |
| 2 | `FactSheet` has no state. Core carries it as `ids["state"]` ∈ {`decided`, `needs_info`, `wrong_customer`, `not_complaint`}. | Works, but it is a hidden convention inside an id dict; the UI and `POST /reply` can't read it cleanly | §4.6, §6 |
| 3 | The pipeline doesn't pass `u.is_complaint` to `build_facts`. A WRONG_CUSTOMER case gets an empty reply and keeps the policy route. | Compliments and gibberish rely on Core's rules-only re-check (the LLM's verdict is lost). **The updated brief rejects empty replies** (`api_check.py` contract problem, and auto-checks on `predictions.csv`). A wrong-customer case must not be auto-sent. | §6 rows "Wrong customer", "Gibberish / not a complaint"; [brief-changes review](../reviews/2026-10-23-brief-changes.md) #6 |
| 4 | API shapes (contracts §3) differ from the organisers' fixed API in `docs/api.md` (paths, `complaint_id` keys, `status` / `self_check` / `case_state` / `sent` / `human_action`) | The hidden test (15 pts) and the human gate (10 pts) can't reach us | [brief-changes review](../reviews/2026-10-23-brief-changes.md) #1, #4 |

> **Revised after the upstream brief change (origin/main 89332b5):** a WRONG_CUSTOMER case now gets a short,
> non-empty verification reply that names no txn, amount or payee, and is routed HUMAN_APPROVAL so it waits
> (`sent: false`). This replaces "no reply" (SPEC §6). Core builds it as C19. §2 and §5 below reflect this.

## 1. `models.py` (joint)
Both new fields have defaults, so existing callers and stored JSON keep validating.

```python
CaseState = Literal["decided", "needs_info", "wrong_customer", "not_complaint"]

class FactSheet(BaseModel):
    ...                                   # existing fields unchanged
    state: CaseState = "decided"          # replaces ids["state"]

class Reply(BaseModel):
    ...                                   # existing fields unchanged
    flags: list[str] = []                 # subset of {"degraded", "check_flagged", "not_complaint"}
```

Flag meanings, one vocabulary for `AgentDecision.flags` and the §8 queue badges:

| Flag | Set by | Meaning |
|---|---|---|
| `degraded` | Core `reply` / `classify` / `investigate` | An LLM call failed, timed out, hit an open circuit breaker, or missed the cache in `DEMO_MODE=cached`; the code path decided |
| `check_flagged` | Core `reply` | The LLM draft failed the self-check twice, so the template was sent; a human should review |
| `not_complaint` | Core `reply` | Compliment or gibberish: INFO_ONLY, sampled for review |
| `injection_suspected` | Platform `pipeline` (from `Understanding`) | Already set today; unchanged |
| `wrong_customer` | Platform `pipeline` (from `MatchResult.status`) | Verification reply held for approval (never auto-sent), manager alert (§6, revised) |
| `needs_info` | Platform `pipeline` (from `Decision.needs_info`) | NEEDS_INFO queue (§8) |
| `vulnerable` | Platform `pipeline` (from `Decision.inputs["vulnerable_bump"] == "yes"`) | 65+ priority bump badge (§8, DEMO §2) |

## 2. `pipeline.py` (Dev B)
```python
facts = reply.build_facts(row, issue.category, m, d, u.is_complaint)   # pass the LLM/rules verdict
r = reply.write_reply(facts, mode, emit)
wrong_customer = m.status == "WRONG_CUSTOMER"
flags = sorted({
    *r.flags,
    *(["injection_suspected"] if u.injection_suspected else []),
    *(["check_flagged"] if not r.check.ok else []),
    *(["wrong_customer"] if wrong_customer else []),
    *(["needs_info"] if d.needs_info else []),
    *(["vulnerable"] if d.inputs.get("vulnerable_bump") == "yes" else []),
})
...
reply_text=r.text,   # never empty (upstream brief); for wrong_customer it is Core's verification reply (C19)
```
Core's `policy.decide` routes WRONG_CUSTOMER to HUMAN_APPROVAL (C19), so `store()` holds it in `awaiting_approval`
with `sent: false`, keeps it out of the outbox until approved, and raises the manager alert (§6).

### API alignment with `docs/api.md` (Dev B, joint text in contracts §3)
`GET /cases/{complaint_id}` is built from the stored case. The mapping:

| API field | Source |
|---|---|
| `category`, `matched_txn_id`, `outcome`, `refund_amount_myr`, `priority`, `reply_language`, `route`, `reply_text` | `AgentDecision.to_csv_row()` (immutable, never changed by a human) |
| `status` | `processing` while the job runs, `done` once `agent_decision` is stored, `error` (plus an `error` field) if the pipeline raised |
| `self_check` | `"passed"` if `AgentDecision.check_ok`, else `"flagged"` |
| `case_state`, `sent` | From `route` before any action (`AUTO_RESOLVE` → `auto_resolved`/true, `HUMAN_APPROVAL` → `awaiting_approval`/false, `FRAUD_TEAM` → `with_fraud_team`/holding reply). After an action: `approved`/true or `rejected`/false. Internal states (`escalated`, `needs_info`, `investigating`) map onto these five |
| `human_action` | `final_action`: `{action, actor, reason, at, reply_text}`, `null` until a human acts |

`POST /cases/{complaint_id}/actions` runs `check.check_reply(reply_text, agent_decision.facts)` on `edit_approve` and
returns 422 if it fails. The SPEC §7 two-tier escalation stays a bonus-platform layer on top: an over-limit approve by
tier 1 stays `awaiting_approval` until the manager acts.

## 3. `contracts.md` text edits (joint)
- §1 `FactSheet`: add `state: CaseState = "decided"`. `Reply`: add `flags: list[str] = []`. Add the `CaseState` literal.
- §1 `AgentDecision` comment: the flags vocabulary is the table above.
- §2 table: `reply.build_facts(row, category, m, d, is_complaint=None) -> FactSheet`.
- §2 note: the tool registry is scoped to the case customer, `tools.handlers(customer_id)` and
  `tools.call_tool(name, args, customer_id)`. Only Core's investigator calls it; a Platform tool-call panel reads the
  logged `StageEvent`s instead of calling tools.
- §4 ownership: add `backend/tests/conftest.py` to **Both**. It is an autouse fixture that sets `REPLY_MODE=template`
  so the suite (including `test_contracts.py`) never calls Sonnet when `.env` has a key.

## 4. Core follow-up after the joint commit (Dev A, about 10 min)
- `reply.build_facts`: set `FactSheet.state` and stop writing `ids["state"]`. `templates.state_of` reads
  `facts.state`. The wrong-customer reply becomes a non-empty verification template (C19), so `check.check_reply`
  no longer needs the empty-reply exception.
- `reply.write_reply`: return `Reply.flags` (`degraded`, `check_flagged`, `not_complaint`). Keep the event payload too,
  for the trace.
- Re-record `tests/core/fixtures/reply_llm_cache.json` if the fact-sheet layout in the prompt changes (about $0.02).

## 5. Tests to add
- `tests/test_contracts.py` (joint): a WRONG_CUSTOMER row (e.g. CUS-00013, "unauthorised RM39.90 StreamMax on my Visa
  ending 9999") gives a non-empty reply that names no txn or amount, route HUMAN_APPROVAL, and `"wrong_customer" in flags`. A compliment ("Thanks, your staff were very
  helpful today!") gives INFO_ONLY and `"not_complaint" in flags`.
- `tests/core/test_reply.py` (Core): a draft that fails twice gives `Reply.flags == ["check_flagged"]`. `CacheMiss`
  gives `["degraded"]`.
- `tests/platform/` (Dev B): `store()` holds a wrong-customer case in `awaiting_approval` (`sent: false`) and raises
  a manager alert. `python scoring/api_check.py http://localhost:8000 --n 30` passes every probe.

## Open question for the stand-up
Should the 65+ `vulnerable` flag come from `Decision.inputs["vulnerable_bump"]` (as above, no model change), or should
`Decision` get an explicit field? We propose `inputs`, so §1 doesn't grow.
