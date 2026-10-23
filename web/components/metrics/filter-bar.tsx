"use client"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import type { Schemas } from "@/lib/api/client"
import { categoryLabel } from "@/lib/labels"

export interface Filters {
  date_from: string
  date_to: string
  category: string
  channel: string
}

export const NO_FILTERS: Filters = { date_from: "", date_to: "", category: "", channel: "" }
const ALL = "all"

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
      {label}
      {children}
    </label>
  )
}

export function FilterBar({
  filters,
  options,
  onChange,
}: {
  filters: Filters
  options: Schemas["MetricOptions"] | undefined
  onChange: (next: Filters) => void
}) {
  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch })
  const categories = [{ value: ALL, label: "All categories" }, ...(options?.categories ?? []).map((v) => ({ value: v, label: categoryLabel(v) }))]
  const channels = [{ value: ALL, label: "All channels" }, ...(options?.channels ?? []).map((v) => ({ value: v, label: v }))]
  const active = Object.values(filters).some(Boolean)

  return (
    <form
      aria-label="Filters"
      onSubmit={(e) => e.preventDefault()}
      className="flex flex-wrap items-end gap-3 rounded-md border bg-card px-3 py-3"
    >
      <Field label="Received from">
        <Input
          type="date"
          value={filters.date_from}
          min={options?.date_min ?? undefined}
          max={filters.date_to || options?.date_max || undefined}
          onChange={(e) => set({ date_from: e.target.value })}
          className="w-40"
        />
      </Field>
      <Field label="Received to">
        <Input
          type="date"
          value={filters.date_to}
          min={filters.date_from || options?.date_min || undefined}
          max={options?.date_max ?? undefined}
          onChange={(e) => set({ date_to: e.target.value })}
          className="w-40"
        />
      </Field>
      <div className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
        Category
        <Select items={categories} value={filters.category || ALL} onValueChange={(v) => set({ category: v === ALL ? "" : String(v) })}>
          <SelectTrigger aria-label="Category" className="w-56"><SelectValue /></SelectTrigger>
          <SelectContent alignItemWithTrigger={false}>
            {categories.map((c) => <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      <div className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
        Channel
        <Select items={channels} value={filters.channel || ALL} onValueChange={(v) => set({ channel: v === ALL ? "" : String(v) })}>
          <SelectTrigger aria-label="Channel" className="w-44"><SelectValue /></SelectTrigger>
          <SelectContent alignItemWithTrigger={false}>
            {channels.map((c) => <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      <Button type="button" variant="outline" disabled={!active} onClick={() => onChange(NO_FILTERS)}>Reset filters</Button>
    </form>
  )
}
