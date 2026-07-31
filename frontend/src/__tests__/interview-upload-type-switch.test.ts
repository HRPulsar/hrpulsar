import { describe, expect, it } from "vitest";
import {
  detectKind,
  requiresTypeSwitchConfirm,
} from "@/lib/interview-upload";

// detectKind only reads `name` and `type`, so a structural stub is enough.
function file(name: string, type: string): File {
  return { name, type } as unknown as File;
}

describe("detectKind — MIME types named in HRP-405", () => {
  it.each([
    ["audio/mpeg", "audio"],
    ["audio/wav", "audio"],
    ["audio/x-wav", "audio"],
    ["audio/mp4", "audio"],
    ["audio/x-m4a", "audio"],
    ["video/mp4", "video"],
    ["video/webm", "video"],
    ["application/pdf", "text_transcript"],
    ["text/plain", "text_transcript"],
  ])("maps %s to %s", (mime, expected) => {
    expect(detectKind(file("recording.bin", mime))).toBe(expected);
  });

  it("falls back to the extension when the browser reports no MIME", () => {
    expect(detectKind(file("legacy.avi", ""))).toBe("video");
    expect(detectKind(file("notes.txt", ""))).toBe("text_transcript");
  });
});

describe("requiresTypeSwitchConfirm", () => {
  // Case 1: audio / text_transcript interview receiving a video file.
  it("warns before turning an audio or transcript interview into video", () => {
    expect(requiresTypeSwitchConfirm("audio", "video")).toBe(true);
    expect(requiresTypeSwitchConfirm("text_transcript", "video")).toBe(true);
  });

  // Case 2: video / text_transcript interview receiving an audio file.
  it("warns before turning a video or transcript interview into audio", () => {
    expect(requiresTypeSwitchConfirm("video", "audio")).toBe(true);
    expect(requiresTypeSwitchConfirm("text_transcript", "audio")).toBe(true);
  });

  // Case 3: video / audio interview receiving a transcript file.
  it("warns before turning a video or audio interview into a transcript", () => {
    expect(requiresTypeSwitchConfirm("video", "text_transcript")).toBe(true);
    expect(requiresTypeSwitchConfirm("audio", "text_transcript")).toBe(true);
  });

  // Case 4: "I'll decide later" adopts the file's kind silently.
  it("does not warn for an undecided interview", () => {
    expect(requiresTypeSwitchConfirm("undecided", "video")).toBe(false);
    expect(requiresTypeSwitchConfirm(null, "audio")).toBe(false);
    expect(requiresTypeSwitchConfirm(undefined, "text_transcript")).toBe(false);
  });

  it("does not warn when the file matches the declared type", () => {
    expect(requiresTypeSwitchConfirm("audio", "audio")).toBe(false);
    expect(requiresTypeSwitchConfirm("video", "video")).toBe(false);
    expect(
      requiresTypeSwitchConfirm("text_transcript", "text_transcript"),
    ).toBe(false);
  });
});
