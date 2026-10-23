import { NextResponse, type NextRequest } from "next/server"

export function proxy(request: NextRequest) {
  // This early redirect is UX only; the backend validates the session and every case access.
  if (!request.cookies.has("teratai_session")) return NextResponse.redirect(new URL("/login", request.url))
  return NextResponse.next()
}

export const config = {
  matcher: ["/queues/:path*", "/intake/:path*", "/outbox/:path*", "/cases/:path*", "/metrics/:path*"],
}
