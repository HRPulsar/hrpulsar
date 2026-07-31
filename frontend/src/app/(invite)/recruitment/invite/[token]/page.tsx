"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { AssessmentInvite, CandidateQuestion } from "@/lib/types";
import { CanvasGrid } from "@/components/recruitment/canvas";
import { QuestionCard } from "@/components/recruitment/question-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2 } from "lucide-react";

interface InviteResponse extends AssessmentInvite {
  vacancy_title?: string | null;
  candidate_name?: string | null;
}

interface InviteContextResponse {
  invite: InviteResponse;
  vacancy_id: string;
  vacancy_title: string | null;
  candidate_id: string;
  candidate_name: string;
  resume_url: string | null;
  resume_filename: string | null;
  resume_mime_type: string | null;
  questions: CandidateQuestion[];
}

export default function InvitedEvaluatorPage() {
  const t = useTranslations("auth");
  const { token } = useParams<{ token: string }>();
  const [context, setContext] = useState<InviteContextResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<InviteContextResponse>(
        `/recruitment/invite/${token}/context`,
      );
      setContext(data);
    } catch {
      setError(t("linkExpiredOrInvalid"));
    } finally {
      setLoading(false);
    }
  }, [token, t]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" />
        {t("loadingEllipsis")}
      </div>
    );
  }

  if (error || !context) {
    return (
      <div className="rounded-lg border border-dashed p-12 text-center text-sm text-muted-foreground">
        <p className="text-base font-medium">{t("linkUnavailable")}</p>
        <p className="mt-2">{error ?? t("linkExpiredOrInvalid")}</p>
      </div>
    );
  }

  return (
    <div data-testid="invited-evaluator-page" className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          {t("candidateEvaluation", {
            name: context.candidate_name || t("unnamedCandidate"),
          })}
        </h1>
        {context.vacancy_title && (
          <p className="text-sm text-muted-foreground">
            {t("vacancyLabel", { title: context.vacancy_title })}
          </p>
        )}
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("resume")}</CardTitle>
        </CardHeader>
        <CardContent>
          {context.resume_url ? (
            context.resume_mime_type === "application/pdf" ? (
              <iframe
                src={context.resume_url}
                title={context.resume_filename || t("resumeFallbackTitle")}
                className="h-[600px] w-full rounded-md border"
              />
            ) : (
              <a
                href={context.resume_url}
                target="_blank"
                rel="noreferrer"
                className="text-sm text-accent underline"
              >
                {t("openFile", { filename: context.resume_filename ?? "" })}
              </a>
            )
          ) : (
            <p className="text-sm text-muted-foreground">
              {t("resumeNotAttached")}
            </p>
          )}
        </CardContent>
      </Card>

      <section className="space-y-3">
        <h2 className="text-base font-semibold">{t("interviewQuestions")}</h2>
        {context.questions.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t("noQuestionsPrepared")}
          </p>
        ) : (
          <div className="space-y-2">
            {context.questions.map((q) => (
              <QuestionCard key={q.id} question={q} compact />
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-base font-semibold">{t("evaluationForm")}</h2>
        <CanvasGrid
          vacancyId={context.vacancy_id}
          candidateVacancyId={context.invite.candidate_vacancy_id}
          inviteToken={token}
          mode="compact"
        />
      </section>
    </div>
  );
}

