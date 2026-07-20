"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { API_BASE } from "@/lib/api-base";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { RequireRole } from "@/components/require-role";

interface AssessmentStats {
  total: number;
  by_status: Record<string, number>;
  avg_score: number | null;
}

interface PDPStats {
  total: number;
  by_status: Record<string, number>;
  avg_progress: number;
}

interface MatrixDivision {
  id: string;
  name: string;
}

interface MatrixSpecialization {
  id: string;
  title: string;
}

interface MatrixCell {
  division_id: string;
  specialization_id: string;
  headcount: number;
  active: boolean;
}

interface DivisionMatrix {
  divisions: MatrixDivision[];
  specializations: MatrixSpecialization[];
  cells: MatrixCell[];
}

interface BenchmarkGrade {
  grade_id: string;
  grade_title: string;
  avg_salary: number;
  count: number;
}

interface BenchmarkSpecialization {
  specialization_id: string;
  specialization_title: string;
  avg_salary: number;
  count: number;
}

interface CompensationBenchmark {
  by_grade: BenchmarkGrade[];
  by_specialization: BenchmarkSpecialization[];
}

export default function AnalyticsPage() {
  const [assessmentStats, setAssessmentStats] = useState<AssessmentStats | null>(null);
  const [pdpStats, setPdpStats] = useState<PDPStats | null>(null);
  const [divisionMatrix, setDivisionMatrix] = useState<DivisionMatrix | null>(null);
  const [benchmark, setBenchmark] = useState<CompensationBenchmark | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get<AssessmentStats>("/analytics/assessments").catch(() => null),
      api.get<PDPStats>("/analytics/pdp").catch(() => null),
      api.get<DivisionMatrix>("/analytics/division-matrix").catch(() => null),
      api.get<CompensationBenchmark>("/analytics/compensation/benchmark").catch(() => null),
    ]).then(([a, p, m, b]) => {
      setAssessmentStats(a);
      setPdpStats(p);
      setDivisionMatrix(m);
      setBenchmark(b);
    }).finally(() => setLoading(false));
  }, []);

  async function exportAssessments() {
    const token = localStorage.getItem("access_token");
    const res = await fetch(`${API_BASE}/analytics/export/assessments`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "assessments.xlsx";
    a.click();
    URL.revokeObjectURL(url);
  }

  if (loading) return <div className="py-12 text-center text-muted-foreground">Loading...</div>;

  return (
    <RequireRole manage>
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Analytics</h1>
        <p className="text-sm text-muted-foreground">Organization performance overview</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Assessments</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{assessmentStats?.total ?? 0}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Avg Assessment Score</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{assessmentStats?.avg_score ?? "—"}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total PDPs</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{pdpStats?.total ?? 0}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Avg PDP Progress</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{pdpStats?.avg_progress ?? 0}%</div>
          </CardContent>
        </Card>
      </div>

      <div>
        <h2 className="text-lg font-semibold mb-3">Exports</h2>
        <div className="flex gap-3">
          <Button variant="outline" onClick={exportAssessments}>
            Export Assessments (XLSX)
          </Button>
        </div>
      </div>

      {/* GF5: Compensation Benchmark */}
      {benchmark && (benchmark.by_grade.length > 0 || benchmark.by_specialization.length > 0) && (
        <div>
          <h2 className="text-lg font-semibold mb-3">Compensation Benchmark</h2>
          <div className="grid gap-4 md:grid-cols-2">
            {benchmark.by_grade.length > 0 && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">By Grade</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="rounded-lg border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Grade</TableHead>
                          <TableHead className="text-right">Avg Salary</TableHead>
                          <TableHead className="text-right">Count</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {benchmark.by_grade.map((row) => (
                          <TableRow key={row.grade_id}>
                            <TableCell className="font-medium">{row.grade_title}</TableCell>
                            <TableCell className="text-right">
                              ${(row.avg_salary / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </TableCell>
                            <TableCell className="text-right text-muted-foreground">{row.count}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </CardContent>
              </Card>
            )}
            {benchmark.by_specialization.length > 0 && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">By Specialization</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="rounded-lg border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Specialization</TableHead>
                          <TableHead className="text-right">Avg Salary</TableHead>
                          <TableHead className="text-right">Count</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {benchmark.by_specialization.map((row) => (
                          <TableRow key={row.specialization_id}>
                            <TableCell className="font-medium">{row.specialization_title}</TableCell>
                            <TableCell className="text-right">
                              ${(row.avg_salary / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </TableCell>
                            <TableCell className="text-right text-muted-foreground">{row.count}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}

      {/* GF7: Division-Specialization Matrix */}
      {divisionMatrix && divisionMatrix.divisions.length > 0 && divisionMatrix.specializations.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3">Division-Specialization Matrix</h2>
          <Card>
            <CardContent className="pt-6">
              <div className="overflow-x-auto rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="sticky left-0 bg-background">Division</TableHead>
                      {divisionMatrix.specializations.map((spec) => (
                        <TableHead key={spec.id} className="text-center whitespace-nowrap">
                          {spec.title}
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {divisionMatrix.divisions.map((div) => (
                      <TableRow key={div.id}>
                        <TableCell className="sticky left-0 bg-background font-medium whitespace-nowrap">
                          {div.name}
                        </TableCell>
                        {divisionMatrix.specializations.map((spec) => {
                          const cell = divisionMatrix.cells.find(
                            (c) => c.division_id === div.id && c.specialization_id === spec.id
                          );
                          return (
                            <TableCell key={spec.id} className="text-center">
                              {cell ? (
                                <span className={cell.active ? "font-medium" : "text-muted-foreground"}>
                                  {cell.headcount}
                                </span>
                              ) : (
                                <span className="text-muted-foreground">—</span>
                              )}
                            </TableCell>
                          );
                        })}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
    </RequireRole>
  );
}
