"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { Vacancy } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";
import { useAuth } from "@/context/auth-context";
import {
  VacancyForm,
  emptyVacancyForm,
  vacancyFormToPayload,
} from "../_components/VacancyForm";

export default function CreateVacancyPage() {
  const router = useRouter();
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const { user } = useAuth();
  // HRP-360: the Hiring manager field defaults to the current user. The
  // dashboard renders behind the AuthProvider gate, so `user` is already
  // loaded on first render — a lazy initializer is enough.
  const [form, setForm] = useState(() => ({
    ...emptyVacancyForm,
    hiring_manager_id: user?.id ?? null,
  }));
  const [saving, setSaving] = useState(false);

  async function handleSubmit(generateProfile: boolean) {
    if (!form.title.trim()) {
      toast.error(t("vacancyTitleRequired"));
      return;
    }

    setSaving(true);
    try {
      const payload = vacancyFormToPayload(form);
      const vacancy = await api.post<Vacancy>("/recruitment/vacancies", payload);

      // HRP-238: redirect immediately after the vacancy row is persisted
      // so the form does not appear frozen. When Save & Generate Profile
      // is requested we kick off generation with keepalive:true so the
      // browser does not abort the request during router.push navigation —
      // otherwise the session row may never be committed and the detail
      // page's ProfileGenerationStatus banner never appears.
      if (generateProfile) {
        // keepalive so the request survives the router.push below; errors are
        // surfaced on the detail page through the session row.
        void api
          .post(
            `/recruitment/vacancies/${vacancy.id}/profile/generate`,
            undefined,
            { keepalive: true },
          )
          .catch(() => {});
        toast.success(t("vacancyToastCreatedGenerating"));
        router.push(`/recruitment/requisitions/${vacancy.id}?gen=1`);
      } else {
        toast.success(t("vacancyToastSavedDraft"));
        router.push(`/recruitment/requisitions/${vacancy.id}`);
      }
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("vacancyCreateFailed"),
      );
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <RecruitmentBreadcrumbs
        segments={[
          { label: t("vacanciesTitle"), href: "/recruitment/requisitions" },
          { label: t("vacancyNewBreadcrumb") },
        ]}
      />
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {t("vacancyCreateButton")}
        </h1>
        <p className="text-sm text-muted-foreground">
          {t("vacancyCreateDescription")}
        </p>
      </div>

      <VacancyForm
        values={form}
        onChange={setForm}
        disabled={saving}
        footer={
          <>
            <Button
              variant="outline"
              data-testid="recruitment-vacancy-btn-cancel"
              onClick={() => router.push("/recruitment/requisitions")}
              disabled={saving}
            >
              {tc("cancel")}
            </Button>
            <Button
              variant="outline"
              data-testid="recruitment-vacancy-btn-save-draft"
              onClick={() => handleSubmit(false)}
              disabled={saving}
            >
              {saving ? t("actionSaving") : t("vacancySaveDraft")}
            </Button>
            <Button
              data-testid="recruitment-vacancy-btn-save-generate"
              onClick={() => handleSubmit(true)}
              disabled={saving}
            >
              {saving ? t("actionSaving") : t("vacancySaveAndGenerate")}
            </Button>
          </>
        }
      />
    </div>
  );
}
