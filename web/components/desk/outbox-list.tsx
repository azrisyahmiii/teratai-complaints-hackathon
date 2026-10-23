"use client"

import Link from "next/link"
import { useEffect, useState } from "react"

import { DateTime } from "@/components/desk/date-time"
import { MonoId } from "@/components/desk/mono-id"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { api, type Schemas } from "@/lib/api/client"
import { cn } from "cn"

type Item = Schemas["OutboxItem"]

const POLL_MS = 2000

export function OutboxList() {
  const [items, setItems] = useState<Item[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [pickedId, setPickedId] = useState<number | null>(null)

  useEffect(() => {
    let alive = true
    async function poll() {
      try {
        const { data, error } = await api.GET("/api/outbox")
        if (!alive) return
        if (error || !data) throw new Error("bad response")
        setFailed(false)
        setItems(data)
      } catch {
        if (alive) setFailed(true)
      }
    }
    void poll()
    const t = setInterval(poll, POLL_MS)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  const rows = items ?? []
  const current = rows.find((r) => r.id === pickedId) ?? rows[0]

  return (
    <div className="flex max-w-[1180px] flex-col gap-3 p-6">
      {failed && (
        <p role="status" className="text-[13px] text-status-critical-fg">
          Can&apos;t reach the API. Retrying every 2 s.
        </p>
      )}
      {items && rows.length === 0 && (
        <p className="rounded-md border bg-card px-4 py-8 text-center text-[13px] text-muted-foreground">
          No replies have been sent yet. Auto-resolved replies and approved replies appear here.
        </p>
      )}
      {!items && !failed && <p className="text-[13px] text-muted-foreground">Loading outbox…</p>}

      {rows.length > 0 && current && (
        <div className="flex flex-wrap items-start gap-4">
          <section className="min-w-0 flex-[3_1_480px] overflow-x-auto rounded-md border bg-card">
            <Table className="min-w-[560px] text-[13px]">
              <TableHeader>
                <TableRow className="hover:bg-muted">
                  {["Sent", "Case", "Customer", "Lang", "Authorised by"].map((h) => (
                    <TableHead key={h} className="h-9 bg-muted px-3 text-xs font-medium text-muted-foreground">
                      {h}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow
                    key={r.id}
                    onClick={() => setPickedId(r.id)}
                    aria-selected={r.id === current.id}
                    className={cn("h-10 cursor-pointer hover:bg-accent", r.id === current.id && "bg-accent")}
                  >
                    <TableCell className="px-3 py-0">
                      <DateTime value={r.ts} short />
                    </TableCell>
                    <TableCell className="px-3 py-0">
                      <MonoId>{r.complaint_id}</MonoId>
                    </TableCell>
                    <TableCell className="px-3 py-0">{r.customer_name}</TableCell>
                    <TableCell className="px-3 py-0">
                      <MonoId>{r.language}</MonoId>
                    </TableCell>
                    <TableCell className="px-3 py-0">{r.authorised_by === "agent" ? "Agent (auto)" : r.authorised_by}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </section>

          <section className="min-w-0 flex-[2_1_340px] rounded-md border bg-card">
            <h2 className="border-b px-4 py-3 text-base font-semibold">
              <MonoId className="text-base">{current.complaint_id}</MonoId> · {current.language}
            </h2>
            <div className="whitespace-pre-wrap break-words p-4 leading-relaxed">{current.text}</div>
            <div className="px-4 pb-4 text-xs">
              <Link href={`/cases/${encodeURIComponent(current.complaint_id)}`} className="text-primary hover:underline">
                Open case
              </Link>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
