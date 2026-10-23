// Typed helpers for /api/ops/* and /api/audit (not in the generated schema yet).
import { detailLines } from "@/lib/case"

export type OpsState = "open" | "escalated" | "acknowledged" | "investigating" | "closed"
export type FraudOutcome = "confirmed_fraud" | "not_fraud" | "recall_succeeded" | "recall_failed"

export interface OpsExtra {
  ops_state: OpsState
  assigned_to: string | null
  escalated_by: string | null
  escalation_reason: string | null
  fraud_outcome: FraudOutcome | null
  over_my_limit: boolean
}

export interface OpsCase extends OpsExtra {
  complaint_id: string
  customer_id?: string
  customer_name?: string | null
  category?: string | null
  refund_amount_myr?: string | null
  priority?: string | null
  case_state?: string
}

export interface TrailStep {
  ts: string
  from: string
  to: string
  action: string
  note: string | null
}

export interface AuditRow {
  ts: string
  complaint_id: string | null
  actor: string
  role: string | null
  action: string
  field: string | null
  from: string | null
  to: string | null
  reason: string | null
}

export class WorkflowError extends Error {
  status: number
  lines: string[]
  constructor(status: number, lines: string[]) {
    super(lines.join(" "))
    this.status = status
    this.lines = lines
  }
}

async function call<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    cache: "no-store",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Requested-With": "teratai" },
    ...(method === "POST" ? { body: JSON.stringify(body ?? {}) } : {}),
  })
  if (res.status === 401 && typeof window !== "undefined") window.location.replace("/login")
  const data: unknown = await res.json().catch(() => null)
  if (!res.ok) throw new WorkflowError(res.status, detailLines(data, `The request failed (HTTP ${res.status}).`))
  return data as T
}

const enc = encodeURIComponent
const act = (id: string, verb: string, body?: unknown) => call<OpsCase>("POST", `/ops/cases/${enc(id)}/${verb}`, body)

export const workflow = {
  queue: () => call<{ items: OpsCase[]; counts: Record<string, number> }>("GET", "/ops/queue"),
  escalations: () => call<{ items: OpsCase[] }>("GET", "/ops/escalations"),
  opsCase: (id: string) => call<{ ops: OpsExtra; trail: TrailStep[] }>("GET", `/ops/cases/${enc(id)}`),
  audit: (limit = 200) => call<{ items: AuditRow[] }>("GET", `/audit?limit=${limit}`),
  escalate: (id: string, reason: string) => act(id, "escalate", { reason }),
  managerApprove: (id: string, reason: string) => act(id, "manager-approve", { reason }),
  managerReject: (id: string, reason: string) => act(id, "manager-reject", { reason }),
  fraudAck: (id: string) => act(id, "fraud-ack"),
  fraudLog: (id: string, note: string) => act(id, "fraud-log", { note }),
  fraudOutcome: (id: string, outcome: FraudOutcome, reason: string) => act(id, "fraud-outcome", { outcome, reason }),
}

export function errorLines(e: unknown): string[] {
  return e instanceof WorkflowError ? e.lines : ["Can't reach the API. Check the connection and try again."]
}
