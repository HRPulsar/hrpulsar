"use client";

import { Button } from "@/components/ui/button";

type Props = {
  hasChanges: boolean;
  saving: boolean;
  onSave: () => void;
  onCancel: () => void;
  diffCount: number;
};

export function UnsavedChangesBar({
  hasChanges,
  saving,
  onSave,
  onCancel,
  diffCount,
}: Props) {
  if (!hasChanges) return null;
  return (
    <div
      data-testid="matrix-unsaved-bar"
      className="sticky bottom-4 z-20 mx-auto flex max-w-3xl items-center justify-between gap-4 rounded-lg border bg-background/95 p-3 shadow-md backdrop-blur"
    >
      <div className="text-sm">
        <span className="font-medium">Unsaved changes:</span>{" "}
        <span data-testid="matrix-unsaved-bar-count" className="text-muted-foreground">
          {diffCount}
        </span>
      </div>
      <div className="flex gap-2">
        <Button
          data-testid="matrix-unsaved-bar-btn-cancel"
          variant="outline"
          size="sm"
          onClick={onCancel}
          disabled={saving}
        >
          Cancel
        </Button>
        <Button
          data-testid="matrix-unsaved-bar-btn-save"
          size="sm"
          onClick={onSave}
          disabled={saving}
        >
          {saving ? "Saving..." : "Save"}
        </Button>
      </div>
    </div>
  );
}
