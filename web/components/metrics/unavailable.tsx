import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

/** A value that cannot be measured: an em dash whose tooltip says why (never an invented 0). */
export function Unavailable({ path, map }: { path: string; map: Record<string, string> }) {
  const reason = map[path] ?? "Not measured for this selection."
  return (
    <Tooltip>
      <TooltipTrigger
        render={<span tabIndex={0} aria-label={`Not available: ${reason}`} className="cursor-help text-muted-foreground" />}
      >
        —
      </TooltipTrigger>
      <TooltipContent>{reason}</TooltipContent>
    </Tooltip>
  )
}
