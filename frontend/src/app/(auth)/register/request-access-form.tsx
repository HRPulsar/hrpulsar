"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AuthLogo } from "@/components/auth-logo";
import { createSignupRequest } from "@/lib/signup";
import { TURNSTILE_FAILED_MESSAGE_KEY, useTurnstileGate } from "@/lib/turnstile";

/** Role values sent to the API; labels come from the `auth` catalog. */
const ROLE_VALUES = [
  "hr",
  "recruiter",
  "manager",
  "founder",
  "other",
] as const;

const ROLE_LABEL_KEY: Record<(typeof ROLE_VALUES)[number], string> = {
  hr: "roleHr",
  recruiter: "roleRecruiter",
  manager: "roleManager",
  founder: "roleFounder",
  other: "roleOther",
};

export function RequestAccessForm() {
  const t = useTranslations("auth");
  const tc = useTranslations("common");
  const router = useRouter();
  const [form, setForm] = useState({
    email: "",
    first_name: "",
    last_name: "",
    company_name: "",
    role: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const turnstile = useTurnstileGate();

  function update(field: string, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!turnstile.isReady) return;
    setError("");
    setLoading(true);

    try {
      await createSignupRequest({
        email: form.email,
        first_name: form.first_name,
        last_name: form.last_name || null,
        company_name: form.company_name || null,
        role: form.role || null,
        turnstile_token: turnstile.token,
      });
      router.push(
        `/verify-email?email=${encodeURIComponent(form.email)}&flow=signup`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : t("requestFailed"));
      // Single-use token was burned; reset so retry waits for fresh.
      turnstile.reset();
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col items-center gap-8">
      <AuthLogo />
      <Card className="w-full max-w-sm border-white/10 bg-black/40 backdrop-blur-xl">
        <CardHeader className="text-center">
          <CardTitle className="text-xl text-white">
            {t("requestAccess")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={handleSubmit}
            className="space-y-4"
            data-testid="register-form"
          >
            {error && (
              <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </div>
            )}
            <p className="text-sm text-white/60">{t("requestAccessIntro")}</p>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="first_name" className="text-white/70">
                  {t("firstName")}
                </Label>
                <Input
                  id="first_name"
                  value={form.first_name}
                  onChange={(e) => update("first_name", e.target.value)}
                  className="border-white/10 bg-white/5 text-white placeholder:text-white/30"
                  required
                  data-testid="register-input-firstname"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="last_name" className="text-white/70">
                  {t("lastName")}
                </Label>
                <Input
                  id="last_name"
                  value={form.last_name}
                  onChange={(e) => update("last_name", e.target.value)}
                  className="border-white/10 bg-white/5 text-white placeholder:text-white/30"
                  data-testid="register-input-lastname"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="company" className="text-white/70">
                {t("companyName")}
              </Label>
              <Input
                id="company"
                value={form.company_name}
                onChange={(e) => update("company_name", e.target.value)}
                className="border-white/10 bg-white/5 text-white placeholder:text-white/30"
                data-testid="register-input-company"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email" className="text-white/70">
                {t("workEmail")}
              </Label>
              <Input
                id="email"
                type="email"
                placeholder={t("emailPlaceholder")}
                value={form.email}
                onChange={(e) => update("email", e.target.value)}
                className="border-white/10 bg-white/5 text-white placeholder:text-white/30"
                required
                data-testid="register-input-email"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="role" className="text-white/70">
                {t("role")}
              </Label>
              <select
                id="role"
                value={form.role}
                onChange={(e) => update("role", e.target.value)}
                className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white"
                data-testid="register-select-role"
              >
                <option value="" className="bg-black text-white">
                  {t("chooseRole")}
                </option>
                {ROLE_VALUES.map((value) => (
                  <option
                    key={value}
                    value={value}
                    className="bg-black text-white"
                  >
                    {t(ROLE_LABEL_KEY[value])}
                  </option>
                ))}
              </select>
            </div>
            {turnstile.failed && (
              <div
                className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
                data-testid="register-verify-error"
              >
                {t(TURNSTILE_FAILED_MESSAGE_KEY)}{" "}
                <button
                  type="button"
                  onClick={turnstile.reset}
                  className="font-semibold underline"
                  data-testid="register-verify-retry"
                >
                  {t("retry")}
                </button>
              </div>
            )}
            <Button
              type="submit"
              className="w-full"
              disabled={loading || !turnstile.isReady}
              data-testid="register-btn-submit"
            >
              {loading
                ? t("sendingRequest")
                : !turnstile.isReady && !turnstile.failed
                  ? t("verifying")
                  : t("requestAccess")}
            </Button>
            {turnstile.widget}
          </form>
          <p className="mt-4 text-center text-sm text-white/50">
            {t("haveAccount")}{" "}
            <a
              href="/login"
              className="text-brand hover:underline"
              data-testid="register-link-login"
            >
              {tc("signIn")}
            </a>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
