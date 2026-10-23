import { PageHeader } from "@/components/desk/page-header"
import { ManagerConsole } from "@/components/manager/manager-console"

export const instant = false

export default function Page() {
  return (
    <>
      <PageHeader title="Manager console" description="Escalated cases wait here. Nothing is sent until you decide." />
      <ManagerConsole />
    </>
  )
}
