"use client";

import { useState } from "react";
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

const priorityOptions: { value: QuestionPriority; label: string }[] = [
  { value: "must", label: "Must" },
  { value: "should", label: "Should" },
  { value: "nice_to_ask", label: "Nice to ask" },
];

const purposeOptions: { value: QuestionPurpose; label: string }[] = [
  { value: "clarification", label: "Clarification" },
  { value: "depth", label: "Depth" },
  { value: "risk", label: "Risk" },
  { value: "motivation", label: "Motivation" },
  { value: "fit", label: "Fit" },
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
          {title || (question?.id ? "Edit question" : "New question")}
        </SheetTitle>
        <SheetDescription>
          Adjust the wording and reference answers. Changes save when you press Save.
        </SheetDescription>
      </SheetHeader>
      <div className="space-y-4 px-4 py-3">
        <div className="space-y-2">
          <Label htmlFor="question_text">Question</Label>
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
            <Label htmlFor="priority">Priority</Label>
            <Select
              value={draft.priority || "should"}
              onValueChange={(val) => update("priority", val)}
            >
              <SelectTrigger id="priority" data-testid="question-select-priority">
                <SelectValue>
                  {priorityOptions.find(
                    (p) => p.value === (draft.priority || "should"),
                  )?.label ?? "Should"}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {priorityOptions.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="purpose">Purpose</Label>
            <Select
              value={draft.purpose || "clarification"}
              onValueChange={(val) => update("purpose", val)}
            >
              <SelectTrigger id="purpose" data-testid="question-select-purpose">
                <SelectValue>
                  {purposeOptions.find(
                    (p) => p.value === (draft.purpose || "clarification"),
                  )?.label ?? "Clarification"}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {purposeOptions.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="good_answer">Good answer</Label>
          <Textarea
            id="good_answer"
            value={draft.good_answer || ""}
            onChange={(e) => update("good_answer", e.target.value)}
            rows={3}
            disabled={saving}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="acceptable_answer">Acceptable answer</Label>
          <Textarea
            id="acceptable_answer"
            value={draft.acceptable_answer || ""}
            onChange={(e) => update("acceptable_answer", e.target.value)}
            rows={2}
            disabled={saving}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="poor_answer">Poor answer</Label>
          <Textarea
            id="poor_answer"
            value={draft.poor_answer || ""}
            onChange={(e) => update("poor_answer", e.target.value)}
            rows={2}
            disabled={saving}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="resume_fragment">Resume fragment</Label>
          <Input
            id="resume_fragment"
            value={draft.resume_fragment || ""}
            onChange={(e) => update("resume_fragment", e.target.value)}
            disabled={saving}
            placeholder="optional"
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
            Delete
          </Button>
        ) : (
          <span />
        )}
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
          <Button
            onClick={() => onSave(draft)}
            disabled={saving}
            data-testid="question-btn-save"
          >
            {saving ? <Loader2 className="size-4 animate-spin" /> : "Save"}
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
