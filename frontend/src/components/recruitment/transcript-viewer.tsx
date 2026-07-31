"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { Interview, InterviewSegment } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Pencil, Save, X } from "lucide-react";
import { toast } from "sonner";

interface TranscriptViewerProps {
  interview: Interview;
  currentSec: number;
  onSeek: (sec: number) => void;
  onSegmentChange?: (segment: InterviewSegment) => void;
}

function formatTime(sec: number) {
  const total = Math.floor(sec);
  const m = Math.floor(total / 60)
    .toString()
    .padStart(2, "0");
  const s = (total % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

export function TranscriptViewer({
  interview,
  currentSec,
  onSeek,
  onSegmentChange,
}: TranscriptViewerProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [editingSegId, setEditingSegId] = useState<string | null>(null);
  const [draftText, setDraftText] = useState("");
  const [draftSpeaker, setDraftSpeaker] = useState("");
  const [saving, setSaving] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const segments = useMemo(
    () =>
      [...(interview.segments ?? [])].sort(
        (a, b) => a.start_sec - b.start_sec,
      ),
    [interview.segments],
  );

  const activeSegId = useMemo(() => {
    for (let i = segments.length - 1; i >= 0; i--) {
      if (currentSec >= segments[i].start_sec) return segments[i].id;
    }
    return null;
  }, [segments, currentSec]);

  // Auto-scroll active segment into view (sync-scroll with player).
  useEffect(() => {
    if (!activeSegId || !containerRef.current) return;
    const el = containerRef.current.querySelector<HTMLDivElement>(
      `[data-seg="${activeSegId}"]`,
    );
    if (el) {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [activeSegId]);

  function startEdit(seg: InterviewSegment) {
    setEditingSegId(seg.id);
    setDraftText(seg.text);
    setDraftSpeaker(seg.speaker);
  }

  function cancelEdit() {
    setEditingSegId(null);
    setDraftText("");
    setDraftSpeaker("");
  }

  async function saveEdit(seg: InterviewSegment) {
    setSaving(true);
    try {
      const updated = await api.put<InterviewSegment>(
        `/recruitment/interviews/${interview.id}/segments/${seg.id}`,
        {
          text: draftText,
          speaker: draftSpeaker,
        },
      );
      toast.success(t("transcriptViewerToastSegmentUpdated"));
      onSegmentChange?.(updated);
      cancelEdit();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("transcriptViewerSaveFailed"),
      );
    } finally {
      setSaving(false);
    }
  }

  if (segments.length === 0) {
    if (interview.transcript) {
      return (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            {t("transcriptViewerNoDiarization")}
          </p>
          <div className="whitespace-pre-wrap rounded-md border bg-muted/30 p-3 text-sm">
            {interview.transcript}
          </div>
        </div>
      );
    }
    return (
      <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
        {interview.transcription_status === "processing"
          ? t("transcriptViewerTranscribing")
          : t("transcriptViewerEmpty")}
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      data-testid="recruitment-interview-transcript"
      className="max-h-[60vh] space-y-2 overflow-y-auto pr-1"
    >
      {segments.map((seg) => {
        const isActive = seg.id === activeSegId;
        const isEditing = seg.id === editingSegId;
        return (
          <div
            key={seg.id}
            data-seg={seg.id}
            data-testid={`recruitment-segment-${seg.id}`}
            className={`group rounded-md border p-2 text-sm transition-colors ${
              isActive
                ? "border-accent bg-accent/5"
                : "border-transparent hover:border-border hover:bg-muted/30"
            }`}
          >
            <div className="flex items-center justify-between gap-2 text-xs">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="text-[10px]">
                  {seg.speaker}
                </Badge>
                <button
                  type="button"
                  onClick={() => onSeek(seg.start_sec)}
                  className="font-mono text-muted-foreground hover:text-foreground hover:underline"
                  title={t("transcriptViewerJumpToTimestamp")}
                >
                  {formatTime(seg.start_sec)}
                </button>
              </div>
              {!isEditing ? (
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="opacity-0 transition-opacity group-hover:opacity-100"
                  onClick={() => startEdit(seg)}
                  aria-label={t("transcriptViewerEditSegment")}
                >
                  <Pencil className="size-3.5" />
                </Button>
              ) : (
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={cancelEdit}
                    disabled={saving}
                    aria-label={tc("cancel")}
                  >
                    <X className="size-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => saveEdit(seg)}
                    disabled={saving}
                    aria-label={t("save")}
                  >
                    <Save className="size-3.5" />
                  </Button>
                </div>
              )}
            </div>
            {isEditing ? (
              <div className="mt-1.5 space-y-1.5">
                <input
                  className="h-7 w-full rounded border border-input bg-transparent px-2 text-xs"
                  value={draftSpeaker}
                  onChange={(e) => setDraftSpeaker(e.target.value)}
                  placeholder={t("transcriptViewerSpeakerPlaceholder")}
                />
                <Textarea
                  rows={3}
                  value={draftText}
                  onChange={(e) => setDraftText(e.target.value)}
                />
              </div>
            ) : (
              <p className="mt-1 leading-relaxed">{seg.text}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
