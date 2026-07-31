"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type { CandidateQuestion, QuestionPriority, QuestionPurpose } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { Loader2 } from "lucide-react";

// Module scope cannot call `useTranslations`, so the option maps hold i18n
// keys in the `recruitment` namespace and the form resolves them with its
// own `t` (see employee-status.ts for the same pattern). The `value` side
// stays the enum code sent to the API.
const priorityOptions: { value: QuestionPriority; labelKey: string }[] = [
  { value: "must", labelKey: "questionDetailPriorityMust" },
  { value: "should", labelKey: "questionDetailPriorityShould" },
  { value: "nice_to_ask", labelKey: "questionDetailPriorityNiceToAsk" },
];

const purposeOptions: { value: QuestionPurpose; labelKey: string }[] = [
  { value: "clarification", labelKey: "questionDetailPurposeClarification" },
  { value: "depth", labelKey: "questionDetailPurposeDepth" },
  { value: "risk", labelKey: "questionDetailPurposeRisk" },
  { value: "motivation", labelKey: "questionDetailPurposeMotivation" },
  { value: "fit", labelKey: "questionDetailPurposeFit" },
];

interface QuestionDetailSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  question: Partial<CandidateQuestion> | null;
  saving?: boolean;
  onSave: (data: Partial<CandidateQuestion>) => Promise<void> | void;
  onDelete?: (question: CandidateQuestion) => Promise<void> | void;
  title?: string;
}

const empty: Partial<CandidateQuestion> = {
  question_text: "",
  good_answer: "",
  acceptable_answer: "",
  poor_answer: "",
  resume_fragment: "",
  purpose: "clarification",
  priority: "should",
};

function QuestionForm({
  question,
  saving,
  onSave,
  onDelete,
  onCancel,
  title,
}: {
  question: Partial<CandidateQuestion> | null;
  saving?: boolean;
  onSave: (data: Partial<CandidateQuestion>) => Promise<void> | void;
  onDelete?: (q: CandidateQuestion) => Promise<void> | void;
  onCancel: () => void;
  title?: string;
}) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [draft, setDraft] = useState<Partial<CandidateQuestion>>(() =>
    question ? { ...empty, ...question } : { ...empty },
  );

  function update<K extends keyof CandidateQuestion>(
    key: K,
    value: CandidateQuestion[K] | string,
  ) {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <>
      <SheetHeader>
        <SheetTitle>
          {title ||
            (question?.id
              ? t("questionDetailEditTitle")
              : t("questionDetailNewTitle"))}
        </SheetTitle>
        <SheetDescription>{t("questionDetailDescription")}</SheetDescription>
      </SheetHeader>
      <div className="space-y-4 px-4 py-3">
        <div className="space-y-2">
          <Label htmlFor="question_text">
            {t("questionDetailFieldQuestion")}
          </Label>
          <Textarea
            id="question_text"
            value={draft.question_text || ""}
            onChange={(e) => update("question_text", e.target.value)}
            rows={3}
            disabled={saving}
            data-testid="question-input-text"
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="priority">{t("questionDetailFieldPriority")}</Label>
            <Select
              value={draft.priority || "should"}
              onValueChange={(val) => update("priority", val)}
            >
              <SelectTrigger id="priority" data-testid="question-select-priority">
                <SelectValue>
                  {t(
                    priorityOptions.find(
                      (p) => p.value === (draft.priority || "should"),
                    )?.labelKey ?? "questionDetailPriorityShould",
                  )}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {priorityOptions.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {t(p.labelKey)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="purpose">{t("questionDetailFieldPurpose")}</Label>
            <Select
              value={draft.purpose || "clarification"}
              onValueChange={(val) => update("purpose", val)}
            >
              <SelectTrigger id="purpose" data-testid="question-select-purpose">
                <SelectValue>
                  {t(
                    purposeOptions.find(
                      (p) => p.value === (draft.purpose || "clarification"),
                    )?.labelKey ?? "questionDetailPurposeClarification",
                  )}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {purposeOptions.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {t(p.labelKey)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="good_answer">
            {t("questionDetailFieldGoodAnswer")}
          </Label>
          <Textarea
            id="good_answer"
            value={draft.good_answer || ""}
            onChange={(e) => update("good_answer", e.target.value)}
            rows={3}
            disabled={saving}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="acceptable_answer">
            {t("questionDetailFieldAcceptableAnswer")}
          </Label>
          <Textarea
            id="acceptable_answer"
            value={draft.acceptable_answer || ""}
            onChange={(e) => update("acceptable_answer", e.target.value)}
            rows={2}
            disabled={saving}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="poor_answer">
            {t("questionDetailFieldPoorAnswer")}
          </Label>
          <Textarea
            id="poor_answer"
            value={draft.poor_answer || ""}
            onChange={(e) => update("poor_answer", e.target.value)}
            rows={2}
            disabled={saving}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="resume_fragment">
            {t("questionDetailFieldResumeFragment")}
          </Label>
          <Input
            id="resume_fragment"
            value={draft.resume_fragment || ""}
            onChange={(e) => update("resume_fragment", e.target.value)}
            disabled={saving}
            placeholder={t("questionDetailResumeFragmentPlaceholder")}
          />
        </div>
      </div>

      <SheetFooter className="flex flex-row items-center justify-between gap-2 px-4 pb-4">
        {question?.id && onDelete ? (
          <Button
            variant="outline"
            onClick={() => onDelete(question as CandidateQuestion)}
            disabled={saving}
            data-testid="question-btn-delete"
          >
            {tc("delete")}
          </Button>
        ) : (
          <span />
        )}
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={saving}>
            {tc("cancel")}
          </Button>
          <Button
            onClick={() => onSave(draft)}
            disabled={saving}
            data-testid="question-btn-save"
          >
            {saving ? <Loader2 className="size-4 animate-spin" /> : t("save")}
          </Button>
        </div>
      </SheetFooter>
    </>
  );
}

export function QuestionDetailSheet({
  open,
  onOpenChange,
  question,
  saving,
  onSave,
  onDelete,
  title,
}: QuestionDetailSheetProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full max-w-xl overflow-y-auto sm:max-w-2xl"
        data-testid="question-detail-sheet"
      >
        <QuestionForm
          key={question?.id ?? "new"}
          question={question}
          saving={saving}
          onSave={onSave}
          onDelete={onDelete}
          onCancel={() => onOpenChange(false)}
          title={title}
        />
      </SheetContent>
    </Sheet>
  );
}
