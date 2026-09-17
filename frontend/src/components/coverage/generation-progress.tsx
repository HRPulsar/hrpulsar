"use client";

// W6 (§5.6): one progress strip for both long generations - the two-call
// breakdown and a step's SKILL.md. Segments per phase, a seconds counter,
// and a caption saying which phase is running.
//
// ponytail: there is no honest percentage inside a phase - it is one model
// call that answers all at once - so the segment fills from elapsed time
// against a typical call and stops at 95% until the phase actually flips.
// Real progress means streaming the steps as they are generated; that is a
// task of its own, not a tweak here.

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

/** A healthy call is about a minute; the bar paces itself against that. */
const TYPICAL_PHASE_MS = 60_000;
const CAP = 0.95;

export function GenerationProgress({
  phase,
  phases,
  startedAt,
  caption,
  testId,
}: {
  /** 1-based index of the phase running now. */
  phase: number;
  /** How many phases this generation has. */
  phases: number;
  /** When this run started, as an ISO string; null while unknown. */
  startedAt: string | null;
  /** Already-translated name of the running phase. */
  caption: string;
  testId: string;
}) {
  const t = useTranslations("coverage");
  const [elapsedMs, setElapsedMs] = useState(0);

  useEffect(() => {
    if (!startedAt) return;
    const from = new Date(startedAt).getTime();
    const tick = () => setElapsedMs(Math.max(0, Date.now() - from));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [startedAt]);

  // Elapsed is counted over the whole run, so the phases before this one
  // are already spent: pace the current segment on what is left.
  const inPhaseMs = Math.max(0, elapsedMs - (phase - 1) * TYPICAL_PHASE_MS);
  const fill = Math.min(CAP, inPhaseMs / TYPICAL_PHASE_MS);
  const seconds = Math.floor(elapsedMs / 1000);
  const clock = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

  return (
    <div className="space-y-1.5" data-testid={testId} data-phase={phase}>
      <div className="flex gap-1">
        {Array.from({ length: phases }, (_, i) => (
          <div key={i} className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-[width] duration-1000 ease-linear"
              style={{ width: `${i + 1 < phase ? 100 : i + 1 === phase ? fill * 100 : 0}%` }}
            />
          </div>
        ))}
      </div>
      <p className="text-sm text-muted-foreground">
        {caption}
        {phases > 1 && <span>{t("progressPhase", { phase, phases })}</span>}
        <span data-testid={`${testId}-clock`}>{t("progressClock", { clock })}</span>
      </p>
    </div>
  );
}
