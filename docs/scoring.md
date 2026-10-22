# Scoring

## Predictions file

One row per complaint in `test_ids.csv` (extra rows are ignored), UTF-8 CSV with this header:

```
complaint_id,category,matched_txn_id,outcome,refund_amount_myr,priority,reply_language,route,reply_text
```

| Column | Allowed values |
|---|---|
| `category` | `DUPLICATE_CHARGE`, `FAILED_TRANSFER`, `ATM_NOT_DISPENSED`, `UNAUTHORISED_CARD`, `SCAM_TRANSFER`, `FEE_DISPUTE`, `SERVICE_QUALITY` |
| `matched_txn_id` | A `TXN-…` ID, or empty for `SERVICE_QUALITY` |
| `outcome` | `REFUND`, `DECLINE`, `INVESTIGATE`, `INFO_ONLY` |
| `refund_amount_myr` | Number with two decimals; `0.00` unless REFUND |
| `priority` | `P1`, `P2`, `P3` |
| `reply_language` | `EN`, `MS` |
| `route` | `AUTO_RESOLVE`, `HUMAN_APPROVAL`, `FRAUD_TEAM` |
| `reply_text` | The reply you would send (quote it; it may contain commas and line breaks) |

`submissions/baseline/predictions.csv` (written by `python starter/baseline.py`) shows the format.

## Leaderboard score

Each complaint earns up to 100 points:

| Field | Points | Rule |
|---|---|---|
| `matched_txn_id` | 25 | Exact match (empty = empty) |
| `outcome` | 25 | Exact match, **and** the transaction must be right |
| `refund_amount_myr` | 25 | Within RM0.005, **and** the transaction must be right |
| `category` | 10 | Exact match |
| `priority` | 10 | Exact match |
| `reply_language` | 5 | Exact match |

**Critical errors** are counted separately:
- **Wrongful refund:** you predict a refund above zero when the correct outcome is DECLINE or INVESTIGATE.
- **Missed fraud:** the correct outcome is INVESTIGATE and you predict anything else.

**Final score = mean points × (1 − 2 × critical error rate)**, never below 0. Example: a mean of 90 with 3% critical errors gives 90 × 0.94 = 84.6.

`route` and `reply_text` aren't in the automatic score. Judges check routing in the live round and read a sample of 10 replies per team. We also run automatic checks on all your replies and give the results to the judges: empty replies, replies in the wrong language, transaction IDs or RM amounts that aren't in the customer's evidence (the same check as `starter/check_reply.py`), and whether a refund reply states the refund amount.

Score yourself on the training labels at any time:

```bash
python scoring/score.py submissions/<team>/predictions.csv data/labels_train.csv --details details.csv
```

`--details` writes one line per complaint showing which fields were wrong.

## Final ranking

| Weight | Criterion |
|---|---|
| 30% | Leaderboard score on the test set |
| 25% | Live round: **hidden test (15)**, 20 unseen complaints sent to your API and scored automatically (score × 0.15); **human gate (10)**, judges watch 3 complaints end to end (routing, approvals that hold, fraud queue, self-check) |
| 25% | Business value and demo: reply quality (tone, correct language, no invented facts), clarity, would a bank use it |
| 20% | Engineering: architecture, observability (show why it decided), cost and speed per complaint |

### The live round

Both parts go through your API ([`api.md`](api.md)).

**Hidden test (15 points).** Right after the 15:00 freeze, `scoring/api_check.py` sends 20 complaints you haven't seen to your API, all at once, and scores them with the same per-complaint points and critical-error rule as the leaderboard; your hidden-test points are that score × 0.15. The complaints are about customers and transactions already in the data, written the way real customers write (typos, SMS short forms, emoji, mixed language), each with its own `received_at`. A complaint that isn't `done` within 120 seconds scores 0. The script also checks that each case's `case_state` and `sent` match its route, runs robustness probes (health check, unknown case, missing text, unknown customer, the same complaint twice) and human-in-the-loop probes (a case waiting for approval holds, an edited reply with an invented amount is refused, an approval is recorded without changing the agent's decision), and times each complaint; those results go to the judges for the engineering score. Run it on yourself: `python scoring/api_check.py http://localhost:8000`.

**Human gate (10 points).** In your demo (from 16:30), the judges send 3 more complaints, one at a time, and tick a checklist for each: the case appears on its own; the right transaction, decision and refund; the right route; a case needing approval waits until someone approves it in your system; a fraud case lands in the fraud queue; the reply is in the right language and consistent with the decision; the self-check result is visible. Through the API we also check that a case waiting for approval shows `case_state: awaiting_approval` and `sent: false` until it is approved ([`api.md`](api.md#case-states-human-in-the-loop)). Your points are the share of checks passed × 10.
