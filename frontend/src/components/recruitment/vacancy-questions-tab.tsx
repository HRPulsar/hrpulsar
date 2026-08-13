"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import {
  GOAL_LABEL_KEYS,
  PRIORITY_LABEL_KEYS,
  type QuestionGoal,
  type QuestionPriority,
} from "@/lib/question-enums";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MultiSelectFilter } from "@/components/multi-select-filter";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { BADGE_OUTLINE } from "@/lib/badge-tones";
import { FileQuestion } from "lucide-react";

// HRP-504: the tab used to fan out one request per candidate against the
// legacy candidate_questions table, which nothing has written since the
// candidate page moved to question sets (HRP-205) — so the list came back
// empty, the candidate filter fell back to raw UUIDs and the competence
// filter compared profile slugs against uuid5 keys and matched nothing.
// One vacancy-level endpoint now returns the latest live set per
// candidate, each question carrying its resolved competence name, plus
// the vacancy's whole competence list for the filter.
interface VacancyQuestionRow {
  id: string;
  text: string;
  goal: QuestionGoal;
  priority: QuestionPriority;
  competence_id: string | null;
  competence_name: string | null;
  rationale: string | null;
  sort_order: number;
}

interface VacancyQuestionsPayload {
  vacancy_id: string;
  competences: { id: string; name: string }[];
  candidates: {
    candidate_id: string;
    candidate_vacancy_id: string;
    candidate_name: string;
    question_set: {
      id: string;
      name: string;
      questions: VacancyQuestionRow[];
    } | null;
  }[];
}

const NO_COMPETENCE = "__none__";

interface VacancyQuestionsTabProps {
  vacancyId: string;
}

export function VacancyQuestionsTab({ vacancyId }: VacancyQuestionsTabProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const router = useRouter();
  const [data, setData] = useState<VacancyQuestionsPayload | null>(null);
  const [filterCandidate, setFilterCandidate] = useState<string>("");
  const [filterCompetences, setFilterCompetences] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(
        await api.get<VacancyQuestionsPayload>(
          `/recruitment/vacancies/${vacancyId}/question-sets`,
        ),
      );
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [vacancyId]);

  useEffect(() => {
    load();
  }, [load]);

  const candidates = useMemo(() => data?.candidates ?? [], [data]);

  const competenceOptions = useMemo(
    () => [
      ...(data?.competences ?? []).map((c) => ({
        value: c.id,
        label: c.name,
      })),
      { value: NO_COMPETENCE, label: t("vacancyQuestionsTabWithoutCompetency") },
    ],
    [data, t],
  );

  const visible = useMemo(() => {
    const selected = new Set(filterCompetences);
    return candidates
      .filter((c) => !filterCandidate || c.candidate_id === filterCandidate)
      .map((c) => {
        const questions = (c.question_set?.questions ?? []).filter((q) => {
          if (selected.size === 0) return true;
          return q.competence_id
            ? selected.has(q.competence_id)
            : selected.has(NO_COMPETENCE);
        });
        return { ...c, questions };
      });
  }, [candidates, filterCandidate, filterCompetences]);

  const total = useMemo(
    () => visible.reduce((sum, c) => sum + c.questions.length, 0),
    [visible],
  );

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

  const selectedCandidateName = candidates.find(
    (c) => c.candidate_id === filterCandidate,
  )?.candidate_name;

  return (
    <div data-testid="vacancy-questions-tab" className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Select
          value={filterCandidate || "__all__"}
          onValueChange={(v) => setFilterCandidate(v === "__all__" ? "" : v)}
        >
          <SelectTrigger
            className="w-56"
            data-testid="vacancy-questions-filter-candidate"
          >
            <SelectValue placeholder={t("vacancyQuestionsTabAllCandidates")}>
              {filterCandidate
                ? selectedCandidateName || tc("candidate")
                : t("vacancyQuestionsTabAllCandidates")}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">
              {t("vacancyQuestionsTabAllCandidates")}
            </SelectItem>
            {candidates.map((c) => (
              <SelectItem key={c.candidate_id} value={c.candidate_id}>
                {c.candidate_name || tc("candidate")}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <MultiSelectFilter
          className="w-56"
          options={competenceOptions}
          value={filterCompetences}
          onChange={setFilterCompetences}
          placeholder={t("vacancyQuestionsTabAllCompetencies")}
          data-testid="vacancy-questions-filter-competence"
        />
        <span className="text-xs text-muted-foreground">
          {t("vacancyQuestionsTabCount", { count: total })}
        </span>
      </div>

      {total === 0 ? (
        <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
          {t("vacancyQuestionsTabNoMatch")}
        </div>
      ) : (
        <div className="space-y-6">
          {visible
            .filter((c) => c.questions.length > 0)
            .map((c) => (
              <div key={c.candidate_id} className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-baseline gap-2">
                    <span className="text-sm font-medium">
                      {c.candidate_name || tc("candidate")}
                    </span>
                    {c.question_set && (
                      <span className="text-xs text-muted-foreground">
                        {c.question_set.name}
                      </span>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      router.push(
                        `/recruitment/candidates/${c.candidate_id}?tab=questions&vacancyId=${vacancyId}`,
                      )
                    }
                    className="h-auto px-1 text-xs"
                    data-testid={`vacancy-questions-go-${c.candidate_id}`}
                  >
                    {t("vacancyQuestionsTabOpenCandidate")}
                  </Button>
                </div>
                <div className="space-y-2">
                  {c.questions.map((q) => (
                    <div
                      key={q.id}
                      className="rounded-lg border p-3"
                      data-testid={`vacancy-questions-item-${q.id}`}
                    >
                      <p className="text-sm">{q.text}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        <Badge className={BADGE_OUTLINE.neutral}>
                          {PRIORITY_LABEL_KEYS[q.priority]
                            ? t(PRIORITY_LABEL_KEYS[q.priority])
                            : q.priority}
                        </Badge>
                        <Badge className={BADGE_OUTLINE.neutral}>
                          {GOAL_LABEL_KEYS[q.goal]
                            ? t(GOAL_LABEL_KEYS[q.goal])
                            : q.goal}
                        </Badge>
                        {q.competence_name && (
                          <Badge
                            className={BADGE_OUTLINE.blue}
                            data-testid={`vacancy-questions-item-${q.id}-competence`}
                          >
                            {q.competence_name}
                          </Badge>
                        )}
                      </div>
                      {q.rationale && (
                        <p className="mt-2 text-xs text-muted-foreground">
                          {q.rationale}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
