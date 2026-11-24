"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AuthLogo } from "@/components/auth-logo";
import { ApiError } from "@/lib/api";
import { magicLogin } from "@/lib/signup";
import { setClientCookie } from "@/lib/cookies";

export default function MagicLoginPage() {
  return (
    <Suspense>
      <MagicLoginContent />
    </Suspense>
  );
}

function MagicLoginContent() {
  const t = useTranslations("auth");
  const tc = useTranslations("common");
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  // A link without its token never worked: said without a request.
  const error = token ? failure : t("signInLinkInvalid");
  // HRP-1161: the account's first entry sets its password - the link works
  // once, and the approval made the account with a random one. The backend
  // asks for it before it burns the link.
  const [needsPassword, setNeedsPassword] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  // Sets state only once the answer is in: the page signs in from an
  // effect, and the buttons clear the old error before they call it.
  const signIn = useCallback(
    async (linkToken: string, newPassword?: string) => {
      try {
        const resp = await magicLogin(linkToken, newPassword);
        localStorage.setItem("access_token", resp.access_token);
        localStorage.setItem("refresh_token", resp.refresh_token);
        setClientCookie("has_token", "1");
        // Still busy: the page is leaving, and a second press of the
        // button would meet a link already used.
        router.push("/dashboard");
      } catch (err) {
        setBusy(false);
        if (err instanceof ApiError && err.code === "magic_login_password_required") {
          setNeedsPassword(true);
          return;
        }
        // The link itself stopped working: no form can save it.
        if (err instanceof ApiError && err.status === 401) setNeedsPassword(false);
        // A rate limit answers without a message: an empty one would show
        // no error at all, and the spinner would never end.
        setFailure((err instanceof Error && err.message) || t("signInFailed"));
      }
    },
    [router, t],
  );

  useEffect(() => {
    // The state writes happen after the await, not in the effect body;
    // the rule cannot see through the async boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (token) void signIn(token);
  }, [token, signIn]);

  function handleLogin(linkToken: string, newPassword?: string) {
    setFailure("");
    setBusy(true);
    void signIn(linkToken, newPassword);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    if (password !== confirmPassword) {
      setFailure(t("passwordsDoNotMatch"));
      return;
    }
    if (password.length < 8) {
      setFailure(t("passwordTooShort"));
      return;
    }
    handleLogin(token, password);
  }

  if (needsPassword) {
    return (
      <div className="flex flex-col items-center gap-8">
        <AuthLogo />
        <Card className="w-full max-w-sm border-white/10 bg-black/40 backdrop-blur-xl">
          <CardHeader className="text-center">
            <CardTitle className="text-xl text-white">{t("createPasswordTitle")}</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <p className="text-sm text-white/70">{t("createPasswordIntro")}</p>
              {error && (
                <div
                  className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
                  data-testid="magic-login-error"
                >
                  {error}
                </div>
              )}
              <div className="space-y-2">
                <Label htmlFor="password" className="text-white/70">
                  {t("password")}
                </Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="border-white/10 bg-white/5 text-white placeholder:text-white/30"
                  required
                  data-testid="magic-login-input-password"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirm" className="text-white/70">
                  {t("confirmPassword")}
                </Label>
                <Input
                  id="confirm"
                  type="password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="border-white/10 bg-white/5 text-white placeholder:text-white/30"
                  required
                  data-testid="magic-login-input-confirm"
                />
              </div>
              <p className="text-xs text-white/40">{t("passwordMinLength")}</p>
              <Button
                type="submit"
                className="w-full"
                disabled={busy}
                data-testid="magic-login-btn-submit"
              >
                {busy ? t("signingYouIn") : t("createPasswordSubmit")}
              </Button>
            </form>
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
          <CardTitle className="text-xl text-white">
            {error ? t("couldNotSignIn") : t("signingYouIn")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {error ? (
            <>
              <div
                className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
                data-testid="magic-login-error"
              >
                {error}
              </div>
              <div className="flex flex-col gap-2">
                {token && (
                  <Button
                    variant="outline"
                    className="w-full border-white/10 text-white hover:bg-white/5"
                    onClick={() => handleLogin(token)}
                    disabled={busy}
                  >
                    {busy ? t("retrying") : tc("tryAgain")}
                  </Button>
                )}
                <a
                  href="/register"
                  className="block text-center text-sm text-brand hover:underline"
                >
                  {t("requestNewLink")}
                </a>
                {/* HRP-1161: an approved account whose link is spent gets
                    its password this way, not by asking for a workspace again. */}
                <a
                  href="/forgot-password"
                  className="block text-center text-sm text-brand hover:underline"
                  data-testid="magic-login-link-forgot"
                >
                  {t("forgotPassword")}
                </a>
                {/* A link used once already set the password: sign in with it. */}
                <a
                  href="/login"
                  className="block text-center text-sm text-brand hover:underline"
                  data-testid="magic-login-link-signin"
                >
                  {tc("signIn")}
                </a>
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center gap-3 py-4">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-brand" />
              <p className="text-sm text-white/50">
                {t("verifyingLinkWait")}
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
