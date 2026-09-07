// @vitest-environment jsdom
//
// HRP-671: `credit_transactions.action` is a dotted code — `employee.create`,
// and `.refund` appended when a charge is given back. The HRP-653 catalog
// keys the halves separately, so the label is assembled segment by segment;
// a code the catalog never heard of must still read as words, not vanish.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import enMessages from "../../messages/en.json";
import { useBillingActionLabel } from "@/lib/billing-labels";

function Probe({ codes }: { codes: string[] }) {
  const label = useBillingActionLabel();
  return <ul>{codes.map((c) => <li key={c}>{label(c)}</li>)}</ul>;
}

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

function labelsFor(codes: string[]): string[] {
  act(() => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <Probe codes={codes} />
      </NextIntlClientProvider>,
    );
  });
  return Array.from(container.querySelectorAll("li")).map(
    (li) => li.textContent ?? "",
  );
}

describe("billing action labels", () => {
  it("joins the category and the action of a dotted code", () => {
    expect(labelsFor(["employee.create"])).toEqual(["Employees · Create"]);
  });

  it("keeps the refund suffix as its own segment", () => {
    expect(labelsFor(["employee.create.refund"])).toEqual([
      "Employees · Create · Refund",
    ]);
  });

  it("reads a dotless transaction code as an action", () => {
    // Written by the refill job and the top-up flow, never priced in
    // credits.yaml — the keys exist so they do not read as wire codes.
    expect(labelsFor(["monthly_refill", "purchase", "bonus_grant"])).toEqual([
      "Monthly Refill",
      "Purchase",
      "Bonus Grant",
    ]);
  });

  it("humanizes a code the catalog does not carry", () => {
    expect(labelsFor(["future_area.future_action"])).toEqual([
      "Future Area · Future Action",
    ]);
  });
});
