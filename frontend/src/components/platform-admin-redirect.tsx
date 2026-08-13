"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/auth-context";

/**
 * Redirect platform admins to /platform when they are in the platform tenant.
 *
 * HRP-550: this used to live inside `(dashboard)/layout.tsx`, so the
 * `(fullscreen)` shell added in HRP-510 — same auth guard, no app chrome —
 * let a platform admin render a tenant-scoped surface instead of bouncing
 * them to their own console. Both authenticated shells now wrap their tree
 * in this one component.
 *
 * Inert in community builds: `is_platform_admin` is only ever set by the
 * enterprise RBAC seam (`ee.rbac`), so the flag stays false and the guard
 * renders its children unchanged.
 *
 * Both shells mount this inside `AuthProvider`, which renders nothing until
 * the session resolves and returns null without a user — so there is no
 * loading state left for this component to handle. The optional chaining
 * stays because the context type is `User | null`.
 */
export function PlatformAdminRedirect({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (user?.is_platform_admin) {
      router.replace("/platform");
    }
  }, [user, router]);

  if (user?.is_platform_admin) {
    return null;
  }

  return <>{children}</>;
}
