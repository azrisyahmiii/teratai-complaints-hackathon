// Human labels for enums (DESIGN.md §3). Raw values appear only in trace and JSON views.

export const CATEGORY_LABELS: Record<string, string> = {
  DUPLICATE_CHARGE: "Duplicate charge",
  FAILED_TRANSFER: "Failed transfer",
  ATM_NOT_DISPENSED: "ATM cash not dispensed",
  UNAUTHORISED_CARD: "Unauthorised card payment",
  SCAM_TRANSFER: "Scam transfer",
  FEE_DISPUTE: "Fee dispute",
  SERVICE_QUALITY: "Service quality",
}

export const OUTCOME_LABELS: Record<string, string> = {
  REFUND: "Refund",
  DECLINE: "Decline",
  INVESTIGATE: "Investigate",
  INFO_ONLY: "Information only",
}

export const ROUTE_LABELS: Record<string, string> = {
  AUTO_RESOLVE: "Auto-resolve",
  HUMAN_APPROVAL: "Human approval",
  FRAUD_TEAM: "Fraud team",
}

export const FLAG_LABELS: Record<string, string> = {
  check_flagged: "Self-check flagged",
  injection_suspected: "Injection suspected",
  vulnerable: "Vulnerable 65+",
  needs_info: "Needs information",
  wrong_customer: "Wrong customer",
  degraded: "Degraded",
  not_complaint: "Not a complaint",
  channel_unknown: "Channel unknown",
}

const label = (map: Record<string, string>, v: string | null | undefined) => (v ? (map[v] ?? v) : "—")
export const categoryLabel = (v?: string | null) => label(CATEGORY_LABELS, v)
export const outcomeLabel = (v?: string | null) => label(OUTCOME_LABELS, v)
export const routeLabel = (v?: string | null) => label(ROUTE_LABELS, v)
export const flagLabel = (v: string) => FLAG_LABELS[v] ?? v.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())
