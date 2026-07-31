"use client";

import { useTranslations } from "next-intl";
import type { Interview } from "@/lib/types";
import { Check, Circle, Loader2, X } from "lucide-react";

interface AnalysisProgressProps {
  interview: Interview;
}

type StageState = "done" | "active" | "todo" | "failed";

function StageRow({
  state,
  label,
  detail,
}: {
  state: StageState;
  label: string;
  detail?: string;
}) {
  const Icon = state === "done"
    ? Check
    : state === "active"
      ? Loader2
      : state === "failed"
        ? X
        : Circle;
  const tone = {
    done: "text-emerald-600",
    active: "text-accent",
    todo: "text-muted-foreground/50",
    failed: "text-rose-600",
  }[state];
  return (
    <li className="flex items-start gap-2 text-xs">
      <Icon
        className={`mt-0.5 size-3.5 ${tone} ${state === "active" ? "animate-spin" : ""}`}
      />
      <div className="flex-1">
        <p className={state === "todo" ? "text-muted-foreground" : "font-medium"}>
          {label}
        </p>
        {detail && (
          <p className="text-[10px] text-muted-foreground">{detail}</p>
        )}
      </div>
    </li>
  );
}

export function AnalysisProgress({ interview }: AnalysisProgressProps) {
  const t = useTranslations("recruitment");
  const hasMedia = !!(interview.audio_file_id || interview.video_file_id);

  const upload: StageState = hasMedia ? "done" : "todo";

  let transcription: StageState;
  if (interview.transcription_status === "completed") transcription = "done";
  else if (interview.transcription_status === "processing")
    transcription = "active";
  else if (interview.transcription_status === "failed")
    transcription = "failed";
  else transcription = hasMedia ? "todo" : "todo";

  const diarization: StageState =
    interview.transcription_status === "completed"
      ? interview.segments.length > 1
        ? "done"
        : "todo"
      : "todo";

  const hasAnalysis =
    interview.analysis &&
    (interview.analysis.competence_assessments?.length ?? 0) > 0;

  let competence: StageState;
  if (interview.analysis_status === "completed" && hasAnalysis)
    competence = "done";
  else if (interview.analysis_status === "processing") competence = "active";
  else if (interview.analysis_status === "failed") competence = "failed";
  else competence = "todo";

  const blindSpots: StageState =
    interview.analysis?.blind_spots && interview.analysis.blind_spots.length > 0
      ? "done"
      : interview.analysis_status === "processing"
        ? "active"
        : "todo";

  const verdict: StageState = interview.analysis?.verdict
    ? "done"
    : interview.analysis_status === "processing"
      ? "active"
      : "todo";

  return (
    <ul className="space-y-1.5">
      <StageRow state={upload} label={t("analysisProgressUpload")} />
      <StageRow
        state={transcription}
        label={t("analysisProgressTranscription")}
        detail={interview.transcription_error || undefined}
      />
      <StageRow state={diarization} label={t("analysisProgressDiarization")} />
      <StageRow state={competence} label={t("analysisProgressCompetence")} />
      <StageRow state={blindSpots} label={t("analysisProgressBlindSpots")} />
      <StageRow
        state={verdict}
        label={t("analysisProgressVerdict")}
        detail={interview.analysis_error || undefined}
      />
    </ul>
  );
}
