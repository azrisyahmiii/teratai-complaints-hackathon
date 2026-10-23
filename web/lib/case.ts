// Helpers for the case page. Display only: the backend decides, the page explains.
import type { Schemas } from "@/lib/api/client"
import { formatMoney } from "@/lib/format"
import { categoryLabel, outcomeLabel, routeLabel } from "@/lib/labels"

export type CaseDetail = Schemas["CaseDetail"]
export type EventView = Schemas["EventView"]
export type TokenVerdict = Schemas["TokenVerdict"]
export type CheckIssue = Schemas["CheckIssue"]

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

export const str = (v: unknown): string | null => (typeof v === "string" && v !== "" ? v : null)

/** The calc string can arrive with a UTF-8 minus sign decoded as cp1252; show the real sign. */
export function fixCalc(calc: string | null): string | null {
  if (!calc) return null
  return calc
    .replace(/âˆ’/g, "−")
    .replace(/ - /g, " − ")
    .replace(/\d+\.\d{2}/g, (n) => formatMoney(n).slice(2))
}

function dayParts(d: string | null | undefined) {
  const m = d ? /^(\d{4})-(\d{2})-(\d{2})/.exec(d) : null
  return m ? { y: m[1], m: Number(m[2]) - 1, d: Number(m[3]) } : null
}

/** "2026-07-17" -> "17 Jul 2026" */
export function dayLong(d: string | null | undefined): string {
  const p = dayParts(d)
  return p ? `${p.d} ${MONTHS[p.m]} ${p.y}` : "—"
}

/** "16–18 Jul 2026", or "30 Jun – 2 Jul 2026" across months. */
export function dayRange(a: string | null | undefined, b: string | null | undefined): string {
  const x = dayParts(a)
  const y = dayParts(b)
  if (!x || !y) return "—"
  if (a === b) return dayLong(a)
  if (x.m === y.m && x.y === y.y) return `${x.d}–${y.d} ${MONTHS[y.m]} ${y.y}`
  return `${dayLong(a)} – ${dayLong(b)}`
}

/** Why the case went to this route, in one line (DESIGN.md writing rules). */
export function routeReason(d: CaseDetail): string {
  const route = str(d.decision?.route) ?? d.case.route
  const outcome = str(d.decision?.outcome) ?? d.case.outcome
  if (d.decision?.needs_info === true) return "Not enough to decide: a person follows up with the customer"
  if (route === "FRAUD_TEAM") return "Card or scam case: fraud team investigates"
  if (route === "AUTO_RESOLVE") return "Within the auto-resolve rules"
  if (route === "HUMAN_APPROVAL") {
    if (outcome === "REFUND") return "Refund above the RM500.00 auto limit"
    if (outcome === "DECLINE") return "Declines need a person's sign-off"
    return "A person signs this off"
  }
  return "—"
}

export function classifierLine(d: CaseDetail): string | null {
  const conf = d.decision?.category_conf
  const source = str(d.understanding?.source)
  const who = source === "classifier" ? "Classifier" : source === "llm" ? "Language model" : source
  if (typeof conf === "number" && who) return `${who} ${conf.toFixed(2)}`
  return who
}

export function replySourceLine(source: string | null | undefined, drafts: number): string | null {
  if (source === "template") return "Template fallback"
  if (source === "redraft") return "Redrafted once"
  if (source === "llm") return drafts > 1 ? "Written by the LLM, redrafted" : "Written by the LLM, passed first time"
  return null
}

export function stateOf(d: CaseDetail): string | null {
  return d.case.status === "done" ? (d.case.case_state ?? null) : d.case.status
}

const STAGE_LABELS: Record<string, string> = {
  intake: "Intake",
  understand: "Understand",
  resolve: "Resolve dates",
  match: "Match",
  investigate: "Investigate",
  decide: "Decide",
  reply: "Reply and self-check",
}
export const stageLabel = (s: string | null) => (s ? (STAGE_LABELS[s] ?? s.replace(/^./, (c) => c.toUpperCase())) : "—")

export function tookLabel(ms: number): string {
  if (ms <= 0) return "<1 ms"
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`
}

const asRecord = (v: unknown): Record<string, unknown> => (v && typeof v === "object" ? (v as Record<string, unknown>) : {})

/** A short result for one agent stage. Falls back to OK / Failed. */
export function stageResult(e: EventView, d: CaseDetail): string {
  const p = asRecord(e.payload)
  if (!e.ok) return str(p.error) ?? str(p.reason) ?? "Failed"
  switch (e.stage) {
    case "understand": {
      const cat = str(asRecord(p.clues).category)
      const tier = str(p.tier)
      return cat ? `${categoryLabel(cat)}${tier ? ` · ${tier}` : ""}` : "OK"
    }
    case "resolve": {
      const w = d.window
      return str(w?.phrase) ? `"${str(w?.phrase)}" → ${dayLong(str(w?.exact_day) ?? str(w?.start))}` : "OK"
    }
    case "match": {
      const n = Array.isArray(p.candidates) ? p.candidates.length : null
      const txn = str(p.txn_id)
      if (n === null) return str(p.status) ?? "OK"
      return `${n} ${n === 1 ? "candidate" : "candidates"}${txn ? ` · ${txn}` : ""}`
    }
    case "decide": {
      const dec = d.decision
      if (!dec) return "OK"
      const refund = str(dec.refund_myr)
      return [outcomeLabel(str(dec.outcome)) + (refund && refund !== "0.00" ? ` ${formatMoney(refund)}` : ""), str(dec.priority), routeLabel(str(dec.route))]
        .filter(Boolean)
        .join(" · ")
    }
    case "reply": {
      const src = replySourceLine(str(p.source), typeof p.drafts === "number" ? p.drafts : 1)
      const check = p.check_ok === true ? "self-check passed" : p.check_ok === false ? "self-check flagged" : null
      const cost = Number(e.cost_usd) > 0 ? `$${e.cost_usd}` : null
      return [src, check, cost].filter(Boolean).join(" · ") || "OK"
    }
    default:
      return "OK"
  }
}

/** Segments of the reply text: plain runs and checked tokens, by offsets. Ignores overlaps or out-of-range tokens. */
export type Segment = { text: string; token?: TokenVerdict }
export function segmentReply(text: string, tokens: TokenVerdict[]): Segment[] {
  const out: Segment[] = []
  let pos = 0
  for (const t of [...tokens].sort((a, b) => a.start - b.start)) {
    if (t.start < pos || t.end > text.length || t.end <= t.start) continue
    if (t.start > pos) out.push({ text: text.slice(pos, t.start) })
    out.push({ text: text.slice(t.start, t.end), token: t })
    pos = t.end
  }
  if (pos < text.length) out.push({ text: text.slice(pos) })
  return out
}

/** Error detail from the organisers' action endpoint: a string, or a list of strings. */
export function detailLines(body: unknown, fallback: string): string[] {
  const detail = asRecord(body).detail
  if (typeof detail === "string") return [detail]
  if (Array.isArray(detail)) {
    const lines = detail.map((x) => (typeof x === "string" ? x : str(asRecord(x).msg))).filter((x): x is string => !!x)
    if (lines.length) return lines
  }
  return [fallback]
}
