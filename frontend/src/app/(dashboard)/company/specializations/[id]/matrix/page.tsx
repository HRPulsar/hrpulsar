"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { api } from "@/lib/api";
import {
  specializationsApi,
  type MatrixBulk,
  type SpecializationDetail,
} from "@/lib/api/specializations";
import type { Competence, CompetenceGroupTree, SkillLevel } from "@/lib/types";
import { useCompetenceTree } from "@/hooks/use-competence-tree";
import { MatrixEditor } from "@/components/specialization/matrix-editor";

function flattenCompetences(tree: CompetenceGroupTree[]): Competence[] {
  const out: Competence[] = [];
  function walk(node: CompetenceGroupTree) {
    for (const comp of node.competences) {
      if (comp.is_active) out.push(comp);
    }
    for (const child of node.children) walk(child);
  }
  for (const root of tree) walk(root);
  return out;
}

export default function SpecializationMatrixPage() {
  const t = useTranslations("company");
  const tc = useTranslations("common");
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const id = params?.id;
  const highlightedGradeId = search?.get("grade_id") ?? null;
  // HRP-54: matrix opened from a position page carries `from=position&
  // position_id=...` so we can swap the breadcrumb for a direct return
  // link instead of routing through the spec detail page.
  const fromPositionId =
    search?.get("from") === "position" ? search?.get("position_id") ?? null : null;

  const [detail, setDetail] = useState<SpecializationDetail | null>(null);
  const [bulk, setBulk] = useState<MatrixBulk | null>(null);
  const [skillLevels, setSkillLevels] = useState<SkillLevel[]>([]);
  const [loading, setLoading] = useState(true);

  const { tree } = useCompetenceTree();
  const competencesPool = useMemo(() => flattenCompetences(tree), [tree]);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      try {
        const [d, m, levels] = await Promise.all([
          specializationsApi.get(id),
          specializationsApi.matrixBulk(id),
          api.get<SkillLevel[]>("/skill-levels"),
        ]);
        if (!cancelled) {
          setDetail(d);
          setBulk(m);
          setSkillLevels(levels);
        }
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : t("toastMatrixLoadFailed"),
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, t]);

  if (loading) {
    return (
      <div className="py-12 text-center text-sm text-muted-foreground">
        {tc("loading")}
      </div>
    );
  }

  if (!detail || !bulk) {
    return (
      <div className="py-12 text-center text-sm text-muted-foreground">
        {t("specializationNotFound")}
      </div>
    );
  }

  if (bulk.grades.length === 0) {
    return (
      <div className="space-y-4">
        {fromPositionId ? (
          <Link
            href={`/company/positions/${fromPositionId}`}
            data-testid="matrix-page-back-to-position"
            className="text-xs text-muted-foreground hover:underline"
          >
            {t("backToPosition")}
          </Link>
        ) : (
          <Link
            href={`/company/specializations/${id}`}
            className="text-xs text-muted-foreground hover:underline"
          >
            ← {detail.title}
          </Link>
        )}
        <h1 className="text-2xl font-semibold tracking-tight">
          {t("competenceMatrix")}
        </h1>
        <p
          data-testid="matrix-no-grades"
          className="rounded-lg border bg-muted/30 py-12 text-center text-sm text-muted-foreground"
        >
          {t("matrixNoGrades")}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="matrix-page">
      <div>
        {fromPositionId ? (
          <Link
            href={`/company/positions/${fromPositionId}`}
            data-testid="matrix-page-back-to-position"
            className="text-xs text-muted-foreground hover:underline"
          >
            {t("backToPosition")}
          </Link>
        ) : (
          <Link
            href={`/company/specializations/${id}`}
            className="text-xs text-muted-foreground hover:underline"
          >
            ← {detail.title}
          </Link>
        )}
        <h1
          data-testid="matrix-page-title"
          className="text-2xl font-semibold tracking-tight"
        >
          {t("competenceMatrix")}
        </h1>
        <p className="text-sm text-muted-foreground">{t("matrixPageHint")}</p>
      </div>

      <MatrixEditor
        specId={id!}
        bulk={bulk}
        skillLevels={skillLevels}
        competencesPool={competencesPool}
        competenceTree={tree}
        highlightedGradeId={highlightedGradeId}
        gradeMeta={detail.grades}
        onSaved={(next) => setBulk(next)}
        onGradesChanged={(grades) =>
          setDetail((prev) => (prev ? { ...prev, grades } : prev))
        }
      />
    </div>
  );
}
