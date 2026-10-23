"use client"

import { LogOut, ShieldCheck } from "lucide-react"
import Image from "next/image"
import { useState } from "react"
import { useRole, useSession } from "@/lib/role"
import { Button } from "@/components/ui/button"

export function StaffAccount() {
  const { user } = useRole()
  const { logout } = useSession()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  async function signOut() {
    setBusy(true)
    setError("")
    try { await logout() } catch { setError("Unable to sign out. Please retry."); setBusy(false) }
  }

  return (
    <div className="staff-account-bar">
      <span className="flex items-center gap-2 text-xs text-muted-foreground"><ShieldCheck className="size-4" aria-hidden />Staff workspace</span>
      <div className="ml-auto flex items-center gap-3">
        <div className="staff-avatar overflow-hidden shrink-0" aria-hidden>
          {["asyraf", "leon", "azri", "nishan", "vincent"].includes(user.username) ? (
            <Image src={`/images/profiles/${user.username}.jpeg`} alt="" width={34} height={34} sizes="34px" className="h-full w-full object-cover" />
          ) : user.username.slice(0, 1).toUpperCase()}
        </div>
        <div className="text-right">
          <p className="text-[13px] font-medium">{user.username}</p>
          <p className="text-[11px] text-muted-foreground">{user.role_label}</p>
        </div>
        <Button variant="ghost" disabled={busy} onClick={() => void signOut()}><LogOut aria-hidden className="size-4" />{busy ? "Signing out…" : "Log out"}</Button>
      </div>
      {error && <p role="alert" className="w-full text-right text-xs text-destructive">{error}</p>}
    </div>
  )
}
