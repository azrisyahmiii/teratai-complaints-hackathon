# Teratai Bank Complaints Agent Hackathon

**Two days. One problem. Build an AI agent that handles bank customer complaints end to end**: it reads the complaint, finds the transaction, applies the bank's policy, decides the refund and drafts the reply. A human signs off on the risky calls.

> Teratai Bank is fictional and every record in this repo is synthetic. Payment-rail names (DuitNow, IBG, JomPAY) are used for realism only.

---

## The challenge

Teratai Bank receives complaints through app chat, email, call-centre notes, branch forms and social media. They arrive in English, in Malay, and in a mix of both. Today a complaints officer reads each one, searches the customer's transactions, checks the policy, decides what the bank owes and writes the reply. It is slow, and the backlog keeps growing.

Your team builds the agent that does this work. For every complaint it must produce:

| Field | Values | What it means |
|---|---|---|
| `category` | 7 types (below) | What the complaint is about |
| `matched_txn_id` | `TXN-…` or empty | The transaction the complaint refers to, found in `transactions.csv` |
| `outcome` | `REFUND` / `DECLINE` / `INVESTIGATE` / `INFO_ONLY` | The decision under the bank's policy |
| `refund_amount_myr` | e.g. `45.90` | How much the bank pays back (0 unless REFUND) |
| `priority` | `P1` / `P2` / `P3` | How urgent the case is |
| `reply_language` | `EN` / `MS` | The language the reply must be written in |
| `route` | `AUTO_RESOLVE` / `HUMAN_APPROVAL` / `FRAUD_TEAM` | Who acts next |
| `reply_text` | free text | The reply to the customer |

Two examples:

> **CMP-00165** (app chat): *"Hai, saya telah dicaj dua kali di GoRide hari Selasa lepas sebanyak RM46.66. Saya hanya membuat satu pembelian. Sila bantu."*
> The agent works out that "last Tuesday" means 18 Aug. It finds two identical GoRide charges 1 minute 50 seconds apart, neither reversed. Result: DUPLICATE_CHARGE, matched TXN-0115572 (the later charge), REFUND RM46.66, P2, reply in Malay, AUTO_RESOLVE.

> **CMP-00387** (call-centre note): *"Customer called. Disputes a card transaction of about RM2,200 at LUXEGOODS LONDON last Saturday; says the card is in their possession."*
> The agent finds the RM2,213.95 charge on 19 Sep and sees it was approved with a one-time password (3DS-OTP). Result: UNAUTHORISED_CARD, INVESTIGATE, no refund now, P1, route to the fraud team. The reply goes in the customer's preferred language (English), because staff wrote the note.

## The seven complaint types

| Category | Typical complaint | What decides it |
|---|---|---|
| `DUPLICATE_CHARGE` | "I was charged twice at …" | Two identical card charges no more than 10 minutes apart, neither reversed → refund the later one |
| `FAILED_TRANSFER` | "My DuitNow transfer failed but the money was deducted" | Status Failed and not reversed → refund. Already reversed, or actually completed → decline |
| `ATM_NOT_DISPENSED` | "The ATM didn't give me the cash" | The ATM journal shows less dispensed than requested → refund the difference |
| `UNAUTHORISED_CARD` | "I didn't make this payment" | No strong authentication → refund. Approved with OTP or chip and PIN → fraud team investigates |
| `SCAM_TRANSFER` | "A 'police officer' told me to move my money to a safe account" | Always the fraud team, P1, to attempt a recall |
| `FEE_DISPUTE` | "Why was I charged this fee?" | The fee schedule and its waivers (product, age, card's first year) → refund what was wrongly charged |
| `SERVICE_QUALITY` | "I waited two hours at the branch" | No money involved: apologise and explain the next step |

The full decision rules are in [`data/complaint_policy.csv`](data/complaint_policy.csv). The rules that apply to every complaint:

- **Priority:** P1 for scams and unauthorised card use; P2 for duplicates, failed transfers and ATM cases; P3 for fees and service. A customer aged **65 or over** on the day the complaint arrives moves **one level up**.
- **Reply language:** the language the complaint is written in. If it mixes English and Malay, or it is a call-centre note written by staff, use the customer's `preferred_language`.
- **Routing:** INVESTIGATE goes to the **fraud team**. Every DECLINE, and every refund **over RM 500**, needs **human approval** before anything reaches the customer. Everything else is auto-resolved.

## What your agent must do

This is an agent hackathon, not a classification contest. A model that only labels CSV rows won't win. Your solution must:

1. **Expose the API.** Your agent runs as a small service with a fixed API ([`docs/api.md`](docs/api.md)): a complaint POSTed to it starts the workflow on its own, and the decision can be read back. That is how the live round sends you complaints.
2. **Use tools.** It looks things up through tools or functions (customer, accounts, transactions, ATM journal, fee schedule). It does not paste whole tables into a prompt.
3. **Act.** It writes a case record: the decision, the evidence it used and the drafted reply.
4. **Keep a human in charge.** Cases that need approval wait in an approval queue, and fraud cases land in a fraud queue. Nothing that needs approval goes out without it. In the API this shows as `case_state` and `sent`, and people act through `POST /cases/{id}/actions` ([`docs/api.md`](docs/api.md#case-states-human-in-the-loop)).
5. **Check itself.** Code, not the LLM, checks that every transaction ID and amount in the reply appears in the evidence. Anything that fails the check is flagged.

The design that wins: **the LLM does language** (understanding the complaint, writing the reply), and **code does money and rules** (finding the transaction, applying the policy, working out the refund).

## The data

Everything is CSV in [`data/`](data/). All times are Malaysia time (UTC+8). Column-by-column details are in [`docs/data_dictionary.md`](docs/data_dictionary.md).

| File | Rows | What |
|---|---|---|
| `complaints.csv` | 2,500 | The complaints: channel, received time, subject, free text. Only the customer is identified |
| `customers.csv` | 3,000 | Name, date of birth, location, segment, preferred language |
| `accounts.csv` | 4,903 | Savings, current and credit-card accounts, with card last-4 digits |
| `transactions.csv` | 156,366 | April to September 2026: card, transfer, ATM, bill, fee and reversal transactions |
| `atm_journal.csv` | 18,240 | What each ATM actually dispensed |
| `fee_schedule.csv` | 6 | Fees by product, with waiver rules |
| `complaint_policy.csv` | 7 | The decision rules per category |
| `policy_parameters.csv` | 7 | Thresholds and rules: refund approval limit, vulnerable age, matching window, routing, reply language |
| `sla_policy.csv` | 3 | Acknowledge and resolve targets by priority |
| `labels_train.csv` | 1,750 | Correct answers for 70% of complaints. Use them to build and test |
| `test_ids.csv` | 750 | The complaints you are scored on. Their answers are held by the organisers |

## Scoring and judging

**Leaderboard (automatic).** Submit predictions for the 750 test complaints. Each complaint scores up to 100:

| Field | Points |
|---|---|
| `matched_txn_id` | 25 |
| `outcome` | 25, only if the transaction is right |
| `refund_amount_myr` | 25, exact to the sen, only if the transaction is right |
| `category` | 10 |
| `priority` | 10 |
| `reply_language` | 5 |

A decision about the wrong transaction earns nothing, so finding the right transaction is the heart of the task. The keyword baseline in `starter/` scores **31.9**. The answer key scores 100.

**Critical errors** are penalised on top: paying a refund the bank doesn't owe, and failing to send a fraud case to the fraud team. Each 1% of critical errors costs 2% of your score. Run the same scorer on the training labels at any time (see *Getting started*).

**Final ranking:**

| Weight | Criterion | How it is judged |
|---|---|---|
| 30% | Accuracy | Leaderboard score on the test set |
| 25% | Live round | **Hidden test (15):** our script sends 20 unseen, messily written complaints to your API and scores the answers automatically. **Human gate (10):** judges watch 3 more complaints end to end and check that approvals hold and fraud cases reach the fraud queue |
| 25% | Business value and demo | Reply quality (tone, correct language, no invented facts; judges read 10 of your replies), clarity, and whether a bank would use it |
| 20% | Engineering | Architecture, observability (can you show why it decided what it did?), cost and speed per complaint |

### The live round

Two parts, both through your API ([`docs/api.md`](docs/api.md)). Put its URL in your submission PR and keep it running from the 15:00 freeze until your demo ends.

**Hidden test (15 points, automatic).** Right after the 15:00 freeze, our script sends **20 complaints you have never seen** to your API, all at once, and scores the answers exactly like the leaderboard (score × 0.15). They are about customers and transactions already in the data, but they are written the way real customers write: typos, SMS short forms, emoji, mixed English and Malay. An agent tuned to the wording of `complaints.csv` will struggle; one that understands language won't. Each complaint carries its own `received_at`: use it, not today's date. Run the same script on yourself with training complaints any time: `python scoring/api_check.py http://localhost:8000`.

**Human gate (10 points, judges).** In your demo, we send 3 more complaints, one at a time, and watch. The case appears on its own, and you show us the matched transaction, the evidence, the decision, the route, the reply and the self-check. A case that needs approval must wait until someone approves it in your system, and a fraud case must land in the fraud queue. We also check this through the API: until it's approved, a case waiting for approval must show `case_state: awaiting_approval` and `sent: false`.

Every live complaint is the six fields of a `complaints.csv` row as JSON. [`examples/live_complaint_example.json`](examples/live_complaint_example.json) is one (training complaint CMP-00244). The script's robustness probes and timings go to the judges as part of the engineering score.

## Schedule

**Day 1**

| Time | |
|---|---|
| 09:00 | Kick-off: the problem, data, rules and scoring |
| 09:30 | Walkthrough of the starter kit and the baseline |
| 10:00 | Teams design their workflow |
| 10:30 | Build |
| 13:00 | Lunch |
| 16:00 | **Checkpoint 1:** the agent classifies and finds the right transaction for 20 training complaints |
| 17:30 | Day 1 close (the room stays open) |

**Day 2**

| Time | |
|---|---|
| 09:00 | Stand-ups, 5 minutes per team |
| 12:00 | **Checkpoint 2:** the full workflow (decision, reply, approval and write-back) runs on 50 training complaints, your training score is posted, `scoring/api_check.py` passes against your API, and we confirm we can reach it from the organisers' laptop |
| 13:00 | Lunch |
| 15:00 | **Agent and API freeze:** predictions due (PR with commit hash and API URL); your API must be running |
| 15:00–15:45 | Organisers score the predictions and run the hidden test on every team's API. Keep it running |
| 15:00–16:30 | Keep working on your UI and the optional ops platform |
| 16:30 | Demos: about 10 minutes per team (presentation, human gate, ops platform if you built one) |
| 17:20 | Final judging |
| 17:45 | Awards |

The 750 test complaints are in `complaints.csv` from the start, so you can run them whenever you are ready. Don't leave a 750-complaint LLM run for the last hour.

## Getting started

Teams of 3 to 5. Use any language, agent framework and LLM your team can access. The starter kit needs only Python 3.10+, with no packages to install. On macOS or Linux, use `python3` where the commands below say `python`.

```bash
git clone https://github.com/DM-Data-Science/teratai-complaints-hackathon.git
cd teratai-complaints-hackathon

# 1. See one complaint with its evidence: an ATM that paid out RM950 of a RM1,500 withdrawal
python starter/evidence_pack.py CMP-00244

# 2. Run the keyword baseline and score it on the training labels: 31.9 is the score to beat
python starter/baseline.py
python scoring/score.py submissions/baseline/predictions.csv data/labels_train.csv

# 3. Check drafted replies against the evidence (the self-check every agent needs)
python starter/check_reply.py CMP-00244 "We have refunded RM550.00 for transaction TXN-0088211."   # VERIFIED
python starter/check_reply.py CMP-00244 "We have refunded RM600.00 for transaction TXN-0088299."   # FLAGGED: invented ID and amount

# 4. Once your API is running, test it the way the live round will
python scoring/api_check.py http://localhost:8000
```

More in [`docs/build_guide.md`](docs/build_guide.md): a reference workflow, where to use the LLM and where to use code, and common pitfalls.

## Bonus: the ops platform

An optional, separately judged award ("Best Ops Platform") for teams that turn the case record into a real back-office system: complaints officers and fraud analysts sign in to interfaces fitted to their job and see only their cases, a manager handles second-tier approval across both queues, and every action is written back and audited. It does not affect the main ranking or the leaderboard, and you can keep building it until 16:30 on Day 2. See [`docs/bonus_platform.md`](docs/bonus_platform.md).

## Submitting

1. Fork this repo (one fork per team) and build in your fork.
2. Run your workflow on all 750 complaints in `test_ids.csv`.
3. Save `submissions/<team-name>/predictions.csv` with these columns: `complaint_id, category, matched_txn_id, outcome, refund_amount_myr, priority, reply_language, route, reply_text`. The format is in [`docs/scoring.md`](docs/scoring.md).
4. Open a pull request from your fork to this repo, titled `Submission: <team-name>`, before **15:00 on Day 2**. The PR only needs the predictions file; your code can stay in your fork. In the PR description put your **freeze commit hash** (the last commit in your fork at 15:00) and your **API URL**.

15:00 freezes the agent and its API: we take your leaderboard and hidden-test scores right after, so later changes to the agent don't count. You can keep working on your UI and the optional ops platform until 16:30, then demo.

Building the [bonus ops platform](docs/bonus_platform.md)? Your `predictions.csv` is still the agent's autonomous output, exported from your database and scored exactly as above — the platform does not change what you submit.

If this repo changes before the event (clarifications only, never the data), sync your fork with GitHub's **Sync fork** button.

## Ground rules

- **Your workflow produces the answers.** No hand-labelling of the test set. The live round shows whether your system really works; a big gap between your leaderboard score and the live round will be questioned. This holds even if you build the [bonus ops platform](docs/bonus_platform.md): the scored `predictions.csv` is always the agent's autonomous decision, never the human-corrected one.
- **Use any tools.** That includes any LLM, framework or cloud service. You may use the training labels however you like: few-shot examples, evaluation, fine-tuning.
- **Data stays synthetic.** Don't add real customer data, and keep API keys out of the repo.
- **Ask early.** If a rule is unclear, [open an issue](https://github.com/DM-Data-Science/teratai-complaints-hackathon/issues) in this repo. Every team can see the answers.

## FAQ

**How will our agent be evaluated?** In four parts (details under *Scoring and judging*):
1. **Accuracy (30%):** we score your `predictions.csv` for the 750 test complaints automatically.
2. **Live round (25%):** right after the 15:00 freeze, our script sends 20 unseen, messily written complaints to your API and scores them (15); in your demo, judges watch 3 more end to end to check the approval and fraud handling (10).
3. **Replies and demo (25%):** judges read your replies to the same 10 test complaints as every other team, and score the demo.
4. **Engineering (20%):** you walk the judges through how it's built.

Separately, there is an optional **Best Ops Platform** award for teams that build a full staff app: role-based queues, two-tier approval and an audit trail ([`docs/bonus_platform.md`](docs/bonus_platform.md)). It is judged on its own and doesn't change the main ranking.

**Do we need to build an API?** Yes, a small one with a fixed contract: `POST /complaints`, `GET /cases/{complaint_id}` and `GET /health` ([`docs/api.md`](docs/api.md)). It's about 30 lines with FastAPI ([`docs/build_guide.md`](docs/build_guide.md#the-api)). It's how the live round sends you complaints, so every team is tested the same way. Check yours with `python scoring/api_check.py`.

**How do approvals work through the API?** Each case carries `case_state` (`auto_resolved`, `awaiting_approval`, `with_fraud_team`, `approved`, `rejected`) and `sent`. A person acts with `POST /cases/{id}/actions`: approve, reject, or edit and approve, with their name and a reason. An edited reply must pass your self-check. The agent's own decision never changes; the human's action is stored next to it in `human_action`. Your UI's buttons can call the same endpoint. Details and examples: [`docs/api.md`](docs/api.md#post-casescomplaint_idactions).

**Do we need an API gateway, keys or rate limits?** No. Our calls carry no credentials. We do check that bad input gets a `4xx` instead of a crash, that posting the same complaint twice doesn't create a second case, and how long each complaint takes; those results feed the engineering score.

**Do we need a chatbot UI?** No. This is a back-office tool for complaints officers, not a customer chatbot. Customers never talk to your agent; it drafts the reply an officer would send. You need a way to show three things:
- the queues: auto-resolved, waiting for approval, fraud team;
- a case: the complaint, the matched transaction, the evidence, the decision, the reply and the self-check result;
- the approval step.

A simple web page, a Streamlit or Gradio app, a CLI or a notebook all work for the main ranking. Judges score clarity and whether a bank could use it, not visual polish. A fuller staff app is what the optional Best Ops Platform award is for.

**Do we need user accounts or roles (RBAC) for managers?** Not for the main ranking. There, "human in charge" means a case that needs approval waits until someone approves it in your system, and an approve or reject action that records the approver's name is enough. Roles (complaints officer, fraud analyst, manager), seeded users and second-tier approval by the manager belong to the optional **Best Ops Platform** award ([`docs/bonus_platform.md`](docs/bonus_platform.md)). Even there, seeded users with a `role` column are enough: don't build real authentication. Get the core agent working first.

**Do we actually send replies or refunds?** No. Put approved replies in an outbox (a file or a table) and record the refund as a decision. Nothing leaves your system.

**Can the policy rules be plain code?** Yes, and that's the recommended design. The LLM reads the complaint and writes the reply; code finds the transaction, applies `complaint_policy.csv` and works out the refund. An agent that leaves the money to the LLM will lose points on accuracy.

## Repo layout

```
data/          the CSVs (complaints, customers, accounts, transactions, ATM journal, policies, training labels, test IDs)
docs/          data dictionary, scoring details, API contract, build guide, bonus ops platform
examples/      one complaint in the API's JSON format (and as a CSV row)
starter/       evidence pack builder, reply checker, keyword baseline (Python, standard library only)
scoring/       score.py (the leaderboard scorer) and api_check.py (tests your API the way the live round does)
submissions/   one folder per team
```
