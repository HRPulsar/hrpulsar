"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { EmployeeSummaryLine } from "@/components/employee/employee-summary-line";
import { api } from "@/lib/api";
import type {
  DictionaryItem,
  Division,
  Employee,
  EmployeeList,
  ExamResult,
  MassExamDetail,
  PositionList,
} from "@/lib/types";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";
import {
  ArrowLeft,
  CheckCircle2,
  ImagePlus,
  Pencil,
  Plus,
  Send,
  Trash2,
  XCircle,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import { formatDate } from "@/lib/date-format";
import { isPastDeadline, todayLocalISO } from "@/lib/deadline";
import {
  STATUS_CHIP_COLOR,
  STATUS_LABELS,
  statusLabel,
} from "../status";

const questionTypes = [
  { value: "single_choice", label: "Single choice" },
  { value: "multiple_choice", label: "Multiple choice" },
  { value: "essay", label: "Essay" },
];

const questionTypeLabel = (code: string) =>
  questionTypes.find((t) => t.value === code)?.label ?? code;

interface OptionForm {
  title: string;
  is_correct: boolean;
}

export default function ExamDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [exam, setExam] = useState<MassExamDetail | null>(null);
  const [results, setResults] = useState<ExamResult[]>([]);
  const [loading, setLoading] = useState(true);

  // Add question
  const [qOpen, setQOpen] = useState(false);
  const [qForm, setQForm] = useState({
    title: "",
    description: "",
    question_type: "single_choice",
    weight: 1,
  });
  const [options, setOptions] = useState<OptionForm[]>([
    { title: "", is_correct: false },
    { title: "", is_correct: false },
  ]);

  // Question image
  const [qImage, setQImage] = useState<{ id: string; name: string; url: string } | null>(null);
  const [qImageUploading, setQImageUploading] = useState(false);

  // Pass mark (HRP-226 redo: one dialog for add + edit)
  const [pmOpen, setPmOpen] = useState(false);
  const [pmEditingId, setPmEditingId] = useState<string | null>(null);
  const [pmForm, setPmForm] = useState({ min_score_percent: "", min_score_points: "" });

  // Assign employees
  const [assignOpen, setAssignOpen] = useState(false);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [employeesLoading, setEmployeesLoading] = useState(false);
  const [employeeFilter, setEmployeeFilter] = useState("");
  const [selectedEmployeeIds, setSelectedEmployeeIds] = useState<Set<string>>(new Set());
  // HRP-225 REDO: division / position / specialization filters + select-all,
  // mirroring the Mass assessment "Select employees" step.
  const [divisions, setDivisions] = useState<Division[]>([]);
  const [positions, setPositions] = useState<{ id: string; title: string }[]>([]);
  const [specializations, setSpecializations] = useState<DictionaryItem[]>([]);
  const [filterDivision, setFilterDivision] = useState("");
  const [filterPosition, setFilterPosition] = useState("");
  const [filterSpecialization, setFilterSpecialization] = useState("");

  // Deadline edit
  const [deadlineOpen, setDeadlineOpen] = useState(false);
  const [deadlineDraft, setDeadlineDraft] = useState("");

  // HRP-231: title / description inline edit (pencil icons on /exams/[uuid]).
  const [titleOpen, setTitleOpen] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [descOpen, setDescOpen] = useState(false);
  const [descDraft, setDescDraft] = useState("");

  // HRP-228: edit / delete question. Edit re-uses the add-question form via a
  // dedicated draft slot so the create flow stays untouched.
  const [qEditId, setQEditId] = useState<string | null>(null);
  const [qEditForm, setQEditForm] = useState({
    title: "",
    description: "",
    question_type: "single_choice",
    weight: 1,
  });
  const [qEditOptions, setQEditOptions] = useState<OptionForm[]>([]);
  const [qEditImage, setQEditImage] = useState<{ id: string; name: string; url: string } | null>(null);
  const [qEditImageUploading, setQEditImageUploading] = useState(false);
  const [qDeleteId, setQDeleteId] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const [detail, resultsData] = await Promise.all([
        api.get<MassExamDetail>(`/mass-exams/${id}`),
        api.get<ExamResult[]>(`/mass-exams/${id}/results`),
      ]);
      setExam(detail);
      setResults(resultsData);
    } catch {
      toast.error("Failed to load exam");
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
      await api.post(`/mass-exams/${id}/status`, { status_code: status });
      toast.success(`Status changed to ${STATUS_LABELS[status] ?? status}`);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleQuestionImageUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      toast.error("Please select an image file");
      return;
    }
    setQImageUploading(true);
    try {
      const res = await api.upload<{ id: string; original_name: string; url: string }>("/files/upload", file);
      setQImage({ id: res.id, name: res.original_name, url: res.url || "" });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to upload image");
    } finally {
      setQImageUploading(false);
      e.target.value = "";
    }
  }

  const trimmedOptions = options.filter((o) => o.title.trim());
  const correctOptionCount = trimmedOptions.filter((o) => o.is_correct).length;
  const isEssay = qForm.question_type === "essay";
  const questionFormValid =
    qForm.title.trim().length > 0 &&
    (isEssay
      ? true
      : trimmedOptions.length >= 2 &&
        correctOptionCount >= 1 &&
        (qForm.question_type === "single_choice" ? correctOptionCount === 1 : true));

  async function addQuestion() {
    if (!questionFormValid) return;
    setSaving(true);
    try {
      await api.post(`/mass-exams/${id}/questions`, {
        ...qForm,
        title: qForm.title.trim(),
        description: qForm.description.trim() || null,
        sort_index: exam ? exam.questions.length : 0,
        image_file_id: qImage?.id || null,
        options: isEssay
          ? []
          : trimmedOptions.map((o, i) => ({
              title: o.title.trim(),
              is_correct: o.is_correct,
              sort_index: i,
            })),
      });
      toast.success("Question added");
      setQOpen(false);
      setQForm({ title: "", description: "", question_type: "single_choice", weight: 1 });
      setOptions([{ title: "", is_correct: false }, { title: "", is_correct: false }]);
      setQImage(null);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  function openPassMarkAdd() {
    setPmEditingId(null);
    setPmForm({ min_score_percent: "", min_score_points: "" });
    setPmOpen(true);
  }

  function openPassMarkEdit(pm: MassExamDetail["pass_marks"][number]) {
    setPmEditingId(pm.id);
    setPmForm({
      min_score_percent: pm.min_score_percent != null ? String(pm.min_score_percent) : "",
      min_score_points: pm.min_score_points != null ? String(pm.min_score_points) : "",
    });
    setPmOpen(true);
  }

  async function savePassMark() {
    setSaving(true);
    try {
      const payload = {
        min_score_percent: pmForm.min_score_percent ? Number(pmForm.min_score_percent) : null,
        min_score_points: pmForm.min_score_points ? Number(pmForm.min_score_points) : null,
      };
      if (pmEditingId) {
        await api.patch(`/mass-exams/${id}/pass-marks/${pmEditingId}`, payload);
        toast.success("Pass mark updated");
      } else {
        await api.post(`/mass-exams/${id}/pass-marks`, payload);
        toast.success("Pass mark added");
      }
      setPmOpen(false);
      setPmEditingId(null);
      setPmForm({ min_score_percent: "", min_score_points: "" });
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  async function deletePassMark(passMarkId: string) {
    setSaving(true);
    try {
      await api.delete(`/mass-exams/${id}/pass-marks/${passMarkId}`);
      toast.success("Pass mark removed");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  function openAssignDialog() {
    setAssignOpen(true);
    setSelectedEmployeeIds(new Set());
    setEmployeeFilter("");
    setFilterDivision("");
    setFilterPosition("");
    setFilterSpecialization("");
    if (
      divisions.length === 0 &&
      positions.length === 0 &&
      specializations.length === 0
    ) {
      void Promise.all([
        api.get<Division[]>("/divisions").catch(() => []),
        api
          .get<PositionList>("/positions?limit=500&is_active=true")
          .then((r) => r.items.map((p) => ({ id: p.id, title: p.title })))
          .catch(() => []),
        api.get<DictionaryItem[]>("/dictionaries/specialization").catch(() => []),
      ]).then(([divs, pos, specs]) => {
        setDivisions(divs);
        setPositions(pos);
        setSpecializations(specs);
      });
    }
  }

  // Monotonic sequence: filter changes can race, only the latest response
  // may land — a stale list under fresh filters would feed select-all the
  // wrong cohort.
  const assignReqSeq = useRef(0);

  const loadAssignEmployees = useCallback(async () => {
    const seq = ++assignReqSeq.current;
    setEmployeesLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("status", "active");
      params.set("limit", "500");
      if (filterDivision) params.set("division_id", filterDivision);
      if (filterPosition) params.set("position_id", filterPosition);
      if (filterSpecialization)
        params.set("specialization_id", filterSpecialization);
      const data = await api.get<EmployeeList>(`/employees?${params}`);
      if (seq !== assignReqSeq.current) return;
      setEmployees(data.items);
    } catch (err) {
      if (seq !== assignReqSeq.current) return;
      toast.error(err instanceof Error ? err.message : "Failed to load employees");
    } finally {
      if (seq === assignReqSeq.current) setEmployeesLoading(false);
    }
  }, [filterDivision, filterPosition, filterSpecialization]);

  useEffect(() => {
    if (assignOpen) void loadAssignEmployees();
  }, [assignOpen, loadAssignEmployees]);

  function toggleEmployee(empId: string) {
    setSelectedEmployeeIds((prev) => {
      const next = new Set(prev);
      if (next.has(empId)) next.delete(empId);
      else next.add(empId);
      return next;
    });
  }

  const filteredEmployees = useMemo(() => {
    const q = employeeFilter.trim().toLowerCase();
    if (!q) return employees;
    return employees.filter((e) =>
      [e.user_name, e.user_email, e.division_name, e.position_title]
        .filter(Boolean)
        .some((v) => (v ?? "").toLowerCase().includes(q)),
    );
  }, [employees, employeeFilter]);

  const alreadyAssigned = useMemo(
    () => new Set(results.map((r) => r.employee_id)),
    [results],
  );

  // HRP-225 REDO: select-all covers what the user currently sees (server
  // filters + text search) minus rows that are already assigned.
  const selectableEmployees = useMemo(
    () => filteredEmployees.filter((e) => !alreadyAssigned.has(e.id)),
    [filteredEmployees, alreadyAssigned],
  );

  const allSelectableSelected =
    selectableEmployees.length > 0 &&
    selectableEmployees.every((e) => selectedEmployeeIds.has(e.id));

  function toggleAllSelectable() {
    setSelectedEmployeeIds((prev) => {
      const next = new Set(prev);
      if (allSelectableSelected) {
        selectableEmployees.forEach((e) => next.delete(e.id));
      } else {
        selectableEmployees.forEach((e) => next.add(e.id));
      }
      return next;
    });
  }

  // Flatten division tree for the filter dropdown
  const flatDivisions = useMemo(() => {
    function flatten(
      divs: Division[],
      depth = 0,
    ): { id: string; name: string; depth: number }[] {
      const out: { id: string; name: string; depth: number }[] = [];
      for (const d of divs) {
        out.push({ id: d.id, name: d.name, depth });
        if (d.children?.length) out.push(...flatten(d.children, depth + 1));
      }
      return out;
    }
    return flatten(divisions);
  }, [divisions]);

  async function assignEmployees() {
    const ids = Array.from(selectedEmployeeIds);
    if (ids.length === 0) {
      toast.error("Select at least one employee");
      return;
    }
    setSaving(true);
    try {
      await api.post(`/mass-exams/${id}/employees`, ids);
      toast.success("Employees assigned");
      setAssignOpen(false);
      setSelectedEmployeeIds(new Set());
      setEmployeeFilter("");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  function addOption() {
    setOptions([...options, { title: "", is_correct: false }]);
  }

  function removeOption(idx: number) {
    setOptions(options.filter((_, i) => i !== idx));
  }

  function updateOption(idx: number, patch: Partial<OptionForm>) {
    // HRP-229 #3: single_choice has radio semantics — picking one option
    // un-picks any others.
    if (patch.is_correct === true && qForm.question_type === "single_choice") {
      setOptions(
        options.map((o, i) => ({
          ...o,
          ...(i === idx ? patch : { is_correct: false }),
        })),
      );
      return;
    }
    setOptions(options.map((o, i) => (i === idx ? { ...o, ...patch } : o)));
  }

  function openTitleEditor() {
    setTitleDraft(exam?.title ?? "");
    setTitleOpen(true);
  }

  async function saveTitle() {
    const trimmed = titleDraft.trim();
    if (!trimmed) {
      toast.error("Title is required");
      return;
    }
    setSaving(true);
    try {
      await api.patch(`/mass-exams/${id}`, { title: trimmed });
      toast.success("Title updated");
      setTitleOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  function openDescriptionEditor() {
    setDescDraft(exam?.description ?? "");
    setDescOpen(true);
  }

  async function saveDescription() {
    setSaving(true);
    try {
      await api.patch(`/mass-exams/${id}`, {
        description: descDraft.trim() || null,
      });
      toast.success("Description updated");
      setDescOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  function openQuestionEditor(q: MassExamDetail["questions"][number]) {
    setQEditId(q.id);
    setQEditForm({
      title: q.title,
      description: q.description ?? "",
      question_type: q.question_type,
      weight: q.weight,
    });
    setQEditOptions(
      q.options.length > 0
        ? q.options.map((o) => ({ title: o.title, is_correct: o.is_correct }))
        : [
            { title: "", is_correct: false },
            { title: "", is_correct: false },
          ],
    );
    setQEditImage(
      q.image_file_id && q.image_url
        ? { id: q.image_file_id, name: "", url: q.image_url }
        : null,
    );
  }

  function closeQuestionEditor() {
    setQEditId(null);
  }

  async function handleQuestionEditImageUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      toast.error("Please select an image file");
      return;
    }
    setQEditImageUploading(true);
    try {
      const res = await api.upload<{ id: string; original_name: string; url: string }>("/files/upload", file);
      setQEditImage({ id: res.id, name: res.original_name, url: res.url || "" });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to upload image");
    } finally {
      setQEditImageUploading(false);
      e.target.value = "";
    }
  }

  const qEditTrimmedOptions = qEditOptions.filter((o) => o.title.trim());
  const qEditCorrectCount = qEditTrimmedOptions.filter((o) => o.is_correct).length;
  const qEditIsEssay = qEditForm.question_type === "essay";
  const qEditValid =
    qEditForm.title.trim().length > 0 &&
    (qEditIsEssay
      ? true
      : qEditTrimmedOptions.length >= 2 &&
        qEditCorrectCount >= 1 &&
        (qEditForm.question_type === "single_choice" ? qEditCorrectCount === 1 : true));

  function updateEditOption(idx: number, patch: Partial<OptionForm>) {
    if (patch.is_correct === true && qEditForm.question_type === "single_choice") {
      setQEditOptions(
        qEditOptions.map((o, i) => ({
          ...o,
          ...(i === idx ? patch : { is_correct: false }),
        })),
      );
      return;
    }
    setQEditOptions(qEditOptions.map((o, i) => (i === idx ? { ...o, ...patch } : o)));
  }

  function addEditOption() {
    setQEditOptions([...qEditOptions, { title: "", is_correct: false }]);
  }

  function removeEditOption(idx: number) {
    setQEditOptions(qEditOptions.filter((_, i) => i !== idx));
  }

  async function saveQuestionEdit() {
    if (!qEditId || !qEditValid) return;
    setSaving(true);
    try {
      await api.patch(`/mass-exams/${id}/questions/${qEditId}`, {
        title: qEditForm.title.trim(),
        description: qEditForm.description.trim() || null,
        question_type: qEditForm.question_type,
        weight: qEditForm.weight,
        image_file_id: qEditImage?.id || null,
        options: qEditIsEssay
          ? []
          : qEditTrimmedOptions.map((o, i) => ({
              title: o.title.trim(),
              is_correct: o.is_correct,
              sort_index: i,
            })),
      });
      toast.success("Question updated");
      closeQuestionEditor();
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  async function confirmDeleteQuestion() {
    if (!qDeleteId) return;
    setSaving(true);
    try {
      await api.delete(`/mass-exams/${id}/questions/${qDeleteId}`);
      toast.success("Question removed");
      setQDeleteId(null);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  function openDeadlineEditor() {
    setDeadlineDraft(exam?.ended_at ? exam.ended_at.slice(0, 10) : "");
    setDeadlineOpen(true);
  }

  async function saveDeadline() {
    if (deadlineDraft && isPastDeadline(deadlineDraft)) {
      toast.error("Deadline cannot be in the past");
      return;
    }
    setSaving(true);
    try {
      await api.patch(`/mass-exams/${id}`, {
        ended_at: deadlineDraft ? new Date(deadlineDraft).toISOString() : null,
      });
      toast.success("Deadline updated");
      setDeadlineOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center py-12 text-muted-foreground">Loading...</div>;
  }

  if (!exam) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" render={<Link href="/exams" />}>
          <ArrowLeft className="mr-1 h-4 w-4" />
          Back to exams
        </Button>
        <div className="py-12 text-center text-muted-foreground">Exam not found</div>
      </div>
    );
  }

  const deadlineInPast = exam.ended_at ? isPastDeadline(exam.ended_at) : false;
  const hasPassMark = exam.pass_marks.length > 0;
  const isTerminal = exam.status === "done" || exam.status === "cancelled";
  const canEditMeta = !isTerminal;
  const canEditQuestions = exam.status === "draft";

  // HRP-236 task 3: per-status action buttons in Details.
  const actionButtons: { code: string; label: string; disabled?: boolean; hint?: string }[] = [];
  if (exam.status === "draft") {
    const missing: string[] = [];
    if (exam.questions.length === 0) missing.push("add a question");
    if (exam.assigned_count === 0) missing.push("assign an employee");
    // HRP-237 redo: a past deadline does NOT disable Send — same as
    // Assessments / Development plans, the click surfaces the backend
    // "Deadline in the past" error while the date itself renders red.
    actionButtons.push({
      code: "sent",
      label: "send",
      disabled: missing.length > 0,
      hint: missing.length > 0 ? `To send: ${missing.join(", ")}` : undefined,
    });
    actionButtons.push({ code: "cancelled", label: "cancel" });
  } else if (exam.status === "sent") {
    actionButtons.push({ code: "cancelled", label: "cancel" });
  } else if (exam.status === "in_progress") {
    actionButtons.push({ code: "done", label: "complete" });
    actionButtons.push({ code: "cancelled", label: "cancel" });
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon-sm" render={<Link href="/exams" />}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          {/* HRP-231: pencil next to Title — editable until terminal. */}
          <h1 className="flex items-center gap-1.5 text-2xl font-semibold tracking-tight">
            <span data-testid="exam-title">{exam.title}</span>
            {canEditMeta && (
              <button
                type="button"
                onClick={openTitleEditor}
                className="text-muted-foreground hover:text-foreground"
                aria-label="Edit title"
                data-testid="exam-title-edit"
              >
                <Pencil className="h-4 w-4" />
              </button>
            )}
          </h1>
          {/* HRP-231: pencil next to Description; placeholder text when empty. */}
          <p className="mt-0.5 flex items-center gap-1.5 text-sm text-muted-foreground">
            {exam.description ? (
              <span data-testid="exam-description">{exam.description}</span>
            ) : (
              canEditMeta && (
                <span className="italic" data-testid="exam-description-empty">
                  No description yet
                </span>
              )
            )}
            {canEditMeta && (
              <button
                type="button"
                onClick={openDescriptionEditor}
                className="text-muted-foreground hover:text-foreground"
                aria-label="Edit description"
                data-testid="exam-description-edit"
              >
                <Pencil className="h-3 w-3" />
              </button>
            )}
          </p>
        </div>
        <Badge variant="secondary" className={STATUS_CHIP_COLOR[exam.status] || ""}>
          {statusLabel(exam.status)}
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
              <Badge variant="secondary" className={STATUS_CHIP_COLOR[exam.status] || ""}>
                {statusLabel(exam.status)}
              </Badge>
            </div>
            <div>
              <p className="text-muted-foreground">Questions</p>
              <p className="font-medium">{exam.questions.length}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Assigned</p>
              <p className="font-medium">{exam.assigned_count}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Created</p>
              <p className="font-medium">{formatDate(exam.created_at)}</p>
            </div>
            {/* HRP-233 task 2: terminal exams show Completed / Cancelled +
                its date in place of Deadline (the deadline is no longer
                actionable). Active exams keep the pencil-edit affordance. */}
            <div>
              {exam.status === "done" ? (
                <>
                  <p className="text-muted-foreground">Completed</p>
                  <p className="font-medium" data-testid="exam-finished-at">
                    {exam.finished_at ? formatDate(exam.finished_at) : "—"}
                  </p>
                </>
              ) : exam.status === "cancelled" ? (
                <>
                  <p className="text-muted-foreground">Cancelled</p>
                  <p className="font-medium" data-testid="exam-finished-at">
                    {exam.finished_at ? formatDate(exam.finished_at) : "—"}
                  </p>
                </>
              ) : (
                <>
                  <p className="text-muted-foreground">Deadline</p>
                  <p className="flex items-center gap-1.5 font-medium">
                    {exam.ended_at ? (
                      <span
                        className={deadlineInPast ? "text-destructive" : undefined}
                        data-testid="exam-deadline"
                      >
                        {formatDate(exam.ended_at)}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                    <button
                      type="button"
                      onClick={openDeadlineEditor}
                      className="text-muted-foreground hover:text-foreground"
                      aria-label="Edit deadline"
                      data-testid="exam-deadline-edit"
                    >
                      <Pencil className="h-3 w-3" />
                    </button>
                  </p>
                </>
              )}
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {actionButtons.map((btn) => (
              <Button
                key={btn.code}
                size="sm"
                variant="outline"
                onClick={() => changeStatus(btn.code)}
                disabled={saving || btn.disabled}
                title={btn.hint}
                data-testid={`exam-btn-${btn.label}`}
              >
                {btn.code === "sent" && <Send className="mr-1 h-4 w-4" />}
                {btn.label}
              </Button>
            ))}
            {exam.status === "draft" && (
              <Button size="sm" variant="outline" onClick={openAssignDialog}>
                Assign employees
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Questions */}
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">Questions</CardTitle>
          {exam.status === "draft" && (
            <Button size="sm" variant="outline" onClick={() => setQOpen(true)}>
              <Plus className="mr-1 h-4 w-4" />
              Add question
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {exam.questions.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">No questions yet</p>
          ) : (
            <div className="space-y-3">
              {exam.questions
                .sort((a, b) => a.sort_index - b.sort_index)
                .map((q, idx) => (
                  <div
                    key={q.id}
                    className="rounded-lg border p-3"
                    data-testid={`exam-question-${q.id}`}
                  >
                    <div className="flex items-start gap-3">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium">
                        {idx + 1}
                      </span>
                      <div className="flex-1">
                        <div className="prose prose-sm max-w-none text-sm font-medium">
                          <ReactMarkdown>{q.title}</ReactMarkdown>
                        </div>
                        {q.description && (
                          <div className="prose prose-sm max-w-none mt-0.5 text-xs text-muted-foreground">
                            <ReactMarkdown>{q.description}</ReactMarkdown>
                          </div>
                        )}
                        {q.image_url && (
                          // eslint-disable-next-line @next/next/no-img-element -- dynamic user-uploaded image
                          <img src={q.image_url} alt="Question image" className="mt-2 max-h-48 rounded-md border" />
                        )}
                        <div className="mt-1 flex gap-1">
                          <Badge variant="outline" className="text-[10px]">{questionTypeLabel(q.question_type)}</Badge>
                          <Badge variant="outline" className="text-[10px]">weight: {q.weight}</Badge>
                        </div>
                        {q.options.length > 0 && (
                          <div className="mt-2 space-y-1">
                            {q.options.map((opt) => (
                              <div key={opt.id} className="flex items-center gap-2 text-xs">
                                <div className={`h-3 w-3 rounded-full border ${opt.is_correct ? "bg-green-500 border-green-500" : "border-muted-foreground"}`} />
                                <span className={opt.is_correct ? "font-medium text-green-700" : ""}>{opt.title}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                      {/* HRP-228: per-question edit / delete (draft only). */}
                      {canEditQuestions && (
                        <div className="flex items-center gap-1">
                          <Button
                            size="icon-xs"
                            variant="ghost"
                            onClick={() => openQuestionEditor(q)}
                            aria-label="Edit question"
                            data-testid={`exam-question-${q.id}-edit`}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            size="icon-xs"
                            variant="ghost"
                            onClick={() => setQDeleteId(q.id)}
                            aria-label="Delete question"
                            data-testid={`exam-question-${q.id}-delete`}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Pass mark (HRP-226: at most one) */}
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">Pass Mark</CardTitle>
          {/* HRP-226 redo: pass mark editable on any non-terminal exam. */}
          {!hasPassMark && !isTerminal && (
            <Button size="sm" variant="outline" onClick={openPassMarkAdd} data-testid="exam-passmark-add">
              <Plus className="mr-1 h-4 w-4" />
              Add
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {!hasPassMark ? (
            <p className="py-4 text-center text-sm text-muted-foreground">No pass mark configured (default: 60%)</p>
          ) : (
            <div className="space-y-2">
              {exam.pass_marks.map((pm) => (
                <div
                  key={pm.id}
                  className="flex items-center justify-between gap-4 rounded-md border p-3 text-sm"
                  data-testid="exam-passmark-row"
                >
                  <div className="flex items-center gap-4">
                    {pm.min_score_percent != null && (
                      <span>Min score: <span className="font-medium">{pm.min_score_percent}%</span></span>
                    )}
                    {pm.min_score_points != null && (
                      <span>Min points: <span className="font-medium">{pm.min_score_points}</span></span>
                    )}
                    {pm.grade_id && (
                      <Badge variant="outline" className="text-xs">grade: {pm.grade_id.slice(0, 8)}</Badge>
                    )}
                  </div>
                  {!isTerminal && (
                    <div className="flex items-center gap-1">
                      <Button
                        size="icon-xs"
                        variant="ghost"
                        onClick={() => openPassMarkEdit(pm)}
                        aria-label="Edit pass mark"
                        data-testid="exam-passmark-edit"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="icon-xs"
                        variant="ghost"
                        onClick={() => deletePassMark(pm.id)}
                        aria-label="Remove pass mark"
                        data-testid="exam-passmark-delete"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Results */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Results</CardTitle>
        </CardHeader>
        <CardContent>
          {results.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">No results yet</p>
          ) : (
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Employee</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Score</TableHead>
                    <TableHead>Result</TableHead>
                    <TableHead>Finished</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {results.map((r) => {
                    const display = r.employee_name ?? "Unknown";
                    return (
                      <TableRow key={r.id}>
                        <TableCell className="text-sm">
                          <div className="flex flex-col gap-0.5">
                            {r.can_view_profile ? (
                              <Link
                                href={`/employees/${r.employee_id}`}
                                className="hover:underline"
                              >
                                {display}
                              </Link>
                            ) : (
                              <span>{display}</span>
                            )}
                            {/* HRP-333: position + non-active status chip
                                under the name (shared EmployeeSummaryLine). */}
                            <EmployeeSummaryLine
                              employee={{
                                user_name: r.employee_name,
                                position_title: r.position_title,
                                status: r.employee_status,
                              }}
                              hideName
                              data-testid={`exam-result-${r.id}-summary`}
                            />
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="secondary"
                            className={STATUS_CHIP_COLOR[r.status] ?? "bg-muted text-muted-foreground"}
                          >
                            {statusLabel(r.status)}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {r.score != null && r.max_score != null ? (
                            <span className="font-medium">{r.score}/{r.max_score} ({Math.round(r.score / r.max_score * 100)}%)</span>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell>
                          {r.passed === true && (
                            <span className="inline-flex items-center gap-1 text-sm text-green-700">
                              <CheckCircle2 className="h-4 w-4" /> Passed
                            </span>
                          )}
                          {r.passed === false && (
                            <span className="inline-flex items-center gap-1 text-sm text-red-600">
                              <XCircle className="h-4 w-4" /> Failed
                            </span>
                          )}
                          {r.passed == null && <span className="text-muted-foreground">—</span>}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {r.finished_at ? formatDate(r.finished_at) : "—"}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Add question dialog */}
      <Dialog open={qOpen} onOpenChange={setQOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Add question</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>
                Question <span className="text-destructive">*</span>
              </Label>
              <Textarea
                value={qForm.title}
                onChange={(e) => setQForm({ ...qForm, title: e.target.value })}
                rows={2}
              />
            </div>
            <div className="space-y-2">
              <Label>Description (optional)</Label>
              <Input
                value={qForm.description}
                onChange={(e) => setQForm({ ...qForm, description: e.target.value })}
              />
            </div>
            <div className="flex gap-4">
              <div className="flex-1 space-y-2">
                <Label>Type</Label>
                <Select value={qForm.question_type} onValueChange={(val) => setQForm({ ...qForm, question_type: val })}>
                  <SelectTrigger className="w-full">
                    <SelectValue>{questionTypeLabel(qForm.question_type)}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {questionTypes.map((t) => (
                      <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="w-24 space-y-2">
                <Label>Weight</Label>
                <Input
                  type="number"
                  min={1}
                  value={qForm.weight}
                  onChange={(e) => setQForm({ ...qForm, weight: Number(e.target.value) })}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>Image (optional)</Label>
              {qImage ? (
                <div className="space-y-2">
                  {/* eslint-disable-next-line @next/next/no-img-element -- preview of user-uploaded image */}
                  <img src={qImage.url} alt={qImage.name} className="max-h-32 rounded-md border" />
                  <button onClick={() => setQImage(null)} className="text-xs text-destructive hover:underline">Remove image</button>
                </div>
              ) : (
                <div>
                  <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border px-3 py-1.5 text-sm hover:bg-muted transition-colors">
                    <ImagePlus className="h-4 w-4" />
                    {qImageUploading ? "Uploading..." : "Add image"}
                    <input type="file" accept="image/*" className="hidden" onChange={handleQuestionImageUpload} disabled={qImageUploading} />
                  </label>
                </div>
              )}
            </div>
            {!isEssay && (
              <div className="space-y-2">
                <Label>
                  Options <span className="text-destructive">*</span>
                </Label>
                <p className="text-xs text-muted-foreground">
                  At least 2 options, at least 1 marked correct
                  {qForm.question_type === "single_choice" ? " (exactly one)" : ""}
                </p>
                <div className="space-y-2">
                  {options.map((opt, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <Checkbox
                        checked={opt.is_correct}
                        onCheckedChange={() => updateOption(i, { is_correct: !opt.is_correct })}
                      />
                      <Input
                        className="flex-1"
                        placeholder={`Option ${i + 1}`}
                        value={opt.title}
                        onChange={(e) => updateOption(i, { title: e.target.value })}
                      />
                      {options.length > 2 && (
                        <Button size="icon-xs" variant="ghost" onClick={() => removeOption(i)}>
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      )}
                    </div>
                  ))}
                  <Button size="sm" variant="ghost" onClick={addOption}>
                    <Plus className="mr-1 h-3 w-3" />
                    Add option
                  </Button>
                </div>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setQOpen(false)} disabled={saving}>Cancel</Button>
            <Button onClick={addQuestion} disabled={saving || !questionFormValid}>
              {saving ? "Adding..." : "Add question"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Assign employees dialog */}
      <Dialog open={assignOpen} onOpenChange={setAssignOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Select employees</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              placeholder="Search by name, email, division..."
              value={employeeFilter}
              onChange={(e) => setEmployeeFilter(e.target.value)}
            />
            {/* HRP-225 REDO: division / position / specialization filters */}
            <div className="grid grid-cols-3 gap-2">
              <Select value={filterDivision} onValueChange={setFilterDivision}>
                <SelectTrigger className="w-full" data-testid="exam-assign-select-division">
                  <SelectValue placeholder="Division">
                    {filterDivision
                      ? flatDivisions.find((d) => d.id === filterDivision)?.name
                      : undefined}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">All divisions</SelectItem>
                  {flatDivisions.map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {"  ".repeat(d.depth)}{d.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={filterPosition} onValueChange={setFilterPosition}>
                <SelectTrigger className="w-full" data-testid="exam-assign-select-position">
                  <SelectValue placeholder="Position">
                    {filterPosition
                      ? positions.find((p) => p.id === filterPosition)?.title
                      : undefined}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">All positions</SelectItem>
                  {positions.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={filterSpecialization}
                onValueChange={setFilterSpecialization}
              >
                <SelectTrigger className="w-full" data-testid="exam-assign-select-specialization">
                  <SelectValue placeholder="Specialization">
                    {filterSpecialization
                      ? specializations.find((s) => s.id === filterSpecialization)?.title
                      : undefined}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">All</SelectItem>
                  {specializations.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="max-h-80 overflow-y-auto rounded-md border">
              <div className="flex items-center gap-3 border-b p-2">
                <Checkbox
                  data-testid="exam-assign-checkbox-select-all"
                  checked={allSelectableSelected}
                  disabled={employeesLoading || selectableEmployees.length === 0}
                  onCheckedChange={toggleAllSelectable}
                />
                <span className="text-sm text-muted-foreground">
                  Select all ({selectableEmployees.length})
                </span>
              </div>
              {employeesLoading ? (
                <p className="p-4 text-center text-sm text-muted-foreground">Loading...</p>
              ) : filteredEmployees.length === 0 ? (
                <p className="p-4 text-center text-sm text-muted-foreground">No employees match filters</p>
              ) : (
                <ul className="divide-y">
                  {filteredEmployees.map((emp) => {
                    const isAssigned = alreadyAssigned.has(emp.id);
                    const isSelected = selectedEmployeeIds.has(emp.id);
                    return (
                      <li
                        key={emp.id}
                        className={`flex items-center gap-3 p-2 text-sm ${isAssigned ? "opacity-50" : ""}`}
                      >
                        <Checkbox
                          checked={isSelected}
                          disabled={isAssigned}
                          onCheckedChange={() => toggleEmployee(emp.id)}
                        />
                        <div className="min-w-0 flex-1">
                          <p className="truncate font-medium">{emp.user_name ?? emp.user_email ?? emp.id.slice(0, 8)}</p>
                          <p className="truncate text-xs text-muted-foreground">
                            {[emp.position_title, emp.division_name].filter(Boolean).join(" · ")}
                          </p>
                        </div>
                        {isAssigned && (
                          <span className="text-xs text-muted-foreground">already assigned</span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              {selectedEmployeeIds.size} selected
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAssignOpen(false)} disabled={saving}>Cancel</Button>
            <Button onClick={assignEmployees} disabled={saving || selectedEmployeeIds.size === 0}>
              {saving ? "Assigning..." : "Assign"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Pass mark dialog (HRP-226 redo: add + edit) */}
      <Dialog
        open={pmOpen}
        onOpenChange={(open) => {
          setPmOpen(open);
          if (!open) setPmEditingId(null);
        }}
      >
        <DialogContent data-testid="exam-passmark-modal">
          <DialogHeader>
            <DialogTitle>{pmEditingId ? "Edit pass mark" : "Add pass mark"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Minimum score (%)</Label>
              <Input
                type="number"
                min={0}
                max={100}
                placeholder="e.g. 60"
                value={pmForm.min_score_percent}
                onChange={(e) => setPmForm({ ...pmForm, min_score_percent: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Minimum score (points)</Label>
              <Input
                type="number"
                min={0}
                placeholder="e.g. 15"
                value={pmForm.min_score_points}
                onChange={(e) => setPmForm({ ...pmForm, min_score_points: e.target.value })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPmOpen(false)} disabled={saving}>Cancel</Button>
            <Button
              onClick={savePassMark}
              disabled={saving || (!pmForm.min_score_percent && !pmForm.min_score_points)}
              data-testid="exam-passmark-modal-btn-submit"
            >
              {saving ? "Saving..." : pmEditingId ? "Save" : "Add"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* HRP-231: Title edit dialog */}
      <Dialog open={titleOpen} onOpenChange={setTitleOpen}>
        <DialogContent data-testid="exam-title-modal">
          <DialogHeader>
            <DialogTitle>Edit title</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <Label>
              Title <span className="text-destructive">*</span>
            </Label>
            <Input
              value={titleDraft}
              onChange={(e) => setTitleDraft(e.target.value)}
              maxLength={100}
              data-testid="exam-title-input"
            />
            {!titleDraft.trim() && (
              <p className="text-xs text-destructive">Title is required</p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTitleOpen(false)} disabled={saving}>Cancel</Button>
            <Button
              onClick={saveTitle}
              disabled={saving || !titleDraft.trim()}
              data-testid="exam-title-save"
            >
              {saving ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* HRP-231: Description edit dialog */}
      <Dialog open={descOpen} onOpenChange={setDescOpen}>
        <DialogContent data-testid="exam-description-modal">
          <DialogHeader>
            <DialogTitle>Edit description</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <Label>Description</Label>
            <Textarea
              value={descDraft}
              onChange={(e) => setDescDraft(e.target.value)}
              rows={3}
              maxLength={250}
              data-testid="exam-description-input"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDescOpen(false)} disabled={saving}>Cancel</Button>
            <Button
              onClick={saveDescription}
              disabled={saving}
              data-testid="exam-description-save"
            >
              {saving ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* HRP-228: Edit question dialog */}
      <Dialog
        open={qEditId !== null}
        onOpenChange={(o) => { if (!o) closeQuestionEditor(); }}
      >
        <DialogContent className="max-w-lg" data-testid="exam-question-edit-modal">
          <DialogHeader>
            <DialogTitle>Edit question</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>
                Question <span className="text-destructive">*</span>
              </Label>
              <Textarea
                value={qEditForm.title}
                onChange={(e) => setQEditForm({ ...qEditForm, title: e.target.value })}
                rows={2}
                data-testid="exam-question-edit-title"
              />
            </div>
            <div className="space-y-2">
              <Label>Description (optional)</Label>
              <Input
                value={qEditForm.description}
                onChange={(e) => setQEditForm({ ...qEditForm, description: e.target.value })}
              />
            </div>
            <div className="flex gap-4">
              <div className="flex-1 space-y-2">
                <Label>Type</Label>
                <Select
                  value={qEditForm.question_type}
                  onValueChange={(val) =>
                    setQEditForm({ ...qEditForm, question_type: val })
                  }
                >
                  <SelectTrigger className="w-full">
                    <SelectValue>{questionTypeLabel(qEditForm.question_type)}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {questionTypes.map((t) => (
                      <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="w-24 space-y-2">
                <Label>Weight</Label>
                <Input
                  type="number"
                  min={1}
                  value={qEditForm.weight}
                  onChange={(e) =>
                    setQEditForm({ ...qEditForm, weight: Number(e.target.value) })
                  }
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>Image (optional)</Label>
              {qEditImage ? (
                <div className="space-y-2">
                  {/* eslint-disable-next-line @next/next/no-img-element -- preview of user-uploaded image */}
                  <img src={qEditImage.url} alt={qEditImage.name} className="max-h-32 rounded-md border" />
                  <button
                    onClick={() => setQEditImage(null)}
                    className="text-xs text-destructive hover:underline"
                  >
                    Remove image
                  </button>
                </div>
              ) : (
                <div>
                  <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border px-3 py-1.5 text-sm hover:bg-muted transition-colors">
                    <ImagePlus className="h-4 w-4" />
                    {qEditImageUploading ? "Uploading..." : "Add image"}
                    <input
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={handleQuestionEditImageUpload}
                      disabled={qEditImageUploading}
                    />
                  </label>
                </div>
              )}
            </div>
            {!qEditIsEssay && (
              <div className="space-y-2">
                <Label>
                  Options <span className="text-destructive">*</span>
                </Label>
                <p className="text-xs text-muted-foreground">
                  At least 2 options, at least 1 marked correct
                  {qEditForm.question_type === "single_choice" ? " (exactly one)" : ""}
                </p>
                <div className="space-y-2">
                  {qEditOptions.map((opt, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <Checkbox
                        checked={opt.is_correct}
                        onCheckedChange={() => updateEditOption(i, { is_correct: !opt.is_correct })}
                      />
                      <Input
                        className="flex-1"
                        placeholder={`Option ${i + 1}`}
                        value={opt.title}
                        onChange={(e) => updateEditOption(i, { title: e.target.value })}
                      />
                      {qEditOptions.length > 2 && (
                        <Button size="icon-xs" variant="ghost" onClick={() => removeEditOption(i)}>
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      )}
                    </div>
                  ))}
                  <Button size="sm" variant="ghost" onClick={addEditOption}>
                    <Plus className="mr-1 h-3 w-3" />
                    Add option
                  </Button>
                </div>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closeQuestionEditor} disabled={saving}>Cancel</Button>
            <Button
              onClick={saveQuestionEdit}
              disabled={saving || !qEditValid}
              data-testid="exam-question-edit-save"
            >
              {saving ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* HRP-228: Delete question confirmation */}
      <Dialog
        open={qDeleteId !== null}
        onOpenChange={(o) => { if (!o) setQDeleteId(null); }}
      >
        <DialogContent data-testid="exam-question-delete-modal">
          <DialogHeader>
            <DialogTitle>Delete question?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This will remove the question and all of its options. The action cannot be undone.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setQDeleteId(null)} disabled={saving}>Cancel</Button>
            <Button
              variant="destructive"
              onClick={confirmDeleteQuestion}
              disabled={saving}
              data-testid="exam-question-delete-confirm"
            >
              {saving ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Deadline edit dialog */}
      <Dialog open={deadlineOpen} onOpenChange={setDeadlineOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit deadline</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <Label>Deadline</Label>
            {/* HRP-335: shared DatePicker (HRP-152) instead of the
                native date input. */}
            <DatePicker
              min={todayLocalISO()}
              value={deadlineDraft}
              onChange={setDeadlineDraft}
              data-testid="exam-deadline-input"
            />
            {deadlineDraft && isPastDeadline(deadlineDraft) && (
              <p className="text-xs text-destructive">Deadline cannot be in the past</p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeadlineOpen(false)} disabled={saving}>Cancel</Button>
            <Button onClick={saveDeadline} disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
