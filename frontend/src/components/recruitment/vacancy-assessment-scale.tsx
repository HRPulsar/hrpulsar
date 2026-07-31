"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";

type ScaleLevel = {
  value: number;
  label: string;
  description?: string | null;
  weight: number;
};

type Scale = {
  id: string;
  name: string;
  is_default: boolean;
  archived_at: string | null;
  levels: ScaleLevel[];
};

type VacancyShape = {
  id: string;
  assessment_scale_id?: string | null;
  assessment_scale_snapshot?: { name?: string; levels?: ScaleLevel[] } | null;
};

interface Props {
  vacancyId: string;
  initial: VacancyShape;
  onScaleChanged?: (vacancy: VacancyShape) => void;
}

export function VacancyAssessmentScaleBlock({
  vacancyId,
  initial,
  onScaleChanged,
}: Props) {
  const t = useTranslations("recruitment");
  const [scales, setScales] = useState<Scale[]>([]);
  const [loading, setLoading] = useState(false);
  const [picking, setPicking] = useState(false);
  const [vacancy, setVacancy] = useState<VacancyShape>(initial);

  const snapshot = vacancy.assessment_scale_snapshot ?? null;
  const lockedBySnapshot = Boolean(snapshot);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.get<Scale[]>("/v1/tenants/me/assessment-scales");
      setScales(rows);
    } catch {
      setScales([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const activeScale = (() => {
    if (snapshot) {
      return {
        name: snapshot.name ?? t("vacancyScaleSnapshotFallback"),
        levels: snapshot.levels ?? [],
      };
    }
    if (vacancy.assessment_scale_id) {
      const found = scales.find((s) => s.id === vacancy.assessment_scale_id);
      if (found) return { name: found.name, levels: found.levels };
    }
    const def = scales.find((s) => s.is_default && !s.archived_at);
    if (def) return { name: def.name, levels: def.levels };
    return null;
  })();

  async function selectScale(scaleId: string) {
    setPicking(true);
    try {
      await api.patch(
        `/v1/vacancies/${vacancyId}/assessment-scale`,
        { assessment_scale_id: scaleId },
      );
      const next = {
        ...vacancy,
        assessment_scale_id: scaleId,
      } satisfies VacancyShape;
      setVacancy(next);
      onScaleChanged?.(next);
      toast.success(t("vacancyScaleToastUpdated"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("scaleUpdateFailed"));
    } finally {
      setPicking(false);
    }
  }

  return (
    <div
      className="rounded-lg border bg-muted/30 p-3"
      data-testid="vacancy-overview-scale-display"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="space-y-0.5">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            {t("vacancyScaleHeading")}
          </p>
          {activeScale ? (
            <p className="text-sm font-medium">
              {activeScale.name}
              <span className="ml-1 text-xs text-muted-foreground">
                {t("vacancyScaleLevels", {
                  count: activeScale.levels.length,
                })}
              </span>
              {lockedBySnapshot && (
                <Badge variant="outline" className="ml-2 text-[10px]">
                  {t("vacancyScaleSnapshotLocked")}
                </Badge>
              )}
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">
              {t("vacancyScaleNone")}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {loading ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <select
              className="rounded-md border px-2 py-1 text-xs"
              value={vacancy.assessment_scale_id ?? ""}
              disabled={lockedBySnapshot || picking}
              onChange={(e) => {
                if (e.target.value) void selectScale(e.target.value);
              }}
              data-testid="vacancy-overview-scale-select"
            >
              <option value="">
                {activeScale
                  ? t("vacancyScaleCurrentOption", { name: activeScale.name })
                  : t("vacancyScalePick")}
              </option>
              {scales.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                  {s.is_default ? t("vacancyScaleDefaultSuffix") : ""}
                  {s.archived_at ? t("vacancyScaleArchivedSuffix") : ""}
                </option>
              ))}
            </select>
          )}
          <Button
            size="sm"
            variant="ghost"
            onClick={load}
            disabled={loading}
            data-testid="vacancy-overview-scale-change-btn"
          >
            {t("actionRefresh")}
          </Button>
        </div>
      </div>
      {lockedBySnapshot && (
        <p className="mt-1 text-[11px] text-muted-foreground">
          {t("vacancyScaleFrozen")}
        </p>
      )}
    </div>
  );
}
