"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { AuthProvider } from "@/context/auth-context";
import { PlatformAdminRedirect } from "@/components/platform-admin-redirect";
import { Sidebar } from "@/components/sidebar";
import { Header } from "@/components/header";
import { ImpersonationBanner } from "@/components/impersonation-banner";
import { AIGenerationBanner } from "@/components/ai-generation-banner";
import { DemoBanner } from "@/components/dashboard/demo-banner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { WebSocketProvider } from "@/lib/ws";
import { useInAppNotifications } from "@/hooks/use-in-app-notifications";

function InAppNotificationsBridge() {
  useInAppNotifications();
  return null;
}

function CreditLimitListener() {
  const t = useTranslations("common");
  useEffect(() => {
    function handleCreditLimit(e: Event) {
      const detail = (e as CustomEvent).detail;
      toast.error(detail || t("creditLimitReached"));
    }
    window.addEventListener("hrpulsar:credit-limit", handleCreditLimit);
    return () => window.removeEventListener("hrpulsar:credit-limit", handleCreditLimit);
  }, [t]);
  return null;
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthProvider>
      <PlatformAdminRedirect>
        <WebSocketProvider>
          <TooltipProvider>
            <InAppNotificationsBridge />
            <CreditLimitListener />
            <div className="flex h-full">
              <div className="hidden lg:block">
                <Sidebar />
              </div>
              <div className="flex flex-1 flex-col min-w-0">
                <ImpersonationBanner />
                <AIGenerationBanner />
                <DemoBanner />
                <Header />
                <main className="flex-1 overflow-auto p-4 sm:p-6">{children}</main>
              </div>
            </div>
          </TooltipProvider>
        </WebSocketProvider>
      </PlatformAdminRedirect>
    </AuthProvider>
  );
}
