"use client";

// HRP-1204: the "?" next to a step's automation mode. One popover with every
// mode side by side - its badge, in its colour, and what it means - so a
// reader learns the whole scale at once instead of one label at a time.
// Hover, focus and a click (touch) open it. One component wherever the mode
// badge shows. HRP-1182 (QA 20.11): the modes only - Preliminary has its own
// "?" - and the "?" sits by the badge it explains, not halfway to the next one.

import { CircleHelp } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { MODE_COLOR } from "@/components/coverage/gaps-tab";
import type { AutomationMode } from "@/lib/api/work";

export function ModeHelp({ testId }: { testId: string }) {
  const t = useTranslations("coverage");
  // Read at render, not at import: gaps-tab, which holds the colours, puts
  // this "?" on its own rows (HRP-1198), so the two modules import each other.
  const modes = Object.keys(MODE_COLOR) as AutomationMode[];
  return (
    <Popover>
      <PopoverTrigger
        openOnHover
        delay={150}
        aria-label={t("modeHelpTitle")}
        className="-ml-1 inline-flex shrink-0 items-center justify-center rounded-full text-muted-foreground/70 transition-colors hover:text-foreground focus-visible:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        data-testid={testId}
      >
        <CircleHelp className="size-3.5" />
      </PopoverTrigger>
      <PopoverContent
        align="start"
        sideOffset={6}
        className="w-[380px] max-w-[90vw] p-4 text-sm"
        data-testid={`${testId}-popover`}
      >
        <p className="font-semibold">{t("modeHelpTitle")}</p>
        <dl className="mt-2 space-y-2">
          {modes.map((mode) => (
            <div key={mode} data-testid={`${testId}-${mode}`}>
              <dt>
                <Badge className={MODE_COLOR[mode]}>{t(`mode_${mode}`)}</Badge>
              </dt>
              <dd className="mt-0.5 text-muted-foreground">{t(`modeHelp_${mode}`)}</dd>
            </div>
          ))}
        </dl>
      </PopoverContent>
    </Popover>
  );
}
