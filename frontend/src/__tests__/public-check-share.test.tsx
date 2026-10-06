// @vitest-environment jsdom
//
// HRP-928: sharing a ready result of the public check - LinkedIn and X by
// their plain share URLs, the link copied with the Clipboard API or, where
// there is none, the old way - and the text "AI takes N of my M steps",
// counted by steps (a check may have no shares).

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import { ShareButtons } from "@/components/public-check/share-buttons";
import type { CheckResult, ResultStep } from "@/lib/api/public-check";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// The server's canonical address; the page itself is open on the app host.
const CANONICAL = "https://check.hrpulsar.com/r/tok-1";

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  window.history.pushState({}, "", "/check/r/tok-1?utm_source=linkedin");
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

const byId = (id: string) => container.querySelector<HTMLElement>(`[data-testid="${id}"]`);

function step(position: number): ResultStep {
  return {
    position,
    title: `Step ${position}`,
    description: null,
    codes: ["P3"],
    hours_per_run: null,
    runs_per_year: null,
    hours_per_year: null,
    reason: { mode: "automatable", codes: ["P3"], responsibility: "none", output_type: "draft" },
  };
}

function result(moves: number, toReview: number, stays: number, outOfScope = 0): CheckResult {
  let n = 0;
  const steps = (count: number) => Array.from({ length: count }, () => step(++n));
  return {
    schema_version: 1,
    preliminary: true,
    catalog_version: "v1.1",
    shares: null,
    hours: { total: 0, moves: 0, to_review: 0, stays: 0, to_review_after: 0, freed: 0, unestimated: 0 },
    money: null,
    buckets: { moves: steps(moves), to_review: steps(toReview), stays: steps(stays) },
    out_of_scope: steps(outOfScope),
  };
}

async function render(res: CheckResult, title = "Month-end close") {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages} timeZone="UTC">
        <ShareButtons url={CANONICAL} result={res} title={title} />
      </NextIntlClientProvider>,
    );
  });
}

describe("the share buttons", () => {
  it("share the canonical link, not the address bar: LinkedIn by URL, X with the headline", async () => {
    // Two of five steps in scope go to an agent; the out-of-scope one counts in neither.
    await render(result(2, 2, 1, 1));

    const linkedin = new URL(byId("check-social-linkedin")!.getAttribute("href")!);
    expect(linkedin.origin + linkedin.pathname).toBe("https://www.linkedin.com/sharing/share-offsite/");
    expect(linkedin.searchParams.get("url")).toBe(CANONICAL);

    const x = new URL(byId("check-social-x")!.getAttribute("href")!);
    expect(x.origin + x.pathname).toBe("https://x.com/intent/tweet");
    expect(x.searchParams.get("text")).toBe("AI takes 2 of my 5 steps in “Month-end close”");
    expect(x.searchParams.get("url")).toBe(CANONICAL);

    // Plain links, no script of a network; they open apart from the result.
    expect(byId("check-social-x")!.getAttribute("target")).toBe("_blank");
    expect(byId("check-social-x")!.getAttribute("rel")).toContain("noopener");
    expect(container.querySelector("script")).toBeNull();
    expect((byId("check-social-url") as HTMLInputElement).value).toBe(CANONICAL);
  });

  it("says one step in the singular", async () => {
    await render(result(1, 0, 0));
    const x = new URL(byId("check-social-x")!.getAttribute("href")!);
    expect(x.searchParams.get("text")).toBe("AI takes 1 of my 1 step in “Month-end close”");
  });

  it("falls back to the service's line when no step is in scope", async () => {
    await render(result(0, 0, 0, 3));
    const x = new URL(byId("check-social-x")!.getAttribute("href")!);
    expect(x.searchParams.get("text")).toBe(enMessages.publicCheck.metaTitle);
  });

  it("copies the link with the Clipboard API and says so", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    await render(result(2, 1, 1));

    expect(byId("check-social-copy")!.textContent).toBe(enMessages.publicCheck.shareCopy);
    await act(async () => byId("check-social-copy")!.click());
    expect(writeText).toHaveBeenCalledWith(CANONICAL);
    expect(byId("check-social-copy")!.textContent).toBe(enMessages.publicCheck.shareCopied);
    expect(container.querySelector('[aria-live="polite"]')!.textContent).toBe(
      enMessages.publicCheck.shareCopied,
    );
  });

  it("copies the selected field the old way without a Clipboard API", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    const execCommand = vi.fn().mockReturnValue(true);
    document.execCommand = execCommand;
    await render(result(2, 1, 1));

    await act(async () => byId("check-social-copy")!.click());
    expect(execCommand).toHaveBeenCalledWith("copy");
    const field = byId("check-social-url") as HTMLInputElement;
    expect(document.activeElement === field || field.selectionEnd === CANONICAL.length).toBe(true);
    expect(byId("check-social-copy")!.textContent).toBe(enMessages.publicCheck.shareCopied);
  });

  it("claims no copy when both ways fail - the field stays selected for the visitor", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) } });
    document.execCommand = vi.fn().mockReturnValue(false);
    await render(result(2, 1, 1));

    await act(async () => byId("check-social-copy")!.click());
    expect(byId("check-social-copy")!.textContent).toBe(enMessages.publicCheck.shareCopy);
  });
});
