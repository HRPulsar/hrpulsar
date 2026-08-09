// HRP-444: the New set dialog only has two decisions to make, and both
// are pure. Pinning them here keeps the guard rails (no round twice, no
// transcript the server would refuse) honest without rendering anything.

import { describe, expect, it } from "vitest";
import {
  buildNewSetBody,
  interviewLabel,
  nextInterviewNumber,
  selectableRounds,
  setSourceInterviewIds,
  transcribedInterviews,
} from "@/lib/new-question-set";

describe("transcribedInterviews", () => {
  it("keeps only completed, non-archived transcripts", () => {
    const rows = [
      { id: "a", transcription_status: "completed", archived_at: null },
      { id: "b", transcription_status: "processing", archived_at: null },
      { id: "c", transcription_status: "completed", archived_at: "2026-08-01" },
      { id: "d", transcription_status: "failed", archived_at: null },
    ];
    expect(transcribedInterviews(rows).map((r) => r.id)).toEqual(["a"]);
  });
});

describe("nextInterviewNumber", () => {
  it("starts at 1 when no interview round exists", () => {
    expect(
      nextInterviewNumber([
        { id: "p", type: "pre_interview", round_number: null },
      ]),
    ).toBe(1);
  });

  it("continues from the highest interview number", () => {
    expect(
      nextInterviewNumber([
        { id: "p", type: "pre_interview", round_number: null },
        { id: "i1", type: "interview", round_number: 1 },
        { id: "i2", type: "interview", round_number: 2 },
        { id: "f", type: "final", round_number: null },
      ]),
    ).toBe(3);
  });
});

describe("selectableRounds", () => {
  const rounds = [
    { id: "p", type: "pre_interview" as const, round_number: null },
    { id: "i1", type: "interview" as const, round_number: 1 },
    { id: "i2", type: "interview" as const, round_number: 2 },
    { id: "i3", type: "interview" as const, round_number: 3, archived_at: "x" },
  ];

  it("offers interview rounds that have no set yet", () => {
    const sets = [{ id: "s1", assessment_round_id: "i1", archived_at: null }];
    expect(selectableRounds(rounds, sets).map((r) => r.id)).toEqual(["i2"]);
  });

  it("frees a round again once its set is archived", () => {
    const sets = [
      { id: "s1", assessment_round_id: "i1", archived_at: "2026-08-01" },
    ];
    expect(selectableRounds(rounds, sets).map((r) => r.id)).toEqual([
      "i1",
      "i2",
    ]);
  });

  it("ignores sets that are not bound to a round", () => {
    const sets = [{ id: "s1", assessment_round_id: null, archived_at: null }];
    expect(selectableRounds(rounds, sets).map((r) => r.id)).toEqual([
      "i1",
      "i2",
    ]);
  });
});

describe("buildNewSetBody", () => {
  it("binds an existing round and always asks for a round set", () => {
    const body = buildNewSetBody({
      transcriptId: "iv2",
      contextTranscriptIds: ["iv1", "iv2"],
      roundId: "r2",
      createRound: false,
    });
    expect(body).toEqual({
      mode: "dynamic_next",
      set_type: "interview_round",
      round_id: "iv2",
      source_round_ids: ["iv2", "iv1"],
      assessment_round_id: "r2",
    });
  });

  it("asks the server to open the next round instead", () => {
    const body = buildNewSetBody({
      transcriptId: "iv1",
      contextTranscriptIds: ["iv1"],
      roundId: null,
      createRound: true,
    });
    expect(body.create_round).toBe(true);
    expect(body.assessment_round_id).toBeUndefined();
    expect(body.source_round_ids).toEqual(["iv1"]);
  });

  it("keeps the picked transcript in context even if it was not listed", () => {
    const body = buildNewSetBody({
      transcriptId: "iv9",
      contextTranscriptIds: ["iv1"],
      roundId: null,
      createRound: true,
    });
    expect(body.source_round_ids).toEqual(["iv9", "iv1"]);
  });
});

describe("setSourceInterviewIds", () => {
  it("prefers the recorded source rounds", () => {
    expect(
      setSourceInterviewIds({ source_round_ids: ["a", "b"], round_id: "c" }),
    ).toEqual(["a", "b"]);
  });

  it("falls back to round_id for pre-HRP-444 sets", () => {
    expect(
      setSourceInterviewIds({ source_round_ids: null, round_id: "c" }),
    ).toEqual(["c"]);
  });

  it("returns nothing for a set built from the resume alone", () => {
    expect(
      setSourceInterviewIds({ source_round_ids: [], round_id: null }),
    ).toEqual([]);
  });
});

describe("interviewLabel", () => {
  const t = (key: string, values?: Record<string, string | number>) =>
    values ? `${key}:${JSON.stringify(values)}` : key;
  const fmt = (iso: string) => iso.slice(0, 10);

  it("uses the title when the interview has one", () => {
    expect(
      interviewLabel({ id: "a", title: "Tech screen" }, t, fmt),
    ).toBe("Tech screen");
  });

  it("falls back to the dated label", () => {
    expect(
      interviewLabel(
        { id: "a", title: null, interview_date: "2026-08-01T10:00:00Z" },
        t,
        fmt,
      ),
    ).toBe('candidateInterviewsRowTitleDated:{"date":"2026-08-01"}');
  });

  it("falls back to a generic label when it has neither", () => {
    expect(interviewLabel({ id: "a" }, t, fmt)).toBe("interviewBreadcrumb");
  });
});
