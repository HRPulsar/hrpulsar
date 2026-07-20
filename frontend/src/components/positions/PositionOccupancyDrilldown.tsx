"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  EmployeeList,
  type EmployeeListItem,
} from "@/components/employees/EmployeeListRow";

export interface PositionOccupancySummary {
  id: string;
  title: string;
  headcount: number | null;
  employee_count: number;
}

export interface PositionOccupancyDrilldownProps {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  position: PositionOccupancySummary | null;
}

/**
 * HRP-175: builds the readable subtitle for the drilldown header.
 * Replaces the cryptic "2/3" form with explicit phrasing:
 * - `Showing 2 of 3 employees` when `headcount` is set and differs from
 *   the loaded list size (the legacy filtered-by-plan case)
 * - `N employees` (or `1 employee`) for the unambiguous total
 * - `No employees` when the list is empty (matches the body empty state)
 */
export function buildDrilldownCounter(
  position: PositionOccupancySummary | null,
): string {
  if (!position) return "";
  const total = position.employee_count;
  const plan = position.headcount;
  if (plan != null && plan !== total) {
    return `Showing ${total} of ${plan} employees`;
  }
  if (total === 0) return "No employees";
  if (total === 1) return "1 employee";
  return `${total} employees`;
}

export function PositionOccupancyDrilldown({
  open,
  onOpenChange,
  position,
}: PositionOccupancyDrilldownProps) {
  const [employees, setEmployees] = useState<EmployeeListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const positionId = position?.id ?? null;

  const refresh = useCallback(
    async (id: string) => {
      setLoading(true);
      setError(null);
      setEmployees([]);
      try {
        const data = await api.get<EmployeeListItem[]>(
          `/positions/${id}/employees?with_alerts=true`,
        );
        setEmployees(data);
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (!open || !positionId) return;
    void refresh(positionId);
  }, [open, positionId, refresh]);

  const counterLabel = buildDrilldownCounter(position);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* HRP-175: widen to 960px on desktop, fall back to full-screen
          sheet under sm. Body scrolls inside the popup so the sticky
          column header on the employee list stays anchored. */}
      <DialogContent
        data-testid="positions-drilldown"
        className="flex max-h-[85vh] w-[min(960px,92vw)] flex-col gap-0 p-0 sm:max-w-[960px]"
      >
        <DialogHeader className="border-b p-4">
          <DialogTitle
            data-testid="positions-drilldown-header-title"
            className="text-lg font-semibold"
          >
            {position?.title ?? "Position"}
          </DialogTitle>
          {counterLabel ? (
            <DialogDescription
              data-testid="positions-drilldown-header-counter"
              className="text-sm text-muted-foreground"
            >
              {counterLabel}
            </DialogDescription>
          ) : null}
        </DialogHeader>
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="py-12 text-center text-sm text-muted-foreground">
              Loading…
            </div>
          ) : error ? (
            <div
              data-testid="positions-drilldown-error"
              className="py-12 text-center text-sm text-destructive"
            >
              {error}
            </div>
          ) : employees.length === 0 ? (
            <div
              data-testid="positions-drilldown-empty"
              className="py-12 text-center text-sm text-muted-foreground"
            >
              No employees on this position.
            </div>
          ) : (
            <EmployeeList
              employees={employees}
              testIdPrefix="positions-drilldown-row"
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
