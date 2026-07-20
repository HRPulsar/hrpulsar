"use client";

import { useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";

const emptySubscribe = () => () => {};

function getTenantName() {
  return typeof window !== "undefined"
    ? localStorage.getItem("impersonation_tenant_name")
    : null;
}

export function ImpersonationBanner() {
  const tenantName = useSyncExternalStore(emptySubscribe, getTenantName, () => null);

  if (!tenantName) return null;

  function exitImpersonation() {
    const returnToken = localStorage.getItem("impersonation_return_token");
    const returnRefresh = localStorage.getItem("impersonation_return_refresh");
    if (returnToken && returnRefresh) {
      localStorage.setItem("access_token", returnToken);
      localStorage.setItem("refresh_token", returnRefresh);
    }
    localStorage.removeItem("impersonation_return_token");
    localStorage.removeItem("impersonation_return_refresh");
    localStorage.removeItem("impersonation_tenant_name");
    window.location.href = "/platform";
  }

  return (
    <div
      className="flex items-center justify-between bg-amber-500/10 border-b border-amber-500/20 px-4 py-2"
      data-testid="impersonation-banner"
    >
      <div className="flex items-center gap-2 text-sm">
        <svg className="h-4 w-4 text-amber-600" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
        </svg>
        <span className="text-amber-700 dark:text-amber-400">
          Viewing as <strong>{tenantName}</strong>
        </span>
      </div>
      <Button
        size="sm"
        variant="outline"
        onClick={exitImpersonation}
        className="border-amber-500/30 text-amber-700 hover:bg-amber-500/10 dark:text-amber-400"
        data-testid="impersonation-btn-exit"
      >
        Exit impersonation
      </Button>
    </div>
  );
}
