import { IntakeForm } from "@/components/desk/intake-form"
import { PageHeader } from "@/components/desk/page-header"

export const instant = false

export default function Page() {
  return (
    <>
      <PageHeader title="New complaint" description="Capture the concern. The agent gathers the evidence and drafts a reply for review." />
      <IntakeForm />
    </>
  )
}
