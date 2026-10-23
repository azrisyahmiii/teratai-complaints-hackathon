# HOWTO: two devs, two laptops, one Claude Code session each

> **Current team allocation:** use [CURRENT-WORK.md](CURRENT-WORK.md) for Azri, Leon and Asyraf.
> It supersedes this historical two-dev workflow and its ownership/branch instructions for new work.

Read in this order: [contracts.md](contracts.md) (shared models, file ownership, ports), then your own task file:
[core.md](core.md) (Dev A) or [platform.md](platform.md) (Dev B). Each dev has one lead session that plans and merges, and
**builder** subagents that each build one task in an isolated git worktree. A **reviewer** checks every wave.
Times follow SPEC §15; merge points are in contracts §7.

## Together (P4a, D1 10:00–10:30, on Dev B's laptop, Dev A watching)
First merge this docs branch into `main` (`git switch main && git merge --no-ff docs/dev-plan && git push`), then run:
```text
Implement @docs/dev/tasks/contracts.md on main, nothing else: models.py, the §2 stage stubs returning the CMP-00165
gold answer, pipeline.process_complaint/store, tests/test_contracts.py, a minimal api/main.py + schemas.py +
dump_openapi.py, the §5 packages, the gen:api script and web/lib/api/client.ts, and backend/var/ in .gitignore.
Verify: `cd backend && uv run pytest tests/test_contracts.py -q` passes, mypy + ruff clean, then
`uv run python -m teratai.api.dump_openapi ../web/lib/api/openapi.json && cd ../web && npm run gen:api && npm run typecheck`.
Commit to main "contracts: models, stubs, packages, api types", push, paste Verified: lines.
```
Both devs read the diff before the push. From now on `models.py` changes only via a joint `contracts: …` commit.

## Dev A (Core)
```bash
git switch main && git pull && git switch -c feat/core && git push -u origin feat/core
CLAUDE_CODE_SUBAGENT_MODEL=sonnet claude --model opusplan        # PowerShell: $env:CLAUDE_CODE_SUBAGENT_MODEL='sonnet'; claude --model opusplan
```
```text
Build @docs/dev/tasks/core.md wave by wave with builder subagents (isolation: worktree, ≤3 at once, one task each).
Give each builder its task row, the "How to build" block, and its port + -s name from @docs/dev/tasks/contracts.md §6.
Edit only Core-owned files (contracts §4); put contract or package needs in your report, never edit them.
After each wave: merge the worktree branches into feat/core, rerun every Done check, then the reviewer subagent on the
wave diff (spec gaps only). Fix, commit, push. Stop and tell me at each merge point in contracts §7.
```
**At the merge points:** **CP1** push `feat/core` with the first train score (C8) and tell Dev B, then build C9 (safety net)
the same evening. **Stand-up:** `git merge origin/main` into `feat/core`, then rerun `uv run pytest -q`. **CP2:** push
C10 (and C11/C12 if green); B merges and runs the 50-case check. Then C13 (final run, PR) and C16 if time allows.
**Freeze 13:30:** only fixes for critical errors (C13 must be done); open the PR by 14:30.

Steering one-liners:
- `Status of each builder with evidence. Kill any stuck >10 min.`
- `Score dropped: run score.py --details, bucket misses by category × reason, fix the top bucket only, failing test first.`
- `Re-baseline: what does this add in minutes vs @docs/dev/DEMO.md? Keep or cut.`

## Dev B (Platform, integrator)
```bash
git switch main && git pull && git switch -c feat/platform && git push -u origin feat/platform
CLAUDE_CODE_SUBAGENT_MODEL=sonnet claude --model opusplan
```
```text
Build @docs/dev/tasks/platform.md wave by wave with builder subagents (isolation: worktree, ≤3 at once, one task each).
P1 (walking skeleton) runs first and ends with a screenshot I can see; then W1's other tasks; then the later waves.
Give each builder its task row, the "How to build" block, and its port + -s name from @docs/dev/tasks/contracts.md §6.
Edit only Platform-owned files. After each wave: merge into feat/platform, rerun the Done checks, then the reviewer
subagent on the wave diff (spec gaps only). Fix, commit, push. Stop and tell me at each merge point in contracts §7.
```
**At the merge points:** **CP1** run the integration below and show LIVE-07 → case page. **Stand-up:** integrate, then
both devs merge `main`. **CP2** integrate, run P10, then start the bonus waves (W5+). Tell Dev A when P15 is merged, so
A can take `web/app/fraud/**`. **Freeze:** integrate one last time, run the DEMO §7 check, then P18.

Steering one-liners:
- `Status of each builder with evidence. Kill any stuck >10 min.`
- `Live row failed: reproduce with curl --data-binary, add a failing test in tests/platform first, then fix.`
- `Screenshot the DEMO.md path at 1280x720 with -s=b0 and list what a judge would trip over.`

## Integration (Dev B, at every merge point)
```text
Integrate into main, one branch at a time: main (contracts) → origin/feat/core → origin/feat/platform.
After each merge: cd backend && uv sync && uv run pytest -q && uv run mypy src && uv run ruff check; then regenerate the
TS types (contracts §3) and cd web && npm run typecheck && npm run lint && npm run build. Stop at the first failure and
say which branch broke it. Then run the @docs/dev/DEMO.md §7 end-to-end check, paste the 4 scripted rows with
playwright-cli -s=b0, inspect the screenshots, push main, and paste Verified: lines.
```
Conflicts should not happen, because the globs are disjoint. If one does, the file's owner resolves it. Lock files
(`uv.lock`, `package-lock.json`) only change on B's side, from package requests in A's reports.

## BA hand-offs
| When | To | Deliverable (all in `eval/`, BA-owned) |
|---|---|---|
| D1 09:00 | organisers | GitHub issues for the still-open §18 questions |
| D1 11:00 | A | baseline score: `python starter/baseline.py` + `scoring/score.py` output, as the bar C8 must beat |
| D1 12:00 | A | `date_phrases.csv`: 30 phrases from the data with `received_at` and the expected window (C2) |
| D1 12:00 | B | `live07.csv` (the README row), `scripted_rows.csv` (the 4 DEMO rows), `live_kit.md` (10 `LIVE-xx` rows, 30 Sep) |
| D1 13:00 | A | `regulatory_facts.md`: 997 / FMOS / BNMLINK verified, each with its source URL (feeds the C7 allow-list) |
| D1 13:00 | A, B | `adversarial.jsonl` (30 cases: injection, wrong customer, gibberish, phone numbers) for C7, P1 and P8 tests |
| D1 16:00 | A | `error_buckets.md`: ranked bug list from `score.py --details` (after C8) |
| D1 17:00 | A | `template_wording.md`: EN/MS text per category × outcome; A pastes it into `templates/` (C7) |
| D1 evening | A | review of 20 replies (MS register, §4.6) |
| D2 09:15 | B | `live_kit_log.md`: failures from pasting the live kit through the UI |
| D2 10:00 | B | `cp2_ids.csv` (50 train IDs, all categories) and `seed_spec.md` (~30 demo cases across all queues) for P10/P11 |
| D2 12:00+ | all | 10 test replies reviewed, DEMO.md numbers filled in (score, cost, latency), pitch, demo rehearsed ×2 |
