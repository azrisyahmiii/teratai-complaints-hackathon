// Pure formatting helpers. Money is a decimal string ("1500.00"): never parseFloat it for maths.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

/** "1500.00" -> "RM1,500.00". Strings that are not plain decimals come back unchanged. */
export function formatMoney(value: string | null | undefined): string {
  if (value == null || value === "") return "—"
  const m = /^(-?)(\d+)(?:\.(\d*))?$/.exec(value.trim())
  if (!m) return value
  const [, sign, whole, frac = ""] = m
  const grouped = whole.replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, ",")
  return `${sign ? "-" : ""}RM${grouped}.${frac.padEnd(2, "0").slice(0, 2)}`
}

interface Parts {
  year: string
  month: number
  day: number
  time: string
}

// Reads the wall-clock parts straight from the ISO string, so the browser's timezone never shifts MYT times.
function parts(iso: string | null | undefined): Parts | null {
  if (!iso) return null
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(iso)
  if (!m) return null
  return { year: m[1], month: Number(m[2]) - 1, day: Number(m[3]), time: `${m[4]}:${m[5]}` }
}

/** "20 Jul 2026, 22:32" */
export function formatDateTime(iso: string | null | undefined): string {
  const p = parts(iso)
  return p ? `${p.day} ${MONTHS[p.month]} ${p.year}, ${p.time}` : "—"
}

/** "20 Jul, 22:32" */
export function formatDateTimeShort(iso: string | null | undefined): string {
  const p = parts(iso)
  return p ? `${p.day} ${MONTHS[p.month]}, ${p.time}` : "—"
}

/** "25 Jul" */
export function formatDayShort(iso: string | null | undefined): string {
  const p = parts(iso)
  return p ? `${p.day} ${MONTHS[p.month]}` : "—"
}

/** Wall-clock milliseconds (as if UTC) so two MYT strings compare without timezone drift. */
export function wallMs(iso: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/.exec(iso)
  if (!m) return NaN
  return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]), Number(m[6] ?? 0))
}
