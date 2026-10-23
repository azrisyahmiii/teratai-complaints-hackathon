import type { ReactNode } from "react"

import { Unavailable } from "./unavailable"
import { formatPct } from "./fmt"
import type { Schemas } from "@/lib/api/client"

export interface Stat {
  label: string
  value: ReactNode
  hint?: string
}

/** Label-left, value-right rows for scalar measures. */
export function StatList({ title, stats }: { title: string; stats: Stat[] }) {
  return (
    <div className="min-w-0">
      <div className="h-9 bg-muted px-3 text-xs font-medium leading-9 text-muted-foreground">{title}</div>
      <dl className="text-[13px]">
        {stats.map((s) => (
          <div key={s.label} className="flex min-h-10 items-center justify-between gap-4 border-b px-3 py-1.5 last:border-b-0">
            <dt>
              {s.label}
              {s.hint && <span className="block text-xs text-muted-foreground">{s.hint}</span>}
            </dt>
            <dd className="text-right tabular-nums">{s.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

/** "12.5% (1 of 8)", or an em dash with the reason when there is nothing to divide. */
export function RateValue({
  rate,
  path,
  map,
}: {
  rate: Schemas["MetricRate"] | null | undefined
  path: string
  map: Record<string, string>
}) {
  if (!rate) return <Unavailable path={path} map={map} />
  if (rate.pct == null) return <Unavailable path={path} map={{ [path]: map[path] ?? "No cases to measure in this selection." }} />
  return (
    <>
      {formatPct(rate.pct)} <span className="text-xs text-muted-foreground">({rate.numerator} of {rate.denominator})</span>
    </>
  )
}
