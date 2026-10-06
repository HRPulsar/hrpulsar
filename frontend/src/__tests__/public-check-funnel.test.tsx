// @vitest-environment jsdom
//
// HRP-931: the funnel beacons of the public check pages. The input page
// says "opened" once per visit and "started" once, at the first text in
// the field - never again on a re-render or StrictMode's second effect run;
// the share buttons say "shared" once per result page, with the check's
// campaign.

import { NextIntlClientProvider } from "next-intl";
import { StrictMode, act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { CheckResult } from "@/lib/api/public-check";

const { trackEvent } = vi.hoisted(() => ({ trackEvent: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
// Dictation (HRP-947) without a microphone: the button hands over its text.
vi.mock("@/components/public-check/dictate-button", () => ({
  DictateButton: ({ onText }: { onText: (text: string) => void }) => (
    <button type="button" data-testid="fake-dictate" onClick={() => onText("We close the books")} />
  ),
}));
vi.mock("@/lib/api/public-check", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/public-check")>()),
  trackEvent,
}));

const { CheckForm } = await import("@/components/public-check/check-form");
const { ShareButtons } = await import("@/components/public-check/share-buttons");

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  trackEvent.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

const byId = <T extends HTMLElement = HTMLElement>(id: string) =>
  container.querySelector<T>(`[data-testid="${id}"]`)!;

const UTM = { source: "linkedin", campaign: "launch" };

async function renderForm() {
  await act(async () => {
    root.render(
      <StrictMode>
        <NextIntlClientProvider locale="en" messages={enMessages} timeZone="UTC">
          <CheckForm resultBase="/r" utm={UTM} />
        </NextIntlClientProvider>
      </StrictMode>,
    );
  });
}

async function type(value: string) {
  const el = byId<HTMLTextAreaElement>("check-input-description");
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
  await act(async () => {
    setter.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

const calls = (event: string) => trackEvent.mock.calls.filter(([e]) => e === event);

describe("the input page", () => {
  it("is opened once, whatever re-renders it", async () => {
    await renderForm();
    await renderForm();
    await type("We close the books");
    expect(calls("opened")).toEqual([["opened", UTM]]);
  });

  it("is started once, at the first text in the field", async () => {
    await renderForm();
    expect(calls("started")).toEqual([]);
    await type("W");
    await type("We close");
    await type("");
    await type("Again");
    expect(calls("started")).toEqual([["started", UTM]]);
  });

  it("counts dictated text as a start", async () => {
    await renderForm();
    await act(async () => byId("fake-dictate").click());
    expect(calls("started")).toEqual([["started", UTM]]);
  });

  it("counts an example as a start", async () => {
    await renderForm();
    await act(async () => byId("check-example-hiring").click());
    expect(calls("started")).toEqual([["started", UTM]]);
  });
});

const RESULT: CheckResult = {
  schema_version: 1,
  preliminary: true,
  catalog_version: "v1.1",
  shares: null,
  hours: { total: 0, moves: 0, to_review: 0, stays: 0, to_review_after: 0, freed: 0, unestimated: 0 },
  money: null,
  buckets: { moves: [], to_review: [], stays: [] },
  out_of_scope: [],
};

describe("the share buttons", () => {
  it("say shared once per result page, with the check's campaign", async () => {
    vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    await act(async () => {
      root.render(
        <NextIntlClientProvider locale="en" messages={enMessages} timeZone="UTC">
          <ShareButtons url="https://check.hrpulsar.com/r/tok-1" result={RESULT} title="Close" utm={UTM} />
        </NextIntlClientProvider>,
      );
    });
    expect(trackEvent).not.toHaveBeenCalled();
    for (const id of ["check-social-linkedin", "check-social-x", "check-social-copy"]) {
      await act(async () => {
        byId(id).dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      });
    }
    expect(trackEvent.mock.calls).toEqual([["shared", UTM]]);
  });

  it("counts a copy only once the link is on the clipboard", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    document.execCommand = vi.fn().mockReturnValue(false);
    await act(async () => {
      root.render(
        <NextIntlClientProvider locale="en" messages={enMessages} timeZone="UTC">
          <ShareButtons url="https://check.hrpulsar.com/r/tok-1" result={RESULT} title="Close" utm={UTM} />
        </NextIntlClientProvider>,
      );
    });
    await act(async () => byId("check-social-copy").click());
    expect(trackEvent).not.toHaveBeenCalled();

    writeText.mockResolvedValue(undefined);
    await act(async () => byId("check-social-copy").click());
    expect(trackEvent.mock.calls).toEqual([["shared", UTM]]);
  });
});
