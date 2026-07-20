"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Vacancy } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { CanvasGrid } from "@/components/recruitment/canvas";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";
import { ArrowLeft } from "lucide-react";

export default function VacancyCanvasPage() {
  const { id } = useParams<{ id: string }>();
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
          { label: "Vacancies", href: "/recruitment/requisitions" },
          {
            label: vacancy?.title || "Vacancy",
            href: `/recruitment/requisitions/${id}`,
          },
          { label: "Canvas" },
        ]}
      />
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Evaluation Canvas
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
              <ArrowLeft className="mr-1 size-4" /> Back to vacancy
            </Link>
          }
        />
      </div>

      {/* Mobile fallback banner */}
      <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground md:hidden">
        This page works best on a computer: the &ldquo;candidates × competences&rdquo; matrix is designed for a wide screen.
      </p>

      <CanvasGrid vacancyId={id} mode="fullscreen" />
    </div>
  );
}
