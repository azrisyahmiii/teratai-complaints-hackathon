"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Suspense } from "react"
import { BarChart3, Inbox, Leaf, MailCheck, Plus } from "lucide-react"

import { cn } from "cn"
import { LotusMark } from "./lotus-mark"

const NAV = [
  { href: "/queues", label: "Queues", icon: Inbox },
  { href: "/intake", label: "New complaint", icon: Plus },
  { href: "/outbox", label: "Outbox", icon: MailCheck },
  { href: "/metrics", label: "Insights", icon: BarChart3 },
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
              "desk-nav-link",
              on && "is-active",
            )}
          >
            <n.icon className="size-[18px] shrink-0" aria-hidden />
            {n.label}
            {on && <span className="nav-active-dot" aria-hidden />}
          </Link>
        )
      })}
    </>
  )
}

export function Sidebar() {
  return (
    <nav
      aria-label="Main"
      className="desk-sidebar"
    >
      <Link href="/queues" className="desk-brand" aria-label="Teratai Bank complaints desk">
        <LotusMark className="size-11 shrink-0 text-[#DCBD83]" />
        <div>
          <div className="text-[15px] font-medium tracking-[0.12em]">TERATAI BANK</div>
          <div className="mt-1 text-[10px] tracking-[0.18em] text-[#BAC9BF]">COMPLAINTS PLATFORM</div>
        </div>
      </Link>
      <p className="sidebar-section-label">Workspace</p>
      {/* usePathname is runtime data on dynamic routes: it must sit under Suspense (cacheComponents). */}
      <Suspense fallback={<NavLinks pathname="" />}>
        <ActiveNav />
      </Suspense>
      <div className="sidebar-story" aria-hidden="true">
        <Leaf className="mb-2 size-4 text-[#DCBD83]" />
        <p>Every concern<br />deserves care.</p>
        <span>The Teratai way.</span>
      </div>
    </nav>
  )
}
