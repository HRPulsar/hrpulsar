"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { Vacancy } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { CanvasGrid } from "@/components/recruitment/canvas";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";
import { ArrowLeft } from "lucide-react";

export default function VacancyCanvasPage() {
  const { id } = useParams<{ id: string }>();
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [vacancy, setVacancy] = useState<Vacancy | null>(null);

  useEffect(() => {
    api.get<Vacancy>(`/recruitment/vacancies/${id}`)
      .then(setVacancy)
      .catch(() => {});
  }, [id]);

  return (
    <div data-testid="recruitment-canvas-fullscreen" className="space-y-4">
      <RecruitmentBreadcrumbs
        segments={[
          { label: t("vacanciesTitle"), href: "/recruitment/requisitions" },
          {
            label: vacancy?.title || tc("vacancy"),
            href: `/recruitment/requisitions/${id}`,
          },
          { label: t("canvasBreadcrumb") },
        ]}
      />
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("canvasTitle")}
          </h1>
          {vacancy && (
            <p className="text-sm text-muted-foreground">{vacancy.title}</p>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          render={
            <Link href={`/recruitment/requisitions/${id}`}>
              <ArrowLeft className="mr-1 size-4" /> {t("vacancyBackToVacancy")}
            </Link>
          }
        />
      </div>

      {/* Mobile fallback banner */}
      <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground md:hidden">
        {t("canvasMobileHint")}
      </p>

      <CanvasGrid vacancyId={id} mode="fullscreen" />
    </div>
  );
}
