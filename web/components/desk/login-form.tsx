"use client"

import { ArrowRight, Eye, EyeOff, LockKeyhole } from "lucide-react"
import { useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useSession } from "@/lib/role"
import { LotusMark } from "./lotus-mark"

export function LoginForm() {
  const { login } = useSession()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [visible, setVisible] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (busy) return
    setError("")
    setBusy(true)
    try { await login(username.trim(), password) }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to connect. Please try again."); setBusy(false) }
  }

  return (
    <main className="login-scene">
      <header className="login-brandbar">
        <div className="desk-brand !p-0">
          <LotusMark className="size-14 text-[#E3C38A]" />
          <div>
            <p className="text-lg font-medium tracking-[0.16em]">TERATAI BANK</p>
            <p className="mt-1 text-[10px] tracking-[0.22em] text-[#E0E6DA]">COMPLAINTS PLATFORM</p>
          </div>
        </div>
        <span className="login-staff-label">Staff access</span>
      </header>

      <div className="login-composition">
        <div className="login-message">
          <p className="eyebrow">Care, with clarity</p>
          <h1>Every concern<br />deserves care.</h1>
          <p>A dedicated workspace for the people<br className="hidden sm:block" /> behind every resolution.</p>
        </div>

        <section className="login-panel" aria-labelledby="login-title">
          <p className="eyebrow">Staff portal</p>
          <h2 id="login-title">Welcome back</h2>
          <p className="mt-2 text-sm text-muted-foreground">Sign in to your complaints workspace.</p>
          <form onSubmit={submit} className="mt-8 flex flex-col gap-5" aria-busy={busy}>
            <div className="flex flex-col gap-2">
              <Label htmlFor="staff-id">Staff ID</Label>
              <Input id="staff-id" name="username" autoComplete="username" autoCapitalize="none" spellCheck={false}
                placeholder="Enter your staff ID" required maxLength={100} value={username} disabled={busy}
                onChange={(e) => setUsername(e.target.value)} aria-invalid={!!error} aria-describedby={error ? "login-error" : undefined} />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="staff-password">Password</Label>
              <div className="relative">
                <Input id="staff-password" name="password" type={visible ? "text" : "password"} autoComplete="current-password"
                  placeholder="Enter your password" required maxLength={72} value={password} disabled={busy}
                  onChange={(e) => setPassword(e.target.value)} className="pr-12" aria-invalid={!!error} aria-describedby={error ? "login-error" : undefined} />
                <button type="button" onClick={() => setVisible(!visible)} aria-label={visible ? "Hide password" : "Show password"}
                  aria-pressed={visible} className="absolute inset-y-0 right-0 flex w-11 cursor-pointer items-center justify-center rounded-r-lg text-muted-foreground hover:text-foreground">
                  {visible ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
                </button>
              </div>
            </div>
            {error && <p id="login-error" role="alert" className="rounded-md border border-status-critical-border bg-status-critical-bg p-3 text-[13px] text-status-critical-fg">{error}</p>}
            <Button type="submit" disabled={busy || !username.trim() || !password} className="login-submit">
              {busy ? "Signing in…" : "Sign in"}<ArrowRight className="size-4" aria-hidden />
            </Button>
          </form>
          <p className="mt-6 flex items-center justify-center gap-2 text-xs text-muted-foreground"><LockKeyhole className="size-3.5" aria-hidden />For authorised bank staff only</p>
          <p className="mt-5 border-t pt-5 text-center text-xs leading-relaxed text-muted-foreground">Need access? Contact your bank administrator.</p>
        </section>
      </div>

      <footer className="login-footer"><span>© 2026 Teratai Bank</span><span>Internal use only</span></footer>
    </main>
  )
}
