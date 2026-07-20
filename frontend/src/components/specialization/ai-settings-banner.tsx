"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { aiSettingsApi, type AISettings } from "@/lib/api/ai-settings";

export function AISettingsBanner() {
  const [settings, setSettings] = useState<AISettings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    aiSettingsApi
      .get()
      .then((s) => {
        if (!cancelled) setSettings(s);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div
        data-testid="ai-settings-banner-error"
        className="rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
      >
        Failed to load AI settings: {error}
      </div>
    );
  }

  if (!settings) {
    return (
      <div
        data-testid="ai-settings-banner-loading"
        className="rounded-md border bg-muted px-4 py-3 text-sm text-muted-foreground"
      >
        Loading AI settings…
      </div>
    );
  }

  return (
    <div
      data-testid="ai-settings-banner"
      className="flex items-center justify-between rounded-md border bg-muted/40 px-4 py-3 text-sm"
    >
      <span className="text-muted-foreground">
        Generation runs with{" "}
        <strong className="text-foreground" data-testid="ai-settings-banner-model">
          {settings.effective_model}
        </strong>
        {" · "}
        effort{" "}
        <strong className="text-foreground" data-testid="ai-settings-banner-effort">
          {settings.effort_level}
        </strong>
        {" · "}
        temperature {settings.effective_temperature.toFixed(2)}
      </span>
      <Link
        href="/settings/ai"
        data-testid="ai-settings-banner-link"
        className="text-primary hover:underline"
      >
        Adjust AI settings →
      </Link>
    </div>
  );
}
