"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  Briefcase,
  Download,
  FileText,
  Link2,
  Mail,
  MapPin,
  Phone,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { ApiError, api } from "@/lib/api";
import { formatDate } from "@/lib/date-format";
import { cn } from "@/lib/utils";
import { AiInsightsSection } from "@/components/recruitment/ai-insights-section";
import { AiVerdictBadge } from "@/components/recruitment/ai-verdict-badge";
import { CandidateInterviewsSection } from "@/components/recruitment/candidate-interviews-section";
import { InterviewQuestionSets } from "@/components/recruitment/interview-question-sets";
import { ManagerAssessmentSection } from "@/components/recruitment/manager-assessment-section";
import { ParsedResumeEditor } from "@/components/recruitment/parsed-resume-editor";
import { useAuth } from "@/context/auth-context";
import type {
  CandidateCanonical,
  CandidateCanonicalCard,
} from "@/lib/recruitment-types";

// HRP-476: labels live in the `recruitment` i18n namespace; this list only
// owns the payload key → input type → key relation.
const PERSONAL_FIELDS: Array<{
  key: keyof PersonalEditState;
  labelKey: string;
  type?: "email" | "url" | "text" | "number" | "textarea";
}> = [
  { key: "full_name", labelKey: "candidateFieldFullName" },
  { key: "email", labelKey: "columnEmail", type: "email" },
  { key: "phone", labelKey: "candidateFieldPhone" },
  { key: "linkedin_url", labelKey: "candidateFieldLinkedinUrl", type: "url" },
  { key: "location", labelKey: "candidateFieldLocation" },
  { key: "current_position", labelKey: "candidateFieldCurrentPosition" },
  {
    key: "years_of_experience",
    labelKey: "candidateFieldYearsExperience",
    type: "number",
  },
  { key: "source", labelKey: "columnSource" },
  { key: "notes", labelKey: "candidateFieldNotes", type: "textarea" },
];

interface PersonalEditState {
  full_name: string;
  email: string;
  phone: string;
  linkedin_url: string;
  location: string;
  current_position: string;
  years_of_experience: string;
  source: string;
  notes: string;
}

function toEditState(c: CandidateCanonical): PersonalEditState {
  return {
    full_name: c.full_name ?? "",
    email: c.email ?? "",
    phone: c.phone ?? "",
    linkedin_url: c.linkedin_url ?? "",
    location: c.location ?? "",
    current_position: c.current_position ?? "",
    years_of_experience:
      c.years_of_experience !== null && c.years_of_experience !== undefined
        ? String(c.years_of_experience)
        : "",
    source: c.source ?? "",
    notes: c.notes ?? "",
  };
}

export default function CandidateDetailPage() {
  const { id } = useParams<{ id: string }>();
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const searchParams = useSearchParams();
  const router = useRouter();
  // HRP-181 REDO: candidate cards are reached from a vacancy funnel.
  // ``vacancyId`` query param keeps the breadcrumb anchored to that
  // vacancy so Back lands on the vacancy detail, not the legacy
  // standalone candidates list.
  const vacancyContextId = searchParams.get("vacancyId");
  // HRP-460: the "Interview questions ready" email links straight to
  // the generated set.
  const questionSetContextId = searchParams.get("questionSet");
  const backHref = vacancyContextId
    ? `/recruitment/requisitions/${vacancyContextId}`
    : "/recruitment/requisitions";
  const [card, setCard] = useState<CandidateCanonicalCard | null>(null);
  const [etag, setEtag] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { user } = useAuth();
  // HRP-205: tenant flag that lets hiring managers see Interview questions
  // above the parsed resume — they open the card minutes before the call
  // and the questions are what they came for.
  const [questionsAboveResume, setQuestionsAboveResume] = useState(false);

  const assessmentVacancies = useMemo(
    () =>
      (card?.vacancy_applications ?? []).map((a) => ({
        id: a.cv_id,
        vacancy_id: a.vacancy_id,
        vacancy_title: a.vacancy_title,
      })),
    [card?.vacancy_applications],
  );

  // HRP-205 / HRP-202: per-vacancy options shared by the Interview
  // questions and Interviews sections. `has_parsed_resume` gates the
  // Generate button — question generation requires a parsed resume.
  const interviewVacancyOptions = useMemo(
    () =>
      (card?.vacancy_applications ?? []).map((a) => ({
        id: a.vacancy_id,
        title:
          a.vacancy_title ??
          t("candidateVacancyFallback", { id: a.vacancy_id.slice(0, 8) }),
        candidate_vacancy_id: a.cv_id,
        has_parsed_resume: Boolean(card?.parsed_resume_jsonb),
      })),
    [card?.vacancy_applications, card?.parsed_resume_jsonb, t],
  );

  // Mirrors backend resolve_user_role: full-payload roles win before the
  // hiring_manager slice (see recruitment/common.py).
  const isHiringManager =
    (user?.roles ?? []).includes("hiring_manager") &&
    !(user?.roles ?? []).some((r) =>
      ["admin", "recruiter", "hr", "hrd"].includes(r),
    );

  useEffect(() => {
    // Only hiring managers can be affected by the flag — skip the round
    // trip for everyone else.
    if (!isHiringManager) return;
    let cancelled = false;
    api
      .get<{ hm_questions_above_resume: boolean }>("/recruitment/settings/ui")
      .then((s) => {
        if (!cancelled) setQuestionsAboveResume(s.hm_questions_above_resume);
      })
      .catch(() => {
        /* default order when the flag is unreadable */
      });
    return () => {
      cancelled = true;
    };
  }, [isHiringManager]);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const { data, headers } = await api.getWithMeta<CandidateCanonicalCard>(
        `/recruitment/candidates/${id}/card`,
      );
      setCard(data);
      setEtag(headers.get("ETag"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("candidateLoadFailed"));
    } finally {
      setLoading(false);
    }
  }, [id, t]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !card) {
    return (
      <div className="py-12 text-center text-muted-foreground">
        {tc("loading")}
      </div>
    );
  }

  if (!card) {
    return (
      <div className="space-y-3 py-12 text-center text-muted-foreground">
        <p>{error || t("candidateNotFound")}</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => router.push(backHref)}
        >
          {t("actionBack")}
        </Button>
      </div>
    );
  }

  return (
    <div
      data-testid="recruitment-candidate-detail"
      className="space-y-6"
    >
      <Header card={card} backHref={backHref} />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-1">
          <PersonalCard
            card={card}
            etag={etag}
            onSaved={(c, newEtag) => {
              setCard((prev) =>
                prev
                  ? {
                      ...prev,
                      ...c,
                    }
                  : prev,
              );
              setEtag(newEtag);
            }}
          />
          <FilesCard files={card.candidate_files} />
        </div>
        <div className="space-y-4 lg:col-span-2">
          {(() => {
            const questionsSection = (
              <InterviewQuestionSets
                key="question-sets"
                candidateId={card.id}
                vacancyOptions={interviewVacancyOptions}
                initialVacancyId={vacancyContextId ?? undefined}
                initialQuestionSetId={questionSetContextId ?? undefined}
              />
            );
            const resumeSection = (
              <ParsedResumeEditor
                key="resume"
                card={card}
                etag={etag}
                onSaved={(c, newEtag) => {
                  setCard((prev) =>
                    prev
                      ? {
                          ...prev,
                          ...c,
                        }
                      : prev,
                  );
                  setEtag(newEtag);
                }}
              />
            );
            const insightsSection = (
              <AiInsightsSection
                key="ai-insights"
                candidateId={card.id}
                vacancyApplications={card.vacancy_applications}
                initialVacancyId={vacancyContextId ?? undefined}
                // HRP-488: a manually added candidate has nothing to
                // analyse. Either a parsed resume file or the canonical
                // parsed-resume mirror (manual entry, bulk import) is
                // enough to unblock Analyze.
                hasParsedResume={
                  card.parsed_resume_jsonb !== null ||
                  card.candidate_files.some(
                    (f) =>
                      f.file_type === "resume" &&
                      f.parse_status === "completed",
                  )
                }
              />
            );
            const applicationsSection = (
              <VacancyApplicationsCard
                key="vacancy-applications"
                card={card}
              />
            );
            // HRP-424: the blocks follow the sourcing timeline — resume in,
            // application created, AI verdict, interview questions.
            // HRP-205: when the tenant flag is on, hiring managers get the
            // questions first — the "20 minutes before the interview" path.
            return questionsAboveResume && isHiringManager
              ? [
                  questionsSection,
                  resumeSection,
                  applicationsSection,
                  insightsSection,
                ]
              : [
                  resumeSection,
                  applicationsSection,
                  insightsSection,
                  questionsSection,
                ];
          })()}
          <CandidateInterviewsSection
            candidateId={card.id}
            vacancyOptions={interviewVacancyOptions}
            initialVacancyId={vacancyContextId ?? undefined}
            candidateEmail={card.email}
          />
          <ManagerAssessmentSection
            vacancies={assessmentVacancies}
            initialVacancyId={vacancyContextId ?? undefined}
          />
        </div>
      </div>
    </div>
  );
}

function Header({
  card,
  backHref,
}: {
  card: CandidateCanonicalCard;
  backHref: string;
}) {
  const t = useTranslations("recruitment");
  const isArchived = !!card.archived_at;
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1
          className="text-2xl font-semibold tracking-tight"
          data-testid="candidate-card-full-name"
        >
          {card.full_name}
        </h1>
        <p className="mt-1 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
          {card.email && (
            <span className="inline-flex items-center gap-1">
              <Mail className="size-3.5" /> {card.email}
            </span>
          )}
          {card.phone && (
            <span className="inline-flex items-center gap-1">
              <Phone className="size-3.5" /> {card.phone}
            </span>
          )}
          {card.linkedin_url && (
            <a
              href={card.linkedin_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 hover:underline"
            >
              <Link2 className="size-3.5" /> LinkedIn
            </a>
          )}
          {card.location && (
            <span className="inline-flex items-center gap-1">
              <MapPin className="size-3.5" /> {card.location}
            </span>
          )}
          {isArchived && (
            <Badge variant="outline" className="border-rose-200 text-rose-700">
              {t("statusArchived")}
            </Badge>
          )}
        </p>
      </div>
      <Button variant="outline" render={<Link href={backHref} />}>
        {t("actionBack")}
      </Button>
    </div>
  );
}

interface PersonalCardProps {
  card: CandidateCanonicalCard;
  etag: string | null;
  onSaved: (updated: CandidateCanonical, etag: string | null) => void;
}

function PersonalCard({ card, etag, onSaved }: PersonalCardProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<PersonalEditState>(() => toEditState(card));
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!editing) setForm(toEditState(card));
  }, [card, editing]);

  const save = useCallback(async () => {
    const trimmedFullName = form.full_name.trim();
    if (!trimmedFullName) {
      // Backend Candidate.full_name is NOT NULL — block here so the user
      // gets a clear inline error instead of a 500 IntegrityError.
      toast.error(t("candidateFullNameRequired"));
      return;
    }
    setBusy(true);
    try {
      const yoeNum = form.years_of_experience.trim()
        ? Number.parseInt(form.years_of_experience, 10)
        : null;
      const payload = {
        full_name: trimmedFullName,
        email: form.email.trim() || null,
        phone: form.phone.trim() || null,
        linkedin_url: form.linkedin_url.trim() || null,
        location: form.location.trim() || null,
        current_position: form.current_position.trim() || null,
        years_of_experience:
          yoeNum !== null && Number.isFinite(yoeNum) ? yoeNum : null,
        source: form.source.trim() || null,
        notes: form.notes.trim() || null,
      };
      const { data, headers } = await api.sendWithMeta<CandidateCanonical>(
        `/recruitment/candidates/${card.id}`,
        "PATCH",
        payload,
        etag ? { headers: { "If-Match": etag } } : undefined,
      );
      onSaved(data, headers.get("ETag"));
      setEditing(false);
      toast.success(t("candidateToastUpdated"));
    } catch (err) {
      if (err instanceof ApiError && err.status === 412) {
        toast.error(t("candidateConflictReload"));
      } else {
        toast.error(
          err instanceof Error ? err.message : t("candidateSaveFailed"),
        );
      }
    } finally {
      setBusy(false);
    }
  }, [card.id, etag, form, onSaved, t]);

  return (
    <Card data-testid="candidate-card-section-personal">
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="text-sm">{t("candidatePersonalInfo")}</CardTitle>
        {!editing ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setEditing(true)}
            data-testid="candidate-card-edit-personal-btn"
          >
            {t("actionEdit")}
          </Button>
        ) : (
          <div className="flex gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setEditing(false)}
              disabled={busy}
            >
              {tc("cancel")}
            </Button>
            <Button
              size="sm"
              onClick={save}
              disabled={busy}
              data-testid="candidate-card-save-personal-btn"
            >
              {busy ? t("actionSaving") : t("save")}
            </Button>
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {editing ? (
          PERSONAL_FIELDS.map(({ key, labelKey, type }) => (
            <div key={key} className="space-y-1">
              <Label className="text-xs" htmlFor={`personal-${key}`}>
                {t(labelKey)}
              </Label>
              {type === "textarea" ? (
                <Textarea
                  id={`personal-${key}`}
                  rows={3}
                  value={form[key]}
                  onChange={(e) =>
                    setForm((p) => ({ ...p, [key]: e.target.value }))
                  }
                />
              ) : (
                <Input
                  id={`personal-${key}`}
                  type={type ?? "text"}
                  value={form[key]}
                  onChange={(e) =>
                    setForm((p) => ({ ...p, [key]: e.target.value }))
                  }
                />
              )}
            </div>
          ))
        ) : (
          <dl className="grid grid-cols-1 gap-2">
            <ReadField label={t("columnEmail")} value={card.email} />
            <ReadField label={t("candidateFieldPhone")} value={card.phone} />
            <ReadField
              label={t("candidateFieldLinkedin")}
              value={card.linkedin_url}
            />
            <ReadField
              label={t("candidateFieldLocation")}
              value={card.location}
            />
            <ReadField
              label={t("candidateFieldCurrentPosition")}
              value={card.current_position}
            />
            <ReadField
              label={t("candidateFieldYearsExperience")}
              value={
                card.years_of_experience !== null
                  ? `${card.years_of_experience}`
                  : null
              }
            />
            <ReadField label={t("columnSource")} value={card.source} />
            <ReadField label={t("candidateFieldNotes")} value={card.notes} />
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

function ReadField({
  label,
  value,
}: {
  label: string;
  value: string | null | undefined;
}) {
  return (
    <div className="flex flex-col">
      <dt className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="text-sm text-foreground">
        {value && value.trim() ? value : "—"}
      </dd>
    </div>
  );
}

function FilesCard({
  files,
}: {
  files: CandidateCanonicalCard["candidate_files"];
}) {
  const t = useTranslations("recruitment");
  if (files.length === 0) {
    return (
      <Card data-testid="candidate-card-section-files">
        <CardHeader>
          <CardTitle className="text-sm">{t("candidateFilesTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">
            {t("candidateNoFiles")}
          </p>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card data-testid="candidate-card-section-files">
      <CardHeader>
        <CardTitle className="text-sm">{t("candidateFilesTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {files.map((f) => (
          <div
            key={f.id}
            className="flex items-center justify-between rounded-md border px-3 py-2"
            data-testid={`candidate-card-file-${f.id}`}
          >
            <div className="flex min-w-0 items-center gap-2">
              <FileText className="size-4 text-muted-foreground" />
              <div className="min-w-0">
                <p className="truncate text-sm">{f.original_filename}</p>
                <p className="text-xs text-muted-foreground">
                  {f.file_type} · {f.parse_status}
                </p>
              </div>
            </div>
            {f.file_type === "resume" && (
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => downloadResume(f.id, t("candidateDownloadFailed"))}
                aria-label={t("candidateDownloadResume")}
                data-testid={`candidate-card-file-${f.id}-download`}
              >
                <Download className="size-4" />
              </Button>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

// HRP-476: the fallback message is passed in — the helper sits outside the
// component tree and cannot call `useTranslations` itself.
async function downloadResume(fileId: string, failedMessage: string) {
  try {
    // HRP-347: the endpoint returns a presigned URL envelope, not the file
    // bytes; ``disposition=attachment`` makes the URL force a download with
    // the original filename.
    const res = await api.get<{ url: string }>(
      `/recruitment/resumes/${fileId}/download?disposition=attachment`,
    );
    const a = document.createElement("a");
    a.href = res.url;
    a.rel = "noopener";
    a.click();
  } catch (err) {
    toast.error(err instanceof Error ? err.message : failedMessage);
  }
}

function VacancyApplicationsCard({
  card,
}: {
  card: CandidateCanonicalCard;
}) {
  const t = useTranslations("recruitment");
  const apps = card.vacancy_applications;
  return (
    <Card data-testid="candidate-card-section-applications">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <Briefcase className="size-4 text-muted-foreground" />{" "}
          {t("candidateApplicationsTitle")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {apps.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            {t("candidateNoApplications")}
          </p>
        ) : (
          <ul className="space-y-2">
            {apps.map((a) => (
              <li
                key={a.cv_id}
                className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm"
                data-testid={`candidate-card-application-${a.cv_id}`}
              >
                <div className="min-w-0">
                  {a.vacancy_title ? (
                    <Link
                      href={`/recruitment/requisitions/${a.vacancy_id}`}
                      className="block truncate font-medium hover:underline"
                    >
                      {a.vacancy_title}
                    </Link>
                  ) : (
                    <span className="block truncate font-medium">
                      {t("candidateVacancyFallback", {
                        id: a.vacancy_id.slice(0, 8),
                      })}
                    </span>
                  )}
                  <p className="text-xs text-muted-foreground">
                    {t("candidateApplicationMeta", {
                      stage: a.stage_name || "—",
                      status: a.status,
                      date: formatDate(a.added_at),
                    })}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {a.manager_score !== null && (
                    <span
                      className={cn(
                        "rounded-full bg-muted px-2 py-0.5 text-xs tabular-nums",
                      )}
                    >
                      {t("candidateManagerScore", {
                        score: a.manager_score.toFixed(1),
                      })}
                    </span>
                  )}
                  <AiVerdictBadge
                    verdict={a.ai_verdict}
                    aiScore={a.ai_score}
                    summary={a.ai_verdict_summary}
                    testIdPrefix={`candidate-card-application-${a.cv_id}`}
                  />
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

