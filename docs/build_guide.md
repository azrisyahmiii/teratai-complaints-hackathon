# Build guide

Use any stack you like. This guide gives a reference workflow that meets the rules, and the pitfalls we expect teams to hit.

## A reference workflow

```
new complaint ──► 1. UNDERSTAND (LLM) ──► 2. FIND THE TRANSACTION (code) ──► 3. DECIDE (code)
                                                                                   │
   case record ◄── 6. ROUTE (code) ◄── 5. CHECK (code) ◄── 4. DRAFT THE REPLY (LLM) ◄┘
        │
        ├── AUTO_RESOLVE   → reply sent, case closed
        ├── HUMAN_APPROVAL → approval queue: an officer approves or edits, then it is sent
        └── FRAUD_TEAM     → fraud queue, P1; holding reply to the customer
```

1. **Understand (LLM).** From the complaint text, extract structured fields: category, language, and the clues to the transaction (amount, exact or approximate; merchant or recipient name, full or partial; date phrase; card last 4; fee type and month). Return JSON and validate it.
2. **Find the transaction (code).** Turn the date phrase into a date range, using the `received_at` date ("yesterday", "hari Sabtu lepas", "last week"). Filter the customer's debits in the 45-day window by channel family, amount (with a tolerance for "about"), name (partial, case-insensitive), date and card. For duplicates, take the later of the two identical charges. If you are left with zero or several candidates, don't guess: flag the case and say so.
3. **Decide (code).** Apply `complaint_policy.csv` with the evidence: reversals, `status`, `auth_method`, the ATM journal, the fee schedule with the customer's age and the card's open date. Work out the refund to the sen. Set priority (base, plus one level for 65+) and the route.
4. **Draft the reply (LLM).** Give it the decision and the evidence pack, and ask for a short reply in `reply_language`. It must not change the decision or invent facts.
5. **Check (code).** Every transaction ID and RM amount in the reply must exist in the evidence (`starter/check_reply.py`). If the check fails, redraft once, then flag it for a human.
6. **Route and write back.** Store a case record (decision, matched transaction, evidence, reply, check result, route, due date from `sla_policy.csv`) and put it in the right queue.

Steps 2, 3 and 5 are deterministic: you can test them against `labels_train.csv` without calling an LLM. That's where most of the points are.

## The API

The live round reaches your agent through the API in [`api.md`](api.md). The simplest shape: accept the complaint, decide in the background, serve the case, and let a human act on cases waiting for approval. This FastAPI version is a working starting point; plug in your agent as `handle_complaint` and your reply check as `self_check` (see `starter/check_reply.py`). Point your own UI's Approve and Reject buttons at `POST /cases/{id}/actions` too:

```python
# app.py, run with: uvicorn app:app --host 0.0.0.0 --port 8000
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()
CASES: dict[str, dict] = {}            # use a database in your real build
POOL = ThreadPoolExecutor(max_workers=8)
STATE = {"AUTO_RESOLVE": ("auto_resolved", True), "HUMAN_APPROVAL": ("awaiting_approval", False),
         "FRAUD_TEAM": ("with_fraud_team", False)}


class Complaint(BaseModel):
    complaint_id: str
    customer_id: str
    received_at: str
    channel: str = ""
    subject: str = ""
    text: str                           # missing text: FastAPI answers 422 for you


class Action(BaseModel):
    action: Literal["approve", "reject", "edit_approve"]   # anything else: 422
    actor: str
    reason: str = ""
    reply_text: Optional[str] = None


def work(c: Complaint):
    try:
        decision = handle_complaint(c.model_dump())   # your agent: category, matched_txn_id, outcome, ..., reply_text, self_check
        state, sent = STATE[decision["route"]]
        CASES[c.complaint_id] = {"complaint_id": c.complaint_id, "status": "done", **decision,
                                 "case_state": state, "sent": sent, "human_action": None}
        # if sent: put decision["reply_text"] in your outbox
    except Exception as e:
        CASES[c.complaint_id] = {"complaint_id": c.complaint_id, "status": "error", "error": str(e)}


@app.post("/complaints", status_code=202)
def new_complaint(c: Complaint):
    if c.complaint_id in CASES:                    # the same complaint again: no second case
        return {"complaint_id": c.complaint_id, "status": CASES[c.complaint_id]["status"]}
    if not c.text.strip():
        raise HTTPException(422, "text is empty")
    CASES[c.complaint_id] = {"complaint_id": c.complaint_id, "status": "processing"}
    POOL.submit(work, c)
    return {"complaint_id": c.complaint_id, "status": "processing"}


@app.get("/cases/{complaint_id}")
def get_case(complaint_id: str):
    if complaint_id not in CASES:
        raise HTTPException(404, "unknown complaint")
    return CASES[complaint_id]


@app.post("/cases/{complaint_id}/actions")
def act(complaint_id: str, a: Action):
    case = CASES.get(complaint_id)
    if case is None:
        raise HTTPException(404, "unknown complaint")
    if case.get("case_state") != "awaiting_approval":
        raise HTTPException(409, f"case is {case.get('case_state')}, not awaiting_approval")
    if not a.actor.strip():
        raise HTTPException(422, "actor is required")
    reply = case["reply_text"]
    if a.action == "edit_approve":
        if not a.reply_text or self_check(complaint_id, a.reply_text):   # your self-check: returns the problems found
            raise HTTPException(422, "edited reply is missing or fails the self-check")
        reply = a.reply_text
    approved = a.action != "reject"
    case.update(case_state="approved" if approved else "rejected", sent=approved,   # the agent's fields stay as they were
                human_action={"action": a.action, "actor": a.actor, "reason": a.reason,
                              "at": datetime.now().isoformat(sep=" ", timespec="seconds"), "reply_text": reply})
    # if approved: put reply in your outbox
    return case


@app.get("/health")
def health():
    return {"ok": True}
```

Use the same `handle_complaint` for the 750 test complaints (read `complaints.csv` and call it for each `test_ids.csv` row), so the live round tests the system you scored. Then check the service:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
python scoring/api_check.py http://localhost:8000
```

## Where to use the LLM and where to use code

| Task | Use | Why |
|---|---|---|
| Reading messy English, Malay and mixed text | LLM | Language understanding |
| Turning "last Friday" into a date | Code (LLM can help extract the phrase) | Arithmetic on dates must be exact |
| Searching 156k transactions | Code | Exact, fast, cheap |
| Applying the refund rules | Code | Money must be right to the sen, and auditable |
| Writing the reply | LLM | Tone and language |
| Verifying the reply | Code | You can't use the model to check the model |

An agent that lets the LLM choose which tools to call (for example `find_transactions(customer, filters)`, `get_atm_journal(txn)`, `get_fee_schedule(product)`) is welcome. The decision rules and the self-check must still run in code.

## Pitfalls

- **Pasting the whole transactions table into a prompt.** It's slow and costly, and the model will still pick the wrong row. Give it the evidence pack for one customer, or tools.
- **Relative dates.** "Hari Selasa lepas" means the most recent Tuesday before the complaint arrived. "Last week" is fuzzy: search a range, then use the amount and name.
- **Approximate amounts.** "Lebih kurang RM1,400" can be RM1,383.20. Match with a tolerance, then confirm with the name or date.
- **Duplicates that aren't.** Two identical charges days apart are two purchases. Charges reversed already have been refunded.
- **Mixed language.** A reply to a mixed or call-centre complaint uses `preferred_language`, not your guess.
- **Age rules.** Vulnerable is 65+ on the received date. The debit fee waiver is 60+ on the charge date. These are different dates.
- **Running out of time.** 750 complaints × several LLM calls takes a while. Run them in parallel and cache results. The test complaints are available from Day 1.
- **Secrets.** Keep API keys in environment variables, never in the repo. This repo is public.
