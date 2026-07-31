"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { api } from "@/lib/api";
import type { AnswerScaleDetail } from "@/lib/types";
import {
  answerScaleDescription,
  answerScaleLabel,
  scaleLevelLabel,
  scaleOptionDescription,
  scaleOptionLabel,
} from "@/lib/reference-labels";
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
  const t = useTranslations("assessments");
  const tRef = useTranslations("reference");
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
            err instanceof Error ? err.message : t("errorLoadScale"),
          );
        }
      });
    return () => {
      alive = false;
    };
  }, [open, scaleId, useInitial, t]);

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
          <DialogTitle>
            {scale ? answerScaleLabel(tRef, scale) : t("scalePreviewTitle")}
          </DialogTitle>
        </DialogHeader>
        {loading || !scale ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {t("loadingEllipsis")}
          </p>
        ) : (
          <div className="max-h-[70vh] space-y-5 overflow-y-auto pr-1">
            {(() => {
              const description = answerScaleDescription(tRef, scale);
              return description ? (
                <p className="text-sm text-muted-foreground">{description}</p>
              ) : null;
            })()}

            <section className="space-y-2">
              <h3 className="text-sm font-medium">{t("answerOptions")}</h3>
              <div className="space-y-1.5">
                {sortedOptions.map((opt) => (
                  <div
                    key={opt.id}
                    className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm"
                  >
                    <span className="flex-1">{scaleOptionLabel(tRef, opt)}</span>
                    {opt.is_neutral ? (
                      <Badge variant="outline" className="text-xs">
                        {t("excludedFromScore")}
                      </Badge>
                    ) : (
                      <Badge variant="secondary" className="text-xs">
                        {t("scoreValue", { value: opt.weight ?? "—" })}
                      </Badge>
                    )}
                    {scaleOptionDescription(tRef, opt) && (
                      <span className="text-xs text-muted-foreground">
                        {scaleOptionDescription(tRef, opt)}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </section>

            {sortedLevels.length > 0 && (
              <section className="space-y-2">
                <h3 className="text-sm font-medium">{t("matchPercentLevels")}</h3>
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t("colFrom")}</TableHead>
                        <TableHead>{t("colTo")}</TableHead>
                        <TableHead>{t("fieldTitle")}</TableHead>
                        <TableHead>{t("fieldDescription")}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {sortedLevels.map((lvl) => (
                        <TableRow key={lvl.id}>
                          <TableCell>{lvl.percent_from}</TableCell>
                          <TableCell>{lvl.percent_to}</TableCell>
                          <TableCell className="font-medium">
                            {scaleLevelLabel(tRef, lvl)}
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
