import { PageHeader } from "@/components/desk/page-header"
import { FraudWorkbench } from "@/components/fraud/fraud-workbench"

export const instant = false

export default function Page() {
  return (
    <>
      <PageHeader title="Fraud workbench" />
      <FraudWorkbench />
    </>
  )
}
