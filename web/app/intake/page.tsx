import { IntakeForm } from "@/components/desk/intake-form"

export default function Page() {
  return (
    <>
      <header className="flex flex-wrap items-center gap-3 border-b bg-card px-6 py-3">
        <h1 className="text-xl font-semibold">New complaint</h1>
        <span className="ml-auto text-[13px] text-muted-foreground">
          Posts to the same API the judges use · POST /complaints
        </span>
      </header>
      <IntakeForm />
    </>
  )
}
