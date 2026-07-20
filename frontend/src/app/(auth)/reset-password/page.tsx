"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AuthLogo } from "@/components/auth-logo";

import { API_BASE } from "@/lib/api-base";

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<div className="text-white/50">Loading...</div>}>
      <ResetPasswordForm />
    </Suspense>
  );
}

function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: "Request failed" }));
        throw new Error(body.detail || "Request failed");
      }
      setSuccess(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <div className="flex flex-col items-center gap-8">
        <AuthLogo />
        <Card className="w-full max-w-sm border-white/10 bg-black/40 backdrop-blur-xl">
          <CardContent className="py-8 text-center">
            <p className="text-sm text-white/70">Invalid or missing reset token.</p>
            <a href="/forgot-password" className="mt-2 inline-block text-sm text-brand hover:underline">
              Request a new reset link
            </a>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-8">
      <AuthLogo />
      <Card className="w-full max-w-sm border-white/10 bg-black/40 backdrop-blur-xl">
        <CardHeader className="text-center">
          <CardTitle className="text-xl text-white">Set new password</CardTitle>
        </CardHeader>
        <CardContent>
          {success ? (
            <div className="space-y-4 text-center">
              <p className="text-sm text-white/70">Your password has been reset successfully.</p>
              <a href="/login" className="text-sm text-brand hover:underline">
                Sign in with your new password
              </a>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              {error && (
                <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {error}
                </div>
              )}
              <div className="space-y-2">
                <Label htmlFor="password" className="text-white/70">New password</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="border-white/10 bg-white/5 text-white placeholder:text-white/30"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirm" className="text-white/70">Confirm password</Label>
                <Input
                  id="confirm"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="border-white/10 bg-white/5 text-white placeholder:text-white/30"
                  required
                />
              </div>
              <p className="text-xs text-white/40">Minimum 8 characters</p>
              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? "Resetting..." : "Reset password"}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
