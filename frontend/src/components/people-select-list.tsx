"use client";

import { Checkbox } from "@/components/ui/checkbox";

/** One selectable person. `disabled` rows render greyed out with a note
 *  (Exams uses it for employees already assigned to the test). */
export interface PersonRow {
  id: string;
  name: string;
  subtitle?: string | null;
  disabled?: boolean;
  disabledNote?: string;
}

interface Props {
  rows: PersonRow[];
  isSelected: (id: string) => boolean;
  onToggle: (id: string) => void;
  loading?: boolean;
  loadingLabel: string;
  emptyLabel: string;
  /** Header row with a "select all" checkbox — omit for a plain list. */
  selectAll?: {
    label: string;
    checked: boolean;
    disabled?: boolean;
    onToggle: () => void;
    testId?: string;
  };
  className?: string;
  testId?: string;
  rowTestId?: (id: string) => string | undefined;
}

/** HRP-386/387: the employee-picker list shared by Exams → Assign
 *  employees and the interview Interviewer(s) fields, so the two stay the
 *  same control instead of drifting as two hand-rolled copies. */
export function PeopleSelectList({
  rows,
  isSelected,
  onToggle,
  loading,
  loadingLabel,
  emptyLabel,
  selectAll,
  className,
  testId,
  rowTestId,
}: Props) {
  return (
    <div
      className={`max-h-80 overflow-y-auto rounded-md border ${className ?? ""}`}
      data-testid={testId}
    >
      {selectAll && (
        <div className="flex items-center gap-3 border-b p-2">
          <Checkbox
            data-testid={selectAll.testId}
            checked={selectAll.checked}
            disabled={selectAll.disabled}
            onCheckedChange={selectAll.onToggle}
          />
          <span className="text-sm text-muted-foreground">
            {selectAll.label}
          </span>
        </div>
      )}
      {loading ? (
        <p className="p-4 text-center text-sm text-muted-foreground">
          {loadingLabel}
        </p>
      ) : rows.length === 0 ? (
        <p className="p-4 text-center text-sm text-muted-foreground">
          {emptyLabel}
        </p>
      ) : (
        <ul className="divide-y">
          {rows.map((row) => (
            <li
              key={row.id}
              className={`flex items-center gap-3 p-2 text-sm ${
                row.disabled ? "opacity-50" : ""
              }`}
            >
              <Checkbox
                checked={isSelected(row.id)}
                disabled={row.disabled}
                onCheckedChange={() => onToggle(row.id)}
                data-testid={rowTestId?.(row.id)}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{row.name}</p>
                {row.subtitle && (
                  <p className="truncate text-xs text-muted-foreground">
                    {row.subtitle}
                  </p>
                )}
              </div>
              {row.disabled && row.disabledNote && (
                <span className="text-xs text-muted-foreground">
                  {row.disabledNote}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
