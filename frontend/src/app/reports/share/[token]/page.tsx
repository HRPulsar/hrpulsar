/* eslint-disable react/jsx-no-literals -- accepted F2 debt (HRP-476): public
   share surface for external recipients, deliberately English until localized */
"use client";

import { use, useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";
import type { ReportSharePublicView } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Download, Loader2 } from "lucide-react";
import { formatDateTime } from "@/lib/date-format";

interface PageProps {
  params: Promise<{ token: string }>;
}

export default function PublicReportSharePage({ params }: PageProps) {
  const { token } = use(params);
  const [view, setView] = useState<ReportSharePublicView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetch(`${API_BASE}/reports/share/${encodeURIComponent(token)}`)
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          if (res.status === 410) setError("This share link has expired.");
          else if (res.status === 404) setError("This share link is no longer available.");
          else setError("Failed to load the report.");
          return;
        }
        const data: ReportSharePublicView = await res.json();
        if (!cancelled) setView(data);
      })
      .catch(() => {
        if (!cancelled) setError("Network error.");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (error) {
    return (
      <div className="mx-auto flex min-h-screen max-w-xl items-center px-4 py-10">
        <Card className="w-full" data-testid="share-error">
          <CardHeader>
            <CardTitle>Report unavailable</CardTitle>
          </CardHeader>
          <CardContent>{error}</CardContent>
        </Card>
      </div>
    );
  }

  if (!view) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-xl items-center px-4 py-10">
      <Card className="w-full" data-testid="share-view">
        <CardHeader>
          <CardTitle>{view.vacancy_title ?? "Recruitment report"}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            {view.generated_at ? `Generated on ${formatDateTime(view.generated_at)}.` : ""}
            {" "}
            Link expires on {formatDateTime(view.expires_at)}.
          </p>
          {view.download_url ? (
            <a
              href={view.download_url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              data-testid="share-download"
            >
              <Download className="mr-2 h-4 w-4" />
              Download XLSX
            </a>
          ) : (
            <p className="text-sm text-amber-700">Download URL unavailable.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
