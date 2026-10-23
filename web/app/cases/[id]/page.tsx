import { Suspense } from "react"

export const instant = false

import { CaseView } from "@/components/desk/case-view"

async function Case({ params }: { params: PageProps<"/cases/[id]">["params"] }) {
  const { id } = await params
  return <CaseView id={decodeURIComponent(id)} />
}

export default function Page(props: PageProps<"/cases/[id]">) {
  return (
    // params are runtime data: with cacheComponents they must be read under Suspense.
    <Suspense fallback={<p className="p-6 text-[13px] text-muted-foreground">Loading case…</p>}>
      <Case params={props.params} />
    </Suspense>
  )
}
