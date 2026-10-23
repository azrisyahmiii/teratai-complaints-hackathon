"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useMemo, useRef, useState } from "react"

import { Money } from "@/components/desk/money"
import { MonoId } from "@/components/desk/mono-id"
import { DateTime } from "@/components/desk/date-time"
import { StatusBadge } from "@/components/desk/status-badge"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { api, type Schemas } from "@/lib/api/client"
import { formatDateTimeShort, formatDayShort, formatMoney, wallMs } from "@/lib/format"
import { categoryLabel, flagLabel } from "@/lib/labels"
import { useRole, type Role } from "@/lib/role"
import { cn } from "cn"

type CaseRow = Schemas["CaseRow"]
type CaseList = Schemas["CaseList"]
type TabKey = "awaiting_approval" | "with_fraud_team" | "auto_resolved" | "all"

const POLL_MS = 2000
const FRESH_MS = 10000

const TABS: { key: TabKey; label: string }[] = [
  { key: "awaiting_approval", label: "Awaiting approval" },
  { key: "with_fraud_team", label: "With fraud team" },
  { key: "auto_resolved", label: "Auto-resolved" },
  { key: "all", label: "All" },
]

const ROLE_TAB: Record<Role, TabKey> = { officer: "awaiting_approval", fraud: "with_fraud_team", manager: "all" }

const EMPTY: Record<TabKey, string> = {
  awaiting_approval: "No cases are waiting for approval. New ones appear here automatically.",
  with_fraud_team: "No cases are with the fraud team. New ones appear here automatically.",
  auto_resolved: "No cases have been auto-resolved yet. New ones appear here automatically.",
  all: "No cases yet. Complaints posted to the API appear here automatically.",
}

interface Fig {
  label: string
  value: string
  sub: string
  red?: boolean
}

function figuresFor(role: Role, data: CaseList, rows: CaseRow[]): Fig[] {
  const f = data.figures
  const now = wallMs(f.now)
  const waiting = rows.filter((c) => c.case_state === "awaiting_approval")
  const open = rows.filter((c) => c.case_state === "with_fraud_team")
  const firstP1 = (list: CaseRow[]) => list.find((c) => c.priority === "P1")?.complaint_id

  if (role === "officer") {
    const o = f.officer
    const due = waiting
      .filter((c) => c.ack_due && wallMs(c.ack_due) >= now && wallMs(c.ack_due) <= now + 2 * 3600_000)
      .sort((a, b) => wallMs(a.ack_due!) - wallMs(b.ack_due!))[0]
    return [
      {
        label: "Waiting for approval",
        value: String(o.waiting),
        sub: o.oldest ? `Oldest: ${o.oldest.complaint_id}, received ${formatDayShort(o.oldest.received_at)}` : "Nothing waiting",
      },
      { label: "P1 waiting", value: String(o.p1_waiting), sub: firstP1(waiting) ?? "None", red: o.p1_waiting > 0 },
      {
        label: "Acknowledge due within 2 h",
        value: String(o.ack_due_2h),
        sub: due ? `${due.complaint_id} · due ${formatDateTimeShort(due.ack_due)}` : "None",
      },
      {
        label: "Self-check flagged",
        value: String(o.check_flagged),
        sub: o.check_flagged > 0 ? "Needs a corrected reply" : "None",
        red: o.check_flagged > 0,
      },
    ]
  }
  if (role === "fraud") {
    const r = f.fraud
    return [
      { label: "Open with fraud team", value: String(r.open), sub: "Holding reply sent" },
      { label: "P1 open", value: String(r.p1_open), sub: firstP1(open) ?? "None", red: r.p1_open > 0 },
      { label: "Acknowledge overdue", value: String(r.ack_overdue), sub: "P1 target: 2 h", red: r.ack_overdue > 0 },
      { label: "Amount disputed", value: formatMoney(r.amount_disputed_myr), sub: "No refund until investigated" },
    ]
  }
  const m = f.manager
  const flagged = waiting.filter((c) => c.self_check === "flagged").length
  const p1Waiting = waiting.filter((c) => c.priority === "P1").length
  return [
    { label: "All cases", value: String(m.all), sub: "Live run" },
    { label: "Waiting for approval", value: String(m.awaiting_approval), sub: `${p1Waiting} P1 · ${flagged} self-check flagged` },
    { label: "With fraud team", value: String(m.with_fraud_team), sub: `${open.filter((c) => c.priority === "P1").length} P1` },
    { label: "Auto-resolved", value: String(m.auto_resolved), sub: "Reply sent, case closed" },
    {
      label: "Processing errors",
      value: String(m.errors),
      sub: `${m.processing} processing`,
      red: m.errors > 0,
    },
  ]
}

function stateValue(c: CaseRow): string | null {
  return c.status === "done" ? (c.case_state ?? null) : c.status
}

function useCases() {
  const [data, setData] = useState<CaseList | null>(null)
  const [failed, setFailed] = useState(false)
  const [fresh, setFresh] = useState<ReadonlySet<string>>(new Set())
  const seen = useRef<Set<string> | null>(null)

  useEffect(() => {
    let alive = true
    const timers: ReturnType<typeof setTimeout>[] = []

    async function poll() {
      try {
        const { data: d, error } = await api.GET("/api/cases")
        if (!alive) return
        if (error || !d) throw new Error("bad response")
        setFailed(false)
        setData(d)
        const ids = d.items.map((c) => c.complaint_id)
        if (seen.current) {
          const known = seen.current
          const added = ids.filter((id) => !known.has(id))
          if (added.length) {
            setFresh((prev) => new Set([...prev, ...added]))
            timers.push(
              setTimeout(() => {
                if (alive) setFresh((prev) => new Set([...prev].filter((id) => !added.includes(id))))
              }, FRESH_MS),
            )
          }
        }
        seen.current = new Set(ids)
      } catch {
        if (alive) setFailed(true)
      }
    }

    void poll()
    const t = setInterval(poll, POLL_MS)
    return () => {
      alive = false
      clearInterval(t)
      timers.forEach(clearTimeout)
    }
  }, [])

  return { data, failed, fresh }
}

export function Queues() {
  const { role } = useRole()
  const router = useRouter()
  const { data, failed, fresh } = useCases()
  const [tab, setTab] = useState<TabKey>(ROLE_TAB[role])
  const [seenRole, setSeenRole] = useState(role)
  if (seenRole !== role) {
    setSeenRole(role)
    setTab(ROLE_TAB[role])
  }

  const rows = useMemo(() => data?.items ?? [], [data])
  const shown = useMemo(
    () => (tab === "all" ? rows : rows.filter((c) => c.status === "done" && c.case_state === tab)),
    [rows, tab],
  )
  const figs = data ? figuresFor(role, data, rows) : null

  return (
    <div className="flex max-w-[1180px] flex-col gap-4 p-6">
      {figs && (
        <section
          aria-label="Figures"
          className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] overflow-hidden rounded-md border bg-card"
        >
          {figs.map((f) => (
            <div key={f.label} className="min-w-0 border-r px-4 py-3 last:border-r-0">
              <div className="text-xs font-medium text-muted-foreground">{f.label}</div>
              <div className={cn("mt-0.5 text-xl font-semibold tabular-nums", f.red && "text-status-critical-fg")}>
                {f.value}
              </div>
              <div className="mt-0.5 truncate text-xs text-muted-foreground">{f.sub}</div>
            </div>
          ))}
        </section>
      )}

      <section className="rounded-md border bg-card">
        <Tabs value={tab} onValueChange={(v) => setTab(v as TabKey)}>
          <TabsList variant="line" className="group-data-horizontal/tabs:h-auto w-full flex-wrap justify-start gap-1 rounded-none border-b px-3 py-0">
            {TABS.map((t) => (
              <TabsTrigger
                key={t.key}
                value={t.key}
                className="h-auto flex-none rounded-none border-0 border-b-2 border-transparent px-3 py-2.5 text-sm text-muted-foreground after:hidden data-active:border-primary data-active:font-medium data-active:text-foreground"
              >
                {t.label}
                <span className="rounded-[4px] bg-muted px-1.5 text-xs font-normal text-muted-foreground tabular-nums">
                  {data?.counts[t.key] ?? 0}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        {failed && (
          <p role="status" className="px-3 pt-2 text-[13px] text-status-critical-fg">
            Can&apos;t reach the API. Retrying every 2 s.
          </p>
        )}

        <Table className="min-w-[960px] text-[13px]">
          <TableHeader>
            <TableRow className="hover:bg-muted">
              {["Priority", "Case", "Customer", "Category", "Amount", "State", "Received", "Flags"].map((h) => (
                <TableHead
                  key={h}
                  className={cn("h-9 bg-muted px-3 text-xs font-medium text-muted-foreground", h === "Amount" && "text-right")}
                >
                  {h}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((c) => {
              const done = c.status === "done"
              const flags = c.flags.map(flagLabel)
              return (
                <TableRow
                  key={c.complaint_id}
                  onClick={() => router.push(`/cases/${encodeURIComponent(c.complaint_id)}`)}
                  className={cn("h-10 cursor-pointer hover:bg-accent", fresh.has(c.complaint_id) && "bg-[#FFFBEB]")}
                >
                  <TableCell className="px-3 py-0">{done ? <StatusBadge value={c.priority} /> : "—"}</TableCell>
                  <TableCell className="px-3 py-0">
                    <Link href={`/cases/${encodeURIComponent(c.complaint_id)}`} className="text-primary hover:underline">
                      <MonoId>{c.complaint_id}</MonoId>
                    </Link>
                  </TableCell>
                  <TableCell className="px-3 py-0">{c.customer_name}</TableCell>
                  <TableCell className="px-3 py-0">{done ? categoryLabel(c.category) : "—"}</TableCell>
                  <TableCell className="px-3 py-0">
                    {done ? <Money value={c.refund_amount_myr} /> : <span className="block text-right">—</span>}
                  </TableCell>
                  <TableCell className="px-3 py-0">
                    <StatusBadge value={stateValue(c)} />
                  </TableCell>
                  <TableCell className="px-3 py-0">
                    <DateTime value={c.received_at} short />
                  </TableCell>
                  <TableCell className="px-3 py-0 text-xs text-muted-foreground">{flags.join(", ")}</TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>

        {data && shown.length === 0 && (
          <p className="border-t px-3 py-8 text-center text-[13px] text-muted-foreground">{EMPTY[tab]}</p>
        )}
        {!data && !failed && <p className="border-t px-3 py-8 text-center text-[13px] text-muted-foreground">Loading cases…</p>}

        <p className="border-t px-3 py-2.5 text-xs text-muted-foreground">
          Sorted by priority, then received time. Amount is the refund the agent decided; RM0.00 is a decline or investigation.
        </p>
      </section>
    </div>
  )
}
