# Teratai Bank complaints agent

Spec: @docs/dev/SPEC.md · Demo path: @docs/dev/DEMO.md · Data: docs/data_dictionary.md

## Commands
- Web (Next 16, shadcn base-nova, ESM): `cd web && npm run dev | build | start | typecheck | lint`; add UI: `npx shadcn@latest add <component>`
- Backend (uv, Python 3.11, package at `backend/src/teratai/`): `cd backend && uv run pytest -q`, `uv run mypy src`, `uv run ruff check`, `uv add <pkg>`
- API dev server: `cd backend && uv run fastapi dev src/teratai/api/main.py` (port 8000)
- Score: `python scoring/score.py <predictions.csv> data/labels_train.csv --details details.csv`
- Starter oracle: `python starter/evidence_pack.py CMP-00244`, `python starter/check_reply.py CMP-00244 "<reply>"`
- Docs: `npx ctx7@latest library <Name> "<question>"` → `npx ctx7@latest docs /org/project "<question>"` (≤3 calls per question)
- Browser: `playwright-cli -s=<your-session> open <url>`, then `snapshot`, `click <ref>`, `fill <ref> <text>`,
  `screenshot --filename=shots/<name>.png`, `close`. Always pass your own `-s=<name>`. Never `close-all` / `kill-all`
  (other agents share the machine). Redirect output to a file and `cat` it (`> "$TEMP/pw-<name>.txt" 2>&1 < /dev/null`).
- Stop hook (`.claude/hooks/check.sh`) runs typecheck + lint on changed web/ and backend/ and blocks until they pass.

## Rules
1. **Verify APIs before using them:** typings first (`web/node_modules/**/*.d.ts`, `backend/.venv/Lib/site-packages`),
   then ctx7, then a tiny probe (script, curl, REPL) that you run. Never code an SDK call from memory.
   Next 16 differs from training data: read `web/node_modules/next/dist/docs/` for the feature you touch.
2. **Done = evidence.** Paste the command output (test, build, curl), or a screenshot you opened and inspected.
   "Should work" is not done. End reports with `Verified:` lines naming the command and its result.
3. **Build only what DEMO.md touches.** Anything else: ask first, or note it as cut.
4. **LLM does language, code does money and rules.** The LLM never sets outcome, refund, route or priority.
   Money is `Decimal`, never float.
5. Never edit `starter/`, `scoring/`, `data/`. `predictions.csv` comes from the immutable `agent_decision`.
6. Models: `claude-haiku-5-5` (extract, investigator), `claude-sonnet-5-5` (replies). Keys in `.env` only; never commit secrets.
7. Scaffolder defaults, no exotic packages. Match the surrounding code style.
