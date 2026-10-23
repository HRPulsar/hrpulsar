"use client";

import * as React from "react";
import Link from "next/link";

import { useAuth } from "@/context/auth-context";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

/*
 * HRP-829 REDO (QA 14.10): an employee's name is a link to their card only
 * when the viewer may open that card. The decision is the backend's - the
 * rule of GET /employees/{id} itself (`readable_card_ids`), asked through
 * GET /employees/card-access - never a threshold of this file:
 *
 * - every name mounted in one render goes out in one request (by 100s),
 *   and the answer is kept per id for the signed-in user and their level;
 * - with the employees section closed (`none`) nothing is asked and every
 *   name is plain text;
 * - unknown, still loading or a failed check - plain text.
 */

const BATCH = 100;
// ponytail: answers live for the tab's session per user and level; a
// colleague who leaves meanwhile still links until a reload (the card then
// answers "not found"). Add an expiry if that shows up.
let owner: string | null = null;
const known = new Map<string, boolean | null>(); // null: asked, no answer yet
let queued: string[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

async function flush() {
  timer = null;
  const ids = queued;
  const asking = owner;
  queued = [];
  for (let i = 0; i < ids.length; i += BATCH) {
    const chunk = ids.slice(i, i + BATCH);
    const query = new URLSearchParams(chunk.map((id) => ["ids", id]));
    try {
      const open = new Set(
        await api.get<string[]>(`/employees/card-access?${query}`),
      );
      if (owner !== asking) return; // signed out or switched meanwhile
      for (const id of chunk) known.set(id, open.has(id));
    } catch {
      if (owner !== asking) return;
      for (const id of chunk) known.delete(id); // the next mount asks again
    }
  }
  listeners.forEach((listener) => listener());
}

function ask(key: string, id: string) {
  if (owner !== key) {
    owner = key;
    known.clear();
    queued = [];
  }
  if (known.has(id)) return;
  known.set(id, null);
  queued.push(id);
  timer ??= setTimeout(() => void flush(), 0);
}

/** Test seam: forget every answer. */
export function resetCardAccess() {
  owner = null;
  known.clear();
  queued = [];
}

/** Whether the viewer may open this employee's card (false until known). */
export function useCardReadable(employeeId?: string | null): boolean {
  const { user } = useAuth();
  const level = user?.sections?.employees;
  const key = user && level ? `${user.id}:${level}` : null;
  React.useEffect(() => {
    if (key && employeeId) ask(key, employeeId);
  }, [key, employeeId]);
  return React.useSyncExternalStore(
    subscribe,
    () => Boolean(key && employeeId && owner === key && known.get(employeeId)),
    () => false,
  );
}

type EmployeeNameProps = Omit<React.HTMLAttributes<HTMLElement>, "children"> & {
  employeeId?: string | null;
  children: React.ReactNode;
  /** On the link only, on top of `className`. */
  linkClassName?: string;
  /** On the link; also on the text unless `textTestId` is given. */
  testId?: string;
  textTestId?: string;
  /** Open the card in a new tab (a picker that must stay put). */
  newTab?: boolean;
};

/** An employee's name: a link to their card, or text when it does not open. */
export function EmployeeName({
  employeeId,
  children,
  className,
  linkClassName,
  testId,
  textTestId,
  newTab,
  onClick,
  ...rest
}: EmployeeNameProps) {
  const readable = useCardReadable(employeeId);
  if (readable && employeeId) {
    return (
      <Link
        href={`/employees/${employeeId}`}
        className={cn(className, linkClassName)}
        data-testid={testId}
        {...(newTab ? { target: "_blank", rel: "noreferrer" } : {})}
        {...rest}
        // Names sit in rows and cards that open something else on click.
        onClick={(event) => {
          event.stopPropagation();
          onClick?.(event);
        }}
      >
        {children}
      </Link>
    );
  }
  return (
    <span className={className} data-testid={textTestId ?? testId} {...rest}>
      {children}
    </span>
  );
}
