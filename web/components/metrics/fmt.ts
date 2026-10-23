// Display helpers for the Insights page. Counts and percentages only; money stays a server string.

/** 1, "case" -> "1 case"; 3 -> "3 cases". */
export function plural(n: number, word: string): string {
  return `${n} ${n === 1 ? word : `${word}s`}`
}

/** 12.5 -> "12.5%". */
export function formatPct(pct: number): string {
  return `${pct.toFixed(1)}%`
}

/** Minutes -> "1 h 05 min" / "12 min" / "<1 min". */
export function formatMinutes(min: number): string {
  if (min < 1) return "<1 min"
  const total = Math.round(min)
  if (total < 60) return `${total} min`
  return `${Math.floor(total / 60)} h ${String(total % 60).padStart(2, "0")} min`
}

/** Milliseconds -> "820 ms" / "1.2 s". */
export function formatMs(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`
}

export function formatUsd(value: string): string {
  return `US$${value}`
}

export const LANGUAGE_LABELS: Record<string, string> = { EN: "English", MS: "Malay", MIXED: "Mixed", OTHER: "Other" }

export const REPLY_SOURCE_LABELS: Record<string, string> = {
  llm: "Model, first pass",
  redraft: "Model, redrafted",
  template: "Template fallback",
}

export const TEAM_LABELS: Record<string, string> = {
  approval: "Approval team",
  fraud: "Fraud team",
  auto: "Auto-resolved",
}
