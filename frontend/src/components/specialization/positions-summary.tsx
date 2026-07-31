"use client";

import { useTranslations } from "next-intl";

import type { DivisionPositionsBlock } from "@/lib/api/specializations";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

/** Lifecycle status code → key in the `company` i18n namespace. Unknown
 * codes fall through to the raw value, as before. */
const STATUS_LABEL_KEY: Record<string, string> = {
  active: "positionStatusActive",
  on_hold: "positionStatusOnHold",
  frozen: "positionStatusFrozen",
  closed: "positionStatusClosed",
};

export function PositionsSummary({
  blocks,
}: {
  blocks: DivisionPositionsBlock[];
}) {
  const t = useTranslations("company");
  if (blocks.length === 0) {
    return (
      <p
        data-testid="specialization-positions-summary-empty"
        className="py-8 text-center text-sm text-muted-foreground"
      >
        {t("positionsSummaryEmpty")}
      </p>
    );
  }

  return (
    <div
      data-testid="specialization-positions-summary"
      className="space-y-6"
    >
      {blocks.map((block) => {
        const headcount = block.positions.reduce(
          (acc, p) => acc + (p.headcount ?? 0),
          0,
        );
        const assigned = block.positions.reduce(
          (acc, p) => acc + p.assigned,
          0,
        );
        return (
          <div
            key={block.division_id ?? "unassigned"}
            data-testid={`specialization-positions-block-${block.division_id ?? "unassigned"}`}
            className="rounded-lg border"
          >
            <div className="flex items-center justify-between border-b px-4 py-2">
              <h3 className="text-sm font-semibold">
                {block.division_name ?? t("unassigned")}
              </h3>
              <span className="text-xs text-muted-foreground">
                {t("assignedOfPlan", { assigned, headcount })}
              </span>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("position")}</TableHead>
                  <TableHead>{t("grade")}</TableHead>
                  <TableHead className="w-32 text-right">
                    {t("colAssignedPlan")}
                  </TableHead>
                  <TableHead className="w-24">{t("status")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {block.positions.map((pos) => (
                  <TableRow key={pos.id}>
                    <TableCell className="font-medium">{pos.title}</TableCell>
                    <TableCell>{pos.grade_title ?? "—"}</TableCell>
                    <TableCell className="text-right">
                      {pos.assigned}/{pos.headcount ?? 0}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="capitalize">
                        {STATUS_LABEL_KEY[pos.lifecycle_status]
                          ? t(STATUS_LABEL_KEY[pos.lifecycle_status])
                          : pos.lifecycle_status}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        );
      })}
    </div>
  );
}
