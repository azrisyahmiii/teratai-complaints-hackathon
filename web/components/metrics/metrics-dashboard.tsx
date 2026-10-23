"use client"

import { useRouter, useSearchParams } from "next/navigation"
import { useEffect, useMemo, useState, type ReactNode } from "react"

import { Money } from "@/components/desk/money"
import { api, type Schemas } from "@/lib/api/client"
import { formatDateTimeShort, formatMoney } from "@/lib/format"
import { useRole } from "@/lib/role"
import { BreakdownTable } from "./breakdown-table"
import { FilterBar, type Filters } from "./filter-bar"
import { FigureRow, type Figure } from "./figure-row"
import { formatMinutes, formatMs, formatUsd, plural } from "./fmt"
import { StageTable } from "./stage-table"
import { RateValue, StatList } from "./stat-list"
import { TeamTable } from "./team-table"
import { Unavailable } from "./unavailable"

type Metrics = Schemas["MetricsOut"]

const POLL_MS = 5000
const OPEN_STATES = ["awaiting_approval", "with_fraud_team", "escalated"]

function Panel({ id, title, note, children }: { id: string; title: string; note?: string; children: ReactNode }) {
  return (
    <section className="rounded-md border bg-card" aria-labelledby={id}>
      <div className="border-b px-3 py-3">
        <h2 id={id} className="text-base font-semibold">{title}</h2>
        {note && <p className="mt-1 text-xs text-muted-foreground">{note}</p>}
      </div>
      <div className="grid md:grid-cols-2 xl:grid-cols-3 md:[&>*]:border-r md:[&>*]:border-b">{children}</div>
    </section>
  )
}

function useMetrics(filters: Filters) {
  const [data, setData] = useState<Metrics | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { date_from, date_to, category, channel } = filters

  useEffect(() => {
    let alive = true
    async function poll() {
      try {
        const { data: d, error: e, response } = await api.GET("/api/metrics", {
          params: {
            query: {
              date_from: date_from || undefined,
              date_to: date_to || undefined,
              category: category || undefined,
              channel: channel || undefined,
            },
          },
        })
        if (!alive) return
        if (e || !d) {
          const detail = (e as { detail?: unknown } | undefined)?.detail
          throw new Error(response.status === 422 && typeof detail === "string" ? detail : "bad response")
        }
        setError(null)
        setData(d)
      } catch (err) {
        if (alive) setError(err instanceof Error && err.message !== "bad response" ? err.message : "Can't reach the API. Retrying every 5 s.")
      }
    }
    void poll()
    const t = setInterval(poll, POLL_MS)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [date_from, date_to, category, channel])

  return { data, error }
}

function buildFigures(m: Metrics): Figure[] {
  const u = m.unavailable
  const open = m.operations.backlog.filter((b) => OPEN_STATES.includes(b.key)).reduce((n, b) => n + b.count, 0)
  const p = m.performance
  const figs: Figure[] = [
    { label: "Open backlog", value: String(open), sub: `${plural(m.volume.total, "case")} in selection` },
    {
      label: "Acknowledge overdue",
      value: String(m.operations.ack_overdue),
      sub: `${m.operations.ack_due_2h} more due within 2 h`,
      red: m.operations.ack_overdue > 0,
    },
  ]
  if (m.money) {
    figs.push(
      { label: "Refunds paid", value: formatMoney(m.money.refunds_paid_myr), sub: `${plural(m.money.refunds_paid_count, "refund")} sent` },
      {
        label: "Awaiting approval",
        value: formatMoney(m.money.awaiting_approval_myr),
        sub: `${plural(m.money.awaiting_approval_count, "refund")} not yet sent`,
      },
    )
  }
  if (m.fraud) {
    figs.push(
      { label: "Fraud cases open", value: String(m.fraud.open), sub: `${m.fraud.p1_open} P1`, red: m.fraud.p1_open > 0 },
      { label: "Amount disputed", value: formatMoney(m.fraud.amount_disputed_myr), sub: "On open fraud cases" },
    )
  }
  const g = m.guardrails.self_check_flagged
  figs.push(
    {
      label: "Self-check flagged",
      value: g.pct == null ? "—" : `${g.pct.toFixed(1)}%`,
      sub: g.pct == null ? "No decided cases" : `${g.numerator} of ${g.denominator} ${g.denominator === 1 ? "reply" : "replies"}`,
      red: g.numerator > 0,
    },
    {
      label: "Cost per complaint",
      value: p.cost_per_complaint_usd == null ? <Unavailable path="performance" map={u} /> : formatUsd(p.cost_per_complaint_usd),
      sub: `${plural(p.cases_measured, "case")} measured`,
    },
  )
  return figs
}

export function MetricsDashboard() {
  const { role } = useRole()
  const router = useRouter()
  const params = useSearchParams()
  const filters: Filters = useMemo(
    () => ({
      date_from: params.get("date_from") ?? "",
      date_to: params.get("date_to") ?? "",
      category: params.get("category") ?? "",
      channel: params.get("channel") ?? "",
    }),
    [params],
  )
  const { data: m, error } = useMetrics(filters)

  function setFilters(next: Filters) {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(next)) if (v) qs.set(k, v)
    router.replace(qs.size ? `/metrics?${qs}` : "/metrics", { scroll: false })
  }

  return (
    <div className="workspace-content flex flex-col">
      <FilterBar filters={filters} options={m?.options} onChange={setFilters} />

      {error && (
        <p role="alert" className="rounded-md border border-status-critical-border bg-status-critical-bg px-3 py-2 text-[13px] text-status-critical-fg">
          {error}
        </p>
      )}
      {!m && !error && <Skeleton />}
      {m && <Body m={m} role={role} filtered={Object.values(filters).some(Boolean)} />}
      {m && (
        <p className="text-xs text-muted-foreground" role="status">
          Updated every 5 s · clock {formatDateTimeShort(m.sim_now)} · {m.run_id} run
        </p>
      )}
    </div>
  )
}

function Skeleton() {
  return (
    <div aria-busy className="flex flex-col gap-6" role="status">
      <span className="sr-only">Loading insights…</span>
      <div className="h-28 animate-pulse rounded-md border bg-card" />
      <div className="h-64 animate-pulse rounded-md border bg-card" />
      <div className="h-64 animate-pulse rounded-md border bg-card" />
    </div>
  )
}

function Body({ m, role, filtered }: { m: Metrics; role: string; filtered: boolean }) {
  const u = m.unavailable
  if (m.volume.total === 0) {
    return (
      <p className="rounded-md border bg-card px-3 py-8 text-center text-[13px] text-muted-foreground">
        {filtered ? "No complaints match these filters." : "No complaints yet. Complaints appear here once they have been processed."}
      </p>
    )
  }

  const outcomes = (
    <Panel id="outcomes" title="Outcomes" note="What the agent decided. Amounts are refunds decided, not money paid.">
      <BreakdownTable title="Outcome" kind="outcome" rows={m.outcomes.by_outcome} amountLabel="Refund total" />
      <BreakdownTable title="Route" kind="route" rows={m.outcomes.by_route} />
      <StatList
        title="Automation"
        stats={[{ label: "Auto-resolve rate", value: <RateValue rate={m.outcomes.auto_resolve_rate} path="outcomes.auto_resolve_rate" map={u} /> }]}
      />
    </Panel>
  )

  const money = m.money && (
    <Panel id="money" title="Refund money" note="Paid means the reply was sent. Awaiting approval is decided but not yet sent.">
      <StatList
        title="Refunds"
        stats={[
          { label: "Paid", value: <Money value={m.money.refunds_paid_myr} /> },
          { label: "Refunds paid", value: m.money.refunds_paid_count },
          { label: "Average refund", value: m.money.avg_refund_myr == null ? <Unavailable path="money.avg_refund_myr" map={{ "money.avg_refund_myr": u["money.avg_refund_myr"] ?? "No refunds have been paid in this selection." }} /> : <Money value={m.money.avg_refund_myr} /> },
          { label: "Awaiting approval", value: <Money value={m.money.awaiting_approval_myr} /> },
          { label: "Refunds awaiting approval", value: m.money.awaiting_approval_count },
        ]}
      />
      <BreakdownTable title="Refunds by category" kind="category" rows={m.money.refunds_by_category} amountLabel="Refund total" />
    </Panel>
  )

  const f = m.fraud
  const fraud = f && (
    <Panel id="fraud" title="Fraud team" note="Cases routed to the fraud team. No refund is made until an investigation concludes.">
      <StatList
        title="Fraud cases"
        stats={[
          { label: "All fraud cases", value: f.total },
          { label: "Open", value: f.open },
          { label: "P1 open", value: f.p1_open },
          { label: "Acknowledge overdue", value: f.ack_overdue },
          { label: "Amount disputed", value: <Money value={f.amount_disputed_myr} /> },
        ]}
      />
      <BreakdownTable title="Fraud by category" kind="category" rows={f.by_category} />
      <StatList
        title="Investigation"
        stats={[
          { label: "Acknowledged", value: f.acknowledged ?? <Unavailable path="fraud.acknowledged" map={u} /> },
          { label: "Recall attempts", value: f.recall_attempts ?? <Unavailable path="fraud.recall_attempts" map={u} /> },
          { label: "Outcomes recorded", value: f.outcomes == null ? <Unavailable path="fraud.outcomes" map={u} /> : f.outcomes.reduce((n, o) => n + o.count, 0) },
        ]}
      />
      {f.outcomes && f.outcomes.length > 0 && <BreakdownTable title="Investigation outcome" kind="plain" rows={f.outcomes} />}
    </Panel>
  )

  const o = m.operations
  const operations = (
    <Panel id="operations" title="Operations" note="Backlog counts each case once, in its current state.">
      <BreakdownTable title="Backlog by state" kind="state" rows={o.backlog} />
      <StatList
        title="Deadlines"
        stats={[
          { label: "Acknowledge overdue", value: o.ack_overdue },
          { label: "Acknowledge due within 2 h", value: o.ack_due_2h },
          { label: "Resolve deadlines met", value: <Unavailable path="operations.resolve_adherence" map={u} /> },
        ]}
      />
      <StatList
        title="Approval turnaround"
        stats={[
          { label: "Human decisions", value: o.human_actions },
          { label: "Median", value: o.turnaround.p50_minutes == null ? <Unavailable path="operations.turnaround" map={{ "operations.turnaround": u["operations.turnaround"] ?? "No case has been actioned by a person yet." }} /> : formatMinutes(o.turnaround.p50_minutes) },
          { label: "95th percentile", value: o.turnaround.p95_minutes == null ? <Unavailable path="operations.turnaround" map={{ "operations.turnaround": u["operations.turnaround"] ?? "No case has been actioned by a person yet." }} /> : formatMinutes(o.turnaround.p95_minutes) },
        ]}
        />
    </Panel>
  )

  const g = m.guardrails
  const guardrails = (
    <Panel id="guardrails" title="Guardrails" note="How often the checks and people changed what the agent produced.">
      <StatList
        title="Checks and overrides"
        stats={[
          { label: "Self-check flagged", value: <RateValue rate={g.self_check_flagged} path="guardrails.self_check_flagged" map={u} /> },
          { label: "Overridden by a person", value: <RateValue rate={g.overrides} path="guardrails.overrides" map={{ ...u, "guardrails.overrides": u["guardrails.overrides"] ?? "No case has been actioned by a person yet." }} /> },
          { label: "Rejected", value: <RateValue rate={g.rejections} path="guardrails.rejections" map={{ ...u, "guardrails.rejections": u["guardrails.rejections"] ?? "No case has been actioned by a person yet." }} /> },
          { label: "Escalated to manager", value: <RateValue rate={g.escalations} path="guardrails.escalations" map={u} /> },
        ]}
      />
      <BreakdownTable title="Reply source" kind="source" rows={g.reply_source} />
      <StatList
        title="Flags raised"
        stats={[
          { label: "Injection suspected", value: g.injection_suspected },
          { label: "Degraded (no model)", value: g.degraded },
          { label: "Needs information", value: g.needs_info },
          { label: "Vulnerable 65+", value: g.vulnerable },
        ]}
      />
    </Panel>
  )

  const v = m.volume
  const volume = (
    <Panel id="volume" title="Volume" note="By received date and customer attributes.">
      <StatList
        title="Cases"
        stats={[
          { label: "Total", value: v.total },
          { label: "Processing", value: v.processing },
          { label: "Processing errors", value: v.errors },
        ]}
      />
      <BreakdownTable title="By day received" kind="day" rows={v.by_day} />
      <BreakdownTable title="By channel" kind="plain" rows={v.by_channel} />
      <BreakdownTable title="By category" kind="category" rows={v.by_category} />
      <BreakdownTable title="By priority" kind="priority" rows={v.by_priority} />
      <BreakdownTable title="By reply language" kind="language" rows={v.by_language} />
    </Panel>
  )

  const p = m.performance
  const performance = (
    <section className="rounded-md border bg-card" aria-labelledby="performance">
      <div className="border-b px-3 py-3">
        <h2 id="performance" className="text-base font-semibold">Speed and cost</h2>
        <p className="mt-1 text-xs text-muted-foreground">From the agent&apos;s recorded stage events. Batch runs record none.</p>
      </div>
      {p.cases_measured === 0 ? (
        <p className="px-3 py-4 text-[13px] text-muted-foreground">
          <Unavailable path="performance" map={u} /> {u.performance ?? "No agent events were recorded for this selection."}
        </p>
      ) : (
        <>
          <div className="grid md:grid-cols-2 md:[&>*]:border-r">
            <StatList
              title="Per complaint"
              stats={[
                { label: "Cases measured", value: p.cases_measured },
                { label: "Median time", value: p.latency_p50_ms == null ? "—" : formatMs(p.latency_p50_ms) },
                { label: "95th percentile time", value: p.latency_p95_ms == null ? "—" : formatMs(p.latency_p95_ms) },
              ]}
            />
            <StatList
              title="Model usage"
              stats={[
                { label: "Model calls", value: p.llm_calls },
                { label: "Total cost", value: p.cost_total_usd == null ? "—" : formatUsd(p.cost_total_usd) },
                { label: "Cost per complaint", value: p.cost_per_complaint_usd == null ? "—" : formatUsd(p.cost_per_complaint_usd) },
              ]}
            />
          </div>
          <StageTable stages={p.stages} />
        </>
      )}
    </section>
  )

  const teams = m.teams && (
    <section className="rounded-md border bg-card" aria-labelledby="teams">
      <div className="border-b px-3 py-3">
        <h2 id="teams" className="text-base font-semibold">Team comparison</h2>
        <p className="mt-1 text-xs text-muted-foreground">Each case belongs to one team by route.</p>
      </div>
      <TeamTable teams={m.teams} />
    </section>
  )

  const order =
    role === "fraud"
      ? [fraud, operations, guardrails, volume, performance]
      : role === "officer"
        ? [outcomes, money, operations, guardrails, volume, performance]
        : [teams, outcomes, money, fraud, operations, guardrails, volume, performance]

  return (
    <>
      <FigureRow figures={buildFigures(m)} />
      {order.map((s, i) => s && <div key={i} className="contents">{s}</div>)}
    </>
  )
}
