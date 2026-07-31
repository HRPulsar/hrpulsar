"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { ArrowLeft, Sparkles } from "lucide-react";
import {
  AIGenerateForm,
  clearAIGenerateDraft,
} from "@/components/specialization/ai-generate-form";
import { AIGenerateProgress } from "@/components/specialization/ai-generate-progress";
import { AIReviewModal } from "@/components/specialization/ai-review-modal";
import { AISettingsBanner } from "@/components/specialization/ai-settings-banner";
import { specializationAiApi } from "@/lib/api/specialization-ai";
import type { CompetenceGenerationSession } from "@/lib/api/competence-generation";
import { resolveApplyToast } from "@/lib/matrix-apply-toast";
import { specializationsApi, type SpecializationDetail } from "@/lib/api/specializations";
import { api } from "@/lib/api";
import type { Position } from "@/lib/types";

export default function SpecializationAIGeneratePage() {
  const t = useTranslations("company");
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const id = params?.id ?? "";
  const sessionParam = searchParams?.get("session") ?? null;
  // HRP-33 REDO: a position id arrives via `?position=<id>` when the user
  // clicked "AI Generate" on a Position page. We surface a banner naming
  // the position, force its grade into the brief, tag the session with
  // `position_id` so the global banner can route back, and bounce the user
  // home to the position after Apply.
  const positionParam = searchParams?.get("position") ?? null;

  const [spec, setSpec] = useState<SpecializationDetail | null>(null);
  const [contextPosition, setContextPosition] = useState<Position | null>(null);
  const [session, setSession] = useState<CompetenceGenerationSession | null>(null);
  const [showReview, setShowReview] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Tracks which `?session=<id>` we've already hydrated. Without this the
  // hydration effect would re-fire on every poll tick (poll mutates session
  // state every 3s) and waste a network call each time.
  const hydratedSessionRef = useRef<string | null>(null);

  // Hydrate from `?session=<id>` so the AI history «Repeat» action and the
  // global banner's "Open session" land on the live status of the running
  // session, not the empty form. Runs once per session-id; the polling
  // effect below picks up pending/running.
  useEffect(() => {
    if (!sessionParam) {
      // Clearing the ref lets a follow-up `?session=<X>` re-hydrate after
      // the user navigated away from a session and back to the same id
      // (e.g. closing the drawer, then clicking the list-row badge).
      hydratedSessionRef.current = null;
      return;
    }
    if (hydratedSessionRef.current === sessionParam) return;
    hydratedSessionRef.current = sessionParam;
    let cancelled = false;
    specializationAiApi
      .get(sessionParam)
      .then((s) => {
        if (!cancelled) setSession(s);
      })
      .catch((err) => {
        if (!cancelled) {
          hydratedSessionRef.current = null;
          toast.error(
            err instanceof Error ? err.message : t("toastSessionLoadFailed"),
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [sessionParam, t]);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    specializationsApi
      .get(id)
      .then((d) => {
        if (!cancelled) setSpec(d);
      })
      .catch((err) =>
        toast.error(
          err instanceof Error ? err.message : t("toastSpecLoadFailed"),
        ),
      );
    return () => {
      cancelled = true;
    };
  }, [id, t]);

  // HRP-33 REDO: pull the originating Position when we have `?position=<id>`
  // so the brief can pin its grade as required and the banner can name it.
  // Cleanup clears `contextPosition` so a navigate from `pos-A` to `pos-B`
  // doesn't leave Position A's grade pinned into Position B's brief while
  // the new fetch is in flight.
  useEffect(() => {
    if (!positionParam) return;
    let cancelled = false;
    api
      .get<Position>(`/positions/${positionParam}`)
      .then((p) => {
        if (!cancelled) setContextPosition(p);
      })
      .catch((err) => {
        if (!cancelled) {
          toast.error(
            err instanceof Error ? err.message : t("toastPositionLoadFailed"),
          );
        }
      });
    return () => {
      cancelled = true;
      setContextPosition(null);
    };
  }, [positionParam, t]);

  // `contextPosition` is gated on the live `positionParam` so dropping the
  // query param immediately removes the banner / grade pin without waiting
  // for the cleanup to settle.
  const effectivePosition = positionParam ? contextPosition : null;

  // Poll the active session every 3 s while pending/running. The CR11 flow
  // also pushes via WebSocket, but polling is the lowest-friction fallback
  // and matches the pattern used in `GenerationDrawer`.
  useEffect(() => {
    if (!session) return;
    if (session.status !== "pending" && session.status !== "running") return;

    let cancelled = false;
    const tick = async () => {
      try {
        const next = await specializationAiApi.get(session.id);
        if (cancelled) return;
        setSession(next);
        if (next.status === "ready") {
          setShowReview(true);
          // HRP-119 AC3: notify even when the user scrolled away from the
          // review section. Dedup'd by session id so reopening the page
          // doesn't pile up toasts.
          toast.success(t("toastMatrixReady"), {
            id: `matrix-ready-${next.id}`,
            action: {
              label: t("openReview"),
              onClick: () => setShowReview(true),
            },
          });
          return;
        }
        if (next.status === "error") {
          toast.error(next.error_message ?? t("generationFailed"));
          return;
        }
        pollRef.current = setTimeout(tick, 3000);
      } catch (err) {
        if (!cancelled) {
          toast.error(err instanceof Error ? err.message : t("pollingFailed"));
        }
      }
    };
    pollRef.current = setTimeout(tick, 3000);
    return () => {
      cancelled = true;
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [session, t]);

  const initialGradeIds = useMemo(() => {
    const base = spec ? spec.grades.map((g) => g.grade_id) : [];
    if (effectivePosition?.grade_id) {
      return Array.from(new Set([...base, effectivePosition.grade_id]));
    }
    return base;
  }, [spec, effectivePosition]);

  const requiredGradeIds = useMemo(
    () => (effectivePosition?.grade_id ? [effectivePosition.grade_id] : []),
    [effectivePosition],
  );

  const draftKey = positionParam
    ? `position-matrix:${positionParam}`
    : id
      ? `spec-matrix:${id}`
      : undefined;

  function redirectAfterApply() {
    if (positionParam) {
      router.push(`/company/positions/${positionParam}`);
    } else {
      router.push(`/company/specializations/${id}`);
    }
  }

  return (
    <div className="space-y-6" data-testid="specialization-ai-generate">
      <div>
        {positionParam ? (
          <Link
            href={`/company/positions/${positionParam}`}
            data-testid="spec-ai-generate-back-to-position"
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:underline"
          >
            <ArrowLeft className="h-3 w-3" />
            {t("backToPositionPlain")}
          </Link>
        ) : (
          <Link
            href={`/company/specializations/${id}`}
            className="text-xs text-muted-foreground hover:underline"
          >
            {t("backToSpecialization")}
          </Link>
        )}
        <h1 className="text-2xl font-semibold tracking-tight">
          {spec
            ? t("aiGenerateMatrixFor", { title: spec.title })
            : t("aiGenerateMatrix")}
        </h1>
        <p className="text-sm text-muted-foreground">
          {t("aiGenerateMatrixIntro")}
        </p>
      </div>

      {positionParam && effectivePosition ? (
        <div
          data-testid="spec-ai-generate-position-banner"
          className="flex flex-wrap items-start gap-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm"
        >
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
          <div className="min-w-0">
            <p className="font-medium">
              {t.rich("positionBannerHeadline", {
                spec: spec?.title ?? t("specializationFallback"),
                specName: (chunks) => (
                  <span className="text-primary">{chunks}</span>
                ),
              })}
            </p>
            <p className="text-xs text-muted-foreground">
              {t.rich(
                effectivePosition.grade_title
                  ? "positionBannerBodyWithGrade"
                  : "positionBannerBody",
                {
                  position: effectivePosition.title,
                  grade: effectivePosition.grade_title ?? "",
                  positionName: (chunks) => (
                    <span className="font-medium text-foreground">
                      {chunks}
                    </span>
                  ),
                },
              )}
            </p>
          </div>
        </div>
      ) : null}

      <AISettingsBanner />

      {!session && (
        <AIGenerateForm
          specId={id}
          positionId={positionParam ?? undefined}
          initialGradeIds={initialGradeIds}
          requiredGradeIds={requiredGradeIds}
          draftKey={draftKey}
          // HRP-119 AC2: surface the "extend existing" checkbox when at
          // least one grade row already has competences attached.
          hasExistingCompetences={
            spec ? spec.grades.some((g) => g.competence_count > 0) : false
          }
          onSessionCreated={setSession}
          disabled={!spec || (Boolean(positionParam) && !effectivePosition)}
        />
      )}

      {session && session.status !== "applied" && session.status !== "cancelled" && (
        <div
          data-testid="ai-generate-status"
          className="space-y-3 rounded-md border bg-background p-4 text-sm"
        >
          {(session.status === "pending" || session.status === "running") && (
            <AIGenerateProgress
              key={session.id}
              sessionId={session.id}
              scope={session.scope}
            />
          )}
          {session.status === "running" && (
            <p className="text-xs text-muted-foreground">
              {t("sessionKeepsRunning")}
            </p>
          )}
          {session.status === "error" && (
            <p className="text-destructive">
              {session.error_message ?? t("generationFailed")}
            </p>
          )}
          {session.status === "ready" && (
            <button
              type="button"
              onClick={() => setShowReview(true)}
              className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:bg-primary/90"
              data-testid="ai-generate-open-review"
            >
              {t("reviewSuggestions")}
            </button>
          )}
        </div>
      )}

      {session && showReview && session.status === "ready" && (
        <AIReviewModal
          session={session}
          onApplied={(result) => {
            setShowReview(false);
            // HRP-97 extension: wipe the brief draft after a successful
            // Apply so the next visit starts fresh, matching the Jira
            // wipe scenario ("session ends by applying to the database").
            if (draftKey) clearAIGenerateDraft(draftKey);
            const decision = resolveApplyToast(result);
            const addedComps = decision.addedCompetences;
            const addedLinks = decision.addedGradeLinks;
            // HRP-105: same empty-result message the position page uses
            // — staying silent on a 0-row Apply makes the spec page look
            // like it just lost the suggestions.
            if (decision.kind === "warning") {
              toast.warning(t("toastApplyEmpty"), {
                id: `matrix-applied-empty-${result.idempotency_key}`,
                duration: 8000,
              });
            } else {
              toast.success(
                t("toastMatrixApplied", {
                  competences: addedComps,
                  links: addedLinks,
                }),
              );
            }
            redirectAfterApply();
          }}
          onCancel={() => setShowReview(false)}
        />
      )}
    </div>
  );
}
