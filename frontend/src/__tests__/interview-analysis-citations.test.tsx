// @vitest-environment jsdom
//
// HRP-981: the analysis panel shows a citation for what it is. The backend
// now saves only quotes that are really in the cited segment, with that
// segment's timecodes. On the page that means: a timecode button only
// when there is a recording to seek, the quote itself for a text
// transcript, an "outdated" mark once the transcript was edited after the
// run, and "Unconfirmed" on an assessed competence nothing backs.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import {
  InterviewAnalysisPanel,
  locateCitation,
} from "@/components/recruitment/interview-analysis";
import type { Interview, InterviewSegment } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn(() => Promise.resolve(null)) },
}));

const SEGMENT: InterviewSegment = {
  id: "seg-1",
  interview_id: "iv-1",
  speaker: "Candidate",
  start_sec: 754,
  end_sec: 790,
  text: "We keyed every transfer on an idempotency key.",
};

function interview(overrides: Partial<Interview> = {}): Interview {
  return {
    id: "iv-1",
    candidate_vacancy_id: "cv-1",
    status: "completed",
    transcription_status: "completed",
    analysis_status: "completed",
    segments: [SEGMENT],
    ai_assessments: [],
    analysis: {
      verdict: "recommended",
      verdict_summary: "Fine.",
      competence_assessments: [
        {
          competence_id: "distributed-systems",
          score: 0.9,
          status: "assessed",
          reasoning: "Knows idempotency.",
          citations: [
            {
              segment_id: "seg-1",
              start_sec: 754,
              end_sec: 790,
              quote: "an idempotency key",
            },
          ],
        },
      ],
    },
    ...overrides,
  } as Interview;
}

const TRANSCRIPT = "Candidate: We keyed every transfer on an idempotency key.";

describe("locateCitation", () => {
  it("accepts a quote still in the text, whitespace and case aside", () => {
    expect(
      locateCitation(
        { segment_id: "seg-1", quote: "AN  idempotency\nkey" },
        [SEGMENT],
        TRANSCRIPT,
      ),
    ).toEqual({ current: true, seekSec: 754 });
  });

  it("calls a quote outdated once the edited transcript lost it, though the segment rows did not change", () => {
    // "Edit entire transcript" rewrites the transcript, not the segments.
    expect(
      locateCitation(
        { segment_id: "seg-1", quote: "an idempotency key" },
        [SEGMENT],
        "Candidate: We retried transfers by hand.",
      ).current,
    ).toBe(false);
  });

  it("keeps a quote current when the same text was pasted again under new segment ids", () => {
    const repasted = { ...SEGMENT, id: "seg-new", start_sec: 12 };
    expect(
      locateCitation(
        { segment_id: "seg-1", start_sec: 754, quote: "an idempotency key" },
        [repasted],
        TRANSCRIPT,
      ),
    ).toEqual({ current: true, seekSec: 12 });
  });

  it("rejects a quote no segment says any more", () => {
    expect(
      locateCitation({ segment_id: "seg-1", quote: "exactly once" }, [SEGMENT])
        .current,
    ).toBe(false);
  });

  it("forgives typographic quotes, apostrophes and the ellipsis around a quote", () => {
    const segment = { ...SEGMENT, text: "I think she's right about the keys." };
    expect(
      locateCitation({ quote: "she\u2019s right" }, [segment]).current,
    ).toBe(true);
    expect(
      locateCitation({ quote: "\u00ab\u2026she\u2019s right about\u2026\u00bb" }, [segment])
        .current,
    ).toBe(true);
  });

  it("finds a quote across the seam of two neighbouring segments", () => {
    const next = {
      ...SEGMENT,
      id: "seg-2",
      start_sec: 790,
      end_sec: 820,
      text: "Then a reconciliation loop runs nightly.",
    };
    expect(
      locateCitation(
        { segment_id: "seg-1", quote: "idempotency key. Then a reconciliation" },
        [SEGMENT, next],
        `${TRANSCRIPT} Then a reconciliation loop runs nightly.`,
      ),
    ).toEqual({ current: true, seekSec: 754 });
  });

  it("reads the transcript text when there are no segments", () => {
    expect(
      locateCitation({ quote: "reconciliation" }, [], "A reconciliation loop."),
    ).toEqual({ current: true, seekSec: null });
    expect(locateCitation({ quote: "" }, [], "anything").current).toBe(false);
  });
});

describe("InterviewAnalysisPanel citations", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function render(iv: Interview, onSeek = vi.fn()) {
    act(() => {
      root.render(
        <NextIntlClientProvider locale="en" messages={enMessages}>
          <InterviewAnalysisPanel interview={iv} onSeek={onSeek} scaleMax={1} />
        </NextIntlClientProvider>,
      );
    });
    return onSeek;
  }

  it("seeks the recording to the cited segment", () => {
    const onSeek = render(interview({ audio_file_id: "file-1" }));
    const button = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent === "@ 12:34",
    );
    expect(button).toBeDefined();
    act(() => button!.click());
    expect(onSeek).toHaveBeenCalledWith(754);
  });

  it("shows the quote, not a dead timecode, for a text transcript", () => {
    render(interview());
    expect(container.querySelector("button")).toBeNull();
    expect(container.querySelector("q")?.textContent).toBe("an idempotency key");
    expect(container.textContent).not.toContain("Unconfirmed");
  });

  it("marks a quote the edited transcript no longer holds", () => {
    render(
      interview({
        audio_file_id: "file-1",
        segments: [{ ...SEGMENT, text: "We retried transfers by hand." }],
      }),
    );
    expect(container.querySelector("button")).toBeNull();
    expect(container.textContent).toContain("outdated");
    expect(
      container.querySelector('[data-testid="recruitment-analysis-unconfirmed"]'),
    ).not.toBeNull();
  });

  it("seeks to the segment that holds the quote after a re-paste", () => {
    const onSeek = render(
      interview({
        audio_file_id: "file-1",
        transcript: TRANSCRIPT,
        segments: [{ ...SEGMENT, id: "seg-new", start_sec: 75 }],
      }),
    );
    const button = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent === "@ 1:15",
    );
    act(() => button!.click());
    expect(onSeek).toHaveBeenCalledWith(75);
  });

  it("marks an edited-out quote outdated even when the segments were not rebuilt", () => {
    render(interview({ transcript: "Candidate: We retried transfers by hand." }));
    expect(container.textContent).toContain("outdated");
  });

  it("names an unchecked paraphrase as such, not as an edit", () => {
    const iv = interview();
    iv.analysis!.competence_assessments![0].citations = [
      { segment_id: null, quote: "Knows idempotency inside out." },
    ];
    render(iv);
    expect(container.textContent).toContain("not checked");
    expect(container.textContent).not.toContain("outdated");
    expect(container.querySelector("q")?.parentElement?.getAttribute("title")).toBe(
      "This quote was saved before quotes were checked against the transcript.",
    );
  });

  it("flags an assessed competence without any citation as unconfirmed", () => {
    const iv = interview();
    iv.analysis!.competence_assessments![0].citations = [];
    render(iv);
    expect(
      container.querySelector('[data-testid="recruitment-analysis-unconfirmed"]')
        ?.textContent,
    ).toBe("Unconfirmed");
  });
});
