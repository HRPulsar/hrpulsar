"use client";

// HRP-1205: the closing popup of a breakdown - in plain words, what stays
// with people, what goes to an agent, who checks, and how to go on: the
// instruction for the agent goes to the company's own bot, since the agent
// is not built into the product. The figures are `CoverageOutcome`'s
// (HRP-1200), the very block under the summary. "What's next" on the page
// opens it any time; in a demo sandbox it also opens once per process, when
// a breakdown finishes while the page is open.

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { CoverageOutcome, outcomeOf } from "@/components/coverage/coverage-outcome";
import { MOMENT_DELAY_MS } from "@/components/dashboard/demo-feedback-popup";
import type { CoverageStep } from "@/lib/api/work";

/** Per process: the popup opened by itself once and does not again. */
const SHOWN_PREFIX = "coverage_what_next:";

export function whatNextShown(containerId: string): boolean {
  try {
    return !!localStorage.getItem(`${SHOWN_PREFIX}${containerId}`);
  } catch {
    // Storage off (private mode): unset, like the demo card's flags - it
    // opens again on the next breakdown finished in front of the visitor.
    return false;
  }
}

export function markWhatNextShown(containerId: string) {
  try {
    localStorage.setItem(`${SHOWN_PREFIX}${containerId}`, "1");
  } catch {
    // See above.
  }
}

/** The demo's own overlays: the "Where to start" window and the corner card. */
const DEMO_OVERLAYS = '[data-testid="demo-guide-dialog"], [data-testid="demo-feedback-popup"]';

/** Opens once no demo overlay is on screen - the queue the demo card keeps
 * for its own cards: the one on screen keeps the slot, the next one waits.
 * Looked at only after the card's own delay, so the breakdown's value-moment
 * card (HRP-1158), fired by the same apply, is already there to wait for.
 * Returns the cancel. */
export function whenDemoIsClear(open: () => void): () => void {
  let observer: MutationObserver | null = null;
  const tryOpen = () => {
    if (document.querySelector(DEMO_OVERLAYS)) return false;
    observer?.disconnect();
    open();
    return true;
  };
  const timer = window.setTimeout(() => {
    if (tryOpen()) return;
    observer = new MutationObserver(tryOpen);
    observer.observe(document.body, { childList: true, subtree: true });
  }, MOMENT_DELAY_MS + 500);
  return () => {
    window.clearTimeout(timer);
    observer?.disconnect();
  };
}

export function WhatNextDialog({ steps, onClose }: { steps: CoverageStep[]; onClose: () => void }) {
  const t = useTranslations("coverage");
  const { unchecked, unassigned } = outcomeOf(steps);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg" data-testid="coverage-what-next">
        <DialogHeader>
          <DialogTitle>{t("whatNextTitle")}</DialogTitle>
          <DialogDescription>{t("whatNextIntro")}</DialogDescription>
        </DialogHeader>
        <CoverageOutcome steps={steps} linkSteps={false} />
        <div className="space-y-1.5 text-sm">
          <p className="font-medium">{t("whatNextHowTitle")}</p>
          <ol className="list-decimal space-y-1 pl-5" data-testid="coverage-what-next-steps">
            {unassigned.length > 0 && (
              <li data-testid="coverage-what-next-executor">
                {t("whatNextStepExecutor", { button: t("assignExecutor") })}
              </li>
            )}
            {unchecked.length > 0 && (
              <li data-testid="coverage-what-next-checker">
                {t("whatNextStepChecker", { button: t("whoChecks") })}
              </li>
            )}
            <li data-testid="coverage-what-next-download">
              {t("whatNextStepDownload", { tab: t("tabGaps") })}
            </li>
            <li data-testid="coverage-what-next-bot">{t("whatNextStepBot")}</li>
          </ol>
        </div>
        <DialogFooter>
          <Button onClick={onClose} data-testid="coverage-what-next-close">
            {t("whatNextDone")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
