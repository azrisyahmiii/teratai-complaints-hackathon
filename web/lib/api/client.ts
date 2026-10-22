import createClient from "openapi-fetch"

import type { components, paths } from "./schema"

// Browser calls go to /api/* on this origin (next.config.ts rewrites them to API_URL).
// Server components need an absolute URL, so they call API_URL directly.
const baseUrl = typeof window === "undefined" ? (process.env.API_URL ?? "http://localhost:8000") : ""

export const api = createClient<paths>({ baseUrl })

// Money fields are strings ("46.66"): display them, never parseFloat them for maths.
export type Schemas = components["schemas"]
