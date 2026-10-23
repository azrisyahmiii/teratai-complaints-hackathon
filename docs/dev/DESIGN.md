# DESIGN: how the Teratai complaints desk looks and reads

## Current visual direction (2026-10-23)

The requested lotus-bank theme for the frontend redesign supersedes the original visual tokens below.
The working screens retain their human approval confirmations and self-checks behind authenticated staff APIs.
Use forest green `#123D30` for navigation, warm ivory `#F5F3EE` for the workspace, pale stone panels
`#FFFEFB`, champagne gold for restrained identity details, and the existing berry `#8A1F5C` for actions.
Keep semantic status colours and labels distinct. IBM Plex remains the working font; a restrained serif
appears only in the queue introduction and sidebar brand message. Use the generated lotus pavilion
(`web/public/images/teratai-pavilion.webp`) as contextual imagery, never behind case evidence or reply text.
Motion is a short page entrance and control/row transitions, disabled for reduced-motion preferences.
On small screens the sidebar becomes a compact navigation bar; wide evidence tables scroll within their panels.
The top-right staff bar shows the signed-in ID, role and logout. There is no role selector;
the server scopes every staff read and action. See [AUTH.md](AUTH.md) for accounts and access rules.

Image provenance: generated with the built-in ImageGen tool, then resized to a 1600px WebP (245 KB)
with the existing Sharp dependency. Prompt: "Photorealistic architectural photograph of a lotus-inspired
Malaysian bank pavilion in pale travertine, glass and brass, overlooking a calm reflecting pool with
lotus flowers, tropical greenery and a subtle Kuala Lumpur skyline at sunrise. Warm champagne gold
light and forest green shadows; building on the right, dark negative space on the left. No text,
logos, money or UI." No new runtime dependencies are required.

The original specification below is retained as context; current CSS variables are the source of truth for colour and radius.

Read this before building or changing any screen in `web/`. It applies to every role (officer, fraud analyst, manager)
and to the demo screens. The audience is a bank's back office: people who process dozens of cases a shift and must be
able to defend every decision. The design should feel like a well-run banking system, not a startup landing page.

Mockups: the "Teratai complaints platform screens" design canvas (claude.ai). This file wins where they differ.

## 1. Principles
1. **Precision over decoration.** Every value is exact, labelled and formatted the same way everywhere.
2. **Records are never erased.** Nothing is crossed out, hidden or overwritten on screen. A change shows both values,
   labelled *From* and *To*, with who changed it, when and why.
3. **Colour means something, or it isn't used.** Neutral greys for structure; colour only for status (priority, case
   state, self-check). At most two coloured badges per row.
4. **Readable without colour.** Every status also has a word (and an icon where it helps). Never colour alone.
5. **Dense, scannable, calm.** Tables over cards, compact rows, left-aligned text, right-aligned money. No hero sections,
   no big metric tiles unless a decision depends on the number.
6. **Name the action and its consequence.** Buttons say what happens ("Approve and send reply"); anything that sends a
   reply or moves money asks for confirmation that names the amount and the customer.
7. **Show who and why.** The maker (agent or person) and the checker (who approved) are always visible on a case.

## 2. Tokens
We keep shadcn/ui's components and restyle them through its CSS variables in `web/app/globals.css`. These are the
values to put there (light theme; dark theme is out of scope for the hackathon).

| shadcn variable | Value | Used for |
|---|---|---|
| `--background` | `#F6F7F8` | Page background |
| `--foreground` | `#14191F` | Body text |
| `--card`, `--popover` | `#FFFFFF` | Panels, tables, dialogs |
| `--card-foreground`, `--popover-foreground` | `#14191F` | Text on panels |
| `--primary` | `#8A1F5C` | Lotus berry (*teratai* is the lotus): primary buttons, links, focus, selected nav. Hover `#6E184A` |
| `--primary-foreground` | `#FFFFFF` | Text on primary |
| `--secondary`, `--muted` | `#EEF1F3` | Secondary buttons, table header, quiet fills |
| `--secondary-foreground` | `#14191F` | Text on secondary |
| `--muted-foreground` | `#4B5563` | Labels, secondary text (7.4:1 on white) |
| `--accent` | `#F8E9F1` | Hover and selected rows |
| `--accent-foreground` | `#8A1F5C` | Text on accent (7.4:1) |
| `--destructive` | `#B42318` | Reject, destructive actions |
| `--border` | `#D8DDE2` | Dividers, table lines, panel borders |
| `--input` | `#C0C8D0` | Input borders |
| `--ring` | `#8A1F5C` | Focus ring |
| `--radius` | `0.375rem` (6 px) | Corners: modest, never pill-shaped except badges |

**Status colours** (new variables, add them to `:root` and to `@theme inline` as `--color-status-*`):

| Status | Text | Background | Border | Used for |
|---|---|---|---|---|
| `critical` | `#B42318` | `#FEF3F2` | `#FECDCA` | P1, with fraud team, self-check flagged, SLA breached |
| `warning` | `#93370D` | `#FFFAEB` | `#FEDF89` | P2, needs information, escalated, SLA at risk |
| `info` | `#175CD3` | `#EFF8FF` | `#B2DDFF` | Awaiting approval |
| `success` | `#067647` | `#ECFDF3` | `#ABEFC6` | Approved, auto-resolved, sent, self-check passed |
| `neutral` | `#344054` | `#F2F4F7` | `#D0D5DD` | P3, rejected, closed, anything without a status meaning |

**Brand vs status:** the brand colour sits in a hue no status uses (status owns red, amber, blue and green), so a
primary button never reads as "success". Use the berry only for identity and the one primary action per screen
(logo, selected nav, links, focus ring, primary button), never for badges or row highlights. Destructive actions stay
a red *outline* button, so they differ from the filled berry primary in shape as well as colour.

**Type:** IBM Plex Sans for everything, IBM Plex Mono for IDs (load with `next/font/google`, weights 400, 500, 600).
Scale: 12 px captions · 13 px table text and secondary · 14 px body (the base) · 16 px section titles · 20 px page
titles · 24 px the one headline figure on a case (the refund or disputed amount). Weights: 400 body, 500 labels and
table headers, 600 titles. Never 700.

**Spacing:** 4 px grid. Page padding 24 px; panel padding 16 px; table rows 40 px high (cell padding 8 × 12 px);
gap between panels 16 px. **Shadows:** none, except dialogs and dropdowns (shadcn defaults).

## 3. Status vocabulary (use these exact words everywhere)
| Data value | Label | Colour |
|---|---|---|
| `case_state: auto_resolved` | Auto-resolved | success |
| `case_state: awaiting_approval` | Awaiting approval | info |
| `case_state: with_fraud_team` | With fraud team | critical |
| `case_state: approved` | Approved | success |
| `case_state: rejected` | Rejected | neutral |
| status `needs_info` | Needs information | warning |
| status `escalated` (bonus) | Escalated to manager | warning |
| `P1` / `P2` / `P3` | P1 / P2 / P3 (tooltip: Urgent / High / Normal) | critical / warning / neutral |
| `self_check: passed` / `flagged` | Self-check passed / Self-check flagged | success / critical |
| `sent: true` / `false` | Reply sent / Not sent | plain text, no colour |
| route `AUTO_RESOLVE` / `HUMAN_APPROVAL` / `FRAUD_TEAM` | Auto-resolve / Human approval / Fraud team | plain text |
| outcome `REFUND` / `DECLINE` / `INVESTIGATE` / `INFO_ONLY` | Refund / Decline / Investigate / Information only | plain text, 600 weight |
| category `DUPLICATE_CHARGE` … | Duplicate charge, Failed transfer, ATM cash not dispensed, Unauthorised card payment, Scam transfer, Fee dispute, Service quality | plain text |

Raw enum values (`HUMAN_APPROVAL`, `DUPLICATE_CHARGE`) appear only in the technical trace and JSON views.

## 4. Formats
- **Money:** `RM1,500.00`: always two decimals, thousands separator, no space after RM (the Malaysian convention).
  Right-aligned in tables, `tabular-nums`. Zero refund is `RM0.00`, not a dash. A calculation is shown in mono:
  `1,500.00 − 950.00 = 550.00`.
- **Dates and times:** absolute, 24-hour: `17 Jul 2026, 07:20`. The page header says once that times are MYT.
  Relative times appear only next to an absolute one: `Due 21 Jul, 22:32 · 3 h left`.
- **IDs:** `CMP-00244`, `TXN-0088211`, `CUS-02394`, `ACC-003802` in IBM Plex Mono, never truncated.
- **Names:** the customer's full name as in the data. Honorifics (Encik, Puan, Tuan/Puan) only in replies.
- **Language:** `EN` / `MS` as a small mono tag next to the reply.
- **Empty values:** an em dash `—` in tables, with a tooltip saying why if it isn't obvious.

## 5. Layout patterns
- **App shell:** a left sidebar (232 px, white, 1 px border; selected item = accent fill + primary text, no dark
  sidebar), a top bar with the page title, an environment tag (`Live`, `Demo`, `Frozen API`) and the simulated clock.
  Breadcrumbs on record pages: `Approval queue / CMP-00244`.
- **Queue (Table):** columns in this order: Priority · Case · Customer · Category · Amount · State · Due · Assignee.
  Sorted by priority, then due time. Row hover = accent; the whole row opens the case. No zebra stripes. Filters as
  shadcn Tabs above the table, each with a count.
- **Case record page:** (1) a header strip: case ID, customer, channel, received time, state badge, priority badge;
  (2) a decision summary row: Outcome · Refund · Route · Rule; (3) two columns: left = complaint text and the evidence
  table, right = reply and approval; (4) Tabs below for Trace, Audit, Tool calls.
- **Evidence table:** the matched transaction is marked by a 3 px primary left border **and** a "Matched" label in the
  first cell, not by a coloured background alone. Rows that were filtered out stay in muted text with the reason.
- **Reply panel:** the reply text with each ID and amount underlined in success (verified) or critical (not in evidence)
  colour, plus a dotted underline so it reads without colour; the self-check badge above it; the language tag.
- **Approval bar** (bottom of the reply panel): "Your name" input, "Reason" input, then buttons: primary "Approve and
  send reply", secondary "Edit and approve", destructive-outline "Reject". A confirm Dialog before sending:
  "Send the RM550.00 refund reply to Aisyah binti Kassim? You'll be recorded as the approver."
- **Audit log (Table):** Time · Case · Actor · Action · Field · From · To · Reason. From and To are plain values in two
  columns. Newest first. Agent rows say "Agent" as the actor.

## 6. Components (shadcn)
| Need | Use | Notes |
|---|---|---|
| Queues, evidence, audit log | Table | Dense rows, header in `--muted` fill, 500 weight |
| Status, priority, self-check | Badge | One `StatusBadge` wrapper maps §3 to the status colours; square-ish (radius 4 px) |
| Decision summary, reply panel | Card | Only these two; everything else sits on the page or in a table |
| Queue filters, case sub-views | Tabs | With counts |
| Confirm before send or reject | Dialog | Names the amount and customer |
| Reply editing | Textarea | Mono off; 14 px; live self-check below it |
| Names, reasons | Input, Select | Labels above fields, never placeholder-only |
| Truncated text, codes | Tooltip | Full value on hover and focus |
| Sections | Separator | Instead of extra boxes |

Our own components are thin wrappers around these, styled only with the tokens: `StatusBadge`, `Money`, `DateTime`,
`MonoId`, `ReplyTokens` (verified and flagged highlights), `SlaDue`. Nothing else custom.

## 7. Writing
- Buttons are verbs that say the result: "Approve and send reply", "Reject, send nothing", "Escalate to manager".
  Never "Submit", "OK", "Confirm".
- Errors say what is wrong and what to do: "Self-check flagged RM600.00: it isn't in this case's evidence. Correct
  the amount or reject the case."
- Empty states say what will appear: "No cases are waiting for approval. New ones appear here automatically."
- No exclamation marks, emoji, "Oops", or jokes. Sentence case for everything.
- Staff-facing text is English. Customer-facing replies are English or Malay, set by the case.

## 8. Do and don't
| Don't | Do |
|---|---|
| ~~escalated~~ → sent (strikethrough) | From: Escalated · To: Approved (two plain labelled values) |
| Coloured pill on every field | Badges only for priority, state and self-check; the rest plain text |
| Big rounded cards for every block, lots of empty padding | Tables and a record page; Cards only for the decision summary and reply |
| Hero metric tiles, made-up percentages | Numbers in tables with their date range and source; `—` until real |
| `RM550`, `550.00`, `RM 550` mixed | `RM550.00` everywhere, right-aligned |
| "2 h ago" alone | `Due 21 Jul, 22:32 · 3 h left` |
| Raw enums: `HUMAN_APPROVAL`, `ATM_NOT_DISPENSED` | Human approval, ATM cash not dispensed |
| Matched row shown only by a green background | 3 px primary left border + "Matched" label |
| Full-height sidebar in the brand colour | White sidebar, 1 px border, accent for the selected item |
| Gradients, glow, emoji, decorative icons | Flat surfaces; Lucide icons only where they add meaning (check, alert, clock) |
| Centre-aligned table numbers | Right-aligned, `tabular-nums` |
| "Submit" / "OK" | "Approve and send reply" |

## 9. Accessibility
Text contrast at least 4.5:1 (the tokens above meet it); visible focus ring on every control; every control has a
label; status never by colour alone; keyboard can reach and operate the approval bar and dialogs (shadcn handles this
if we don't override it).
