"use client";

import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { acceptInvitation, fetchInvitationPreview } from "@/lib/auth";
import { splitFullName } from "@/lib/name";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AuthLogo } from "@/components/auth-logo";
import { getBrandName } from "@/lib/brand";

export default function AcceptInvitePage() {
  return (
    <Suspense>
      <AcceptInviteContent />
    </Suspense>
  );
}

function AcceptInviteContent() {
  const t = useTranslations("auth");
  const tc = useTranslations("common");
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";

  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    password: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [invitedEmail, setInvitedEmail] = useState("");
  // Set when the link itself is unusable (missing, unknown, cancelled,
  // expired) — there is nothing to submit, so the form stays locked.
  const [linkInvalid, setLinkInvalid] = useState(false);

  const invalidLinkMessage = t("invalidInviteLink");

  // HRP-435: pre-fill from the invitation itself. The inviter types a single
  // `Name`, which we split into the two fields this form collects — both stay
  // editable. Without a server-provided value the browser used to autofill the
  // invitee's email into "Last name".
  useEffect(() => {
    if (!token) {
      setError(invalidLinkMessage);
      setLinkInvalid(true);
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const invitation = await fetchInvitationPreview(token);
        if (cancelled) return;
        const { firstName, lastName } = splitFullName(invitation.name);
        setInvitedEmail(invitation.email);
        setForm((prev) => ({
          ...prev,
          first_name: prev.first_name || firstName,
          last_name: prev.last_name || lastName,
        }));
      } catch (err) {
        if (cancelled) return;
        // Invalid, cancelled or expired link — say so before the visitor
        // fills the form in, and keep them from submitting into a second error.
        setError(err instanceof Error ? err.message : invalidLinkMessage);
        setLinkInvalid(true);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token, invalidLinkMessage]);

  function update(field: string, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    setError("");
    setLoading(true);

    try {
      await acceptInvitation({ token, ...form });
      router.push("/dashboard");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t("acceptInviteFailed"),
      );
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
            {t("acceptInvitation")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={handleSubmit}
            className="space-y-4"
            data-testid="accept-invite-form"
          >
            {error && (
              <div
                className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
                data-testid="accept-invite-error"
              >
                {error}
              </div>
            )}
            <p className="text-center text-sm text-white/50">
              {t("joinTeamOn", { brand: getBrandName() })}
            </p>
            {invitedEmail && (
              <div className="space-y-2">
                <Label htmlFor="email" className="text-white/70">
                  {t("email")}
                </Label>
                {/* Read-only: the invitation is bound to this address. Also
                    gives password managers the username they would otherwise
                    guess out of the name fields. */}
                <Input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete="username"
                  value={invitedEmail}
                  readOnly
                  className="border-white/10 bg-white/5 text-white/70 placeholder:text-white/30"
                  data-testid="accept-invite-input-email"
                />
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="first_name" className="text-white/70">
                  {t("firstName")}
                </Label>
                <Input
                  id="first_name"
                  name="first_name"
                  autoComplete="given-name"
                  value={form.first_name}
                  onChange={(e) => update("first_name", e.target.value)}
                  className="border-white/10 bg-white/5 text-white placeholder:text-white/30"
                  required
                  data-testid="accept-invite-input-firstname"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="last_name" className="text-white/70">
                  {t("lastName")}
                </Label>
                <Input
                  id="last_name"
                  name="last_name"
                  autoComplete="family-name"
                  value={form.last_name}
                  onChange={(e) => update("last_name", e.target.value)}
                  className="border-white/10 bg-white/5 text-white placeholder:text-white/30"
                  required
                  data-testid="accept-invite-input-lastname"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="password" className="text-white/70">
                {t("password")}
              </Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="new-password"
                minLength={8}
                value={form.password}
                onChange={(e) => update("password", e.target.value)}
                className="border-white/10 bg-white/5 text-white placeholder:text-white/30"
                required
                data-testid="accept-invite-input-password"
              />
            </div>
            <Button
              type="submit"
              className="w-full"
              disabled={loading || !token || linkInvalid}
              data-testid="accept-invite-btn-submit"
            >
              {loading ? t("settingUpAccount") : t("acceptAndJoin")}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-white/50">
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
