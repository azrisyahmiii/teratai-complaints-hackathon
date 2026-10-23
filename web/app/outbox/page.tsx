import { OutboxList } from "@/components/desk/outbox-list"
import { PageHeader } from "@/components/desk/page-header"

export const instant = false

export default function Page() {
  return (
    <>
      <PageHeader title="Outbox" description="A record of authorised replies. Delivery is simulated; nothing leaves the platform." />
      <OutboxList />
    </>
  )
}
