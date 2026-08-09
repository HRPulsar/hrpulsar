"use client";

import { AuthProvider } from "@/context/auth-context";
import { TooltipProvider } from "@/components/ui/tooltip";

/**
 * HRP-510 — authenticated shell without the app chrome.
 *
 * Same auth guard as the dashboard, but no sidebar, header or banners:
 * these pages are single-purpose full-viewport surfaces (the assessment
 * canvas) where every pixel of width is the point. Navigation back into
 * the app is the page's own "Back" control.
 */
export default function FullscreenLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthProvider>
      <TooltipProvider>
        <div className="flex h-screen flex-col overflow-hidden bg-background">
          {children}
        </div>
      </TooltipProvider>
    </AuthProvider>
  );
}
