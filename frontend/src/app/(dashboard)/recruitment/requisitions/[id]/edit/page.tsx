"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { Vacancy } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";
import { ALERT_TONE } from "@/lib/badge-tones";
import {
  VacancyForm,
  emptyVacancyForm,
  vacancyFormToPayload,
  vacancyToFormValues,
  type VacancyFormValues,
} from "../../_components/VacancyForm";

const SKELETON_MIN_MS = 600;

export default function EditVacancyPage() {
  const { id } = useParams<{ id: string }>();
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const router = useRouter();
  const [form, setForm] = useState<VacancyFormValues>(emptyVacancyForm);
  const initialRef = useRef<VacancyFormValues>(emptyVacancyForm);
  const [etag, setEtag] = useState<string | null>(null);
  const [vacancy, setVacancy] = useState<Vacancy | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const loadVacancy = useCallback(async () => {
    setLoading(true);
    const start = performance.now();
    try {
      const { data, headers } = await api.getWithMeta<Vacancy>(
        `/recruitment/vacancies/${id}`,
      );
      setVacancy(data);
      setEtag(headers.get("ETag"));
      const values = vacancyToFormValues(data as unknown as Record<string, unknown>);
      initialRef.current = values;
      setForm(values);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("vacancyLoadFailed"));
    } finally {
      const elapsed = performance.now() - start;
      const remain = Math.max(0, SKELETON_MIN_MS - elapsed);
      window.setTimeout(() => setLoading(false), remain);
    }
  }, [id, t]);

  useEffect(() => {
    void loadVacancy();
  }, [loadVacancy]);

  const isDirty =
    JSON.stringify(form) !== JSON.stringify(initialRef.current);

  useEffect(() => {
    function handleBeforeUnload(e: BeforeUnloadEvent) {
      if (isDirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [isDirty]);

  async function handleSave() {
    if (!form.title.trim()) {
      toast.error(t("vacancyTitleRequired"));
      return;
    }
    setSaving(true);
    try {
      const payload = vacancyFormToPayload(form);
      const headers: Record<string, string> = {};
      if (etag) headers["If-Match"] = etag;
      await api.patch<Vacancy>(`/recruitment/vacancies/${id}`, payload, {
        headers,
      });
      toast.success(t("vacancyToastUpdated"));
      router.push(`/recruitment/requisitions/${id}`);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : t("vacancyUpdateFailed");
      if (err && typeof err === "object" && "status" in err && err.status === 412) {
        toast.error(t("vacancyConflictReload"));
      } else {
        toast.error(message);
      }
    } finally {
      setSaving(false);
    }
  }

  function handleCancel() {
    if (isDirty && !window.confirm(t("vacancyLeaveUnsavedConfirm"))) {
      return;
    }
    router.push(`/recruitment/requisitions/${id}`);
  }

  if (loading) {
    return (
      <div className="space-y-4 py-12 text-center text-muted-foreground">
        {tc("loading")}
      </div>
    );
  }

  if (vacancy?.archived_at) {
    return (
      <div className="space-y-6">
        <RecruitmentBreadcrumbs
          segments={[
            { label: t("vacanciesTitle"), href: "/recruitment/requisitions" },
            { label: vacancy.title, href: `/recruitment/requisitions/${id}` },
            { label: t("actionEdit") },
          ]}
        />
        <div
          data-testid="vacancy-archived-banner"
          className={`rounded-md border p-4 text-sm ${ALERT_TONE.yellow}`}
        >
          {t("vacancyArchivedBanner")}
        </div>
        <VacancyForm
          values={form}
          onChange={() => {}}
          disabled
          testId="vacancy-edit-form"
          footer={
            <Button variant="outline" onClick={handleCancel}>
              {t("actionBack")}
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <RecruitmentBreadcrumbs
        segments={[
          { label: t("vacanciesTitle"), href: "/recruitment/requisitions" },
          {
            label: vacancy?.title ?? t("actionEdit"),
            href: `/recruitment/requisitions/${id}`,
          },
          { label: t("actionEdit") },
        ]}
      />
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {t("vacancyEditTitle")}
        </h1>
        <p className="text-sm text-muted-foreground">
          {t("vacancyEditDescription")}
        </p>
      </div>

      <VacancyForm
        values={form}
        onChange={setForm}
        disabled={saving}
        testId="vacancy-edit-form"
        footer={
          <>
            <Button
              variant="outline"
              data-testid="vacancy-edit-form-cancel"
              onClick={handleCancel}
              disabled={saving}
            >
              {tc("cancel")}
            </Button>
            <Button
              data-testid="vacancy-edit-form-save"
              onClick={handleSave}
              disabled={saving || !isDirty}
            >
              {saving ? t("actionSaving") : t("actionSaveChanges")}
            </Button>
          </>
        }
      />
    </div>
  );
}
