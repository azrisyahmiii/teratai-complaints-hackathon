"use client"

import { TooltipProvider } from "@/components/ui/tooltip"
import { RoleProvider } from "@/lib/role"

import { Sidebar } from "./sidebar"

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <RoleProvider>
      <TooltipProvider>
        <div className="flex min-h-screen flex-col md:flex-row">
          <Sidebar />
          <main className="flex min-w-0 flex-1 flex-col">{children}</main>
        </div>
      </TooltipProvider>
    </RoleProvider>
  )
}
