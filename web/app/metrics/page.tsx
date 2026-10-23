import { Suspense } from "react"

import { PageHeader } from "@/components/desk/page-header"
import { MetricsDashboard } from "@/components/metrics/metrics-dashboard"

export const instant = false

export default function Page() {
  return (
    <>
      <PageHeader title="Insights" description="Read-only figures computed from stored cases and agent events." />
      <Suspense fallback={null}>
        <MetricsDashboard />
      </Suspense>
    </>
  )
}
