"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { login, isTenantSelection, selectTenant, getLoginRedirect } from "@/lib/auth";
import type { TenantInfo } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AuthLogo } from "@/components/auth-logo";

// HRP-84 REDO: only honour ?next when it's a safe same-origin path. The
// proxy middleware appends it for the unauthenticated email-link case so
// participants land on the assessment page right after signing in instead
// of the generic /dashboard.
function safeNextParam(raw: string | null): string | null {
  if (!raw) return null;
  if (!raw.startsWith("/")) return null;
  if (raw.startsWith("//")) return null;
  return raw;
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginContent />
    </Suspense>
  );
}

function LoginContent() {
  const router = useRouter();
  const search = useSearchParams();
  const nextParam = safeNextParam(search.get("next"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [tenants, setTenants] = useState<TenantInfo[] | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const result = await login(email, password);
      if (isTenantSelection(result)) {
        setTenants(result.tenants);
      } else {
        router.push(nextParam ?? getLoginRedirect(result));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleTenantSelect(tenantId: string) {
    setError("");
    setLoading(true);
    try {
      const result = await selectTenant(email, password, tenantId);
      router.push(nextParam ?? getLoginRedirect(result));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to select tenant");
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
            {tenants ? "Select organization" : "Sign in"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {tenants ? (
            <div className="space-y-3">
              {error && (
                <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {error}
                </div>
              )}
              <p className="text-sm text-white/60">
                Your account belongs to multiple organizations. Choose one to continue:
              </p>
              <div className="space-y-2" data-testid="login-tenant-list">
                {tenants.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => handleTenantSelect(t.id)}
                    disabled={loading}
                    data-testid={`login-tenant-item-${t.id}`}
                    className="flex w-full items-center justify-between rounded-lg border border-white/10 bg-white/5 px-4 py-3 text-left transition-colors hover:bg-white/10 disabled:opacity-50"
                  >
                    <div>
                      <div className="font-medium text-white">{t.name}</div>
                      <div className="text-xs text-white/40">{t.slug}</div>
                    </div>
                    <div className="flex gap-1">
                      {t.roles.map((role) => (
                        <Badge key={role} variant="secondary" className="text-xs">
                          {role}
                        </Badge>
                      ))}
                    </div>
                  </button>
                ))}
              </div>
              <button
                onClick={() => setTenants(null)}
                className="w-full text-center text-sm text-white/50 hover:text-white/70"
                data-testid="login-btn-back"
              >
                Back to login
              </button>
            </div>
          ) : (
            <>
              <form onSubmit={handleSubmit} className="space-y-4" data-testid="login-form">
                {error && (
                  <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive" data-testid="login-error">
                    {error}
                  </div>
                )}
                <div className="space-y-2">
                  <Label htmlFor="email" className="text-white/70">
                    Email
                  </Label>
                  <Input
                    id="email"
                    type="email"
                    placeholder="you@company.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="border-white/10 bg-white/5 text-white placeholder:text-white/30"
                    required
                    data-testid="login-input-email"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="password" className="text-white/70">
                    Password
                  </Label>
                  <Input
                    id="password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="border-white/10 bg-white/5 text-white placeholder:text-white/30"
                    required
                    data-testid="login-input-password"
                  />
                </div>
                <Button type="submit" className="w-full" disabled={loading} data-testid="login-btn-submit">
                  {loading ? "Signing in..." : "Sign in"}
                </Button>
              </form>
              <div className="mt-4 space-y-2 text-center text-sm text-white/50">
                <p>
                  <a href="/forgot-password" className="text-white/60 hover:text-white/80 hover:underline" data-testid="login-link-forgot">
                    Forgot your password?
                  </a>
                </p>
                <p>
                  Don&apos;t have an account?{" "}
                  <a href="/register" className="text-brand hover:underline" data-testid="login-link-register">
                    Sign up
                  </a>
                </p>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
