"use client";

import { useCallback, useState, type KeyboardEvent } from "react";

/**
 * HRP-110: minimal state shape shared by inline-edit fields on entity
 * detail pages (assessment title/deadline, position title/headcount/
 * description).
 *
 * The hook owns:
 *   - `editing` toggle
 *   - `draft` value of type `T`
 *   - `start`/`cancel`/`close` helpers so the page doesn't re-state the
 *     `setEditing(true)` + `setDraft(seed)` pair at every trigger.
 *
 * Validation, save calls, toasts and the `saving` flag stay with the
 * page — both call sites need different shapes there (assessment hits
 * the API directly; positions go through a shared `savePatch` helper),
 * so trying to fold them into the hook would just push the difference
 * into a thicket of options.
 *
 * Pair with `inlineEditKeys` below for the Enter/Esc keymap on the
 * input itself.
 */
export interface UseInlineEdit<T> {
  editing: boolean;
  draft: T;
  setDraft: (next: T) => void;
  start: (seed?: T) => void;
  cancel: () => void;
  close: () => void;
}

export function useInlineEdit<T>(initial: () => T): UseInlineEdit<T> {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<T>(initial);

  const start = useCallback(
    (seed?: T) => {
      setDraft(seed === undefined ? initial() : seed);
      setEditing(true);
    },
    [initial],
  );
  // `cancel` and `close` are intentionally distinct names even though the
  // body is identical — call `cancel` for user-driven exits (Esc / Cancel
  // button) and `close` after a successful save. Splitting the names keeps
  // the call sites readable and lets us diverge later (e.g. add an
  // "unsaved changes" guard on cancel) without touching every consumer.
  const cancel = useCallback(() => setEditing(false), []);
  const close = useCallback(() => setEditing(false), []);

  return { editing, draft, setDraft, start, cancel, close };
}

/**
 * HRP-110: keyboard glue for inline-edit inputs.
 *
 * - Enter — preventDefault + commit (skipped if `disabled` is set).
 * - Escape — cancel.
 *
 * `disabled` is the caller's `saving` flag; the guard prevents
 * double-submit when the user hits Enter twice in a row before the API
 * settles.
 */
export function inlineEditKeys<E extends HTMLElement>(opts: {
  onCommit: () => void;
  onCancel: () => void;
  disabled?: boolean;
}): (e: KeyboardEvent<E>) => void {
  const { onCommit, onCancel, disabled } = opts;
  return (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (disabled) return;
      onCommit();
    } else if (e.key === "Escape") {
      onCancel();
    }
  };
}
