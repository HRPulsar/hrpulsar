"use client";

// HRP-444: "New set" used to fire another from-scratch pre-interview
// generation. Only the first set works that way — every later set is
// built on an interview that already happened, for a round that does
// not have a set yet. This dialog collects those two choices before
// anything is generated.

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatDate } from "@/lib/date-format";
import {
  type AssessmentRoundRow,
  interviewLabel as buildInterviewLabel,
  type NewSetSelection,
  nextInterviewNumber,
  type QuestionSetRow,
  selectableRounds,
  type TranscribedInterviewRow,
} from "@/lib/new-question-set";

/** Sentinel for "open the next round first" — not a round id. */
const CREATE_ROUND = "__create__";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  rounds: AssessmentRoundRow[];
  /** Already filtered to transcribed, non-archived interviews. */
  interviews: TranscribedInterviewRow[];
  sets: QuestionSetRow[];
  generating: boolean;
  costSuffix: string;
  onSubmit: (selection: NewSetSelection) => void;
}

export function NewQuestionSetDialog({
  open,
  onOpenChange,
  rounds,
  interviews,
  sets,
  generating,
  costSuffix,
  onSubmit,
}: Props) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");

  const openRounds = useMemo(
    () => selectableRounds(rounds, sets),
    [rounds, sets],
  );
  const nextNumber = useMemo(() => nextInterviewNumber(rounds), [rounds]);

  // ``null`` means "no explicit pick yet", so the defaults below stay
  // live: rounds and interviews both move while the page is up, and a
  // pick stored at mount would point at a round that has since been
  // filled. Closing the dialog clears the overrides.
  const [roundPick, setRoundPick] = useState<string | null>(null);
  const [transcriptPick, setTranscriptPick] = useState<string | null>(null);

  const roundChoice = roundPick ?? openRounds[0]?.id ?? CREATE_ROUND;
  const transcriptId =
    transcriptPick ?? interviews[interviews.length - 1]?.id ?? "";

  function reset() {
    setRoundPick(null);
    setTranscriptPick(null);
  }

  function interviewLabel(iv: TranscribedInterviewRow): string {
    return buildInterviewLabel(iv, t, formatDate);
  }

  function roundLabel(id: string): string {
    if (id === CREATE_ROUND) {
      return t("questionSetsNewSetCreateRound", { number: nextNumber });
    }
    const rd = openRounds.find((r) => r.id === id);
    return t("managerAssessmentRoundInterview", {
      number: rd?.round_number ?? nextNumber,
    });
  }

  const noTranscripts = interviews.length === 0;

  function handleSubmit() {
    if (!transcriptId) return;
    onSubmit({
      transcriptId,
      contextTranscriptIds: interviews.map((iv) => iv.id),
      roundId: roundChoice === CREATE_ROUND ? null : roundChoice,
      createRound: roundChoice === CREATE_ROUND,
    });
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset();
        onOpenChange(o);
      }}
    >
      <DialogContent
        className="max-w-lg"
        data-testid="recruitment-interview-questions-new-set-dialog"
      >
        <DialogHeader>
          <DialogTitle>{t("questionSetsNewSetDialogTitle")}</DialogTitle>
        </DialogHeader>

        <p className="text-sm text-muted-foreground">
          {t("questionSetsNewSetDialogHint")}
        </p>

        {noTranscripts ? (
          <p
            className="rounded-md border border-dashed p-4 text-sm text-muted-foreground"
            data-testid="recruitment-interview-questions-new-set-no-transcripts"
          >
            {t("questionSetsNewSetNoTranscripts")}
          </p>
        ) : (
          <div className="space-y-4">
            <div>
              <Label>{t("questionSetsNewSetFieldRound")}</Label>
              <Select value={roundChoice} onValueChange={setRoundPick}>
                <SelectTrigger
                  className="w-full"
                  data-testid="recruitment-interview-questions-new-set-round"
                >
                  <SelectValue>{roundLabel(roundChoice)}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {openRounds.map((r) => (
                    <SelectItem key={r.id} value={r.id}>
                      {t("managerAssessmentRoundInterview", {
                        number: r.round_number ?? nextNumber,
                      })}
                    </SelectItem>
                  ))}
                  <SelectItem value={CREATE_ROUND}>
                    {t("questionSetsNewSetCreateRound", { number: nextNumber })}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label>{t("questionSetsNewSetFieldTranscript")}</Label>
              <Select value={transcriptId} onValueChange={setTranscriptPick}>
                <SelectTrigger
                  className="w-full"
                  data-testid="recruitment-interview-questions-new-set-transcript"
                >
                  <SelectValue>
                    {interviews.find((iv) => iv.id === transcriptId)
                      ? interviewLabel(
                          interviews.find((iv) => iv.id === transcriptId)!,
                        )
                      : t("questionSetsNewSetFieldTranscript")}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {interviews.map((iv) => (
                    <SelectItem key={iv.id} value={iv.id}>
                      {interviewLabel(iv)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("questionSetsNewSetTranscriptHint")}
              </p>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {tc("cancel")}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={noTranscripts || !transcriptId || generating}
            data-testid="recruitment-interview-questions-new-set-submit"
          >
            {generating ? (
              <>
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                {t("questionSetsGenerating")}
              </>
            ) : (
              <>
                <Sparkles className="mr-1 h-4 w-4" />
                {t("questionSetsNewSetSubmit")}
                {costSuffix}
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
