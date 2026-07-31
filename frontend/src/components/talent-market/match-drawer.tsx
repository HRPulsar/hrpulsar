"use client";

// HRP-172: Match drawer (shadcn Sheet) opened from the Match cell in the
// Candidates list and the Add / Change picker dialogs on the card detail
// page. Renders a per-Required-Competence row with the projected percent
// the matcher used (HRP-129 REDO), plus a per-Required-Specialization
// row with the employee's total tenure on matching positions and whether
// it clears the min_experience_years floor. Colour rules mirror HRP-173.

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { api } from "@/lib/api";
import { BADGE_COLOR } from "@/lib/badge-tones";
import { dictionaryItemLabel, skillLevelLabel } from "@/lib/reference-labels";
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
  // HRP-479: origin reference rows localize via reference.* keys.
  required_skill_level_i18n_key?: string | null;
  card_match_percent: number;
  actual_percent: number | null;
  qualifies: boolean;
}

interface BreakdownSpecRow {
  specialization_id: string;
  specialization_title: string;
  specialization_i18n_key?: string | null;
  grade_id: string | null;
  grade_title: string | null;
  grade_i18n_key?: string | null;
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

// HRP-476: the wording lives in the `talentMarket` i18n namespace, so the
// helper takes the translator as a parameter instead of owning literals.
function formatMonths(
  t: (key: string, values?: Record<string, number>) => string,
  total: number | null,
): string {
  if (total === null) return t("experienceNone");
  if (total <= 0) return t("experienceLessThanMonth");
  const years = Math.floor(total / 12);
  const months = total % 12;
  const yearPart = years ? t("experienceYears", { count: years }) : "";
  const monthPart = months ? t("experienceMonths", { count: months }) : "";
  if (yearPart && monthPart) return `${yearPart} ${monthPart}`;
  return yearPart || monthPart || t("experienceLessThanMonth");
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
  const t = useTranslations("talentMarket");
  const tRef = useTranslations("reference");
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
          setError(err instanceof Error ? err.message : t("toastLoadFailed"));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    });
    return () => {
      cancelled = true;
    };
  }, [cardId, employeeId, open, t]);

  const title = data?.employee_name ?? employeeName ?? t("drawerFallbackTitle");

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent data-testid="talent-market-match-drawer">
        <SheetHeader>
          <SheetTitle data-testid="talent-market-match-drawer-title">
            {title}
          </SheetTitle>
          <SheetDescription>{t("drawerDescription")}</SheetDescription>
        </SheetHeader>

        {/* HRP-172 redo item 5: large requirement / experience lists
            used to clip past the viewport — wrap the body in a flex
            column so the inner list can scroll within the Sheet panel. */}
        <div className="flex-1 space-y-6 overflow-y-auto p-5">
          {loading && (
            <p className="text-sm text-muted-foreground">
              {t("loadingEllipsis")}
            </p>
          )}
          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}

          {data && data.competences.length > 0 && (
            <section data-testid="talent-market-match-drawer-competences">
              <h3 className="mb-2 text-sm font-medium">
                {t("requiredCompetencies")}
              </h3>
              <p className="mb-3 text-xs text-muted-foreground">
                {t("drawerThreshold", { percent: data.card_match_percent })}
              </p>
              <ul className="space-y-2">
                {data.competences.map((row) => {
                  const pctLabel =
                    row.actual_percent === null
                      ? t("drawerNoAssessment")
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
                            {t("drawerRequiredLevel", {
                              level: skillLevelLabel(tRef, {
                                title: row.required_skill_level_title,
                                i18n_key: row.required_skill_level_i18n_key,
                              }),
                            })}
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
              <h3 className="mb-2 text-sm font-medium">
                {t("drawerExperience")}
              </h3>
              <ul className="space-y-2">
                {data.specializations.map((row) => {
                  // HRP-210: when there's no WorkExperience tenure but
                  // the employee's current Position lines up with this
                  // spec, the chip becomes "Current position" (muted).
                  let expLabel = formatMonths(t, row.actual_months);
                  if (row.actual_months === null && row.current_position_match) {
                    expLabel = t("drawerCurrentPosition");
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
                          {dictionaryItemLabel(tRef, {
                            type: "specialization",
                            title: row.specialization_title,
                            i18n_key: row.specialization_i18n_key,
                          })}
                          {row.grade_title && (
                            <span className="ml-2 text-muted-foreground">
                              ·{" "}
                              {dictionaryItemLabel(tRef, {
                                type: "grade",
                                title: row.grade_title,
                                i18n_key: row.grade_i18n_key,
                              })}
                            </span>
                          )}
                        </p>
                        {row.required_years != null && row.required_years > 0 && (
                          <p className="text-xs text-muted-foreground">
                            {t("drawerRequiredYears", {
                              count: row.required_years,
                            })}
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
                {t("drawerEmptyRequirements")}
              </p>
            )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
