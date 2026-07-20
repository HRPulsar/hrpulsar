"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Info, Save } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import type { DictionaryItem, GradeSpecialization } from "@/lib/types";
import { RequireRole } from "@/components/require-role";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const PASSING_SCORE_HINT =
  "Passing score — the percentage threshold above which the grade is considered confirmed after an assessment. Default 75%, configurable from 0 to 100 in 1% steps.";

export default function SpecializationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [specialization, setSpecialization] = useState<DictionaryItem | null>(null);
  const [chains, setChains] = useState<GradeSpecialization[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [specs, chainList] = await Promise.all([
        api.get<DictionaryItem[]>("/dictionaries/specialization"),
        api.get<GradeSpecialization[]>(`/grade-system/specializations/${id}`),
      ]);
      const spec = specs.find((s) => s.id === id) ?? null;
      setSpecialization(spec);
      setChains(chainList);
      setDrafts(
        Object.fromEntries(
          chainList.map((c) => [
            c.id,
            c.passing_score == null ? "75" : String(c.passing_score),
          ]),
        ),
      );
    } catch {
      toast.error("Failed to load specialization");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function saveScore(chain: GradeSpecialization) {
    const raw = drafts[chain.id];
    const value = Number(raw);
    if (!Number.isFinite(value) || value < 0 || value > 100 || !Number.isInteger(value)) {
      toast.error("Enter a whole number between 0 and 100");
      return;
    }
    if (value === chain.passing_score) return;
    setSavingId(chain.id);
    try {
      await api.put(`/grade-system/chains/${chain.id}`, { passing_score: value });
      toast.success("Passing score saved");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSavingId(null);
    }
  }

  return (
    <RequireRole manage>
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon-sm"
            render={<Link href="/dictionaries" />}
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="flex-1">
            <h1 className="text-2xl font-semibold tracking-tight">
              {specialization?.title ?? "Specialization"}
            </h1>
            <p className="text-sm text-muted-foreground">
              Grades and passing scores
            </p>
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Grades and passing scores</CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                Loading…
              </div>
            ) : chains.length === 0 ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                No grades configured for this specialization yet.
              </div>
            ) : (
              <div className="rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Grade</TableHead>
                      <TableHead>Competences</TableHead>
                      <TableHead>
                        <span className="inline-flex items-center gap-1.5">
                          Passing score (%)
                          <span
                            title={PASSING_SCORE_HINT}
                            className="text-muted-foreground"
                            aria-label="Passing score tooltip"
                          >
                            <Info className="size-3.5" />
                          </span>
                        </span>
                      </TableHead>
                      <TableHead className="w-32" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {chains
                      .slice()
                      .sort((a, b) => a.sort_index - b.sort_index)
                      .map((chain) => {
                        const draft = drafts[chain.id] ?? "";
                        const dirty = draft !== String(chain.passing_score ?? 75);
                        return (
                          <TableRow key={chain.id}>
                            <TableCell className="font-medium">
                              {chain.grade_title}
                            </TableCell>
                            <TableCell className="text-muted-foreground">
                              {chain.competence_links.length}
                            </TableCell>
                            <TableCell>
                              <Input
                                type="number"
                                min={0}
                                max={100}
                                step={1}
                                value={draft}
                                onChange={(e) =>
                                  setDrafts((prev) => ({
                                    ...prev,
                                    [chain.id]: e.target.value,
                                  }))
                                }
                                className="w-24"
                                data-testid={`grade-spec-passing-score-input-${chain.grade_id}`}
                              />
                            </TableCell>
                            <TableCell>
                              <Button
                                size="xs"
                                variant={dirty ? "default" : "outline"}
                                disabled={!dirty || savingId === chain.id}
                                onClick={() => saveScore(chain)}
                                data-testid={`grade-spec-passing-score-save-${chain.grade_id}`}
                              >
                                <Save className="mr-1 h-3 w-3" />
                                {savingId === chain.id ? "Saving…" : "Save"}
                              </Button>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </RequireRole>
  );
}
