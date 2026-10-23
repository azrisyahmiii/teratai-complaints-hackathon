"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Suspense } from "react"

import { ROLES, useRole } from "@/lib/role"
import { cn } from "cn"

const NAV = [
  { href: "/queues", label: "Queues" },
  { href: "/intake", label: "New complaint" },
  { href: "/outbox", label: "Outbox" },
]

function ActiveNav() {
  return <NavLinks pathname={usePathname()} />
}

function NavLinks({ pathname }: { pathname: string }) {
  return (
    <>
      {NAV.map((n) => {
        const on = pathname === n.href || (n.href === "/queues" && pathname.startsWith("/cases"))
        return (
          <Link
            key={n.href}
            href={n.href}
            aria-current={on ? "page" : undefined}
            className={cn(
              "rounded-md px-2.5 py-2 text-sm no-underline hover:bg-background",
              on && "bg-accent font-medium text-accent-foreground hover:bg-accent",
            )}
          >
            {n.label}
          </Link>
        )
      })}
    </>
  )
}

export function Sidebar() {
  const { role, setRole } = useRole()
  return (
    <nav
      aria-label="Main"
      className="flex shrink-0 flex-col gap-0.5 border-b bg-card px-3 py-4 md:sticky md:top-0 md:h-screen md:w-[232px] md:border-r md:border-b-0"
    >
      <div className="flex items-center gap-2.5 px-2.5 pt-1 pb-4">
        <span className="flex size-7 items-center justify-center rounded-md bg-primary font-semibold text-primary-foreground">
          T
        </span>
        <div>
          <div className="font-semibold">Teratai Bank</div>
          <div className="text-xs text-muted-foreground">Complaints desk</div>
        </div>
      </div>
      {/* usePathname is runtime data on dynamic routes: it must sit under Suspense (cacheComponents). */}
      <Suspense fallback={<NavLinks pathname="" />}>
        <ActiveNav />
      </Suspense>
      <div className="mt-auto border-t px-2.5 pt-3">
        <div className="mb-1.5 text-xs font-medium text-muted-foreground" id="viewing-as">
          Viewing as
        </div>
        <div className="flex flex-col gap-1" role="group" aria-labelledby="viewing-as">
          {ROLES.map((r) => (
            <button
              key={r.key}
              type="button"
              aria-pressed={role === r.key}
              onClick={() => setRole(r.key)}
              className={cn(
                "cursor-pointer rounded-md border bg-card px-2.5 py-1.5 text-left text-[13px] outline-none focus-visible:ring-2 focus-visible:ring-ring",
                role === r.key && "border-primary bg-accent font-medium text-accent-foreground",
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">No sign-in. Approvals record the name you type.</p>
      </div>
    </nav>
  )
}
