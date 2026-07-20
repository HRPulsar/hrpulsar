"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { AlertTriangle, Lock, ShieldOff, Wrench, MonitorX, ServerCrash } from "lucide-react";
import type { ReactNode } from "react";
import { getBrandName } from "@/lib/brand";

interface SystemScreenProps {
  icon: ReactNode;
  title: string;
  description: string;
  cta?: { label: string; href: string };
  testId: string;
}

function SystemScreen({ icon, title, description, cta, testId }: SystemScreenProps) {
  return (
    <div
      className="mx-auto flex max-w-md flex-col items-center gap-4 rounded-lg border bg-card p-10 text-center"
      data-testid={testId}
    >
      <div className="rounded-full bg-muted p-4 text-muted-foreground">{icon}</div>
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="text-sm text-muted-foreground">{description}</p>
      {cta && (
        <Link
          href={cta.href}
          className="inline-flex h-9 items-center justify-center rounded-md border border-input bg-transparent px-3 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
        >
          {cta.label}
        </Link>
      )}
    </div>
  );
}

export function NotFoundScreen() {
  return (
    <SystemScreen
      testId="system-screen-404"
      icon={<AlertTriangle className="h-6 w-6" />}
      title="Page not found"
      description="It may have been moved, or the link is incorrect."
      cta={{ label: "Go home", href: "/" }}
    />
  );
}

export function UnauthorizedScreen() {
  return (
    <SystemScreen
      testId="system-screen-401"
      icon={<Lock className="h-6 w-6" />}
      title="Sign in required"
      description="Please sign in to continue."
      cta={{ label: "Sign in", href: "/login" }}
    />
  );
}

export function ForbiddenScreen() {
  return (
    <SystemScreen
      testId="system-screen-403"
      icon={<ShieldOff className="h-6 w-6" />}
      title="Access denied"
      description="You don't have permission to access this section."
      cta={{ label: "Go home", href: "/" }}
    />
  );
}

export function ServerErrorScreen({ onRetry }: { onRetry?: () => void }) {
  return (
    <div
      className="mx-auto flex max-w-md flex-col items-center gap-4 rounded-lg border bg-card p-10 text-center"
      data-testid="system-screen-500"
    >
      <div className="rounded-full bg-muted p-4 text-muted-foreground">
        <ServerCrash className="h-6 w-6" />
      </div>
      <h1 className="text-2xl font-semibold tracking-tight">
        Something went wrong
      </h1>
      <p className="text-sm text-muted-foreground">
        A server error occurred. Try refreshing the page.
      </p>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : (
        <Link
          href="/"
          className="inline-flex h-9 items-center justify-center rounded-md border border-input bg-transparent px-3 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
        >
          Go home
        </Link>
      )}
    </div>
  );
}

export function MaintenanceScreen() {
  return (
    <SystemScreen
      testId="system-screen-maintenance"
      icon={<Wrench className="h-6 w-6" />}
      title="Scheduled maintenance"
      description="The service is temporarily unavailable. We'll be back soon."
    />
  );
}

export function BrowserUnsupportedScreen() {
  return (
    <SystemScreen
      testId="system-screen-browser-unsupported"
      icon={<MonitorX className="h-6 w-6" />}
      title="Browser not supported"
      description={`${getBrandName()} runs on the latest versions of Chrome, Edge, Firefox, and Safari.`}
    />
  );
}
