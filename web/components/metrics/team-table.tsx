import { Money } from "@/components/desk/money"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { Schemas } from "@/lib/api/client"
import { TEAM_LABELS } from "./fmt"

/** Manager only: the three routes side by side. */
export function TeamTable({ teams }: { teams: Schemas["MetricTeam"][] }) {
  const heads = ["Team", "Cases", "Open", "P1 open", "Ack overdue", "Refund total", "Self-check flagged"]
  return (
    <div className="overflow-x-auto">
      <Table className="min-w-[720px] text-[13px]">
        <caption className="sr-only">Team comparison</caption>
        <TableHeader>
          <TableRow className="hover:bg-muted">
            {heads.map((h) => (
              <TableHead key={h} className={`h-9 bg-muted px-3 text-xs font-medium text-muted-foreground ${h === "Team" ? "" : "text-right"}`}>{h}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {teams.map((t) => (
            <TableRow key={t.team} className="h-10">
              <TableCell className="px-3 py-0 font-medium">{TEAM_LABELS[t.team] ?? t.team}</TableCell>
              <TableCell className="px-3 py-0 text-right tabular-nums">{t.cases}</TableCell>
              <TableCell className="px-3 py-0 text-right tabular-nums">{t.open}</TableCell>
              <TableCell className="px-3 py-0 text-right tabular-nums">{t.p1_open}</TableCell>
              <TableCell className="px-3 py-0 text-right tabular-nums">{t.ack_overdue}</TableCell>
              <TableCell className="px-3 py-0"><Money value={t.refund_total_myr} /></TableCell>
              <TableCell className="px-3 py-0 text-right tabular-nums">{t.flagged}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
