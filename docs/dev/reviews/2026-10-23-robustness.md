# Robustness review: overfitting and the hidden messy test

For Dev A and the BA (Dev B: §6 only). On 2026-10-23, two independent Sonnet reviewers looked at `feat/core` (b6fb0fc):
- A scoring and overfitting expert (high effort).
- A Malaysian-language and prompt red-team (medium effort).

Both ran real complaints through `process_complaint(run_id="live")`. Their scratch sets are in `$TEMP/ev1/` and
`$TEMP/ev2/`. `$TEMP` is not durable: save those sets (§4) before the machine is cleaned. This doc feeds tasks
C17–C19, tracked in [core.md](../tasks/core.md) (context: [brief-changes review](2026-10-23-brief-changes.md)).

## 0. Design decision: the LLM reads, code verifies, code decides
**What is overfit:** reading the customer's free text with hand-written rules, and a classifier trained on templated
text. That covers the amount, approximation, date, payee, fee and language patterns, plus a τ taken from a
template-leaking CV. **What is not overfit:** code on structured data and on our own output. That covers the matcher's
hard filters and scoring, the policy engine in `Decimal`, routing, "never guess → NEEDS_INFO", and the self-check's
`TXN-`/RM patterns. Those stay exactly as they are.

**Decision (changes SPEC §4.2, where the LLM was only a fallback):**
1. **The LLM extracts on every complaint**, in batch and live. Haiku costs about $0.0001 per call and about 1–1.5 s
   (measured), so roughly $0.10 for the 750 test run.
2. **The LLM is the primary reader. Code verifies each value against the original text** (verbatim span, a derivable
   amount, a closed date vocabulary, a payee that fuzzy-matches a real candidate). A value that fails verification falls
   back to the deterministic reader.
3. **The deterministic reader stays as the verifier and the outage fallback.** It is generalised (amount grammar,
   approx class, clue-only normaliser), not grown string by string.
4. **Category:** the LLM is primary, with the classifier as a cheap second opinion. Agreement → accept. Disagreement →
   scam precedence plus the safe defaults, and a flag.
5. **Unchanged:** txn selection, policy, refund, route, priority, the self-check. The LLM never decides money, so a
   misread can only lead to NEEDS_INFO, never a refund (0 criticals on 109 messy rows).

**Ship gate:** train and test-style data stay at 100.00 / 0 critical (the leaderboard set is templated, so measure,
don't assume), and messy-dev rises from about 85.6 to ≥ 92 with 0 criticals. Total measurement cost is under $1.
If LLM-first ever loses on templated rows, the agree/disagree hybrid (item 4) protects the leaderboard.

## 1. Verdict
**The 100.00 train score is real, but it measures template recall, not language understanding.** On messy text we
are good but not leading.

| Measure | Result | Status |
|---|---|---|
| Train texts distinct after masking amounts and names | 1,563 / 1,750 (89%); 1,550 distinct sentences among 4,036 | CONFIRMED |
| Test texts identical to a train text after masking | 146 / 750 (19.5%). Mean test 4-gram coverage by train is 0.93, and 61% of test texts are fully covered | CONFIRMED |
| Classifier, stratified 5-fold (our "OOF 1.0000") | 1.0000, min confidence 0.7945 (that minimum *is* τ) | CONFIRMED, leaks templates across folds |
| Classifier, **group-K-fold by template cluster** | 0.990 at cosine 0.9 (780 clusters); 0.905 at 0.7 (149 coarse clusters, pessimistic). Honest range ≈ 90–99% | CONFIRMED |
| **Messy set, live mode** | Expert: 61 rows, 86.4 (88.0 and 83.7). Red team: 46 rows, 84.5. **Pooled ≈ 85.6 → about 12.8 of the 15 hidden-test points** | CONFIRMED |
| Criticals on messy text | **0 / 109**. Every lost txn fell to DECLINE or INVESTIGATE, never a wrong refund | CONFIRMED |
| Category / priority on messy text | 109 / 109 | CONFIRMED (category is not the weak point) |
| Spread at n = 20 | About ±8 points on the mean (one lost txn costs 75 points). Plausible hidden-test range 76–93 | PLAUSIBLE |

**What this means against strong teams.** The leaderboard (30%) is a likely tie zone, because the organisers' build
guide recommends the same design. The 15-point hidden test is where an LLM-first team that normalises messy text can
beat us. Moving from 85.6 to about 92 is worth roughly 1 point of the total score. **Even so, the API and the human gate
(Dev B) still come first:** without them, 25% of the total can't reach us (see [brief-changes review](2026-10-23-brief-changes.md) §3).

## 2. Where the points go: lost txn = 75 points each
| Root cause | Share of misses | Example → effect | Component |
|---|---|---|---|
| **`k` / spaced / word amounts** | Largest | `rm4.4k` → 4.4, `rm1.5k` → 1.5, `RM 1 500` → 1, `3 967.30` → 3, `seribu lima ratus` → none, `46.66myr` → none | `extract._AMOUNT` |
| **Approximation short forms** | ~3 per 60 | `abt`, `lbh krg`, `lebih krg`, `kira2`, `ard`, `dlm`, `~RM` read as exact, so the exact-amount hard filter drops the txn (CMP-00387) | `extract._APPROX_BEFORE` |
| **LLM counterparty vetoes a correct match** | Biggest red-team loss | Typos (`gamevalt` vs GameVault), spacing (`Go Ride` vs GoRide), an account number taken as a name (`akaun 9576`, `akaun berakhir 1548`) → `counterparty_mismatch` → AMBIGUOUS. Batch mode (regex only) matched the same rows | `match._party_mismatch`, `extract.merge_issue` |
| **SMS date forms unparsed** | Silent | `smlm`, `kmrn`, `lps`, `jmt lps`, `last sat`, `lst fri`, `2 hari lps`, `minggu lps`, `15hb`, `2 weeks ago` → None → 45-day window. Exact-day scoring is lost and duplicates go AMBIGUOUS. The LLM returns `selasa lps` verbatim, and `resolve_window` can't parse it | `dates.py` |
| **Disputed vs other amount** | Occasional | "baki RM1,200 tp kena caj RM46.66" → picks 1,200 (the first amount) | `extract.disputed_amount` |
| **SMS-Malay language** | 5 points each | `hai mesin cdm kt cawangan sg petani dh rosak` → 0 MS hits → MIXED → preferred language. `MINORITY_SHARE = 0.05` makes one English word = MIXED. A naive SMS word list broke 14 / 1,397 train labels | `lang.py` |
| Batch hides LLM behaviour | — | Batch 90.0 vs live 88.0 on the same rows | eval method |

## 3. Overfit components: fitted to train wording
| Component | Fitted how | Generalisation risk |
|---|---|---|
| `classify` τ = 0.7945 | The minimum of in-template CV, not a calibrated value | Messy confidences ran 0.44–0.98. Recalibrate τ from group-K-fold |
| `extract._APPROX_BEFORE`, `_AMOUNT` | Built from training phrasings | Short forms and `k` forms fail (§2) |
| `config.AMOUNT_APPROX_MIN_MYR = 25` | Fitted to 12 train cases | `k`-rounded amounts ("3.2k") can exceed 5% or RM25 |
| `lang.MS_WORDS`, `MIN_HITS = 2`, `MINORITY_SHARE = 0.05`, `LOANWORDS` | Tuned on formal templated Malay | SMS Malay scores 0 hits |
| `dates.py` phrase rules | Built from train phrases, tested on fixed dates | No SMS forms |
| `classify.SCAM_CUES`, `_COMPLAINT_MARKER` | EN + formal MS | `x` = tidak is missing (category held up anyway) |

## 4. Harness change: make the eval honest before tuning (C17)
1. **Two sets, generator ≠ tuner.**
   - **Dev set:** the 109 reviewer rows (`$TEMP/ev1/messy*.csv`, `$TEMP/ev2/redteam*.csv`, with labels). They were written by agents who had read the code, so they are adversarial, and fine for tuning. Save them now as `backend/tests/core/fixtures/messy_dev.csv` (+ labels).
   - **Hold-out:** 40–60 rows generated blind. Sonnet, given only a style card (§5.4) and the gold facts, never the code. The BA reviews them for realism and for the `reply_language` label. Save as `eval/messy_holdout.csv`. **Nobody tunes against it.** Score it at CP2 and again at freeze, and report it once.
2. **Run in live mode** (`run_id="live"`), the hidden test's path, scored by `scoring/api_check.py --complaints … --labels … --all` once Dev B's API is up. Until then, use a local runner that applies `score.py`'s field rules.
3. **Report with uncertainty:** the mean with a bootstrap 95% interval. Gate on n ≥ 100 (dev) and the hold-out, never on 20 rows.
4. **Keep the honest classifier number** next to the 100.00: group-K-fold accuracy at cosine 0.9.
5. **Regression gates for every C18 change:** train 100.00 / 0 critical, matcher 1750/1750, train language 1750/1750, messy-dev ≥ the previous best, **0 criticals on messy**.

## 5. Generalise by mechanism, not by adding the red-team's words
Adding each failing string to a list just overfits to the red-team set. Prefer mechanisms that cover a whole class of
inputs, and test each with a pattern grid (unit tests over generated variants), not only the reviewer rows.

### 5.1 Code (deterministic, money stays here)
1. **Amount grammar** (`extract._AMOUNT` + `_amount_of`):
   - `k` suffix (×1000).
   - Thousands written with spaces or dots (`1 500`, `RM1.500` when 3 digits follow), and `myr` glued to the number.
   - `N ringgit`, and Malay and English number words (`seribu lima ratus`, `one thousand five hundred`).
   - A guard: a number below 10 with `k` is never taken literally.
   - Grid test: 6 amounts × 8 surface forms.
2. **Approx markers as a class:** `abt`, `about`, `around`, `ard`, `approx`, `~`, `lebih kurang` / `lbh krg` / `lebih krg`, `kira-kira` / `kira2`, `dlm`/`dalam`, `sekitar`, `in the region of`. For `k`-rounded amounts, widen the tolerance to the rounding unit (half a step of the precision given), not a fixed RM25.
3. **Disputed-amount choice:** skip amounts in a balance, total, limit or expected clause (`baki`, `balance`, `jumlah`, `total`, `limit`, `had`, `sepatutnya`, `should be`). If two remain, prefer the one beside the charge, deduct or transfer verb (`caj`, `charged`, `potong`, `tolak`, `deducted`, `trf`, `transfer`, `withdraw`).
4. **Counterparty: a soft signal, never a veto by default.** Compare without spaces or case, using an edit-distance ratio ≥ 0.8 on the alphanumeric squash (catches `gamevalt` and `Go Ride`). Never treat a span that is mostly digits, an account phrase (`akaun|acc|account … NNNN`) or a date word as a name. Veto only on a **clear person-name mismatch** for transfers (two-token human name, distance ratio < 0.5). Otherwise it's a missing +3, not AMBIGUOUS.
5. **Clue normaliser** (`extract.normalise(text) -> str`, new). A small dictionary of established SMS-Malay and Manglish forms (`x`/`tk` → tak, `sy` → saya, `kt`/`kat` → di, `dh` → dah, `tp` → tapi, `utk` → untuk, `dgn` → dengan, `lps` → lepas, `smlm` → semalam, `kmrn` → kelmarin, `jmt` → jumaat, `hr` → hari, `mgu`/`mgg` → minggu, `td` → tadi, `abt` → about, `ytd`/`yday` → yesterday, `lst` → last, `tq` → terima kasih), weekday abbreviations, and digit-letter splits. Used only for clue extraction, date parsing and language counting. **The stored complaint text is never altered**, and the `verbatim()` span checks still run against the original text.
6. **`lang.py`:** count MS hits on the normalised text. Replace `MINORITY_SHARE = 0.05` with a minimum count of minority-language function words (e.g. ≥ 2 EN function words, not ≥ 5% of hits), so one English loanword doesn't make the text MIXED. Must keep train at 1750/1750.
7. **`dates.py`:** parse the normalised text. Add the general relative forms `N hari/days/minggu/weeks lepas/ago`, `Nhb` (day of month) and `last <weekday abbrev>`.
8. **τ recalibration:** choose τ from group-K-fold OOF so accepted items are ≥ 99% accurate under held-out templates. Expect a higher τ, so more rows go to the LLM in batch. The cost is small, because there are about 0 LLM rows today.

### 5.2 Let the LLM lean in on language. Code still verifies, and the LLM still never decides money.
| Signal | Today | Change | Code check that keeps it safe |
|---|---|---|---|
| Amount | Regex wins if present | LLM returns `amount_text` (verbatim) and `amount_value`. **The LLM wins when the regex value comes from a `k`/space/word form, or sits in a balance/total clause** | `amount_text` must be verbatim in the original text, and `amount_value` must be derivable from it (digits, ×1000 for `k`, number words). Otherwise keep regex |
| Date | Verbatim `date_phrase` only | Add `date_phrase_normalised` in a **closed canonical vocabulary**: `today`, `yesterday`, `day before yesterday`, `N days ago`, `last <weekday>`, `this <weekday>`, `last week`, `this week`, `last month`, `<D> <Month> [YYYY]`. `resolve_window` parses only that vocabulary | The verbatim span must exist in the text. A canonical form that can't be parsed falls back to code parsing |
| Counterparty | Verbatim span, which can veto | Name only. The prompt says never an account number or date word. The span becomes a soft signal (§5.1.4) | Verbatim, plus the fuzzy match against candidates |
| Language | Ignored (code only) | `language_guess` ∈ {EN, MS, MIXED}. **Tie-break only** when the code detector says MIXED on short text (< 25 words) and it's not a call-centre note | The policy rule still decides: mixed or staff note → `preferred_language` |
| Other amounts | — | `other_amounts: [{amount_text, role: balance|total|expected|other}]` | Used only to exclude amounts from the disputed-amount choice |
| Category | Classifier unless conf < τ | Unchanged mechanism, with the recalibrated τ (§5.1.8) | Scam precedence and policy stay in code |

### 5.3 Prompt changes
**`extract.llm_issue`** (bump `PROMPT_VERSION`, re-record `fixtures/extract_llm_cache.json`):
- Add: "Complaints are often SMS-style Malay or Manglish with typos and emoji. Read `x`/`tak` as not, `sy` as saya, `kt` as di, `lps` as lepas, `smlm` as semalam, `jmt` as Jumaat, `abt`/`dlm`/`lebih krg` as about. `k` means thousand, and Malay number words are amounts. Interpret them, but copy spans verbatim."
- Add: "`counterparty` is a merchant or person name only, never an account or card number, a date, or a channel word."
- Add: "Return `date_phrase_normalised` using only this vocabulary: … If unsure, return null."
- Add the new fields `amount_text`, `amount_value`, `other_amounts`, `language_guess`, keeping all existing ones.
- Add 3 short few-shots in a neutral style: one SMS Malay, one Manglish, one with a balance amount. **Write them from the style card, not copied from the dev or hold-out rows.**

**`investigate`:** "Merchant and person names may be misspelt or spaced differently. Compare ignoring case, spaces and small typos. Never pick a transaction whose amount and payee both differ from the complaint."

**`reply.SYSTEM_PROMPT`:** no change needed (0 reply failures in 109 rows). Re-record only if the fact sheet changes.

### 5.4 Style card for the blind hold-out generator (C17)
Real Malaysian customer writing:
- SMS Malay short forms, Manglish particles (`lah`, `liao`, `wor`, `meh`), and EN/MS code-switching mid-sentence.
- ALL CAPS rants, emoji-only emphasis, missing punctuation, typos in merchant names.
- Amount forms: `k`, spaces, words, no `RM`, glued `myr`.
- Relative dates in either language, very short complaints (≤ 12 words), two amounts with only one disputed, staff notes in third person (EN or MS).
- Keep the customer, `received_at` and the facts of the source complaint. Never invent a transaction.

## 6. Unknown-unknowns to cover in the hold-out (and in Dev B's demo rehearsal)
- Two amounts (balance, expected, or a duplicate's total).
- "Isteri/wife's card" vs "my card". Third-person Malay staff notes.
- Date ranges ("between Mon and Wed"). A 20-word complaint naming only the merchant.
- An amount off by a small typo (`46.6` for 46.66). An account-number payee.
- A customer naming a different channel from the txn ("transfer" for a card payment). Two issues in one complaint.

## 7. Plan and order (fold into C18)
| # | Change | Points / effort | Files |
|---|---|---|---|
| 0 | **LLM-first extraction on every complaint** (§0): extract always, LLM-primary merge with code verification, LLM-primary category with the classifier as a cross-check, prompt upgrade (§5.3) | High / medium | `extract.py`, `classify.py`, `config.py`, fixtures |
| 1 | Counterparty soft signal + fuzzy match; no account or date spans as names | High / low | `match.py`, `extract.py` |
| 2 | Amount grammar (`k`, spaces, words, `myr`) + approx-marker class + rounding-unit tolerance | High / low | `extract.py`, `config.py` |
| 3 | `date_phrase_normalised` (LLM, closed vocabulary) + parser for it, plus SMS date forms via the normaliser | High / low–medium | `extract.py`, `dates.py` |
| 4 | Clue normaliser (dict), used by amounts, dates and language only | High / medium | `extract.py`, `lang.py`, `dates.py` |
| 5 | Disputed-amount choice (role words + LLM `other_amounts`) | Medium / low | `extract.py` |
| 6 | Language: normalised counting, minority-count rule, LLM tie-break on short MIXED text | Small (5 pts each) / low | `lang.py`, `classify.py` |
| 7 | τ from group-K-fold; report the honest classifier number | Small / low | `classify.py` |
| 8 | Prompt updates (§5.3) + re-record fixtures | Supports #1–#6 | `extract.py`, `investigate.py`, fixtures |

Done check for C18: messy-dev (109 rows, live) ≥ 92 with 0 criticals; blind hold-out reported once at CP2 and at
freeze; every gate in §4.5 still green. Budget: about US$1 of live calls across the dev runs.
