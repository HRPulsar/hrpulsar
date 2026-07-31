"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { Candidate } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";
// HRP-476: labels live in the `recruitment` i18n namespace; the shared
// dictionary owns the API code → key relation for every source surface.
import {
  CANDIDATE_SOURCE_OPTIONS,
  candidateSourceKey,
  candidateSourceLabel,
} from "@/lib/candidate-source";

const emptyForm = {
  first_name: "",
  last_name: "",
  middle_name: "",
  email: "",
  phone: "",
  source: "manual",
  notes: "",
};

export default function NewCandidatePage() {
  const router = useRouter();
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  function updateField(field: keyof typeof emptyForm, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleManualSubmit() {
    if (!form.first_name.trim() || !form.last_name.trim()) {
      toast.error(t("candidateNameRequired"));
      return;
    }

    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
        middle_name: form.middle_name.trim() || null,
        email: form.email.trim() || null,
        phone: form.phone.trim() || null,
        source: form.source || null,
        notes: form.notes.trim() || null,
      };
      const candidate = await api.post<Candidate>(
        "/recruitment/candidates",
        payload,
      );
      toast.success(t("candidateToastCreated"));
      router.push(`/recruitment/candidates/${candidate.id}`);
    } catch (err) {
      const message =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : t("candidateCreateFailed");
      toast.error(message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div data-testid="recruitment-candidate-new" className="space-y-6">
      <RecruitmentBreadcrumbs
        segments={[
          { label: t("candidatesTitle"), href: "/recruitment/candidates" },
          { label: t("candidateNewBreadcrumb") },
        ]}
      />

      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {t("candidateAddButton")}
        </h1>
        <p className="text-sm text-muted-foreground">
          {t("candidateNewDescription")}
        </p>
      </div>

      <div className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="last_name">{t("candidateLastNameLabel")}</Label>
            <Input
              id="last_name"
              data-testid="recruitment-candidate-input-last-name"
              value={form.last_name}
              onChange={(e) => updateField("last_name", e.target.value)}
              disabled={saving}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="first_name">{t("candidateFirstNameLabel")}</Label>
            <Input
              id="first_name"
              data-testid="recruitment-candidate-input-first-name"
              value={form.first_name}
              onChange={(e) => updateField("first_name", e.target.value)}
              disabled={saving}
            />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="middle_name">{t("candidateMiddleNameLabel")}</Label>
          <Input
            id="middle_name"
            data-testid="recruitment-candidate-input-middle-name"
            value={form.middle_name}
            onChange={(e) => updateField("middle_name", e.target.value)}
            disabled={saving}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="email">{t("columnEmail")}</Label>
            <Input
              id="email"
              type="email"
              data-testid="recruitment-candidate-input-email"
              value={form.email}
              onChange={(e) => updateField("email", e.target.value)}
              disabled={saving}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="phone">{t("candidateFieldPhone")}</Label>
            <Input
              id="phone"
              data-testid="recruitment-candidate-input-phone"
              value={form.phone}
              onChange={(e) => updateField("phone", e.target.value)}
              disabled={saving}
            />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="source">{t("columnSource")}</Label>
          <Select
            value={form.source}
            onValueChange={(val) => updateField("source", val)}
          >
            <SelectTrigger
              className="w-full sm:w-56"
              data-testid="recruitment-candidate-select-source-new"
            >
              <SelectValue placeholder={t("candidateSelectSource")}>
                {candidateSourceKey(form.source)
                  ? candidateSourceLabel(t, form.source)
                  : t("candidateSelectSource")}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {CANDIDATE_SOURCE_OPTIONS.map((s) => (
                <SelectItem key={s} value={s}>
                  {candidateSourceLabel(t, s)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="notes">{t("candidateFieldNotes")}</Label>
          <Textarea
            id="notes"
            data-testid="recruitment-candidate-input-notes"
            placeholder={t("candidateNotesPlaceholder")}
            value={form.notes}
            onChange={(e) => updateField("notes", e.target.value)}
            rows={4}
            disabled={saving}
          />
        </div>

        <div className="flex items-center justify-end gap-3 border-t pt-4">
          <Button
            variant="outline"
            data-testid="recruitment-candidate-btn-cancel"
            onClick={() => router.push("/recruitment/candidates")}
            disabled={saving}
          >
            {tc("cancel")}
          </Button>
          <Button
            data-testid="recruitment-candidate-btn-create"
            onClick={handleManualSubmit}
            disabled={saving}
          >
            {saving ? t("actionCreating") : t("candidateCreateButton")}
          </Button>
        </div>
      </div>
    </div>
  );
}
