"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  getWsState,
  onWsStateChange,
  subscribeWs,
  type WsBusState,
} from "@/lib/ws-bus";
import type { SessionScope } from "@/lib/api/competence-generation";

type Phase = "thinking" | "grades" | "competences" | "indicators" | "matrix";

interface ProgressEventPayload {
  session_id: string;
  phase: Phase;
  total?: number;
  current?: number;
}

function isProgressPayload(value: unknown): value is ProgressEventPayload {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.session_id === "string" && typeof v.phase === "string";
}

interface State {
  // `thinkingActive` flips on the `thinking` event; any later phase event
  // means the LLM call returned, so thinking is done. We track them as two
  // booleans rather than a string state machine because phase events can
  // race over the websocket and we just want monotonic "started → done".
  thinkingActive: boolean;
  thinkingDone: boolean;
  grades: { total: number; current: number; complete: boolean };
  competences: { total: number; current: number; complete: boolean };
  indicators: { total: number; current: number; complete: boolean };
  matrix: { total: number; current: number; complete: boolean };
}

const initial: State = {
  thinkingActive: false,
  thinkingDone: false,
  grades: { total: 0, current: 0, complete: false },
  competences: { total: 0, current: 0, complete: false },
  indicators: { total: 0, current: 0, complete: false },
  matrix: { total: 0, current: 0, complete: false },
};

interface Props {
  sessionId: string;
  scope: SessionScope;
}

export function AIGenerateProgress({ sessionId, scope }: Props) {
  const t = useTranslations("company");
  // Parent resets us via `key={sessionId}` when the session id changes,
  // so this state survives only the current session — no setState in effect.
  const [state, setState] = useState<State>(initial);
  // Lazy initialiser pulls the current ws state once at mount so we never
  // setState in the subscription effect (lint: react-hooks/set-state-in-effect).
  const [wsState, setWsBusState] = useState<WsBusState>(() => getWsState());

  useEffect(() => {
    const unsubscribe = subscribeWs("compgen.progress", (msg) => {
      const p = msg.payload;
      if (!isProgressPayload(p) || p.session_id !== sessionId) return;
      setState((prev) => {
        if (p.phase === "thinking") {
          return { ...prev, thinkingActive: true };
        }
        // Any non-thinking event means the LLM call returned and we're now
        // streaming totals — flip thinking to done.
        const base = { ...prev, thinkingDone: true };
        const total = p.total ?? 0;
        const current = p.current ?? 0;
        const complete = current >= total;
        if (p.phase === "grades") {
          return { ...base, grades: { total, current, complete } };
        }
        if (p.phase === "competences") {
          return { ...base, competences: { total, current, complete } };
        }
        if (p.phase === "indicators") {
          return { ...base, indicators: { total, current, complete } };
        }
        if (p.phase === "matrix") {
          return { ...base, matrix: { total, current, complete } };
        }
        return prev;
      });
    });
    return unsubscribe;
  }, [sessionId]);

  useEffect(() => onWsStateChange(setWsBusState), []);

  const isMatrix = scope === "specialization_matrix";
  const isIndicatorScope = scope === "competence_indicators";

  return (
    <ul
      data-testid="ai-generate-progress"
      className="space-y-1 text-sm"
    >
      <Step
        label={t("progressThinking")}
        status={
          state.thinkingDone
            ? "done"
            : state.thinkingActive
              ? "active"
              : "pending"
        }
        testId="ai-generate-progress-thinking"
      />
      {isMatrix && (
        <Step
          label={
            state.grades.total > 0
              ? t("progressGradesWithTotal", { total: state.grades.total })
              : t("progressGrades")
          }
          status={state.grades.complete ? "done" : "pending"}
          testId="ai-generate-progress-grades"
        />
      )}
      {!isIndicatorScope && (
        <Step
          label={
            state.competences.total > 0
              ? t("progressCompetencesWithTotal", {
                  total: state.competences.total,
                })
              : t("progressCompetences")
          }
          status={state.competences.complete ? "done" : "pending"}
          testId="ai-generate-progress-competences"
        />
      )}
      <Step
        label={
          state.indicators.total > 0
            ? state.indicators.complete
              ? t("progressIndicatorsDone", { total: state.indicators.total })
              : t("progressIndicatorsRunning", {
                  current: state.indicators.current,
                  total: state.indicators.total,
                })
            : t("progressIndicators")
        }
        status={
          state.indicators.complete
            ? "done"
            : state.indicators.current > 0
              ? "active"
              : "pending"
        }
        testId="ai-generate-progress-indicators"
      />
      {isMatrix && (
        <Step
          label={t("progressMatrix")}
          status={state.matrix.complete ? "done" : "pending"}
          testId="ai-generate-progress-matrix"
        />
      )}
      {(wsState === "closed" || wsState === "reconnecting") && (
        <li
          data-testid="ai-generate-progress-ws-fallback"
          className="pt-2 text-xs text-muted-foreground"
        >
          {t("progressWsFallback")}
        </li>
      )}
    </ul>
  );
}

function Step({
  label,
  status,
  testId,
}: {
  label: string;
  status: "pending" | "active" | "done";
  testId: string;
}) {
  const icon = status === "done" ? "✓" : status === "active" ? "⏳" : "○";
  const tone =
    status === "done"
      ? "text-green-700"
      : status === "active"
        ? "text-blue-700"
        : "text-muted-foreground";
  return (
    <li
      data-testid={testId}
      data-status={status}
      className={`flex items-center gap-2 ${tone}`}
    >
      <span aria-hidden className="w-4 text-center">
        {icon}
      </span>
      <span>{label}</span>
    </li>
  );
}
