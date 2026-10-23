"use client"

import Link from "next/link"
import { useCallback, useEffect, useRef, useState } from "react"

import { CaseHeader, ComplaintPanel, DecisionSummary, EvidencePanel } from "@/components/desk/case-parts"
import { ReplyPanel } from "@/components/desk/case-reply"
import { CaseTabs } from "@/components/desk/case-tabs"
import { api } from "@/lib/api/client"
import type { CaseDetail } from "@/lib/case"

const POLL_MS = 2000

type Load = { kind: "loading" } | { kind: "missing" } | { kind: "forbidden" } | { kind: "ok"; detail: CaseDetail }

async function fetchCase(id: string): Promise<Load> {
  const { data, response } = await api.GET("/api/cases/{complaint_id}", { params: { path: { complaint_id: id } } })
  if (response.status === 404) return { kind: "missing" }
  if (response.status === 403) return { kind: "forbidden" }
  if (!data) throw new Error("bad response")
  return { kind: "ok", detail: data }
}

function useCase(id: string, paused: boolean) {
  const [load, setLoad] = useState<Load>({ kind: "loading" })
  const [failed, setFailed] = useState(false)
  const alive = useRef(true)

  const reload = useCallback(async () => {
    try {
      const next = await fetchCase(id)
      if (!alive.current) return
      setFailed(false)
      setLoad(next)
    } catch {
      if (alive.current) setFailed(true)
    }
  }, [id])

  const detail = load.kind === "ok" ? load.detail : null
  const status = detail?.case.status
  const state = detail?.case.case_state
  // Poll while the agent works or a person still has to act; never while typing in the edit box.
  const live = load.kind === "loading" || status === "processing" || state === "awaiting_approval"

  useEffect(() => {
    alive.current = true
    const poll = () => void reload()
    poll()
    const t = live && !paused ? setInterval(poll, POLL_MS) : null
    return () => {
      alive.current = false
      if (t) clearInterval(t)
    }
  }, [reload, live, paused])

  return { load, failed, reload }
}

export function CaseView({ id }: { id: string }) {
  const [editing, setEditing] = useState(false)
  const { load, failed, reload } = useCase(id, editing)
  const detail = load.kind === "ok" ? load.detail : null

  if (load.kind === "missing" || load.kind === "forbidden") {
    return (
      <>
        <CaseHeader id={id} detail={null} />
        <div className="p-6 text-[13px]">
          <p className="mb-2 text-status-critical-fg">{load.kind === "forbidden" ? "This case belongs to another team. Your account does not have access." : `No case with the ID ${id} exists.`}</p>
          <Link href="/queues" className="text-primary hover:underline">
            Back to queues
          </Link>
        </div>
      </>
    )
  }

  return (
    <>
      <CaseHeader id={id} detail={detail} />
      <div className="workspace-content flex flex-col">
        {failed && (
          <p role="status" className="text-[13px] text-status-critical-fg">
            Can&apos;t reach the API. Retrying every 2 s.
          </p>
        )}
        {!detail && !failed && <p className="text-[13px] text-muted-foreground">Loading case…</p>}
        {detail?.case.status === "processing" && (
          <p role="status" className="rounded-md border bg-card px-4 py-3 text-[13px]">
            The agent is working on this case. This page updates by itself.
          </p>
        )}
        {detail?.case.status === "error" && (
          <p
            role="alert"
            className="rounded-md border border-status-critical-border bg-status-critical-bg px-4 py-3 text-[13px] text-status-critical-fg"
          >
            The agent could not process this case{detail.error ? `: ${detail.error}` : "."}
          </p>
        )}
        {detail?.case.status === "done" && (
          <>
            <DecisionSummary detail={detail} />
            <div className="grid items-start gap-4 min-[900px]:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
              <div className="flex min-w-0 flex-col gap-4">
                <ComplaintPanel detail={detail} />
                <EvidencePanel detail={detail} />
              </div>
              <div className="min-w-0">
                <ReplyPanel detail={detail} onChanged={reload} onEditingChange={setEditing} />
              </div>
            </div>
            <CaseTabs detail={detail} />
          </>
        )}
      </div>
    </>
  )
}
