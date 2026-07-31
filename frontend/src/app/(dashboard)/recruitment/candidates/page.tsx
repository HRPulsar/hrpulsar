"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { Candidate, CandidateList } from "@/lib/types";
import { formatDate } from "@/lib/date-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import { Pagination } from "@/components/pagination";
import { usePermissions } from "@/hooks/use-permissions";
import { RecruitmentBreadcrumbs, RecruitmentTabs } from "@/components/recruitment";
import { Search, UserPlus, X } from "lucide-react";
import {
  CANDIDATE_SOURCE_OPTIONS,
  candidateSourceLabel,
} from "@/lib/candidate-source";

const PAGE_SIZE = 25;

export default function CandidateListPage() {
  const router = useRouter();
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [filterSource, setFilterSource] = useState("");

  const { canManage } = usePermissions();

  const loadCandidates = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(PAGE_SIZE));
      if (filterSource) params.set("source", filterSource);
      const data = await api.get<CandidateList>(`/recruitment/candidates?${params}`);
      setCandidates(data.items);
      setTotal(data.total);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [page, filterSource]);

  useEffect(() => {
    loadCandidates();
  }, [loadCandidates]);

  function applyFilter(source: string) {
    setFilterSource(source);
    setPage(1);
  }

  function clearFilters() {
    setSearchQuery("");
    setFilterSource("");
    setPage(1);
  }

  const hasFilters = searchQuery || filterSource;

  const filtered = searchQuery
    ? candidates.filter((c) => {
        // HRP-181 REDO: ``person`` is null for externally-sourced
        // candidates — fall back to the denormalised canonical columns.
        const fullName = (
          c.full_name ||
          (c.person
            ? `${c.person.first_name} ${c.person.last_name}`
            : "")
        ).toLowerCase();
        const email = (c.email ?? c.person?.email ?? "").toLowerCase();
        const q = searchQuery.toLowerCase();
        return fullName.includes(q) || email.includes(q);
      })
    : candidates;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        {tc("loading")}
      </div>
    );
  }

  return (
    <div data-testid="recruitment-candidate-list" className="space-y-6">
      <RecruitmentBreadcrumbs segments={[{ label: t("candidatesTitle") }]} />
      <RecruitmentTabs />
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("candidatesTitle")}
          </h1>
          <p className="text-sm text-muted-foreground">
            {t("candidatesTotalCount", { count: total })}
          </p>
        </div>
        {canManage && (
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              data-testid="recruitment-btn-add-candidate"
              onClick={() => router.push("/recruitment/candidates/new")}
            >
              <UserPlus className="mr-1 h-4 w-4" />
              {t("candidateAddButton")}
            </Button>
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            data-testid="recruitment-candidate-input-search"
            placeholder={t("candidatesSearchPlaceholder")}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8"
          />
        </div>
        <Select value={filterSource} onValueChange={(val) => applyFilter(val)}>
          <SelectTrigger className="w-40" data-testid="recruitment-candidate-select-source">
            <SelectValue placeholder={t("candidatesFilterAllSources")}>
              {filterSource
                ? candidateSourceLabel(t, filterSource)
                : t("candidatesFilterAllSources")}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="">{t("candidatesFilterAllSources")}</SelectItem>
            {CANDIDATE_SOURCE_OPTIONS.map((s) => (
              <SelectItem key={s} value={s}>
                {candidateSourceLabel(t, s)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {hasFilters && (
          <Button variant="ghost" size="sm" onClick={clearFilters}>
            <X className="mr-1 h-3 w-3" />
            {t("actionClear")}
          </Button>
        )}
      </div>

      {filtered.length === 0 ? (
        <div
          data-testid="recruitment-candidate-empty"
          className="rounded-lg border border-dashed p-12 text-center text-muted-foreground"
        >
          <UserPlus className="mx-auto mb-3 h-10 w-10 opacity-40" />
          <p className="text-sm font-medium">
            {hasFilters ? t("candidatesEmptyFiltered") : t("candidatesEmpty")}
          </p>
          {!hasFilters && canManage && (
            <p className="mt-1 text-xs">{t("candidatesEmptyHint")}</p>
          )}
        </div>
      ) : (
        <>
          <div className="rounded-lg border">
            <Table data-testid="recruitment-candidate-table">
              <TableHeader>
                <TableRow>
                  <TableHead>{t("fieldName")}</TableHead>
                  <TableHead>{t("columnEmail")}</TableHead>
                  <TableHead>{t("columnSource")}</TableHead>
                  <TableHead>{t("columnResumes")}</TableHead>
                  <TableHead>{t("columnCreated")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((candidate) => (
                  <TableRow
                    key={candidate.id}
                    data-testid={`recruitment-candidate-row-${candidate.id}`}
                  >
                    <TableCell className="font-medium">
                      <Link
                        href={`/recruitment/candidates/${candidate.id}`}
                        className="hover:underline"
                        data-testid={`recruitment-candidate-row-${candidate.id}-name`}
                      >
                        {(
                          candidate.full_name ||
                          (candidate.person
                            ? `${candidate.person.first_name} ${candidate.person.last_name}`
                            : "")
                        ).trim() || t("candidateParsing")}
                      </Link>
                      {candidate.is_employee && (
                        <Badge variant="outline" className="ml-2 text-[10px]">
                          {tc("employee")}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {candidate.email || candidate.person?.email || "---"}
                    </TableCell>
                    <TableCell className="text-muted-foreground capitalize">
                      {candidateSourceLabel(t, candidate.source) || "---"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {candidate.resumes_count ?? 0}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDate(candidate.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </>
      )}
    </div>
  );
}
