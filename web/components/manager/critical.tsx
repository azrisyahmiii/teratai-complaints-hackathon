export function CriticalLines({ lines }: { lines: string[] }) {
  if (!lines.length) return null
  return (
    <div
      role="alert"
      className="flex flex-col gap-1 rounded-[4px] border border-status-critical-border bg-status-critical-bg px-2 py-1.5 text-[13px] leading-snug text-status-critical-fg"
    >
      {lines.map((l, i) => (
        <p key={i}>{l}</p>
      ))}
    </div>
  )
}
