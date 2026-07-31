"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type {
  Interview,
  InterviewAnalysis,
  InterviewAnalysisCompetence,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, Lightbulb, ShieldAlert, Target, Trophy } from "lucide-react";
import { ALERT_TONE, BADGE_COLOR } from "@/lib/badge-tones";

interface CompetenceDictionary {
  [competenceId: string]: { name?: string };
}

interface InterviewAnalysisProps {
  interview: Interview;
  competences?: CompetenceDictionary;
  onSeek?: (sec: number) => void;
  // Override the upper bound used to render score bars. When omitted the
  // panel fetches the tenant's active scale and falls back to 5 if none is
  // configured (legacy behaviour).
  scaleMax?: number;
}

const FALLBACK_SCALE_MAX = 5;

const verdictTone: Record<string, string> = {
  hire: BADGE_COLOR.green,
  consider: BADGE_COLOR.amber,
  reject: BADGE_COLOR.red,
};

function CompetenceBars({
  competences,
  dictionary,
  onSeek,
  scaleMax,
}: {
  competences: InterviewAnalysisCompetence[];
  dictionary: CompetenceDictionary;
  onSeek?: (sec: number) => void;
  scaleMax: number;
}) {
  const t = useTranslations("recruitment");
  if (competences.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        {t("interviewAnalysisNoScores")}
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {competences.map((c, i) => {
        const name = dictionary[c.competence_id]?.name || c.competence_id;
        const pct =
          c.score == null
            ? 0
            : Math.max(
                0,
                Math.min(100, (Number(c.score) / scaleMax) * 100),
              );
        const greenCutoff = scaleMax * 0.8;
        const amberCutoff = scaleMax * 0.5;
        const tone =
          c.score == null
            ? "bg-muted"
            : c.score >= greenCutoff
              ? "bg-emerald-500"
              : c.score >= amberCutoff
                ? "bg-amber-500"
                : "bg-rose-500";
        return (
          <li key={`${c.competence_id}-${i}`} className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium">{name}</span>
              <span className="text-muted-foreground">
                {c.score != null ? c.score.toFixed(1) : "—"} · {c.status}
              </span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded bg-muted">
              <div
                className={`h-full ${tone}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            {c.reasoning && (
              <p className="text-[11px] text-muted-foreground">{c.reasoning}</p>
            )}
            {c.citations && c.citations.length > 0 && onSeek && (
              <div className="flex flex-wrap gap-1.5">
                {c.citations.slice(0, 3).map((cit, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => {
                      if (typeof cit.start_sec === "number")
                        onSeek(cit.start_sec);
                    }}
                    className="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-muted"
                    title={cit.quote}
                  >
                    {typeof cit.start_sec === "number"
                      ? `@ ${Math.floor(cit.start_sec / 60)}:${(
                          Math.floor(cit.start_sec) % 60
                        )
                          .toString()
                          .padStart(2, "0")}`
                      : t("interviewAnalysisQuote")}
                  </button>
                ))}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function InterviewAnalysisPanel({
  interview,
  competences = {},
  onSeek,
  scaleMax,
}: InterviewAnalysisProps) {
  const t = useTranslations("recruitment");
  const analysis: InterviewAnalysis | null = interview.analysis ?? null;

  const verdictClass = useMemo(() => {
    const r = (analysis?.verdict?.recommendation || "").toLowerCase();
    return verdictTone[r] || "bg-muted text-muted-foreground border-border";
  }, [analysis]);

  // When the parent supplies scaleMax we use it directly; otherwise we fetch
  // the tenant's active scale once and derive resolvedScaleMax from props +
  // fetched state, keeping the effect free of synchronous setState calls
  // (forbidden by React 19's `react-hooks/set-state-in-effect` rule).
  const [fetchedMax, setFetchedMax] = useState<number | null>(null);

  useEffect(() => {
    if (typeof scaleMax === "number" && scaleMax > 0) return;
    // `api.get` does not currently accept an AbortSignal, so we fall back
    // to a captured-flag guard. The fetch still completes in the
    // background after unmount, but the setState is suppressed — which is
    // all React 19 needs to avoid the warning.
    let cancelled = false;
    api
      .get<{ max_value?: number } | null>(
        "/recruitment/settings/scales/active",
      )
      .then((res) => {
        if (cancelled) return;
        if (res && typeof res.max_value === "number" && res.max_value > 0) {
          setFetchedMax(res.max_value);
        }
      })
      .catch(() => {
        if (!cancelled) setFetchedMax(null);
      });
    return () => {
      cancelled = true;
    };
  }, [scaleMax]);

  const resolvedScaleMax =
    typeof scaleMax === "number" && scaleMax > 0
      ? scaleMax
      : fetchedMax ?? FALLBACK_SCALE_MAX;

  if (interview.analysis_status === "pending") {
    return (
      <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
        {t("interviewAnalysisPending")}
      </div>
    );
  }
  if (interview.analysis_status === "processing") {
    return (
      <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
        {t("interviewAnalysisProcessing")}
      </div>
    );
  }
  if (interview.analysis_status === "failed") {
    return (
      <div className={`rounded-md border p-4 text-sm ${ALERT_TONE.rose}`}>
        {t("interviewAnalysisFailed")} {interview.analysis_error}
      </div>
    );
  }
  if (!analysis) {
    return (
      <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
        {t("interviewAnalysisUnavailable")}
      </div>
    );
  }

  return (
    <div data-testid="recruitment-interview-analysis" className="space-y-5">
      {analysis.verdict && (
        <section className="space-y-1">
          <h3 className="flex items-center gap-1.5 text-sm font-medium">
            <Trophy className="size-4 text-amber-500" />
            {t("interviewAnalysisVerdictHeading")}
          </h3>
          <div className={`rounded-md border p-3 text-sm ${verdictClass}`}>
            <p className="font-semibold capitalize">
              {analysis.verdict.recommendation}
            </p>
            {analysis.verdict.key_strength && (
              <p className="mt-1 text-xs">
                <strong>{t("interviewAnalysisKeyStrength")}</strong>{" "}
                {analysis.verdict.key_strength}
              </p>
            )}
            {analysis.verdict.key_risk && (
              <p className="mt-1 text-xs">
                <strong>{t("interviewAnalysisRisk")}</strong>{" "}
                {analysis.verdict.key_risk}
              </p>
            )}
            {analysis.verdict.risk_mitigation && (
              <p className="mt-1 text-xs">
                <strong>{t("interviewAnalysisMitigation")}</strong>{" "}
                {analysis.verdict.risk_mitigation}
              </p>
            )}
          </div>
        </section>
      )}

      <section className="space-y-1.5">
        <h3 className="flex items-center gap-1.5 text-sm font-medium">
          <Target className="size-4 text-accent" />
          {t("interviewAnalysisCompetencesHeading")}
        </h3>
        <CompetenceBars
          competences={analysis.competence_assessments ?? []}
          dictionary={competences}
          onSeek={onSeek}
          scaleMax={resolvedScaleMax}
        />
      </section>

      {analysis.blind_spots && analysis.blind_spots.length > 0 && (
        <section className="space-y-1.5">
          <h3 className="flex items-center gap-1.5 text-sm font-medium">
            <Lightbulb className="size-4 text-amber-500" />
            {t("interviewAnalysisBlindSpots")}
          </h3>
          <ul className="space-y-1.5">
            {analysis.blind_spots.map((b, i) => (
              <li key={i} className="rounded-md border bg-muted/30 p-2 text-xs">
                {b.topic && <p className="font-medium">{b.topic}</p>}
                {b.reason && (
                  <p className="text-muted-foreground">{b.reason}</p>
                )}
                {b.suggested_question && (
                  <p className="mt-1">
                    <Badge variant="outline" className="mr-1 text-[10px]">
                      {t("interviewAnalysisQuestionBadge")}
                    </Badge>
                    {b.suggested_question}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {analysis.process_findings && analysis.process_findings.length > 0 && (
        <section className="space-y-1.5">
          <h3 className="flex items-center gap-1.5 text-sm font-medium">
            <AlertTriangle className="size-4 text-blue-600" />
            {t("interviewAnalysisProcessFindings")}
          </h3>
          <ul className="space-y-1.5">
            {analysis.process_findings.map((f, i) => (
              <li key={i} className="rounded-md border bg-muted/30 p-2 text-xs">
                <p className="font-medium capitalize">{f.finding_type}</p>
                {f.detail && (
                  <p className="text-muted-foreground">{f.detail}</p>
                )}
                {f.positive_reframe && (
                  <p className="mt-1 text-emerald-700">
                    💡 {f.positive_reframe}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {analysis.red_flags && analysis.red_flags.length > 0 && (
        <section className="space-y-1.5">
          <h3 className="flex items-center gap-1.5 text-sm font-medium">
            <ShieldAlert className="size-4 text-rose-600" />
            {t("interviewAnalysisRedFlags")}
          </h3>
          <ul className="space-y-1.5">
            {analysis.red_flags.map((f, i) => (
              <li
                key={i}
                className={`rounded-md border p-2 text-xs ${ALERT_TONE.rose}`}
              >
                <p className="font-medium capitalize">{f.finding_type}</p>
                {f.detail && <p>{f.detail}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
