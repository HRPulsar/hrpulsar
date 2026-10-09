// @vitest-environment jsdom
//
// HRP-1031: "Transcribe and run AI analysis automatically after upload" keeps
// the recruiter's choice for this candidate on this vacancy across a reload;
// another candidate-vacancy starts from the default (on).

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useAutoProcess } from "@/components/recruitment/interview-upload-zone";

let container: HTMLDivElement;
let root: Root;
let current: [boolean, (on: boolean) => void];

function Probe({
  cvId,
  report,
}: {
  cvId?: string;
  report: (value: [boolean, (on: boolean) => void]) => void;
}) {
  report(useAutoProcess(cvId));
  return null;
}

async function mount(cvId?: string) {
  await act(async () =>
    root.render(<Probe cvId={cvId} report={(v) => (current = v)} />),
  );
}

beforeEach(() => {
  window.localStorage.clear();
  container = document.createElement("div");
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
});

describe("auto-process switch per candidate x vacancy (HRP-1031)", () => {
  it("is on by default", async () => {
    await mount("cv-1");
    expect(current[0]).toBe(true);
  });

  it("stays off after a reload, for that candidate-vacancy only", async () => {
    await mount("cv-1");
    await act(async () => current[1](false));
    expect(current[0]).toBe(false);
    // A reload: a fresh tree with no state of its own.
    act(() => root.unmount());
    root = createRoot(container);
    await mount("cv-1");
    expect(current[0]).toBe(false);
    await mount("cv-2");
    expect(current[0]).toBe(true);
    await mount("cv-1");
    await act(async () => current[1](true));
    act(() => root.unmount());
    root = createRoot(container);
    await mount("cv-1");
    expect(current[0]).toBe(true);
  });

  it("still toggles without a candidate-vacancy, keeping nothing", async () => {
    await mount(undefined);
    await act(async () => current[1](false));
    expect(current[0]).toBe(false);
    expect(window.localStorage.length).toBe(0);
  });
});
