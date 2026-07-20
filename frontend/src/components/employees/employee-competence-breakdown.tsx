"use client";

import { useState } from "react";
import { Info } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import type { EmployeeCompetenceLevelBreakdown } from "@/lib/types";
import { BADGE_COLOR } from "@/lib/badge-tones";

interface EmployeeCompetenceBreakdownProps {
  competenceId: string;
  competenceTitle: string;
  breakdown: EmployeeCompetenceLevelBreakdown[];
  /** Used to build a stable `data-testid` per row/button. */
  testIdPrefix: string;
}

function levelTone(percent: number): string {
  if (percent >= 75) return BADGE_COLOR.green;
  if (percent >= 50) return BADGE_COLOR.yellow;
  return BADGE_COLOR.red;
}

export function EmployeeCompetenceBreakdown({
  competenceId,
  competenceTitle,
  breakdown,
  testIdPrefix,
}: EmployeeCompetenceBreakdownProps) {
  const [open, setOpen] = useState(false);
  // No breakdown rows yet -> render an inert placeholder so the row
  // alignment doesn't jump around when some rows have data and others
  // don't. The button just doesn't open anything.
  if (breakdown.length === 0) {
    return (
      <span
        aria-hidden
        className="inline-flex size-7 items-center justify-center text-muted-foreground/30"
        data-testid={`${testIdPrefix}-info-disabled-${competenceId}`}
      >
        <Info className="size-4" />
      </span>
    );
  }
  const sorted = [...breakdown].sort(
    (a, b) => a.skill_level_sort_index - b.skill_level_sort_index,
  );
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <button
            type="button"
            className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
            data-testid={`${testIdPrefix}-info-${competenceId}`}
            aria-label={`Per-level breakdown for ${competenceTitle}`}
          />
        }
      >
        <Info className="size-4" />
      </DialogTrigger>
      <DialogContent
        data-testid={`${testIdPrefix}-breakdown-modal-${competenceId}`}
      >
        <DialogHeader>
          <DialogTitle>{competenceTitle}</DialogTitle>
        </DialogHeader>
        <table className="w-full text-sm" data-testid={`${testIdPrefix}-breakdown-table`}>
          <thead>
            <tr className="border-b text-left text-xs uppercase text-muted-foreground">
              <th className="py-1.5">Skill level</th>
              <th className="py-1.5 text-right">Percent</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr
                key={row.skill_level_id}
                className="border-b last:border-0"
                data-testid={`${testIdPrefix}-breakdown-row-${row.skill_level_id}`}
              >
                <td className="py-2">{row.skill_level_title}</td>
                <td className="py-2 text-right">
                  <span
                    className={`rounded-md px-2 py-0.5 text-xs font-medium ${levelTone(row.percent)}`}
                  >
                    {row.percent}%
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DialogContent>
    </Dialog>
  );
}
