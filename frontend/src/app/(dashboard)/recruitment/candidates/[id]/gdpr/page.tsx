"use client";

import { use, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, Download, Loader2, ShieldOff } from "lucide-react";
import { toast } from "sonner";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";
import { formatDate, formatDateTime } from "@/lib/date-format";
import { ALERT_TONE } from "@/lib/badge-tones";

type ExportRequest = {
  id: string;
  subject_type: string;
  subject_id: string;
  status: string;
  file_url: string | null;
  expires_at: string | null;
  requested_by: string | null;
  error: string | null;
  created_at: string;
};

export default function CandidateGDPRPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [requests, setRequests] = useState<ExportRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [erasing, setErasing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get<{ items: ExportRequest[]; total: number }>(
        `/recruitment/gdpr-requests?candidate_id=${id}`,
      );
      setRequests(data.items);
    } catch {
      setRequests([]);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleExport() {
    setExporting(true);
    try {
      const result = await api.post<ExportRequest>(
        "/recruitment/gdpr-export",
        { candidate_id: id },
      );
      if (result.file_url) {
        window.open(result.file_url, "_blank");
      } else {
        toast.success(
          `Export registered (id ${result.id.slice(0, 8)}). The file will be available once it is ready.`,
        );
      }
      void load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(false);
    }
  }

  async function handleErase() {
    if (
      !confirm(
        "Are you sure you want to anonymize this candidate's data? This action is irreversible. Name, email and interview transcripts will be replaced with \"redacted\".",
      )
    )
      return;
    if (!confirm("Confirm once more: anonymize the data?")) return;
    setErasing(true);
    try {
      await api.post("/recruitment/gdpr-erase", {
        candidate_id: id,
        confirm: true,
      });
      toast.success("Candidate data anonymized");
      void load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error");
    } finally {
      setErasing(false);
    }
  }

  return (
    <div className="space-y-5" data-testid="candidate-gdpr-page">
      <RecruitmentBreadcrumbs
        segments={[
          { label: "Candidates", href: "/recruitment/candidates" },
          { label: "Profile", href: `/recruitment/candidates/${id}` },
          { label: "GDPR" },
        ]}
      />
      <header>
        <h1 className="text-xl font-semibold tracking-tight">GDPR</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Data subject rights compliance: export all collected data and
          anonymize it (right to be forgotten). Soft-erase: the record remains,
          but PII is replaced with &ldquo;redacted&rdquo; for audit purposes.
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Download className="size-4" />
              Export data
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-muted-foreground">
              We will collect all candidate data (resume, questions, interviews,
              scores, consents) into JSON. The link will be valid for 7 days.
            </p>
            <Button
              onClick={handleExport}
              disabled={exporting}
              data-testid="gdpr-btn-export"
            >
              {exporting ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Download className="size-4" />
              )}
              Start export
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <ShieldOff className="size-4" />
              Erase data
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-muted-foreground">
              Candidate name, email, phone, resume text, interview transcripts
              and segments will be replaced with &ldquo;redacted&rdquo;. The
              record structure is preserved for audit purposes.
            </p>
            <div className={`flex gap-2 rounded-md border p-2 text-xs ${ALERT_TONE.amber}`}>
              <AlertTriangle className="size-4 shrink-0" />
              This action is irreversible.
            </div>
            <Button
              variant="destructive"
              onClick={handleErase}
              disabled={erasing}
              data-testid="gdpr-btn-erase"
            >
              {erasing ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <ShieldOff className="size-4" />
              )}
              Anonymize
            </Button>
          </CardContent>
        </Card>
      </div>

      <section className="space-y-2">
        <h2 className="text-sm font-medium">Export request history</h2>
        {loading ? (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            Loading…
          </div>
        ) : requests.length === 0 ? (
          <div className="rounded-md border border-dashed p-6 text-center text-xs text-muted-foreground">
            No export requests for this candidate yet.
          </div>
        ) : (
          <ul className="space-y-2">
            {requests.map((req) => (
              <li
                key={req.id}
                className="flex items-center justify-between gap-2 rounded-lg border p-3"
                data-testid={`gdpr-request-${req.id}`}
              >
                <div className="flex flex-col gap-0.5">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs">
                      {req.id.slice(0, 8)}
                    </span>
                    <Badge
                      variant={
                        req.status === "completed" ? "default" : "outline"
                      }
                    >
                      {req.status}
                    </Badge>
                    {req.expires_at && (
                      <span className="text-[11px] text-muted-foreground">
                        expires{" "}
                        {formatDate(req.expires_at)}
                      </span>
                    )}
                  </div>
                  <span className="text-[11px] text-muted-foreground">
                    {formatDateTime(req.created_at)}
                  </span>
                </div>
                {req.file_url ? (
                  <a
                    href={req.file_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-cyan-700 underline-offset-2 hover:underline"
                  >
                    Download JSON →
                  </a>
                ) : (
                  <span className="text-xs text-muted-foreground">
                    File unavailable
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
