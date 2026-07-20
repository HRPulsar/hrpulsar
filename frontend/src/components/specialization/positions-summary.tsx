"use client";

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

const STATUS_LABEL: Record<string, string> = {
  active: "Active",
  on_hold: "On hold",
  frozen: "Frozen",
  closed: "Closed",
};

export function PositionsSummary({
  blocks,
}: {
  blocks: DivisionPositionsBlock[];
}) {
  if (blocks.length === 0) {
    return (
      <p
        data-testid="specialization-positions-summary-empty"
        className="py-8 text-center text-sm text-muted-foreground"
      >
        No positions reference this specialization yet.
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
                {block.division_name ?? "Unassigned"}
              </h3>
              <span className="text-xs text-muted-foreground">
                {assigned}/{headcount} assigned
              </span>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Position</TableHead>
                  <TableHead>Grade</TableHead>
                  <TableHead className="w-32 text-right">
                    Assigned / plan
                  </TableHead>
                  <TableHead className="w-24">Status</TableHead>
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
                        {STATUS_LABEL[pos.lifecycle_status] ??
                          pos.lifecycle_status}
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
