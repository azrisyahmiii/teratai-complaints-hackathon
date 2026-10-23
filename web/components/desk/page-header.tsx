export function PageHeader({ title }: { title: string }) {
  return (
    <header className="flex flex-wrap items-center gap-3 border-b bg-card px-6 py-3">
      <h1 className="text-xl font-semibold">{title}</h1>
      <span className="inline-flex h-[22px] items-center rounded-[4px] border border-status-success-border bg-status-success-bg px-1.5 text-xs font-medium text-status-success-fg">
        Live
      </span>
      <span className="ml-auto text-[13px] text-muted-foreground">Updates every 2 s · times in MYT</span>
    </header>
  )
}
