"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  competenceGenerationApi,
  type SessionHistoryItem,
  type SessionStatus,
} from "@/lib/api/competence-generation";
import { formatDateTime } from "@/lib/date-format";
import { BADGE_COLOR } from "@/lib/badge-tones";

interface Props {
  specializationId: string;
}

const STATUS_LABEL: Record<SessionStatus, string> = {
  pending: "Pending",
  running: "Running",
  ready: "Ready",
  error: "Error",
  applied: "Applied",
  cancelled: "Cancelled",
};

const STATUS_TONE: Record<SessionStatus, string> = {
  pending: BADGE_COLOR.neutral,
  running: BADGE_COLOR.blue,
  ready: BADGE_COLOR.amber,
  error: BADGE_COLOR.red,
  applied: BADGE_COLOR.green,
  cancelled: BADGE_COLOR.neutral,
};

function formatDate(iso: string): string {
  return formatDateTime(iso);
}

function summaryLine(item: SessionHistoryItem): string {
  const parts: string[] = [];
  if (item.summary.position_title) parts.push(`Position: ${item.summary.position_title}`);
  if (item.summary.refinement_prompt) {
    const trimmed = item.summary.refinement_prompt.replace(/\s+/g, " ").trim();
    parts.push(
      trimmed.length > 80 ? `Refine: ${trimmed.slice(0, 80)}…` : `Refine: ${trimmed}`,
    );
  }
  if (item.summary.file_count > 0) {
    parts.push(
      `${item.summary.file_count} file${item.summary.file_count === 1 ? "" : "s"}`,
    );
  }
  if (!item.summary.with_indicators) parts.push("No indicators");
  return parts.length > 0 ? parts.join(" · ") : "—";
}

export function AiHistoryTab({ specializationId }: Props) {
  const router = useRouter();
  const [items, setItems] = useState<SessionHistoryItem[] | null>(null);
  // Initialise as true so the "Loading…" state shows on first render without
  // a setState-in-effect lint hit (react-hooks/set-state-in-effect).
  const [loading, setLoading] = useState(true);
  const [replayingId, setReplayingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    competenceGenerationApi
      .list({ target_id: specializationId, limit: 50 })
      .then((rows) => {
        if (!cancelled) setItems(rows);
      })
      .catch((err) => {
        if (!cancelled) {
          toast.error(
            err instanceof Error ? err.message : "Failed to load AI history",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [specializationId]);

  async function handleReplay(item: SessionHistoryItem) {
    if (replayingId) return;
    setReplayingId(item.id);
    try {
      const child = await competenceGenerationApi.regenerate(item.id);
      router.push(
        `/company/specializations/${specializationId}/ai-generate?session=${child.id}`,
      );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to start regeneration",
      );
      setReplayingId(null);
    }
  }

  if (loading && items === null) {
    return (
      <p
        data-testid="specialization-ai-history-loading"
        className="py-8 text-center text-sm text-muted-foreground"
      >
        Loading AI history…
      </p>
    );
  }

  if (!items || items.length === 0) {
    return (
      <div
        data-testid="specialization-ai-history-empty"
        className="rounded-md border border-dashed bg-muted/30 px-4 py-12 text-center text-sm text-muted-foreground"
      >
        No AI generations yet. Use «AI Generate matrix» to start one.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border">
      <table
        data-testid="specialization-ai-history"
        className="w-full text-sm"
      >
        <thead className="bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-2 font-medium">Date</th>
            <th className="px-3 py-2 font-medium">Initiator</th>
            <th className="px-3 py-2 font-medium">Brief</th>
            <th className="px-3 py-2 font-medium text-right">Counts</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const isApplied = item.status === "applied";
            const replayEnabled =
              item.status === "applied" ||
              item.status === "cancelled" ||
              item.status === "error";
            return (
              <tr
                key={item.id}
                data-testid={`specialization-ai-history-row-${item.id}`}
                className="border-t"
              >
                <td className="px-3 py-2 text-xs text-muted-foreground">
                  {formatDate(item.created_at)}
                </td>
                <td className="px-3 py-2">{item.user_full_name}</td>
                <td
                  className="px-3 py-2 text-muted-foreground"
                  data-testid="specialization-ai-history-summary"
                >
                  {summaryLine(item)}
                </td>
                <td className="px-3 py-2 text-right text-xs">
                  <span className="text-muted-foreground">
                    {item.counts.competences} comp · {item.counts.indicators} ind
                  </span>
                  {(isApplied || item.status === "ready") && (
                    <div className="text-[11px]">
                      <span className="text-green-700">
                        ✓ {item.counts.accepted}
                      </span>
                      {" · "}
                      <span className="text-muted-foreground">
                        ✕ {item.counts.rejected}
                      </span>
                    </div>
                  )}
                </td>
                <td className="px-3 py-2">
                  <span
                    className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${STATUS_TONE[item.status]}`}
                  >
                    {STATUS_LABEL[item.status]}
                  </span>
                  {item.error_code && (
                    <div className="text-[11px] text-red-700">
                      {item.error_code}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  <button
                    type="button"
                    data-testid={`specialization-ai-history-replay-${item.id}`}
                    disabled={!replayEnabled || replayingId !== null}
                    onClick={() => handleReplay(item)}
                    className="rounded-md border border-input bg-background px-2 py-1 text-xs font-medium hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {replayingId === item.id ? "Starting…" : "Repeat"}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
