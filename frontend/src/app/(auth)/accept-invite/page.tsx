"use client";

import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { acceptInvitation } from "@/lib/auth";
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

  useEffect(() => {
    if (!token) {
      setError("Invalid invitation link. Please check the link and try again.");
    }
  }, [token]);

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
      setError(err instanceof Error ? err.message : "Failed to accept invitation");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col items-center gap-8">
      <AuthLogo />
      <Card className="w-full max-w-sm border-white/10 bg-black/40 backdrop-blur-xl">
        <CardHeader className="text-center">
          <CardTitle className="text-xl text-white">Accept invitation</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </div>
            )}
            <p className="text-center text-sm text-white/50">
              Set up your account to join your team on {getBrandName()}.
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
                  required
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="password" className="text-white/70">
                Password
              </Label>
              <Input
                id="password"
                type="password"
                minLength={8}
                value={form.password}
                onChange={(e) => update("password", e.target.value)}
                className="border-white/10 bg-white/5 text-white placeholder:text-white/30"
                required
              />
            </div>
            <Button type="submit" className="w-full" disabled={loading || !token}>
              {loading ? "Setting up account..." : "Accept & join"}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-white/50">
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
