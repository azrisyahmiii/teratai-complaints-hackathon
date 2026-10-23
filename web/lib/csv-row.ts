// Parser for one complaints.csv row (or the same fields as JSON). Pure: no DOM, no imports.

export interface ComplaintFields {
  complaint_id: string
  customer_id: string
  received_at: string
  channel: string
  subject: string
  text: string
}

export type ParseResult = { ok: true; fields: ComplaintFields } | { ok: false; error: string }

export const README_EXAMPLE =
  'LIVE-07,CUS-01234,2026-09-30 10:15,App chat,,"Hi, I was charged twice at ShopLah Online today for RM89.90..."'

const KEYS = ["complaint_id", "customer_id", "received_at", "channel", "subject", "text"] as const

/** RFC 4180: commas, doubled quotes and line breaks inside quoted fields. Returns records of cells. */
function splitCsv(input: string): string[][] {
  const records: string[][] = []
  let row: string[] = []
  let cell = ""
  let quoted = false
  let i = 0
  while (i < input.length) {
    const ch = input[i]
    if (quoted) {
      if (ch === '"') {
        if (input[i + 1] === '"') {
          cell += '"'
          i += 2
          continue
        }
        quoted = false
      } else {
        cell += ch
      }
    } else if (ch === '"' && cell === "") {
      quoted = true
    } else if (ch === ",") {
      row.push(cell)
      cell = ""
    } else if (ch === "\r" || ch === "\n") {
      if (ch === "\r" && input[i + 1] === "\n") i++
      row.push(cell)
      records.push(row)
      row = []
      cell = ""
    } else {
      cell += ch
    }
    i++
  }
  if (quoted) throw new Error("A quoted field is not closed. Check the row was pasted whole.")
  if (cell !== "" || row.length > 0) {
    row.push(cell)
    records.push(row)
  }
  return records
}

function fromJson(input: string): ParseResult {
  let obj: unknown
  try {
    obj = JSON.parse(input)
  } catch {
    return { ok: false, error: "That looks like JSON but doesn't parse. Check the braces and quotes." }
  }
  if (typeof obj !== "object" || obj === null || Array.isArray(obj)) {
    return { ok: false, error: "Expected one JSON object with the six complaint fields." }
  }
  const rec = obj as Record<string, unknown>
  const out = {} as ComplaintFields
  for (const k of KEYS) {
    const v = rec[k]
    if (v === undefined || v === null) {
      if (k === "subject") {
        out[k] = ""
        continue
      }
      return { ok: false, error: `The JSON is missing "${k}".` }
    }
    if (typeof v !== "string") return { ok: false, error: `"${k}" must be a string.` }
    out[k] = v
  }
  return { ok: true, fields: out }
}

export function parseComplaintRow(raw: string): ParseResult {
  const input = raw.replace(/^﻿/, "").trim()
  if (input === "") return { ok: false, error: "Paste a complaints.csv row or a JSON body." }
  if (input.startsWith("{")) return fromJson(input)

  let records: string[][]
  try {
    records = splitCsv(input)
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "Could not read the row." }
  }
  if (records.length > 1 && records[0].map((c) => c.trim().toLowerCase()).join(",") === KEYS.join(",")) {
    records = records.slice(1)
  }
  if (records.length !== 1) {
    return { ok: false, error: `Expected one row, found ${records.length}. Send one complaint at a time.` }
  }
  const cells = records[0]
  if (cells.length !== 6) {
    return { ok: false, error: `Expected 6 fields, found ${cells.length}. Check the row was pasted whole.` }
  }
  const [complaint_id, customer_id, received_at, channel, subject, text] = cells
  return { ok: true, fields: { complaint_id, customer_id, received_at, channel, subject, text } }
}
