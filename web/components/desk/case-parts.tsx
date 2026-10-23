import Link from "next/link"

import { DateTime } from "@/components/desk/date-time"
import { Money } from "@/components/desk/money"
import { MonoId } from "@/components/desk/mono-id"
import { StatusBadge } from "@/components/desk/status-badge"
import { Card } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { classifierLine, dayLong, dayRange, fixCalc, routeReason, stateOf, str, type CaseDetail } from "@/lib/case"
import { formatDateTimeShort, formatMoney } from "@/lib/format"
import { categoryLabel, flagLabel, outcomeLabel, routeLabel } from "@/lib/labels"
import { cn } from "cn"

export function CaseHeader({ id, detail }: { id: string; detail: CaseDetail | null }) {
  const c = detail?.case
  const done = c?.status === "done"
  return (
    <header className="workspace-header !flex-col !items-start">
      <nav aria-label="Breadcrumb" className="text-[13px] text-muted-foreground">
        <Link href="/queues" className="text-primary hover:underline">
          Queues
        </Link>{" "}
        / <MonoId>{id}</MonoId>
      </nav>
      <div className="flex flex-wrap items-center gap-2.5">
        <h1 className="font-mono text-xl font-semibold">{id}</h1>
        {detail && <StatusBadge value={stateOf(detail)} />}
        {done && <StatusBadge value={c?.priority} />}
        {c && (
          <span className="text-[13px] text-muted-foreground sm:ml-auto">
            {c.customer_name} · <MonoId>{c.customer_id}</MonoId> · {c.channel} · received <DateTime value={c.received_at} />
          </span>
        )}
      </div>
      {c && c.flags.length > 0 && (
        <p className="text-xs text-muted-foreground">Flags: {c.flags.map(flagLabel).join(", ")}</p>
      )}
    </header>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 text-xs font-medium text-muted-foreground">{label}</div>
      {children}
    </div>
  )
}

export function DecisionSummary({ detail }: { detail: CaseDetail }) {
  const d = detail.decision ?? {}
  const outcome = str(d.outcome) ?? detail.case.outcome
  const route = str(d.route) ?? detail.case.route
  const refund = str(d.refund_myr) ?? detail.case.refund_amount_myr
  const calc = fixCalc(str(d.calc))
  const cls = classifierLine(detail)
  return (
    <Card className="gap-0 rounded-md py-0 ring-0 border">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-4 p-4 min-[1180px]:grid-cols-[0.8fr_1.25fr_1fr_1.4fr_1fr]">
        <Field label="Outcome">
          <div className="font-semibold">{outcomeLabel(outcome)}</div>
        </Field>
        <Field label="Refund">
          <div className="text-2xl font-semibold tabular-nums">
            <Money value={refund} className="text-left" />
          </div>
          {calc && <div className="font-mono text-[12.5px] text-muted-foreground">{calc}</div>}
        </Field>
        <Field label="Route">
          <div>{routeLabel(route)}</div>
          <div className="text-xs text-muted-foreground">{routeReason(detail)}</div>
        </Field>
        <Field label="Rule">
          <div>{str(d.rule_text) ?? "—"}</div>
        </Field>
        <Field label="Category">
          <div>{categoryLabel(detail.case.category)}</div>
          {cls && <div className="text-xs text-muted-foreground">{cls}</div>}
        </Field>
      </div>
    </Card>
  )
}

export function ComplaintPanel({ detail }: { detail: CaseDetail }) {
  const w = detail.window
  const phrase = str(w?.phrase)
  const resolved = str(w?.exact_day)
  return (
    <section className="rounded-md border bg-card">
      <h2 className="border-b px-4 py-3 text-base font-semibold">Complaint</h2>
      <div className="p-4 leading-relaxed">
        {detail.subject && <p className="mb-2 font-medium">Subject: {detail.subject}</p>}
        <p className="whitespace-pre-wrap">{detail.text}</p>
      </div>
      {w && (
        <p className="px-4 pb-4 text-xs text-muted-foreground">
          {phrase ? <>&quot;{phrase}&quot;{resolved ? ` → ${dayLong(resolved)}` : ""}</> : "No date given"} · searched{" "}
          {dayRange(str(w.start), str(w.end))}
        </p>
      )}
    </section>
  )
}

const ROLE_LABEL: Record<string, string> = {
  matched: "Matched",
  candidate: "Candidate",
  duplicate_sibling: "Duplicate of",
  reversal: "Reversal",
}

export function EvidencePanel({ detail }: { detail: CaseDetail }) {
  const rows = detail.evidence
  const j = detail.atm_journal
  return (
    <section className="rounded-md border bg-card">
      <h2 className="flex flex-wrap items-baseline gap-2 border-b px-4 py-3 text-base font-semibold">
        Evidence
        {rows.length > 0 && <span className="text-xs font-normal text-muted-foreground">Matched transaction and related rows</span>}
      </h2>
      {rows.length === 0 ? (
        <p className="px-4 py-4 text-[13px] text-muted-foreground">
          No transaction matched.{detail.match_status ? ` Match status: ${detail.match_status.toLowerCase().replace(/_/g, " ")}.` : ""}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <Table className="text-[13px]">
            <TableHeader>
              <TableRow className="hover:bg-muted">
                {["", "Transaction", "Merchant", "Amount", "Status"].map((h, i) => (
                  <TableHead
                    key={i}
                    className={cn("h-9 bg-muted px-2 text-xs font-medium text-muted-foreground", h === "Amount" && "text-right")}
                  >
                    {h}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => {
                const matched = r.role === "matched"
                const quiet = r.role === "candidate"
                return (
                  <TableRow key={`${r.role}-${r.txn_id}`} className={cn("h-10", quiet && "text-muted-foreground")}>
                    <TableCell
                      className={cn("border-l-[3px] border-transparent px-2 py-0 text-xs", matched && "border-primary font-medium")}
                    >
                      {ROLE_LABEL[r.role] ?? r.role}
                      {quiet && r.score != null && <span className="block text-muted-foreground">score {r.score}</span>}
                    </TableCell>
                    {/* Two lines per cell keep Amount and Status visible in the narrow left column. */}
                    <TableCell className="px-2 py-1.5">
                      <MonoId>{r.txn_id}</MonoId>
                      <span className="block text-xs text-muted-foreground">{formatDateTimeShort(r.txn_time)}</span>
                    </TableCell>
                    <TableCell className="whitespace-normal px-2 py-1.5">
                      {r.merchant || "—"}
                      <span className="block text-xs text-muted-foreground">{r.channel}</span>
                    </TableCell>
                    <TableCell className="px-2 py-0"><Money value={r.amount_myr} /></TableCell>
                    <TableCell className="px-2 py-0">{r.status}</TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}
      {j && (
        <p className="border-t px-4 py-2.5 text-xs text-muted-foreground">
          ATM journal: requested {formatMoney(j.requested_myr)} · dispensed {formatMoney(j.dispensed_myr)} ({j.atm_location}
          ). <MonoId>{j.txn_id}</MonoId> is {j.journal_status.toLowerCase().replace(/_/g, " ")}.
        </p>
      )}
    </section>
  )
}
