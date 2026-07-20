"use client";

import { useAuth } from "@/context/auth-context";

/**
 * True only on SaaS deployments, where billing endpoints exist. Community
 * (on-prem) backends mount no /api/billing/* routes — every billing request
 * must be gated on this flag so self-hosted installs stay 404-free (HRP-397).
 */
export function useIsSaas(): boolean {
  const { user } = useAuth();
  return user?.deployment_mode === "saas";
}
