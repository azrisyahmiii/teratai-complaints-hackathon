import { formatMoney } from "@/lib/format"
import { cn } from "cn"

/** "1500.00" -> "RM1,500.00". Right-aligned, tabular figures. */
export function Money({ value, className }: { value: string | null | undefined; className?: string }) {
  return <span className={cn("block text-right tabular-nums", className)}>{formatMoney(value)}</span>
}
