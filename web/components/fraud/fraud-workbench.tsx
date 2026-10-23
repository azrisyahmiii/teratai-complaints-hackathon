"use client"

import Link from "next/link"
import { useState } from "react"

import { MonoId } from "@/components/desk/mono-id"
import { Money } from "@/components/desk/money"
import { StatusBadge } from "@/components/desk/status-badge"
import { CriticalLines } from "@/components/manager/critical"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { categoryLabel } from "@/lib/labels"
import { useRole } from "@/lib/role"
import { errorLines, workflow, type FraudOutcome, type OpsCase } from "@/lib/workflow"
import { usePoll } from "@/lib/workflow-hooks"

const OUTCOMES: { value: FraudOutcome; label: string }[] = [
  { value: "confirmed_fraud", label: "Confirmed fraud" },
  { value: "not_fraud", label: "Not fraud" },
  { value: "recall_succeeded", label: "Recall succeeded" },
  { value: "recall_failed", label: "Recall failed" },
]

const loadQueue = () => workflow.queue()

function FraudCard({ c, onDone }: { c: OpsCase; onDone: () => void }) {
  const [note, setNote] = useState("")
  const [outcome, setOutcome] = useState<FraudOutcome>("confirmed_fraud")
  const [reason, setReason] = useState("")
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  const id = c.complaint_id
  const closed = c.ops_state === "closed"

  async function run(fn: () => Promise<unknown>, after?: () => void) {
    setBusy(true)
    setErrors([])
    try {
      await fn()
      after?.()
      onDone()
    } catch (e) {
      setErrors(errorLines(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="flex flex-col gap-3 rounded-md border bg-card p-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link href={`/cases/${encodeURIComponent(id)}`} className="text-primary hover:underline">
          <MonoId>{id}</MonoId>
        </Link>
        <span className="text-[13px]">{c.customer_name ?? c.customer_id ?? ""}</span>
        <span className="text-[13px] text-muted-foreground">{categoryLabel(c.category)}</span>
        {c.priority && <StatusBadge value={c.priority} />}
        <StatusBadge value={c.ops_state} />
        {c.refund_amount_myr && <Money value={c.refund_amount_myr} className="ml-auto" />}
      </div>
      {c.fraud_outcome && <p className="text-[13px]">Outcome recorded: {c.fraud_outcome.replace(/_/g, " ")}.</p>}
      {!closed && (
        <div className="flex flex-col gap-3">
          <div>
            <Button variant="secondary" disabled={busy || c.ops_state !== "open"} onClick={() => void run(() => workflow.fraudAck(id))}>
              Acknowledge
            </Button>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <div className="flex min-w-[240px] flex-1 flex-col gap-1">
              <Label htmlFor={`note-${id}`} className="text-xs font-medium text-muted-foreground">
                Investigation note
              </Label>
              <Input id={`note-${id}`} value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
            <Button
              variant="secondary"
              disabled={busy || !note.trim()}
              onClick={() => void run(() => workflow.fraudLog(id, note.trim()), () => setNote(""))}
            >
              Log investigation step
            </Button>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <div className="flex flex-col gap-1">
              <Label htmlFor={`out-${id}`} className="text-xs font-medium text-muted-foreground">
                Outcome
              </Label>
              <select
                id={`out-${id}`}
                value={outcome}
                onChange={(e) => setOutcome(e.target.value as FraudOutcome)}
                className="h-8 rounded-md border bg-background px-2 text-sm"
              >
                {OUTCOMES.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex min-w-[240px] flex-1 flex-col gap-1">
              <Label htmlFor={`reason-${id}`} className="text-xs font-medium text-muted-foreground">
                Reason
              </Label>
              <Input id={`reason-${id}`} value={reason} onChange={(e) => setReason(e.target.value)} />
            </div>
            <Button
              disabled={busy || !reason.trim()}
              onClick={() => void run(() => workflow.fraudOutcome(id, outcome, reason.trim()), () => setReason(""))}
            >
              Record outcome
            </Button>
          </div>
        </div>
      )}
      <CriticalLines lines={errors} />
    </article>
  )
}

export function FraudWorkbench() {
  const { role } = useRole()
  const q = usePoll(loadQueue)
  const items = q.data?.items ?? []

  if (role === "officer") {
    return <p className="p-6 text-[13px] text-status-critical-fg">This page is for the fraud team. Your account does not have access.</p>
  }

  return (
    <div className="workspace-content flex flex-col gap-4">
      <p className="text-[13px] text-muted-foreground">The customer has only received the holding reply.</p>
      <CriticalLines lines={q.errors} />
      {items.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">No cases are with the fraud team. New ones appear here automatically.</p>
      ) : (
        items.map((c) => <FraudCard key={c.complaint_id} c={c} onDone={q.reload} />)
      )}
    </div>
  )
}
