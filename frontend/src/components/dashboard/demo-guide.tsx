"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { CheckCircle2, Compass, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { useAuth } from "@/context/auth-context";
import { MUTATION_EVENT, type MutationEventDetail } from "@/lib/api";
import type { FeedbackContext } from "@/lib/api/feedback";
import { chooseDemoGuide, type DemoGuidePath } from "@/lib/demo";
import { matchMoment } from "@/components/dashboard/demo-feedback-popup";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/** The sandbox's start route, per tenant: the pick, the step reached,
 * the pages it happens on, and whether it was closed. No entry means
 * "Where to start" has not been answered yet. */
const STORAGE_PREFIX = "demo_guide:";

/** How long the finished route's "Done" stays before the strip goes. */
const DONE_SHOWN_MS = 6_000;

/** How long a pick waits for its answer before it starts from the list:
 * the window has no other way out while it waits. */
const PICK_WAIT_MS = 5_000;

/** Marks the button the current step asks for; the ring is in globals.css. */
const TARGET_ATTR = "data-demo-guide-target";

type Route = Exclude<DemoGuidePath, "skip">;

type GuideState = {
  path: DemoGuidePath;
  step: number;
  /** The page the route happens on: its anchor (the completed assessment,
   * the process with no steps), or what the leading "open" step reached. */
  back: string | null;
  /** No anchor at the pick: the route starts with an "open" step from the
   * list. Decided once, so the steps never change under the visitor - and
   * a route stored by 2.6.0 has no such field. */
  lead: boolean;
  /** Coverage: a process where the seed guarantees a step nobody does. */
  gap: string | null;
  closed?: boolean;
};

/** A step is something the visitor does (HRP-1178): getting to its page
 * is the pick's and "Go"'s job, never a step of its own - except the
 * leading "open" of a route that has no anchor. */
type Step = {
  /** Catalog key; `leadText` instead on a route that had to lead. */
  text: string;
  leadText?: string;
  /** Where "Go" leads from the current page: to the step's button. */
  href: (state: GuideState, pathname: string) => string | null;
  /** `data-testid` of the buttons to press, the furthest along first:
   * the first one on screen gets the ring, and "Go" has nowhere to lead. */
  targets?: string[];
  /** The targets count on the step's own page only. */
  here?: boolean;
  /** Pressing the target completes the step. */
  click?: boolean;
  /** Reaching this page completes the step. */
  at?: RegExp;
  /** One of these value moments (the demo card's) completes the step. */
  on?: FeedbackContext[];
};

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
/** A page of the app — `:id` is a record id, so `/coverage/new` is not
 * a process. */
const page = (pattern: string) => new RegExp(`^${pattern.replace(":id", UUID)}$`);
const toBack = (s: GuideState) => s.back;
const LIST: Record<Route, string> = {
  coverage: "/coverage",
  pdp: "/assessments",
  assessment: "/assessments",
};

/** HRP-1159: three five-minute routes, each ending on a create — the
 * moment the demo card asks about (HRP-1158), so the strip only says
 * "Done" and the card does the rest. */
const ROUTES: Record<Route, Step[]> = {
  coverage: [
    {
      text: "demoGuideCoverageGenerate",
      leadText: "demoGuideCoverageRegenerate",
      href: toBack,
      // On another process the button reads "Regenerate steps".
      here: true,
      targets: ["coverage-btn-apply-generation", "coverage-btn-generate"],
      on: ["decomposition_applied"],
    },
    {
      text: "demoGuideCoverageHireNeed",
      // A fresh breakdown may leave no step without an owner: "Go" leads
      // to a process that has one, and a hire need opened anywhere counts.
      href: (s) => s.gap ?? s.back,
      targets: ["coverage-btn-hire-submit", "coverage-gap-btn-hire-need"],
      on: ["hire_need_created"],
    },
  ],
  pdp: [
    {
      text: "demoGuidePdpGrowth",
      href: toBack,
      targets: ["assessment-create-plan"],
      // Not "reached /development": the menu leads there too.
      click: true,
    },
    {
      text: "demoGuidePdpCreate",
      href: toBack,
      targets: ["development-create-submit", "assessment-create-plan"],
      on: ["pdp_from_assessment", "pdp_created"],
    },
  ],
  assessment: [
    {
      text: "demoGuideAssessmentResults",
      // "Go" is "next" on the results, and the way back to them elsewhere.
      href: (s, at) => (s.back && s.back !== at ? s.back : "/assessments"),
      at: page("/assessments"),
    },
    {
      text: "demoGuideAssessmentNew",
      href: () => "/assessments",
      targets: [
        "assessments-modal-create-btn-submit",
        "assessments-modal-mode-btn-single",
        "assessments-btn-create",
      ],
      on: ["assessment_created"],
    },
  ],
};

/** The "open" step of a route picked with no anchor - a sandbox seeded
 * before 2.6.1, or one whose anchor is used up. */
const LEAD: Record<Route, Step> = {
  coverage: {
    text: "demoGuideCoverageOpen",
    href: () => "/coverage",
    at: page("/coverage/:id"),
  },
  pdp: {
    text: "demoGuidePdpOpenAny",
    href: () => "/assessments",
    at: page("/assessments/:id"),
  },
  assessment: {
    text: "demoGuideAssessmentOpenAny",
    href: () => "/assessments",
    at: page("/assessments/:id"),
  },
};

function stepsOf(state: GuideState): Step[] {
  if (state.path === "skip") return [];
  const steps = ROUTES[state.path];
  return state.lead ? [LEAD[state.path], ...steps] : steps;
}

const ROUTE_COPY: Record<Route, { title: string; hint: string }> = {
  coverage: { title: "demoGuideRouteCoverage", hint: "demoGuideRouteCoverageHint" },
  pdp: { title: "demoGuideRoutePdp", hint: "demoGuideRoutePdpHint" },
  assessment: {
    title: "demoGuideRouteAssessment",
    hint: "demoGuideRouteAssessmentHint",
  },
};

/** Moves the route on: a value moment completes its step — or a later
 * one, when the visitor got ahead of the strip — and then every page step
 * the current page already satisfies. */
export function advance(
  state: GuideState,
  pathname: string,
  moment: FeedbackContext | null = null,
): GuideState {
  if (state.path === "skip" || state.closed) return state;
  const steps = stepsOf(state);
  let { step, back } = state;
  if (moment) {
    for (let i = steps.length - 1; i >= step; i--) {
      if (steps[i].on?.includes(moment)) {
        step = i + 1;
        break;
      }
    }
  }
  while (step < steps.length && steps[step].at?.test(pathname)) {
    if (state.lead && step === 0) back = pathname;
    step += 1;
  }
  return step === state.step ? state : { ...state, step, back };
}

// ponytail: one observer on the whole page, so every DOM change re-runs a
// few querySelector calls while a step has a button to find. The button
// may come late (a list loading, a tab not opened yet, a dialog); if this
// ever shows in a profile, observe the page's <main> only.
function watchPage(onChange: () => void) {
  const seen = new MutationObserver(onChange);
  seen.observe(document.body, { childList: true, subtree: true });
  return () => seen.disconnect();
}
const watchNothing = () => () => {};

function findTarget(ids: string[] | null | undefined): HTMLElement | null {
  for (const id of ids ?? []) {
    const el = document.querySelector<HTMLElement>(`[data-testid="${id}"]`);
    if (el) return el;
  }
  return null;
}

// Storage can be off (private mode): no stored route asks again, and a
// route that cannot be written lives as long as the page.
function readGuide(key: string): GuideState | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const state = JSON.parse(raw) as GuideState;
    // A route stored by 2.6.0 walked other steps: it counts as closed,
    // and "Where to start" stays answered.
    return typeof state.lead === "boolean" ? state : { ...state, closed: true };
  } catch {
    return null;
  }
}

function writeGuide(key: string, state: GuideState) {
  try {
    localStorage.setItem(key, JSON.stringify(state));
  } catch {
    // See above.
  }
}

/** "Where to start" and the route strip of a demo sandbox (HRP-1159).
 * The admin persona only: the employee persona is a read-only view.
 * Renders nothing outside a demo — `tenant_is_demo` is never set on a
 * community build. */
export function DemoGuide() {
  const { user } = useAuth();
  if (!user?.tenant_is_demo || user.demo_persona !== "admin") return null;
  return <Guide key={user.tenant_id} storageKey={`${STORAGE_PREFIX}${user.tenant_id}`} />;
}

function Guide({ storageKey }: { storageKey: string }) {
  const t = useTranslations("dashboard");
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const [state, setState] = useState<GuideState | null>(() => readGuide(storageKey));
  const [justDone, setJustDone] = useState(false);
  const [picking, setPicking] = useState(false);

  function commit(next: GuideState) {
    setState(next);
    if (next.path !== "skip" && next.step >= stepsOf(next).length) {
      setJustDone(true);
    }
  }

  // Reaching a step's page completes it — worked out while rendering, so
  // the strip never shows a step the page already did.
  const reached = state && advance(state, pathname);
  if (reached && reached !== state) commit(reached);

  const steps = state && !state.closed ? stepsOf(state) : [];
  const step = (state && steps[state.step]) || null;
  const href = (state && step?.href(state, pathname)) || null;
  // HRP-1177: the step's button, once it is on the page.
  const targets = step?.here && href !== pathname ? null : step?.targets;
  const target = useSyncExternalStore(
    targets ? watchPage : watchNothing,
    () => findTarget(targets),
    () => null,
  );

  // The ring, and the button brought into view once - without taking the
  // focus or covering the page. To the top (globals.css keeps a margin),
  // not the middle: the demo card sits in the bottom corner, and a value
  // moment half way through a route brings it over the next button. A
  // dialog scrolls no further than it must: its fields come first.
  useEffect(() => {
    if (!target) return;
    target.setAttribute(TARGET_ATTR, "");
    target.scrollIntoView?.({
      block: target.closest('[role="dialog"]') ? "nearest" : "start",
    });
    return () => target.removeAttribute(TARGET_ATTR);
  }, [target]);

  useEffect(() => {
    if (!target || !state || !step?.click) return;
    const pressed = () => commit({ ...state, step: state.step + 1 });
    target.addEventListener("click", pressed);
    return () => target.removeEventListener("click", pressed);
  }, [target, state, step]);

  useEffect(() => {
    if (state) writeGuide(storageKey, state);
  }, [state, storageKey]);

  // So does the step's create — read through the demo card's own matcher.
  useEffect(() => {
    if (!state) return;
    const current = state;
    function onMutation(e: Event) {
      const hit = matchMoment((e as CustomEvent<MutationEventDetail>).detail);
      const next = hit && advance(current, pathname, hit.context);
      if (next && next !== current) commit(next);
    }
    window.addEventListener(MUTATION_EVENT, onMutation);
    return () => window.removeEventListener(MUTATION_EVENT, onMutation);
  }, [pathname, state]);

  useEffect(() => {
    if (!justDone) return;
    const id = setTimeout(() => setJustDone(false), DONE_SHOWN_MS);
    return () => clearTimeout(id);
  }, [justDone]);

  function choose(path: DemoGuidePath) {
    if (picking) return;
    if (path === "skip") {
      commit({ path, step: 0, back: null, lead: false, gap: null });
      // The funnel's guided/free split, best-effort.
      chooseDemoGuide(path).catch(() => {});
      return;
    }
    // HRP-1175: the pick opens the page the route starts on, which only
    // the answer names. No answer in time, or nothing to start from: the
    // list, and the route leads with "open".
    setPicking(true);
    Promise.race([
      chooseDemoGuide(path).catch(() => null),
      new Promise<null>((resolve) => setTimeout(resolve, PICK_WAIT_MS, null)),
    ]).then((starts) => {
      const id = path === "coverage" ? starts?.process_id : starts?.assessment_id;
      const back = id ? `${LIST[path]}/${id}` : null;
      commit({
        path,
        step: 0,
        back,
        lead: !back,
        gap: starts?.gap_process_id ? `/coverage/${starts.gap_process_id}` : null,
      });
      router.push(back ?? LIST[path]);
    });
  }

  if (!state) {
    return (
      <Dialog
        open
        // Esc, a click outside and the cross all mean "I'll look around".
        onOpenChange={(open) => !open && choose("skip")}
      >
        <DialogContent className="sm:max-w-lg" data-testid="demo-guide-dialog">
          <DialogHeader>
            <DialogTitle>{t("demoGuideTitle")}</DialogTitle>
            <DialogDescription>{t("demoGuideIntro")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            {(Object.keys(ROUTES) as Route[]).map((route) => (
              <button
                key={route}
                type="button"
                disabled={picking}
                onClick={() => choose(route)}
                className="w-full rounded-lg border border-border p-3 text-left transition-colors hover:border-brand hover:bg-brand/5 disabled:opacity-60"
                data-testid={`demo-guide-route-${route}`}
              >
                <span className="block font-semibold">{t(ROUTE_COPY[route].title)}</span>
                <span className="mt-0.5 block text-sm text-muted-foreground">
                  {t(ROUTE_COPY[route].hint)}
                </span>
              </button>
            ))}
          </div>
          <button
            type="button"
            disabled={picking}
            onClick={() => choose("skip")}
            className="w-full rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
            data-testid="demo-guide-skip"
          >
            {t("demoGuideSkip")}
          </button>
        </DialogContent>
      </Dialog>
    );
  }

  if (state.path === "skip" || state.closed) return null;
  const finished = state.step >= steps.length;
  if (finished && !justDone) return null;

  return (
    <div
      className="border-b border-border bg-muted/50 px-4 py-2 text-sm"
      data-testid="demo-guide-strip"
      data-route={state.path}
      data-step={finished ? "done" : state.step + 1}
    >
      <div className="mx-auto flex max-w-[1400px] items-center gap-3">
        {step ? (
          <Compass className="h-4 w-4 shrink-0 text-brand" aria-hidden />
        ) : (
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" aria-hidden />
        )}
        {/* Keyed by the step: a new step is a new node, never an edit of
            the text in place. */}
        <p key={finished ? "done" : state.step} className="min-w-0 flex-1">
          {step ? (
            <>
              <span className="font-semibold">
                {t("demoGuideStep", { n: state.step + 1, total: steps.length })}
              </span>{" "}
              {t(state.lead && step.leadText ? step.leadText : step.text)}
            </>
          ) : (
            t("demoGuideDone")
          )}
        </p>
        {/* The button on screen, or its page already open: nowhere to go. */}
        {href && href !== pathname && !target && (
          <Link
            href={href}
            className="shrink-0 font-semibold text-brand hover:underline"
            data-testid="demo-guide-go"
          >
            {t("demoGuideGo")}
          </Link>
        )}
        <button
          type="button"
          onClick={() =>
            finished ? setJustDone(false) : commit({ ...state, closed: true })
          }
          className="shrink-0 rounded p-1 text-muted-foreground hover:bg-foreground/10 hover:text-foreground"
          aria-label={t("demoGuideClose")}
          data-testid="demo-guide-close"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
