"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type {
  GeneratedCompetence,
  GeneratedGroup,
  GeneratedTreePayload,
  SessionScope,
} from "@/lib/api/competence-generation";
import { newClientId } from "@/lib/utils";

export interface ApplyDialogProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** Session scope — controls which selection list the dialog summarises. */
  scope?: SessionScope;
  payload: GeneratedTreePayload;
  selection: Record<string, boolean>;
  onApply: (body: {
    publish: boolean;
    idempotency_key: string;
  }) => Promise<void> | void;
  /** HRP-102: caller-provided warning shown above the action buttons (e.g.
   * the usage banner when the target competence is already in use). */
  warning?: React.ReactNode;
  /** HRP-102: optional pre-submit guard. When provided, the dialog asks
   * the guard for permission before calling `onApply`. Returning false
   * aborts the apply silently — the caller is expected to show its own
   * confirm UI inside the guard (e.g. the usage-warning dialog) and only
   * resolve true once the user clicks through it. Runs *after* the local
   * publish-confirm step for the matrix scope, so the publish/cancel
   * decision is fixed before the usage prompt appears. */
  applyGuard?: (publish: boolean) => Promise<boolean>;
}

interface SelectedCompetenceSummary {
  title: string;
  hasSelectedIndicators: boolean;
  totalIndicators: number;
}

function collectSelectedCompetences(
  payload: GeneratedTreePayload,
  selection: Record<string, boolean>,
): SelectedCompetenceSummary[] {
  const out: SelectedCompetenceSummary[] = [];
  function visitGroup(g: GeneratedGroup) {
    for (const c of g.competences ?? []) addIfSelected(c);
    for (const ch of g.children ?? []) visitGroup(ch);
  }
  function addIfSelected(c: GeneratedCompetence) {
    if (!c.temp_id || !selection[c.temp_id]) return;
    const inds = c.indicators ?? [];
    const hasSelected = inds.some((i) => i.temp_id && selection[i.temp_id]);
    out.push({
      title: c.title,
      hasSelectedIndicators: hasSelected || inds.length === 0,
      totalIndicators: inds.length,
    });
  }
  for (const g of payload.groups ?? []) visitGroup(g);
  return out;
}

interface SelectedIndicatorSummary {
  title: string;
  skill_level: string;
}

function collectSelectedIndicators(
  payload: GeneratedTreePayload,
  selection: Record<string, boolean>,
): SelectedIndicatorSummary[] {
  const out: SelectedIndicatorSummary[] = [];
  for (const ind of payload.indicators ?? []) {
    if (ind.temp_id && selection[ind.temp_id]) {
      out.push({ title: ind.title, skill_level: ind.skill_level });
    }
  }
  return out;
}

export function ApplyDialog({
  open,
  onOpenChange,
  scope = "whole_base",
  payload,
  selection,
  onApply,
  warning,
  applyGuard,
}: ApplyDialogProps) {
  const t = useTranslations("competences");
  const tc = useTranslations("common");
  const [confirmPublishOpen, setConfirmPublishOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const idempotencyRef = useRef<string | null>(null);

  // Generate the key once per dialog session — protects against double
  // submits (re-clicks while the request is in-flight) collapsing into
  // separate billing events.
  useEffect(() => {
    if (open && !idempotencyRef.current) {
      idempotencyRef.current = newClientId();
    }
    if (!open) {
      idempotencyRef.current = null;
      setConfirmPublishOpen(false);
    }
  }, [open]);

  const isIndicatorScope = scope === "competence_indicators";
  const summary = useMemo(
    () => collectSelectedCompetences(payload, selection),
    [payload, selection],
  );
  const indicatorSummary = useMemo(
    () => collectSelectedIndicators(payload, selection),
    [payload, selection],
  );
  const hasSelection = isIndicatorScope
    ? indicatorSummary.length > 0
    : summary.length > 0;

  async function submit(publish: boolean) {
    if (!idempotencyRef.current) {
      idempotencyRef.current = newClientId();
    }
    setSubmitting(true);
    try {
      if (applyGuard) {
        const proceed = await applyGuard(publish);
        if (!proceed) return;
      }
      await onApply({
        publish,
        idempotency_key: idempotencyRef.current,
      });
      onOpenChange(false);
    } finally {
      setSubmitting(false);
    }
  }

  const wontBePublished = summary.filter((s) => !s.hasSelectedIndicators);

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent
          data-testid="compgen-apply-dialog"
          className="sm:max-w-md"
        >
          <DialogHeader>
            <DialogTitle>
              {isIndicatorScope ? t("applyTitleIndicators") : t("addToLibrary")}
            </DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {isIndicatorScope
              ? t("applyIndicatorsDescription", {
                  count: indicatorSummary.length,
                })
              : t("applyLibraryDescription")}
          </p>
          {isIndicatorScope && indicatorSummary.length > 0 && (
            <ul
              data-testid="compgen-apply-indicator-list"
              className="max-h-48 space-y-1 overflow-y-auto rounded-md border bg-muted/30 p-3 text-sm"
            >
              {indicatorSummary.map((i, idx) => (
                <li key={idx} className="flex items-start gap-2">
                  <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-foreground/50" />
                  <span className="flex-1">{i.title}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {i.skill_level}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {warning}
          <DialogFooter className="flex-col sm:flex-row">
            <Button
              data-testid="compgen-apply-btn-cancel"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
            >
              {tc("cancel")}
            </Button>
            <Button
              data-testid="compgen-apply-btn-unpublished"
              variant="outline"
              onClick={() => submit(false)}
              disabled={submitting || !hasSelection}
            >
              {t("applyWithoutPublishing")}
            </Button>
            <Button
              data-testid="compgen-apply-btn-publish"
              onClick={() =>
                isIndicatorScope ? submit(true) : setConfirmPublishOpen(true)
              }
              disabled={submitting || !hasSelection}
            >
              {t("applyAndPublish")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmPublishOpen} onOpenChange={setConfirmPublishOpen}>
        <DialogContent
          data-testid="compgen-apply-confirm-publish"
          className="sm:max-w-lg"
        >
          <DialogHeader>
            <DialogTitle>{t("applyConfirmPublishTitle")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <p className="text-muted-foreground">
              {t("applyWillBePublished")}
            </p>
            <ul className="space-y-1 rounded-md border bg-muted/30 p-3 text-sm">
              {summary
                .filter((s) => s.hasSelectedIndicators)
                .map((s, i) => (
                  <li key={i} className="flex items-center gap-2">
                    <span className="h-1 w-1 rounded-full bg-foreground/50" />
                    {s.title}
                  </li>
                ))}
            </ul>
            {wontBePublished.length > 0 && (
              <>
                <p className="text-muted-foreground">
                  {t("applyWontBePublished")}
                </p>
                <ul className="space-y-1 rounded-md border bg-amber-50 p-3 text-sm dark:bg-amber-950/20">
                  {wontBePublished.map((s, i) => (
                    <li key={i} className="flex items-center gap-2">
                      <span className="h-1 w-1 rounded-full bg-amber-600" />
                      {s.title}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmPublishOpen(false)}
              disabled={submitting}
            >
              {t("back")}
            </Button>
            <Button
              onClick={() => {
                setConfirmPublishOpen(false);
                submit(true);
              }}
              disabled={submitting}
            >
              {submitting ? t("applyApplying") : t("publish")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
