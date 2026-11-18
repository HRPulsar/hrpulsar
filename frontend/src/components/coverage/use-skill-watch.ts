"use client";

// HRP-1192 / HRP-1202: one poll per process page for the skills being
// written. A generation started from a dialog, from "Generate N" on the To
// do tab or elsewhere is followed here, not in the component that started
// it: closing the dialog or the bulk run ending used to stop the watch, and
// the step read "Generating" until F5. The tabs report what they loaded,
// the page follows the generating steps and bumps `version` when one ends,
// and every place that shows the status reloads on it.

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { generationErrorText } from "@/components/coverage/generation-errors";
import { ApiError } from "@/lib/api";
import { type SkillStatus, workApi } from "@/lib/api/work";

const POLL_MS = 3_000;
// Past the server's cutoff (SKILL_GENERATING_TIMEOUT, 15 min in
// work/service.py): by then the server reads a stuck run as failed and the
// poll ends on that answer. The bound only stops a step whose status never
// comes back at all (the network, the server), and says nothing - a
// guessed "failed" would be a lie about a file that may still arrive.
const FOLLOW_MS = 16 * 60_000;

export interface SkillRow {
  step_id: string;
  position: number;
  skill_status: SkillStatus;
}

export interface SkillWatch {
  /** The rows a tab just loaded: the generating ones are followed. */
  watch: (rows: SkillRow[]) => void;
  /** Bumped when a followed step stops generating; reload on it. */
  version: number;
}

export function useSkillWatch(): SkillWatch {
  const t = useTranslations("coverage");
  // step id -> position (for the toast) and when the watch began.
  const [followed, setFollowed] = useState<Map<string, { position: number; since: number }>>(
    () => new Map(),
  );
  const [version, setVersion] = useState(0);
  // A step whose budget ran out is not picked up again by the next reload
  // that still reads it "generating": the bound would otherwise restart.
  // Once a reload reads it as anything else, a new run is followed again.
  const givenUp = useRef(new Set<string>());

  const watch = useCallback((rows: SkillRow[]) => {
    for (const row of rows) {
      if (row.skill_status !== "generating") givenUp.current.delete(row.step_id);
    }
    setFollowed((prev) => {
      let next: Map<string, { position: number; since: number }> | null = null;
      for (const row of rows) {
        if (row.skill_status !== "generating") continue;
        if (prev.has(row.step_id) || givenUp.current.has(row.step_id)) continue;
        next ??= new Map(prev);
        next.set(row.step_id, { position: row.position, since: Date.now() });
      }
      return next ?? prev;
    });
  }, []);

  // Restarted whenever the followed set changes; a new step waits one
  // interval like the rest.
  useEffect(() => {
    if (followed.size === 0) return;
    let stopped = false;
    let timer = 0;

    async function tick() {
      const ended: string[] = [];
      await Promise.all(
        [...followed].map(async ([stepId, { position, since }]) => {
          if (Date.now() - since > FOLLOW_MS) {
            givenUp.current.add(stepId);
            ended.push(stepId);
            return;
          }
          try {
            const skill = await workApi.getSkill(stepId);
            // Restarted meanwhile (the followed set changed while this
            // request hung): the new run asks again; no second toast.
            if (stopped || skill.status === "generating") return;
            ended.push(stepId);
            if (skill.status === "ready") {
              toast.success(t("skillReadyToast", { position }));
            } else {
              const reason = generationErrorText(t, skill.error_code, skill.error_message, "skillFailed");
              toast.error(t("skillFailedToast", { position, reason }));
            }
          } catch (err) {
            // The step is gone (a regenerated breakdown); anything else is
            // retried on the next tick.
            if (!stopped && err instanceof ApiError && err.status === 404) ended.push(stepId);
          }
        }),
      );
      if (stopped || ended.length === 0) return;
      setFollowed((prev) => {
        const next = new Map(prev);
        for (const id of ended) next.delete(id);
        return next;
      });
      setVersion((v) => v + 1);
    }

    async function loop() {
      await tick();
      if (!stopped) timer = window.setTimeout(loop, POLL_MS);
    }
    timer = window.setTimeout(loop, POLL_MS);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [followed, t]);

  return { watch, version };
}

/** A tab's side of the watch: report the rows it loaded, reload when a
 * followed step ends. No watch (a tab rendered on its own) - no-op. */
export function useFollowSkills(
  skillWatch: SkillWatch | undefined,
  rows: SkillRow[] | null | undefined,
  reload: () => unknown,
) {
  const watch = skillWatch?.watch;
  useEffect(() => {
    if (rows && watch) watch(rows);
  }, [rows, watch]);
  const version = skillWatch?.version ?? 0;
  // A remounted tab loads on its own; only a bump after the mount reloads.
  const seen = useRef(version);
  useEffect(() => {
    if (version === seen.current) return;
    seen.current = version;
    void reload();
  }, [version, reload]);
}
