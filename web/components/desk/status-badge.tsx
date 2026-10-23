import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "cn"

type Tone = "critical" | "warning" | "info" | "success" | "neutral"

// Full class strings so Tailwind can see them.
const TONE: Record<Tone, string> = {
  critical: "border-status-critical-border bg-status-critical-bg text-status-critical-fg",
  warning: "border-status-warning-border bg-status-warning-bg text-status-warning-fg",
  info: "border-status-info-border bg-status-info-bg text-status-info-fg",
  success: "border-status-success-border bg-status-success-bg text-status-success-fg",
  neutral: "border-status-neutral-border bg-status-neutral-bg text-status-neutral-fg",
}

interface Def {
  label: string
  tone: Tone
  tip?: string
}

// DESIGN.md §3. Keys are the data values.
const DEFS: Record<string, Def> = {
  auto_resolved: { label: "Auto-resolved", tone: "success" },
  awaiting_approval: { label: "Awaiting approval", tone: "info" },
  with_fraud_team: { label: "With fraud team", tone: "critical" },
  approved: { label: "Approved", tone: "success" },
  rejected: { label: "Rejected", tone: "neutral" },
  needs_info: { label: "Needs information", tone: "warning" },
  escalated: { label: "Escalated to manager", tone: "warning" },
  P1: { label: "P1", tone: "critical", tip: "Urgent" },
  P2: { label: "P2", tone: "warning", tip: "High" },
  P3: { label: "P3", tone: "neutral", tip: "Normal" },
  passed: { label: "Self-check passed", tone: "success" },
  flagged: { label: "Self-check flagged", tone: "critical" },
  processing: { label: "Processing", tone: "neutral" },
  error: { label: "Error", tone: "critical" },
}

export function StatusBadge({ value, className }: { value: string | null | undefined; className?: string }) {
  if (!value) return <span className="text-muted-foreground">—</span>
  const def = DEFS[value] ?? { label: value, tone: "neutral" as Tone }
  const cls = cn("h-[22px] rounded-[4px] px-1.5 font-medium", TONE[def.tone], className)
  if (!def.tip) return <Badge className={cls}>{def.label}</Badge>
  return (
    <Tooltip>
      <TooltipTrigger render={<Badge className={cls} tabIndex={0} />}>{def.label}</TooltipTrigger>
      <TooltipContent>{def.tip}</TooltipContent>
    </Tooltip>
  )
}
