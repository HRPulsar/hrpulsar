// @vitest-environment jsdom
//
// HRP-925: the result page of the public process check. It polls the check
// while it runs (queue → phases of the progress bar), says what went wrong
// on error with a "try again" that starts a new check from the same input,
// says a dead link is dead, and renders a ready result from the frozen
// contract of backend/app/modules/public_check/schemas.py - with and without
// percentages, with and without money, and with the out-of-scope steps.

import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import { ApiError } from "@/lib/api";
import type { CheckRead, CheckResult, ResultStep } from "@/lib/api/public-check";

const getCheck = vi.fn();
const createCheck = vi.fn();
const push = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("@/lib/api/public-check", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/public-check")>()),
  getCheck,
  createCheck,
}));

const { CheckResultPage, MAX_POLL_FAILURES, POLL_MS } = await import(
  "@/components/public-check/check-result"
);
const { reasonKey, ResultView } = await import("@/components/public-check/result-view");

const t = enMessages.publicCheck;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
// jsdom has no layout: the error banner scrolls itself into view.
Element.prototype.scrollIntoView = vi.fn();

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.useFakeTimers();
  getCheck.mockReset();
  createCheck.mockReset();
  push.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

async function render() {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages} timeZone="UTC">
        <CheckResultPage
          token="tok-1"
          inputHref="/"
          resultBase="/r"
          registerHref="https://app.hrpulsar.com/register?utm_source=public_check"
          shareUrl="https://check.hrpulsar.com/r/tok-1"
        />
      </NextIntlClientProvider>,
    );
  });
}

async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

const byId = (id: string) => container.querySelector<HTMLElement>(`[data-testid="${id}"]`);

function check(over: Partial<CheckRead> = {}): CheckRead {
  return {
    status: "pending",
    phase: null,
    error_code: null,
    locale: "en",
    title: "Every month the accounting team closes the books.",
    description: "Every month the accounting team closes the books.",
    answers: { industry: "logistics", team_size: 4, frequency: "monthly", hourly_rate: 50, currency: "EUR" },
    created_at: "2026-10-02T10:00:00Z",
    expires_at: "2026-10-12T10:00:00Z",
    result: null,
    ...over,
  };
}

function step(position: number, over: Partial<ResultStep> = {}): ResultStep {
  return {
    position,
    title: `Step ${position}`,
    description: `What step ${position} does`,
    codes: ["P3"],
    hours_per_run: 2,
    runs_per_year: 12,
    hours_per_year: 24,
    reason: { mode: "automatable", codes: ["P3"], responsibility: "none", output_type: "draft" },
    ...over,
  };
}

function result(over: Partial<CheckResult> = {}): CheckResult {
  return {
    schema_version: 1,
    preliminary: true,
    catalog_version: "1.1",
    shares: { moves: 42.4, to_review: 31.6, stays: 26 },
    hours: { total: 96, moves: 40.7, to_review: 30.3, stays: 25, to_review_after: 15.2, freed: 55.8, unestimated: 0 },
    money: { total: 4800, moves: 2035, to_review: 1515, stays: 1250, to_review_after: 760, freed: 2790, currency: "EUR" },
    buckets: {
      moves: [step(1)],
      to_review: [
        step(2, {
          reason: { mode: "draft_then_review", codes: ["P5"], responsibility: "none", output_type: "draft" },
        }),
      ],
      stays: [
        step(4, {
          reason: { mode: "blocked_judgment", codes: ["P6"], responsibility: "none", output_type: "draft" },
        }),
      ],
    },
    out_of_scope: [
      step(3, {
        codes: ["B2"],
        hours_per_year: null,
        reason: { mode: "blocked_physical", codes: ["B2"], responsibility: "none", output_type: "draft" },
      }),
    ],
    ...over,
  };
}

describe("while the check runs", () => {
  it("walks the progress bar from the queue through the phases, then stops polling on ready", async () => {
    getCheck
      .mockResolvedValueOnce(check())
      .mockResolvedValueOnce(check({ status: "running", phase: "splitting" }))
      .mockResolvedValueOnce(check({ status: "running", phase: "classifying" }))
      .mockResolvedValueOnce(check({ status: "running", phase: "finishing" }))
      .mockResolvedValue(check({ status: "ready", result: result() }));

    await render();
    const bar = () => byId("check-progress-bar")!;
    expect(bar().getAttribute("role")).toBe("progressbar");
    expect(bar().dataset.phase).toBe("queued");
    expect(bar().getAttribute("aria-valuetext")).toBe(t.phaseQueued);
    const queued = Number(bar().getAttribute("aria-valuenow"));

    await tick(POLL_MS);
    expect(bar().dataset.phase).toBe("splitting");
    await tick(POLL_MS);
    expect(bar().dataset.phase).toBe("classifying");
    expect(bar().getAttribute("aria-valuetext")).toBe(t.phaseClassifying);
    const classifying = Number(bar().getAttribute("aria-valuenow"));
    expect(classifying).toBeGreaterThan(queued);
    expect(classifying).toBeLessThan(100);
    await tick(POLL_MS);
    expect(bar().dataset.phase).toBe("finishing");
    // HRP-928: nothing to share until the result is there.
    expect(byId("check-social")).toBeNull();

    await tick(POLL_MS);
    expect(byId("check-progress")).toBeNull();
    expect(byId("check-result")).not.toBeNull();
    expect(byId("check-social")).not.toBeNull();
    expect((byId("check-social-url") as HTMLInputElement).value).toBe(
      "https://check.hrpulsar.com/r/tok-1",
    );
    expect(getCheck).toHaveBeenCalledTimes(5);
    expect(getCheck).toHaveBeenCalledWith("tok-1");

    await tick(POLL_MS * 10);
    expect(getCheck).toHaveBeenCalledTimes(5);
  });

  it("keeps polling through a network blip instead of giving up", async () => {
    getCheck
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValue(check({ status: "running", phase: "splitting" }));

    await render();
    expect(byId("check-loading")!.textContent).toContain(t.reconnecting);

    await tick(POLL_MS * 2);
    expect(byId("check-progress-bar")!.dataset.phase).toBe("splitting");
  });
});

describe("a check that ended in error", () => {
  it("explains the engine's error code and tries again with the same input", async () => {
    const failed = check({
      status: "error",
      error_code: "overload",
      locale: "de",
      utm: { source: "linkedin", campaign: "launch" },
    });
    getCheck.mockResolvedValue(failed);
    createCheck.mockResolvedValue({ token: "tok-2", status: "pending", expires_at: null });

    await render();
    expect(byId("check-run-error")!.textContent).toContain(t.runErrorOverload);

    await act(async () => byId("check-btn-retry")!.click());
    // The campaign too (HRP-931): a retry must not turn a visit "direct".
    expect(createCheck).toHaveBeenCalledWith({
      description: failed.description,
      answers: failed.answers,
      locale: "de",
      utm: { source: "linkedin", campaign: "launch" },
    });
    expect(push).toHaveBeenCalledWith("/r/tok-2");
  });

  it("tries a dictated description again as dictated", async () => {
    getCheck.mockResolvedValue(check({ status: "error", error_code: "overload", dictated: true }));
    createCheck.mockResolvedValue({ token: "tok-2", status: "pending", expires_at: null });
    await render();
    await act(async () => byId("check-btn-retry")!.click());
    expect(createCheck).toHaveBeenCalledWith(expect.objectContaining({ dictated: true }));
  });

  it("falls back to a general message for a code it does not know", async () => {
    getCheck.mockResolvedValue(check({ status: "error", error_code: "parse_error" }));
    await render();
    expect(byId("check-run-error")!.textContent).toContain(t.runErrorGeneric);
  });

  it("shows the reason when the retry itself is refused", async () => {
    getCheck.mockResolvedValue(check({ status: "error", error_code: "service_error" }));
    createCheck.mockRejectedValue(
      new ApiError(429, "limit", "limit", "public_check_daily_limit"),
    );
    await render();
    await act(async () => byId("check-btn-retry")!.click());
    expect(byId("check-retry-error")!.textContent).toBe(t.errorDailyLimit);
    expect(push).not.toHaveBeenCalled();
  });
});

it("says an unknown or expired link is gone, with a way to start over", async () => {
  getCheck.mockRejectedValue(new ApiError(404, "nope", "nope", "public_check_not_found"));
  await render();
  expect(byId("check-not-found")!.textContent).toContain(t.notFoundTitle);
  expect(byId("check-link-new")!.getAttribute("href")).toBe("/");
  await tick(POLL_MS * 5);
  expect(getCheck).toHaveBeenCalledTimes(1);
});

describe("a ready result", () => {
  it("leads with the share an agent takes, lists every step with its reason, and prices the hours", async () => {
    getCheck.mockResolvedValue(check({ status: "ready", result: result() }));
    await render();

    const headline = byId("check-result-headline")!;
    expect(headline.dataset.share).toBe("42.4");
    expect(headline.textContent).toContain("42%");
    expect(headline.textContent).toContain(t.headlineText);
    expect(byId("check-share-to-review")!.dataset.share).toBe("31.6");
    expect(byId("check-result-preliminary")!.textContent).toBe(t.preliminary);

    // Hours and money per year, in the visitor's currency.
    expect(byId("check-figure-total")!.textContent).toContain("96 h");
    expect(byId("check-figure-total")!.textContent).toContain("€4,800");
    expect(byId("check-figure-freed")!.textContent).toContain("€2,790");

    // The three lists, each step with its reason and the capability names.
    expect(byId("check-list-moves")!.querySelector('[data-testid="check-step-1"]')).not.toBeNull();
    expect(byId("check-list-moves")!.textContent).toContain("€2,035");
    expect(byId("check-list-to-review")!.querySelector('[data-testid="check-step-2"]')).not.toBeNull();
    expect(byId("check-list-stays")!.querySelector('[data-testid="check-step-4"]')).not.toBeNull();
    expect(byId("check-step-1-reason")!.textContent).toContain(t.reasonAutomatable);
    expect(byId("check-step-1-reason")!.textContent).toContain(
      enMessages.reference.primitive.p3.label,
    );
    expect(byId("check-step-2-reason")!.textContent).toContain(t.reasonDraftThenReview);
    expect(byId("check-step-1")!.textContent).toContain("24 h a year");

    // Out-of-scope steps are kept, folded, and count in no figure.
    const outOfScope = byId("check-out-of-scope")!;
    expect(outOfScope.tagName).toBe("DETAILS");
    expect(outOfScope.hasAttribute("open")).toBe(false);
    expect(outOfScope.querySelector('[data-testid="check-step-3"]')!.textContent).toContain(
      t.stepNoEstimate,
    );
    expect(outOfScope.textContent).toContain(enMessages.reference.primitive.b2.label);

    expect(byId("check-cta-register")!.getAttribute("href")).toBe(
      "https://app.hrpulsar.com/register?utm_source=public_check",
    );
    expect(byId("check-result-expires")!.textContent).toContain("October 12, 2026");
    expect(byId("check-result-no-shares")).toBeNull();
    expect(byId("check-result-unestimated")).toBeNull();
  });

  it("leads with the lists and shows no percent or money when the engine gives none", async () => {
    getCheck.mockResolvedValue(
      check({
        status: "ready",
        expires_at: null,
        result: result({
          shares: null,
          money: null,
          out_of_scope: [],
          hours: { total: 24, moves: 24, to_review: 0, stays: 0, to_review_after: 0, freed: 24, unestimated: 2 },
        }),
      }),
    );
    await render();

    expect(byId("check-result-headline")).toBeNull();
    expect(byId("check-result-no-shares")!.textContent).toBe(t.noShares);
    expect(container.textContent).not.toContain("%");
    expect(container.textContent).not.toContain("€");
    expect(byId("check-figure-total")!.textContent).toContain("24 h");
    // The lists come before the figures when there is no headline.
    const order = [...container.querySelectorAll("[data-testid]")].map((el) => el.getAttribute("data-testid"));
    expect(order.indexOf("check-list-moves")).toBeLessThan(order.indexOf("check-result-figures"));
    expect(byId("check-result-unestimated")!.textContent).toContain("2 steps have no hour estimate");
    expect(byId("check-out-of-scope")).toBeNull();
    expect(byId("check-result-expires")).toBeNull();
  });
});

describe("the share buttons of a result", () => {
  // HRP-928 x HRP-926: "my checks" reads a saved check by its id - no link
  // token, nothing canonical to share - so it renders the view without one.
  it("show only with a canonical address to share", async () => {
    const ready = check({ status: "ready", result: result() });
    const view = (shareUrl?: string) => (
      <NextIntlClientProvider locale="en" messages={enMessages} timeZone="UTC">
        <ResultView check={ready} result={ready.result!} inputHref="/" registerHref="/register" shareUrl={shareUrl} />
      </NextIntlClientProvider>
    );
    await act(async () => root.render(view()));
    expect(byId("check-result")).not.toBeNull();
    expect(byId("check-social")).toBeNull();
    await act(async () => root.render(view("https://check.hrpulsar.com/r/tok-1")));
    expect((byId("check-social-url") as HTMLInputElement).value).toBe("https://check.hrpulsar.com/r/tok-1");
  });
});

describe("the reason sentence of a step", () => {
  const reason = (over: object) => ({
    mode: "review_required" as const,
    codes: [],
    responsibility: "none" as const,
    output_type: "draft" as const,
    ...over,
  });

  it("names what made a person review the step", () => {
    expect(reasonKey(reason({ responsibility: "regulatory" }))).toBe("reasonReviewRegulatory");
    expect(reasonKey(reason({ responsibility: "formal" }))).toBe("reasonReviewFormal");
    expect(reasonKey(reason({ output_type: "external_change" }))).toBe("reasonReviewExternal");
    expect(reasonKey(reason({}))).toBe("reasonReviewRequired");
  });

  it("has a sentence for every mode and for a step with no capability", () => {
    for (const mode of [
      "automatable",
      "draft_then_review",
      "blocked_judgment",
      "blocked_physical",
      null,
    ] as const) {
      expect(t).toHaveProperty(reasonKey(reason({ mode })));
    }
  });
});

describe("when polling keeps failing (review M1, M2)", () => {
  const blip = () => new TypeError("Failed to fetch");

  it("stops after the cap and says so; try again polls the same check again", async () => {
    getCheck.mockRejectedValue(blip());
    await render();
    for (let i = 1; i < MAX_POLL_FAILURES; i++) await tick(POLL_MS * 2);

    expect(getCheck).toHaveBeenCalledTimes(MAX_POLL_FAILURES);
    expect(byId("check-unavailable")!.textContent).toContain(t.unavailableTitle);
    expect(byId("check-unavailable")!.textContent).toContain(t.errorUnavailable);
    expect(byId("check-loading")).toBeNull();
    await tick(POLL_MS * 20);
    expect(getCheck).toHaveBeenCalledTimes(MAX_POLL_FAILURES);

    getCheck.mockReset().mockResolvedValue(check({ status: "running", phase: "classifying" }));
    await act(async () => byId("check-btn-repoll")!.click());
    expect(getCheck).toHaveBeenCalledWith("tok-1");
    expect(createCheck).not.toHaveBeenCalled();
    expect(byId("check-unavailable")).toBeNull();
    expect(byId("check-progress-bar")!.dataset.phase).toBe("classifying");
  });

  it("counts only failures in a row: a good poll starts the count over", async () => {
    for (let i = 1; i < MAX_POLL_FAILURES; i++) getCheck.mockRejectedValueOnce(blip());
    getCheck.mockResolvedValueOnce(check({ status: "running", phase: "splitting" }));
    getCheck.mockRejectedValue(blip());

    await render();
    for (let i = 1; i < MAX_POLL_FAILURES; i++) await tick(POLL_MS * 2);
    expect(byId("check-progress-bar")!.dataset.phase).toBe("splitting");

    await tick(POLL_MS);
    for (let i = 2; i < MAX_POLL_FAILURES; i++) await tick(POLL_MS * 2);
    expect(byId("check-unavailable")).toBeNull();
    expect(byId("check-progress")!.textContent).toContain(t.reconnecting);

    await tick(POLL_MS * 2);
    expect(byId("check-unavailable")).not.toBeNull();
  });

  it("does not hang on a ready check without a result", async () => {
    getCheck.mockResolvedValue(check({ status: "ready", result: null }));
    await render();
    for (let i = 1; i < MAX_POLL_FAILURES; i++) await tick(POLL_MS * 2);

    expect(byId("check-progress")).toBeNull();
    expect(byId("check-unavailable")).not.toBeNull();
    await tick(POLL_MS * 20);
    expect(getCheck).toHaveBeenCalledTimes(MAX_POLL_FAILURES);
  });

  it("keeps polling past a passing ready-without-result and shows the result", async () => {
    getCheck
      .mockResolvedValueOnce(check({ status: "ready", result: null }))
      .mockResolvedValue(check({ status: "ready", result: result() }));
    await render();
    await tick(POLL_MS * 2);
    expect(byId("check-result")).not.toBeNull();
  });
});

it("announces the first load to screen readers (review M7)", async () => {
  getCheck.mockReturnValue(new Promise(() => {}));
  await render();
  const loading = byId("check-loading")!;
  expect(loading.getAttribute("role")).toBe("status");
  expect(loading.getAttribute("aria-busy")).toBe("true");
  expect(loading.querySelector(".sr-only")!.textContent).toBe(t.loadingLabel);
});

describe("the owner key in this browser", () => {
  // Review 2.2 D6: the keys must not pile up in localStorage for ever.
  const KEY = "public-check:owner:tok-1";
  const TERMS = "public-check:owner-terms";

  beforeEach(() => localStorage.clear());

  it("is forgotten when the link is dead", async () => {
    localStorage.setItem(KEY, "own-1");
    getCheck.mockRejectedValue(new ApiError(404, "not found", "not found", "public_check_not_found"));
    await render();
    expect(byId("check-not-found")).not.toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("is forgotten once the check is kept without a term, kept while it has one", async () => {
    const { rememberOwnerKey } = await import("@/components/public-check/owner-key");
    rememberOwnerKey("tok-1", "own-1", "2026-10-12T10:00:00Z");
    getCheck.mockResolvedValue(check({ status: "running", phase: "splitting" }));
    await render();
    expect(localStorage.getItem(KEY)).toBe("own-1");

    getCheck.mockResolvedValue(check({ status: "running", phase: "splitting", expires_at: null }));
    await tick(POLL_MS);
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(JSON.parse(localStorage.getItem(TERMS)!)).toEqual({});
  });

  it("of a check past its term is swept when the next check is remembered", async () => {
    const { rememberOwnerKey, ownerKeyFor } = await import("@/components/public-check/owner-key");
    vi.setSystemTime(new Date("2026-10-01T10:00:00Z"));
    rememberOwnerKey("old", "own-old", "2026-10-08T10:00:00Z");
    rememberOwnerKey("live", "own-live", "2026-10-20T10:00:00Z");
    vi.setSystemTime(new Date("2026-10-10T10:00:00Z"));
    rememberOwnerKey("new", "own-new", "2026-10-17T10:00:00Z");
    expect(ownerKeyFor("old")).toBeNull();
    expect(ownerKeyFor("live")).toBe("own-live");
    expect(ownerKeyFor("new")).toBe("own-new");
    expect(Object.keys(JSON.parse(localStorage.getItem(TERMS)!)).sort()).toEqual(["live", "new"]);
  });
});
