import { OutboxList } from "@/components/desk/outbox-list"

export default function Page() {
  return (
    <>
      <header className="flex flex-wrap items-center gap-3 border-b bg-card px-6 py-3">
        <h1 className="text-xl font-semibold">Outbox</h1>
        <span className="ml-auto text-[13px] text-muted-foreground">
          Simulated: replies that would have gone to customers · times in MYT
        </span>
      </header>
      <OutboxList />
    </>
  )
}
