# Staff sign-in and access

Use the generated lotus pavilion as the login background, with the ivory sign-in panel and berry action from the preview.
The working platform keeps the forest-green navigation. Replace the local role switcher with session identity and logout
in the top-right staff bar. Do not display complaint content until the server validates the session.

| ID | Role | Staff access |
|---|---|---|
| asyraf | Manager | Both teams, all runs, prediction export, approvals above the officer limit |
| leon | Complaints officer | General complaints and their resolved history; approval up to RM2,000 |
| azri | Fraud analyst | Fraud cases and their holding replies, evidence and audit history |
| vincent | Complaints officer | Same general-complaints access and RM2,000 approval limit as leon |
| nishan | Fraud analyst | Same fraud access as azri |

The requested local demonstration password is `000000` for all five users. Passwords are bcrypt hashes in SQLite;
the browser receives an opaque, expiring HttpOnly session cookie, not a role it can change. Logout revokes the session.
Seed users once without resetting existing passwords. Use Secure cookies when `AUTH_COOKIE_SECURE=1` behind HTTPS.
Profile pictures use the supplied, matching filenames under `web/public/images/profiles/` and appear beside the
signed-in ID and role. These are static demo assets; users without a supplied picture keep the initial avatar.

SQLite has no native row-level security. Staff list/detail/check/action/outbox queries share a server-side row predicate
based on the immutable agent route. Pending cases are visible only to their submitter and the manager. Once decided,
the responsible team owns access. Counts and figures use only permitted rows, including after approval. Only the
manager may read non-live runs or export predictions. An action records the session username, ignoring a claimed actor.
Mutation requests require the same-origin custom header; sessions expire after eight hours. Failed login attempts are
limited to ten per username and source address within five minutes.

Implementation order: authentication/schema and regression tests; shared staff query/action checks; generated OpenAPI
types; login and session guard; identity/logout bar and scoped queues; backend tests and browser checks for all users.

The organiser endpoints (`/complaints`, `/cases/{id}`, `/cases/{id}/actions`, `/health`) deliberately remain credential-free
as mandated by `docs/api.md` and `docs/bonus_platform.md`. The browser uses authenticated `/api` routes instead; its old
`/agent` proxy is removed. These organiser endpoints must be isolated or disabled before using this system outside the
synthetic hackathon environment. The local frontend is not a reverse proxy to that public API.

## Verification and local preview

Verified: 2,461 backend tests passed, one skipped; frontend lint, TypeScript and the production build pass.
Changed backend modules pass mypy. The full-source mypy check still reports existing NumPy `max`/`argmax`
overload errors in `classify.py` with this environment's NumPy version; those files were not changed.
Browser checks exercised all three accounts against the actual backend, role-filtered queues, cross-team `403`s,
manager approval permission, session revocation and responsive login at 1440/768/390px.

The local preview runs at `http://localhost:3100/login`, with the backend bound to `127.0.0.1:8000`.
Four existing synthetic examples were submitted for review: CMP-00165, CMP-00244, CMP-00289 and CMP-00387.
The preview backend uses `EXTRACT_MODE=regex`, `REPLY_MODE=template`, `INVESTIGATOR=off` to avoid paid LLM calls.
Remove those overrides when running the normal live-language pipeline. No source data files were changed.
