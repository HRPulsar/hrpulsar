"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { MassExam } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DatePicker } from "@/components/ui/date-picker";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { MultiSelectFilter } from "@/components/multi-select-filter";
import { usePermissions } from "@/hooks/use-permissions";
import { toast } from "sonner";
import Link from "next/link";
import { ChevronRight, MoreHorizontal, PenLine, Plus, Search, X } from "lucide-react";
import {
  ExamReviewSheet,
  ExamTakeSheet,
} from "@/components/exam/exam-take-sheet";
import { isPastDeadline, todayLocalISO } from "@/lib/deadline";
import { formatDate } from "@/lib/date-format";
import {
  STATUS_CHIP_COLOR,
  STATUS_LABELS,
  STATUS_TRANSITIONS,
  isTerminalStatus,
  statusLabel,
} from "./status";
import {
  examListTimestamp,
  hasActiveExamFilters,
  matchesExamFilters,
  sortExamsForList,
} from "@/lib/exam-filters";

const FILTERABLE_STATUSES = ["draft", "sent", "in_progress", "done", "cancelled"] as const;

const emptyForm = { title: "", description: "", ended_at: "" };

interface EmployeeExamRow {
  id: string;
  mass_exam_id: string;
  status: string;
  mass_exam_title: string | null;
  created_at: string;
  score: number | null;
  max_score: number | null;
  finished_at: string | null;
}

export default function ExamsPage() {
  const { canManage } = usePermissions();
  if (canManage) {
    return <ManagerExamsView />;
  }
  return <EmployeeExamsView />;
}

function ManagerExamsView() {
  const [exams, setExams] = useState<MassExam[]>([]);
  const [loading, setLoading] = useState(true);

  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);

  const [statusOpen, setStatusOpen] = useState(false);
  const [statusTarget, setStatusTarget] = useState<MassExam | null>(null);
  const [newStatus, setNewStatus] = useState("");

  const [saving, setSaving] = useState(false);

  // HRP-227: title search + multi-status filter mirroring Development.
  const [searchQuery, setSearchQuery] = useState("");
  const [filterStatuses, setFilterStatuses] = useState<string[]>([]);

  async function load() {
    try {
      setExams(await api.get<MassExam[]>("/mass-exams"));
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const titleTrimmed = form.title.trim();
  const canCreate = titleTrimmed.length > 0 && !isPastDeadline(form.ended_at);

  async function handleCreate() {
    if (!titleTrimmed) {
      toast.error("Title is required");
      return;
    }
    if (isPastDeadline(form.ended_at)) {
      toast.error("Deadline cannot be in the past");
      return;
    }
    setSaving(true);
    try {
      await api.post("/mass-exams", {
        title: titleTrimmed,
        description: form.description || null,
        ended_at: form.ended_at || null,
      });
      toast.success("Exam created");
      setCreateOpen(false);
      setForm(emptyForm);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create");
    } finally {
      setSaving(false);
    }
  }

  function openStatus(e: MassExam) {
    setStatusTarget(e);
    setNewStatus("");
    setStatusOpen(true);
  }

  async function handleStatus() {
    if (!statusTarget || !newStatus) return;
    setSaving(true);
    try {
      await api.post(`/mass-exams/${statusTarget.id}/status`, { status_code: newStatus });
      toast.success("Status updated");
      setStatusOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update status");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="py-12 text-center text-muted-foreground">Loading...</div>;

  const allowedNextStatuses = statusTarget
    ? STATUS_TRANSITIONS[statusTarget.status] ?? []
    : [];

  // HRP-227 + HRP-233: filter, then bucket-sort (active → done → cancelled).
  const filters = { searchQuery, filterStatuses };
  const filtered = sortExamsForList(exams.filter((e) => matchesExamFilters(e, filters)));
  const filtersActive = hasActiveExamFilters(filters);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight" data-testid="exams-heading">Exams</h1>
          {/* HRP-290: counter respects active filters (Assessments parity). */}
          <p className="text-sm text-muted-foreground" data-testid="exams-count">
            {filtered.length} exam{filtered.length !== 1 ? "s" : ""}
          </p>
        </div>
        <Button size="sm" onClick={() => setCreateOpen(true)} data-testid="exams-btn-create">
          <Plus className="mr-1 h-4 w-4" />
          Create exam
        </Button>
      </div>

      {/* HRP-227: title search + multi-status filter — parity with Development. */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            data-testid="exams-input-search"
            placeholder="Search by title..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8"
          />
        </div>
        <MultiSelectFilter
          data-testid="exams-multi-statuses"
          options={FILTERABLE_STATUSES.map((s) => ({ value: s, label: STATUS_LABELS[s] ?? s }))}
          value={filterStatuses}
          onChange={setFilterStatuses}
          placeholder="All statuses"
          className="w-40"
        />
        {filtersActive && (
          <Button
            data-testid="exams-btn-clear-filters"
            variant="ghost"
            size="sm"
            onClick={() => { setSearchQuery(""); setFilterStatuses([]); }}
          >
            <X className="mr-1 h-3 w-3" />
            Clear
          </Button>
        )}
      </div>

      {exams.length === 0 ? (
        <div className="rounded-lg border border-dashed p-12 text-center text-muted-foreground" data-testid="exams-empty">No exams yet</div>
      ) : filtered.length === 0 ? (
        <div className="rounded-lg border border-dashed p-12 text-center text-muted-foreground" data-testid="exams-empty-filtered">No exams match the filters</div>
      ) : (
        <div className="rounded-lg border">
          <Table data-testid="exams-table">
            <TableHeader>
              <TableRow>
                <TableHead>Title</TableHead>
                <TableHead>Status</TableHead>
                {/* HRP-233: no header — the per-row label changes with status. */}
                <TableHead />
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((e) => {
                const ts = examListTimestamp(e);
                return (
                  <TableRow key={e.id} data-testid={`exams-row-${e.id}`}>
                    <TableCell className="font-medium">
                      <Link href={`/exams/${e.id}`} className="hover:underline">{e.title}</Link>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className={STATUS_CHIP_COLOR[e.status] || ""} data-testid={`exams-row-${e.id}-status`}>
                        {statusLabel(e.status)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground" data-testid={`exams-row-${e.id}-timestamp`}>
                      {ts ? `${ts.label}: ${formatDate(ts.iso)}` : "—"}
                    </TableCell>
                    <TableCell>
                      {!isTerminalStatus(e.status) && (
                        <DropdownMenu>
                          <DropdownMenuTrigger render={<Button variant="ghost" size="icon-xs" />} data-testid={`exams-row-${e.id}-actions`}>
                            <MoreHorizontal className="h-4 w-4" />
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => openStatus(e)}>Change status</DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Create dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent data-testid="exams-modal-create">
          <DialogHeader><DialogTitle>Create exam</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>
                Title <span className="text-destructive">*</span>
              </Label>
              {/* HRP-230 redo: no red highlight on the pristine field — the
                  asterisk plus the disabled Create button carry the
                  requirement until the user types something. */}
              <Input
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                data-testid="exams-modal-create-input-title"
                maxLength={100}
              />
            </div>
            <div className="space-y-2">
              <Label>Description</Label>
              <Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={2} data-testid="exams-modal-create-input-description" maxLength={250} />
            </div>
            <div className="space-y-2">
              <Label>Deadline</Label>
              {/* HRP-335: shared DatePicker (HRP-152) instead of the
                  native date input. */}
              <DatePicker
                min={todayLocalISO()}
                value={form.ended_at}
                onChange={(value) => setForm({ ...form, ended_at: value })}
                data-testid="exams-modal-create-input-end-date"
              />
              {isPastDeadline(form.ended_at) && (
                <p className="text-xs text-destructive">Deadline cannot be in the past</p>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)} disabled={saving}>Cancel</Button>
            <Button
              onClick={handleCreate}
              disabled={saving || !canCreate}
              data-testid="exams-modal-create-btn-submit"
            >
              {saving ? "Creating..." : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Status dialog */}
      <Dialog open={statusOpen} onOpenChange={setStatusOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Change status</DialogTitle></DialogHeader>
          <div className="space-y-2">
            <Label>New status</Label>
            <Select value={newStatus} onValueChange={setNewStatus}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select a status" />
              </SelectTrigger>
              <SelectContent>
                {allowedNextStatuses.length === 0 ? (
                  <div className="px-2 py-1.5 text-sm text-muted-foreground">
                    No further transitions available
                  </div>
                ) : (
                  allowedNextStatuses.map((s) => (
                    <SelectItem key={s} value={s}>{STATUS_LABELS[s] ?? s}</SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setStatusOpen(false)} disabled={saving}>Cancel</Button>
            <Button onClick={handleStatus} disabled={saving || !newStatus}>{saving ? "Saving..." : "Save"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function EmployeeExamsView() {
  const [exams, setExams] = useState<EmployeeExamRow[]>([]);
  const [loading, setLoading] = useState(true);
  // HRP-328: take/review side sheets. The icon of the row whose sheet is
  // open stays highlighted (hover-style) so the active exam is obvious.
  const [takeExamId, setTakeExamId] = useState<string | null>(null);
  const [takeOpen, setTakeOpen] = useState(false);
  const [reviewExamId, setReviewExamId] = useState<string | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  // Monotonic sequence so an older in-flight GET can never overwrite a
  // newer list (load() is also fired from sheet callbacks).
  const loadSeq = useRef(0);

  const load = async () => {
    const seq = ++loadSeq.current;
    try {
      const rows = await api.get<EmployeeExamRow[]>("/exams");
      if (seq === loadSeq.current) setExams(rows);
    } catch {
      if (seq === loadSeq.current) toast.error("Failed to load exams");
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  if (loading) {
    return <div className="py-12 text-center text-muted-foreground">Loading...</div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight" data-testid="exams-heading">Exams</h1>
        <p className="text-sm text-muted-foreground">
          {exams.length} exam{exams.length !== 1 ? "s" : ""}
        </p>
      </div>

      {exams.length === 0 ? (
        <div className="rounded-lg border border-dashed p-12 text-center text-muted-foreground" data-testid="exams-empty">No exams yet</div>
      ) : (
        <div className="rounded-lg border">
          <Table data-testid="exams-table">
            <TableHeader>
              <TableRow>
                <TableHead>Title</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Score</TableHead>
                <TableHead>Assigned</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {exams.map((e) => {
                const takeActive = takeOpen && takeExamId === e.id;
                const reviewActive = reviewOpen && reviewExamId === e.id;
                return (
                  <TableRow key={e.id} data-testid={`exams-row-${e.id}`}>
                    <TableCell className="font-medium">
                      {e.mass_exam_title ?? "Untitled"}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className={STATUS_CHIP_COLOR[e.status] || ""}>
                        {statusLabel(e.status)}
                      </Badge>
                    </TableCell>
                    <TableCell data-testid={`exams-row-${e.id}-score`}>
                      {e.score != null && e.max_score != null
                        ? `${e.score} / ${e.max_score}`
                        : "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{formatDate(e.created_at)}</TableCell>
                    <TableCell>
                      {(e.status === "assigned" || e.status === "in_progress") && (
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          className={takeActive ? "bg-accent text-accent-foreground" : ""}
                          title="Take this exam"
                          onClick={() => {
                            setTakeExamId(e.id);
                            setTakeOpen(true);
                          }}
                          data-testid={`exams-row-${e.id}-take`}
                        >
                          <PenLine className="h-4 w-4" />
                        </Button>
                      )}
                      {/* HRP-236: a survey voided by a whole-exam cancel keeps
                          its submitted results reviewable. */}
                      {(e.status === "done" ||
                        (e.status === "cancelled" && e.finished_at != null)) && (
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          className={reviewActive ? "bg-accent text-accent-foreground" : ""}
                          title="View submitted results"
                          onClick={() => {
                            setReviewExamId(e.id);
                            setReviewOpen(true);
                          }}
                          data-testid={`exams-row-${e.id}-review`}
                        >
                          <ChevronRight className="h-4 w-4" />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <ExamTakeSheet
        examId={takeExamId}
        open={takeOpen}
        onOpenChange={setTakeOpen}
        onFinished={() => void load()}
      />
      <ExamReviewSheet
        examId={reviewExamId}
        open={reviewOpen}
        onOpenChange={setReviewOpen}
      />
    </div>
  );
}
