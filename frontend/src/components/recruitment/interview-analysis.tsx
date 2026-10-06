"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type {
  Interview,
  InterviewAnalysis,
  InterviewAnalysisCitation,
  InterviewAnalysisCompetence,
  InterviewSegment,
} from "@/lib/types";
import {
  aiVerdictLabel,
  competenceAssessmentStatusLabel,
  processFindingLabel,
  redFlagLabel,
} from "@/lib/recruitment-types";
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
  // panel fetches the tenant's active scale; until it answers the bars stay
  // empty (see `scoreBar`).
  scaleMax?: number;
}

// HRP-673: when the tenant has no active ScaleConfig the backend keeps the
// score on the raw 0..1 scale (identity fallback in
// compute_normalized_ai_score) — the bar bound must mirror that, not
// pretend a 5-point scale exists.
const NO_SCALE_MAX = 1;
// Only when the scale request itself fails — the one case where nothing
// says which scale the scores are on — the pre-HRP-673 5-point default.
export const FALLBACK_SCALE_MAX = 5;

/** Fill and tone of one score bar. `scaleMax` is null while the tenant's
 *  scale is still being fetched: the bar stays empty and neutral rather
 *  than being drawn against a bound we do not have yet — dividing by a
 *  placeholder painted every bar full green on the first paint. */
export function scoreBar(
  score: number | null | undefined,
  scaleMax: number | null,
): { pct: number; tone: string } {
  if (score == null || scaleMax == null) return { pct: 0, tone: "bg-muted" };
  const n = Number(score);
  return {
    pct: Math.max(0, Math.min(100, (n / scaleMax) * 100)),
    tone:
      n >= scaleMax * 0.8
        ? "bg-emerald-500"
        : n >= scaleMax * 0.5
          ? "bg-amber-500"
          : "bg-rose-500",
  };
}

// HRP-981: the same slack the backend check gives a quote
// (``_normalize_text`` / ``_normalize_quote`` in prompts_interview.py —
// keep the two in step): typographic quotes and apostrophes read as
// straight ones, an ellipsis as three dots, whitespace collapsed, lower
// case; a quote also loses the quote marks and dots around it.
const TYPOGRAPHIC: Record<string, string> = {
  "\u2018": "'",
  "\u2019": "'",
  "\u201a": "'",
  "\u201b": "'",
  "\u201c": '"',
  "\u201d": '"',
  "\u201e": '"',
  "\u201f": '"',
  "\u00ab": '"',
  "\u00bb": '"',
  "\u2039": '"',
  "\u203a": '"',
  "\u2026": "...",
};
const normalizeText = (text?: string | null) =>
  (text ?? "")
    .replace(/[\u2018-\u201f\u00ab\u00bb\u2039\u203a\u2026]/g, (ch) => TYPOGRAPHIC[ch] ?? ch)
    .split(/\s+/)
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
const normalizeQuote = (text?: string | null) =>
  normalizeText(text).replace(/^[\s"'.]+|[\s"'.]+$/g, "");

/** HRP-981: where a saved citation stands against the transcript as it
 *  reads now. The analysis kept only checked quotes, so a quote that is no
 *  longer in the text means the transcript was edited after the run.
 *  Judged by text, not by segment id: editing the whole transcript leaves
 *  the segment rows as they were, and pasting the same text again mints
 *  new ids — so the quote has to be found both in a segment and in the
 *  transcript text, whichever of the two the interview has. The segments
 *  only supply the timecode to seek to. */
export function locateCitation(
  citation: InterviewAnalysisCitation,
  segments: InterviewSegment[],
  transcript?: string | null,
): { current: boolean; seekSec: number | null } {
  const quote = normalizeQuote(citation.quote);
  const single = quote
    ? segments.filter((s) => normalizeText(s.text).includes(quote))
    : [];
  // A quote across the seam of two neighbours: the first one holds it, as
  // on the backend (`_segment_windows`).
  const holders =
    single.length > 0 || !quote
      ? single
      : segments.filter(
          (s, i) =>
            i + 1 < segments.length &&
            normalizeText(`${s.text} ${segments[i + 1].text}`).includes(quote),
        );
  const current =
    !!quote &&
    (segments.length > 0 || !!transcript) &&
    (segments.length === 0 || holders.length > 0) &&
    (!transcript || normalizeText(transcript).includes(quote));
  const holder =
    holders.find((s) => s.id === citation.segment_id) ?? holders[0];
  return {
    current,
    seekSec: holder?.start_sec ?? citation.start_sec ?? null,
  };
}

function formatTimecode(sec: number) {
  return `@ ${Math.floor(sec / 60)}:${(Math.floor(sec) % 60)
    .toString()
    .padStart(2, "0")}`;
}

// Keyed on the backend ``Verdict`` enum (prompts_interview.py) — the
// same vocabulary ai-verdict-badge colours.
const verdictTone: Record<string, string> = {
  recommended: BADGE_COLOR.green,
  needs_check: BADGE_COLOR.amber,
  not_recommended: BADGE_COLOR.red,
};

function CompetenceBars({
  competences,
  dictionary,
  onSeek,
  scaleMax,
  segments,
  transcript,
  hasMedia,
}: {
  competences: InterviewAnalysisCompetence[];
  dictionary: CompetenceDictionary;
  onSeek?: (sec: number) => void;
  scaleMax: number | null;
  segments: InterviewSegment[];
  transcript?: string | null;
  hasMedia: boolean;
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
        // HRP-673: the backend rebases the raw 0..1 score onto the tenant
        // scale as ``normalized_score``; the raw ``score`` is only a
        // last-resort fallback for payloads predating the field.
        const score = c.normalized_score ?? c.score;
        const { pct, tone } = scoreBar(score, scaleMax);
        return (
          <li key={`${c.competence_id}-${i}`} className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium">{name}</span>
              <span className="text-muted-foreground">
                {score != null ? Number(score).toFixed(1) : "—"} ·{" "}
                {competenceAssessmentStatusLabel(t, c.status)}
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
            <CitationList
              citations={(c.citations ?? []).slice(0, 3)}
              assessed={c.status === "assessed"}
              segments={segments}
              transcript={transcript}
              // A text transcript (PDF, TXT, pasted) has no recording to
              // seek — its timecodes are word-count estimates — so the
              // quote itself is the evidence there.
              onSeek={hasMedia ? onSeek : undefined}
            />
          </li>
        );
      })}
    </ul>
  );
}

function CitationList({
  citations,
  assessed,
  segments,
  transcript,
  onSeek,
}: {
  citations: InterviewAnalysisCitation[];
  assessed: boolean;
  segments: InterviewSegment[];
  transcript?: string | null;
  onSeek?: (sec: number) => void;
}) {
  const t = useTranslations("recruitment");
  const checked = citations.map((citation) => ({
    citation,
    ...locateCitation(citation, segments, transcript),
  }));
  const confirmed = checked.some((c) => c.current);
  if (checked.length === 0 && !assessed) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {assessed && !confirmed && (
        <Badge
          variant="outline"
          className={`text-[10px] ${BADGE_COLOR.amber}`}
          title={t("interviewAnalysisUnconfirmedHint")}
          data-testid="recruitment-analysis-unconfirmed"
        >
          {t("interviewAnalysisUnconfirmed")}
        </Badge>
      )}
      {checked.map(({ citation, current, seekSec }, idx) => {
        if (current && onSeek && seekSec !== null) {
          return (
            <button
              key={idx}
              type="button"
              onClick={() => onSeek(seekSec)}
              className="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-muted"
              title={citation.quote}
            >
              {formatTimecode(seekSec)}
            </button>
          );
        }
        // A quote without a segment that is not in the text was never
        // checked: it predates the check (HRP-981), when the model's
        // paraphrase was saved as is. Saying the transcript changed would
        // name the wrong reason.
        const unchecked = !current && !citation.segment_id;
        return (
          <span
            key={idx}
            className="text-[11px] text-muted-foreground"
            title={
              current
                ? undefined
                : unchecked
                  ? t("interviewAnalysisCitationUncheckedHint")
                  : t("interviewAnalysisCitationOutdatedHint")
            }
          >
            <q className={current ? "italic" : "italic opacity-60 line-through"}>
              {citation.quote}
            </q>
            {!current && (
              <span className="ml-1">
                {unchecked
                  ? t("interviewAnalysisCitationUnchecked")
                  : t("interviewAnalysisCitationOutdated")}
              </span>
            )}
          </span>
        );
      })}
    </div>
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
    const r = (analysis?.verdict || "").toLowerCase();
    return verdictTone[r] || "bg-muted text-muted-foreground border-border";
  }, [analysis]);

  // When the parent supplies scaleMax we use it directly; otherwise we fetch
  // the tenant's active scale once and derive resolvedScaleMax from props +
  // fetched state, keeping the effect free of synchronous setState calls
  // (forbidden by React 19's `react-hooks/set-state-in-effect` rule).
  // Null = the request has not answered yet; a 200 with no scale is the
  // identity bound, a failure the legacy one.
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
        setFetchedMax(
          res && typeof res.max_value === "number" && res.max_value > 0
            ? res.max_value
            : NO_SCALE_MAX,
        );
      })
      .catch(() => {
        if (!cancelled) setFetchedMax(FALLBACK_SCALE_MAX);
      });
    return () => {
      cancelled = true;
    };
  }, [scaleMax]);

  const resolvedScaleMax =
    typeof scaleMax === "number" && scaleMax > 0 ? scaleMax : fetchedMax;

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
      {(analysis.verdict || analysis.verdict_summary) && (
        <section className="space-y-1">
          <h3 className="flex items-center gap-1.5 text-sm font-medium">
            <Trophy className="size-4 text-amber-500" />
            {t("interviewAnalysisVerdictHeading")}
          </h3>
          <div className={`rounded-md border p-3 text-sm ${verdictClass}`}>
            {analysis.verdict && (
              <p className="font-semibold">
                {aiVerdictLabel(t, analysis.verdict)}
              </p>
            )}
            {analysis.verdict_summary && (
              <p className="mt-1 text-xs">{analysis.verdict_summary}</p>
            )}
            {analysis.key_strength && (
              <p className="mt-1 text-xs">
                <strong>{t("interviewAnalysisKeyStrength")}</strong>{" "}
                {analysis.key_strength}
              </p>
            )}
            {analysis.key_risk && (
              <p className="mt-1 text-xs">
                <strong>{t("interviewAnalysisRisk")}</strong>{" "}
                {analysis.key_risk}
              </p>
            )}
            {analysis.risk_mitigation && (
              <p className="mt-1 text-xs">
                <strong>{t("interviewAnalysisMitigation")}</strong>{" "}
                {analysis.risk_mitigation}
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
          segments={interview.segments ?? []}
          transcript={interview.transcript}
          hasMedia={!!(interview.audio_file_id || interview.video_file_id)}
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
                {b.competence_id && competences[b.competence_id]?.name && (
                  <p className="font-medium">
                    {competences[b.competence_id]?.name}
                  </p>
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
                <p className="font-medium">
                  {processFindingLabel(t, f.finding_type)}
                </p>
                {f.full_description && (
                  <p className="text-muted-foreground">{f.full_description}</p>
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
                <p className="font-medium">{redFlagLabel(t, f.flag_type)}</p>
                {f.description && <p>{f.description}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
