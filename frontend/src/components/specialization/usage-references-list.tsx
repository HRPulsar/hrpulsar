"use client";

// HRP-103 redo: shared block for the specialization-delete confirm
// dialogs (list + detail). Renders the live positions / grade chains
// that block deletion so the operator can see exactly what to detach
// before retrying. `null` usage = still loading; `undefined` = no
// references (delete is free to proceed).

import { Loader2 } from "lucide-react";
import type { DictionaryItemUsage } from "@/lib/api/dictionaries";
import { ALERT_TONE } from "@/lib/badge-tones";

type Props = {
  usage: DictionaryItemUsage | null | undefined;
};

export function UsageReferencesList({ usage }: Props) {
  if (usage === null) {
    return (
      <div
        data-testid="usage-references-loading"
        className="flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground"
      >
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading references…
      </div>
    );
  }
  if (!usage) return null;

  const hasPositions = usage.positions.length > 0;
  const hasChains = usage.chains.length > 0;
  const extraCounts: { key: string; label: string; count: number }[] = [
    { key: "assessments", label: "Assessments", count: usage.assessments_count },
    {
      key: "assessment-groups",
      label: "Assessment groups",
      count: usage.assessment_groups_count,
    },
    { key: "pdps", label: "PDPs", count: usage.pdps_count },
    {
      key: "exam-pass-marks",
      label: "Exam pass marks",
      count: usage.exam_pass_marks_count,
    },
    // HRP-286 redo: non-zero only for competence_type items.
    { key: "competences", label: "Competences", count: usage.competences_count },
  ].filter((entry) => entry.count > 0);
  if (!hasPositions && !hasChains && extraCounts.length === 0) return null;

  return (
    <div
      data-testid="usage-references"
      className={`space-y-3 rounded-md border p-3 text-sm ${ALERT_TONE.amber}`}
    >
      <p className="text-xs font-medium uppercase tracking-wide text-amber-700 dark:text-amber-300">
        Detach the references below before deleting
      </p>
      {hasPositions ? (
        <section data-testid="usage-references-positions">
          <p className="text-xs font-semibold">
            Positions ({usage.positions.length})
          </p>
          <ul className="mt-1 space-y-0.5 text-xs">
            {usage.positions.map((p) => (
              <li
                key={p.id}
                data-testid={`usage-references-position-${p.id}`}
                className="truncate"
              >
                • {p.title}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {hasChains ? (
        <section data-testid="usage-references-chains">
          <p className="text-xs font-semibold">
            Grade chains ({usage.chains.length})
          </p>
          <ul className="mt-1 space-y-0.5 text-xs">
            {usage.chains.map((c) => (
              <li
                key={c.id}
                data-testid={`usage-references-chain-${c.id}`}
                className="truncate"
              >
                • {c.specialization_title ?? "—"} → {c.grade_title ?? "—"}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {extraCounts.length > 0 ? (
        <section data-testid="usage-references-extra">
          <p className="text-xs font-semibold">Other references</p>
          <ul className="mt-1 space-y-0.5 text-xs">
            {extraCounts.map((entry) => (
              <li
                key={entry.key}
                data-testid={`usage-references-${entry.key}`}
              >
                • {entry.label}: {entry.count}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
