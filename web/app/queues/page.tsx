import { PageHeader } from "@/components/desk/page-header"
import { Queues } from "@/components/desk/queues"

export const instant = false

export default function Page() {
  return (
    <>
      <PageHeader title="Queues" />
      <Queues />
    </>
  )
}
