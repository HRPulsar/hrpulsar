"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { RecruitmentBreadcrumbs, RecruitmentTabs } from "@/components/recruitment";
import { formatDateTime } from "@/lib/date-format";

type AuditEvent = {
  id: string;
  user_id: string | null;
  user_email: string | null;
  user_name: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  payload_diff: Record<string, unknown> | null;
  ip: string | null;
  user_agent: string | null;
  created_at: string;
};

const PAGE_SIZE = 50;

// Entity types emitted by the recruitment audit hooks (see
// backend/app/modules/recruitment/audit_registry.py and the settings
// router). Keeping this as a static list — entity_type is a controlled
// vocabulary, not free text.
const ENTITY_TYPE_OPTIONS = [
  "vacancy",
  "candidate",
  "interview",
  "consent",
  "report",
  "assessment",
  "question",
  "stage",
  "scale",
  "llm_provider",
  "transcription_provider",
  "branding",
  "retention",
] as const;

export default function AuditLogPage() {
  const [items, setItems] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    entity_type: "",
    action: "",
  });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams({
      skip: String(page * PAGE_SIZE),
      limit: String(PAGE_SIZE),
    });
    if (filters.entity_type) params.set("entity_type", filters.entity_type);
    if (filters.action) params.set("action", filters.action);

    try {
      const data = await api.get<{ items: AuditEvent[]; total: number }>(
        `/recruitment/audit-log?${params}`,
      );
      setItems(data.items);
      setTotal(data.total);
    } catch {
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [filters.entity_type, filters.action, page]);

  useEffect(() => {
    void load();
  }, [load]);

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="space-y-5" data-testid="recruitment-audit-log-page">
      <RecruitmentBreadcrumbs
        segments={[
          { label: "Settings", href: "/recruitment/settings" },
          { label: "Audit log" },
        ]}
      />
      <RecruitmentTabs />
      <header>
        <h1 className="text-xl font-semibold tracking-tight">
          Audit log
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          All mutating operations in the recruitment module: creating vacancies,
          changing stages, sending consents, generating reports, GDPR requests.
        </p>
      </header>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-3">
            <select
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              value={filters.entity_type}
              onChange={(e) =>
                setFilters((f) => ({ ...f, entity_type: e.target.value }))
              }
              data-testid="audit-filter-entity-type"
            >
              <option value="">entity_type (all)</option>
              {ENTITY_TYPE_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
            <Input
              placeholder="action (vacancy.create, …)"
              value={filters.action}
              onChange={(e) =>
                setFilters((f) => ({ ...f, action: e.target.value }))
              }
              data-testid="audit-filter-action"
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage(0)}
            >
              Apply
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="rounded-lg border">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="w-8 p-2"></th>
              <th className="p-2 text-left">Time</th>
              <th className="p-2 text-left">User</th>
              <th className="p-2 text-left">Action</th>
              <th className="p-2 text-left">Entity</th>
              <th className="p-2 text-left">IP</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} className="p-4 text-center text-muted-foreground">
                  <Loader2 className="inline size-4 animate-spin" /> Loading…
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={6} className="p-6 text-center text-xs text-muted-foreground">
                  No records found.
                </td>
              </tr>
            ) : (
              items.map((event) => (
                <ExpandableRow
                  key={event.id}
                  event={event}
                  expanded={expanded.has(event.id)}
                  onToggle={() => toggle(event.id)}
                />
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {total} records · page {page + 1} of{" "}
          {Math.max(1, Math.ceil(total / PAGE_SIZE))}
        </span>
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant="outline"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
          >
            ← Previous
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setPage((p) => p + 1)}
            disabled={(page + 1) * PAGE_SIZE >= total}
          >
            Next →
          </Button>
        </div>
      </div>
    </div>
  );
}

function ExpandableRow({
  event,
  expanded,
  onToggle,
}: {
  event: AuditEvent;
  expanded: boolean;
  onToggle: () => void;
}) {
  const ts = formatDateTime(event.created_at);
  const subject = event.user_email || event.user_name || "—";
  return (
    <>
      <tr className="border-t hover:bg-muted/30">
        <td className="p-2">
          <button onClick={onToggle} className="text-muted-foreground">
            {expanded ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronRight className="size-4" />
            )}
          </button>
        </td>
        <td className="whitespace-nowrap p-2 font-mono text-xs">{ts}</td>
        <td className="p-2 text-xs">{subject}</td>
        <td className="p-2">
          <Badge variant="outline" className="font-mono text-[11px]">
            {event.action}
          </Badge>
        </td>
        <td className="p-2 text-xs">
          <span className="text-muted-foreground">{event.entity_type}</span>{" "}
          {event.entity_id ? (
            <code className="rounded bg-muted px-1 py-0.5 text-[10px]">
              {event.entity_id.slice(0, 8)}
            </code>
          ) : null}
        </td>
        <td className="whitespace-nowrap p-2 font-mono text-[11px] text-muted-foreground">
          {event.ip || "—"}
        </td>
      </tr>
      {expanded && (
        <tr className="border-t bg-muted/20">
          <td></td>
          <td colSpan={5} className="p-2">
            <pre className="overflow-x-auto rounded bg-muted/40 p-2 text-[11px] leading-snug">
              {JSON.stringify(event.payload_diff ?? {}, null, 2)}
            </pre>
            <div className="mt-1 text-[10px] text-muted-foreground">
              {event.user_agent || "—"}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
