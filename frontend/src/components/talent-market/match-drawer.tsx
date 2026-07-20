"use client";

// HRP-172: Match drawer (shadcn Sheet) opened from the Match cell in the
// Candidates list and the Add / Change picker dialogs on the card detail
// page. Renders a per-Required-Competence row with the projected percent
// the matcher used (HRP-129 REDO), plus a per-Required-Specialization
// row with the employee's total tenure on matching positions and whether
// it clears the min_experience_years floor. Colour rules mirror HRP-173.

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { BADGE_COLOR } from "@/lib/badge-tones";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";

interface BreakdownCompetenceRow {
  competence_id: string;
  competence_title: string;
  required_skill_level_id: string | null;
  required_skill_level_title: string | null;
  card_match_percent: number;
  actual_percent: number | null;
  qualifies: boolean;
}

interface BreakdownSpecRow {
  specialization_id: string;
  specialization_title: string;
  grade_id: string | null;
  grade_title: string | null;
  required_years: number | null;
  actual_months: number | null;
  qualifies: boolean;
  /** HRP-210: True when the employee has no matching WorkExperience
   * row but their current Position lines up with the spec. The drawer
   * renders "Current position" (muted) for those rows. */
  current_position_match?: boolean;
}

interface Breakdown {
  employee_id: string;
  employee_name: string | null;
  card_match_percent: number;
  competences: BreakdownCompetenceRow[];
  specializations: BreakdownSpecRow[];
}

export interface MatchDrawerProps {
  cardId: string;
  employeeId: string | null;
  employeeName?: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function formatMonths(total: number | null): string {
  if (total === null) return "No experience";
  if (total <= 0) return "Less than a month";
  const years = Math.floor(total / 12);
  const months = total % 12;
  const yearPart = years ? `${years} year${years === 1 ? "" : "s"}` : "";
  const monthPart = months ? `${months} month${months === 1 ? "" : "s"}` : "";
  if (yearPart && monthPart) return `${yearPart} ${monthPart}`;
  return yearPart || monthPart || "Less than a month";
}

// HRP-172 redo (2026-06-09): the per-competence chip now mirrors the
// card-level threshold rule — green when % ≥ threshold, red when below,
// muted when there is no assessment. The separate Match / Below chip
// is gone; the % chip carries the verdict on its own.
function percentChipClass(
  percent: number | null,
  threshold: number,
): string {
  if (percent === null) return BADGE_COLOR.neutral;
  return percent >= threshold ? BADGE_COLOR.green : BADGE_COLOR.red;
}

export function MatchDrawer({
  cardId,
  employeeId,
  employeeName,
  open,
  onOpenChange,
}: MatchDrawerProps) {
  const [data, setData] = useState<Breakdown | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !employeeId) {
      return;
    }
    let cancelled = false;
    // Defer state mutations to a microtask so the synchronous body of
    // the effect stays free of setState — React 19's
    // react-hooks/set-state-in-effect rule.
    void Promise.resolve().then(() => {
      if (cancelled) return;
      setLoading(true);
      setError(null);
      api
        .get<Breakdown>(
          `/talent-market/${cardId}/candidates/${employeeId}/breakdown`,
        )
        .then((res) => {
          if (cancelled) return;
          setData(res);
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setError(err instanceof Error ? err.message : "Failed to load");
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    });
    return () => {
      cancelled = true;
    };
  }, [cardId, employeeId, open]);

  const title = data?.employee_name ?? employeeName ?? "Candidate match";

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent data-testid="talent-market-match-drawer">
        <SheetHeader>
          <SheetTitle data-testid="talent-market-match-drawer-title">
            {title}
          </SheetTitle>
          <SheetDescription>
            Match breakdown against the card requirements.
          </SheetDescription>
        </SheetHeader>

        {/* HRP-172 redo item 5: large requirement / experience lists
            used to clip past the viewport — wrap the body in a flex
            column so the inner list can scroll within the Sheet panel. */}
        <div className="flex-1 space-y-6 overflow-y-auto p-5">
          {loading && (
            <p className="text-sm text-muted-foreground">Loading…</p>
          )}
          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}

          {data && data.competences.length > 0 && (
            <section data-testid="talent-market-match-drawer-competences">
              <h3 className="mb-2 text-sm font-medium">Required competencies</h3>
              <p className="mb-3 text-xs text-muted-foreground">
                Threshold: {data.card_match_percent}%
              </p>
              <ul className="space-y-2">
                {data.competences.map((row) => {
                  const pctLabel =
                    row.actual_percent === null
                      ? "No assessment"
                      : `${row.actual_percent}%`;
                  // HRP-172 redo (2026-06-09): chip colour is driven by
                  // the card threshold — green ≥ threshold, red below,
                  // muted when there's no assessment. The standalone
                  // Match / Below chip was removed; the % chip carries
                  // the verdict on its own.
                  const chipClass = percentChipClass(
                    row.actual_percent,
                    row.card_match_percent,
                  );
                  return (
                    <li
                      key={row.competence_id}
                      className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm"
                      data-testid="talent-market-match-drawer-competence-row"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium">
                          {row.competence_title}
                        </p>
                        {row.required_skill_level_title && (
                          <p className="text-xs text-muted-foreground">
                            Required level: {row.required_skill_level_title}
                          </p>
                        )}
                      </div>
                      <Badge
                        variant="secondary"
                        className={chipClass}
                        data-testid="talent-market-match-drawer-competence-percent"
                      >
                        {pctLabel}
                      </Badge>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          {data && data.specializations.length > 0 && (
            <section data-testid="talent-market-match-drawer-experience">
              <h3 className="mb-2 text-sm font-medium">Experience</h3>
              <ul className="space-y-2">
                {data.specializations.map((row) => {
                  // HRP-210: when there's no WorkExperience tenure but
                  // the employee's current Position lines up with this
                  // spec, the chip becomes "Current position" (muted).
                  let expLabel = formatMonths(row.actual_months);
                  if (row.actual_months === null && row.current_position_match) {
                    expLabel = "Current position";
                  }
                  // HRP-173 redo case 2.1: "no tenure on the matching
                  // specs" is muted, not red — the operator should see
                  // the absence as missing data rather than a failure.
                  let chipClass: string = BADGE_COLOR.neutral;
                  if (row.actual_months !== null) {
                    chipClass = row.qualifies ? BADGE_COLOR.green : BADGE_COLOR.red;
                  }
                  return (
                    <li
                      key={row.specialization_id}
                      className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm"
                      data-testid="talent-market-match-drawer-spec-row"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium">
                          {row.specialization_title}
                          {row.grade_title && (
                            <span className="ml-2 text-muted-foreground">
                              · {row.grade_title}
                            </span>
                          )}
                        </p>
                        {row.required_years != null && row.required_years > 0 && (
                          <p className="text-xs text-muted-foreground">
                            Required: {row.required_years} year
                            {row.required_years === 1 ? "" : "s"}
                          </p>
                        )}
                      </div>
                      <Badge
                        variant="secondary"
                        className={chipClass}
                        data-testid="talent-market-match-drawer-experience-value"
                      >
                        {expLabel}
                      </Badge>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          {data &&
            data.competences.length === 0 &&
            data.specializations.length === 0 &&
            !loading && (
              <p className="text-sm text-muted-foreground">
                This card has no requirements yet — set Required competencies or
                Required specializations to compute a match.
              </p>
            )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
