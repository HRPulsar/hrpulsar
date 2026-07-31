"use client";

import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import type { CandidateQuestion, QuestionPriority } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Pencil, RefreshCw, Sparkles, Trash2 } from "lucide-react";

const priorityClasses: Record<QuestionPriority, string> = {
  must: "bg-[color-mix(in_oklch,var(--rec-red-flag)_15%,transparent)] text-[var(--rec-red-flag)]",
  should:
    "bg-[color-mix(in_oklch,var(--rec-data-partial)_15%,transparent)] text-[var(--rec-data-partial)]",
  nice_to_ask:
    "bg-[color-mix(in_oklch,var(--rec-data-missing)_15%,transparent)] text-[var(--rec-data-missing)]",
};

/** Priority code → key in the `recruitment` i18n namespace. */
const priorityLabelKeys: Record<QuestionPriority, string> = {
  must: "questionCardPriorityMust",
  should: "questionCardPriorityShould",
  nice_to_ask: "questionCardPriorityNiceToAsk",
};

interface QuestionCardProps {
  question: CandidateQuestion;
  competenceName?: string | null;
  compact?: boolean;
  onEdit?: (q: CandidateQuestion) => void;
  onDelete?: (q: CandidateQuestion) => void;
  onRegenerate?: (q: CandidateQuestion) => void;
  onAskedToggle?: (q: CandidateQuestion, asked: boolean) => void;
  asked?: boolean;
}

export function QuestionCard({
  question,
  competenceName,
  compact,
  onEdit,
  onDelete,
  onRegenerate,
  onAskedToggle,
  asked = false,
}: QuestionCardProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const priority = question.priority;
  return (
    <div
      data-testid={`question-card-${question.id}`}
      className={cn(
        "rounded-lg border p-3 transition-colors",
        compact ? "space-y-1.5" : "space-y-2",
        asked && "bg-muted/40",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-1 items-start gap-2">
          {!question.is_manual && (
            <Sparkles className="mt-0.5 size-3.5 shrink-0 text-[var(--rec-ai-accent)]" />
          )}
          <p
            className={cn(
              "text-sm",
              asked && "text-muted-foreground line-through",
            )}
          >
            {question.question_text}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <Badge
            variant="secondary"
            className={cn("text-[10px]", priorityClasses[priority])}
          >
            {t(priorityLabelKeys[priority])}
          </Badge>
          {onAskedToggle && priority === "must" && (
            <input
              type="checkbox"
              checked={asked}
              onChange={(e) => onAskedToggle(question, e.target.checked)}
              className="size-3.5 cursor-pointer"
              aria-label={t("questionCardMarkAsked")}
              data-testid={`question-asked-${question.id}`}
            />
          )}
        </div>
      </div>

      {!compact && (question.purpose || competenceName) && (
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          {competenceName && <span>{competenceName}</span>}
          <span className="capitalize">{question.purpose}</span>
        </div>
      )}

      {!compact && question.resume_fragment && (
        <p className="rounded-md bg-muted/40 p-2 text-xs italic text-muted-foreground">
          “{question.resume_fragment}”
        </p>
      )}

      {!compact && (onEdit || onDelete || onRegenerate) && (
        <div className="flex items-center justify-end gap-1 pt-1">
          {onRegenerate && !question.is_manual && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onRegenerate(question)}
              data-testid={`question-regenerate-${question.id}`}
              aria-label={t("questionCardRegenerateAria")}
            >
              <RefreshCw className="size-3.5" />
            </Button>
          )}
          {onEdit && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onEdit(question)}
              data-testid={`question-edit-${question.id}`}
              aria-label={t("actionEdit")}
            >
              <Pencil className="size-3.5" />
            </Button>
          )}
          {onDelete && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onDelete(question)}
              data-testid={`question-delete-${question.id}`}
              aria-label={tc("delete")}
            >
              <Trash2 className="size-3.5" />
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
