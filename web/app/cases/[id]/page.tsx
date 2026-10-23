import { Suspense } from "react"

import { PageHeader } from "@/components/desk/page-header"

async function CaseTitle({ params }: { params: PageProps<"/cases/[id]">["params"] }) {
  const { id } = await params
  return <PageHeader title={`Case ${id}`} />
}

export default function Page(props: PageProps<"/cases/[id]">) {
  return (
    <>
      {/* params are runtime data: with cacheComponents they must be read under Suspense. */}
      <Suspense fallback={<PageHeader title="Case" />}>
        <CaseTitle params={props.params} />
      </Suspense>
      <p className="p-6 text-muted-foreground">Built in U2.</p>
    </>
  )
}
