import { cn } from "cn"

/** CMP-00244, TXN-0088211: always mono, never truncated. */
export function MonoId({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn("font-mono text-[12.5px]", className)}>{children}</span>
}
