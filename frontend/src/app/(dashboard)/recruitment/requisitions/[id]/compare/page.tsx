"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import type { ComparisonResponse, ComparisonCompetence, Vacancy } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ArrowLeft, Loader2, AlertTriangle, Check } from "lucide-react";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";
import { ALERT_TONE } from "@/lib/badge-tones";

const DIVERGENCE_THRESHOLD = 1.5;

function divergenceFlag(comp: ComparisonCompetence): "ok" | "warn" | "none" {
  if (comp.divergence == null) return "none";
  return comp.divergence >= DIVERGENCE_THRESHOLD ? "warn" : "ok";
}

export default function CompareCandidatesPage() {
  const { id } = useParams<{ id: string }>();
  const search = useSearchParams();
  const [comparison, setComparison] = useState<ComparisonResponse | null>(null);
  const [vacancy, setVacancy] = useState<Vacancy | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [requestKey, setRequestKey] = useState<string>("");

  const candidateIds = useMemo(() => {
    const raw = search.get("candidates") || "";
    return raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }, [search]);

  const tooFewCandidates = candidateIds.length < 2;
  const expectedKey = candidateIds.join(",");

  useEffect(() => {
    if (!id) return;
    api
      .get<Vacancy>(`/recruitment/vacancies/${id}`)
      .then(setVacancy)
      .catch(() => setVacancy(null));
  }, [id]);

  useEffect(() => {
    if (!id || tooFewCandidates) return;
    const params = new URLSearchParams();
    candidateIds.forEach((cid) => params.append("candidate_ids", cid));
    let cancelled = false;
    api
      .get<ComparisonResponse>(
        `/recruitment/vacancies/${id}/comparison?${params.toString()}`,
      )
      .then((res) => {
        if (cancelled) return;
        setComparison(res);
        setFetchError(null);
        setRequestKey(expectedKey);
      })
      .catch((err) => {
        if (cancelled) return;
        setFetchError(
          err instanceof Error ? err.message : "Failed to load",
        );
        setRequestKey(expectedKey);
      });
    return () => {
      cancelled = true;
    };
  }, [id, candidateIds, tooFewCandidates, expectedKey]);

  // Loading is derived from "we expect data for these ids but haven't
  // received it yet" — no effect-driven setState needed.
  const loading = !tooFewCandidates && requestKey !== expectedKey && !fetchError;
  const error = tooFewCandidates
    ? "Select 2–5 candidates to compare"
    : fetchError;

  const competences = comparison?.competences || [];
  const candidates = comparison?.candidates || [];

  return (
    <div className="space-y-6" data-testid="recruitment-compare-page">
      <RecruitmentBreadcrumbs
        segments={[
          { label: "Vacancies", href: "/recruitment/requisitions" },
          {
            label: vacancy?.title || "Vacancy",
            href: `/recruitment/requisitions/${id}`,
          },
          { label: "Compare" },
        ]}
      />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Compare candidates
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {candidates.length > 0
              ? `${candidates.length} candidates · ${competences.length} competences`
              : "Select candidates in the vacancy table."}
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          render={
            <Link href={`/recruitment/requisitions/${id}`}>
              <ArrowLeft className="mr-1 size-4" />
              Back to vacancy
            </Link>
          }
        />
      </div>

      {loading && (
        <div className="flex items-center justify-center py-16 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          <span className="ml-2">Loading…</span>
        </div>
      )}

      {error && (
        <div className={`rounded-lg border p-4 text-sm ${ALERT_TONE.yellow}`}>
          {error}
        </div>
      )}

      {!loading && !error && competences.length === 0 && (
        <div className="rounded-lg border border-dashed p-12 text-center text-muted-foreground">
          <p className="text-sm font-medium">No data to compare</p>
          <p className="mt-1 text-xs">
            Generate a vacancy profile and score candidates first.
          </p>
        </div>
      )}

      {!loading && !error && competences.length > 0 && (
        <div className="rounded-lg border">
          <div className="max-h-[640px] overflow-auto">
            <Table data-testid="recruitment-compare-table">
              <TableHeader className="sticky top-0 z-10 bg-background">
                <TableRow>
                  <TableHead className="min-w-[240px]">Competence</TableHead>
                  {candidates.map((cand) => (
                    <TableHead
                      key={cand.id}
                      className="min-w-[140px] text-center"
                    >
                      <Link
                        href={`/recruitment/candidates/${cand.id}?vacancyId=${id}`}
                        className="font-medium hover:underline"
                      >
                        {cand.name}
                      </Link>
                    </TableHead>
                  ))}
                  <TableHead className="w-[120px] text-right">Δ</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {competences.map((comp) => {
                  const flag = divergenceFlag(comp);
                  return (
                    <TableRow key={comp.competence_id}>
                      <TableCell className="font-medium">
                        <div>{comp.name}</div>
                        {comp.criticality && (
                          <Badge variant="outline" className="mt-1 text-xs">
                            {comp.criticality}
                          </Badge>
                        )}
                      </TableCell>
                      {candidates.map((cand) => {
                        const cell = comp.cells.find(
                          (c) => c.candidate_id === cand.id,
                        );
                        return (
                          <TableCell
                            key={cand.id}
                            className="text-center"
                          >
                            {cell && cell.score != null ? (
                              <div className="flex flex-col items-center">
                                <span className="text-lg font-semibold">
                                  {cell.score.toFixed(1)}
                                </span>
                                <span className="text-xs text-muted-foreground">
                                  {cell.source}
                                </span>
                              </div>
                            ) : (
                              <span className="text-xs text-muted-foreground">
                                —
                              </span>
                            )}
                          </TableCell>
                        );
                      })}
                      <TableCell className="text-right">
                        {comp.divergence == null ? (
                          <span className="text-xs text-muted-foreground">—</span>
                        ) : flag === "warn" ? (
                          <Badge
                            variant="destructive"
                            className="gap-1"
                          >
                            <AlertTriangle className="size-3" />
                            {comp.divergence.toFixed(1)}
                          </Badge>
                        ) : (
                          <Badge variant="secondary" className="gap-1">
                            <Check className="size-3" />
                            {comp.divergence.toFixed(1)}
                          </Badge>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </div>
      )}
    </div>
  );
}
