"use client"

import { useEffect, useRef } from "react"
import { formatMoney } from "@/lib/format"
import { cn } from "cn"

/** "1500.00" -> "RM1,500.00". Right-aligned, tabular figures. */
export function Money({ value, className, animate = false }: { value: string | null | undefined; className?: string; animate?: boolean }) {
  const ref = useRef<HTMLSpanElement>(null)
  const formatted = formatMoney(value)

  useEffect(() => {
    const element = ref.current
    if (!animate || !element || !value || !/^\d+(?:\.\d{1,2})?$/.test(value)) return
    // Only the visual count uses numbers; the final amount keeps the original decimal string.
    const [whole, fraction = ""] = value.split(".")
    const cents = Number(whole) * 100 + Number(fraction.padEnd(2, "0"))
    if (!Number.isSafeInteger(cents) || cents <= 0) return
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)")
    if (motion.matches) return
    let frame = 0
    let start: number | undefined
    const finish = () => {
      cancelAnimationFrame(frame)
      element.textContent = formatted
      observer.disconnect()
    }
    const tick = (time: number) => {
      start ??= time
      const progress = Math.min((time - start) / 1200, 1)
      const current = Math.round(cents * (1 - (1 - progress) ** 3))
      element.textContent = formatMoney((current / 100).toFixed(2))
      if (progress < 1) frame = requestAnimationFrame(tick)
      else finish()
    }
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return
      observer.disconnect()
      element.textContent = formatMoney("0")
      frame = requestAnimationFrame(tick)
    }, { threshold: 0.5 })
    observer.observe(element)
    motion.addEventListener("change", finish)
    return () => {
      finish()
      motion.removeEventListener("change", finish)
    }
  }, [animate, value, formatted])

  return <span className={cn("block text-right tabular-nums", className)}>
    {animate && <span className="sr-only">{formatted}</span>}
    <span ref={ref} aria-hidden={animate || undefined}>{formatted}</span>
  </span>
}
