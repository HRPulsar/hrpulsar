"use client";

import { useState } from "react";
import { CircleHelp } from "lucide-react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

// HRP-659: the labels stay as agreed with the customer, so the explanation
// of what a number actually counts hangs off a question mark next to it.
// Hover and focus open it; the click toggle is what makes it reachable on
// touch, where there is no hover. TooltipProvider already wraps the
// dashboard layout — no provider here.
export function Hint({
  text,
  title,
  className,
  "data-testid": testId,
}: {
  text: string;
  /** Optional bold first line — use when the text alone is ambiguous. */
  title?: string;
  className?: string;
  "data-testid"?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Tooltip
      open={open}
      // Base UI closes the tooltip on a trigger press. On touch that press
      // is the only way to open it at all, so the click toggle below owns
      // that reason — hover and focus still go through untouched.
      onOpenChange={(next, details) => {
        if (details.reason !== "trigger-press") setOpen(next);
      }}
    >
      <TooltipTrigger
        render={
          <button
            type="button"
            aria-label={title ? `${title}. ${text}` : text}
            data-testid={testId}
            onClick={() => setOpen((v) => !v)}
            className={cn(
              "inline-flex shrink-0 items-center justify-center rounded-full text-muted-foreground/70 transition-colors hover:text-foreground focus-visible:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
              className,
            )}
          >
            <CircleHelp className="h-3.5 w-3.5" />
          </button>
        }
      />
      <TooltipContent className="max-w-[18rem] leading-relaxed">
        {title && <div className="mb-0.5 font-semibold">{title}</div>}
        {text}
      </TooltipContent>
    </Tooltip>
  );
}
