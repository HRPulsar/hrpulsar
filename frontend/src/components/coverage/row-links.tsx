"use client";

// HRP-864: what a coverage row lets the reader follow - a person's name to
// the employee card, a step title in a summary bucket to the step's row, an
// agent type to what an agent of that type does, a handed-over gap to its
// vacancy (HRP-801).

import type { ReactNode } from "react";
import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { EmployeeName } from "@/components/employees/employee-name";
import { useTranslations } from "next-intl";
import { usePermissions } from "@/hooks/use-permissions";
import type { GapHireNeed } from "@/lib/api/work";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

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

/** A person's name as a link to the employee card where the reader may open
 * it (HRP-829 REDO, `EmployeeName`) - a colleague outside the reader's HR
 * scope opens as the directory card (HRP-623) - and plain text otherwise. */
export function PersonLink({
  person,
  testId,
}: {
  person: { employee_id?: string | null; name: string };
  testId: string;
}) {
  return (
    <EmployeeName
      employeeId={person.employee_id}
      linkClassName="text-foreground underline-offset-4 hover:underline"
      testId={testId}
    >
      {person.name}
    </EmployeeName>
  );
}

/** HRP-1197: the rest of a step's people behind "+N" - a click lists them,
 * each linked the way `PersonLink` links one. Nothing when nobody is left. */
export function MorePeople({
  people,
  testId,
}: {
  people: { employee_id: string; name: string }[];
  testId: string;
}) {
  const t = useTranslations("coverage");
  if (people.length === 0) return null;
  return (
    <Popover>
      <PopoverTrigger
        className="rounded-sm underline decoration-dotted underline-offset-4 transition-colors hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={t("morePeopleAria", { count: people.length })}
        data-testid={testId}
      >
        {t("morePeople", { count: people.length })}
      </PopoverTrigger>
      <PopoverContent
        align="start"
        sideOffset={6}
        className="w-64 max-w-[90vw] rounded-md p-3 text-sm"
        data-testid={`${testId}-popover`}
      >
        <ul className="space-y-1">
          {people.map((person) => (
            <li key={person.employee_id}>
              <PersonLink person={person} testId={`${testId}-${person.employee_id}`} />
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
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
    <Popover>
      <PopoverTrigger
        className="rounded-sm underline decoration-dotted underline-offset-4 transition-colors hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        data-testid={testId}
      >
        {label}
      </PopoverTrigger>
      <PopoverContent
        align="start"
        sideOffset={6}
        className="w-[360px] max-w-[90vw] rounded-md p-4 text-sm"
        data-testid={`${testId}-popover`}
      >
        <p className="font-semibold">{label}</p>
        <p className="mt-1 text-muted-foreground">{tRef(key)}</p>
      </PopoverContent>
    </Popover>
  );
}

/** HRP-801: where a gap was handed to - the talent-market card "look inside
 * first" opened (QA 12.11) or a vacancy's twin, the Recruitment draft
 * otherwise, whichever of the two the reader may open; nothing when neither. */
export function VacancyLink({
  need,
  label,
  testId,
}: {
  need: GapHireNeed;
  label: string;
  testId: string;
}) {
  const { canViewSection } = usePermissions();
  const href =
    need.talent_card_id && canViewSection("talent-market")
      ? `/talent-market/${need.talent_card_id}`
      : need.vacancy_id && canViewSection("recruitment")
        ? `/recruitment/requisitions/${need.vacancy_id}`
        : null;
  if (!href) return null;
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline"
      data-testid={testId}
    >
      <ExternalLink className="size-3.5" />
      {label}
    </Link>
  );
}
