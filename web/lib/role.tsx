"use client"

import { createContext, useCallback, useContext, useEffect, useState } from "react"
import type { Schemas } from "@/lib/api/client"

export type Role = Schemas["StaffUser"]["role"]
type User = Schemas["StaffUser"]

interface SessionValue {
  user: User | null
  status: "loading" | "ready" | "error"
  refresh: () => Promise<void>
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const SessionContext = createContext<SessionValue | null>(null)

export function RoleProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [status, setStatus] = useState<SessionValue["status"]>("loading")
  const refresh = useCallback(() => {
    return fetch("/api/me", { cache: "no-store" }).then(async (r): Promise<User | null> => {
      if (r.status === 401) return null
      if (!r.ok) throw new Error("Could not verify session")
      return r.json()
    }).then((current) => {
      setUser(current)
      setStatus("ready")
    }).catch(() => {
      setUser(null)
      setStatus("error")
    })
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  async function login(username: string, password: string) {
    const r = await fetch("/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "teratai" },
      body: JSON.stringify({ username, password }),
    })
    if (!r.ok) {
      const body = await r.json().catch(() => null)
      throw new Error(typeof body?.detail === "string" ? body.detail : "Sign-in is unavailable. Please try again.")
    }
    setUser(await r.json())
    setStatus("ready")
    // A full navigation clears any prefetched content from a previous staff session.
    window.location.replace("/queues")
  }

  async function logout() {
    const r = await fetch("/api/auth/logout", { method: "POST", headers: { "X-Requested-With": "teratai" } })
    if (!r.ok) throw new Error("Could not sign out. Please try again.")
    setUser(null)
    window.location.replace("/login")
  }

  return <SessionContext.Provider value={{ user, status, refresh, login, logout }}>{children}</SessionContext.Provider>
}

export function useSession() {
  const v = useContext(SessionContext)
  if (!v) throw new Error("useSession must be used inside RoleProvider")
  return v
}

export function useRole() {
  const { user } = useSession()
  if (!user) throw new Error("The workspace requires a verified staff session")
  return { role: user.role, defaultName: user.username, user }
}
