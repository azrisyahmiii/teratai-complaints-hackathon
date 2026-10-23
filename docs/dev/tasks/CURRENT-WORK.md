# Current allocation: Azri, Leon and Asyraf

This allocation supersedes the old Dev A/Dev B ownership, waves and branch instructions in
`core.md`, `platform.md`, `contracts.md` section 4 and `HOWTO.md`. Keep their functional requirements
as reference, but use the file boundaries and handoffs below for new work.

## Start from one integrated baseline

Asyraf is the integrator. At this review, `feat/platform` contains login/design commit `4ef2b80`,
but is 23 commits behind `main`. First integrate the latest `main` into the platform work, preserving
the authenticated staff API, role-scoped queries and UI, plus main's C20 safety fixes, loader warm-up
and final predictions. Run backend tests and frontend checks, then publish that common baseline.
These counts are a snapshot; fetch and recheck before merging. Do not reset, force-push or overwrite
another person's uncommitted changes.

Azri may continue existing work in his current branch. Before integration, bring in the common
baseline and resolve only his owned files. Leon starts his feature branch from that baseline.
Use separate clones or worktrees; never switch branches in a checkout another person is editing.
Suggested new branch names: `codex/azri-ops-workflow` and `codex/leon-insights`. Existing active
branches can keep their names. Asyraf continues integrating through `feat/platform`.

## Deliverables

| Person | Work | Done means |
|---|---|---|
| **Azri** | Fraud acknowledgements, investigation/recall logs and outcomes; explicit manager escalation; audit history and agent-versus-human comparison | Azri's account can act only on fraud cases. Leon's over-limit/sensitive cases escalate with a reason and remain unsent. Asyraf can see the escalation, approve/reject it, and see the full history. Every action records the session ID; agent decisions and predictions stay unchanged. |
| **Leon** | Read-only insights: metrics API and dashboard | Role-scoped backlog, outcomes, refund totals, approval turnaround, latency/cost and guardrail figures come from stored cases/events. Date/category/channel filters work. Officer/fraud users cannot infer the other team's figures; manager sees both. Missing measurements display as unavailable, not invented zeroes. |
| **Asyraf** | Baseline integration; SLA and assignment helpers; shared wiring; final verification and demo readiness | Latest main and platform work coexist. SLA helpers handle business days and the documented holiday calendar; assignment respects role/availability. Feature routers and navigation are wired once, API types regenerated, organiser API checker and live/offline demo paths checked, and network reachability tested from another laptop. |

Leon builds the dashboard first; no AI chat or new chart library is required. Azri keeps the
log/escalation work already underway. Asyraf prioritises integration and verification over new UI
features. Structured intake/customer picker, SSE, smart routing and notifications come afterwards.

## Exclusive file ownership

Paths are repository-relative; `T = backend/src/teratai`.

| Owner | Files they may edit |
|---|---|
| **Azri — workflow and persistence** | `T/db.py`, `T/pipeline.py`, `T/api/{auth,routes_agent,routes_ui,states}.py`; new `T/api/{routes_fraud,routes_manager}.py`; optional workflow helpers under `T/ops/workflow*.py`; `backend/tests/platform/{test_auth,test_agent_api,test_ui_api}.py` and new `test_fraud.py`, `test_escalation.py`, `test_workflow_audit.py`; `web/app/{fraud,manager}/**`; `web/components/desk/{case-view,case-parts,case-reply,case-tabs,queues,status-badge}.tsx`; new `web/components/{fraud,manager}/**`; workflow-only `web/lib/workflow*.ts` |
| **Leon — insights only** | New `T/api/routes_metrics.py` (including its response models); `T/ops/metrics.py`; `backend/tests/platform/test_metrics.py`; `web/app/metrics/**`; `web/components/metrics/**`; `docs/dev/tasks/leon-insights.md` |
| **Asyraf — integration and supporting ops** | `T/api/{main,schemas,dump_openapi,routes_export}.py`; `T/{settings,seed}.py`; `T/ops/{sla,holidays_2026,routing}.py`; `backend/tests/platform/{test_sla,test_routing,test_seed,test_export,conftest}.py`; `web/lib/api/**`; `web/components/desk/{sidebar,shell,page-header,staff-account,login-form,intake-form,outbox-list}.tsx`; `web/lib/role.tsx`; `web/app/{layout.tsx,globals.css,login/**,intake/**,outbox/**}`; `web/{proxy.ts,next.config.ts,package.json,package-lock.json}`; Python dependency/lock files; `docs/dev/{AUTH,DESIGN,DEMO,SPEC}.md`; coordination/review documents, README and `eval/**` |

Unlisted existing files are read-only until Asyraf assigns an owner. Existing core decision files,
`T/models.py`, source `data/**`, `starter/**`, `scoring/**` and `submissions/**` are not part of these
feature assignments. Bring in their upstream changes through integration; do not regenerate or
change prediction files as part of a dashboard or workflow task.

Only Asyraf edits `api/main.py`, navigation, global CSS, dependency manifests/locks and generated
OpenAPI/TypeScript files. Azri owns mutations and schema migrations in `db.py`; Leon must not add
tables or change workflow state. Existing tests and fixtures keep one owner, as listed above.
Feature-specific styles belong in the owner's component or CSS module; request shared theme
changes from Asyraf instead of editing `globals.css` in parallel.

## Contracts and handoffs

1. **Agree the public shapes early.** Azri publishes workflow request/response models and event
   names; Leon publishes the metrics response models in his own router. Asyraf registers these
   routers and regenerates `web/lib/api/*` in one small integration commit. Everyone updates to
   that commit before frontend code uses the new endpoints. Never hand-write generated types.
2. **Keep the current access boundary.** Reuse `auth.User`/`MutationUser`, `require_case`,
   `require_run` and `case_scope`. Metrics SQL uses case alias `c` for the shared row predicate.
   Azri preserves these helper interfaces while adding workflow permissions. Any breaking change
   waits for an agreed integration commit; do not silently change the metrics dependency.
3. **Do not replace the organiser API.** Its credential-free contract remains as specified in
   `docs/api.md`; staff actions stay authenticated under `/api`. Role/limit checks are enforced
   server-side, and the actor always comes from the session. Reuse the existing money and
   self-check logic. An escalation must never send a reply or overwrite `agent_decision`.
4. **One writer for audit events.** Azri publishes the final event vocabulary and payload keys
   for acknowledgement, investigation, outcome, escalation and final approval/rejection, including
   actor, reason, time and old/new values. Leon reads those events; he does not add logging to
   `pipeline.py`, `db.py` or action endpoints. Initial metrics can use today's fields while the
   richer event contract lands.
5. **SLA/assignment are additive.** Asyraf publishes and tests pure helper signatures and any
   configuration defaults first. Azri alone wires them into write-back/workflow code and owns
   migrations for persisted fields. Leon consumes the agreed fields/helpers after that handoff;
   until then, omit unavailable metrics. Do not independently implement SLA calculations twice.
6. **One schema migration owner.** Use additive SQLite migrations, retain existing users,
   sessions/cases and agent decisions, and test upgrade from the pre-change schema. Leon and
   Asyraf send field requirements to Azri; they do not each patch `db.py`.

## Merge and verification sequence

1. Asyraf publishes the integrated baseline and shared API/type contracts.
2. In parallel: Azri completes workflow/log/escalation; Leon completes metrics using existing
   records; Asyraf completes SLA/assignment helpers and the demo/checklist work.
3. Asyraf integrates Azri's workflow first. Azri resolves any workflow conflicts and wires the
   agreed SLA/assignment helpers. Verify role isolation, the manager hold and unchanged exports.
4. Leon updates metrics to the final event/field contract in his own files, then Asyraf integrates
   insights and registers its navigation. Do not count an escalated case twice in backlog or money.
5. Asyraf regenerates types, runs the full backend suite, frontend typecheck/lint/build and
   organiser API checker, then rehearses all three staff accounts and the wrong-amount edit demo.
   Test reachability from another laptop. Record any remaining typecheck/environment failures.

Each handoff lists the commit, exact files changed, endpoint/event contract changes, checks run
and anything deferred. No one fixes another owner's file opportunistically. If a shared change
is essential, send its requested diff/contract to the owner and wait for that integration commit.
This document allocates human work only; it does not dispatch agents or message other chats.
