"use client";

// HRP-871: what a human match stands on - the person's competences behind
// the step's capabilities, each with the score of the latest completed
// assessment against the passing score of their grade specialization. An
// `expected` match says so in its own words: the grade matrix of the position
// asks for the competence, no assessment has confirmed it yet.
//
// The shell and the row idiom follow the Talent Market match drawer
// (competence on the left, the percent on the right). Its requirement blocks
// are editors over a talent card and do not fit this data. Purely
// presentational: the grounds arrive on the coverage row, and a reader who
// may not see the person has no row.human to open this from.

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { BADGE_COLOR } from "@/lib/badge-tones";
import type { CoverageStep } from "@/lib/api/work";

export function MatchGroundsDrawer({
  human,
  capabilityLabel,
  onClose,
}: {
  human: NonNullable<CoverageStep["human"]>;
  capabilityLabel: (code: string) => string;
  onClose: () => void;
}) {
  const t = useTranslations("coverage");
  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent data-testid="coverage-grounds-drawer" data-label={human.label}>
        <SheetHeader>
          <SheetTitle data-testid="coverage-grounds-drawer-title">
            {t("groundsTitle", { name: human.name })}
          </SheetTitle>
          <SheetDescription data-testid="coverage-grounds-drawer-text">
            {human.label === "assessed" ? t("groundsAssessedText") : t("groundsExpectedText")}
          </SheetDescription>
        </SheetHeader>
        <div className="flex-1 space-y-3 overflow-y-auto p-5">
          {human.passing_score != null && (
            <p className="text-xs text-muted-foreground" data-testid="coverage-grounds-drawer-threshold">
              {t("groundsPassingScore", { percent: human.passing_score })}
            </p>
          )}
          <ul className="space-y-2">
            {(human.grounds ?? []).map((ground) => {
              // A label, not a literal in the markup (as the Talent Market drawer does).
              const percent = ground.state === "assessed" && ground.percent !== null ? `${ground.percent}%` : null;
              return (
                <li
                  key={ground.competence_id}
                  className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm"
                  data-testid={`coverage-grounds-row-${ground.competence_id}`}
                  data-state={ground.state}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{ground.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {t("groundsCovers", { capabilities: ground.codes.map(capabilityLabel).join(", ") })}
                    </p>
                  </div>
                  {/* Grey "No assessment", as the Talent Market drawer says it
                      (HRP-871 REDO); short, so the title keeps the room. */}
                  <Badge
                    variant="secondary"
                    className={`shrink-0 ${percent ? BADGE_COLOR.green : BADGE_COLOR.neutral}`}
                  >
                    {percent ?? t("groundsNotAssessed")}
                  </Badge>
                </li>
              );
            })}
          </ul>
        </div>
      </SheetContent>
    </Sheet>
  );
}
