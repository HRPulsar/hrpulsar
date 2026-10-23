// HRP-1085: the media block of the interview page stops at "upload" once a
// transcript is in - pasted or uploaded - and never spins on "Fetching
// recording link…" for one; Type is locked the moment the block leaves
// "upload".

import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { interviewMediaBlock } from "@/lib/interview-upload";

const base = {
  type: "audio" as const,
  audio_file_id: null,
  video_file_id: null,
  transcript_file_id: null,
  transcription_status: "pending" as const,
};

describe("interviewMediaBlock", () => {
  it("offers the upload while nothing is in", () => {
    expect(interviewMediaBlock(base, false, false)).toBe("upload");
    // A scheduled text-transcript interview with no text yet still uploads.
    expect(
      interviewMediaBlock({ ...base, type: "text_transcript" }, false, false),
    ).toBe("upload");
  });

  it("treats pasted text as an uploaded transcript", () => {
    expect(
      interviewMediaBlock(
        { ...base, type: "text_transcript", transcription_status: "completed" },
        false,
        false,
      ),
    ).toBe("transcript");
  });

  it("shows an uploaded pdf/txt as uploaded before and without its link", () => {
    const file = {
      ...base,
      type: "text_transcript" as const,
      transcript_file_id: "f1",
      transcription_status: "completed" as const,
    };
    expect(interviewMediaBlock(file, false, false)).toBe("transcript");
    expect(interviewMediaBlock(file, false, true)).toBe("transcript");
    expect(interviewMediaBlock(file, true, false)).toBe("media");
  });

  it("waits for a recording's link, and says when it cannot have one", () => {
    const audio = { ...base, audio_file_id: "a1" };
    expect(interviewMediaBlock(audio, false, false)).toBe("loading");
    expect(interviewMediaBlock(audio, false, true)).toBe("unavailable");
    expect(interviewMediaBlock(audio, true, false)).toBe("media");
  });
});

// Catalogs are discovered, never hardcoded: ru.json is enterprise-only.
const MESSAGES_DIR = resolve(__dirname, "../../messages");
const CATALOGS = Object.fromEntries(
  readdirSync(MESSAGES_DIR)
    .filter((file) => file.endsWith(".json"))
    .map((file) => [
      basename(file, ".json"),
      JSON.parse(readFileSync(resolve(MESSAGES_DIR, file), "utf8")) as {
        recruitment: Record<string, string>;
      },
    ]),
);

describe("transcript label hint (HRP-1085)", () => {
  it.each(Object.keys(CATALOGS))(
    "%s names a speaker label, not only Interviewer/Candidate",
    (locale) => {
      const hint = CATALOGS[locale].recruitment.interviewTranscriptLabelsHint;
      expect(hint).toBeTruthy();
      expect(
        CATALOGS[locale].recruitment.textTranscriptDescription,
      ).toBeUndefined();
    },
  );

  it("gives the ru paste field its own labels, not the English ones", () => {
    if (!CATALOGS.ru) return;
    const placeholder = CATALOGS.ru.recruitment.textTranscriptPlaceholder;
    expect(placeholder.split("\n")).toHaveLength(2);
    expect(placeholder).not.toMatch(/Interviewer:|Candidate:/);
  });
});
