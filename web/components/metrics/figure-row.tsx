import type { ReactNode } from "react"

import { cn } from "cn"

export interface Figure {
  label: string
  value: ReactNode
  sub: string
  red?: boolean
}

/** Compact headline figures, same idiom as the Queues page. */
export function FigureRow({ figures }: { figures: Figure[] }) {
  return (
    <section aria-label="Figures" className="queue-figures">
      {figures.map((f) => (
        <div key={f.label} className="queue-figure">
          <div className="text-xs font-medium text-muted-foreground">{f.label}</div>
          <div className={cn("queue-figure-value", f.red && "text-status-critical-fg")}>{f.value}</div>
          <div className="mt-2 text-xs leading-relaxed text-muted-foreground">{f.sub}</div>
        </div>
      ))}
    </section>
  )
}
