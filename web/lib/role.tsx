"use client"

import { createContext, useCallback, useContext, useMemo, useSyncExternalStore } from "react"

export type Role = "officer" | "fraud" | "manager"

export const ROLES: { key: Role; label: string; defaultName: string }[] = [
  { key: "officer", label: "Complaints officer", defaultName: "Aina" },
  { key: "fraud", label: "Fraud analyst", defaultName: "Siti" },
  { key: "manager", label: "Manager", defaultName: "Manager" },
]

const KEY = "teratai.role"
const EVENT = "teratai:role"

function read(): Role {
  try {
    const v = window.localStorage.getItem(KEY)
    if (v === "officer" || v === "fraud" || v === "manager") return v
  } catch {
    // storage blocked: fall back to the default role
  }
  return "officer"
}

function subscribe(cb: () => void) {
  window.addEventListener(EVENT, cb)
  window.addEventListener("storage", cb)
  return () => {
    window.removeEventListener(EVENT, cb)
    window.removeEventListener("storage", cb)
  }
}

interface RoleValue {
  role: Role
  setRole: (r: Role) => void
  defaultName: string
}

const RoleContext = createContext<RoleValue | null>(null)

export function RoleProvider({ children }: { children: React.ReactNode }) {
  const role = useSyncExternalStore(subscribe, read, () => "officer" as Role)
  const setRole = useCallback((r: Role) => {
    try {
      window.localStorage.setItem(KEY, r)
    } catch {
      // storage blocked: the change still applies for this page view via the event below
    }
    window.dispatchEvent(new Event(EVENT))
  }, [])
  const value = useMemo(
    () => ({ role, setRole, defaultName: ROLES.find((x) => x.key === role)?.defaultName ?? "" }),
    [role, setRole],
  )
  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>
}

export function useRole(): RoleValue {
  const v = useContext(RoleContext)
  if (!v) throw new Error("useRole must be used inside RoleProvider")
  return v
}
