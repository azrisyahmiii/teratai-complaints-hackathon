# SPEC: Teratai Bank Complaints Agent

Two-day hackathon build by a team of 3 (2 devs + 1 BA/tester). This spec records the decisions from the design interview on 2026-10-22. It was revised after a judge review and after the brief was updated (commit `e3973a4`: live-round format, fork + PR submission; commit `6bc5537`: [bonus ops platform](../bonus_platform.md)). Where it says **[ASK ORGANISERS]**, open a GitHub issue on the organisers' repo, where every team sees the answer.

---

## 1. What wins (and what this spec optimises for)

| Weight | Criterion | What drives it | Our lever |
|---|---|---|---|
| 30% | Leaderboard (750 test) | `matched_txn_id` gates 75 of 100 pts; critical errors cost 2× | Deterministic matcher + policy engine, tested offline against 1,750 labels |
| 25% | Agent design + guardrails (live round) | Reacts on its own, routes correctly, approvals wait, self-check catches bad replies | API/UI intake → async pipeline, queues, decision-bound self-check, approval and fraud queues; (bonus) two-tier approval |
| 25% | Business value + demo | Reply quality in EN/MS, no invented facts, would a bank use it | LLM replies grounded in a fact sheet + BNM-style content, template fallback, officer UX |
| 20% | Engineering | Architecture, "why did it decide", cost and speed per complaint | Event trace per case, tool-call log, tokens/cost/latency per stage, metrics page |

**Design principle (from the brief, and non-negotiable):** the LLM does language, and code does money and rules. The LLM never sets `outcome`, `refund_amount_myr`, `route` or `priority`.

**Data facts we measured (training labels, amount-only regex match against the customer's 45-day debits):**
- FAILED_TRANSFER, UNAUTHORISED_CARD, SCAM_TRANSFER, ATM: the gold transaction is the **only** amount match in ~95–97% of cases. The rest need name, date or card tie-breaks.
- DUPLICATE_CHARGE: almost always 2+ amount matches, by design. Take the later of the identical pair.
- FEE_DISPUTE: 73 of 270 have no RM amount, so match by fee type + month.
- ~20 cases where the gold transaction falls outside naive tolerance or window. These are the matcher's regression tests.
- UNAUTHORISED_CARD gold transactions use only `None` (125, all REFUND), `3DS-OTP` (115) and `Chip+PIN` (44), both INVESTIGATE. SCAM_TRANSFER gold transactions are only DuitNow (176) or IBG (37).
- Every refund of exactly RM500.00 is AUTO_RESOLVE, and every refund above it is HUMAN_APPROVAL. The largest training refund is RM4,687.10.
- Labels have one row per complaint, and no multi-issue complaints are visible.
- Complaints were received 2026-07-01 → 2026-09-29. Transactions run 2026-04-01 → 2026-09-30. Live-round complaints are received **30 Sep 2026**.

Target: **≥ 90 final score on training (out-of-fold)**, **0 critical errors** on training.

---

## 2. Decisions log (from the interview)

| Topic | Decision |
|---|---|
| Stack | Python 3.11 + FastAPI backend; Next.js (App Router) + shadcn/ui frontend; SQLite |
| LLM | Provider-agnostic interface. Default: **Claude Haiku 5.5** (`claude-haiku-5-5`) for extraction and the investigator; **Claude Sonnet 5.5** (`claude-sonnet-5-5`) for customer replies. Switch via env |
| Agent shape | **Hybrid**: a fixed, code-orchestrated pipeline calling a tool registry. A bounded tool-calling LLM "investigator" runs only when the deterministic matcher is not confident |
| Classifier | **Tiered**: rules (safety cues) → TF-IDF char n-gram + logistic regression → LLM when confidence is low or tiers disagree → evidence consistency check |
| Ambiguity | **Never guess.** A match must be unique after hard filters and tie-break scoring with a clear margin; otherwise NEEDS_INFO |
| Risk lean | When uncertain: prefer INVESTIGATE / no refund (never a wrongful refund or missed fraud) |
| Batch vs live | **Same pipeline**, batch mode. Eval runs are isolated (`run_id`), never assigned to officers. LLM use in batch is minimised (see §12). `predictions.csv` is exported from the DB's immutable `agent_decision`, never from human-edited values |
| Intake | **API + UI form only.** Accepts exactly a `complaints.csv` row (`complaint_id, customer_id, received_at, channel, subject, text`, e.g. `LIVE-07`), typed field by field or pasted as one CSV line. `customer_id` must exist in `data/customers.csv` (no customer identification). `received_at` is always taken from the input; the form default is `SIM_NOW=2026-09-30 12:00` |
| Self-check | **Decision-bound** (stricter than the starter): only facts from this case's evidence may appear in the reply |
| Replies | LLM with a structured fact sheet + regulatory snippets → self-check → one redraft → deterministic template fallback. **Sonnet for all replies, including the 750 test replies** (judges read 10 of them) |
| Multi-issue | **Could-have.** Split into sub-cases under one parent case. The leaderboard row uses the most severe issue. No multi-issue complaints are visible in the data |
| No match / wrong customer | NEEDS_INFO queue (route HUMAN_APPROVAL) + ops alert. Wrong customer: no decision, no customer-facing reply; stakeholder alerted |
| Storage | SQLite: `cases` (immutable `agent_decision` + mutable `final_action`), `case_events` (append-only trace + audit), `users`, `alerts`, `outbox` |
| Ops platform | **Bonus award ("Best Ops Platform"), built only after the core works and Checkpoint 2 passes.** Follows [docs/bonus_platform.md](../bonus_platform.md): roles Complaints Officer, Fraud Analyst, Manager (admin), with login |
| Approvals | **Two-tier**: officers and analysts clear cases up to `approval_limit_myr` (RM2,000 seed, so real cases escalate); anything above it, or flagged sensitive, escalates to the Manager and waits |
| Officer powers | Approve / edit reply (re-checked) / reject / send back / escalate. Every action that changes the agent's decision needs a reason and is logged old → new |
| Assignment | Baseline: least-loaded per role. Stretch: SLA-aware, capacity- and availability-aware, language-aware routing (§9) |
| Business days | Mon–Fri + 2026 KL public holidays (hard-coded list). Ack targets are calendar hours |
| Submission | Fork per team; PR to the organisers' repo titled `Submission: <team>` containing only `submissions/<team>/predictions.csv` |
| Deploy | Local laptop, `DEMO_MODE=cached` replay fallback, budget ≈ US$30 |
| Self-check demo | Officer edits a reply to a wrong amount → flagged, send blocked. Trigger steps are recorded in DEMO.md |

---

## 3. Architecture

```
            ┌──────────── Next.js UI (login, intake, queues, case trace, metrics) ────────────┐
            │                         │ REST + SSE                                           │
            ▼                         ▼                                                      │
  POST /api/complaints ──► FastAPI ──► job queue (asyncio worker pool, N=8) ──► PIPELINE ────┤
                                                                                │            │
   ┌──────────────────────────────────── PIPELINE (per issue) ──────────────────┘            │
   │ 1 INTAKE      validate, create case, event                                               │
   │ 2 UNDERSTAND  rules → TF-IDF/LR → (LLM extract) → issues[], clues, lang, injection flag   │
   │ 3 RESOLVE     date phrase → [start, end] window (code)                                   │
   │ 4 MATCH       tools.find_transactions(...) → candidates → score → unique? (code)         │
   │ 4b INVESTIGATE (only if 0 / >1 / low conf) LLM tool loop ≤5 calls, validated by code     │
   │ 5 DECIDE      policy engine: outcome, refund (Decimal), priority, route, SLA (code)      │
   │ 6 DRAFT       LLM reply from fact sheet (EN/MS)                                           │
   │ 7 CHECK       decision-bound self-check (code) → redraft once → template fallback        │
   │ 8 WRITE-BACK  case record + evidence + trace → queue → smart assignment → SSE            │
   └──────────────────────────────────────────────────────────────────────────────────────────┘
        data/*.csv loaded once into memory (indexed by customer, txn_id, reversal_of)
```

Every stage appends a `case_events` row (`actor='agent'`): `{case_id, stage, input, output, tool_calls[], model, tokens_in/out, cost_usd, latency_ms, ok}`. Human actions append to the same table. The case trace UI and the metrics page read only from `case_events` and `cases`.

---

## 4. Pipeline: stage by stage

### 4.1 Intake
The live round hands us 2–3 complaints in exactly the `complaints.csv` row format, e.g.
`LIVE-07,CUS-01234,2026-09-30 10:15,App chat,,"Hi, I was charged twice at ShopLah Online today for RM89.90..."`.
The intake must take that in **without code changes**.

- `POST /api/complaints` with JSON `{complaint_id, customer_id, received_at, channel, subject, text}` (the same six columns). `complaint_id` is optional for UI-typed complaints (auto `WEB-nnn`).
- `POST /api/complaints/csv` with a raw body of one CSV line (header optional) → parsed with Python's `csv` module (quoted text with commas and line breaks works) → same path as above.
- UI intake has two tabs: **Paste CSV row** (the default for the live round; shows the parsed fields for a glance-check before Submit) and **Form** (customer search picker showing name, ID, preferred language, age and recent transactions; channel select; `received_at` prefilled with `SIM_NOW`).
- Validation: `customer_id` must exist in `customers.csv`, `channel` must be one of the 5, and `received_at` is parsed as `YYYY-MM-DD HH:MM[:SS]`. A failure returns a 422 with a readable message shown in the UI. A duplicate `complaint_id` returns the existing case.
- `received_at` from the input is **always** used. `SIM_NOW` (env, default `2026-09-30 12:00`) only prefills the form and drives the SLA countdown clock.
- Returns `{case_id}` immediately (202). Processing is async; the UI subscribes to `GET /api/cases/{id}/stream` (SSE).
- Batch: `python -m teratai.batch --ids data/test_ids.csv --run test-v3` feeds the same `process_complaint()` with `run_id` set.

### 4.2 Understand (tiered)

**Tier 0: safety rules (code).** Regex lists in EN and MS:
- Scam cues: `polis|police|PDRM|LHDN|mahkamah|court|parcel|bungkusan|safe account|akaun selamat|invest|pelaburan|part[- ]time|kerja sambilan|love|online friend|kenalan|tertipu|scam|tipu|emergency|kecemasan`.
- Injection cues: `ignore (all|previous)|system prompt|you are now|abaikan arahan|refund me RM\d+ immediately` and similar. These set `injection_suspected=true`, which is shown in the trace. Code still decides, so injection can at worst change the extracted clues.

**Tier 1: classic ML (code, trained on `labels_train.csv`).**
- `FeatureUnion(TfidfVectorizer(analyzer="char_wb", ngram_range=(2,5), sublinear_tf=True), TfidfVectorizer(word 1–2 grams))` → `LogisticRegression(C≈10, class_weight="balanced")`. Input: `subject + " " + text`.
- 5-fold stratified CV. **Training-set evaluation must use out-of-fold predictions**, or the train score is inflated.
- Pick the confidence threshold `τ` from CV so that accepted items are ≥ 99% accurate and ≤ 10% go to the LLM.
- Persist with joblib; train in < 10 s at startup if missing.

**Tier 2: LLM extraction (Haiku, JSON schema / forced tool output, temperature 0).**
Runs **always in live mode** (for clues, multi-issue and the trace). In batch mode it runs only when classifier confidence < τ, Tier 0 and Tier 1 disagree (e.g. scam cue but non-scam label), or regex clue extraction leaves the matcher without a unique candidate.

```jsonc
{
  "issues": [{
    "category": "DUPLICATE_CHARGE|FAILED_TRANSFER|ATM_NOT_DISPENSED|UNAUTHORISED_CARD|SCAM_TRANSFER|FEE_DISPUTE|SERVICE_QUALITY",
    "amount": 46.66 | null, "amount_approx": false,
    "counterparty": "GoRide" | null,          // verbatim span, never normalised
    "date_phrase": "hari Selasa lepas" | null, // verbatim; code resolves it
    "card_last4": "2832" | null,
    "fee_type": "monthly_service|debit_annual|cc_annual" | null, "fee_month": "2026-08" | null,
    "card_in_possession": true | null
  }],
  "language": "EN|MS|MIXED|OTHER",
  "is_complaint": true,
  "injection_suspected": false
}
```
Validate with pydantic. On failure, retry once, then fall back to the regex clues.

**Regex clue extraction (code, always).** Amounts `RM\s?[\d,]+(\.\d{1,2})?` (also `MYR`, `ringgit`); approximation markers `about|around|approx|roughly|lebih kurang|kira-kira|sekitar|dalam`; card last 4; EN/MS month names (`Januari…Disember`, `Mac`, `Mei`, `Julai`, `Ogos`); fee keywords. Counterparty matching is done against the candidates in code (§4.4), so regex never needs to extract merchant names.

**Category decision:**
1. Classifier conf ≥ τ and no Tier 0 conflict → classifier label.
2. Otherwise → LLM label. If the LLM and classifier disagree and classifier conf ≥ 0.95, use the classifier.
3. **Evidence consistency (after matching):** if the matched transaction's channel family contradicts the category (e.g. FAILED_TRANSFER matched to a Card POS), re-run matching with the second-best category. If it is still inconsistent → NEEDS_INFO.
4. Scam precedence: if a Tier 0 scam cue fires and the best label is FAILED_TRANSFER or UNAUTHORISED_CARD with conf < 0.95, prefer SCAM_TRANSFER (it leads to INVESTIGATE, so no critical error is possible).

**Language (code):** call-centre note → `preferred_language`. Otherwise, stopword ratios (EN vs MS lists): clearly MS → MS, clearly EN → EN, both above threshold → MIXED → `preferred_language`. OTHER (e.g. Chinese, Tamil) → `preferred_language` + flag. Tune the thresholds against `reply_language` in the training labels.

### 4.3 Resolve dates (code, `dates.py`)
Relative to `received_at` (all times naive MYT):
- `yesterday|semalam` = −1 day; `kelmarin|day before yesterday` = −2 days; `today|hari ini|tadi` = 0.
- `last <weekday>|hari <weekday> lepas|<weekday> lepas` = the most recent such weekday **strictly before** the received date. MS weekdays: Isnin, Selasa, Rabu, Khamis, Jumaat, Sabtu, Ahad.
- `last week|minggu lepas` = [−13, −1] days (fuzzy range). `this week|minggu ini` = [Mon of this week, today].
- `last month|bulan lepas` = the whole previous calendar month.
- Absolute dates: `28 July 2026`, `11 Jul`, `11/7`, `11 Julai`.
- No phrase → full 45-day window (`MATCH_WINDOW_DAYS`, +1 day of slack, as the starter does).
- Exact day → search [day − 1, day + 1] (timezone and posting-lag slack), but **score** an exact-day hit higher.
- `dateparser` (languages `ms`, `en`) is an optional second opinion only. Our own resolver is authoritative. Unit-test 30 phrases taken from the data.

### 4.4 Match (code, `match.py`)
Tool: `find_transactions(customer_id, window, channels, direction="DR", amount=None, tol=None, card_last4=None)`.

**Channel families by category:**
| Category | Channels |
|---|---|
| DUPLICATE_CHARGE, UNAUTHORISED_CARD | Card POS, Card e-Commerce |
| FAILED_TRANSFER, SCAM_TRANSFER | DuitNow Transfer, IBG Transfer (all training scams are one of these) |
| ATM_NOT_DISPENSED | ATM Withdrawal |
| FEE_DISPUTE | Fee (`description` starts with the fee name; month from the description, e.g. `Monthly service charge Jun 2026`) |
| SERVICE_QUALITY | no match; `matched_txn_id = ""` |

**Hard filters:** customer, window, channel family, direction DR, and amount: exact ±0.005, or with `amount_approx` within max(5%, RM20).

**Tie-break score** (only among survivors): exact amount +3; counterparty fuzzy hit (case-insensitive token or substring, e.g. `paycoin` ⊂ `PAYCOIN LTD`) +3; exact date-phrase day +2, inside the range +1; card last 4 match +2; for FEE, fee type + month match +5.

**Unique rule:** accept the top candidate if it is the only survivor, or its score ≥ second-best + 2. Otherwise → Investigator (4b), then NEEDS_INFO.

**Category-specific:**
- DUPLICATE_CHARGE: candidates = charges with ≥1 identical sibling (same card, merchant, amount). Choose the **later** charge of the closest identical pair. If 3+ identical, pick the latest one whose predecessor is within 10 min; otherwise the latest. The policy engine decides REFUND/DECLINE.
- FEE_DISPUTE without an amount: match by fee type + month. If two accounts each have that fee in the month (e.g. two savings accounts), prefer the account whose product the text names; otherwise NEEDS_INFO.

### 4.4b Investigator (bounded LLM tool loop)
Runs only when 4.4 returns 0 or >1 candidates, or when category confidence is low. Haiku with tools: `find_transactions`, `get_customer`, `get_accounts`, `get_atm_journal`, `get_reversal`, `get_fee_schedule`. Max 5 tool calls, temperature 0. It returns `{txn_id | null, rationale}`.
- **Code validates** the answer: the txn must belong to the customer, lie in the window, fit the channel family and pass the hard filters. If it fails → NEEDS_INFO.
- Every tool call and result is logged as an event (this is the "uses tools" evidence for the judges).
- Live mode: always available. Batch: same, but limited to the rare ambiguous cases.

### 4.5 Decide (code, `policy.py`): money in `Decimal`, never float
| Category | Rule |
|---|---|
| DUPLICATE_CHARGE | Earlier identical charge within ≤ 10 min (`DUPLICATE_WINDOW_MINUTES`) **and** neither has a Reversal → REFUND the later amount; otherwise DECLINE |
| FAILED_TRANSFER | `status=Failed` and no Reversal references it → REFUND the amount. Reversal exists → DECLINE (reply states the reversal date). `Completed` → DECLINE |
| ATM_NOT_DISPENSED | Journal `dispensed < requested` → REFUND `requested − dispensed`; otherwise DECLINE |
| UNAUTHORISED_CARD | `auth_method=None` → REFUND the amount. `3DS-OTP` or `Chip+PIN` → INVESTIGATE. Any other value → INVESTIGATE as a defensive default (no such case exists in the training data) |
| SCAM_TRANSFER | Always INVESTIGATE, refund 0 |
| FEE_DISPUTE | `due` per fee_schedule: MSC by product (Basic Savings 0); debit annual 12.00, waived if age ≥ 60 **on the charge date**; CC annual 150/250, waived if the charge date < first anniversary of the card account's `open_date`. Refund = `charged − due` if > 0 → REFUND; otherwise DECLINE |
| SERVICE_QUALITY | INFO_ONLY, txn empty, refund 0 |

- **Priority:** base from the policy; +1 level if age ≥ 65 (`VULNERABLE_AGE`) on the **received date** (P3→P2, P2→P1, P1 stays).
- **Route:** INVESTIGATE → FRAUD_TEAM; DECLINE → HUMAN_APPROVAL; REFUND > 500.00 → HUMAN_APPROVAL (exactly 500.00 → AUTO); else AUTO_RESOLVE. NEEDS_INFO → HUMAN_APPROVAL.
- **SLA:** `ack_due = received_at + ack_hours` (calendar hours); `resolve_due = received_at + N business days` (Mon–Fri, minus `holidays_2026.py`). Hard-code the 2026 KL holiday list from an official source; do not compute it.
- **Rule trace:** the decision object includes `rule_id`, the policy text from `complaint_policy.csv`, and the inputs used (e.g. `auth_method=3DS-OTP`), for the "why" panel.
- **Validate against labels:** a `policy_test.py` feeds the *gold* `matched_txn_id` + category and asserts outcome/refund/priority/route equal the labels for all 1,750. This isolates policy bugs from matching bugs.

### 4.6 Draft reply (LLM, Sonnet, in live and batch alike, because judges read 10 test replies)
Input = a **fact sheet**, not raw tables: customer name and honorific, category, outcome, refund amount, matched txn (id, date, merchant, amount), reversal date / dispensed amount / fee due where relevant, SLA days, reply language, plus fixed regulatory snippets:
- Scam / INVESTIGATE: call **NSRC 997** and/or lodge a police report; recall attempted, recovery not guaranteed; updates at least every 10 working days.
- DECLINE: reason in plain words + redress: may refer to the ombudsman (**FMOS, formerly OFS**) or **BNMLINK / BNMTELELINK**.
- **Verification gate (BA, Day 1):** confirm each name, number and URL on bnm.gov.my / nsrc sources and record the source link in `eval/regulatory_facts.md`. Anything not confirmed is replaced with neutral wording ("you may contact our customer care hotline or refer the matter to the relevant ombudsman"). Confirmed numbers go into the self-check allow-list. **Any other phone number in a reply is flagged.**
- MS register: "Tuan/Puan", "pihak bank", "Dukacita dimaklumkan", "Sekian, terima kasih". **BA reviews MS outputs.**

Constraints in the prompt: ≤ 120 words; mention only facts from the sheet; never promise a refund unless outcome = REFUND; no internal terms (route, rule IDs). Prompt caching on the static prefix.

### 4.7 Self-check (code, `check.py`): decision-bound
`allowed_facts(case)` = the matched txn ID and amount, the refund amount, the earlier duplicate txn (ID, amount), reversal ID, date and amount, ATM requested/dispensed/shortfall, fee charged/due/difference, `AUTO_REFUND_LIMIT_MYR`, SLA days, and 997. **Not** the customer's whole 45-day history (the starter's check is too permissive: a wrong-but-existing amount passes).

Checks, each producing a named failure:
1. Every `TXN-\d{7}` in the reply ∈ allowed IDs.
2. Every amount (`RM\s?…`, `MYR …`, `ringgit`) ∈ allowed amounts (±0.005).
3. Outcome consistency: refund verbs (`refunded|will refund|credited|dikreditkan|dikembalikan|bayaran balik`) are forbidden unless outcome = REFUND; on REFUND the refund amount must appear.
4. Language: the stopword-ratio detector on the reply == `reply_language`.
5. Hygiene: no route/rule jargon, no `{placeholders}`, length ≤ 1,200 characters, and no phone numbers or URLs outside the verified regulatory allow-list.
6. Dates mentioned (stretch): must be the txn date, reversal date or SLA date.

Flow: draft → check → fail? → redraft once with the failure list → fail? → **template fallback** (per category × outcome × language, fully deterministic, always passes) + `check_flagged=true` on the case for human review. Officer edits re-run the check on save; **Send is disabled while it fails.**

### 4.8 Write-back
- **`agent_decision` is immutable**: category, txn, outcome, refund, priority, language, route and reply exactly as the agent produced them. Human actions write to `final_action` and append `case_events`. `predictions.csv` is exported from `agent_decision` only (ground rule: the scored file is the agent's autonomous output).
- The case row stores all decision fields, evidence JSON (candidates considered with scores, the matched txn, related rows), the reply, the check result, the route, ack/resolve due, `run_id`, `parent_case_id` and status.
- Status machine: `pending → (sent [auto-resolved] | pending [approval] | investigating [fraud] | needs_info) → (escalated) → approved/rejected → sent/closed`.
- AUTO_RESOLVE: the reply is "sent" (stored + shown in a simulated customer outbox) and the case is closed.
- FRAUD_TEAM: the holding reply is sent once it passes the check (it contains no money decision); the case stays open in the fraud queue.
- Live cases (`run_id=live`) go to smart assignment (§9). Eval runs do not.

---

## 5. Multi-issue complaints (Could-have)
No multi-issue complaints are visible in the training data, and the scorer takes one row per complaint. Build this only if time remains. Until then the extraction schema keeps `issues[]`, and a second issue sets a `multi_issue` flag that is shown to the officer.
- The LLM returns `issues[]`. More than one issue → a parent case with one sub-case per issue (`CMP-X#1`, `#2`). Each runs its own match/decide/route/SLA. **One combined customer reply** with a section per issue (each section checked against its own sub-case facts).
- The parent's status is the worst of its children's. It is visible in every queue the children are in.
- **Leaderboard row = the most severe issue:** SCAM > UNAUTHORISED > (DUPLICATE | FAILED | ATM, by amount desc) > FEE > SERVICE.
- In batch, the classifier gives one label, so multi-issue detection only runs when the LLM is invoked.

---

## 6. Edge cases

| Case | Behaviour |
|---|---|
| 0 candidates after investigator | NEEDS_INFO; reply asks for date / amount / merchant; CSV: empty txn, refund 0.00, outcome **INVESTIGATE** for SCAM/UNAUTH categories (avoids a missed-fraud critical), **DECLINE** for others; route HUMAN_APPROVAL (FRAUD_TEAM for INVESTIGATE) |
| >1 candidates, no margin | Same as above. Trace lists the tied candidates so the officer picks one in the UI (officer pick = a decision change with a reason; escalates if over their limit) |
| Wrong customer (card last 4 not owned, or "my friend's account") | NEEDS_INFO reason `WRONG_CUSTOMER`: no decision, **no customer reply sent**, manager alert ("stakeholder informed") |
| Prompt injection | `injection_suspected` badge; the LLM output is only clues; policy runs in code; the reply never echoes instructions. Demo-able |
| Gibberish / not a complaint / compliment | `is_complaint=false` → INFO_ONLY, polite generic reply, AUTO_RESOLVE, flag for sampling |
| Other language (Chinese, Tamil) | Reply in `preferred_language`; `language_other` flag |
| Duplicate where one charge was already reversed | DECLINE ("already refunded on <reversal date>") |
| Identical charges days apart | Not a duplicate → DECLINE |
| Failed transfer later reversed | DECLINE + reversal date in the reply |
| Fee: two accounts with the same fee | Product named in the text; otherwise NEEDS_INFO |
| Age 65 boundary | Age computed on the received **date** (birthday on that day counts) |
| Age 60 debit waiver | Age on the **charge** date (different date from the above) |
| CC first anniversary | Charge on the anniversary day → chargeable |
| Refund exactly RM500.00 | AUTO_RESOLVE (limit is "above 500") |
| Unknown `auth_method` on an "unauthorised" card txn | INVESTIGATE (defensive; none in the training data) |
| LLM down / timeout | Classifier + regex path + template reply; case flagged `degraded`. In demo, `DEMO_MODE=cached` |
| Same complaint submitted twice | Idempotency key = hash(customer_id, text, received_at) → returns the existing case |
| Live row pasted with quotes, commas or line breaks in `text` | Parsed by the `csv` module, not by splitting on commas; unit-tested with the README `LIVE-07` example |
| "today" in a live complaint (received 30 Sep) | Resolves to 2026-09-30; transactions run until 23:30 that day, so same-day matches work |

---

## 7. Humans in the loop: the ops platform (bonus award)
The core brief needs only this much: approval and fraud cases **wait** in queues, and an officer can approve or edit, with the self-check re-run on edits. Everything else in §7–§9 is the **"Best Ops Platform" bonus** ([docs/bonus_platform.md](../bonus_platform.md)). It is judged separately and does not affect the main ranking. Build it after Checkpoint 2.

### 7.1 Auth
- Seeded users in SQLite (bcrypt hashes) with a `role` column. JWT in an httpOnly cookie; FastAPI dependency `require_role(...)`. No SSO, no self-registration. The bonus doc says not to let sign-in eat the two days, so keep it to this.
- Seed users: `officer.aina` (EN, MS, limit RM2,000), `officer.daniel` (EN, limit RM2,000), `fraud.siti` (EN, MS, limit RM2,000), `fraud.raj` (EN, limit RM2,000), and `manager` (no limit). Demo passwords live in a local `.env`, not in the repo.
- The RM2,000 limit is a deliberate choice: the largest training refund is RM4,687.10, so a RM5,000 limit would never trigger an escalation in the demo.

### 7.2 Roles, screens and actions
| Role | Sees | Screen | Actions |
|---|---|---|---|
| **Complaints officer** (tier 1) | HUMAN_APPROVAL + NEEDS_INFO, own and unassigned | **Resolution desk**: editable reply first, then the decision and refund, the evidence panel, and the remaining approval headroom | Approve; edit & approve (self-check re-runs, Send blocked while it fails); reject/decline; send back to the agent; **escalate to manager** (replaces Approve when the refund > their limit) |
| **Fraud analyst** (tier 1) | FRAUD_TEAM, own and unassigned | **Investigation workbench**: suspicious txn + `auth_method` first, related account transactions, case timeline; the holding reply is secondary | Acknowledge → log investigation / recall attempt → record outcome (`confirmed fraud`, `not fraud`, `recall succeeded`, `recall failed`); escalate when the amount > limit or the case is sensitive |
| **Manager** (admin, tier 2) | Both queues + the escalation queue + audit log + metrics | **Oversight console**: throughput, SLA, override rate; a merged escalation queue showing what tier 1 did and why | Approve or reject escalations with a reason; reassign; set officer availability |

- **Two-tier rule:** a tier-1 action on a case whose refund > the actor's `approval_limit_myr`, or one flagged `sensitive` (vulnerable 65+, `injection_suspected`, `check_flagged`), sets status `escalated`. It is **not sent** until the manager approves.
- **Reasons:** every action that changes the agent's decision (outcome, amount, txn, reply text) needs a one-line reason. Reason codes: `WRONG_TXN`, `GOODWILL`, `POLICY_EXCEPTION`, `CUSTOMER_PROVIDED_INFO`, `OTHER (text)`. Overridden amounts are re-checked against the evidence: a refund greater than the charged amount is blocked.
- **Agent vs human:** the case page shows `agent_decision` beside `final_action` with the differences highlighted. The manager's dashboard shows the override rate. This gap is not scored, but the bonus doc calls it "one of the most interesting things you can show a judge".
- **Core-only fallback** (if the bonus is cut): a single `officer` login, the approval and fraud queues, approve / edit with re-check. That still meets README point 4.

## 8. Queues
- **Approval** (HUMAN_APPROVAL: DECLINEs, refunds > RM500), **Fraud** (FRAUD_TEAM), **Needs info** (NEEDS_INFO, WRONG_CUSTOMER), **Escalations** (manager only), **Auto-resolved** (read-only audit log).
- Sorted by priority, then SLA due time (the bonus MVP requirement).
- Each row: priority badge, SLA countdown (ack and resolve; amber at 75%, red when breached), category, amount, language, assignee, flags (check failed, injection, degraded, multi-issue, vulnerable 65+).

## 9. Assignment (`ops/routing.py`)
**Baseline (build first, ~30 lines):** on case creation, assign it to the online user with the right role and the fewest open cases; P1 first. The manager can reassign.

**Stretch (only after the rest of the bonus works): smart routing.** Modelled on Salesforce Omni-Channel and Twilio TaskRouter: weighted capacity, skill filter, availability gate, earliest-deadline ordering, timed escalation.

- Officer: `role, languages[], status(online|away|offline), shift_start, shift_end, max_capacity (default 6), load`.
- Case weight: P1 = 3, P2 = 2, P3 = 1. Queue role: FRAUD_TEAM → Fraud analyst; APPROVAL / NEEDS_INFO → Complaints officer; ESCALATED → Manager.

```
eligible(o, c) = o.role == c.queue_role and o.status == "online" and in_shift(o, now)
                 and o.load + c.weight <= o.max_capacity
order unassigned cases by (ack_due ASC, priority ASC, received_at ASC)   # earliest deadline first
for c in order:
    pool = eligible officers
    pool = [o for o in pool if c.reply_language in o.languages] or pool   # soft language match
    if not pool and c.ack_elapsed >= 0.75: pool = [manager]                # overflow
    if pool: assign min(pool, key=(load/max_capacity, last_assigned_at)); log reason
```
- The reason string is shown on the case: *"Fraud role · MS ✓ · load 2/6 · ack due in 1h40m"*.
- **Re-run on:** new case, case closed or sent, officer status or shift change, capacity change, and a 60 s ticker (at-risk escalation at 75% of the ack window → `at_risk` flag + manager alert; breach at 100%).
- Officer goes offline → their unacknowledged cases are unassigned and re-routed. Acknowledged cases stay with them, with a manager alert.
- The SIM clock drives SLA maths in the demo, so countdowns are meaningful. The manager has a "fast-forward 1h" button to show escalation.

## 10. Data model (SQLite)
```
users(id, username, pw_hash, role[officer|fraud|manager], languages, approval_limit_myr NULL=unlimited,
      status, shift_start, shift_end, max_capacity, last_assigned_at)
cases(id, complaint_id, parent_id, run_id, customer_id, channel, received_at, subject, text,
      agent_decision JSON  -- immutable: category, conf, source, txn, outcome, refund, priority, lang, route, reply
      final_action JSON    -- what humans did / what was sent; NULL until a human acts
      status[pending|escalated|approved|rejected|sent|investigating|closed|needs_info],
      check_ok, check_issues JSON, flags JSON, evidence JSON, decision_trace JSON,
      ack_due, resolve_due, acknowledged_at, assigned_to, assign_reason, created_at, updated_at)
case_events(id, case_id, ts, actor['agent'|username], action, stage, field, old_value, new_value, reason,
            payload JSON, tool_name, model, tokens_in, tokens_out, cost_usd, latency_ms, ok)   -- append-only
alerts(id, ts, kind, case_id, message, seen)
outbox(id, case_id, ts, language, text, authorised_by)   -- simulated "sent to customer"
llm_cache(key, response JSON, ts)                         -- key = sha256(model, prompt_version, input)
```
`case_events` holds both the agent's pipeline trace (`actor='agent'`, per stage) and the human audit log (old → new + reason). One table means one timeline in the UI.

## 11. API (FastAPI)
```
POST /api/complaints            JSON {complaint_id?, customer_id, received_at, channel, subject, text} → 202 {case_id}
POST /api/complaints/csv        raw text/csv body: one complaints.csv row (header optional)    → 202 {case_id}
GET  /api/customers?q=          (form picker: id, name, age, pref lang, recent txns)
GET  /api/cases?queue=&assignee=&run_id=        GET /api/cases/{id}  (incl. case_events)
GET  /api/cases/{id}/stream     (SSE stage updates)
POST /api/cases/{id}/reply      (edit → re-check → {check_ok, issues, send_enabled})
POST /api/cases/{id}/approve | /reject | /send-back | /escalate          (officer)
POST /api/cases/{id}/ack | /investigation | /outcome                      (fraud analyst)
POST /api/cases/{id}/manager-approve | /manager-reject | /reassign        (manager)
POST /api/auth/login | /logout   GET /api/me   POST /api/users/{id}/status   GET /api/alerts
GET  /api/metrics?run_id=        POST /api/admin/clock (SIM_NOW, fast-forward)
GET  /api/export/predictions?run_id=   → predictions.csv from agent_decision only
```
Pipeline functions are plain Python and are also callable from the batch CLI. No HTTP is needed for eval.

## 12. LLM layer and cost
- `llm/base.py`: `extract(schema, messages) -> dict`, `generate(messages) -> str`, `tool_loop(tools, messages, max_calls) -> result`. Implementations: `anthropic_provider.py`, `openai_provider.py` (same interface), `replay_provider.py` (reads `llm_cache`; used for `DEMO_MODE=cached`).
- Config: `LLM_PROVIDER`, `EXTRACT_MODEL`, `REPLY_MODEL`, `PRICE_TABLE` (US$/MTok per model, for the cost column). Use `ctx7` / provider docs for the current SDK syntax; don't code from memory.
- All calls go through the disk cache, keyed by (model, prompt_version, input hash). Re-runs of unchanged prompts are free.
- **Batch budget plan (keep total ≈ US$30; check current per-token prices before the 750 run):**
  - Train 1,750: classifier + regex + matcher + policy, **no LLM**, for iteration speed (seconds per full run). The LLM extract only runs on the low-confidence or ambiguous subset.
  - Train replies: a 50-case sample (Checkpoint 2) + a 200-case sample for self-check stats.
  - Test 750: full pipeline; LLM extract on the fallback subset; replies with `REPLY_MODEL` (Sonnet), because judges read 10 of them. Concurrency 8–16.
  - Live/demo: Sonnet replies, LLM extract always.
- The metrics page shows cost per complaint and p50/p95 latency per stage, from `case_events`.

## 13. Observability: "show me why"
Case detail page:
1. **Timeline**: each stage with duration, model, tokens, cost, ✓/✗.
2. **Understanding**: classifier top-3 with probabilities, which tier decided, extracted clues, the resolved date window, language reasoning.
3. **Evidence**: the customer's debits in the window, with filtered-out rows greyed, candidates scored (score breakdown), the matched row highlighted, plus related rows (duplicate sibling, reversal, ATM journal, fee schedule row).
4. **Decision card**: the policy rule text, the inputs, the outcome, the refund calculation (e.g. `1500.00 − 950.00 = 550.00`), priority (base + vulnerable bump), route reason, SLA dates.
5. **Reply + self-check**: tokens highlighted green (verified) or red (not in evidence), drafts history (draft 1 failed → draft 2 / template).
6. **Tool calls**: investigator / tool registry calls with args and results.
7. **Audit**: acknowledgements, edits, decision changes with reasons (old → new), escalations and manager approvals, assignment reasons, and `agent_decision` vs `final_action`.

## 14. Repo layout
```
backend/teratai/
  data.py           (loads CSVs once; indexes; reversal_of; Decimal amounts)
  dates.py  classify.py  extract.py  match.py  investigate.py  policy.py
  reply.py  check.py  templates/{en,ms}.py  tools.py  pipeline.py  batch.py
  llm/ base.py anthropic_provider.py openai_provider.py replay_provider.py
  ops/ routing.py sla.py holidays_2026.py
  api/ main.py auth.py routes_*.py sse.py   db.py
backend/tests/      test_dates.py test_match.py test_policy.py test_check.py test_routing.py
eval/               adversarial.jsonl  live_kit.md  (BA-owned)
web/                Next.js + shadcn (login, intake, resolution desk, fraud workbench, manager console, case, metrics)
submissions/<team>/predictions.csv
```
`starter/` and `scoring/` stay untouched. Our check is stricter but must still pass the starter's `check_reply.py`.

---

## 15. Team split and timeline

| | **Dev A, "Core" (accuracy owner)** | **Dev B, "Platform" (live-round owner)** | **BA/Tester, "Quality + Demo"** |
|---|---|---|---|
| Owns | data, dates, classifier, extract, match, investigator, policy, batch, scoring loop | FastAPI, DB, intake (JSON + CSV row), pipeline orchestration, SSE, reply + self-check wiring, queues UI; then the bonus ops platform | eval sets, error analysis, MS/EN reply review, templates, regulatory fact check, DEMO.md, pitch |

**Day 1**
- 09:00–10:00 Kick-off. BA opens GitHub issues for anything in §18 that is still unclear.
- 10:00–10:30 Contracts together: `Case`/`AgentDecision`/`Extraction` pydantic models, DB schema, API list, CSV writer. Commit.
- 10:30–13:00 A: data + dates + matcher + `policy_test.py` on gold txns. B: FastAPI skeleton, LLM layer (one real call through the provider with a tool call executed), SQLite, **both intake endpoints with the README `LIVE-07` row as the first test**, pipeline stub → SSE; Next.js scaffold. BA: run the baseline + scorer; build `adversarial.jsonl` (30 cases) and `live_kit.md` (10 `LIVE-xx` rows in the official format, received 30 Sep); collect 30 date phrases for tests; **verify 997 / FMOS / BNMLINK and write `eval/regulatory_facts.md` with sources**.
- 14:00–16:00 A: classifier (OOF CV) + full deterministic run on train → **first score**. B: queues + case page reading real cases. BA: `--details` error analysis → ranked bug list to A.
- **16:00 Checkpoint 1**: classify + match on 20 train complaints (we show all 1,750 OOF).
- 16:00–close: A: fix top error buckets; **write a safety-net test submission tonight (deterministic + template replies)**. B: reply LLM + decision-bound self-check + redraft/template fallback. BA: MS/EN templates (using only verified regulatory facts); review 20 replies.

**Day 2**
- 09:00 Stand-up (5 min).
- 09:15–12:00 A: LLM extract fallback + investigator; train score ≥ 90. B: **core human gate first**: approval + fraud queues, approve / edit with re-check, outbox, `agent_decision` export; then the 50-case Checkpoint 2 run. BA: paste the live kit through the UI and log failures; review 10 test replies.
- **12:00 Checkpoint 2**: full workflow on 50 train (decision, reply, approval, write-back) + training score posted.
- 12:00–13:30 A: **final 750 test run** (cached; Sonnet replies), score sanity checks (distribution vs train), export the CSV from the DB. B: **bonus ops platform**: roles + login, two-tier escalation, fraud workbench actions, audit timeline, agent-vs-human view; `DEMO_MODE=cached` recording; seed ~30 demo cases. BA: rehearse the demo ×2.
- 13:30–14:30 **Feature freeze.** Fix criticals only. README with AI and tool disclosure.
- **≤ 14:30 Open the PR** from the team fork to the organisers' repo, titled `Submission: <team>`, containing `submissions/<team>/predictions.csv`. This leaves 30 min of buffer before 15:00.
- 15:15 Demo.

## 16. MoSCoW (cut order, scoring-aware)
**Must** (main ranking): deterministic matcher + policy + priority + language (30% leaderboard); intake accepting the official CSV row via API/UI → async pipeline → queues (live round); decision-bound self-check + edit re-check; approval and fraud queues where cases wait for a human; case trace (evidence + decision card); a valid predictions.csv with Sonnet replies, exported from `agent_decision`.
**Should** (main ranking): classifier tiers + LLM extract fallback; investigator tool loop; LLM replies with template fallback; cached demo mode; cost and latency per stage on the metrics page.
**Should** (bonus award, after Checkpoint 2): role-based login (officer / fraud analyst / manager); two-tier approval with escalation; fraud workbench actions; audit timeline + agent-vs-human view; least-loaded assignment.
**Could**: smart SLA/capacity/language routing; multi-issue split; fast-forward clock; date checks in the reply; alerts panel polish.
**Won't**: real email/SMS sending, customer identification from text, SSO, cloud deploy, fine-tuning, a per-state weekend calendar, translation of non-EN/MS languages.

**Cut first when behind:** multi-issue → smart routing → fast-forward clock → metrics polish → the whole bonus platform (fall back to the core-only gate in §7.2). **Never cut:** matcher accuracy work, the official-format intake, self-check, approval/fraud queues, the safety-net submission.

## 17. Testing and acceptance
- `pytest backend/tests`: 30 date phrases; matcher regression on the ~20 "gold missing" cases; policy on gold txns for all 1,750 (100% outcome/refund/priority/route); self-check (the starter's two examples + 10 adversarial replies, incl. an unverified phone number); CSV-row intake (the README `LIVE-07` example, quoted text with commas and a newline, bad customer_id → 422); two-tier escalation (refund > limit cannot be sent by tier 1); export uses `agent_decision` even after a human edit.
- `python -m teratai.batch --ids train --run dev && python scoring/score.py submissions/<team>/train_predictions.csv data/labels_train.csv --details details.csv` → ≥ 90, 0 critical.
- Live acceptance: the scripted DEMO.md cases + 5 `live_kit.md` rows pasted into the UI produce the expected outcome, route, queue, assignee and self-check status, and the CMP-00244 edit flags `RM600.00`.
- Test-set sanity: category/outcome/route distribution of the 750 within ±5 pp of the training distribution; a spike means a bug, not a feature.

## 18. Risks and open questions (ask via GitHub issues)
Answered by the updated brief: the live clock (30 Sep 2026), the live intake format (a `complaints.csv` row incl. `customer_id`), and submission (fork + `Submission: <team>` PR). Answered by the data: Contactless cases (none) and JomPAY scams (none).

Still open:
1. Are the 10 replies judges read sampled from `predictions.csv` or from the live system? (We use Sonnet for both, so the answer only affects emphasis.)
2. Is the Malay reply judged by a native speaker? (affects BA review time)

| Risk | Mitigation |
|---|---|
| Inflated train score (classifier trained on the same labels) | Out-of-fold predictions only |
| Template-repeat leakage train→test | Watch the per-channel and per-category score; don't tune τ on test |
| 750-run fails late | Safety-net submission on Day 1 evening; cached LLM; resume-by-ID batch |
| Live row fails to parse in front of judges | `csv` module parsing, the README example as the first unit test, BA rehearses with 10 `LIVE-xx` rows |
| Venue Wi-Fi / API outage in the demo | `DEMO_MODE=cached` + phone hotspot |
| Malay tone sounds machine-written | BA review + formal-register few-shots + templates |
| Unverified regulatory facts read as invented facts | Day 1 verification gate; neutral wording otherwise; unknown phone numbers flagged by the self-check |
| Dev B overload (intake + replies + queues + bonus) | Core human gate before Checkpoint 2; the bonus only after it; cut order in §16 |
| API keys in a public repo | `.env` in `.gitignore`; pre-commit `git diff --cached` grep for `sk-` |

## 19. Out of scope
Real channels (email/SMS/WhatsApp), customer identity resolution, payments execution, chargeback filing, PDPA/DSAR flows, mobile UI, multi-tenant, production security hardening.
