"use client"

import { Suspense, useEffect } from "react"
import { usePathname, useRouter } from "next/navigation"
import { TooltipProvider } from "@/components/ui/tooltip"
import { RoleProvider, useSession } from "@/lib/role"

import { Sidebar } from "./sidebar"
import { StaffAccount } from "./staff-account"

function SessionGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const { user, status, refresh } = useSession()
  const isLogin = pathname === "/login"

  useEffect(() => {
    if (status !== "ready") return
    if (!user && !isLogin) router.replace("/login")
    if (user && isLogin) router.replace("/queues")
  }, [user, status, isLogin, router])

  if (isLogin) return children
  if (status === "error") return (
    <div className="session-wait" role="alert">
      <p>We couldn&apos;t verify your session. Check the connection and try again.</p>
      <button className="text-primary underline" onClick={() => void refresh()}>Retry connection</button>
    </div>
  )
  if (!user || status !== "ready") return <div className="session-wait" role="status">Verifying your staff session…</div>
  return (
    <>
      <a href="#workspace" className="skip-link">Skip to workspace</a>
      <div className="desk-shell flex min-h-screen flex-col md:flex-row">
        <Sidebar />
        <main id="workspace" tabIndex={-1} className="workspace flex min-w-0 flex-1 flex-col outline-none">
          <StaffAccount />
          {children}
        </main>
      </div>
    </>
  )
}

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <RoleProvider>
      <TooltipProvider>
        <Suspense fallback={<div className="session-wait" role="status">Opening Teratai Bank…</div>}>
          <SessionGate>{children}</SessionGate>
        </Suspense>
      </TooltipProvider>
    </RoleProvider>
  )
}
