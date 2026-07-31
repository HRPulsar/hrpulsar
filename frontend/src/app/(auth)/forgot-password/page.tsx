"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AuthLogo } from "@/components/auth-logo";

import { API_BASE } from "@/lib/api-base";

export default function ForgotPasswordPage() {
  const t = useTranslations("auth");
  const tc = useTranslations("common");
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/auth/forgot-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (!res.ok) {
        const body = await res
          .json()
          .catch(() => ({ detail: t("requestFailed") }));
        throw new Error(body.detail || t("requestFailed"));
      }
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("requestFailed"));
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
            {t("resetPassword")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {submitted ? (
            <div className="space-y-4 text-center">
              <p className="text-sm text-white/70">{t("resetLinkSent")}</p>
              <a href="/login" className="text-sm text-brand hover:underline">
                {t("backToSignIn")}
              </a>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4" data-testid="forgot-form">
              {error && (
                <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {error}
                </div>
              )}
              <p className="text-sm text-white/50">{t("forgotPasswordIntro")}</p>
              <div className="space-y-2">
                <Label htmlFor="email" className="text-white/70">
                  {t("email")}
                </Label>
                <Input
                  id="email"
                  type="email"
                  placeholder={t("emailPlaceholder")}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="border-white/10 bg-white/5 text-white placeholder:text-white/30"
                  required
                  data-testid="forgot-input-email"
                />
              </div>
              <Button type="submit" className="w-full" disabled={loading} data-testid="forgot-btn-submit">
                {loading ? t("sending") : t("sendResetLink")}
              </Button>
            </form>
          )}
          {!submitted && (
            <p className="mt-4 text-center text-sm text-white/50">
              {t("rememberPassword")}{" "}
              <a href="/login" className="text-brand hover:underline" data-testid="forgot-link-login">{tc("signIn")}</a>
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
