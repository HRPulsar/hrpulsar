"use client";

import type { SkillLevel } from "@/lib/types";
import { levelTint } from "@/lib/matrix-grading";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

type Props = {
  competenceId: string;
  gradeId: string;
  levelId: string | null;
  skillLevels: SkillLevel[];
  isDirty: boolean;
  onChange: (levelId: string | null) => void;
  onShowIndicators: () => void;
  disabled?: boolean;
  /** HRP-157 REDO: skip the inner tint + padding wrapper when the
   * caller already provides a styled container (the single-grade
   * list view stamps a colored chip around the cell). Keeps the cell
   * portable across the multi-grade table and the new list layout
   * without duplicating the dirty-underline / hidden-info logic. */
  unstyled?: boolean;
};

export function MatrixCell({
  competenceId,
  gradeId,
  levelId,
  skillLevels,
  isDirty,
  onChange,
  onShowIndicators,
  disabled,
  unstyled,
}: Props) {
  const tint = levelTint(levelId, skillLevels);
  return (
    <div
      data-testid={`matrix-cell-${competenceId}-${gradeId}`}
      data-level-tint={tint ?? "none"}
      className={cn(
        "relative flex items-center gap-1",
        !unstyled && "rounded-md px-1 py-0.5",
        !unstyled && tint,
        isDirty &&
          "underline decoration-orange-500 decoration-2 underline-offset-4",
      )}
    >
      <select
        data-testid={`matrix-cell-select-${competenceId}-${gradeId}`}
        className="h-8 min-w-[8rem] rounded-md border bg-background px-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
        value={levelId ?? ""}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
      >
        <option value="">—</option>
        {skillLevels.map((lvl) => (
          <option key={lvl.id} value={lvl.id}>
            {lvl.title}
          </option>
        ))}
      </select>
      {/* HRP-157 item 4: replace the native `title` (which inherits the
          browser's ~500 ms delay) with the snappy Tooltip provider so the
          hint matches the rest of the matrix UI. */}
      <Tooltip>
        <TooltipTrigger
          render={
            <button
              type="button"
              data-testid={`matrix-cell-btn-info-${competenceId}-${gradeId}`}
              className="text-xs text-muted-foreground hover:text-foreground"
              onClick={onShowIndicators}
              disabled={disabled}
              aria-label="Show indicators"
            />
          }
        >
          ⓘ
        </TooltipTrigger>
        <TooltipContent>Show indicators</TooltipContent>
      </Tooltip>
    </div>
  );
}
