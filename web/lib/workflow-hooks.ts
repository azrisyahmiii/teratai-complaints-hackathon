"use client"

import { useCallback, useEffect, useState } from "react"

import { errorLines } from "@/lib/workflow"

/** Polls a loader every `ms`; keeps the last good data and exposes the API's error lines. */
export function usePoll<T>(load: () => Promise<T>, ms = 2000) {
  const [data, setData] = useState<T | null>(null)
  const [errors, setErrors] = useState<string[]>([])
  const [tick, setTick] = useState(0)
  const reload = useCallback(() => setTick((t) => t + 1), [])
  useEffect(() => {
    let alive = true
    const run = () =>
      load()
        .then((d) => {
          if (!alive) return
          setData(d)
          setErrors([])
        })
        .catch((e) => {
          if (alive) setErrors(errorLines(e))
        })
    void run()
    const t = setInterval(() => void run(), ms)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [load, ms, tick])
  return { data, errors, reload }
}
