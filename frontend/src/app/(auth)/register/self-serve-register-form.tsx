"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AuthLogo } from "@/components/auth-logo";
import { register, login, getLoginRedirect } from "@/lib/auth";

// HRP-390: self-hosted registration — creates the tenant and its admin
// account via POST /api/auth/register. When the backend auto-verifies
// (no email provider configured), the user is logged in right away;
// otherwise they land on the check-your-email screen.
export function SelfServeRegisterForm() {
  const t = useTranslations("auth");
  const tc = useTranslations("common");
  const router = useRouter();
  const [form, setForm] = useState({
    email: "",
    password: "",
    first_name: "",
    last_name: "",
    company_name: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  function update(field: string, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const resp = await register(form);
      if (resp.auto_verified) {
        try {
          const result = await login(form.email, form.password);
          router.push(getLoginRedirect(result));
        } catch {
          // Account exists and is verified — worst case the user signs
          // in manually.
          router.push("/login");
        }
      } else {
        router.push(`/verify-email?email=${encodeURIComponent(form.email)}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("registrationFailed"));
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col items-center gap-8">
      <AuthLogo />
      <Card className="w-full max-w-sm border-white/10 bg-black/40 backdrop-blur-xl">
        <CardHeader className="text-center">
          <CardTitle className="text-xl text-white">
            {t("createYourAccount")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={handleSubmit}
            className="space-y-4"
            data-testid="register-form"
          >
            {error && (
              <div
                className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
                data-testid="register-error"
              >
                {error}
              </div>
            )}
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
                  required
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
                required
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
              <Label htmlFor="password" className="text-white/70">
                {t("password")}
              </Label>
              <Input
                id="password"
                type="password"
                placeholder={t("passwordMinPlaceholder")}
                value={form.password}
                onChange={(e) => update("password", e.target.value)}
                className="border-white/10 bg-white/5 text-white placeholder:text-white/30"
                required
                minLength={8}
                data-testid="register-input-password"
              />
            </div>
            <Button
              type="submit"
              className="w-full"
              disabled={loading}
              data-testid="register-btn-submit"
            >
              {loading ? t("creatingAccount") : t("createAccount")}
            </Button>
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
