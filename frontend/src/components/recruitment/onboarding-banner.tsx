"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import type { RecruitmentOnboardingState } from "@/lib/types";

type Step = RecruitmentOnboardingState["step"];

type StepCopy = {
  title: string;
  hint: string;
  cta: string;
  href: string;
};

export const STEP_COPY: Record<Exclude<Step, "done">, StepCopy> = {
  welcome: {
    title: "Welcome to recruitment",
    hint: "Create your first vacancy or seed a demo pipeline to explore the workflow end-to-end.",
    cta: "Create your first vacancy",
    href: "/recruitment/requisitions/new",
  },
  vacancy_created: {
    title: "Add a candidate",
    hint: "Attach your first candidate to the vacancy you just created.",
    cta: "Add a candidate",
    href: "/recruitment/candidates",
  },
  candidate_invited: {
    title: "Schedule an interview",
    hint: "Record an interview with one of the candidates you've attached.",
    cta: "Schedule an interview",
    href: "/recruitment/interviews",
  },
  interview_scheduled: {
    title: "Run the AI analysis",
    hint: "Upload the recording, transcribe and analyse the interview.",
    cta: "Open interviews",
    href: "/recruitment/interviews",
  },
  report_reviewed: {
    title: "Generate a consolidated report",
    hint: "Compile candidates and AI insights into a single XLSX report.",
    cta: "Open reports",
    href: "/recruitment/reports",
  },
};

export const STEP_ORDER: Exclude<Step, "done">[] = [
  "welcome",
  "vacancy_created",
  "candidate_invited",
  "interview_scheduled",
  "report_reviewed",
];

export function RecruitmentOnboardingBanner() {
  const router = useRouter();
  const [state, setState] = useState<RecruitmentOnboardingState | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.get<RecruitmentOnboardingState>(
        "/recruitment/onboarding",
      );
      setState(res);
    } catch {
      setState(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const skip = useCallback(async () => {
    setBusy(true);
    try {
      const next = await api.post<RecruitmentOnboardingState>(
        "/recruitment/onboarding/dismiss",
        {},
      );
      setState(next);
    } catch {
      toast.error("Failed to dismiss onboarding");
    } finally {
      setBusy(false);
    }
  }, []);

  const seedDemo = useCallback(async () => {
    setBusy(true);
    try {
      await api.post("/recruitment/onboarding/demo-seed", {});
      toast.success("Demo pipeline seeded");
      await load();
    } catch {
      toast.error("Failed to seed demo data");
    } finally {
      setBusy(false);
    }
  }, [load]);

  if (loading || !state) return null;
  if (state.dismissed_at || state.step === "done") return null;

  const copy = STEP_COPY[state.step];
  const currentIndex = STEP_ORDER.indexOf(state.step);
  const isWelcome = state.step === "welcome";

  return (
    <div
      className="sticky top-0 z-30 border-b bg-muted/40 backdrop-blur supports-[backdrop-filter]:bg-muted/30"
      data-testid="recruitment-onboarding"
    >
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-4">
        <div
          className="flex items-center gap-2"
          aria-label={`Step ${currentIndex + 1} of ${STEP_ORDER.length}`}
          data-testid="recruitment-onboarding-stepper"
        >
          {STEP_ORDER.map((step, index) => (
            <span
              key={step}
              aria-hidden="true"
              className={cn(
                "h-1.5 w-6 rounded-full transition-colors",
                index < currentIndex
                  ? "bg-primary"
                  : index === currentIndex
                    ? "bg-primary"
                    : "bg-muted-foreground/30",
              )}
            />
          ))}
        </div>

        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium leading-tight">
            <span className="text-muted-foreground">
              Step {currentIndex + 1} of {STEP_ORDER.length} ·{" "}
            </span>
            {copy.title}
          </p>
          <p className="truncate text-xs text-muted-foreground">{copy.hint}</p>
        </div>

        {state.demo_seeded_at && (
          <span
            className="hidden items-center rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-800 sm:inline-flex"
            data-testid="recruitment-demo-ribbon"
          >
            Demo data active
          </span>
        )}

        <div className="flex items-center gap-2">
          {isWelcome && !state.demo_seeded_at && (
            <Button
              variant="ghost"
              size="sm"
              onClick={seedDemo}
              disabled={busy}
              data-testid="recruitment-onboarding-demo"
            >
              <Sparkles className="mr-1.5 h-3.5 w-3.5" />
              Use demo data
            </Button>
          )}
          <Button
            size="sm"
            onClick={() => router.push(copy.href)}
            disabled={busy}
            data-testid="recruitment-onboarding-cta"
          >
            {copy.cta}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={skip}
            disabled={busy}
            data-testid="recruitment-onboarding-dismiss"
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              "Skip tour"
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}