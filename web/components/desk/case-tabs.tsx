"use client"

import { useState } from "react"

import { DateTime } from "@/components/desk/date-time"
import { MonoId } from "@/components/desk/mono-id"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { stageLabel, stageResult, str, tookLabel, type CaseDetail } from "@/lib/case"
import { categoryLabel } from "@/lib/labels"

type Key = "trace" | "audit"

const TRIGGER =
  "h-auto flex-none rounded-none border-0 border-b-2 border-transparent px-3 py-2.5 text-sm text-muted-foreground after:hidden data-active:border-primary data-active:font-medium data-active:text-foreground"

const STATE_BY_ROUTE: Record<string, string> = {
  AUTO_RESOLVE: "Auto-resolved",
  HUMAN_APPROVAL: "Awaiting approval",
  FRAUD_TEAM: "With fraud team",
}

const ACTION_LABEL: Record<string, string> = {
  approve: "Approved",
  edit_approve: "Edited and approved",
  reject: "Rejected",
}

function Head({ cols }: { cols: string[] }) {
  return (
    <TableHeader>
      <TableRow className="hover:bg-muted">
        {cols.map((h) => (
          <TableHead key={h} className="h-9 bg-muted px-3 text-xs font-medium text-muted-foreground">
            {h}
          </TableHead>
        ))}
      </TableRow>
    </TableHeader>
  )
}

function UnderstandingLine({ detail }: { detail: CaseDetail }) {
  const u = detail.understanding
  if (!u) return null
  const top3 = Array.isArray(u.top3) ? (u.top3 as [string, number][]) : []
  const source = str(u.source)
  return (
    <p className="border-b px-4 py-3 text-[13px] leading-relaxed text-muted-foreground">
      <span className="font-medium text-foreground">Understanding:</span>{" "}
      {source ? `decided by the ${source}` : "source unknown"}
      {top3.length > 0 && <>. Top 3: {top3.map(([c, p]) => `${categoryLabel(c)} ${Number(p).toFixed(2)}`).join(", ")}</>}
      {str(u.language_reason) && <>. Language: {str(u.language_reason)}</>}
      . Injection suspected: {u.injection_suspected === true ? "yes" : "no"}.
    </p>
  )
}

function Trace({ detail }: { detail: CaseDetail }) {
  const agent = detail.events.filter((e) => e.actor === "agent")
  return (
    <>
      <UnderstandingLine detail={detail} />
      <div className="overflow-x-auto">
        <Table className="min-w-[720px] text-[13px]">
          <Head cols={["Time", "Stage", "Model", "Took", "Result"]} />
          <TableBody>
            {agent.map((e, i) => (
              <TableRow key={i} className="h-10">
                <TableCell className="px-3 py-0">
                  <DateTime value={e.ts} short />
                </TableCell>
                <TableCell className="px-3 py-0">{stageLabel(e.stage)}</TableCell>
                <TableCell className="px-3 py-0">{e.model ? <MonoId>{e.model}</MonoId> : "—"}</TableCell>
                <TableCell className="px-3 py-0 tabular-nums">{tookLabel(e.latency_ms)}</TableCell>
                <TableCell className="px-3 py-0">{stageResult(e, detail)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {agent.length === 0 && <p className="px-4 py-6 text-center text-[13px] text-muted-foreground">No agent steps recorded yet.</p>}
    </>
  )
}

interface AuditRow {
  ts: string | null
  actor: string
  action: string
  from: string
  to: string
  reason: string
}

function auditRows(detail: CaseDetail): AuditRow[] {
  const rows: AuditRow[] = []
  const agent = detail.events.filter((e) => e.actor === "agent")
  const route = str(detail.decision?.route) ?? detail.case.route
  if (agent.length > 0 && route) {
    rows.push({
      ts: agent[agent.length - 1].ts,
      actor: "Agent",
      action: "Decided",
      from: "—",
      to: STATE_BY_ROUTE[route] ?? "—",
      reason: str(detail.decision?.rule_id) ?? "—",
    })
  }
  const human = detail.events.filter((e) => e.actor !== "agent")
  for (const e of human) {
    const action = e.action ?? ""
    const payload = e.payload ?? {}
    rows.push({
      ts: e.ts,
      actor: e.actor,
      action: ACTION_LABEL[action] ?? action,
      from: "Awaiting approval",
      to: action === "reject" ? "Rejected" : "Approved",
      reason: str(payload.reason) ?? "—",
    })
  }
  const h = detail.human_action
  if (human.length === 0 && h) {
    const action = str(h.action) ?? ""
    rows.push({
      ts: str(h.at),
      actor: str(h.actor) ?? "—",
      action: ACTION_LABEL[action] ?? action,
      from: "Awaiting approval",
      to: action === "reject" ? "Rejected" : "Approved",
      reason: str(h.reason) ?? "—",
    })
  }
  return rows.reverse()
}

function Audit({ detail }: { detail: CaseDetail }) {
  const rows = auditRows(detail)
  return (
    <div className="overflow-x-auto">
      <Table className="min-w-[720px] text-[13px]">
        <Head cols={["Time", "Actor", "Action", "From", "To", "Reason"]} />
        <TableBody>
          {rows.map((r, i) => (
            <TableRow key={i} className="h-10">
              <TableCell className="px-3 py-0">
                <DateTime value={r.ts} short />
              </TableCell>
              <TableCell className="px-3 py-0">{r.actor}</TableCell>
              <TableCell className="px-3 py-0">{r.action}</TableCell>
              <TableCell className="px-3 py-0">{r.from}</TableCell>
              <TableCell className="px-3 py-0">{r.to}</TableCell>
              <TableCell className="px-3 py-0">{r.reason}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {rows.length === 0 && <p className="px-4 py-6 text-center text-[13px] text-muted-foreground">Nothing recorded yet.</p>}
    </div>
  )
}

export function CaseTabs({ detail }: { detail: CaseDetail }) {
  const [tab, setTab] = useState<Key>("trace")
  return (
    <section className="rounded-md border bg-card">
      <Tabs value={tab} onValueChange={(v) => setTab(v as Key)}>
        <TabsList variant="line" className="group-data-horizontal/tabs:h-auto w-full justify-start gap-1 rounded-none border-b px-3 py-0">
          <TabsTrigger value="trace" className={TRIGGER}>
            Trace
          </TabsTrigger>
          <TabsTrigger value="audit" className={TRIGGER}>
            Audit
          </TabsTrigger>
        </TabsList>
      </Tabs>
      {tab === "trace" ? <Trace detail={detail} /> : <Audit detail={detail} />}
    </section>
  )
}
