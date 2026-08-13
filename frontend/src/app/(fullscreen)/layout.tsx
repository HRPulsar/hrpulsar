"use client";

import { AuthProvider } from "@/context/auth-context";
import { PlatformAdminRedirect } from "@/components/platform-admin-redirect";
import { TooltipProvider } from "@/components/ui/tooltip";

/**
 * HRP-510 — authenticated shell without the app chrome.
 *
 * Same auth guard as the dashboard, but no sidebar, header or banners:
 * these pages are single-purpose full-viewport surfaces (the assessment
 * canvas) where every pixel of width is the point. Navigation back into
 * the app is the page's own "Back" control.
 *
 * HRP-550: "same auth guard" now includes the platform-admin bounce the
 * dashboard shell has always had — without it a platform admin could open
 * a tenant-scoped canvas by URL and get a half-authorised surface.
 */
export default function FullscreenLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthProvider>
      <PlatformAdminRedirect>
        <TooltipProvider>
          <div className="flex h-screen flex-col overflow-hidden bg-background">
            {children}
          </div>
        </TooltipProvider>
      </PlatformAdminRedirect>
    </AuthProvider>
  );
}
