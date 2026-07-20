"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Employee, EmployeeList, Position } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { RequireRole } from "@/components/require-role";
import { toast } from "sonner";

export default function UnassignedEmployeesPage() {
  return (
    <RequireRole manage>
      <UnassignedEmployeesView />
    </RequireRole>
  );
}

function UnassignedEmployeesView() {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [pendingPos, setPendingPos] = useState<Record<string, string>>({});

  async function load() {
    setLoading(true);
    try {
      const [empRes, posRes] = await Promise.all([
        api.get<EmployeeList>("/employees?unassigned_only=true&limit=100"),
        api.get<{ items: Position[]; total: number }>("/positions?limit=100"),
      ]);
      setEmployees(empRes.items);
      setPositions(
        posRes.items.filter((p) => p.lifecycle_status !== "closed"),
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function assign(emp: Employee) {
    const positionId = pendingPos[emp.id];
    if (!positionId) {
      toast.error("Pick a position first");
      return;
    }
    setSavingId(emp.id);
    try {
      await api.put(`/employees/${emp.id}`, { position_id: positionId });
      toast.success("Position assigned");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to assign");
    } finally {
      setSavingId(null);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        Loading...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Unassigned employees
        </h1>
        <p className="text-sm text-muted-foreground">
          Employees without a position. Assign them to a staff record so
          headcount and competence matrix flows can pick them up.
        </p>
      </div>

      <Table data-testid="unassigned-table">
        <TableHeader>
          <TableRow>
            <TableHead>Employee</TableHead>
            <TableHead>Division</TableHead>
            <TableHead>Hire date</TableHead>
            <TableHead>Position</TableHead>
            <TableHead className="w-32" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {employees.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={5}
                data-testid="unassigned-empty"
                className="py-8 text-center text-muted-foreground"
              >
                Every employee has a position assigned.
              </TableCell>
            </TableRow>
          ) : (
            employees.map((emp) => (
              <TableRow
                key={emp.id}
                data-testid={`unassigned-row-${emp.id}`}
              >
                <TableCell className="font-medium">
                  {emp.user_name || emp.user_email || emp.id}
                </TableCell>
                <TableCell>{emp.division_name || "—"}</TableCell>
                <TableCell>{emp.hire_date}</TableCell>
                <TableCell>
                  <div className="space-y-1">
                    <Label className="sr-only">Position</Label>
                    <Select
                      value={pendingPos[emp.id] || ""}
                      onValueChange={(val) =>
                        setPendingPos((prev) => ({ ...prev, [emp.id]: val }))
                      }
                    >
                      <SelectTrigger
                        data-testid={`unassigned-row-${emp.id}-select`}
                        className="w-full"
                      >
                        <SelectValue placeholder="Pick a position">
                          {(() => {
                            const id = pendingPos[emp.id];
                            if (!id) return undefined;
                            const p = positions.find((x) => x.id === id);
                            return p ? p.title : undefined;
                          })()}
                        </SelectValue>
                      </SelectTrigger>
                      <SelectContent>
                        {positions.map((p) => (
                          <SelectItem key={p.id} value={p.id}>
                            {p.title}
                            {p.division_name ? ` · ${p.division_name}` : ""}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </TableCell>
                <TableCell>
                  <Button
                    size="sm"
                    data-testid={`unassigned-row-${emp.id}-btn-assign`}
                    onClick={() => assign(emp)}
                    disabled={savingId === emp.id || !pendingPos[emp.id]}
                  >
                    {savingId === emp.id ? "Saving..." : "Assign"}
                  </Button>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
