"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";

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
    async (t: string) => {
      setError("");
      setVerifying(true);
      try {
        if (isSignupFlow) {
          // Moderated signup: stay on this page after success and
          // show the waiting-for-moderation copy below.
          await verifySignupRequest(t);
          setVerified(true);
        } else {
          await verifyEmail(t);
          router.push("/dashboard");
        }
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Verification failed",
        );
      } finally {
        setVerifying(false);
      }
    },
    [isSignupFlow, router],
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
        err instanceof Error ? err.message : "Failed to resend email",
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
                ? "Verification failed"
                : verified
                  ? "Email confirmed"
                  : "Verifying your email"}
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
                  The verification link may have expired or already been used.
                </p>
                <div className="flex flex-col gap-2">
                  <Button
                    variant="outline"
                    className="w-full border-white/10 text-white hover:bg-white/5"
                    onClick={() => handleVerify(token)}
                    disabled={verifying}
                  >
                    {verifying ? "Retrying..." : "Try again"}
                  </Button>
                  <a
                    href="/register"
                    className="block text-center text-sm text-brand hover:underline"
                  >
                    Back to request access
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
                  Thanks — your request is in our moderation queue. Expect an
                  email with a sign-in link within 24 hours.
                </p>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3 py-4">
                <div className="h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-brand" />
                <p className="text-sm text-white/50">
                  Please wait while we verify your email address...
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  // No token: "check your email" state.
  const titleText = isSignupFlow ? "Check your email" : "Check your email";
  const subText = isSignupFlow
    ? "Click the link in the email to confirm your address. Our team typically reviews new requests within 24 hours after confirmation."
    : "Click the link in the email to verify your account and get started.";

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
              Verification email sent. Please check your inbox.
            </div>
          )}
          <p className="text-center text-sm text-white/60">
            We sent a verification link to
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
                ? "Sending..."
                : cooldown > 0
                  ? `Resend in ${cooldown}s`
                  : "Resend verification email"}
            </Button>
          )}
          <p className="text-center text-sm text-white/50">
            Already have an account?{" "}
            <a href="/login" className="text-brand hover:underline">
              Sign in
            </a>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
