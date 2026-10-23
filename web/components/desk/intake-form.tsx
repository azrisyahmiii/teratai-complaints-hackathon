"use client"

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"

import { DateTime } from "@/components/desk/date-time"
import { Money } from "@/components/desk/money"
import { MonoId } from "@/components/desk/mono-id"
import { StatusBadge } from "@/components/desk/status-badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { api, type Schemas } from "@/lib/api/client"
import { README_EXAMPLE, parseComplaintRow, type ComplaintFields } from "@/lib/csv-row"
import { categoryLabel } from "@/lib/labels"
import { cn } from "cn"

type Detail = Schemas["CaseDetail"]

const POLL_MS = 1000

const STAGE_LABELS: Record<string, string> = {
  understand: "Understand",
  extract: "Extract",
  resolve: "Dates",
  match: "Match",
  investigate: "Investigate",
  decide: "Decide",
  reply: "Reply + self-check",
}

interface Sent {
  id: string
  existing: boolean
}

interface Recent {
  id: string
  state: string | null
}

function stateOf(d: Detail | null): string | null {
  if (!d) return "processing"
  return d.case.status === "done" ? (d.case.case_state ?? "done") : d.case.status
}

function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)} s`
}

function stagesOf(d: Detail | null) {
  const out: { stage: string; label: string; ms: number; ok: boolean }[] = []
  for (const e of d?.events ?? []) {
    if (!e.stage || e.actor !== "agent" || !(e.stage in STAGE_LABELS)) continue
    const prev = out.find((s) => s.stage === e.stage)
    if (prev) {
      prev.ms += e.latency_ms
      prev.ok = prev.ok && e.ok
    } else {
      out.push({ stage: e.stage, label: STAGE_LABELS[e.stage], ms: e.latency_ms, ok: e.ok })
    }
  }
  return out
}

function errorText(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === "string" ? d : typeof d === "object" && d && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
      .filter(Boolean)
      .join(" ")
  }
  return `The API answered ${status}.`
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </>
  )
}

export function IntakeForm() {
  const [raw, setRaw] = useState("")
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState<Sent | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [apiError, setApiError] = useState<string | null>(null)
  const [recent, setRecent] = useState<Recent[]>([])

  const parsed = useMemo(() => (raw.trim() === "" ? null : parseComplaintRow(raw)), [raw])
  const canSend = parsed?.ok === true && !sending

  async function send(fields: ComplaintFields) {
    setSending(true)
    setApiError(null)
    setSent(null)
    setDetail(null)
    try {
      const res = await fetch("/agent/complaints", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      })
      const body: unknown = await res.json().catch(() => ({}))
      if (!res.ok) {
        const d = typeof body === "object" && body && "detail" in body ? (body as { detail: unknown }).detail : null
        setApiError(errorText(d, res.status))
        return
      }
      const id = typeof body === "object" && body && "complaint_id" in body ? String((body as { complaint_id: unknown }).complaint_id) : fields.complaint_id
      setDetail(null)
      setSent({ id, existing: res.status === 200 })
      setRecent((r) => [{ id, state: "processing" }, ...r.filter((x) => x.id !== id)].slice(0, 5))
    } catch {
      setApiError("Can't reach the API. Check that the backend is running, then send again.")
    } finally {
      setSending(false)
    }
  }

  const sentId = sent?.id
  const finished = detail?.case.status === "done" || detail?.case.status === "error"

  useEffect(() => {
    if (!sentId) return
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined

    async function poll() {
      let done = false
      try {
        const { data } = await api.GET("/api/cases/{complaint_id}", { params: { path: { complaint_id: sentId! } } })
        if (!alive) return
        if (data) {
          setDetail(data)
          const st = data.case.status === "done" ? (data.case.case_state ?? "done") : data.case.status
          setRecent((r) => r.map((x) => (x.id === sentId ? { ...x, state: st } : x)))
          done = data.case.status !== "processing"
        }
      } catch {
        // keep polling; the API may be restarting
      }
      if (alive && !done) timer = setTimeout(poll, POLL_MS)
    }

    void poll()
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
    }
  }, [sentId])

  const stages = stagesOf(detail)
  const c = detail?.case

  return (
    <div className="flex max-w-[1180px] flex-wrap items-start gap-4 p-6">
      <section className="min-w-0 flex-[1_1_440px] rounded-md border bg-card">
        <h2 className="border-b px-4 py-3 text-base font-semibold">Paste a complaints.csv row or JSON</h2>
        <div className="flex flex-col gap-3 p-4">
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">Row as given (header optional)</span>
            <Textarea
              value={raw}
              onChange={(e) => setRaw(e.target.value)}
              spellCheck={false}
              className="min-h-[140px] bg-card font-mono text-[12.5px] leading-normal"
            />
          </label>
          <p className="text-xs text-muted-foreground">
            Paste it exactly as the judge gives it. Quoted text with commas and line breaks is fine.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button disabled={!canSend} onClick={() => parsed?.ok && void send(parsed.fields)}>
              {sending ? "Sending…" : "Send to the agent"}
            </Button>
            <Button variant="secondary" onClick={() => setRaw(README_EXAMPLE)}>
              Paste the README example
            </Button>
          </div>
        </div>
      </section>

      <div className="flex min-w-0 flex-[1_1_380px] flex-col gap-4">
        <section className="rounded-md border bg-card">
          <h2 className="border-b px-4 py-3 text-base font-semibold">Check before sending</h2>
          <div className="p-4">
            {parsed === null && <p className="text-[13px] text-muted-foreground">The parsed fields appear here as you type.</p>}
            {parsed?.ok === false && (
              <p role="alert" className="rounded-[4px] border border-status-critical-border bg-status-critical-bg p-2 text-[13px] leading-snug text-status-critical-fg">
                {parsed.error}
              </p>
            )}
            {parsed?.ok && (
              <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-2 text-[13px]">
                <Field label="Complaint ID">
                  <MonoId>{parsed.fields.complaint_id}</MonoId>
                </Field>
                <Field label="Customer">
                  <MonoId>{parsed.fields.customer_id}</MonoId>
                </Field>
                <Field label="Received">
                  <DateTime value={parsed.fields.received_at} />
                  {!/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(parsed.fields.received_at) && (
                    <span className="text-muted-foreground"> as given: {parsed.fields.received_at || "empty"}</span>
                  )}
                </Field>
                <Field label="Channel">{parsed.fields.channel || "—"}</Field>
                <Field label="Subject">{parsed.fields.subject || "—"}</Field>
                <Field label="Text">
                  <span className="whitespace-pre-wrap">{parsed.fields.text || "—"}</span>
                </Field>
              </dl>
            )}
            {apiError && (
              <p role="alert" className="mt-3 rounded-[4px] border border-status-critical-border bg-status-critical-bg p-2 text-[13px] leading-snug text-status-critical-fg">
                {apiError}
              </p>
            )}
          </div>
        </section>

        {sent && (
          <section className="rounded-md border bg-card" aria-live="polite">
            <h2 className="flex flex-wrap items-center gap-2 border-b px-4 py-3 text-base font-semibold">
              <MonoId className="text-base">{sent.id}</MonoId>
              <span aria-hidden>·</span>
              <StatusBadge value={stateOf(detail)} />
            </h2>
            <div className="flex flex-col gap-1 px-4 py-3">
              {sent.existing && (
                <p className="mb-2 rounded-[4px] border border-status-warning-border bg-status-warning-bg p-2 text-[13px] text-status-warning-fg">
                  Already received: this complaint ID was sent before. Showing the existing case.
                </p>
              )}
              {stages.length === 0 && !finished && <p className="py-1.5 text-[13px] text-muted-foreground">Waiting for the first stage…</p>}
              {stages.map((s) => (
                <div key={s.stage} className="flex items-center gap-2.5 py-1.5 text-[13px]">
                  <span
                    aria-hidden
                    className={cn("size-2 rounded-full", s.ok ? "bg-status-success-fg" : "bg-status-critical-fg")}
                  />
                  {s.label}
                  {!s.ok && <span className="text-status-critical-fg">no result</span>}
                  <span className="ml-auto tabular-nums text-muted-foreground">{seconds(s.ms)}</span>
                </div>
              ))}
              {!finished && stages.length > 0 && (
                <div className="flex items-center gap-2.5 py-1.5 text-[13px] text-muted-foreground">
                  <span aria-hidden className="size-2 rounded-full bg-border" />
                  Working…
                </div>
              )}

              {detail?.case.status === "error" && (
                <p className="mt-2 rounded-[4px] border border-status-critical-border bg-status-critical-bg p-2 text-[13px] text-status-critical-fg">
                  The agent could not finish this complaint{detail.error ? `: ${detail.error}` : "."}
                </p>
              )}

              {c && c.status === "done" && (
                <dl className="mt-2 grid grid-cols-[110px_1fr] items-center gap-x-3 gap-y-2 border-t pt-3 text-[13px]">
                  <Field label="Priority">
                    <StatusBadge value={c.priority} />
                  </Field>
                  <Field label="Category">{categoryLabel(c.category)}</Field>
                  <Field label="Refund">
                    <Money value={c.refund_amount_myr} className="text-left" />
                  </Field>
                  <Field label="Self-check">
                    <StatusBadge value={c.self_check} />
                  </Field>
                </dl>
              )}

              <div className="mt-2 text-[13px]">
                <Link href={`/cases/${encodeURIComponent(sent.id)}`} className="text-primary hover:underline">
                  Open case {sent.id}
                </Link>
              </div>
            </div>
          </section>
        )}

        {recent.length > 0 && (
          <section className="rounded-md border bg-card">
            <h2 className="border-b px-4 py-2.5 text-[13px] font-medium text-muted-foreground">Sent in this page view</h2>
            <ul className="divide-y">
              {recent.map((r) => (
                <li key={r.id} className="flex items-center gap-3 px-4 py-2 text-[13px]">
                  <MonoId>{r.id}</MonoId>
                  <StatusBadge value={r.state} />
                  <Link href={`/cases/${encodeURIComponent(r.id)}`} className="ml-auto text-primary hover:underline">
                    Open case
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  )
}
