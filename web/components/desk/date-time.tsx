import { formatDateTime, formatDateTimeShort } from "@/lib/format"

export function DateTime({ value, short = false }: { value: string | null | undefined; short?: boolean }) {
  return <span className="tabular-nums">{short ? formatDateTimeShort(value) : formatDateTime(value)}</span>
}
