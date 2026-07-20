"use client";

import { useCallback, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Check } from "lucide-react";
import type { FunnelStage } from "@/lib/types";

interface StatusChangePopoverProps {
  currentStageId?: string | null;
  stages: FunnelStage[];
  onSelect: (stageId: string, comment?: string) => void;
  children: React.ReactNode;
}

export function StatusChangePopover({
  currentStageId,
  stages,
  onSelect,
  children,
}: StatusChangePopoverProps) {
  const [open, setOpen] = useState(false);
  const [pendingStage, setPendingStage] = useState<FunnelStage | null>(null);
  const [comment, setComment] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  const sortedStages = [...stages].sort((a, b) => a.sort_order - b.sort_order);

  const handleStageClick = useCallback(
    (stage: FunnelStage) => {
      if (stage.id === currentStageId) return;

      if (stage.is_terminal) {
        setPendingStage(stage);
        setComment("");
      } else {
        onSelect(stage.id);
        setOpen(false);
        setPendingStage(null);
      }
    },
    [currentStageId, onSelect],
  );

  const handleConfirmTerminal = useCallback(() => {
    if (!pendingStage) return;
    onSelect(pendingStage.id, comment || undefined);
    setOpen(false);
    setPendingStage(null);
    setComment("");
  }, [pendingStage, comment, onSelect]);

  const handleCancelTerminal = useCallback(() => {
    setPendingStage(null);
    setComment("");
  }, []);

  // Close popover when clicking outside
  const handleBlur = useCallback(
    (e: React.FocusEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.relatedTarget as Node)
      ) {
        setOpen(false);
        setPendingStage(null);
      }
    },
    [],
  );

  return (
    <div
      ref={containerRef}
      className="relative inline-block"
      onBlur={handleBlur}
      data-testid="recruitment-status-popover"
    >
      {/* Trigger */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => setOpen(!open)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setOpen(!open);
          }
        }}
      >
        {children}
      </div>

      {/* Popover content */}
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1.5 w-64 rounded-xl border bg-popover p-1 shadow-lg ring-1 ring-foreground/5">
          {!pendingStage ? (
            <ul className="space-y-0.5" role="listbox">
              {sortedStages.map((stage) => {
                const isCurrent = stage.id === currentStageId;
                return (
                  <li key={stage.id}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={isCurrent}
                      disabled={isCurrent}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm transition-colors",
                        isCurrent
                          ? "bg-accent/10 text-accent font-medium"
                          : "hover:bg-muted",
                        isCurrent && "cursor-default",
                      )}
                      onClick={() => handleStageClick(stage)}
                    >
                      {/* HRP-357 REDO: active stages are always blue; only
                          terminal stages keep their own color. */}
                      {(stage.is_terminal ? stage.color : true) && (
                        <span
                          className="size-2 shrink-0 rounded-full"
                          style={{
                            backgroundColor: stage.is_terminal
                              ? (stage.color ?? undefined)
                              : "var(--accent)",
                          }}
                        />
                      )}
                      <span className="flex-1">{stage.name}</span>
                      {isCurrent && <Check className="size-4" />}
                      {stage.is_terminal && (
                        <span className="text-xs text-muted-foreground">
                          Final
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            /* Terminal stage: reason form */
            <div className="space-y-2 p-2">
              <p className="text-sm font-medium">
                Move to &quot;{pendingStage.name}&quot;
              </p>
              <p className="text-xs text-muted-foreground">
                This is a terminal stage. You may add a reason below.
              </p>
              <Textarea
                placeholder="Reason (optional)"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                className="min-h-16 text-sm"
                data-testid="status-change-reason"
              />
              <div className="flex justify-end gap-1.5">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleCancelTerminal}
                >
                  Back
                </Button>
                <Button size="sm" onClick={handleConfirmTerminal}>
                  Confirm
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
