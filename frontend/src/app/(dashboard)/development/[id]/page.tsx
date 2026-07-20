"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { EmployeeSummaryLine } from "@/components/employee/employee-summary-line";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getBrandAccent } from "@/lib/brand";
import { api } from "@/lib/api";
import { ALERT_TONE, BADGE_COLOR } from "@/lib/badge-tones";
import {
  isPDPGradeLocked,
  isTerminalPDPStatus,
  pdpNextStatuses,
  pdpStatusActionLabel,
  pdpStatusColor,
  pdpStatusLabel,
  type PDPStatus,
} from "@/lib/pdp-status";
import type {
  DictionaryItem,
  GradeOption,
  PDPDetail,
  PDPProgressEntry,
} from "@/lib/types";
import { formatDate, formatDateTime } from "@/lib/date-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DatePicker } from "@/components/ui/date-picker";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { ArrowLeft, ArrowDown, ArrowUp, Check, Download, ExternalLink, FileText, Paperclip, Pencil, Plus, Send, Trash2, X } from "lucide-react";
import { usePermissions } from "@/hooks/use-permissions";
import { useAuth } from "@/context/auth-context";
import { isPastDeadline, todayLocalISO } from "@/lib/deadline";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

const brandAccent = getBrandAccent();

export default function PDPDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [pdp, setPdp] = useState<PDPDetail | null>(null);
  const [progressTimeline, setProgressTimeline] = useState<PDPProgressEntry[]>([]);
  const [loading, setLoading] = useState(true);

  // Add/edit item
  const [itemOpen, setItemOpen] = useState(false);
  const [itemForm, setItemForm] = useState({ title: "", description: "", sort_index: 0 });
  const [editingItemId, setEditingItemId] = useState<string | null>(null);

  // Add/edit material
  const [matOpen, setMatOpen] = useState(false);
  const [matItemId, setMatItemId] = useState("");
  const [matForm, setMatForm] = useState({ title: "", format: "", link: "" });
  const [editingMaterialId, setEditingMaterialId] = useState<string | null>(null);

  // Add comment
  const [commentText, setCommentText] = useState("");
  const [commentFile, setCommentFile] = useState<{ id: string; name: string } | null>(null);
  const [commentUploading, setCommentUploading] = useState(false);

  // Material file
  const [matFile, setMatFile] = useState<{ id: string; name: string } | null>(null);
  const [matUploading, setMatUploading] = useState(false);
  // HRP-14: AbortController used to cancel an in-flight material file upload
  // when the user closes the modal (Cancel button or click-outside) while
  // a large file is still transferring. Without this the next open of the
  // modal still showed "Uploading…" with Add disabled.
  const matUploadAbortRef = useRef<AbortController | null>(null);

  const [saving, setSaving] = useState(false);

  // Inline edit
  const { canManage, isAdmin, roles } = usePermissions();
  const { user } = useAuth();
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [editingDeadline, setEditingDeadline] = useState(false);
  const [deadlineDraft, setDeadlineDraft] = useState("");

  // Change spec/grade
  const [gradeChangeOpen, setGradeChangeOpen] = useState(false);
  const [specDraft, setSpecDraft] = useState("");
  const [gradeDraft, setGradeDraft] = useState("");
  const [specializations, setSpecializations] = useState<DictionaryItem[]>([]);
  // HRP-293: grade options are server-side — chains of the selected
  // specialization minus tenant-deactivated grades (include_id keeps the
  // PDP's saved grade selectable).
  const [specGrades, setSpecGrades] = useState<GradeOption[]>([]);

  // HRP-292: offer only active items; the PDP's saved (drafted) value
  // stays in the list even after deactivation so the stored selection
  // isn't lost when the dialog reopens.
  const specOptions = useMemo(
    () => specializations.filter((s) => s.is_active || s.id === specDraft),
    [specializations, specDraft],
  );
  const dictsLoaded = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    try {
      const [detail, timeline] = await Promise.all([
        api.get<PDPDetail>(`/pdp/${id}`),
        api.get<PDPProgressEntry[]>(`/analytics/pdp/${id}/progress`).catch(() => [] as PDPProgressEntry[]),
      ]);
      setPdp(detail);
      setProgressTimeline(timeline);
    } catch {
      toast.error("Failed to load PDP");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function changeStatus(status: string) {
    setSaving(true);
    try {
      await api.post(`/pdp/${id}/status`, { status_code: status });
      toast.success(`Status changed to ${pdpStatusLabel(status)}`);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to change status");
    } finally {
      setSaving(false);
    }
  }

  function startEditTitle() {
    if (!pdp || !canManage || isTerminalPDPStatus(pdp.status)) return;
    setTitleDraft(pdp.title);
    setEditingTitle(true);
  }

  async function saveTitle() {
    if (!pdp) return;
    const next = titleDraft.trim();
    if (!next || next === pdp.title) {
      setEditingTitle(false);
      return;
    }
    setSaving(true);
    try {
      const updated = await api.patch<PDPDetail>(`/pdp/${id}`, { title: next });
      setPdp((cur) => (cur ? { ...cur, title: updated.title } : cur));
      setEditingTitle(false);
      toast.success("Title updated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update title");
    } finally {
      setSaving(false);
    }
  }

  function startEditDeadline() {
    if (!pdp || !canManage || isTerminalPDPStatus(pdp.status)) return;
    setDeadlineDraft(pdp.deadline ? pdp.deadline.slice(0, 10) : "");
    setEditingDeadline(true);
  }

  // Monotonic token: a slow response for a previously selected
  // specialization must not overwrite the options of the current one.
  const gradeReqSeq = useRef(0);

  async function loadGradesForSpec(specId: string, includeGradeId?: string) {
    const seq = ++gradeReqSeq.current;
    // Clear immediately: the previous specialization's options must not be
    // pickable while the new list is in flight.
    setSpecGrades([]);
    if (!specId) return;
    const url = includeGradeId
      ? `/grade-system/specializations/${specId}/grades?include_id=${includeGradeId}`
      : `/grade-system/specializations/${specId}/grades`;
    let options: GradeOption[] = [];
    try {
      options = await api.get<GradeOption[]>(url);
    } catch {
      options = [];
    }
    // include_id only rescues a chained-but-deactivated grade; a plan
    // saved before the chain restriction may reference an unchained one —
    // inject it from the stored title so the selection stays visible.
    if (
      includeGradeId &&
      pdp?.grade_id === includeGradeId &&
      pdp.grade_title &&
      !options.some((g) => g.id === includeGradeId)
    ) {
      options = [...options, { id: includeGradeId, title: pdp.grade_title }];
    }
    if (!mounted.current || seq !== gradeReqSeq.current) return;
    setSpecGrades(options);
  }

  function handleSpecDraftChange(specId: string) {
    setSpecDraft(specId);
    // The saved grade only survives while the saved specialization is
    // selected — grades are scoped to their specialization's chains.
    const savedGrade =
      pdp && specId === (pdp.specialization_id ?? "") ? pdp.grade_id ?? "" : "";
    setGradeDraft(savedGrade);
    loadGradesForSpec(specId, savedGrade || undefined);
  }

  async function openGradeChange() {
    if (!pdp) return;
    if (!dictsLoaded.current) {
      try {
        const specs = await api
          .get<DictionaryItem[]>("/dictionaries/specialization")
          .catch(() => []);
        if (!mounted.current) return;
        setSpecializations(specs);
        dictsLoaded.current = true;
      } catch {
        // ignore: empty dropdowns are still functional
      }
    }
    if (!mounted.current) return;
    setSpecDraft(pdp.specialization_id ?? "");
    setGradeDraft(pdp.grade_id ?? "");
    await loadGradesForSpec(
      pdp.specialization_id ?? "",
      pdp.grade_id ?? undefined,
    );
    if (!mounted.current) return;
    setGradeChangeOpen(true);
  }

  async function saveGradeChange() {
    if (!pdp) return;
    const nextSpec = specDraft || null;
    const nextGrade = gradeDraft || null;
    if (
      nextSpec === (pdp.specialization_id ?? null) &&
      nextGrade === (pdp.grade_id ?? null)
    ) {
      setGradeChangeOpen(false);
      return;
    }
    setSaving(true);
    try {
      await api.patch<PDPDetail>(`/pdp/${id}`, {
        specialization_id: nextSpec,
        grade_id: nextGrade,
      });
      toast.success("Specialization and grade updated");
      setGradeChangeOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update");
    } finally {
      setSaving(false);
    }
  }

  async function saveDeadline() {
    if (!pdp) return;
    const value = deadlineDraft.trim();
    const original = pdp.deadline ? pdp.deadline.slice(0, 10) : "";
    if (value === original) {
      setEditingDeadline(false);
      return;
    }
    if (isPastDeadline(value)) {
      toast.error("Deadline cannot be in the past");
      return;
    }
    let nextIso: string | null = null;
    if (value) {
      // Anchor at local end-of-day so a date chosen in +UTC keeps the same
      // calendar day after server-side ISO normalisation.
      const [y, m, d] = value.split("-").map(Number);
      nextIso = new Date(y, m - 1, d, 23, 59, 59).toISOString();
    }
    setSaving(true);
    try {
      const updated = await api.patch<PDPDetail>(`/pdp/${id}`, { deadline: nextIso });
      setPdp((cur) => (cur ? { ...cur, deadline: updated.deadline } : cur));
      setEditingDeadline(false);
      toast.success("Deadline updated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update deadline");
    } finally {
      setSaving(false);
    }
  }

  function openAddItem() {
    setEditingItemId(null);
    setItemForm({ title: "", description: "", sort_index: 0 });
    setItemOpen(true);
  }

  function openEditItem(item: PDPDetail["items"][number]) {
    setEditingItemId(item.id);
    setItemForm({
      title: item.title,
      description: item.description ?? "",
      sort_index: item.sort_index,
    });
    setItemOpen(true);
  }

  async function saveItem() {
    setSaving(true);
    try {
      if (editingItemId) {
        await api.patch(`/pdp/${id}/items/${editingItemId}`, {
          title: itemForm.title.trim(),
          description: itemForm.description || null,
        });
        toast.success("Item updated");
      } else {
        await api.post(`/pdp/${id}/items`, itemForm);
        toast.success("Item added");
      }
      setItemOpen(false);
      setEditingItemId(null);
      setItemForm({ title: "", description: "", sort_index: 0 });
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save item");
    } finally {
      setSaving(false);
    }
  }

  async function deleteItem(itemId: string) {
    if (!confirm("Delete this item?")) return;
    setSaving(true);
    try {
      await api.delete(`/pdp/${id}/items/${itemId}`);
      toast.success("Item deleted");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete item");
    } finally {
      setSaving(false);
    }
  }

  async function moveItem(fromIdx: number, toIdx: number, sorted: PDPDetail["items"]) {
    if (!pdp) return;
    if (toIdx < 0 || toIdx >= sorted.length) return;
    const reordered = [...sorted];
    const [moved] = reordered.splice(fromIdx, 1);
    reordered.splice(toIdx, 0, moved);
    setPdp({
      ...pdp,
      items: reordered.map((it, idx) => ({ ...it, sort_index: idx })),
    });
    try {
      await api.post(`/pdp/${id}/items/reorder`, {
        ordered_ids: reordered.map((it) => it.id),
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to reorder");
      await load();
    }
  }

  async function toggleItemPassed(itemId: string, nextPassed: boolean) {
    try {
      await api.post(`/pdp/${id}/items/${itemId}/pass`, { is_passed: nextPassed });
      toast.success(nextPassed ? "Item marked as passed" : "Item unmarked");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update item");
    }
  }

  function openAddMaterial(itemId: string) {
    setMatItemId(itemId);
    setEditingMaterialId(null);
    setMatForm({ title: "", format: "", link: "" });
    setMatFile(null);
    setMatOpen(true);
  }

  function openEditMaterial(itemId: string, mat: PDPDetail["items"][number]["materials"][number]) {
    setMatItemId(itemId);
    setEditingMaterialId(mat.id);
    setMatForm({
      title: mat.title,
      format: mat.format ?? "",
      link: mat.link ?? "",
    });
    setMatFile(
      mat.file_id && mat.file_name
        ? { id: mat.file_id, name: mat.file_name }
        : null,
    );
    setMatOpen(true);
  }

  async function deleteMaterial(itemId: string, materialId: string) {
    if (!confirm("Delete this material?")) return;
    try {
      await api.delete(`/pdp/${id}/items/${itemId}/materials/${materialId}`);
      toast.success("Material deleted");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete material");
    }
  }

  async function handleMatFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    // HRP-14: cancel any previous in-flight upload before starting a new one
    // (e.g. user re-picked a file while the first one was still uploading).
    matUploadAbortRef.current?.abort();
    const controller = new AbortController();
    matUploadAbortRef.current = controller;
    setMatUploading(true);
    try {
      const res = await api.upload<{ id: string; original_name: string }>(
        "/files/upload",
        file,
        { signal: controller.signal },
      );
      // The dialog may have closed while we were waiting: drop the result if
      // the upload was aborted in the interim, otherwise it would surface as
      // a "phantom" attachment on the next open.
      if (controller.signal.aborted) return;
      setMatFile({ id: res.id, name: res.original_name });
      if (!matForm.title) setMatForm((f) => ({ ...f, title: res.original_name }));
    } catch (err) {
      // AbortError is the expected outcome when the user closes the modal
      // mid-upload — no toast in that case.
      const aborted =
        controller.signal.aborted ||
        (err instanceof DOMException && err.name === "AbortError");
      if (!aborted) {
        toast.error(err instanceof Error ? err.message : "Failed to upload file");
      }
    } finally {
      if (matUploadAbortRef.current === controller) {
        matUploadAbortRef.current = null;
      }
      setMatUploading(false);
      e.target.value = "";
    }
  }

  function handleMatOpenChange(open: boolean) {
    // HRP-14: closing the dialog (Cancel button OR click outside) must abort
    // any active file upload so the next open starts from a clean slate.
    if (!open) {
      matUploadAbortRef.current?.abort();
      matUploadAbortRef.current = null;
      setMatUploading(false);
    }
    setMatOpen(open);
  }

  async function saveMaterial() {
    setSaving(true);
    try {
      if (editingMaterialId) {
        await api.patch(`/pdp/${id}/items/${matItemId}/materials/${editingMaterialId}`, {
          title: matForm.title,
          format: matForm.format || null,
          link: matForm.link || null,
          file_id: matFile?.id || null,
        });
        toast.success("Material updated");
      } else {
        await api.post(`/pdp/${id}/items/${matItemId}/materials`, {
          ...matForm,
          file_id: matFile?.id || null,
        });
        toast.success("Material added");
      }
      setMatOpen(false);
      setEditingMaterialId(null);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save material");
    } finally {
      setSaving(false);
    }
  }

  async function handleCommentFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setCommentUploading(true);
    try {
      const res = await api.upload<{ id: string; original_name: string }>("/files/upload", file);
      setCommentFile({ id: res.id, name: res.original_name });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to upload file");
    } finally {
      setCommentUploading(false);
      e.target.value = "";
    }
  }

  async function addComment() {
    if (!commentText.trim() && !commentFile) return;
    setSaving(true);
    try {
      await api.post(`/pdp/${id}/comments`, {
        text: commentText || (commentFile ? `Attached: ${commentFile.name}` : ""),
        file_id: commentFile?.id || null,
      });
      toast.success("Comment added");
      setCommentText("");
      setCommentFile(null);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add comment");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">Loading...</div>
    );
  }

  if (!pdp) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" render={<Link href="/development" />}>
          <ArrowLeft className="mr-1 h-4 w-4" />
          Back to development plans
        </Button>
        <div className="py-12 text-center text-muted-foreground">PDP not found</div>
      </div>
    );
  }

  const isTerminal = isTerminalPDPStatus(pdp.status);
  const isOwner = pdp.is_owner;
  // HRP-130: the assigned PDP reviewer (non-admin) can manage item
  // checkboxes alongside the admin while the plan is under review.
  // ``is_reviewer`` is computed server-side and includes the division
  // manager fallback (a manager who appears as the reviewer name without
  // an explicit ``reviewer_id`` still counts).
  const isAssignedReviewer = pdp.is_reviewer;
  const isPlatformAdmin = user?.is_platform_admin === true;
  // Mirrors backend ``ADMIN_ROLE_CODES`` (admin / hr / platform_admin) so
  // the UI doesn't lock out HR users who can already toggle items via the
  // API.
  const adminTier = isAdmin || isPlatformAdmin || roles.includes("hr");
  // HRP-19: a regular employee viewing their own plan only ever sees
  // "submit for review" (in sent / in_progress / returned). Admins and
  // managers always see the full admin transition graph — even when they
  // happen to be linked to the plan's employee (common in single-tenant
  // demo accounts and the e2e fixture).
  const ownerOnlySubmitFlow = isOwner && !canManage;
  const ownerCanSubmitForReview =
    ownerOnlySubmitFlow &&
    ["sent", "in_progress", "returned"].includes(pdp.status);
  const nextStatuses: PDPStatus[] = ownerOnlySubmitFlow
    ? ownerCanSubmitForReview
      ? ["review"]
      : []
    : pdpNextStatuses(pdp.status);
  // HRP-12: the admin can't send an empty plan or one whose items lack
  // materials — disable "send" with a tooltip until both conditions hold.
  // HRP-191 REDO: a past deadline no longer disables the Send button —
  // matching Assessments / Talent market the button stays enabled and the
  // backend 400 ("Deadline is in the past") surfaces as a snackbar on
  // click, so the operator can act on the message instead of guessing why
  // the action is greyed out.
  const sendBlockedReason =
    pdp.status === "draft" && pdp.items.length === 0
      ? "Add at least one item before sending"
      : pdp.status === "draft" &&
          pdp.items.some((it) => it.materials.length === 0)
        ? "Each item must have at least one material before sending"
        : null;
  // HRP-19: employee submitting for review needs every item ticked off.
  const reviewBlockedReason = ownerCanSubmitForReview
    ? pdp.items.length === 0
      ? "There are no items to review yet"
      : pdp.items.some((it) => !it.is_passed)
        ? "Mark every item as passed before submitting for review"
        : null
    : null;
  // HRP-130 / HRP-187: while a plan is under review the admin/reviewer
  // can only push it back to the employee (= "return") if:
  //   * every item carries at least one material (parity with Send in
  //     Draft — a bare item added during review would otherwise leave the
  //     owner with a "redo" they can't act on);
  //   * at least one item is still unchecked — once all items are accepted
  //     the only sensible next action is Complete.
  // HRP-187 REDO: deadline is NOT a UI-side block — like Assessments /
  // Talent market the button stays enabled, the backend 400 surfaces as a
  // snackbar.
  const returnFromReviewBlockedReason =
    pdp.status === "review" && pdp.items.length === 0
      ? "Add at least one item before returning"
      : pdp.status === "review" &&
          pdp.items.some((it) => it.materials.length === 0)
        ? "Each item must have at least one material before returning"
        : pdp.status === "review" &&
            pdp.items.length > 0 &&
            pdp.items.every((it) => it.is_passed)
          ? "All items are accepted — complete the plan instead of returning it"
          : null;
  // Same exception as Assessment detail (HRP-23 review): if the draft equals
  // the existing saved deadline, don't paint it as past — the operator just
  // re-opened the editor on a legacy past date and pressing Save without
  // changes is a no-op upstream in saveDeadline.
  const pdpExistingDeadline = pdp.deadline ? pdp.deadline.slice(0, 10) : "";
  const pdpDeadlineDraftIsPast =
    deadlineDraft.trim() !== pdpExistingDeadline &&
    isPastDeadline(deadlineDraft);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon-sm" render={<Link href="/development" />} data-testid="development-detail-btn-back">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          {editingTitle ? (
            <div className="flex items-center gap-2">
              <Input
                autoFocus
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                maxLength={100}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    saveTitle();
                  } else if (e.key === "Escape") {
                    e.preventDefault();
                    setEditingTitle(false);
                  }
                }}
                className="h-9 text-2xl font-semibold tracking-tight"
                disabled={saving}
                data-testid="development-detail-title-input"
              />
              <Button
                size="icon-sm"
                variant="ghost"
                onClick={saveTitle}
                disabled={saving || !titleDraft.trim()}
                data-testid="development-detail-title-save"
                aria-label="Save title"
              >
                <Check className="h-4 w-4" />
              </Button>
              <Button
                size="icon-sm"
                variant="ghost"
                onClick={() => setEditingTitle(false)}
                disabled={saving}
                data-testid="development-detail-title-cancel"
                aria-label="Cancel edit"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <h1
                className={`text-2xl font-semibold tracking-tight ${
                  canManage && !isTerminal ? "cursor-pointer hover:opacity-80" : ""
                }`}
                onClick={startEditTitle}
                data-testid="development-detail-title"
              >
                {pdp.title}
              </h1>
              {canManage && !isTerminal && (
                <Button
                  size="icon-xs"
                  variant="ghost"
                  onClick={startEditTitle}
                  data-testid="development-detail-title-edit"
                  aria-label="Edit title"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
          )}
          <p className="text-sm text-muted-foreground">
            {pdp.total_progress}% complete
          </p>
        </div>
        <Badge variant="secondary" className={pdpStatusColor(pdp.status)} data-testid="development-detail-status">
          {pdpStatusLabel(pdp.status)}
        </Badge>
      </div>

      {/* Info */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Details</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-3">
            <div>
              <p className="text-muted-foreground">Status</p>
              <Badge variant="secondary" className={pdpStatusColor(pdp.status)}>
                {pdpStatusLabel(pdp.status)}
              </Badge>
            </div>
            <div>
              <p className="text-muted-foreground">Employee</p>
              <p className="font-medium" data-testid="development-detail-employee">
                {pdp.employee_name ? (
                  <Link href={`/employees/${pdp.employee_id}`} className="hover:underline">
                    {pdp.employee_name}
                  </Link>
                ) : (
                  "—"
                )}
              </p>
              {/* HRP-333: position + non-active status chip under the
                  employee link. */}
              {pdp.employee_name && (
                <EmployeeSummaryLine
                  employee={{
                    user_name: pdp.employee_name,
                    position_title: pdp.employee_position_title,
                    status: pdp.employee_status,
                  }}
                  hideName
                  data-testid="development-detail-employee-summary"
                />
              )}
            </div>
            <div>
              <p className="text-muted-foreground">Progress</p>
              <div className="flex items-center gap-2">
                <div className="h-2 w-20 overflow-hidden rounded-full bg-muted" data-testid="development-detail-progress">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${pdp.total_progress}%` }} />
                </div>
                <span className="text-sm font-medium">{pdp.total_progress}%</span>
              </div>
            </div>
            <div>
              <p className="text-muted-foreground">
                {/* HRP-132: terminal plans expose the moment they ended,
                    not the deadline they were planning against. */}
                {pdp.status === "done"
                  ? "Completed at"
                  : pdp.status === "cancelled"
                    ? "Cancelled at"
                    : "Deadline"}
              </p>
              {editingDeadline ? (
                <div className="flex items-center gap-1">
                  {/* HRP-335: shared DatePicker (HRP-152). */}
                  <DatePicker
                    value={deadlineDraft}
                    min={todayLocalISO()}
                    onChange={setDeadlineDraft}
                    className="w-44"
                    inputClassName="h-8 text-sm"
                    disabled={saving}
                    data-testid="development-detail-deadline-input"
                  />
                  <Button
                    size="icon-xs"
                    variant="ghost"
                    onClick={saveDeadline}
                    disabled={saving || pdpDeadlineDraftIsPast}
                    data-testid="development-detail-deadline-save"
                    aria-label="Save deadline"
                  >
                    <Check className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    size="icon-xs"
                    variant="ghost"
                    onClick={() => setEditingDeadline(false)}
                    disabled={saving}
                    data-testid="development-detail-deadline-cancel"
                    aria-label="Cancel deadline edit"
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ) : (
                <div className="flex items-center gap-1">
                  <p
                    className={`font-medium${
                      pdp.deadline &&
                      !isTerminal &&
                      isPastDeadline(pdp.deadline.slice(0, 10))
                        ? " text-destructive"
                        : ""
                    }`}
                    data-testid="development-detail-deadline"
                  >
                    {/* HRP-132: ``finished_at`` is set on both ``done`` and
                        ``cancelled``; we just relabel it in the title above. */}
                    {(() => {
                      const terminalDate = isTerminal ? pdp.finished_at : null;
                      if (terminalDate) {
                        return formatDate(terminalDate);
                      }
                      return pdp.deadline
                        ? formatDate(pdp.deadline)
                        : "—";
                    })()}
                  </p>
                  {canManage && !isTerminal && (
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      onClick={startEditDeadline}
                      data-testid="development-detail-deadline-edit"
                      aria-label="Edit deadline"
                    >
                      <Pencil className="h-3 w-3" />
                    </Button>
                  )}
                </div>
              )}
            </div>
            <div>
              <p className="text-muted-foreground">Reviewer</p>
              <p className="font-medium" data-testid="development-detail-reviewer">
                {pdp.reviewer_name || "—"}
              </p>
            </div>
            <div>
              <p className="text-muted-foreground">Created</p>
              <p className="font-medium">{formatDate(pdp.created_at)}</p>
            </div>
          </div>
          {/* HRP-189: dev specialization + grade live below the top row,
              right under Progress; in Draft each value carries a pencil
              affordance that opens the Specialization & Grade dialog. */}
          <div className="mt-4 grid grid-cols-2 gap-4 text-sm md:grid-cols-3">
            <div>
              <p className="text-muted-foreground">Development specialization</p>
              <div className="flex items-center gap-1">
                <p
                  className="font-medium"
                  data-testid="development-detail-specialization"
                >
                  {pdp.specialization_title || "—"}
                </p>
                {canManage && !isPDPGradeLocked(pdp.status) && (
                  <Button
                    size="icon-xs"
                    variant="ghost"
                    onClick={openGradeChange}
                    disabled={saving}
                    data-testid="development-detail-specialization-edit"
                    aria-label="Edit specialization"
                  >
                    <Pencil className="h-3 w-3" />
                  </Button>
                )}
              </div>
            </div>
            <div>
              <p className="text-muted-foreground">Development grade</p>
              <div className="flex items-center gap-1">
                <p
                  className="font-medium"
                  data-testid="development-detail-grade"
                >
                  {pdp.grade_title || "—"}
                </p>
                {canManage && !isPDPGradeLocked(pdp.status) && (
                  <Button
                    size="icon-xs"
                    variant="ghost"
                    onClick={openGradeChange}
                    disabled={saving}
                    data-testid="development-detail-grade-edit"
                    aria-label="Edit grade"
                  >
                    <Pencil className="h-3 w-3" />
                  </Button>
                )}
              </div>
            </div>
          </div>
          {!isTerminal && nextStatuses.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-2" data-testid="development-detail-status-actions">
              {nextStatuses.map((s) => {
                const blocked =
                  (s === "sent" && sendBlockedReason !== null) ||
                  (s === "review" && reviewBlockedReason !== null) ||
                  (s === "returned" && returnFromReviewBlockedReason !== null);
                const blockedReason =
                  s === "sent"
                    ? sendBlockedReason
                    : s === "review"
                      ? reviewBlockedReason
                      : s === "returned"
                        ? returnFromReviewBlockedReason
                        : null;
                return (
                  <Button
                    key={s}
                    size="sm"
                    variant={s === "cancelled" ? "outline" : "default"}
                    onClick={() => changeStatus(s)}
                    disabled={saving || blocked}
                    title={blocked ? blockedReason ?? undefined : undefined}
                    data-testid={`development-detail-btn-status-${s}`}
                  >
                    {s === "cancelled" ? (
                      <X className="mr-1 h-4 w-4" />
                    ) : (
                      <Send className="mr-1 h-4 w-4" />
                    )}
                    {pdpStatusActionLabel(s)}
                  </Button>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Items */}
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">Items</CardTitle>
          {canManage && !isTerminal && (
            <Button size="sm" variant="outline" onClick={openAddItem} data-testid="development-detail-btn-add-goal">
              <Plus className="mr-1 h-4 w-4" />
              Add item
            </Button>
          )}
        </CardHeader>
        <CardContent data-testid="development-detail-goals-list">
          {pdp.items.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">No items</p>
          ) : (
            <div className="space-y-3">
              {pdp.items
                .slice()
                .sort((a, b) => a.sort_index - b.sort_index)
                .map((item, idx, sorted) => {
                  const canEditItems = canManage && !isTerminal;
                  // HRP-200: a passed item is read-only — the pencil /
                  // trash / "add material" controls disappear and the
                  // backend matches with a 403 on bypass attempts. The
                  // checkbox is the only affordance left, and clearing it
                  // (only possible in review) puts the item back in
                  // edit-mode.
                  const canEditThisItem = canEditItems && !item.is_passed;
                  // HRP-13/19/130: owner can toggle items freely in
                  // sent/in_progress/returned (HRP-19 REDO Case 4 —
                  // checkbox is a working state, not a one-way switch).
                  // Admin or the assigned PDP reviewer toggle in review
                  // (HRP-130). Everyone is locked out of draft/done/
                  // cancelled.
                  const ownerCanMark =
                    isOwner &&
                    ["sent", "in_progress", "returned"].includes(pdp.status);
                  const reviewerCanToggle =
                    pdp.status === "review" && (adminTier || isAssignedReviewer);
                  const checkboxesEnabled = ownerCanMark || reviewerCanToggle;
                  return (
                    <div key={item.id} className="rounded-lg border p-3">
                      <div className="flex items-start gap-3">
                        <div className="flex flex-col gap-0.5 pt-0.5">
                          <Button
                            size="icon-xs"
                            variant="ghost"
                            disabled={!canEditItems || idx === 0 || saving}
                            onClick={() => moveItem(idx, idx - 1, sorted)}
                            className="h-4 w-4"
                            data-testid={`development-detail-item-${item.id}-up`}
                          >
                            <ArrowUp className="h-3 w-3" />
                          </Button>
                          <Button
                            size="icon-xs"
                            variant="ghost"
                            disabled={!canEditItems || idx === sorted.length - 1 || saving}
                            onClick={() => moveItem(idx, idx + 1, sorted)}
                            className="h-4 w-4"
                            data-testid={`development-detail-item-${item.id}-down`}
                          >
                            <ArrowDown className="h-3 w-3" />
                          </Button>
                        </div>
                        <Checkbox
                          checked={item.is_passed}
                          onCheckedChange={(checked) => {
                            if (!checkboxesEnabled) return;
                            const next = checked === true;
                            if (next !== item.is_passed) {
                              toggleItemPassed(item.id, next);
                            }
                          }}
                          disabled={!checkboxesEnabled}
                          className="mt-0.5"
                          data-testid={`development-detail-item-${item.id}-checkbox`}
                        />
                        <div className="flex-1">
                          <p className={`text-sm font-medium ${item.is_passed ? "line-through text-muted-foreground" : ""}`}>
                            {item.title}
                          </p>
                          {item.description && (
                            <p className="mt-0.5 text-xs text-muted-foreground">{item.description}</p>
                          )}
                          {item.is_passed && (
                            <Badge variant="secondary" className={`mt-1 ${BADGE_COLOR.green}`}>
                              <Check className="mr-1 h-3 w-3" />
                              Passed
                            </Badge>
                          )}

                          {/* Materials */}
                          {item.materials.length > 0 && (
                            <div className="mt-2 space-y-1">
                              {item.materials.map((mat) => (
                                <div key={mat.id} className="flex items-center gap-2 text-xs">
                                  {mat.file_url ? (
                                    <Download className="h-3 w-3 text-muted-foreground" />
                                  ) : (
                                    <ExternalLink className="h-3 w-3 text-muted-foreground" />
                                  )}
                                  {mat.file_url ? (
                                    <a href={mat.file_url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                                      {mat.file_name || mat.title}
                                    </a>
                                  ) : mat.link ? (
                                    <a href={mat.link} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                                      {mat.title}
                                    </a>
                                  ) : (
                                    <span>{mat.title}</span>
                                  )}
                                  {mat.format && (
                                    <Badge variant="outline" className="text-[10px]">{mat.format}</Badge>
                                  )}
                                  {canEditThisItem && (
                                    <>
                                      <Button
                                        size="icon-xs"
                                        variant="ghost"
                                        className="h-5 w-5"
                                        onClick={() => openEditMaterial(item.id, mat)}
                                        data-testid={`development-detail-mat-${mat.id}-edit`}
                                        aria-label="Edit material"
                                      >
                                        <Pencil className="h-3 w-3" />
                                      </Button>
                                      <Button
                                        size="icon-xs"
                                        variant="ghost"
                                        className="h-5 w-5 text-destructive"
                                        onClick={() => deleteMaterial(item.id, mat.id)}
                                        data-testid={`development-detail-mat-${mat.id}-delete`}
                                        aria-label="Delete material"
                                      >
                                        <Trash2 className="h-3 w-3" />
                                      </Button>
                                    </>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                        {canEditThisItem && (
                          <div className="flex items-center gap-0.5">
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              onClick={() => openAddMaterial(item.id)}
                              aria-label="Add material"
                              data-testid={`development-detail-item-${item.id}-add-material`}
                            >
                              <Plus className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              onClick={() => openEditItem(item)}
                              aria-label="Edit item"
                              data-testid={`development-detail-item-${item.id}-edit`}
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              className="text-destructive"
                              onClick={() => deleteItem(item.id)}
                              aria-label="Delete item"
                              data-testid={`development-detail-item-${item.id}-delete`}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Comments */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Comments</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {pdp.comments.length > 0 && (
            <div className="space-y-2">
              {pdp.comments.map((c) => (
                <div key={c.id} className="rounded-md bg-muted/50 p-3">
                  <p className="text-sm">{c.text}</p>
                  {c.file_url && (
                    <a
                      href={c.file_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                    >
                      {c.file_name && /\.(png|jpe?g|gif|webp)$/i.test(c.file_name) ? (
                        // eslint-disable-next-line @next/next/no-img-element -- user-uploaded attachment
                        <img src={c.file_url} alt={c.file_name} className="mt-1 max-h-48 rounded-md" />
                      ) : (
                        <>
                          <FileText className="h-3 w-3" />
                          {c.file_name || "Attachment"}
                        </>
                      )}
                    </a>
                  )}
                  <p className="mt-1 text-xs text-muted-foreground">
                    {c.user_name && <span className="font-medium">{c.user_name} &middot; </span>}
                    {formatDateTime(c.created_at)}
                  </p>
                </div>
              ))}
            </div>
          )}
          {/* HRP-17: hide the composer on terminal plans — comments are
              read-only once the plan is done or cancelled. */}
          {!isTerminal && (
            <div className="space-y-2">
              {commentFile && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Paperclip className="h-3 w-3" />
                  <span>{commentFile.name}</span>
                  <button onClick={() => setCommentFile(null)} className="text-destructive hover:underline">Remove</button>
                </div>
              )}
              <div className="flex gap-2">
                <Textarea
                  placeholder="Add a comment..."
                  value={commentText}
                  onChange={(e) => setCommentText(e.target.value)}
                  rows={2}
                  className="flex-1"
                />
                <div className="flex flex-col gap-1">
                  <label className="inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-md hover:bg-muted transition-colors">
                    <Paperclip className="h-4 w-4 text-muted-foreground" />
                    <input type="file" className="hidden" onChange={handleCommentFileUpload} disabled={commentUploading} />
                  </label>
                  <Button size="sm" onClick={addComment} disabled={saving || (!commentText.trim() && !commentFile)}>
                    Send
                  </Button>
                </div>
              </div>
            </div>
          )}
          {isTerminal && pdp.comments.length === 0 && (
            <p className="py-4 text-center text-sm text-muted-foreground">No comments</p>
          )}
        </CardContent>
      </Card>

      {/* Progress Timeline */}
      {progressTimeline.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Progress Timeline</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={progressTimeline} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                  <defs>
                    <linearGradient id="progressGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={brandAccent} stopOpacity={0.3} />
                      <stop offset="95%" stopColor={brandAccent} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis
                    dataKey="version"
                    tickFormatter={(v: number) => `v${v}`}
                    tick={{ fontSize: 12 }}
                  />
                  <YAxis
                    domain={[0, 100]}
                    tickFormatter={(v: number) => `${v}%`}
                    tick={{ fontSize: 12 }}
                  />
                  <Tooltip
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const d = payload[0].payload as PDPProgressEntry;
                      return (
                        <div className="rounded-lg border bg-background p-3 text-sm shadow-sm">
                          <p className="font-medium">Version {d.version}</p>
                          <p className="text-muted-foreground">Status: {pdpStatusLabel(d.status)}</p>
                          <p className="text-muted-foreground">Progress: {d.progress}%</p>
                          <p className="text-muted-foreground">
                            Items: {d.passed_items}/{d.total_items} passed
                          </p>
                          {d.created_at && (
                            <p className="text-muted-foreground">
                              {formatDate(d.created_at)}
                            </p>
                          )}
                        </div>
                      );
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="progress"
                    stroke={brandAccent}
                    strokeWidth={2}
                    fill="url(#progressGradient)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Add/edit item dialog */}
      <Dialog open={itemOpen} onOpenChange={setItemOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingItemId ? "Edit item" : "Add item"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Title</Label>
              <Input
                value={itemForm.title}
                onChange={(e) => setItemForm({ ...itemForm, title: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Description</Label>
              <Textarea
                value={itemForm.description}
                onChange={(e) => setItemForm({ ...itemForm, description: e.target.value })}
                rows={2}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setItemOpen(false)} disabled={saving}>Cancel</Button>
            <Button onClick={saveItem} disabled={saving || !itemForm.title.trim()}>
              {saving ? "Saving..." : editingItemId ? "Save" : "Add"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* HRP-189: dialog title + warning copy match the Jira spec. */}
      <Dialog open={gradeChangeOpen} onOpenChange={setGradeChangeOpen}>
        <DialogContent data-testid="development-detail-grade-dialog">
          <DialogHeader>
            <DialogTitle>Development specialization & grade</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <p
              className={`rounded-md p-3 text-xs ${ALERT_TONE.amber}`}
              data-testid="development-detail-grade-warning"
            >
              All items will be replaced with the new specialization & grade set.
            </p>
            <div className="space-y-2">
              <Label>Development specialization</Label>
              <Select
                value={specDraft}
                onValueChange={(val) => handleSpecDraftChange(val ?? "")}
              >
                <SelectTrigger
                  className="w-full"
                  data-testid="development-detail-grade-spec-select"
                >
                  <SelectValue placeholder="No specialization">
                    {specializations.find((s) => s.id === specDraft)?.title}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {specOptions.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Development grade</Label>
              {/* HRP-293: disabled until a specialization is chosen;
                  options are the specialization's configured grades. */}
              <Select
                value={gradeDraft}
                onValueChange={(val) => setGradeDraft(val ?? "")}
                disabled={!specDraft}
              >
                <SelectTrigger
                  className="w-full"
                  data-testid="development-detail-grade-grade-select"
                >
                  <SelectValue
                    placeholder={
                      specDraft ? "No grade" : "Select specialization first"
                    }
                  >
                    {specGrades.find((g) => g.id === gradeDraft)?.title}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {specGrades.map((g) => (
                    <SelectItem key={g.id} value={g.id}>
                      {g.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setGradeChangeOpen(false)}
              disabled={saving}
              data-testid="development-detail-grade-cancel"
            >
              Cancel
            </Button>
            <Button
              onClick={saveGradeChange}
              disabled={saving}
              data-testid="development-detail-grade-save"
            >
              {saving ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add/edit material dialog */}
      <Dialog open={matOpen} onOpenChange={handleMatOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingMaterialId ? "Edit material" : "Add material"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Title</Label>
              <Input
                value={matForm.title}
                onChange={(e) => setMatForm({ ...matForm, title: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Format</Label>
              <Select
                value={matForm.format}
                onValueChange={(val) => setMatForm({ ...matForm, format: val ?? "" })}
              >
                <SelectTrigger className="w-full" data-testid="development-detail-mat-format">
                  <SelectValue placeholder="Select format">
                    {matForm.format || undefined}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {["course", "book", "article", "video", "practice"].map((f) => (
                    <SelectItem key={f} value={f}>{f}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Link</Label>
              <Input
                placeholder="https://..."
                value={matForm.link}
                onChange={(e) => setMatForm({ ...matForm, link: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Or upload file</Label>
              {matFile ? (
                <div className="flex items-center gap-2 text-sm">
                  <Paperclip className="h-4 w-4 text-muted-foreground" />
                  <span data-testid="development-detail-mat-file-name">{matFile.name}</span>
                  <button onClick={() => setMatFile(null)} className="text-xs text-destructive hover:underline">Remove</button>
                </div>
              ) : (
                <label
                  className={`inline-flex h-9 w-full cursor-pointer items-center rounded-md border border-input bg-background px-3 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground ${matUploading ? "opacity-50 pointer-events-none" : ""}`}
                  data-testid="development-detail-mat-file-upload"
                >
                  <Paperclip className="mr-2 h-4 w-4" />
                  <span>{matUploading ? "Uploading..." : "Choose file..."}</span>
                  <input
                    type="file"
                    className="hidden"
                    onChange={handleMatFileUpload}
                    disabled={matUploading}
                  />
                </label>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => handleMatOpenChange(false)} disabled={saving}>Cancel</Button>
            <Button
              onClick={saveMaterial}
              disabled={
                saving ||
                matUploading ||
                !matForm.title.trim() ||
                (!matFile && !matForm.link.trim())
              }
              data-testid="development-detail-mat-save"
            >
              {saving ? "Saving..." : editingMaterialId ? "Save" : "Add"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
