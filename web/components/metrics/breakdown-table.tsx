import { StatusBadge } from "@/components/desk/status-badge"
import { Money } from "@/components/desk/money"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { Schemas } from "@/lib/api/client"
import { formatDayShort } from "@/lib/format"
import { categoryLabel, outcomeLabel, routeLabel } from "@/lib/labels"
import { LANGUAGE_LABELS, REPLY_SOURCE_LABELS } from "./fmt"

type Bucket = Schemas["MetricBucket"]
export type BucketKind = "category" | "outcome" | "route" | "state" | "priority" | "language" | "source" | "day" | "plain"

function KeyLabel({ kind, value }: { kind: BucketKind; value: string }) {
  switch (kind) {
    case "category": return <>{categoryLabel(value)}</>
    case "outcome": return <>{outcomeLabel(value)}</>
    case "route": return <>{routeLabel(value)}</>
    case "state":
    case "priority": return <StatusBadge value={value} />
    case "language": return <>{LANGUAGE_LABELS[value] ?? value}</>
    case "source": return <>{REPLY_SOURCE_LABELS[value] ?? value}</>
    case "day": return <>{formatDayShort(`${value}T00:00`)}</>
    default: return <>{value}</>
  }
}

/** Label | count | share bar | amount. Bar widths come from counts only. */
export function BreakdownTable({
  title,
  rows,
  kind,
  amountLabel,
}: {
  title: string
  rows: Bucket[]
  kind: BucketKind
  amountLabel?: string
}) {
  const max = Math.max(1, ...rows.map((r) => r.count))
  const showAmount = amountLabel != null
  return (
    <div className="min-w-0">
      <Table className="text-[13px]">
        <caption className="sr-only">{title}</caption>
        <TableHeader>
          <TableRow className="hover:bg-muted">
            <TableHead className="h-9 bg-muted px-3 text-xs font-medium text-muted-foreground">{title}</TableHead>
            <TableHead className="h-9 w-14 bg-muted px-3 text-right text-xs font-medium text-muted-foreground">Cases</TableHead>
            <TableHead className="h-9 w-[22%] bg-muted px-3 text-xs font-medium text-muted-foreground"><span className="sr-only">Share</span></TableHead>
            {showAmount && (
              <TableHead className="h-9 bg-muted px-3 text-right text-xs font-medium text-muted-foreground">{amountLabel}</TableHead>
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.key} className="h-10">
              <TableCell className="px-3 py-0"><KeyLabel kind={kind} value={r.key} /></TableCell>
              <TableCell className="px-3 py-0 text-right tabular-nums">{r.count}</TableCell>
              <TableCell className="px-3 py-0" aria-hidden>
                <div className="h-1.5 w-full">
                  <div
                    className="h-full rounded-r-[4px] bg-muted-foreground/70"
                    style={{ width: `${r.count > 0 ? Math.max(3, (r.count / max) * 100) : 0}%` }}
                  />
                </div>
              </TableCell>
              {showAmount && (
                <TableCell className="px-3 py-0">
                  {r.amount_myr != null ? <Money value={r.amount_myr} /> : <span className="block text-right text-muted-foreground">—</span>}
                </TableCell>
              )}
            </TableRow>
          ))}
          {rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={showAmount ? 4 : 3} className="px-3 py-3 text-xs text-muted-foreground">No cases in this selection.</TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  )
}
