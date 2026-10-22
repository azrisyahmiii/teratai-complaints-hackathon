# Workflow: zero-prep, driven entirely by prompts

Claude Code on the Pro plan. Version 3, 2026-10-22. Everything is built after the clock starts, and every step is a prompt you type. For FDE work or events that allow setup, use [workflow.md](workflow.md).

**Fair play (MLH rules):**
- ✅ Before the clock: installed tools, accounts, keys, billing, and knowledge.
- ✅ In-event: official scaffolders, public libraries, AI. Disclose them in the README.
- ❌ No pre-written project code or starter repo.

## How to write prompts that are short and effective

1. **Always include a runnable check:** a test, a build, a probe, or a screenshot. It matters most when you're brief.
2. **Reference files, don't retype them:** `@SPEC.md`, `@DEMO.md`. Standing rules live in **CLAUDE.md**, so prompts stay short.
3. **Use literal verbs:** "implement", "create", "run", not "can you suggest".
4. **Bound everything:** ≤N words, ≤N minutes, "or stop after N turns".
5. **Hand tools to agents explicitly.** Subagents don't inherit your rules or skills, so the setup prompt writes the tool commands into each agent's prompt.

## The prompt pack (3-hour times)

**P1 · Research + interview + spec (0:00–0:12)**
```text
Build <pitch> for <event/customer>. Constraints: 3h, Pro plan, <provider> key only, $<x> budget, local prod build, judged on <rubric>.
First: 2 sonnet subagents web-search (1: what wins/what the buyer needs, 2: best UX + current stack versions), ≤300 words each, cite sources.
Then interview me (AskUserQuestion, ≤5 min, hard parts only). Write SPEC.md + DEMO.md (90s script, wow moment, out-of-scope, end-to-end check). No code yet.
```

**P2 · Setup from zero (0:12–0:27)**
```text
Per @SPEC.md, set up using official scaffolders only (Next + shadcn defaults, ESM). Install @playwright/cli and learn it via --help; docs via `npx ctx7@latest`.
Write CLAUDE.md ≤40 lines: commands + rules: verify APIs (typings → ctx7 → probe); done = pasted output or inspected screenshot; build only what @DEMO.md touches.
Create .claude/agents: builder (sonnet) and reviewer (sonnet, read-only), with those tool commands in their prompts (playwright-cli -s=<name>, never close-all). Add a Stop hook: typecheck + lint. Commit.
```
Then **restart** so the new agents load, with Opus planning and Sonnet executing:
`CLAUDE_CODE_SUBAGENT_MODEL=sonnet claude --model opusplan` (a fresh session also gives you a clean context).

**P3 · Skeleton gate (0:27–0:45)**
```text
/goal a probe makes one real model call through our provider where a tool executes (show tool-call + tool-result), the page returns 200, and npm run build passes — or stop after 15 turns
```

**P4 · Contracts + parallel build (0:45–2:05)**
```text
Split @SPEC.md into 2–3 streams: write types/contracts first, file ownership in task.md, one UI owner. Run them in parallel with the builder subagent. Each reports evidence + Verified: lines.
```

**P5 · Integrate + review (by 2:05, the freeze)**
```text
/goal the @DEMO.md path passes on a production build, with playwright-cli screenshots you inspected — or stop after 20 turns
```
```text
Use the reviewer subagent on the diff vs @SPEC.md: correctness gaps only. Fix criticals. Feature freeze after this.
```

**P6 · Demo prep (2:05–2:50)**
```text
Add a DEMO_MODE=cached fallback for the demo input. Write the README (built during the event vs. tools used, AI disclosure, screenshots). Then give me 6 architecture bullets and the 5 hardest judge questions with answers.
```

**P7 · Judge (2:50–3:00)**
```text
Run 2 read-only judge subagents (hackathon + FDE) with rubric anchors for a 3h prototype; cite file:line or screenshots; rank fixes by gain÷minutes.
```

**P8 · Retro (after the event)**
```text
Append to docs/retro/session-log.md: my prompts verbatim, incidents >10 min with root cause, metrics (time to first live call, demo-ready, $/run). Propose ≤3 CLAUDE.md rules.
```

## Steering one-liners (mid-flight)

| Situation | Type |
|---|---|
| Unsure what agents are doing | `Status of each agent with evidence. Kill any stuck >10 min.` |
| Same bug twice | `/clear`, then `@<file> fix <bug>. Root cause in 3 lines first; failing check first.` |
| Scope creep | `Re-baseline: what does this add in minutes? Keep or cut vs @DEMO.md.` |
| Budget | `/usage` |
| Side question | `/btw <question>` (stays out of history) |

## Rules of thumb

1. **Keys, billing and tools ready beforehand; zero project code.**
2. **Constraints + done criteria in P1.** Cap the interview at 5 minutes.
3. **DEMO.md before code.** Scaffolder defaults; no exotic packages.
4. **Skeleton gate (P3) before any fan-out.**
5. **Docs + execution; done = external evidence.**
6. **2–3 streams, one UI owner, contracts first.**
7. **Pro budget:** Opus plans, Sonnet builds; `/clear` is free, `/compact` is expensive.
8. **Two strikes → `/clear`, narrow, fix by hand, or revert.**
9. **Freeze at 70%; ≥15% on the pitch; disclose AI and tools.**

| Session | Bootstrap (P1–P2) | Scope |
|---|---|---|
| 3 h | 20–30 min | One flow, mocked data, cached fallback |
| 8 h | 30–45 min | 2–3 features, one real integration, an eval number |
| 24 h+ | 45–60 min | Polished POC; deploy in the first hour; freeze at T−4 h |

*Sources:*
- Claude Code docs: best practices, subagents (no skill inheritance), `/goal`, hooks, skills.
- Claude prompting best practices.
- `@playwright/cli` README; MLH rules.
- Unverified: time estimates and stream counts.
