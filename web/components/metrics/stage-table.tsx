import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { Schemas } from "@/lib/api/client"
import { formatMs, formatUsd } from "./fmt"

const label = (s: string) => s.replace(/[_-]/g, " ").replace(/^./, (c) => c.toUpperCase())

export function StageTable({ stages }: { stages: Schemas["MetricStage"][] }) {
  const heads = ["Stage", "Calls", "p50", "p95", "Cost", "Tokens in", "Tokens out"]
  return (
    <div className="overflow-x-auto">
      <Table className="min-w-[640px] text-[13px]">
        <caption className="sr-only">Pipeline stages</caption>
        <TableHeader>
          <TableRow className="hover:bg-muted">
            {heads.map((h) => (
              <TableHead key={h} className={`h-9 bg-muted px-3 text-xs font-medium text-muted-foreground ${h === "Stage" ? "" : "text-right"}`}>{h}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {stages.map((s) => (
            <TableRow key={s.stage} className="h-10">
              <TableCell className="px-3 py-0">{label(s.stage)}</TableCell>
              <TableCell className="px-3 py-0 text-right tabular-nums">{s.count}</TableCell>
              <TableCell className="px-3 py-0 text-right tabular-nums">{s.p50_ms != null ? formatMs(s.p50_ms) : "—"}</TableCell>
              <TableCell className="px-3 py-0 text-right tabular-nums">{s.p95_ms != null ? formatMs(s.p95_ms) : "—"}</TableCell>
              <TableCell className="px-3 py-0 text-right tabular-nums">{formatUsd(s.cost_usd)}</TableCell>
              <TableCell className="px-3 py-0 text-right tabular-nums">{s.tokens_in.toLocaleString("en-US")}</TableCell>
              <TableCell className="px-3 py-0 text-right tabular-nums">{s.tokens_out.toLocaleString("en-US")}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
