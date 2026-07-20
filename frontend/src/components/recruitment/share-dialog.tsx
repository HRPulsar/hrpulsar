"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import type { ReportShare } from "@/lib/types";
import { formatDate } from "@/lib/date-format";
import { Copy, Loader2, Share2, Trash2 } from "lucide-react";
import { toast } from "sonner";

interface ShareDialogProps {
  reportId: string;
  open: boolean;
  onClose: () => void;
}

const EXPIRY_OPTIONS = [3, 7, 14, 30];

export function RecruitmentShareDialog({ reportId, open, onClose }: ShareDialogProps) {
  const [recipients, setRecipients] = useState("");
  const [expires, setExpires] = useState(7);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [shares, setShares] = useState<ReportShare[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.get<ReportShare[]>(
        `/recruitment/reports/${reportId}/shares`,
      );
      setShares(rows);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [reportId]);

  useEffect(() => {
    if (!open) return;
    void refresh();
  }, [open, refresh]);

  const submit = useCallback(async () => {
    const list = recipients
      .split(/[,\s]+/)
      .map((e) => e.trim())
      .filter(Boolean);
    setSubmitting(true);
    try {
      await api.post<ReportShare>(`/recruitment/reports/${reportId}/share`, {
        recipients: list,
        expires_in_days: expires,
        message: message || null,
      });
      toast.success("Share link created");
      setRecipients("");
      setMessage("");
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to share report");
    } finally {
      setSubmitting(false);
    }
  }, [recipients, expires, message, reportId, refresh]);

  const revoke = useCallback(
    async (shareId: string) => {
      try {
        await api.delete(`/recruitment/reports/${reportId}/shares/${shareId}`);
        toast.success("Share revoked");
        await refresh();
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Failed to revoke");
      }
    },
    [reportId, refresh],
  );

  const copy = (url: string) => {
    void navigator.clipboard.writeText(url);
    toast.success("Link copied");
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-xl" data-testid="recruitment-share-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Share2 className="h-4 w-4" />
            Share report
          </DialogTitle>
          <DialogDescription>
            Generate a tokenised link recipients can open without an account.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="share-recipients">Recipients (comma-separated)</Label>
            <Input
              id="share-recipients"
              value={recipients}
              onChange={(e) => setRecipients(e.target.value)}
              placeholder="hiring-manager@example.com"
              data-testid="share-recipients"
            />
          </div>
          <div className="flex items-center gap-2">
            <Label className="text-sm">Expiry:</Label>
            {EXPIRY_OPTIONS.map((d) => (
              <Button
                key={d}
                size="sm"
                variant={expires === d ? "default" : "outline"}
                onClick={() => setExpires(d)}
                data-testid={`share-expires-${d}`}
              >
                {d}d
              </Button>
            ))}
          </div>
          <div className="space-y-2">
            <Label htmlFor="share-message">Message (optional, 200 chars)</Label>
            <Input
              id="share-message"
              value={message}
              maxLength={200}
              onChange={(e) => setMessage(e.target.value)}
            />
          </div>
          <Button onClick={submit} disabled={submitting} data-testid="share-submit">
            {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Share2 className="mr-2 h-4 w-4" />}
            Create share link
          </Button>

          <div className="space-y-2">
            <h4 className="text-sm font-medium">Active shares</h4>
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            ) : shares.length === 0 ? (
              <p className="text-sm text-muted-foreground">No shares yet.</p>
            ) : (
              <ul className="divide-y rounded border">
                {shares.map((s) => (
                  <li key={s.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                    <div className="min-w-0">
                      <p className="truncate font-mono text-xs">{s.share_url}</p>
                      <p className="text-xs text-muted-foreground">
                        Expires {formatDate(s.expires_at)} • Opens: {s.open_count}
                        {s.revoked_at ? " • revoked" : ""}
                      </p>
                    </div>
                    <div className="flex items-center gap-1">
                      <Button size="sm" variant="ghost" onClick={() => copy(s.share_url)} aria-label="Copy">
                        <Copy className="h-4 w-4" />
                      </Button>
                      {!s.revoked_at && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => void revoke(s.id)}
                          aria-label="Revoke"
                          data-testid={`share-revoke-${s.id}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
