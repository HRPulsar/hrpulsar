"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, ChevronRight, Star } from "lucide-react";
import { useTranslations } from "next-intl";

import { MatchPercentChip } from "@/components/assessment/match-percent-chip";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { MAX_INLINE_AVATARS } from "@/lib/assessment/group-analytics";
import { ALERT_TONE, BADGE_COLOR } from "@/lib/badge-tones";
import { dictionaryItemLabel } from "@/lib/reference-labels";
import type { GroupAnalyticsEmployee } from "@/lib/types";
import { cn } from "@/lib/utils";

export type HighlightVariant = "atRisk" | "topPerformers";

function initials(name: string | null): string {
  if (!name) return "?";
  return name
    .split(" ")
    .map((part) => part[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
}

function EmployeeAvatar({
  employee,
  className,
}: {
  employee: GroupAnalyticsEmployee;
  className?: string;
}) {
  return (
    <Avatar className={cn("h-7 w-7", className)} size="sm">
      {employee.avatar_url && <AvatarImage src={employee.avatar_url} />}
      <AvatarFallback className="text-[10px]">
        {initials(employee.full_name)}
      </AvatarFallback>
    </Avatar>
  );
}

/** Specialization · Grade, falling back to the denormalized position title. */
function useSubtitle() {
  const tRef = useTranslations("reference");
  return (employee: GroupAnalyticsEmployee): string | null => {
    const parts: string[] = [];
    if (employee.specialization_title) {
      parts.push(
        dictionaryItemLabel(tRef, {
          type: "specialization",
          title: employee.specialization_title,
          i18n_key: employee.specialization_i18n_key,
        }),
      );
    }
    if (employee.grade_title) {
      parts.push(
        dictionaryItemLabel(tRef, {
          type: "grade",
          title: employee.grade_title,
          i18n_key: employee.grade_i18n_key,
        }),
      );
    }
    if (parts.length > 0) return parts.join(" · ");
    return employee.position_title ?? null;
  };
}

interface EmployeeHighlightPlateProps {
  variant: HighlightVariant;
  employees: GroupAnalyticsEmployee[];
}

export function EmployeeHighlightPlate({
  variant,
  employees,
}: EmployeeHighlightPlateProps) {
  const t = useTranslations("assessments");
  const [open, setOpen] = useState(false);
  const subtitle = useSubtitle();

  const isAtRisk = variant === "atRisk";
  const testId = isAtRisk
    ? "group-analytics-at-risk"
    : "group-analytics-top-performers";
  const title = isAtRisk
    ? t("analyticsEmployeesAtRisk")
    : t("analyticsTopPerformers");
  const banner = isAtRisk
    ? t("analyticsEmployeesAtRiskHint")
    : t("analyticsTopPerformersHint");
  const Icon = isAtRisk ? AlertTriangle : Star;
  const empty = employees.length === 0;
  const inline = employees.slice(0, MAX_INLINE_AVATARS);
  const overflow = employees.length - inline.length;

  return (
    <>
      <button
        type="button"
        disabled={empty}
        onClick={() => setOpen(true)}
        className={cn(
          "flex w-full items-center justify-between gap-3 rounded-lg border px-4 py-3 text-left transition-colors",
          empty
            ? "cursor-not-allowed opacity-60"
            : "cursor-pointer hover:bg-muted/60",
        )}
        data-testid={testId}
      >
        <div className="flex min-w-0 items-center gap-2">
          <Icon
            className={cn(
              "h-4 w-4 shrink-0",
              isAtRisk ? "text-amber-600" : "text-green-600",
            )}
          />
          <span className="truncate text-sm font-medium">{title}</span>
          {empty ? (
            <Badge
              variant="secondary"
              className={BADGE_COLOR.neutral}
              data-testid={`${testId}-count`}
            >
              {t("analyticsNone")}
            </Badge>
          ) : (
            <Badge
              variant="secondary"
              className={isAtRisk ? BADGE_COLOR.amber : BADGE_COLOR.green}
              data-testid={`${testId}-count`}
            >
              {employees.length}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          {inline.length > 0 && (
            <div className="flex -space-x-2">
              {inline.map((employee) => (
                <Tooltip key={employee.employee_id}>
                  <TooltipTrigger
                    render={<span className="inline-flex" tabIndex={-1} />}
                  >
                    <EmployeeAvatar
                      employee={employee}
                      className="ring-2 ring-background"
                    />
                  </TooltipTrigger>
                  <TooltipContent>{employee.full_name}</TooltipContent>
                </Tooltip>
              ))}
            </div>
          )}
          {overflow > 0 && (
            <Badge
              variant="secondary"
              className={BADGE_COLOR.neutral}
              data-testid={`${testId}-overflow`}
            >
              {t("analyticsOverflowCount", { count: overflow })}
            </Badge>
          )}
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
        </div>
      </button>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent
          className="max-w-lg sm:max-w-lg"
          data-testid={`${testId}-sheet`}
        >
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              {title}
              <Badge
                variant="secondary"
                className={isAtRisk ? BADGE_COLOR.amber : BADGE_COLOR.green}
              >
                {employees.length}
              </Badge>
            </SheetTitle>
          </SheetHeader>

          <div
            className={cn(
              "flex items-start gap-2 rounded-lg border px-3 py-2 text-sm",
              isAtRisk ? ALERT_TONE.amber : ALERT_TONE.green,
            )}
          >
            <Icon className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{banner}</span>
          </div>

          <div className="flex-1 space-y-1 overflow-y-auto pr-1">
            {employees.map((employee) => {
              const secondary = subtitle(employee);
              return (
                <div
                  key={employee.employee_id}
                  className="flex items-center gap-3 rounded-lg border px-3 py-2"
                  data-testid={`${testId}-row-${employee.employee_id}`}
                >
                  <EmployeeAvatar employee={employee} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">
                      {employee.full_name}
                    </div>
                    {secondary && (
                      <div className="truncate text-xs text-muted-foreground">
                        {secondary}
                      </div>
                    )}
                    {employee.division_name && (
                      <div className="truncate text-xs text-muted-foreground">
                        {employee.division_name}
                      </div>
                    )}
                  </div>
                  <MatchPercentChip percent={employee.percent} />
                  <Tooltip>
                    <TooltipTrigger
                      render={<span className="inline-flex" tabIndex={-1} />}
                    >
                      <Link
                        href={`/assessments/${employee.assessment_id}`}
                        className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                        aria-label={t("analyticsGoToAssessment")}
                        data-testid={`${testId}-link-${employee.employee_id}`}
                      >
                        <ChevronRight className="h-4 w-4" />
                      </Link>
                    </TooltipTrigger>
                    <TooltipContent>
                      {t("analyticsGoToAssessment")}
                    </TooltipContent>
                  </Tooltip>
                </div>
              );
            })}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
