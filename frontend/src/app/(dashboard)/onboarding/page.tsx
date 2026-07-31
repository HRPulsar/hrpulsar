"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import {
  aiSettingsApi,
  CONTENT_LANGUAGES,
  type ContentLanguage,
} from "@/lib/api/ai-settings";
import { getBrandName } from "@/lib/brand";
import { getAvailableLocales, getDefaultLocale, localeLabel } from "@/lib/locale";
import { useAuth } from "@/context/auth-context";
import type { Division } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import {
  Building2,
  GitBranch,
  Users,
  BookOpen,
  Check,
  ArrowRight,
  ArrowLeft,
  Languages,
} from "lucide-react";

const COMPANY_SIZES = [
  "1-10",
  "11-50",
  "51-200",
  "201-500",
  "501-1000",
  "1001-5000",
  "5000+",
];

/** Wizard steps — `labelKey` resolves in the `onboarding` namespace (same
 * label-key pattern as SEGMENT_KEYS in header.tsx). */
const STEPS = [
  { labelKey: "stepLanguage", icon: Languages },
  { labelKey: "stepCompanyInfo", icon: Building2 },
  { labelKey: "stepFirstDivision", icon: GitBranch },
  { labelKey: "stepInviteTeam", icon: Users },
  { labelKey: "stepCompetences", icon: BookOpen },
];

interface OnboardingStatus {
  needs_onboarding: boolean;
  onboarding_completed: boolean;
  employee_count: number;
  division_count: number;
  has_invitations: boolean;
}

export default function OnboardingPage() {
  const router = useRouter();
  const t = useTranslations("onboarding");
  const tCommon = useTranslations("common");
  const { user } = useAuth();
  const [step, setStep] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Step 0: Language — two independent settings (see I18N plan): the
  // interface locale (tenant default) and the AI content language.
  const availableLocales = getAvailableLocales();
  const initialUiLocale = user?.tenant_default_locale || getDefaultLocale();
  const [uiLocale, setUiLocale] = useState(initialUiLocale);
  const [contentLanguage, setContentLanguage] = useState<ContentLanguage>(
    // Pre-select the workspace language when the AI can generate in it —
    // a German-first deployment should not default AI output to English.
    // The save handler PATCHes only a non-"en" (= non-default) choice.
    CONTENT_LANGUAGES.includes(initialUiLocale as ContentLanguage)
      ? (initialUiLocale as ContentLanguage)
      : "en",
  );

  // Step 1: Company Info
  const [companyForm, setCompanyForm] = useState({
    industry: "",
    company_size: "",
    website: "",
    description: "",
  });

  // Step 2: Division
  const [divisionName, setDivisionName] = useState("");
  const [divisionDesc, setDivisionDesc] = useState("");
  const [createdDivisions, setCreatedDivisions] = useState<Division[]>([]);

  // Step 3: Invitations
  const [inviteEmails, setInviteEmails] = useState<string[]>([""]);
  const [sentCount, setSentCount] = useState(0);

  // Check if onboarding is needed
  useEffect(() => {
    async function check() {
      try {
        const status = await api.get<OnboardingStatus>("/onboarding/status");
        if (!status.needs_onboarding) {
          router.replace("/dashboard");
          return;
        }
      } catch {
        router.replace("/dashboard");
        return;
      } finally {
        setLoading(false);
      }
    }
    check();
  }, [router]);

  // Step 0: Save language choices
  async function saveLanguageStep() {
    setSaving(true);
    try {
      // Write only an actual change: an untouched select keeps
      // tenants.default_locale NULL so the tenant keeps inheriting the
      // deployment default, and non-admin visitors (the endpoint is
      // admin-only) can still advance past this step.
      if (availableLocales.length > 1 && uiLocale !== initialUiLocale) {
        await api.put("/settings/company-profile", { default_locale: uiLocale });
      }
      // "en" is the backend default; PATCH only an actual change.
      if (contentLanguage !== "en") {
        await aiSettingsApi.update({ content_language: contentLanguage });
      }
      setStep(1);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setSaving(false);
    }
  }

  // Step 1: Save company profile
  async function saveCompanyInfo() {
    setSaving(true);
    try {
      const payload: Record<string, string | null> = {};
      if (companyForm.industry) payload.industry = companyForm.industry;
      if (companyForm.company_size) payload.company_size = companyForm.company_size;
      if (companyForm.website) payload.website = companyForm.website;
      if (companyForm.description) payload.description = companyForm.description;

      if (Object.keys(payload).length > 0) {
        await api.put("/settings/company-profile", payload);
        toast.success(t("companySaved"));
      }
      setStep(2);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setSaving(false);
    }
  }

  // Step 2: Create division
  async function createDivision() {
    if (!divisionName.trim()) {
      setStep(3);
      return;
    }
    setSaving(true);
    try {
      const div = await api.post<Division>("/divisions", {
        name: divisionName.trim(),
        description: divisionDesc.trim() || null,
      });
      setCreatedDivisions((prev) => [...prev, div]);
      setDivisionName("");
      setDivisionDesc("");
      toast.success(t("divisionCreated", { name: div.name }));
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("divisionCreateFailed"),
      );
    } finally {
      setSaving(false);
    }
  }

  // Step 3: Send invitations
  async function sendInvitations() {
    const emails = inviteEmails.filter((e) => e.trim());
    if (emails.length === 0) {
      setStep(4);
      return;
    }
    setSaving(true);
    let sent = 0;
    for (const email of emails) {
      try {
        await api.post("/invitations", { email: email.trim(), role_code: "employee" });
        sent++;
      } catch {
        // skip failed
      }
    }
    setSentCount(sent);
    if (sent > 0) toast.success(t("invitationsSent", { count: sent }));
    setSaving(false);
    setStep(4);
  }

  // Complete onboarding
  async function completeOnboarding() {
    setSaving(true);
    try {
      await api.post("/onboarding/complete");
      toast.success(t("setupComplete"));
      router.replace("/dashboard");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("completeFailed"));
    } finally {
      setSaving(false);
    }
  }

  // Skip entire wizard
  async function skipOnboarding() {
    await completeOnboarding();
  }

  const updateInviteEmail = useCallback(
    (index: number, value: string) => {
      setInviteEmails((prev) => {
        const next = [...prev];
        next[index] = value;
        return next;
      });
    },
    [],
  );

  function addEmailField() {
    setInviteEmails((prev) => [...prev, ""]);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        {tCommon("loading")}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6 py-8">
      <div className="text-center">
        <h1 className="text-2xl font-semibold tracking-tight">
          {t("welcome", { brand: getBrandName() })}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("subtitle")}</p>
      </div>

      {/* Step indicator */}
      <div className="flex items-center justify-center gap-2">
        {STEPS.map((s, i) => {
          const Icon = s.icon;
          const isActive = i === step;
          const isDone = i < step;
          return (
            <div key={s.labelKey} className="flex items-center gap-2">
              {i > 0 && (
                <div
                  className={`h-px w-8 ${isDone ? "bg-primary" : "bg-border"}`}
                />
              )}
              <div
                data-testid={`onboarding-step-${i}`}
                className={`flex h-8 w-8 items-center justify-center rounded-full text-xs ${
                  isDone
                    ? "bg-primary text-primary-foreground"
                    : isActive
                      ? "border-2 border-primary text-primary"
                      : "border border-border text-muted-foreground"
                }`}
              >
                {isDone ? <Check className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
              </div>
            </div>
          );
        })}
      </div>

      {/* Step content */}
      <Card data-testid="onboarding-form">
        <CardHeader>
          <CardTitle className="text-lg">{t(STEPS[step].labelKey)}</CardTitle>
        </CardHeader>
        <CardContent>
          {step === 0 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                {t("languageIntro")}
              </p>
              {availableLocales.length > 1 && (
                <div className="space-y-2">
                  <Label>{t("interfaceLanguage")}</Label>
                  <Select value={uiLocale} onValueChange={setUiLocale}>
                    <SelectTrigger
                      className="w-full"
                      data-testid="onboarding-select-ui-language"
                    >
                      {/* Radix renders the raw value until the portal
                          content mounts — pass the label explicitly. */}
                      <SelectValue>{localeLabel(uiLocale)}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {availableLocales.map((locale) => (
                        <SelectItem key={locale} value={locale}>
                          {localeLabel(locale)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    {t("interfaceLanguageHint")}
                  </p>
                </div>
              )}
              <div className="space-y-2">
                <Label>{t("contentLanguage")}</Label>
                <Select
                  value={contentLanguage}
                  onValueChange={(v) => setContentLanguage(v as ContentLanguage)}
                >
                  <SelectTrigger
                    className="w-full"
                    data-testid="onboarding-select-content-language"
                  >
                    <SelectValue>{localeLabel(contentLanguage)}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {CONTENT_LANGUAGES.map((lang) => (
                      <SelectItem key={lang} value={lang}>
                        {localeLabel(lang)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {t("contentLanguageHint")}
                </p>
              </div>
              <div className="flex justify-between pt-2">
                <Button variant="ghost" onClick={skipOnboarding} disabled={saving}>
                  {t("skipSetup")}
                </Button>
                <Button onClick={saveLanguageStep} disabled={saving} data-testid="onboarding-btn-next">
                  {saving ? t("saving") : t("next")}
                  <ArrowRight className="ml-1 h-4 w-4" />
                </Button>
              </div>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                {t("companyIntro")}
              </p>
              <div className="space-y-2">
                <Label>{t("industry")}</Label>
                <Input
                  placeholder={t("industryPlaceholder")}
                  value={companyForm.industry}
                  onChange={(e) =>
                    setCompanyForm({ ...companyForm, industry: e.target.value })
                  }
                />
              </div>
              <div className="space-y-2">
                <Label>{t("companySize")}</Label>
                <Select
                  value={companyForm.company_size}
                  onValueChange={(val) =>
                    setCompanyForm({ ...companyForm, company_size: val })
                  }
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder={t("selectSize")} />
                  </SelectTrigger>
                  <SelectContent>
                    {COMPANY_SIZES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {t("sizeEmployees", { size: s })}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{t("website")}</Label>
                <Input
                  placeholder={t("websitePlaceholder")}
                  value={companyForm.website}
                  onChange={(e) =>
                    setCompanyForm({ ...companyForm, website: e.target.value })
                  }
                />
              </div>
              <div className="space-y-2">
                <Label>{t("description")}</Label>
                <Textarea
                  placeholder={t("descriptionPlaceholder")}
                  value={companyForm.description}
                  onChange={(e) =>
                    setCompanyForm({ ...companyForm, description: e.target.value })
                  }
                  rows={3}
                />
              </div>
              <div className="flex justify-between pt-2">
                <Button variant="outline" onClick={() => setStep(0)} disabled={saving} data-testid="onboarding-btn-back">
                  <ArrowLeft className="mr-1 h-4 w-4" />
                  {t("back")}
                </Button>
                <Button onClick={saveCompanyInfo} disabled={saving} data-testid="onboarding-btn-next">
                  {saving ? t("saving") : t("next")}
                  <ArrowRight className="ml-1 h-4 w-4" />
                </Button>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                {t("divisionIntro")}
              </p>
              {createdDivisions.length > 0 && (
                <div className="space-y-1">
                  <Label className="text-muted-foreground">{t("created")}</Label>
                  {createdDivisions.map((d) => (
                    <div
                      key={d.id}
                      className="flex items-center gap-2 rounded-md bg-muted/50 px-3 py-1.5 text-sm"
                    >
                      <Check className="h-3.5 w-3.5 text-green-600" />
                      {d.name}
                    </div>
                  ))}
                </div>
              )}
              <div className="space-y-2">
                <Label>{t("divisionName")}</Label>
                <Input
                  placeholder={t("divisionNamePlaceholder")}
                  value={divisionName}
                  onChange={(e) => setDivisionName(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label>{t("description")}</Label>
                <Input
                  placeholder={t("divisionDescPlaceholder")}
                  value={divisionDesc}
                  onChange={(e) => setDivisionDesc(e.target.value)}
                />
              </div>
              <div className="flex items-center justify-between pt-2">
                <Button variant="outline" onClick={() => setStep(1)} disabled={saving} data-testid="onboarding-btn-back">
                  <ArrowLeft className="mr-1 h-4 w-4" />
                  {t("back")}
                </Button>
                <div className="flex gap-2">
                  {divisionName.trim() && (
                    <Button variant="outline" onClick={createDivision} disabled={saving}>
                      {saving ? t("creating") : t("addAnotherDivision")}
                    </Button>
                  )}
                  <Button
                    onClick={async () => {
                      if (divisionName.trim()) await createDivision();
                      setStep(3);
                    }}
                    disabled={saving}
                    data-testid="onboarding-btn-next"
                  >
                    {saving ? t("creating") : t("next")}
                    <ArrowRight className="ml-1 h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                {t("inviteIntro")}
              </p>
              {inviteEmails.map((email, i) => (
                <div key={i} className="space-y-2">
                  <Label>{i === 0 ? t("emailAddresses") : ""}</Label>
                  <Input
                    type="email"
                    placeholder={t("emailPlaceholder")}
                    value={email}
                    onChange={(e) => updateInviteEmail(i, e.target.value)}
                  />
                </div>
              ))}
              <Button
                variant="ghost"
                size="sm"
                onClick={addEmailField}
                className="text-muted-foreground"
              >
                {t("addAnotherEmail")}
              </Button>
              <div className="flex items-center justify-between pt-2">
                <Button variant="outline" onClick={() => setStep(2)} disabled={saving} data-testid="onboarding-btn-back">
                  <ArrowLeft className="mr-1 h-4 w-4" />
                  {t("back")}
                </Button>
                <Button
                  onClick={async () => {
                    await sendInvitations();
                  }}
                  disabled={saving}
                  data-testid="onboarding-btn-next"
                >
                  {saving
                    ? t("sending")
                    : inviteEmails.some((e) => e.trim())
                      ? t("sendAndNext")
                      : t("skip")}
                  <ArrowRight className="ml-1 h-4 w-4" />
                </Button>
              </div>
            </div>
          )}

          {step === 4 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                {t("competencesIntro")}
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={() => {
                    completeOnboarding();
                    router.replace("/competences");
                  }}
                  className="rounded-lg border p-4 text-left transition-colors hover:bg-muted/50"
                >
                  <BookOpen className="mb-2 h-5 w-5 text-primary" />
                  <div className="font-medium">{t("browseImport")}</div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("browseImportHint")}
                  </p>
                </button>
                <button
                  type="button"
                  onClick={completeOnboarding}
                  className="rounded-lg border p-4 text-left transition-colors hover:bg-muted/50"
                >
                  <Users className="mb-2 h-5 w-5 text-primary" />
                  <div className="font-medium">{t("setupLater")}</div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("setupLaterHint")}
                  </p>
                </button>
              </div>
              {sentCount > 0 && (
                <p className="text-sm text-muted-foreground">
                  {t("invitationsSentSummary", { count: sentCount })}
                </p>
              )}
              <div className="flex items-center justify-between pt-2">
                <Button variant="outline" onClick={() => setStep(3)} disabled={saving} data-testid="onboarding-btn-back">
                  <ArrowLeft className="mr-1 h-4 w-4" />
                  {t("back")}
                </Button>
                <Button onClick={completeOnboarding} disabled={saving} data-testid="onboarding-btn-finish">
                  {saving ? t("finishing") : t("finishSetup")}
                  <Check className="ml-1 h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
