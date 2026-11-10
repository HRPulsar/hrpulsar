"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
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
 * the page the route came back to, and whether it was closed. No entry
 * means "Where to start" has not been answered yet. */
const STORAGE_PREFIX = "demo_guide:";

/** How long the finished route's "Done" stays before the strip goes. */
const DONE_SHOWN_MS = 6_000;

type Route = Exclude<DemoGuidePath, "skip">;

type GuideState = {
  path: DemoGuidePath;
  step: number;
  /** The completed assessment the plan and assessment routes open. */
  anchor: string | null;
  /** The page the first step reached (a process, an assessment): where
   * the next steps happen, so their "Go" leads back to it. */
  back: string | null;
  closed?: boolean;
};

type Step = {
  /** Catalog key; `anyText` instead when there is no anchor assessment. */
  text: string;
  anyText?: string;
  href: (state: GuideState) => string | null;
  /** Reaching this page completes the step. */
  at?: RegExp;
  /** One of these value moments (the demo card's) completes the step. */
  on?: FeedbackContext[];
};

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
/** A page of the app — `:id` is a record id, so `/coverage/new` is not
 * a process. */
const page = (pattern: string) => new RegExp(`^${pattern.replace(":id", UUID)}$`);
const toAnchor = (s: GuideState) =>
  s.anchor ? `/assessments/${s.anchor}` : "/assessments";
const toBack = (s: GuideState) => s.back;

/** HRP-1159: three five-minute routes, each ending on a create — the
 * moment the demo card asks about (HRP-1158), so the strip only says
 * "Done" and the card does the rest. */
const ROUTES: Record<Route, Step[]> = {
  coverage: [
    { text: "demoGuideCoverageOpen", href: () => "/coverage", at: page("/coverage/:id") },
    { text: "demoGuideCoverageBreakDown", href: toBack, on: ["decomposition_applied"] },
    { text: "demoGuideCoverageHire", href: toBack, on: ["hire_need_created"] },
  ],
  pdp: [
    {
      text: "demoGuidePdpOpen",
      anyText: "demoGuidePdpOpenAny",
      href: toAnchor,
      at: page("/assessments/:id"),
    },
    { text: "demoGuidePdpGrowth", href: toBack, at: page("/development") },
    {
      text: "demoGuidePdpCreate",
      href: toBack,
      on: ["pdp_from_assessment", "pdp_created"],
    },
  ],
  assessment: [
    {
      text: "demoGuideAssessmentOpen",
      anyText: "demoGuideAssessmentOpenAny",
      href: toAnchor,
      at: page("/assessments/:id"),
    },
    { text: "demoGuideAssessmentList", href: () => "/assessments", at: page("/assessments") },
    {
      text: "demoGuideAssessmentCreate",
      href: () => "/assessments",
      on: ["assessment_created"],
    },
  ],
};

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
  const steps = ROUTES[state.path];
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
    if (step === 0) back = pathname;
    step += 1;
  }
  return step === state.step ? state : { ...state, step, back };
}

// Storage can be off (private mode): no stored route asks again, and a
// route that cannot be written lives as long as the page.
function readGuide(key: string): GuideState | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as GuideState) : null;
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
  const [state, setState] = useState<GuideState | null>(() => readGuide(storageKey));
  const [justDone, setJustDone] = useState(false);

  function commit(next: GuideState) {
    setState(next);
    if (next.path !== "skip" && next.step >= ROUTES[next.path].length) {
      setJustDone(true);
    }
  }

  // Reaching a step's page completes it — worked out while rendering, so
  // the strip never shows a step the page already did.
  const reached = state && advance(state, pathname);
  if (reached && reached !== state) commit(reached);

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
    commit(advance({ path, step: 0, anchor: null, back: null }, pathname));
    // The funnel's guided/free split. Best-effort: without an answer the
    // plan and assessment routes start from the Assessments list.
    chooseDemoGuide(path)
      .then(({ assessment_id }) => {
        if (!assessment_id) return;
        setState((now) =>
          now?.path === path ? { ...now, anchor: assessment_id } : now,
        );
      })
      .catch(() => {});
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
                onClick={() => choose(route)}
                className="w-full rounded-lg border border-border p-3 text-left transition-colors hover:border-brand hover:bg-brand/5"
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
  const steps = ROUTES[state.path];
  const finished = state.step >= steps.length;
  if (finished && !justDone) return null;
  const step = finished ? null : steps[state.step];
  const href = step?.href(state);

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
        <p className="min-w-0 flex-1">
          {step ? (
            <>
              <span className="font-semibold">
                {t("demoGuideStep", { n: state.step + 1, total: steps.length })}
              </span>{" "}
              {t(!state.anchor && step.anyText ? step.anyText : step.text)}
            </>
          ) : (
            t("demoGuideDone")
          )}
        </p>
        {href && href !== pathname && (
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
