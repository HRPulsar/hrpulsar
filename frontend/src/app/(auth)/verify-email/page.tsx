"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { verifyEmail, resendVerification } from "@/lib/auth";
import { verifySignupRequest } from "@/lib/signup";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AuthLogo } from "@/components/auth-logo";

const RESEND_COOLDOWN = 60;

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <VerifyEmailContent />
    </Suspense>
  );
}

function VerifyEmailContent() {
  const t = useTranslations("auth");
  const tc = useTranslations("common");
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const email = searchParams.get("email");
  const flow = searchParams.get("flow") ?? "auth";
  const isSignupFlow = flow === "signup";

  const [error, setError] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [verified, setVerified] = useState(false);
  const [resending, setResending] = useState(false);
  const [resent, setResent] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  const handleVerify = useCallback(
    async (verifyToken: string) => {
      setError("");
      setVerifying(true);
      try {
        if (isSignupFlow) {
          // Moderated signup: stay on this page after success and
          // show the waiting-for-moderation copy below.
          await verifySignupRequest(verifyToken);
          setVerified(true);
        } else {
          await verifyEmail(verifyToken);
          router.push("/dashboard");
        }
      } catch (err) {
        setError(
          err instanceof Error ? err.message : t("verificationFailed"),
        );
      } finally {
        setVerifying(false);
      }
    },
    [isSignupFlow, router, t],
  );

  useEffect(() => {
    if (token) {
      handleVerify(token);
    }
  }, [token, handleVerify]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => {
      setCooldown((c) => c - 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  async function handleResend() {
    if (!email || cooldown > 0) return;
    setResending(true);
    setError("");
    setResent(false);
    try {
      await resendVerification(email);
      setResent(true);
      setCooldown(RESEND_COOLDOWN);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t("resendFailed"),
      );
    } finally {
      setResending(false);
    }
  }

  // Token-based verification flow: show progress + result.
  if (token) {
    return (
      <div className="flex flex-col items-center gap-8">
        <AuthLogo />
        <Card className="w-full max-w-sm border-white/10 bg-black/40 backdrop-blur-xl">
          <CardHeader className="text-center">
            <CardTitle className="text-xl text-white">
              {error
                ? t("verificationFailed")
                : verified
                  ? t("emailConfirmed")
                  : t("verifyingEmail")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {error ? (
              <>
                <div
                  className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
                  data-testid="verify-error"
                >
                  {error}
                </div>
                <p className="text-center text-sm text-white/50">
                  {t("verifyLinkExpired")}
                </p>
                <div className="flex flex-col gap-2">
                  <Button
                    variant="outline"
                    className="w-full border-white/10 text-white hover:bg-white/5"
                    onClick={() => handleVerify(token)}
                    disabled={verifying}
                  >
                    {verifying ? t("retrying") : tc("tryAgain")}
                  </Button>
                  <a
                    href="/register"
                    className="block text-center text-sm text-brand hover:underline"
                  >
                    {t("backToRequestAccess")}
                  </a>
                </div>
              </>
            ) : verified ? (
              <div
                className="flex flex-col items-center gap-3 py-4"
                data-testid="verify-signup-waiting"
              >
                <div className="text-2xl">✓</div>
                <p className="text-center text-sm text-white">
                  {t("moderationQueue")}
                </p>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3 py-4">
                <div className="h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-brand" />
                <p className="text-sm text-white/50">
                  {t("verifyingEmailWait")}
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  // No token: "check your email" state.
  const titleText = t("checkYourEmail");
  const subText = isSignupFlow
    ? t("checkEmailSignup")
    : t("checkEmailDefault");

  return (
    <div className="flex flex-col items-center gap-8">
      <AuthLogo />
      <Card className="w-full max-w-sm border-white/10 bg-black/40 backdrop-blur-xl">
        <CardHeader className="text-center">
          <CardTitle className="text-xl text-white">{titleText}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && (
            <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          )}
          {resent && (
            <div className="rounded-md bg-emerald-500/10 px-3 py-2 text-sm text-emerald-400">
              {t("verificationEmailSent")}
            </div>
          )}
          <p className="text-center text-sm text-white/60">
            {t("sentVerificationLinkTo")}
          </p>
          {email && (
            <p
              className="text-center text-sm font-medium text-white"
              data-testid="verify-email-target"
            >
              {email}
            </p>
          )}
          <p className="text-center text-sm text-white/50">{subText}</p>
          {!isSignupFlow && email && (
            <Button
              variant="outline"
              className="w-full border-white/10 text-white hover:bg-white/5"
              onClick={handleResend}
              disabled={resending || cooldown > 0}
            >
              {resending
                ? t("sending")
                : cooldown > 0
                  ? t("resendIn", { seconds: cooldown })
                  : t("resendVerificationEmail")}
            </Button>
          )}
          <p className="text-center text-sm text-white/50">
            {t("haveAccount")}{" "}
            <a href="/login" className="text-brand hover:underline">
              {tc("signIn")}
            </a>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
