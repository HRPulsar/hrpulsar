// @vitest-environment jsdom
//
// HRP-721 REDO: the legend is the one place the answer options are
// explained, in the questionnaire, the question preview and the scale
// preview alike. No description on any option -> no legend; at least one
// -> every option listed, the ones without a description saying so.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { ScaleLegend } from "@/components/assessment/scale-legend";
import type { AnswerOption } from "@/lib/types";

import enMessages from "../../messages/en.json";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Custom codes: a seeded code would pull its description from the catalog.
const option = (code: string, sort: number, description: string | null): AnswerOption => ({
  id: `id-${code}`,
  title: `Title ${code}`,
  code,
  weight: sort,
  description,
  sort_index: sort,
  is_neutral: false,
});

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function render(options: AnswerOption[]): HTMLDivElement {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root!.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <ScaleLegend options={options} />
      </NextIntlClientProvider>,
    );
  });
  return container;
}

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

describe("ScaleLegend", () => {
  it("is not shown when no option has a description", () => {
    const el = render([option("c1", 1, null), option("c2", 2, "  ")]);
    expect(el.querySelector('[data-testid="assessment-scale-legend"]')).toBeNull();
  });

  it("lists every option once one has a description", () => {
    const el = render([option("c2", 2, null), option("c1", 1, "Clear and complete")]);
    const legend = el.querySelector('[data-testid="assessment-scale-legend"]');
    expect(legend?.querySelector("summary")?.textContent).toBe("What the answer options mean");
    const rows = Array.from(legend!.querySelectorAll("dl > div")).map((r) => r.textContent);
    expect(rows).toEqual(["Title c1Clear and complete", "Title c2Not specified"]);
  });
});
