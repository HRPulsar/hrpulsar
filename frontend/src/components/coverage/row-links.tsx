"use client";

// HRP-864: what a coverage row lets the reader follow - a person's name to
// the employee card, a step title in a summary bucket to the step's row, an
// agent type to what an agent of that type does.

import type { ReactNode } from "react";
import Link from "next/link";
import * as Popover from "@radix-ui/react-popover";
import { useTranslations } from "next-intl";

// A character no name or label contains, to find where a sentence puts it.
const MARK = "";

/** A translated sentence with a node where its argument goes. The messages
 * keep their plain `{name}` / `{pack}` argument - their wording is not this
 * component's to change - so the node lands where the marker does, in any
 * locale's word order. */
export function around(sentence: (arg: string) => string, node: ReactNode): ReactNode {
  const [before, after = ""] = sentence(MARK).split(MARK);
  return (
    <>
      {before}
      {node}
      {after}
    </>
  );
}

/** A person's name as a link to the employee card. No access check here: the
 * card answers for itself - a colleague outside the reader's HR scope opens
 * as the directory card (HRP-623), anyone else as "not found". A person
 * without an id stays plain text. */
export function PersonLink({
  person,
  testId,
}: {
  person: { employee_id?: string | null; name: string };
  testId: string;
}) {
  if (!person.employee_id) return <>{person.name}</>;
  return (
    <Link
      href={`/employees/${person.employee_id}`}
      className="text-foreground underline-offset-4 hover:underline"
      data-testid={testId}
    >
      {person.name}
    </Link>
  );
}

export const stepRowId = (stepId: string) => `coverage-step-${stepId}`;

/** A step title in a summary bucket: scrolls to the step's row on the same
 * tab and focuses it, so the row is marked until the reader moves on. No
 * routing and no hash left in the URL. */
export function StepJump({ stepId, children, testId }: { stepId: string; children: ReactNode; testId: string }) {
  return (
    <button
      type="button"
      className="block w-full truncate text-left underline-offset-4 hover:underline focus-visible:underline focus-visible:outline-none"
      onClick={() => {
        const row = document.getElementById(stepRowId(stepId));
        row?.scrollIntoView({ behavior: "smooth", block: "center" });
        row?.focus({ preventScroll: true });
      }}
      data-testid={testId}
    >
      {children}
    </button>
  );
}

/** An agent type's label; a click says what an agent of this type does. A
 * pack the interface catalog does not describe - the tenant's own - is plain
 * text: no description, no popover, never a raw message path. */
export function PackChip({ code, label, testId }: { code: string | null; label: string; testId: string }) {
  const tRef = useTranslations("reference");
  const key = `agentPack.${code}.description`;
  if (!code || !tRef.has(key)) return <>{label}</>;
  return (
    <Popover.Root>
      <Popover.Trigger
        className="rounded-sm underline decoration-dotted underline-offset-4 transition-colors hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        data-testid={testId}
      >
        {label}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={6}
          className="z-50 w-[360px] max-w-[90vw] rounded-md border bg-popover p-4 text-sm text-popover-foreground shadow-md outline-none"
          data-testid={`${testId}-popover`}
        >
          <p className="font-semibold">{label}</p>
          <p className="mt-1 text-muted-foreground">{tRef(key)}</p>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
