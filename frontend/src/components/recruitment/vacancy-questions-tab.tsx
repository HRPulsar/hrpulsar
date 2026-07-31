"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type {
  CandidateQuestion,
  CandidateVacancy,
  CompetenceItem,
  VacancyProfile,
} from "@/lib/types";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { FileQuestion } from "lucide-react";
import { QuestionCard } from "./question-card";

interface VacancyQuestionsTabProps {
  vacancyId: string;
  candidates: CandidateVacancy[];
}

interface ProfileWithCompetences extends VacancyProfile {
  profile_data: { competences?: (CompetenceItem & { id?: string })[] } & Record<
    string,
    unknown
  >;
}

export function VacancyQuestionsTab({
  vacancyId,
  candidates,
}: VacancyQuestionsTabProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const router = useRouter();
  const [perCandidate, setPerCandidate] = useState<
    Map<string, CandidateQuestion[]>
  >(new Map());
  const [competences, setCompetences] = useState<{ id: string; name: string }[]>(
    [],
  );
  const [filterCandidate, setFilterCandidate] = useState<string>("");
  const [filterCompetence, setFilterCompetence] = useState<string>("");
  const [loading, setLoading] = useState(true);

  const competenceLookup = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of competences) {
      map.set(c.id, c.name);
    }
    return map;
  }, [competences]);

  const candidateLookup = useMemo(() => {
    const map = new Map<string, string>();
    for (const cv of candidates) {
      if (cv.candidate_name) {
        map.set(cv.candidate_id, cv.candidate_name);
      }
    }
    return map;
  }, [candidates]);

  const loadProfile = useCallback(async () => {
    try {
      const data = await api.get<ProfileWithCompetences | { profile: null }>(
        `/recruitment/vacancies/${vacancyId}/profile`,
      );
      if ("profile" in data && data.profile === null) {
        setCompetences([]);
        return;
      }
      const items = (data as ProfileWithCompetences).profile_data?.competences;
      if (Array.isArray(items)) {
        setCompetences(
          items
            .map((c) => ({
              id: (c as { id?: string }).id || c.name,
              name: c.name,
            }))
            .filter((c) => Boolean(c.id)),
        );
      }
    } catch {
      setCompetences([]);
    }
  }, [vacancyId]);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const candidateIds = candidates.map((c) => c.candidate_id);
      const params = new URLSearchParams({ vacancy_id: vacancyId });
      const results = await Promise.all(
        candidateIds.map((cid) =>
          api
            .get<CandidateQuestion[]>(
              `/recruitment/candidates/${cid}/questions?${params}`,
            )
            .catch(() => [] as CandidateQuestion[]),
        ),
      );
      const map = new Map<string, CandidateQuestion[]>();
      candidateIds.forEach((cid, i) => map.set(cid, results[i] || []));
      setPerCandidate(map);
    } finally {
      setLoading(false);
    }
  }, [vacancyId, candidates]);

  useEffect(() => {
    loadProfile();
    loadAll();
  }, [loadProfile, loadAll]);

  const flattened = useMemo(() => {
    const all: CandidateQuestion[] = [];
    for (const list of perCandidate.values()) {
      all.push(...list);
    }
    return all;
  }, [perCandidate]);

  const filtered = useMemo(() => {
    return flattened.filter((q) => {
      if (filterCandidate && q.candidate_id !== filterCandidate) return false;
      if (filterCompetence) {
        if (filterCompetence === "__none__") {
          if (q.competence_id) return false;
        } else if (q.competence_id !== filterCompetence) {
          return false;
        }
      }
      return true;
    });
  }, [flattened, filterCandidate, filterCompetence]);

  if (loading) {
    return (
      <p className="text-sm text-muted-foreground">
        {t("vacancyQuestionsTabLoading")}
      </p>
    );
  }

  if (candidates.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-12 text-center text-muted-foreground">
        <FileQuestion className="mx-auto mb-3 size-10 opacity-40" />
        <p className="text-sm font-medium">{t("candidatesEmpty")}</p>
        <p className="mt-1 text-xs">{t("vacancyQuestionsTabEmptyHint")}</p>
      </div>
    );
  }

  return (
    <div data-testid="vacancy-questions-tab" className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Select
          value={filterCandidate || "__all__"}
          onValueChange={(v) => setFilterCandidate(v === "__all__" ? "" : v)}
        >
          <SelectTrigger className="w-56" data-testid="vacancy-questions-filter-candidate">
            <SelectValue placeholder={t("vacancyQuestionsTabAllCandidates")}>
              {filterCandidate
                ? candidateLookup.get(filterCandidate) || tc("candidate")
                : t("vacancyQuestionsTabAllCandidates")}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">
              {t("vacancyQuestionsTabAllCandidates")}
            </SelectItem>
            {candidates.map((cv) => (
              <SelectItem key={cv.candidate_id} value={cv.candidate_id}>
                {cv.candidate_name || cv.candidate_id}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={filterCompetence || "__all__"}
          onValueChange={(v) => setFilterCompetence(v === "__all__" ? "" : v)}
        >
          <SelectTrigger className="w-56" data-testid="vacancy-questions-filter-competence">
            <SelectValue placeholder={t("vacancyQuestionsTabAllCompetencies")}>
              {filterCompetence === "__none__"
                ? t("vacancyQuestionsTabWithoutCompetency")
                : filterCompetence
                  ? competenceLookup.get(filterCompetence) ||
                    t("vacancyQuestionsTabCompetencyFallback")
                  : t("vacancyQuestionsTabAllCompetencies")}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">
              {t("vacancyQuestionsTabAllCompetencies")}
            </SelectItem>
            <SelectItem value="__none__">
              {t("vacancyQuestionsTabWithoutCompetency")}
            </SelectItem>
            {competences.map((c) => (
              <SelectItem key={c.id} value={c.id}>
                {c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">
          {t("vacancyQuestionsTabCount", { count: filtered.length })}
        </span>
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
          {t("vacancyQuestionsTabNoMatch")}
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((q) => (
            <div key={q.id} className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">
                  {candidateLookup.get(q.candidate_id) || tc("candidate")}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    router.push(
                      `/recruitment/candidates/${q.candidate_id}?tab=questions&vacancyId=${vacancyId}`,
                    )
                  }
                  className="h-auto px-1 text-xs"
                  data-testid={`vacancy-questions-go-${q.id}`}
                >
                  {t("vacancyQuestionsTabOpenCandidate")}
                </Button>
              </div>
              <QuestionCard
                question={q}
                competenceName={
                  q.competence_id ? competenceLookup.get(q.competence_id) : null
                }
                compact
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
