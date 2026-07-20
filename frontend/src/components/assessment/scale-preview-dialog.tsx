"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import type { AnswerScaleDetail } from "@/lib/types";
import { scaleLevelLabel } from "@/lib/scale-levels-i18n";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export interface ScalePreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  scaleId: string | null;
  initial?: AnswerScaleDetail | null;
}

export function ScalePreviewDialog({
  open,
  onOpenChange,
  scaleId,
  initial,
}: ScalePreviewDialogProps) {
  const [fetched, setFetched] = useState<{
    id: string;
    scale: AnswerScaleDetail;
  } | null>(null);
  const useInitial = initial != null && initial.id === scaleId;

  useEffect(() => {
    if (!open || !scaleId || useInitial) return;
    let alive = true;
    api
      .get<AnswerScaleDetail>(`/answer-scales/${scaleId}`)
      .then((d) => {
        if (alive) setFetched({ id: scaleId, scale: d });
      })
      .catch((err) => {
        if (alive) {
          toast.error(
            err instanceof Error ? err.message : "Failed to load scale",
          );
        }
      });
    return () => {
      alive = false;
    };
  }, [open, scaleId, useInitial]);

  const scale = useInitial
    ? initial ?? null
    : fetched && fetched.id === scaleId
      ? fetched.scale
      : null;
  const loading = !scale && open && !!scaleId;

  const sortedOptions = scale
    ? [...scale.options].sort((a, b) => a.sort_index - b.sort_index)
    : [];
  const sortedLevels = scale
    ? [...scale.levels].sort((a, b) => a.sort_index - b.sort_index)
    : [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-2xl"
        data-testid="assessment-scale-preview-modal"
      >
        <DialogHeader>
          <DialogTitle>{scale?.title ?? "Scale preview"}</DialogTitle>
        </DialogHeader>
        {loading || !scale ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Loading…
          </p>
        ) : (
          <div className="max-h-[70vh] space-y-5 overflow-y-auto pr-1">
            {scale.description && (
              <p className="text-sm text-muted-foreground">
                {scale.description}
              </p>
            )}

            <section className="space-y-2">
              <h3 className="text-sm font-medium">Answer options</h3>
              <div className="space-y-1.5">
                {sortedOptions.map((opt) => (
                  <div
                    key={opt.id}
                    className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm"
                  >
                    <span className="flex-1">{opt.title}</span>
                    {opt.is_neutral ? (
                      <Badge variant="outline" className="text-xs">
                        Excluded from score
                      </Badge>
                    ) : (
                      <Badge variant="secondary" className="text-xs">
                        Score: {opt.weight ?? "—"}
                      </Badge>
                    )}
                    {opt.description && (
                      <span className="text-xs text-muted-foreground">
                        {opt.description}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </section>

            {sortedLevels.length > 0 && (
              <section className="space-y-2">
                <h3 className="text-sm font-medium">Match-percent levels</h3>
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>From, %</TableHead>
                        <TableHead>To, %</TableHead>
                        <TableHead>Title</TableHead>
                        <TableHead>Description</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {sortedLevels.map((lvl) => (
                        <TableRow key={lvl.id}>
                          <TableCell>{lvl.percent_from}</TableCell>
                          <TableCell>{lvl.percent_to}</TableCell>
                          <TableCell className="font-medium">
                            {scaleLevelLabel(lvl)}
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {lvl.description ?? "—"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </section>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
