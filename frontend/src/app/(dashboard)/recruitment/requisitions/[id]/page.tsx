"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import type { CandidateVacancy, Vacancy, VacancyProfile } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatDate } from "@/lib/date-format";
import {
  AssessmentsTab,
  RecruitmentBreadcrumbs,
  ReportsTab,
  VacancyQuestionsTab,
} from "@/components/recruitment";
import { VacancyAnalyticsTab } from "@/components/recruitment/vacancy-analytics-tab";
import { VacancyAssessmentScaleBlock } from "@/components/recruitment/vacancy-assessment-scale";
import { VacancyActionsMenu } from "../_components/VacancyActionsMenu";
import { VacancyOverviewSection } from "../_components/VacancyOverviewSection";
import { VacancyCompetencesSection } from "../_components/VacancyCompetencesSection";
import { VacancyCandidatesSection } from "../_components/VacancyCandidatesSection";
import { ALERT_TONE, BADGE_COLOR } from "@/lib/badge-tones";

const statusColors: Record<string, string> = {
  draft: BADGE_COLOR.neutral,
  open: BADGE_COLOR.green,
  paused: BADGE_COLOR.yellow,
  closed: BADGE_COLOR.red,
  cancelled: BADGE_COLOR.neutral,
};

// Legacy ?tab=profile / ?tab=candidates → single-page anchors.
const LEGACY_TAB_ANCHORS: Record<string, string> = {
  profile: "competences",
  candidates: "candidates",
};

export default function VacancyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [vacancy, setVacancy] = useState<Vacancy | null>(null);
  const [etag, setEtag] = useState<string | null>(null);
  const [profile, setProfile] = useState<VacancyProfile | null>(null);
  const [candidateVacancies, setCandidateVacancies] = useState<CandidateVacancy[]>(
    [],
  );
  const [loading, setLoading] = useState(true);

  const loadVacancy = useCallback(async () => {
    try {
      const { data, headers } = await api.getWithMeta<Vacancy>(
        `/recruitment/vacancies/${id}`,
      );
      setVacancy(data);
      setEtag(headers.get("ETag"));
    } catch {
      // ignore
    }
  }, [id]);

  const loadProfile = useCallback(async () => {
    try {
      const data = await api.get<VacancyProfile>(
        `/recruitment/vacancies/${id}/profile`,
      );
      setProfile(data);
    } catch {
      // 404 means no profile yet
    }
  }, [id]);

  const loadCandidateVacancies = useCallback(async () => {
    try {
      const data = await api.get<
        { items: CandidateVacancy[] } | CandidateVacancy[]
      >(`/recruitment/vacancies/${id}/candidates`);
      const items = Array.isArray(data) ? data : (data.items ?? []);
      setCandidateVacancies(items);
    } catch {
      // ignore — questions tab can still render without the lookup
    }
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await Promise.all([
        loadVacancy(),
        loadProfile(),
        loadCandidateVacancies(),
      ]);
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [loadVacancy, loadProfile, loadCandidateVacancies]);

  // HRP-180: rewrite legacy ?tab=profile / ?tab=candidates to the main
  // page with an anchor — the standalone tabs are gone.
  useEffect(() => {
    const tab = searchParams.get("tab");
    if (tab && LEGACY_TAB_ANCHORS[tab]) {
      router.replace(
        `/recruitment/requisitions/${id}#${LEGACY_TAB_ANCHORS[tab]}`,
      );
    }
  }, [searchParams, id, router]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        Loading...
      </div>
    );
  }

  if (!vacancy) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <p>Vacancy not found</p>
        <Button
          variant="outline"
          size="sm"
          className="mt-4"
          render={<Link href="/recruitment/requisitions" />}
        >
          Back to vacancies
        </Button>
      </div>
    );
  }

  const canEdit = !vacancy.archived_at && vacancy.status !== "closed";

  function handleSaved(next: Vacancy, nextEtag: string | null) {
    setVacancy(next);
    setEtag(nextEtag ?? etag);
  }

  return (
    <div data-testid="recruitment-vacancy-detail" className="space-y-6">
      <RecruitmentBreadcrumbs
        segments={[
          { label: "Vacancies", href: "/recruitment/requisitions" },
          { label: vacancy.title },
        ]}
      />
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">
              {vacancy.title}
            </h1>
            <Badge
              variant="secondary"
              className={
                vacancy.archived_at
                  ? "bg-muted text-muted-foreground"
                  : statusColors[vacancy.status] || ""
              }
            >
              {vacancy.archived_at ? "archived" : vacancy.status}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            {[
              vacancy.position_title,
              ...(vacancy.specializations ?? []).map((s) => s.title || s.id),
              ...(vacancy.grades ?? []).map((g) => g.title || g.id),
              vacancy.division_name,
              vacancy.location,
            ]
              .filter(Boolean)
              .join(" / ") || "No additional details"}
            {" --- "}
            Created {formatDate(vacancy.created_at)}
            {vacancy.owner_name && ` by ${vacancy.owner_name}`}
          </p>
        </div>
        <VacancyActionsMenu
          vacancy={vacancy}
          onChanged={() => {
            void loadVacancy();
          }}
        />
      </div>

      {vacancy.archived_at && (
        <div
          className={`rounded-md border p-3 text-sm ${ALERT_TONE.yellow}`}
          data-testid="vacancy-archived-banner"
        >
          This vacancy is archived. Restore to edit.
        </div>
      )}

      <Tabs defaultValue="overview">
        <TabsList data-testid="vacancy-tabs">
          <TabsTrigger
            value="overview"
            data-testid="recruitment-vacancy-tab-overview"
          >
            Overview
          </TabsTrigger>
          <TabsTrigger
            value="questions"
            data-testid="recruitment-vacancy-tab-questions"
          >
            Questions
          </TabsTrigger>
          <TabsTrigger
            value="assessments"
            data-testid="recruitment-vacancy-tab-assessments"
          >
            Assessments
          </TabsTrigger>
          <TabsTrigger
            value="reports"
            data-testid="recruitment-vacancy-tab-reports"
          >
            Reports
          </TabsTrigger>
          <TabsTrigger
            value="analytics"
            data-testid="recruitment-vacancy-tab-analytics"
          >
            Analytics
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          <VacancyOverviewSection
            vacancy={vacancy}
            etag={etag}
            canEdit={canEdit}
            onSaved={handleSaved}
          />

          {/* HRP-186: Assessment scale picker (kept as standalone block until folded into Overview). */}
          <VacancyAssessmentScaleBlock
            vacancyId={id}
            initial={{
              id: vacancy.id,
              assessment_scale_id:
                (vacancy as { assessment_scale_id?: string | null })
                  .assessment_scale_id ?? null,
              assessment_scale_snapshot:
                (
                  vacancy as {
                    assessment_scale_snapshot?:
                      | { name?: string; levels?: { value: number; label: string; weight: number }[] }
                      | null;
                  }
                ).assessment_scale_snapshot ?? null,
            }}
          />

          <VacancyCompetencesSection
            vacancy={vacancy}
            profile={profile}
            canEdit={canEdit}
            onProfileChange={loadProfile}
          />
          <VacancyCandidatesSection
            vacancyId={vacancy.id}
            count={vacancy.candidates_count ?? 0}
          />
        </TabsContent>

        <TabsContent value="questions" className="space-y-4">
          <VacancyQuestionsTab
            vacancyId={vacancy.id}
            candidates={candidateVacancies}
          />
        </TabsContent>

        <TabsContent value="assessments" className="space-y-4">
          <AssessmentsTab vacancyId={vacancy.id} />
        </TabsContent>

        <TabsContent value="reports" className="space-y-4">
          <ReportsTab vacancyId={vacancy.id} />
        </TabsContent>
        <TabsContent value="analytics" className="space-y-4">
          <VacancyAnalyticsTab vacancyId={vacancy.id} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
