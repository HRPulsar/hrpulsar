// @vitest-environment jsdom
//
// HRP-485 REDO tasks 2-3 — how the two "Add question" dialogs open.
//
// Both opened with their first field focused, and the blue focus ring on
// an untouched form reads as a validation error. The competency dialog
// also opened at the sm width: its own ``max-w-3xl`` is unprefixed and
// loses to DialogContent's base ``sm:max-w-sm`` at every width above the
// breakpoint, so Search / Expand all / Collapse all wrapped onto two rows.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import enMessages from "../../messages/en.json";
import { AddFromCompetencyDialog } from "@/components/recruitment/add-from-competency-dialog";
import { AddQuestionDialog } from "@/components/recruitment/interview-question-sets";
import type { CompetenceItem } from "@/lib/types";

const COMPETENCES: CompetenceItem[] = [
  {
    id: "c-1",
    group: "Analytics",
    subgroup: "Quality",
    name: "Attention to detail",
    criticality: "critical",
    why_important: "Mistakes are expensive here.",
    how_manifests: "",
    indicator_question: "Tell me about a costly mistake you caught.",
    good_answer: "",
    acceptable_answer: "",
    poor_answer: "",
    indicators: ["Double-checks numbers"],
  },
];

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

function tree(isOpen: boolean) {
  return (
    <NextIntlClientProvider locale="en" messages={enMessages}>
      <AddFromCompetencyDialog
        open={isOpen}
        onOpenChange={() => {}}
        competences={COMPETENCES}
        onSubmit={() => {}}
      />
    </NextIntlClientProvider>
  );
}

// Mount closed and then open: the focus manager only runs on the
// transition, so a dialog rendered open from the start never moves
// focus at all and would make the assertions below vacuous.
async function open() {
  await act(async () => {
    root.render(tree(false));
  });
  await act(async () => {
    root.render(tree(true));
  });
  await settleFocus();
}

// The focus manager moves focus off the render pass, and how many
// macrotasks that takes is not ours to know — wait for focus to leave
// <body> rather than for a fixed number of ticks, or the assertions
// that read document.activeElement pass vacuously on a slow run.
async function settleFocus() {
  for (let i = 0; i < 50 && document.activeElement === document.body; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1));
    });
  }
}

const popup = () =>
  document.querySelector<HTMLElement>(
    '[data-testid="recruitment-interview-questions-competency-dialog"]',
  );
const search = () =>
  document.querySelector<HTMLElement>(
    '[data-testid="recruitment-interview-questions-competency-search"]',
  );

describe("Add question - Select competences dialog (HRP-485)", () => {
  it("does not focus the search field on open", async () => {
    await open();
    expect(search()).not.toBeNull();
    expect(document.activeElement).not.toBe(search());
  });

  it("keeps focus inside the dialog so it stays keyboard-usable", async () => {
    await open();
    const el = popup();
    expect(el).not.toBeNull();
    expect(el?.contains(document.activeElement)).toBe(true);
  });

  it("widens itself with a breakpoint-prefixed max width", async () => {
    // Unprefixed ``max-w-3xl`` never wins against the base
    // ``sm:max-w-sm`` — the toolbar wrapped because of exactly that.
    await open();
    const cls = popup()?.className ?? "";
    expect(cls).toContain("sm:max-w-3xl");
    expect(cls).not.toMatch(/(^|\s)max-w-3xl(\s|$)/);
  });
});

describe("Add custom question dialog (HRP-485)", () => {
  it("is titled 'Add question', not 'Add a question'", () => {
    expect(enMessages.recruitment.questionSetsAddDialogTitle).toBe(
      "Add question",
    );
  });

  it("does not focus the question textarea on open", async () => {
    const manual = (isOpen: boolean) => (
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <AddQuestionDialog
          open={isOpen}
          onOpenChange={() => {}}
          onSubmit={() => {}}
        />
      </NextIntlClientProvider>
    );
    await act(async () => {
      root.render(manual(false));
    });
    await act(async () => {
      root.render(manual(true));
    });
    await settleFocus();

    const textarea = document.querySelector(
      '[data-testid="recruitment-interview-questions-add-text"]',
    );
    const popup = document.querySelector(
      '[data-testid="recruitment-interview-questions-add-dialog"]',
    );
    expect(textarea).not.toBeNull();
    expect(document.activeElement).not.toBe(textarea);
    expect(popup?.contains(document.activeElement)).toBe(true);
  });
});
