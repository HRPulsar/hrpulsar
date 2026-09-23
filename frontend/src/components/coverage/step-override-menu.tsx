"use client";

// HRP-863: the company's override of a computed value, right on the coverage
// row - the step's mode or its agent pack. One menu for both: the options,
// a tick on the effective one, and "return to computed" while the value is
// set by hand. The caller owns the PATCH; this only picks.

import type { ReactElement, ReactNode } from "react";
import { Check, RotateCcw } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export interface OverrideOption {
  value: string;
  label: string;
}

export function StepOverrideMenu({
  testId,
  trigger,
  children,
  options,
  value,
  manual,
  resetLabel,
  emptyLabel,
  disabled,
  onOpen,
  onPick,
}: {
  testId: string;
  /** The element that opens the menu; `children` are rendered inside it. */
  trigger: ReactElement;
  children: ReactNode;
  /** `null` while the options are still loading. */
  options: OverrideOption[] | null;
  /** The effective value, ticked in the list. */
  value: string | null;
  /** The effective value is the company's, so it can be returned. */
  manual: boolean;
  resetLabel: string;
  emptyLabel: string;
  disabled?: boolean;
  /** For options fetched on demand. */
  onOpen?: () => void;
  /** `null` returns the computed value. */
  onPick: (value: string | null) => void;
}) {
  return (
    <DropdownMenu onOpenChange={(open) => open && onOpen?.()}>
      <DropdownMenuTrigger render={trigger} disabled={disabled} data-testid={testId}>
        {children}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-56" data-testid={`${testId}-menu`}>
        {options === null || options.length === 0 ? (
          <DropdownMenuItem disabled>{emptyLabel}</DropdownMenuItem>
        ) : (
          options.map((option) => (
            <DropdownMenuItem
              key={option.value}
              // Picking the value already in effect pins it: a manual value
              // survives a reclassification, a computed one does not.
              onClick={() => onPick(option.value)}
              data-testid={`${testId}-option-${option.value}`}
            >
              <Check className={`size-4 ${option.value === value ? "" : "invisible"}`} />
              {option.label}
            </DropdownMenuItem>
          ))
        )}
        {manual && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => onPick(null)} data-testid={`${testId}-reset`}>
              <RotateCcw className="size-4" />
              {resetLabel}
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
