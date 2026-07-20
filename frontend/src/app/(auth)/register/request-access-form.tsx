"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AuthLogo } from "@/components/auth-logo";
import { createSignupRequest } from "@/lib/signup";
import { TURNSTILE_FAILED_MESSAGE, useTurnstileGate } from "@/lib/turnstile";

const ROLE_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "hr", label: "HR" },
  { value: "recruiter", label: "Recruiter" },
  { value: "manager", label: "Manager" },
  { value: "founder", label: "Founder" },
  { value: "other", label: "Other" },
];

export function RequestAccessForm() {
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
      setError(err instanceof Error ? err.message : "Request failed");
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
          <CardTitle className="text-xl text-white">Request access</CardTitle>
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
            <p className="text-sm text-white/60">
              Tell us a bit about yourself and we&apos;ll email you a sign-in
              link once our team approves the request.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="first_name" className="text-white/70">
                  First name
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
                  Last name
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
                Company name
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
                Work email
              </Label>
              <Input
                id="email"
                type="email"
                placeholder="you@company.com"
                value={form.email}
                onChange={(e) => update("email", e.target.value)}
                className="border-white/10 bg-white/5 text-white placeholder:text-white/30"
                required
                data-testid="register-input-email"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="role" className="text-white/70">
                Role
              </Label>
              <select
                id="role"
                value={form.role}
                onChange={(e) => update("role", e.target.value)}
                className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white"
                data-testid="register-select-role"
              >
                <option value="" className="bg-black text-white">
                  Choose a role
                </option>
                {ROLE_OPTIONS.map((opt) => (
                  <option
                    key={opt.value}
                    value={opt.value}
                    className="bg-black text-white"
                  >
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
            {turnstile.failed && (
              <div
                className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
                data-testid="register-verify-error"
              >
                {TURNSTILE_FAILED_MESSAGE}{" "}
                <button
                  type="button"
                  onClick={turnstile.reset}
                  className="font-semibold underline"
                  data-testid="register-verify-retry"
                >
                  Retry
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
                ? "Sending request..."
                : !turnstile.isReady && !turnstile.failed
                  ? "Verifying..."
                  : "Request access"}
            </Button>
            {turnstile.widget}
          </form>
          <p className="mt-4 text-center text-sm text-white/50">
            Already have an account?{" "}
            <a
              href="/login"
              className="text-brand hover:underline"
              data-testid="register-link-login"
            >
              Sign in
            </a>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
