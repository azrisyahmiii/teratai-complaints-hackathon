"use client"

import { useEffect, useState } from "react"

import { StatusBadge } from "@/components/desk/status-badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { api } from "@/lib/api/client"
import { detailLines, replySourceLine, segmentReply, str, type CaseDetail, type CheckIssue, type TokenVerdict } from "@/lib/case"
import { formatDateTime, formatMoney } from "@/lib/format"
import { useRole } from "@/lib/role"
import { cn } from "cn"

/** Reply text with each checked ID and amount underlined: verified in success colour, unverified in critical. */
export function ReplyTokens({ text, tokens }: { text: string; tokens: TokenVerdict[] }) {
  return (
    <div className="whitespace-pre-wrap leading-relaxed">
      {segmentReply(text, tokens).map((s, i) =>
        s.token ? (
          <span
            key={i}
            className={cn(
              "underline decoration-dotted decoration-2 underline-offset-[3px]",
              s.token.verified ? "decoration-status-success-fg" : "font-medium text-status-critical-fg decoration-status-critical-fg",
            )}
            title={s.token.verified ? "In this case's evidence" : "Not in this case's evidence"}
          >
            {s.text}
          </span>
        ) : (
          <span key={i}>{s.text}</span>
        ),
      )}
    </div>
  )
}

interface Check {
  forText: string
  state: "passed" | "flagged"
  issues: CheckIssue[]
  tokens: TokenVerdict[]
  failed?: boolean
}

type Confirm = "approve" | "edit_approve" | "reject" | null

const DEBOUNCE_MS = 300

function Critical({ lines }: { lines: string[] }) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-1 rounded-[4px] border border-status-critical-border bg-status-critical-bg px-2 py-1.5 text-[13px] leading-snug text-status-critical-fg"
    >
      {lines.map((l, i) => (
        <p key={i}>{l}</p>
      ))}
    </div>
  )
}

function humanLine(d: CaseDetail): string | null {
  const h = d.human_action
  if (!h) return null
  const who = str(h.actor) ?? "A reviewer"
  const at = formatDateTime(str(h.at))
  return str(h.action) === "reject"
    ? `Rejected by ${who} on ${at}. Nothing was sent.`
    : `Approved by ${who} on ${at}. The reply is in the outbox.`
}

function closedLine(d: CaseDetail): string | null {
  const s = d.case.case_state
  if (s === "approved" || s === "rejected") return humanLine(d)
  if (s === "with_fraud_team")
    return "With the fraud team. The holding reply was sent; investigation actions come with the ops platform."
  if (s === "auto_resolved") return "Auto-resolved: the reply was sent without a person."
  return null
}

export function ReplyPanel({
  detail,
  onChanged,
  onEditingChange,
}: {
  detail: CaseDetail
  onChanged: () => Promise<void>
  onEditingChange: (editing: boolean) => void
}) {
  const { defaultName } = useRole()
  const id = detail.case.complaint_id
  const [editing, setEditingRaw] = useState(false)
  const [draft, setDraft] = useState("")
  const [check, setCheck] = useState<Check | null>(null)
  const [reason, setReason] = useState("")
  const [confirm, setConfirm] = useState<Confirm>(null)
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState<string[]>([])

  const actor = defaultName
  const awaiting = detail.case.case_state === "awaiting_approval" && detail.can_act
  const caseFlagged = detail.case.self_check === "flagged"
  const customer = detail.case.customer_name
  const outcome = str(detail.decision?.outcome) ?? detail.case.outcome
  const refund = str(detail.decision?.refund_myr) ?? detail.case.refund_amount_myr

  function setEditing(v: boolean) {
    setEditingRaw(v)
    onEditingChange(v)
  }

  function startEdit() {
    setDraft(detail.reply_text)
    setCheck({
      forText: detail.reply_text,
      state: detail.case.self_check ?? "passed",
      issues: detail.check_issues,
      tokens: detail.tokens,
    })
    setErrors([])
    setEditing(true)
  }

  function cancelEdit() {
    setErrors([])
    setEditing(false)
  }

  // Dry-run the self-check ~300 ms after the last keystroke.
  useEffect(() => {
    if (!editing || !check || check.forText === draft) return
    let alive = true
    const t = setTimeout(async () => {
      try {
        const { data, error } = await api.POST("/api/cases/{complaint_id}/check-reply", {
          params: { path: { complaint_id: id } },
          body: { text: draft },
        })
        if (!alive) return
        if (error || !data) throw new Error("bad response")
        setCheck({ forText: draft, state: data.self_check, issues: data.issues, tokens: data.tokens })
      } catch {
        if (alive) setCheck({ forText: draft, state: "flagged", issues: [], tokens: [], failed: true })
      }
    }, DEBOUNCE_MS)
    return () => {
      alive = false
      clearTimeout(t)
    }
  }, [editing, draft, check, id])

  const pending = editing && check !== null && check.forText !== draft
  const shownState = editing ? (pending ? null : (check?.state ?? null)) : detail.case.self_check
  const issues = editing ? (check && !pending ? check.issues : []) : detail.check_issues
  const tokens = editing ? (check && !pending ? check.tokens : []) : detail.tokens
  const text = editing ? draft : detail.reply_text
  const flaggedNow = editing ? !pending && check?.state === "flagged" : caseFlagged

  async function submit(action: "approve" | "edit_approve" | "reject") {
    setBusy(true)
    setErrors([])
    try {
      const res = await fetch(`/api/cases/${encodeURIComponent(id)}/actions`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "teratai" },
        body: JSON.stringify({
          action,
          ...(reason.trim() ? { reason: reason.trim() } : {}),
          ...(action === "edit_approve" ? { reply_text: draft } : {}),
        }),
      })
      if (res.ok) {
        setConfirm(null)
        setEditing(false)
        setReason("")
        await onChanged()
        return
      }
      const body: unknown = await res.json().catch(() => null)
      setConfirm(null)
      if (res.status === 409) {
        setErrors(["This case is no longer awaiting approval. Its current state is shown above."])
        setEditing(false)
        await onChanged()
      } else {
        setErrors(detailLines(body, `The action failed (HTTP ${res.status}). Try again.`))
      }
    } catch {
      setConfirm(null)
      setErrors(["Can't reach the API. Check the connection and try again."])
    } finally {
      setBusy(false)
    }
  }

  const money = refund && refund !== "0.00" ? formatMoney(refund) : null
  const confirmCopy =
    confirm === "reject"
      ? {
          title: "Reject this case?",
          body: `No reply is sent to ${customer}. You'll be recorded as the reviewer.`,
          go: "Reject, send nothing",
        }
      : {
          title: "Send the reply?",
          body: `Send the ${editing ? "edited " : ""}${
            outcome === "REFUND" && money ? `${money} refund` : outcome === "DECLINE" ? "decline" : "holding"
          } reply to ${customer}? You'll be recorded as the approver.`,
          go: "Approve and send reply",
        }

  const sourceLine = replySourceLine(detail.reply_source, detail.reply_drafts)
  const closed = awaiting ? null : closedLine(detail)
  const lang = detail.case.reply_language

  return (
    <Card className="gap-0 rounded-md py-0 ring-0 border">
      <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
        <h2 className="text-base font-semibold">Reply</h2>
        {lang && (
          <span className="rounded-[4px] border border-status-neutral-border bg-status-neutral-bg px-1.5 font-mono text-xs font-medium text-status-neutral-fg">
            {lang}
          </span>
        )}
        {shownState ? <StatusBadge value={shownState} /> : <span className="text-xs text-muted-foreground">Checking…</span>}
      </div>

      <div className="flex flex-col gap-3 p-4">
        {editing ? (
          <>
            <Label htmlFor="reply-edit" className="text-xs font-medium text-muted-foreground">
              Edit the reply
            </Label>
            <Textarea
              id="reply-edit"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="min-h-[200px] rounded-md text-sm leading-relaxed md:text-sm"
            />
            {check?.failed && <Critical lines={["Couldn't run the self-check. Check the connection and keep editing to retry."]} />}
            {issues.length > 0 && <Critical lines={issues.map((i) => i.message)} />}
            <div>
              <div className="mb-1 text-xs font-medium text-muted-foreground">Preview with checked IDs and amounts</div>
              <div className="rounded-md border bg-muted/40 p-3">
                <ReplyTokens text={text} tokens={tokens} />
              </div>
            </div>
          </>
        ) : (
          <>
            {detail.reply_text ? (
              <ReplyTokens text={text} tokens={tokens} />
            ) : (
              <p className="text-muted-foreground">No reply was written for this case.</p>
            )}
            {issues.length > 0 && <Critical lines={issues.map((i) => i.message)} />}
          </>
        )}
        {sourceLine && !editing && <p className="text-xs text-muted-foreground">{sourceLine}</p>}
      </div>

      <div className="flex flex-col gap-3 border-t p-4">
        {detail.case.case_state === "awaiting_approval" && !detail.can_act && (
          <p className="rounded-md border border-status-warning-border bg-status-warning-bg p-3 text-[13px] text-status-warning-fg">
            {detail.action_block_reason ?? "This case is awaiting an authorised reviewer."}
          </p>
        )}
        {closed && <p className="text-[13px]">{closed}</p>}
        {awaiting && (
          <>
            <div className="flex flex-wrap gap-3">
              <div className="flex min-w-[140px] flex-1 flex-col gap-1">
                <Label htmlFor="approver-name" className="text-xs font-medium text-muted-foreground">
                  Your name
                </Label>
                <Input id="approver-name" value={actor} readOnly />
              </div>
              <div className="flex min-w-[200px] flex-[2] flex-col gap-1">
                <Label htmlFor="approver-reason" className="text-xs font-medium text-muted-foreground">
                  Reason
                </Label>
                <Input
                  id="approver-reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  aria-describedby="reason-hint"
                />
              </div>
            </div>
            <p id="reason-hint" className="-mt-1 text-xs text-muted-foreground">
              A reason is required to reject a case or to send an edited reply.
            </p>
            {errors.length > 0 && <Critical lines={errors} />}
            {flaggedNow && !editing && (
              <p className="text-[13px] text-status-critical-fg">
                The self-check flagged this reply. Edit it so every ID and amount is in the evidence, or reject the case.
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              {editing ? (
                <Button
                  disabled={busy || pending || flaggedNow || !reason.trim() || !actor}
                  onClick={() => setConfirm("edit_approve")}
                >
                  Approve edited reply
                </Button>
              ) : (
                <Button disabled={busy || caseFlagged || !actor} onClick={() => setConfirm("approve")}>
                  Approve and send reply
                </Button>
              )}
              {editing ? (
                <Button variant="secondary" disabled={busy} onClick={cancelEdit}>
                  Cancel edit
                </Button>
              ) : (
                <Button variant="secondary" disabled={busy} onClick={startEdit}>
                  Edit and approve
                </Button>
              )}
              <Button
                variant="outline"
                className="border-destructive text-destructive hover:bg-status-critical-bg hover:text-destructive"
                disabled={busy || !actor}
                onClick={() => setConfirm("reject")}
              >
                Reject, send nothing
              </Button>
            </div>
          </>
        )}
      </div>

      <Dialog open={confirm !== null} onOpenChange={(o) => !o && !busy && setConfirm(null)}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{confirmCopy.title}</DialogTitle>
            <DialogDescription>{confirmCopy.body}</DialogDescription>
          </DialogHeader>
          {confirm === "reject" && (
            <div className="flex flex-col gap-1">
              <Label htmlFor="reject-reason" className="text-xs font-medium text-muted-foreground">
                Reason
              </Label>
              <Input id="reject-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
              {!reason.trim() && <p className="text-xs text-muted-foreground">Add a reason to reject this case.</p>}
            </div>
          )}
          <DialogFooter>
            <Button variant="secondary" disabled={busy} onClick={() => setConfirm(null)}>
              Keep reviewing
            </Button>
            {confirm === "reject" ? (
              <Button
                variant="outline"
                className="border-destructive text-destructive hover:bg-status-critical-bg hover:text-destructive"
                disabled={busy || !reason.trim()}
                onClick={() => void submit("reject")}
              >
                {confirmCopy.go}
              </Button>
            ) : (
              <Button disabled={busy} onClick={() => confirm && void submit(confirm)}>
                {confirmCopy.go}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
