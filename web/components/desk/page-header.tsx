import { Clock3 } from "lucide-react"

export function PageHeader({ title, description }: { title: string; description?: string }) {
  return (
    <header className="workspace-header">
      <div>
        <p className="eyebrow">Complaints workspace</p>
        <h1 className="mt-1 text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-[13px] text-muted-foreground">{description}</p>}
      </div>
      <div className="flex items-center gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5"><Clock3 aria-hidden className="size-3.5" />Malaysia time</span>
        <span className="rounded-full border bg-card px-2.5 py-1">MYT · UTC+8</span>
      </div>
    </header>
  )
}
