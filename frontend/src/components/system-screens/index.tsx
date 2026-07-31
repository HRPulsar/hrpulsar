"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
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
  const t = useTranslations("common");
  return (
    <SystemScreen
      testId="system-screen-404"
      icon={<AlertTriangle className="h-6 w-6" />}
      title={t("notFoundTitle")}
      description={t("notFoundDescription")}
      cta={{ label: t("goHome"), href: "/" }}
    />
  );
}

export function UnauthorizedScreen() {
  const t = useTranslations("common");
  return (
    <SystemScreen
      testId="system-screen-401"
      icon={<Lock className="h-6 w-6" />}
      title={t("unauthorizedTitle")}
      description={t("unauthorizedDescription")}
      cta={{ label: t("signIn"), href: "/login" }}
    />
  );
}

export function ForbiddenScreen() {
  const t = useTranslations("common");
  return (
    <SystemScreen
      testId="system-screen-403"
      icon={<ShieldOff className="h-6 w-6" />}
      title={t("forbiddenTitle")}
      description={t("forbiddenDescription")}
      cta={{ label: t("goHome"), href: "/" }}
    />
  );
}

export function ServerErrorScreen({ onRetry }: { onRetry?: () => void }) {
  const t = useTranslations("common");
  return (
    <div
      className="mx-auto flex max-w-md flex-col items-center gap-4 rounded-lg border bg-card p-10 text-center"
      data-testid="system-screen-500"
    >
      <div className="rounded-full bg-muted p-4 text-muted-foreground">
        <ServerCrash className="h-6 w-6" />
      </div>
      <h1 className="text-2xl font-semibold tracking-tight">
        {t("serverErrorTitle")}
      </h1>
      <p className="text-sm text-muted-foreground">
        {t("serverErrorDescription")}
      </p>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          {t("tryAgain")}
        </Button>
      ) : (
        <Link
          href="/"
          className="inline-flex h-9 items-center justify-center rounded-md border border-input bg-transparent px-3 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
        >
          {t("goHome")}
        </Link>
      )}
    </div>
  );
}

export function MaintenanceScreen() {
  const t = useTranslations("common");
  return (
    <SystemScreen
      testId="system-screen-maintenance"
      icon={<Wrench className="h-6 w-6" />}
      title={t("maintenanceTitle")}
      description={t("maintenanceDescription")}
    />
  );
}

export function BrowserUnsupportedScreen() {
  const t = useTranslations("common");
  return (
    <SystemScreen
      testId="system-screen-browser-unsupported"
      icon={<MonitorX className="h-6 w-6" />}
      title={t("browserUnsupportedTitle")}
      description={t("browserUnsupportedDescription", {
        brand: getBrandName(),
      })}
    />
  );
}
