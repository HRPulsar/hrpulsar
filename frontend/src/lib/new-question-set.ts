/**
 * HRP-444: what the "New set" dialog needs to decide, kept out of the
 * component so it can be tested without a DOM.
 *
 * Only the first set is generated from scratch. Every later set follows
 * a round that actually happened, so the dialog has to answer two
 * questions before it can call the API: which assessment round is this
 * set for, and which transcript is it built on.
 */

export interface TranscribedInterviewRow {
  id: string;
  title?: string | null;
  interview_date?: string | null;
  transcription_status?: string | null;
  archived_at?: string | null;
}

export interface AssessmentRoundRow {
  id: string;
  type: "pre_interview" | "interview" | "final";
  round_number: number | null;
  archived_at?: string | null;
}

export interface QuestionSetRow {
  id: string | null;
  assessment_round_id?: string | null;
  archived_at?: string | null;
}

/**
 * Interviews whose transcript is finished and still live.
 *
 * Matches the backend's definition in ``_load_transcripts`` — a set can
 * only be built on a transcript the server will actually load, so an
 * offer the server would reject must never appear in the picker.
 */
export function transcribedInterviews(
  rows: TranscribedInterviewRow[],
): TranscribedInterviewRow[] {
  return rows.filter(
    (r) => r.transcription_status === "completed" && !r.archived_at,
  );
}

/** Next free ``Interview N`` number, ignoring pre-interview and final. */
export function nextInterviewNumber(rounds: AssessmentRoundRow[]): number {
  const numbers = rounds
    .filter((r) => r.type === "interview")
    .map((r) => r.round_number || 0);
  return (numbers.length ? Math.max(...numbers) : 0) + 1;
}

/**
 * Interview rounds that may still receive a question set.
 *
 * A round already holding a live set is not offered — the server
 * enforces one set per round (409 ``round_already_has_question_set``)
 * and the dialog should not let a user walk into that.
 */
export function selectableRounds(
  rounds: AssessmentRoundRow[],
  sets: QuestionSetRow[],
): AssessmentRoundRow[] {
  const taken = new Set(
    sets
      .filter((s) => !s.archived_at && s.assessment_round_id)
      .map((s) => String(s.assessment_round_id)),
  );
  return rounds.filter(
    (r) => r.type === "interview" && !r.archived_at && !taken.has(r.id),
  );
}

export interface NewSetSelection {
  /** Interview whose transcript this set follows from. Required. */
  transcriptId: string;
  /** Every transcript the model may read as context. */
  contextTranscriptIds: string[];
  /** Existing round to bind to; ignored when ``createRound``. */
  roundId: string | null;
  /** Open the next Interview N first and bind to that. */
  createRound: boolean;
}

/**
 * Request body for ``POST /v1/candidate-vacancies/{id}/question-sets``.
 *
 * ``round_id`` is the interview this set *follows from* (what the UI
 * labels "Follows from …"), while ``source_round_ids`` is the wider
 * context the model reads — every prior transcript, not just the picked
 * one. The two fields already carry exactly these meanings server-side.
 */
export function buildNewSetBody(
  selection: NewSetSelection,
): Record<string, unknown> {
  const context = Array.from(
    new Set([selection.transcriptId, ...selection.contextTranscriptIds]),
  ).filter(Boolean);
  const body: Record<string, unknown> = {
    mode: "dynamic_next",
    set_type: "interview_round",
    round_id: selection.transcriptId,
    source_round_ids: context,
  };
  if (selection.createRound) {
    body.create_round = true;
  } else if (selection.roundId) {
    body.assessment_round_id = selection.roundId;
  }
  return body;
}

export type Translate = (
  key: string,
  values?: Record<string, string | number>,
) => string;

/**
 * How an interview is named wherever it is referenced.
 *
 * Interviews have an optional title only, so the Interviews block falls
 * back to the date and then to a generic label. The New set dialog and
 * the set header have to agree with it — a set that says it follows
 * "Interview of 2026-08-01" must name the row the user sees there.
 */
export function interviewLabel(
  iv: TranscribedInterviewRow,
  t: Translate,
  formatDate: (iso: string) => string,
): string {
  if (iv.title) return iv.title;
  if (iv.interview_date) {
    return t("candidateInterviewsRowTitleDated", {
      date: formatDate(iv.interview_date),
    });
  }
  return t("interviewBreadcrumb");
}

/**
 * Interview ids a set was built on, in the order the API returned them.
 * Falls back to ``round_id`` for sets generated before HRP-444, which
 * only ever recorded the single round they followed.
 */
export function setSourceInterviewIds(set: {
  source_round_ids?: string[] | null;
  round_id?: string | null;
}): string[] {
  const ids = set.source_round_ids?.filter(Boolean) ?? [];
  if (ids.length) return ids;
  return set.round_id ? [set.round_id] : [];
}
