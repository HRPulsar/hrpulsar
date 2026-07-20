"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AuthLogo } from "@/components/auth-logo";
import { magicLogin } from "@/lib/signup";

export default function MagicLoginPage() {
  return (
    <Suspense>
      <MagicLoginContent />
    </Suspense>
  );
}

function MagicLoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const handleLogin = useCallback(
    async (t: string) => {
      setError("");
      setBusy(true);
      try {
        const resp = await magicLogin(t);
        localStorage.setItem("access_token", resp.access_token);
        localStorage.setItem("refresh_token", resp.refresh_token);
        document.cookie = "has_token=1; path=/; SameSite=Lax";
        router.push("/dashboard");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Sign-in failed");
      } finally {
        setBusy(false);
      }
    },
    [router],
  );

  useEffect(() => {
    if (token) {
      handleLogin(token);
    } else {
      setError("Sign-in link is missing or invalid.");
    }
  }, [token, handleLogin]);

  return (
    <div className="flex flex-col items-center gap-8">
      <AuthLogo />
      <Card className="w-full max-w-sm border-white/10 bg-black/40 backdrop-blur-xl">
        <CardHeader className="text-center">
          <CardTitle className="text-xl text-white">
            {error ? "Could not sign you in" : "Signing you in..."}
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
                    {busy ? "Retrying..." : "Try again"}
                  </Button>
                )}
                <a
                  href="/register"
                  className="block text-center text-sm text-brand hover:underline"
                >
                  Request a new link
                </a>
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center gap-3 py-4">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-brand" />
              <p className="text-sm text-white/50">
                Please wait while we verify your link...
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
