"use client";

import { ChevronsDownUp, ChevronsUpDown } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * HRP-109: two-button cluster ("Expand all" / "Collapse all") that pairs
 * with `useTreeExpansion`. Each disabled state mirrors the matching flag
 * so the button greys out once the tree is already fully open/closed —
 * cheap visual cue that the click would be a no-op.
 *
 * `testIdPrefix` lets the host page namespace the testids so two trees on
 * the same screen don't collide (e.g. competence picker + assessment list).
 */
export interface TreeExpandControlsProps {
  expandAll: () => void;
  collapseAll: () => void;
  allExpanded: boolean;
  allCollapsed: boolean;
  testIdPrefix: string;
  size?: "sm" | "xs";
  className?: string;
}

export function TreeExpandControls(props: TreeExpandControlsProps) {
  const {
    expandAll,
    collapseAll,
    allExpanded,
    allCollapsed,
    testIdPrefix,
    size = "sm",
    className,
  } = props;
  return (
    <div className={`inline-flex items-center gap-1 ${className ?? ""}`}>
      <Button
        type="button"
        variant="outline"
        size={size}
        onClick={expandAll}
        disabled={allExpanded}
        data-testid={`${testIdPrefix}-btn-expand-all`}
        aria-label="Expand all"
      >
        <ChevronsUpDown className="mr-1 h-3.5 w-3.5" />
        Expand all
      </Button>
      <Button
        type="button"
        variant="outline"
        size={size}
        onClick={collapseAll}
        disabled={allCollapsed}
        data-testid={`${testIdPrefix}-btn-collapse-all`}
        aria-label="Collapse all"
      >
        <ChevronsDownUp className="mr-1 h-3.5 w-3.5" />
        Collapse all
      </Button>
    </div>
  );
}
