"use client"

import Link from "next/link"
import { useState } from "react"

import { MonoId } from "@/components/desk/mono-id"
import { Money } from "@/components/desk/money"
import { CriticalLines } from "@/components/manager/critical"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatDateTimeShort } from "@/lib/format"
import { categoryLabel } from "@/lib/labels"
import { useRole } from "@/lib/role"
import { errorLines, workflow, type OpsCase } from "@/lib/workflow"
import { usePoll } from "@/lib/workflow-hooks"

const loadEsc = () => workflow.escalations()
const loadAudit = () => workflow.audit(200)

function EscalationRow({ c, onDone }: { c: OpsCase; onDone: () => void }) {
  const [reason, setReason] = useState("")
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState<string[]>([])

  async function run(kind: "approve" | "reject") {
    setBusy(true)
    setErrors([])
    try {
      if (kind === "approve") await workflow.managerApprove(c.complaint_id, reason.trim())
      else await workflow.managerReject(c.complaint_id, reason.trim())
      setReason("")
      onDone()
    } catch (e) {
      setErrors(errorLines(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <TableRow>
      <TableCell>
        <Link href={`/cases/${encodeURIComponent(c.complaint_id)}`} className="text-primary hover:underline">
          <MonoId>{c.complaint_id}</MonoId>
        </Link>
      </TableCell>
      <TableCell>{c.customer_name ?? c.customer_id ?? "Unknown"}</TableCell>
      <TableCell>{categoryLabel(c.category)}</TableCell>
      <TableCell>
        <Money value={c.refund_amount_myr} />
      </TableCell>
      <TableCell>{c.escalated_by ?? "Unknown"}</TableCell>
      <TableCell className="max-w-[220px] whitespace-normal">{c.escalation_reason ?? "No reason given"}</TableCell>
      <TableCell className="min-w-[280px] whitespace-normal">
        <div className="flex flex-col gap-2">
          <Label htmlFor={`mr-${c.complaint_id}`} className="text-xs font-medium text-muted-foreground">
            Reason
          </Label>
          <Input id={`mr-${c.complaint_id}`} value={reason} onChange={(e) => setReason(e.target.value)} />
          <CriticalLines lines={errors} />
          <div className="flex flex-wrap gap-2">
            <Button disabled={busy || !reason.trim()} onClick={() => void run("approve")}>
              Approve and send reply
            </Button>
            <Button
              variant="outline"
              className="border-destructive text-destructive hover:bg-status-critical-bg hover:text-destructive"
              disabled={busy || !reason.trim()}
              onClick={() => void run("reject")}
            >
              Reject, send nothing
            </Button>
          </div>
        </div>
      </TableCell>
    </TableRow>
  )
}

export function ManagerConsole() {
  const { role } = useRole()
  const esc = usePoll(loadEsc)
  const audit = usePoll(loadAudit)
  const items = esc.data?.items ?? []

  if (role !== "manager") {
    return <p className="p-6 text-[13px] text-status-critical-fg">This page is for managers. Your account does not have access.</p>
  }

  function refresh() {
    esc.reload()
    audit.reload()
  }

  return (
    <div className="workspace-content flex flex-col gap-6">
      <section className="flex flex-col gap-2">
        <h2 className="text-base font-semibold">Escalations</h2>
        <CriticalLines lines={esc.errors} />
        <div className="rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Case</TableHead>
                <TableHead>Customer</TableHead>
                <TableHead>Category</TableHead>
                <TableHead className="text-right">Refund</TableHead>
                <TableHead>Escalated by</TableHead>
                <TableHead>Reason</TableHead>
                <TableHead>Decision</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="py-6 text-center text-muted-foreground">
                    No escalations are waiting. New ones appear here automatically.
                  </TableCell>
                </TableRow>
              ) : (
                items.map((c) => <EscalationRow key={c.complaint_id} c={c} onDone={refresh} />)
              )}
            </TableBody>
          </Table>
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-base font-semibold">Audit log</h2>
        <CriticalLines lines={audit.errors} />
        <div className="rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Case</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Field</TableHead>
                <TableHead>From</TableHead>
                <TableHead>To</TableHead>
                <TableHead>Reason</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(audit.data?.items ?? []).map((r, i) => (
                <TableRow key={`${r.ts}-${i}`}>
                  <TableCell className="whitespace-nowrap">{formatDateTimeShort(r.ts)}</TableCell>
                  <TableCell>
                    {r.complaint_id ? (
                      <Link href={`/cases/${encodeURIComponent(r.complaint_id)}`} className="text-primary hover:underline">
                        <MonoId>{r.complaint_id}</MonoId>
                      </Link>
                    ) : null}
                  </TableCell>
                  <TableCell>{r.actor}</TableCell>
                  <TableCell>{r.action.replace(/_/g, " ")}</TableCell>
                  <TableCell>{r.field?.replace(/_/g, " ") ?? ""}</TableCell>
                  <TableCell>{r.from ?? ""}</TableCell>
                  <TableCell>{r.to ?? ""}</TableCell>
                  <TableCell className="whitespace-normal">{r.reason ?? ""}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>
    </div>
  )
}
