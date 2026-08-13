"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { useCompetenceTree } from "@/hooks/use-competence-tree";
import { cn, flattenTree } from "@/lib/utils";
import { formatDate } from "@/lib/date-format";
import { getCurrencyOptions, getDefaultSalaryCurrency } from "@/lib/currency";
import {
  ASSESSMENT_STATUS_COLORS,
  assessmentRowDate,
} from "@/lib/assessment-status";
import {
  assessmentStatusTitle,
  assessmentTypeTitle,
} from "@/lib/reference-labels";
import { pdpStatusColor, translatePdpStatus } from "@/lib/pdp-status";
import { sortPdpsForList } from "@/lib/pdp-filters";
import {
  goalsProgressPercent,
  openAssessmentCount,
  openPdpCount,
} from "@/lib/employee-kpis";
import { EmployeeCompetenceTree } from "@/components/employees/employee-competence-tree";
import { employeeStatusLabel } from "@/components/employees/employee-status";
import { EmployeeCompetenceBreakdown } from "@/components/employees/employee-competence-breakdown";
import { CompetenceTreePicker } from "@/components/competence/competence-tree-picker";
import type {
  Assessment,
  AssessmentList,
  Compensation,
  Course,
  Division,
  Education,
  Employee,
  EmployeeCompetenceOverview,
  EmployeeEvent,
  PDP,
  PreviousEmployment,
  WorkExperience,
} from "@/lib/types";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DatePicker } from "@/components/ui/date-picker";
import { Input } from "@/components/ui/input";
import { PositionCombobox } from "@/components/position-combobox";
import { yesterdayIso } from "@/lib/date-picker-helpers";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuth } from "@/context/auth-context";
import { usePermissions } from "@/hooks/use-permissions";
import { toast } from "sonner";
import { ArrowLeft, DollarSign, ExternalLink, Info, Pencil, Plus, Trash2 } from "lucide-react";
import { BADGE_COLOR } from "@/lib/badge-tones";

const statusColors: Record<string, string> = {
  active: BADGE_COLOR.green,
  inactive: BADGE_COLOR.neutral,
  on_leave: BADGE_COLOR.yellow,
  terminated: BADGE_COLOR.red,
};

const statusOptions = ["active", "inactive", "on_leave", "terminated"];

const eventTypeOptions = [
  "hire",
  "promotion",
  "transfer",
  "leave",
  "return",
  "review",
  "training",
  "other",
];

const degreeOptions = [
  "Secondary",
  "Vocational",
  "Bachelor",
  "Master",
  "PhD",
  "Doctorate",
  "Other",
];

/** Loose shape of the next-intl translator so plain helpers below can take
 * it as an argument instead of being turned into components. */
type Translate = (
  key: string,
  values?: Record<string, string | number>,
) => string;

function formatDateRange(
  t: Translate,
  start: string,
  end: string | null,
): string {
  const s = formatDate(start);
  if (!end) return `${s} — ${t("present")}`;
  return `${s} — ${formatDate(end)}`;
}

export default function EmployeeDetailPage() {
  const t = useTranslations("employees");
  const locale = useLocale();
  const tc = useTranslations("common");
  // HRP-476: the Assessments / Development tabs mirror the standalone list
  // pages, so their status chips and row dates read from those pages'
  // catalogs instead of duplicating the wording under `employees`.
  const tAssessments = useTranslations("assessments");
  const tDevelopment = useTranslations("development");
  const tRef = useTranslations("reference");
  const { id } = useParams<{ id: string }>();
  const { user: currentUser } = useAuth();
  const { canManage } = usePermissions();
  const [employee, setEmployee] = useState<Employee | null>(null);
  // HRP-66: employee role keeps write access to the Education tab on their
  // own profile but loses every other write button (Edit profile, Add
  // event / experience / compensation, and the row-level edit/delete
  // inside the tabs that 403 anyway).
  const isOwnProfile =
    !!currentUser?.id && !!employee?.user_id && currentUser.id === employee.user_id;
  const canEditOwnEducation = isOwnProfile;
  const canEditProfile = canManage;
  const canEditOtherSections = canManage;
  const [events, setEvents] = useState<EmployeeEvent[]>([]);
  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [pdps, setPdps] = useState<PDP[]>([]);
  const [divisions, setDivisions] = useState<Division[]>([]);
  const [competenceOverview, setCompetenceOverview] =
    useState<EmployeeCompetenceOverview | null>(null);
  // GF1
  const [workExperiences, setWorkExperiences] = useState<WorkExperience[]>([]);
  const [prevEmployments, setPrevEmployments] = useState<PreviousEmployment[]>([]);
  // GF2
  const [educationRecords, setEducationRecords] = useState<Education[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  // GF5
  const [compensations, setCompensations] = useState<Compensation[]>([]);
  // Competences for tagging (GF1/GF2 Improve) — derived from shared tree.
  const { tree: competenceTree } = useCompetenceTree();

  const [loading, setLoading] = useState(true);

  // Edit employee
  const [editOpen, setEditOpen] = useState(false);
  const [editForm, setEditForm] = useState({
    first_name: "",
    last_name: "",
    division_id: "",
    position_id: "",
    status: "",
  });

  // Add event
  const [eventOpen, setEventOpen] = useState(false);
  const [eventForm, setEventForm] = useState({
    event_type: "other",
    description: "",
    event_date: new Date().toISOString().split("T")[0],
  });

  // GF1 / HRP-151: Current Employment dialog
  const [weOpen, setWeOpen] = useState(false);
  const [weEditId, setWeEditId] = useState<string | null>(null);
  const [weForm, setWeForm] = useState({
    division_id: "",
    position_id: "",
    description: "",
    start_date: "",
    end_date: "",
  });
  const [weError, setWeError] = useState<string | null>(null);

  // GF1: Previous Employment dialog
  const [peOpen, setPeOpen] = useState(false);
  const [peEditId, setPeEditId] = useState<string | null>(null);
  const [peForm, setPeForm] = useState({
    company_name: "",
    position: "",
    description: "",
    start_date: "",
    end_date: "",
  });
  const [peError, setPeError] = useState<string | null>(null);

  // GF2: Education dialog
  const [eduOpen, setEduOpen] = useState(false);
  const [eduEditId, setEduEditId] = useState<string | null>(null);
  const [eduForm, setEduForm] = useState({
    institution: "",
    degree: "",
    field_of_study: "",
    start_date: "",
    end_date: "",
  });
  const [eduError, setEduError] = useState<string | null>(null);

  // GF2: Course dialog
  const [courseOpen, setCourseOpen] = useState(false);
  const [courseEditId, setCourseEditId] = useState<string | null>(null);
  const [courseForm, setCourseForm] = useState({
    title: "",
    provider: "",
    certificate_url: "",
    completed_date: "",
    expiry_date: "",
  });
  const [courseCompetenceIds, setCourseCompetenceIds] = useState<string[]>([]);
  const [courseError, setCourseError] = useState<string | null>(null);

  // GF5: Compensation dialog
  const [compOpen, setCompOpen] = useState(false);
  const [compEditId, setCompEditId] = useState<string | null>(null);
  // HRP-439: compensations default to the installation's currency, the
  // same source the grade salary ranges use.
  const [compForm, setCompForm] = useState({
    type: "salary",
    amount: "",
    currency: getDefaultSalaryCurrency(),
    effective_date: "",
    end_date: "",
    notes: "",
  });
  const [compError, setCompError] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);

  const load = useCallback(
    async function load() {
      try {
        const [emp, evts, asmts, pdpList, divs, we, pe, edu, crs, comp, overview] =
          await Promise.allSettled([
            api.get<Employee>(`/employees/${id}`),
            api.get<EmployeeEvent[]>(`/employees/${id}/events`),
            api.get<AssessmentList>(`/assessments?employee_id=${id}`),
            api.get<PDP[]>(`/pdp?employee_id=${id}`),
            api.get<Division[]>("/divisions"),
            api.get<WorkExperience[]>(`/employees/${id}/work-experience`),
            api.get<PreviousEmployment[]>(`/employees/${id}/previous-employment`),
            api.get<Education[]>(`/employees/${id}/education`),
            api.get<Course[]>(`/employees/${id}/courses`),
            api.get<Compensation[]>(`/employees/${id}/compensation`),
            api.get<EmployeeCompetenceOverview>(
              `/employees/${id}/competences`,
            ),
          ]);
        if (emp.status === "fulfilled") setEmployee(emp.value);
        if (evts.status === "fulfilled") setEvents(evts.value);
        if (asmts.status === "fulfilled") setAssessments(asmts.value.items);
        if (pdpList.status === "fulfilled") setPdps(pdpList.value);
        if (divs.status === "fulfilled") setDivisions(divs.value);
        if (we.status === "fulfilled") setWorkExperiences(we.value);
        if (pe.status === "fulfilled") setPrevEmployments(pe.value);
        if (edu.status === "fulfilled") setEducationRecords(edu.value);
        if (crs.status === "fulfilled") setCourses(crs.value);
        if (comp.status === "fulfilled") setCompensations(comp.value);
        if (overview.status === "fulfilled") setCompetenceOverview(overview.value);
        if (emp.status === "rejected") toast.error(t("toastLoadFailed"));
      } finally {
        setLoading(false);
      }
    },
    [id, t],
  );

  useEffect(() => {
    load();
  }, [load]);

  const flatDivisions = flattenTree(divisions);

  function openEdit() {
    if (!employee) return;
    // HRP-121: derive first/last from user_name (concatenated by the API).
    // Best-effort split on the first space — multi-word first names can be
    // corrected inline before saving.
    const fullName = employee.user_name || "";
    const firstSpace = fullName.indexOf(" ");
    const firstName =
      firstSpace === -1 ? fullName : fullName.slice(0, firstSpace);
    const lastName =
      firstSpace === -1 ? "" : fullName.slice(firstSpace + 1);
    setEditForm({
      first_name: firstName,
      last_name: lastName,
      division_id: employee.division_id || "",
      position_id: employee.position_id || "",
      status: employee.status,
    });
    setEditOpen(true);
  }

  async function handleEdit() {
    const firstName = editForm.first_name.trim();
    const lastName = editForm.last_name.trim();
    if (!firstName || !lastName) {
      toast.error(t("toastNameRequired"));
      return;
    }
    setSaving(true);
    try {
      await api.put(`/employees/${id}`, {
        first_name: firstName,
        last_name: lastName,
        position_id: editForm.position_id || null,
        division_id: editForm.division_id || null,
        status: editForm.status || undefined,
      });
      toast.success(t("toastUpdated"));
      setEditOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastUpdateFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function handleAddEvent() {
    setSaving(true);
    try {
      await api.post(`/employees/${id}/events`, eventForm);
      toast.success(t("toastEventAdded"));
      setEventOpen(false);
      setEventForm({
        event_type: "other",
        description: "",
        event_date: new Date().toISOString().split("T")[0],
      });
      await load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("toastEventAddFailed"),
      );
    } finally {
      setSaving(false);
    }
  }

  // --- HRP-151: Current Employment handlers ---

  function openWeAdd() {
    setWeEditId(null);
    setWeError(null);
    // Defaults pull the employee's current division/position so the
    // common "another spell on the current role" case is one click.
    setWeForm({
      division_id: employee?.division_id || "",
      position_id: employee?.position_id || "",
      description: "",
      start_date: new Date().toISOString().split("T")[0],
      end_date: "",
    });
    setWeOpen(true);
  }

  function openWeEdit(item: WorkExperience) {
    setWeEditId(item.id);
    setWeError(null);
    setWeForm({
      division_id: item.division_id || "",
      position_id: item.position_id || "",
      description: item.description || "",
      start_date: item.start_date,
      end_date: item.end_date || "",
    });
    setWeOpen(true);
  }

  async function handleWeSave() {
    setWeError(null);
    if (!weForm.division_id || !weForm.position_id || !weForm.start_date) {
      setWeError(t("errorWeRequired"));
      return;
    }
    // HRP-219 Task 3: Start must be on or before End for current employment.
    if (
      weForm.end_date &&
      weForm.start_date &&
      weForm.start_date > weForm.end_date
    ) {
      setWeError(t("errorStartBeforeEnd"));
      return;
    }
    setSaving(true);
    try {
      const body = {
        division_id: weForm.division_id,
        position_id: weForm.position_id,
        start_date: weForm.start_date,
        end_date: weForm.end_date || null,
        description: weForm.description || null,
      };
      if (weEditId) {
        await api.put(`/employees/${id}/work-experience/${weEditId}`, body);
        toast.success(t("toastWeUpdated"));
      } else {
        await api.post(`/employees/${id}/work-experience`, body);
        toast.success(t("toastWeAdded"));
      }
      setWeOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastSaveFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function handleWeDelete(itemId: string) {
    setSaving(true);
    try {
      await api.delete(`/employees/${id}/work-experience/${itemId}`);
      toast.success(t("toastWeDeleted"));
      await load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("toastDeleteFailed"),
      );
    } finally {
      setSaving(false);
    }
  }

  // --- GF1: Previous Employment handlers ---

  function openPeAdd() {
    setPeEditId(null);
    setPeError(null);
    setPeForm({ company_name: "", position: "", description: "", start_date: "", end_date: "" });
    setPeOpen(true);
  }

  function openPeEdit(item: PreviousEmployment) {
    setPeEditId(item.id);
    setPeError(null);
    setPeForm({
      company_name: item.company_name,
      position: item.position,
      description: item.description || "",
      start_date: item.start_date,
      end_date: item.end_date || "",
    });
    setPeOpen(true);
  }

  async function handlePeSave() {
    setPeError(null);
    // HRP-219 Tasks 1 + 2: Company, Position, Start, End required;
    // both dates must be in the past; Start must be on or before End.
    if (
      !peForm.company_name.trim() ||
      !peForm.position.trim() ||
      !peForm.start_date ||
      !peForm.end_date
    ) {
      setPeError(t("errorPeRequired"));
      return;
    }
    const today = yesterdayIso();
    if (peForm.start_date > today || peForm.end_date > today) {
      setPeError(t("errorDatesInPast"));
      return;
    }
    if (peForm.start_date > peForm.end_date) {
      setPeError(t("errorStartBeforeEnd"));
      return;
    }
    setSaving(true);
    try {
      const body = {
        ...peForm,
        company_name: peForm.company_name.trim(),
        position: peForm.position.trim(),
        description: peForm.description || null,
      };
      if (peEditId) {
        await api.put(`/employees/${id}/previous-employment/${peEditId}`, body);
        toast.success(t("toastPeUpdated"));
      } else {
        await api.post(`/employees/${id}/previous-employment`, body);
        toast.success(t("toastPeAdded"));
      }
      setPeOpen(false);
      await load();
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("toastSaveFailed");
      setPeError(msg);
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  }

  async function handlePeDelete(itemId: string) {
    setSaving(true);
    try {
      await api.delete(`/employees/${id}/previous-employment/${itemId}`);
      toast.success(t("toastPeDeleted"));
      await load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("toastDeleteFailed"),
      );
    } finally {
      setSaving(false);
    }
  }

  // --- GF2: Education handlers ---

  function openEduAdd() {
    setEduEditId(null);
    setEduError(null);
    setEduForm({ institution: "", degree: "", field_of_study: "", start_date: "", end_date: "" });
    setEduOpen(true);
  }

  function openEduEdit(item: Education) {
    setEduEditId(item.id);
    setEduError(null);
    setEduForm({
      institution: item.institution,
      degree: item.degree,
      field_of_study: item.field_of_study,
      start_date: item.start_date,
      end_date: item.end_date || "",
    });
    setEduOpen(true);
  }

  async function handleEduSave() {
    setEduError(null);
    // HRP-220 Education block: Institution, Degree, Field of Study,
    // Start date are required; Start <= End when End is set.
    if (
      !eduForm.institution.trim() ||
      !eduForm.degree.trim() ||
      !eduForm.field_of_study.trim() ||
      !eduForm.start_date
    ) {
      setEduError(t("errorEduRequired"));
      return;
    }
    if (
      eduForm.end_date &&
      eduForm.start_date > eduForm.end_date
    ) {
      setEduError(t("errorStartBeforeEnd"));
      return;
    }
    setSaving(true);
    try {
      const body = {
        ...eduForm,
        institution: eduForm.institution.trim(),
        field_of_study: eduForm.field_of_study.trim(),
        end_date: eduForm.end_date || null,
      };
      if (eduEditId) {
        await api.put(`/employees/${id}/education/${eduEditId}`, body);
        toast.success(t("toastEduUpdated"));
      } else {
        await api.post(`/employees/${id}/education`, body);
        toast.success(t("toastEduAdded"));
      }
      setEduOpen(false);
      await load();
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("toastSaveFailed");
      setEduError(msg);
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  }

  async function handleEduDelete(itemId: string) {
    setSaving(true);
    try {
      await api.delete(`/employees/${id}/education/${itemId}`);
      toast.success(t("toastEduDeleted"));
      await load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("toastDeleteFailed"),
      );
    } finally {
      setSaving(false);
    }
  }

  // --- GF2: Course handlers ---

  function openCourseAdd() {
    setCourseEditId(null);
    setCourseError(null);
    setCourseForm({ title: "", provider: "", certificate_url: "", completed_date: "", expiry_date: "" });
    setCourseCompetenceIds([]);
    setCourseOpen(true);
  }

  function openCourseEdit(item: Course) {
    setCourseEditId(item.id);
    setCourseError(null);
    setCourseForm({
      title: item.title,
      provider: item.provider || "",
      certificate_url: item.certificate_url || "",
      completed_date: item.completed_date || "",
      expiry_date: item.expiry_date || "",
    });
    setCourseCompetenceIds(item.competences?.map((c) => c.id) || []);
    setCourseOpen(true);
  }

  async function handleCourseSave() {
    setCourseError(null);
    // HRP-220 Courses block: Title and Completed date are required;
    // Completed date must be in the past; Completed <= Expire when set.
    if (!courseForm.title.trim() || !courseForm.completed_date) {
      setCourseError(t("errorCourseRequired"));
      return;
    }
    const today = yesterdayIso();
    if (courseForm.completed_date > today) {
      setCourseError(t("errorCompletedInPast"));
      return;
    }
    if (
      courseForm.expiry_date &&
      courseForm.completed_date > courseForm.expiry_date
    ) {
      setCourseError(t("errorCompletedBeforeExpiry"));
      return;
    }
    setSaving(true);
    try {
      const body = {
        ...courseForm,
        title: courseForm.title.trim(),
        provider: courseForm.provider || null,
        certificate_url: courseForm.certificate_url || null,
        expiry_date: courseForm.expiry_date || null,
        competence_ids: courseCompetenceIds,
      };
      if (courseEditId) {
        await api.put(`/employees/${id}/courses/${courseEditId}`, body);
        toast.success(t("toastCourseUpdated"));
      } else {
        await api.post(`/employees/${id}/courses`, body);
        toast.success(t("toastCourseAdded"));
      }
      setCourseOpen(false);
      await load();
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("toastSaveFailed");
      setCourseError(msg);
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  }

  async function handleCourseDelete(itemId: string) {
    setSaving(true);
    try {
      await api.delete(`/employees/${id}/courses/${itemId}`);
      toast.success(t("toastCourseDeleted"));
      await load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("toastDeleteFailed"),
      );
    } finally {
      setSaving(false);
    }
  }

  // --- GF5: Compensation handlers ---

  function openCompAdd() {
    setCompEditId(null);
    setCompError(null);
    setCompForm({
      type: "salary",
      amount: "",
      currency: getDefaultSalaryCurrency(),
      effective_date: "",
      end_date: "",
      notes: "",
    });
    setCompOpen(true);
  }

  function openCompEdit(item: Compensation) {
    setCompEditId(item.id);
    setCompError(null);
    setCompForm({
      type: item.type,
      amount: String(item.amount / 100),
      currency: item.currency,
      effective_date: item.effective_date,
      end_date: item.end_date || "",
      notes: item.notes || "",
    });
    setCompOpen(true);
  }

  async function handleCompSave() {
    setCompError(null);
    // HRP-221 Bug 1: Effective date must be on or before End date.
    if (
      compForm.end_date &&
      compForm.effective_date &&
      compForm.effective_date > compForm.end_date
    ) {
      setCompError(t("errorCompEffectiveBeforeEnd"));
      return;
    }
    setSaving(true);
    try {
      const body = {
        type: compForm.type,
        amount: Math.round(parseFloat(compForm.amount) * 100),
        currency: compForm.currency,
        effective_date: compForm.effective_date,
        end_date: compForm.end_date || null,
        notes: compForm.notes || null,
      };
      if (compEditId) {
        await api.put(`/employees/${id}/compensation/${compEditId}`, body);
        toast.success(t("toastCompUpdated"));
      } else {
        await api.post(`/employees/${id}/compensation`, body);
        toast.success(t("toastCompAdded"));
      }
      setCompOpen(false);
      await load();
    } catch (err) {
      // HRP-221 Bug 2: surface the backend error inline instead of just
      // toasting it — the save did not succeed if we reach this branch,
      // and an inline message gives a clearer recovery path than a toast
      // that vanishes.
      const msg = err instanceof Error ? err.message : t("toastSaveFailed");
      setCompError(msg);
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  }

  async function handleCompDelete(itemId: string) {
    setSaving(true);
    try {
      await api.delete(`/employees/${id}/compensation/${itemId}`);
      toast.success(t("toastCompDeleted"));
      await load();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("toastDeleteFailed"),
      );
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        {tc("loading")}
      </div>
    );
  }

  if (!employee) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" render={<Link href="/employees" />}>
          <ArrowLeft className="mr-1 h-4 w-4" />
          {t("backToEmployees")}
        </Button>
        <div className="py-12 text-center text-muted-foreground">
          {t("notFound")}
        </div>
      </div>
    );
  }

  // HRP-246: Tenure measures "how long the employee has been using the
  // system", anchored to the first auth date. Falls back to hire_date
  // for accounts that have never logged in so the tile is never blank.
  const tenureAnchorIso = employee.user_first_login_at ?? employee.hire_date;
  const tenureYears = (() => {
    const ms = Date.now() - new Date(tenureAnchorIso).getTime();
    const years = ms / (365.25 * 24 * 3600 * 1000);
    return years >= 1
      ? t("kpiYearsShort", { years: years.toFixed(1) })
      : t("kpiMonthsShort", { months: Math.max(0, Math.round(years * 12)) });
  })();

  const latestAssessment = [...assessments].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  )[0];
  const lastAssessmentLabel = latestAssessment
    ? (() => {
        const days = Math.max(
          0,
          Math.floor(
            (Date.now() - new Date(latestAssessment.created_at).getTime()) /
              (24 * 3600 * 1000),
          ),
        );
        return days === 0 ? t("kpiToday") : t("kpiDaysShort", { days });
      })()
    : "—";

  // HRP-247 / HRP-246: shared helpers — "open" means not yet Done or
  // Cancelled. The legacy filter compared against ``"completed"`` (no
  // PDP ever carries that status), so the count silently included
  // Done / Cancelled plans.
  const openPlansCount = openPdpCount(pdps);
  const goalsProgress = goalsProgressPercent(pdps);
  const openAssessmentsCount = openAssessmentCount(assessments);

  const initialsLetters = employee.user_name
    ? employee.user_name
        .split(" ")
        .map((n: string) => n[0])
        .join("")
        .toUpperCase()
        .slice(0, 2)
    : "?";

  // ``key`` keeps the KPI test ids locale-independent (HRP-247 documents
  // ``employee-kpi-status`` & co.), ``label`` carries the translation.
  const kpis: {
    key: string;
    label: string;
    value: string;
    sub: string;
    info?: string;
  }[] = [
    {
      key: "status",
      label: t("status"),
      value: employeeStatusLabel(t, employee.status),
      // HRP-246: anchor on the last status mutation timestamp; fall
      // back to ``created_at`` only for rows that pre-date the
      // ``status_changed_at`` column.
      sub: t("kpiSince", {
        date: formatDate(employee.status_changed_at ?? employee.created_at),
      }),
    },
    {
      key: "tenure",
      label: t("kpiTenure"),
      value: tenureYears,
      // HRP-246: TENURE measures how long the employee has been
      // *using the system* — anchored on first auth, not hire date.
      sub: t("kpiJoined", { date: formatDate(tenureAnchorIso) }),
    },
    {
      key: "assessments",
      label: t("assessments"),
      value: String(assessments.length),
      // HRP-246: sub-line now spells out the open count instead of the
      // latest row's status, which read as random to QA. "Open" means
      // status_code not in (done, cancelled).
      sub:
        assessments.length === 0
          ? t("kpiNoRecords")
          : t("kpiOpenAssessments", { count: openAssessmentsCount }),
    },
    {
      key: "goals-progress",
      label: t("kpiGoalsProgress"),
      value: goalsProgress === null ? "—" : `${goalsProgress}%`,
      sub: t("kpiOpenPlans", { count: openPlansCount }),
      // HRP-247: surface the formula so HR doesn't have to guess what
      // "55%" means. Open plans = PDPs not yet Done or Cancelled; each
      // plan's progress is items completed / items total.
      info: t("kpiGoalsProgressInfo"),
    },
    {
      key: "last-assessment",
      label: t("kpiLastAssessment"),
      value: lastAssessmentLabel,
      sub:
        latestAssessment?.title ||
        (latestAssessment
          ? assessmentTypeTitle(tRef, latestAssessment)
          : t("kpiNoRecords")),
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <Link
        href="/employees"
        className="inline-flex items-center gap-1 self-start text-xs text-muted-foreground transition-colors hover:text-foreground"
        data-testid="employee-btn-back"
      >
        <ArrowLeft className="h-3 w-3" />
        {t("allEmployees")}
      </Link>

      <div
        className="overflow-hidden rounded-xl border border-border bg-card ring-1 ring-foreground/5"
        data-testid="employee-card-info"
      >
        <div className="flex flex-wrap items-start justify-between gap-4 p-5">
          <div className="flex min-w-0 items-center gap-4">
            <Avatar className="h-14 w-14" data-testid="employee-avatar">
              {employee.avatar_url && <AvatarImage src={employee.avatar_url} />}
              <AvatarFallback className="bg-accent/10 text-base font-semibold text-accent">
                {initialsLetters}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-2xl font-semibold tracking-tight" data-testid="employee-name">
                  {employee.user_name || tc("employee")}
                </h1>
                <Badge variant="secondary" className={statusColors[employee.status] || ""}>
                  {employeeStatusLabel(t, employee.status)}
                </Badge>
              </div>
              <p className="mt-1.5 truncate text-sm text-muted-foreground">
                {[employee.position_title, employee.division_name, employee.user_email]
                  .filter(Boolean)
                  .join(" · ") || "—"}
              </p>
            </div>
          </div>
          {canEditProfile && (
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={openEdit} data-testid="employee-btn-edit">
                <Pencil className="h-3.5 w-3.5" />
                {t("editProfile")}
              </Button>
            </div>
          )}
        </div>
        <div className="flex flex-wrap border-t border-border">
          {kpis.map((k, i) => (
            <div
              key={k.key}
              className={cn(
                "min-w-[140px] flex-1 px-4 py-3.5",
                i < kpis.length - 1 && "border-r border-border",
              )}
              data-testid={`employee-kpi-${k.key}`}
            >
              <div className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                <span>{k.label}</span>
                {k.info && (
                  <Tooltip>
                    <TooltipTrigger
                      type="button"
                      aria-label={t("kpiInfoAria", { label: k.label })}
                      className="inline-flex text-muted-foreground/70 transition-colors hover:text-foreground focus-visible:text-foreground focus-visible:outline-none"
                      data-testid={`employee-kpi-${k.key}-info`}
                    >
                      <Info className="h-3 w-3" />
                    </TooltipTrigger>
                    <TooltipContent className="max-w-xs text-left normal-case">
                      {k.info}
                    </TooltipContent>
                  </Tooltip>
                )}
              </div>
              <div className="mt-1.5 truncate text-lg font-bold capitalize tracking-[-0.02em]">
                {k.value}
              </div>
              <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
                {k.sub}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Tabbed content */}
      <Tabs defaultValue="events">
        <TabsList className="flex w-full max-w-full overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <TabsTrigger value="events" data-testid="employee-tab-events" className="shrink-0">{t("tabEvents")}</TabsTrigger>
          <TabsTrigger value="experience" data-testid="employee-tab-experience" className="shrink-0">{t("tabExperience")}</TabsTrigger>
          <TabsTrigger value="education" data-testid="employee-tab-education" className="shrink-0">{t("tabEducation")}</TabsTrigger>
          <TabsTrigger value="compensation" data-testid="employee-tab-compensation" className="shrink-0">{t("tabCompensation")}</TabsTrigger>
          <TabsTrigger value="assessments" data-testid="employee-tab-assessments" className="shrink-0">{t("assessments")}</TabsTrigger>
          <TabsTrigger value="development" data-testid="employee-tab-development" className="shrink-0">{t("tabDevelopment")}</TabsTrigger>
          <TabsTrigger value="competences" data-testid="employee-tab-competences" className="shrink-0">{t("tabCompetences")}</TabsTrigger>
        </TabsList>

        {/* --- Events tab --- */}
        <TabsContent value="events">
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle className="text-base">{t("tabEvents")}</CardTitle>
              {canEditOtherSections && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setEventOpen(true)}
                data-testid="employee-events-btn-add"
              >
                <Plus className="mr-1 h-4 w-4" />
                {t("addEvent")}
              </Button>
              )}
            </CardHeader>
            <CardContent>
              {events.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  {t("noEvents")}
                </p>
              ) : (
                <div className="space-y-3" data-testid="employee-events-list">
                  {events
                    .sort(
                      (a, b) =>
                        new Date(b.event_date).getTime() -
                        new Date(a.event_date).getTime(),
                    )
                    .map((event) => (
                      <div
                        key={event.id}
                        className="flex items-start gap-3 rounded-md border p-3"
                      >
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium uppercase">
                          {event.event_type.charAt(0)}
                        </div>
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium capitalize">
                              {event.event_type}
                            </span>
                            <span className="text-xs text-muted-foreground">
                              {event.event_date}
                            </span>
                          </div>
                          {event.description && (
                            <p className="mt-0.5 text-sm text-muted-foreground">
                              {event.description}
                            </p>
                          )}
                        </div>
                      </div>
                    ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* --- Experience tab (GF1) --- */}
        <TabsContent value="experience">
          <div className="space-y-6">
            {/* HRP-151: Current Employment block — Division/Position spells
                within the current company, each with a computed duration. */}
            <Card>
              <CardHeader className="flex-row items-center justify-between">
                <CardTitle className="text-base">
                  {t("currentEmployment")}
                </CardTitle>
                {canEditOtherSections && (
                  <Button size="sm" variant="outline" onClick={openWeAdd} data-testid="employee-experience-btn-add">
                    <Plus className="mr-1 h-4 w-4" />
                    {t("add")}
                  </Button>
                )}
              </CardHeader>
              <CardContent data-testid="employee-experience-list">
                {workExperiences.length === 0 ? (
                  <p className="py-4 text-center text-sm text-muted-foreground">
                    {t("noCurrentEmployment")}
                  </p>
                ) : (
                  <div className="space-y-3">
                    {workExperiences.map((item) => {
                      const positionLabel =
                        item.position_title || item.title || "—";
                      const divisionLabel = item.division_name;
                      return (
                        <div
                          key={item.id}
                          className="flex items-start justify-between rounded-md border p-3"
                        >
                          <div className="flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-medium">
                                {positionLabel}
                              </span>
                              {item.role && (
                                <Badge variant="secondary">{item.role}</Badge>
                              )}
                              {item.duration && (
                                <Badge
                                  variant="outline"
                                  className="text-xs"
                                  data-testid={`employee-experience-duration-${item.id}`}
                                >
                                  {item.duration}
                                </Badge>
                              )}
                            </div>
                            {divisionLabel && (
                              <p className="mt-0.5 text-xs text-muted-foreground">
                                {divisionLabel}
                              </p>
                            )}
                            <p className="mt-0.5 text-xs text-muted-foreground">
                              {formatDateRange(t, item.start_date, item.end_date)}
                            </p>
                            {item.description && (
                              <p className="mt-1 text-sm text-muted-foreground">
                                {item.description}
                              </p>
                            )}
                            {item.competences && item.competences.length > 0 && (
                              <div className="mt-1.5 flex flex-wrap gap-1">
                                {item.competences.map((c) => (
                                  <Badge
                                    key={c.id}
                                    variant="outline"
                                    className="text-xs"
                                  >
                                    {c.title}
                                  </Badge>
                                ))}
                              </div>
                            )}
                          </div>
                          {canEditOtherSections && (
                            <div className="flex gap-1">
                              <Button
                                variant="ghost"
                                size="icon-sm"
                                onClick={() => openWeEdit(item)}
                                data-testid={`employee-experience-btn-edit-${item.id}`}
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon-sm"
                                onClick={() => handleWeDelete(item.id)}
                                data-testid={`employee-experience-btn-delete-${item.id}`}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Previous Employment */}
            <Card>
              <CardHeader className="flex-row items-center justify-between">
                <CardTitle className="text-base">
                  {t("previousEmployment")}
                </CardTitle>
                {canEditOtherSections && (
                  <Button size="sm" variant="outline" onClick={openPeAdd} data-testid="employee-prev-employment-btn-add">
                    <Plus className="mr-1 h-4 w-4" />
                    {t("add")}
                  </Button>
                )}
              </CardHeader>
              <CardContent>
                {prevEmployments.length === 0 ? (
                  <p className="py-4 text-center text-sm text-muted-foreground">
                    {t("noPreviousEmployment")}
                  </p>
                ) : (
                  <div className="space-y-3" data-testid="employee-prev-employment-list">
                    {prevEmployments.map((item) => (
                      <div
                        key={item.id}
                        className="flex items-start justify-between rounded-md border p-3"
                      >
                        <div className="flex-1">
                          <span className="text-sm font-medium">
                            {item.position}
                          </span>
                          <p className="text-sm text-muted-foreground">
                            {item.company_name}
                          </p>
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {formatDateRange(t, item.start_date, item.end_date)}
                          </p>
                          {item.description && (
                            <p className="mt-1 text-sm text-muted-foreground">
                              {item.description}
                            </p>
                          )}
                        </div>
                        {canEditOtherSections && (
                          <div className="flex gap-1">
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              onClick={() => openPeEdit(item)}
                              data-testid={`employee-prev-employment-btn-edit-${item.id}`}
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              onClick={() => handlePeDelete(item.id)}
                              data-testid={`employee-prev-employment-btn-delete-${item.id}`}
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
          </div>
        </TabsContent>

        {/* --- Education tab (GF2) --- */}
        <TabsContent value="education">
          <div className="space-y-6">
            {/* Formal Education */}
            <Card>
              <CardHeader className="flex-row items-center justify-between">
                <CardTitle className="text-base">{t("tabEducation")}</CardTitle>
                {(canEditOtherSections || canEditOwnEducation) && (
                  <Button size="sm" variant="outline" onClick={openEduAdd} data-testid="employee-education-btn-add">
                    <Plus className="mr-1 h-4 w-4" />
                    {t("add")}
                  </Button>
                )}
              </CardHeader>
              <CardContent data-testid="employee-education-list">
                {educationRecords.length === 0 ? (
                  <p className="py-4 text-center text-sm text-muted-foreground">
                    {t("noEducation")}
                  </p>
                ) : (
                  <div className="space-y-3">
                    {educationRecords.map((item) => (
                      <div
                        key={item.id}
                        className="flex items-start justify-between rounded-md border p-3"
                      >
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">
                              {t("degreeInField", {
                                degree: item.degree,
                                field: item.field_of_study,
                              })}
                            </span>
                          </div>
                          <p className="text-sm text-muted-foreground">
                            {item.institution}
                          </p>
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {formatDateRange(t, item.start_date, item.end_date)}
                          </p>
                        </div>
                        {(canEditOtherSections || canEditOwnEducation) && (
                        <div className="flex gap-1">
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => openEduEdit(item)}
                            data-testid={`employee-education-btn-edit-${item.id}`}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => handleEduDelete(item.id)}
                            data-testid={`employee-education-btn-delete-${item.id}`}
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

            {/* Courses & Certifications */}
            <Card>
              <CardHeader className="flex-row items-center justify-between">
                <CardTitle className="text-base">
                  {t("coursesTitle")}
                </CardTitle>
                {(canEditOtherSections || canEditOwnEducation) && (
                  <Button size="sm" variant="outline" onClick={openCourseAdd} data-testid="employee-courses-btn-add">
                    <Plus className="mr-1 h-4 w-4" />
                    {t("add")}
                  </Button>
                )}
              </CardHeader>
              <CardContent data-testid="employee-courses-list">
                {courses.length === 0 ? (
                  <p className="py-4 text-center text-sm text-muted-foreground">
                    {t("noCourses")}
                  </p>
                ) : (
                  <div className="space-y-3">
                    {courses.map((item) => (
                      <div
                        key={item.id}
                        className="flex items-start justify-between rounded-md border p-3"
                      >
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">
                              {item.title}
                            </span>
                            {item.expiry_date && (
                              <Badge
                                variant="secondary"
                                className={
                                  new Date(item.expiry_date) < new Date()
                                    ? BADGE_COLOR.red
                                    : ""
                                }
                              >
                                {new Date(item.expiry_date) < new Date()
                                  ? t("courseExpired")
                                  : t("courseExpires", {
                                      date: formatDate(item.expiry_date),
                                    })}
                              </Badge>
                            )}
                          </div>
                          {item.provider && (
                            <p className="text-sm text-muted-foreground">
                              {item.provider}
                            </p>
                          )}
                          {item.completed_date && (
                            <p className="mt-0.5 text-xs text-muted-foreground">
                              {t("courseCompletedOn", {
                                date: formatDate(item.completed_date),
                              })}
                            </p>
                          )}
                          {item.certificate_url && (
                            <a
                              href={item.certificate_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                            >
                              {t("viewCertificate")}
                              <ExternalLink className="h-3 w-3" />
                            </a>
                          )}
                          {item.competences && item.competences.length > 0 && (
                            <div className="mt-1.5 flex flex-wrap gap-1">
                              {item.competences.map((c) => (
                                <Badge key={c.id} variant="outline" className="text-xs">
                                  {c.title}
                                </Badge>
                              ))}
                            </div>
                          )}
                        </div>
                        {(canEditOtherSections || canEditOwnEducation) && (
                          <div className="flex gap-1">
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              onClick={() => openCourseEdit(item)}
                              data-testid={`employee-courses-btn-edit-${item.id}`}
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              onClick={() => handleCourseDelete(item.id)}
                              data-testid={`employee-courses-btn-delete-${item.id}`}
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
          </div>
        </TabsContent>

        {/* --- Compensation tab (GF5) --- */}
        <TabsContent value="compensation">
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle className="text-base">
                {t("compensationHistory")}
              </CardTitle>
              {canEditOtherSections && (
                <Button size="sm" variant="outline" onClick={openCompAdd} data-testid="employee-compensation-btn-add">
                  <Plus className="mr-1 h-4 w-4" />
                  {t("add")}
                </Button>
              )}
            </CardHeader>
            <CardContent data-testid="employee-compensation-list">
              {compensations.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  {t("noCompensation")}
                </p>
              ) : (
                <div className="relative ml-4 border-l-2 border-border pl-6 space-y-6">
                  {[...compensations]
                    .sort((a, b) => new Date(b.effective_date).getTime() - new Date(a.effective_date).getTime())
                    .map((item) => {
                      const typeColors: Record<string, string> = {
                        salary: BADGE_COLOR.green,
                        bonus: BADGE_COLOR.blue,
                        allowance: BADGE_COLOR.purple,
                      };
                      return (
                        <div key={item.id} className="relative">
                          <div className="absolute -left-[31px] top-1 flex h-5 w-5 items-center justify-center rounded-full border-2 border-background bg-primary">
                            <DollarSign className="h-3 w-3 text-primary-foreground" />
                          </div>
                          <div className="flex items-start justify-between rounded-md border p-3">
                            <div className="flex-1">
                              <div className="flex items-center gap-2">
                                <Badge variant="secondary" className={typeColors[item.type] || ""}>
                                  {item.type}
                                </Badge>
                                <span className="text-base font-semibold">
                                  {(item.amount / 100).toLocaleString(locale, {
                                    style: "currency",
                                    currency: item.currency,
                                  })}
                                </span>
                              </div>
                              <p className="mt-1 text-xs text-muted-foreground">
                                {formatDate(item.effective_date)}
                                {item.end_date
                                  ? ` — ${formatDate(item.end_date)}`
                                  : ` — ${t("present")}`}
                              </p>
                              {item.notes && (
                                <p className="mt-1 text-sm text-muted-foreground">{item.notes}</p>
                              )}
                            </div>
                            {canEditOtherSections && (
                              <div className="flex gap-1">
                                <Button variant="ghost" size="icon-sm" onClick={() => openCompEdit(item)} data-testid={`employee-compensation-btn-edit-${item.id}`}>
                                  <Pencil className="h-3.5 w-3.5" />
                                </Button>
                                <Button variant="ghost" size="icon-sm" onClick={() => handleCompDelete(item.id)} data-testid={`employee-compensation-btn-delete-${item.id}`}>
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
        </TabsContent>

        {/* --- Assessments tab --- */}
        <TabsContent value="assessments" data-testid="employee-assessments-content">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("assessments")}</CardTitle>
            </CardHeader>
            <CardContent>
              {assessments.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  {t("noAssessments")}
                </p>
              ) : (
                <div className="rounded-lg border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t("colTitle")}</TableHead>
                        <TableHead>{t("colType")}</TableHead>
                        <TableHead>{t("status")}</TableHead>
                        <TableHead />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {assessments.map((a) => {
                        const rowDate = assessmentRowDate(a);
                        return (
                          <TableRow
                            key={a.id}
                            data-testid={`employee-assessments-row-${a.id}`}
                          >
                            <TableCell className="font-medium">
                              <Link
                                href={`/assessments/${a.id}`}
                                className="text-primary hover:underline"
                              >
                                {a.title || "—"}
                              </Link>
                            </TableCell>
                            <TableCell>{assessmentTypeTitle(tRef, a)}</TableCell>
                            <TableCell>
                              <Badge
                                data-testid={`employee-assessments-row-${a.id}-status`}
                                variant="secondary"
                                className={ASSESSMENT_STATUS_COLORS[a.status_code] || ""}
                              >
                                {assessmentStatusTitle(tRef, a)}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-muted-foreground">
                              {tAssessments("rowDateLabeled", {
                                label: tAssessments(rowDate.labelKey),
                                date: formatDate(rowDate.iso),
                              })}
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
        </TabsContent>

        {/* --- Development tab ---
            HRP-222: drop the Deadline column; surface "Created" (active
            plans), "Done" (Done plans, by ``finished_at``), and
            "Cancelled" (Cancelled plans, by ``finished_at``) in one
            unlabeled date column. The chip colour matches the standalone
            /development list. */}
        <TabsContent value="development">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {t("developmentPlans")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {pdps.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  {t("noDevelopmentPlans")}
                </p>
              ) : (
                <div className="rounded-lg border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t("colTitle")}</TableHead>
                        <TableHead>{t("colProgress")}</TableHead>
                        <TableHead>{t("status")}</TableHead>
                        <TableHead />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {sortPdpsForList(pdps).map((p) => {
                        const dateLabel =
                          p.status === "done"
                            ? t("pdpDateDone")
                            : p.status === "cancelled"
                              ? t("pdpDateCancelled")
                              : t("pdpDateCreated");
                        const dateIso =
                          (p.status === "done" || p.status === "cancelled")
                            ? p.finished_at
                            : p.created_at;
                        return (
                          <TableRow key={p.id}>
                            <TableCell>
                              <Link href={`/development/${p.id}`} className="font-medium hover:underline">
                                {p.title}
                              </Link>
                            </TableCell>
                            <TableCell>
                              <div className="flex items-center gap-2">
                                <div className="h-2 w-20 overflow-hidden rounded-full bg-muted">
                                  <div
                                    className="h-full rounded-full bg-primary"
                                    style={{ width: `${p.total_progress}%` }}
                                  />
                                </div>
                                <span className="text-xs text-muted-foreground">
                                  {p.total_progress}%
                                </span>
                              </div>
                            </TableCell>
                            <TableCell>
                              <Badge variant="secondary" className={pdpStatusColor(p.status)}>
                                {translatePdpStatus(tDevelopment, p.status)}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-muted-foreground">
                              {dateIso ? (
                                <span>
                                  <span className="text-xs">{dateLabel}: </span>
                                  {formatDate(dateIso)}
                                </span>
                              ) : (
                                "—"
                              )}
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
        </TabsContent>

        {/* --- HRP-153: Competences tab — two blocks instead of the radar */}
        <TabsContent value="competences">
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  {t("currentPositionCompetences")}
                </CardTitle>
              </CardHeader>
              <CardContent>
                {competenceOverview ? (
                  <EmployeeCompetenceTree
                    tree={competenceTree}
                    rows={competenceOverview.current_position}
                  />
                ) : (
                  <p
                    className="py-4 text-center text-sm text-muted-foreground"
                    data-testid="employee-competences-current-loading"
                  >
                    {t("competencesLoading")}
                  </p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  {t("otherCompetences")}
                </CardTitle>
              </CardHeader>
              <CardContent data-testid="employee-competences-other-list">
                {competenceOverview && competenceOverview.other.length > 0 ? (
                  <div className="space-y-1.5">
                    {competenceOverview.other.map((row) => {
                      const tone =
                        row.percent !== null && row.percent >= 75
                          ? BADGE_COLOR.green
                          : row.percent !== null && row.percent >= 50
                            ? BADGE_COLOR.yellow
                            : BADGE_COLOR.red;
                      return (
                        <div
                          key={row.competence_id}
                          className="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
                          data-testid={`employee-competences-other-row-${row.competence_id}`}
                        >
                          <div className="flex flex-1 items-center gap-2 text-sm">
                            <span className="truncate">{row.competence_title}</span>
                            <Badge variant="secondary" className="shrink-0 text-xs">
                              {row.skill_level_title}
                            </Badge>
                          </div>
                          <div className="flex items-center gap-2">
                            {row.percent !== null ? (
                              <span
                                className={`rounded-md px-2 py-0.5 text-xs font-medium ${tone}`}
                              >
                                {row.percent}%
                              </span>
                            ) : (
                              <span className="text-sm text-muted-foreground">
                                —
                              </span>
                            )}
                            <EmployeeCompetenceBreakdown
                              competenceId={row.competence_id}
                              competenceTitle={row.competence_title}
                              breakdown={row.level_breakdown}
                              testIdPrefix="employee-competences-other-row"
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p className="py-4 text-center text-sm text-muted-foreground">
                    {t("noOtherCompetences")}
                  </p>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>

      {/* ================================================================= */}
      {/* Dialogs                                                            */}
      {/* ================================================================= */}

      {/* Edit employee dialog */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent data-testid="employee-modal-edit">
          <DialogHeader>
            <DialogTitle>{t("editEmployee")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label>{t("name")}</Label>
                <Input
                  data-testid="employee-modal-edit-input-first-name"
                  value={editForm.first_name}
                  onChange={(e) =>
                    setEditForm({ ...editForm, first_name: e.target.value })
                  }
                  maxLength={100}
                />
              </div>
              <div className="space-y-2">
                <Label>{t("lastName")}</Label>
                <Input
                  data-testid="employee-modal-edit-input-last-name"
                  value={editForm.last_name}
                  onChange={(e) =>
                    setEditForm({ ...editForm, last_name: e.target.value })
                  }
                  maxLength={100}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>{t("position")}</Label>
              <PositionCombobox
                value={editForm.position_id || null}
                onValueChange={(id) =>
                  setEditForm({ ...editForm, position_id: id || "" })
                }
              />
            </div>
            <div className="space-y-2">
              <Label>{t("division")}</Label>
              <Select
                value={editForm.division_id}
                onValueChange={(val) =>
                  setEditForm({ ...editForm, division_id: val })
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder={t("noDivision")}>
                    {(() => { if (!editForm.division_id) return undefined; const d = flatDivisions.find((d) => d.id === editForm.division_id); return d ? `${"—".repeat(d.depth)} ${d.name}` : undefined; })()}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">{t("noDivision")}</SelectItem>
                  {flatDivisions.map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {"—".repeat(d.depth)} {d.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t("status")}</Label>
              <Select
                value={editForm.status}
                onValueChange={(val) =>
                  setEditForm({ ...editForm, status: val })
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue>
                    {editForm.status
                      ? employeeStatusLabel(t, editForm.status)
                      : undefined}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {statusOptions.map((s) => (
                    <SelectItem key={s} value={s}>
                      {employeeStatusLabel(t, s)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setEditOpen(false)}
              disabled={saving}
            >
              {tc("cancel")}
            </Button>
            <Button
              data-testid="employee-modal-edit-btn-submit"
              onClick={handleEdit}
              disabled={saving}
            >
              {saving ? t("saving") : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add event dialog */}
      <Dialog open={eventOpen} onOpenChange={setEventOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("addEvent")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>{t("eventType")}</Label>
              <Select
                value={eventForm.event_type}
                onValueChange={(val) =>
                  setEventForm({ ...eventForm, event_type: val })
                }
              >
                <SelectTrigger className="w-full" data-testid="employee-events-select-type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {eventTypeOptions.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t("date")}</Label>
              <DatePicker
                value={eventForm.event_date}
                onChange={(value) =>
                  setEventForm({ ...eventForm, event_date: value })
                }
                data-testid="employee-events-input-date"
              />
            </div>
            <div className="space-y-2">
              <Label>{t("description")}</Label>
              <Textarea
                value={eventForm.description}
                onChange={(e) =>
                  setEventForm({ ...eventForm, description: e.target.value })
                }
                rows={3}
                placeholder={t("eventDescriptionPlaceholder")}
                data-testid="employee-events-input-description"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setEventOpen(false)}
              disabled={saving}
            >
              {tc("cancel")}
            </Button>
            <Button onClick={handleAddEvent} disabled={saving} data-testid="employee-events-btn-save">
              {saving ? t("adding") : t("addEvent")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* HRP-151: Current Employment dialog */}
      <Dialog open={weOpen} onOpenChange={setWeOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {weEditId ? t("weEditTitle") : t("weAddTitle")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>{t("division")} *</Label>
              <Select
                value={weForm.division_id}
                onValueChange={(val) =>
                  setWeForm({ ...weForm, division_id: val })
                }
              >
                <SelectTrigger data-testid="employee-experience-division">
                  <SelectValue placeholder={t("selectDivision")}>
                    {(value: string | null) => {
                      if (!value) return undefined;
                      const d = flatDivisions.find((dd) => dd.id === value);
                      return d ? d.name : undefined;
                    }}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {flatDivisions.map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {d.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t("position")} *</Label>
              <PositionCombobox
                value={weForm.position_id || null}
                onValueChange={(positionId) =>
                  setWeForm({ ...weForm, position_id: positionId || "" })
                }
                data-testid="employee-experience-position"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("startDate")} *</Label>
                <DatePicker
                  value={weForm.start_date}
                  onChange={(value) =>
                    setWeForm({ ...weForm, start_date: value })
                  }
                  max={weForm.end_date || undefined}
                  data-testid="employee-experience-start-date"
                />
              </div>
              <div className="space-y-2">
                <Label>{t("endDate")}</Label>
                <DatePicker
                  value={weForm.end_date}
                  onChange={(value) =>
                    setWeForm({ ...weForm, end_date: value })
                  }
                  min={weForm.start_date || undefined}
                  data-testid="employee-experience-end-date"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>{t("description")}</Label>
              <Textarea
                value={weForm.description}
                onChange={(e) =>
                  setWeForm({ ...weForm, description: e.target.value })
                }
                rows={3}
                placeholder={t("weDescriptionPlaceholder")}
              />
            </div>
            {weError && (
              <p
                className="text-sm text-destructive"
                data-testid="employee-experience-error"
              >
                {weError}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setWeOpen(false)}
              disabled={saving}
            >
              {tc("cancel")}
            </Button>
            <Button
              onClick={handleWeSave}
              disabled={saving}
              data-testid="employee-experience-btn-save"
            >
              {saving ? t("saving") : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Previous Employment dialog */}
      <Dialog open={peOpen} onOpenChange={setPeOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {peEditId ? t("peEditTitle") : t("peAddTitle")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>{t("companyName")} *</Label>
              <Input
                value={peForm.company_name}
                onChange={(e) =>
                  setPeForm({ ...peForm, company_name: e.target.value })
                }
                data-testid="employee-prev-emp-company"
              />
            </div>
            <div className="space-y-2">
              <Label>{t("position")} *</Label>
              <Input
                value={peForm.position}
                onChange={(e) =>
                  setPeForm({ ...peForm, position: e.target.value })
                }
                data-testid="employee-prev-emp-position"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("startDate")} *</Label>
                <DatePicker
                  value={peForm.start_date}
                  onChange={(value) =>
                    setPeForm({ ...peForm, start_date: value })
                  }
                  max={peForm.end_date || yesterdayIso()}
                  data-testid="employee-prev-emp-start-date"
                />
              </div>
              <div className="space-y-2">
                <Label>{t("endDate")} *</Label>
                <DatePicker
                  value={peForm.end_date}
                  onChange={(value) =>
                    setPeForm({ ...peForm, end_date: value })
                  }
                  min={peForm.start_date || undefined}
                  max={yesterdayIso()}
                  data-testid="employee-prev-emp-end-date"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>{t("description")}</Label>
              <Textarea
                value={peForm.description}
                onChange={(e) =>
                  setPeForm({ ...peForm, description: e.target.value })
                }
                rows={3}
              />
            </div>
            {peError && (
              <p
                className="text-sm text-destructive"
                data-testid="employee-prev-emp-error"
              >
                {peError}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setPeOpen(false)}
              disabled={saving}
            >
              {tc("cancel")}
            </Button>
            <Button
              onClick={handlePeSave}
              disabled={saving}
              data-testid="employee-prev-emp-btn-save"
            >
              {saving ? t("saving") : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Education dialog */}
      <Dialog open={eduOpen} onOpenChange={setEduOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {eduEditId ? t("eduEditTitle") : t("eduAddTitle")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>{t("institution")} *</Label>
              <Input
                value={eduForm.institution}
                onChange={(e) =>
                  setEduForm({ ...eduForm, institution: e.target.value })
                }
                placeholder={t("institutionPlaceholder")}
                data-testid="employee-edu-institution"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("degree")} *</Label>
                <Select
                  value={eduForm.degree}
                  onValueChange={(val) =>
                    setEduForm({ ...eduForm, degree: val })
                  }
                >
                  <SelectTrigger className="w-full" data-testid="employee-edu-degree">
                    <SelectValue placeholder={t("selectDegree")} />
                  </SelectTrigger>
                  <SelectContent>
                    {degreeOptions.map((d) => (
                      <SelectItem key={d} value={d}>
                        {d}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{t("fieldOfStudy")} *</Label>
                <Input
                  value={eduForm.field_of_study}
                  onChange={(e) =>
                    setEduForm({ ...eduForm, field_of_study: e.target.value })
                  }
                  placeholder={t("fieldOfStudyPlaceholder")}
                  data-testid="employee-edu-field"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("startDate")} *</Label>
                <DatePicker
                  value={eduForm.start_date}
                  onChange={(value) =>
                    setEduForm({ ...eduForm, start_date: value })
                  }
                  max={eduForm.end_date || undefined}
                  data-testid="employee-edu-start-date"
                />
              </div>
              <div className="space-y-2">
                <Label>{t("endDate")}</Label>
                <DatePicker
                  value={eduForm.end_date}
                  onChange={(value) =>
                    setEduForm({ ...eduForm, end_date: value })
                  }
                  min={eduForm.start_date || undefined}
                  data-testid="employee-edu-end-date"
                />
              </div>
            </div>
            {eduError && (
              <p
                className="text-sm text-destructive"
                data-testid="employee-edu-error"
              >
                {eduError}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setEduOpen(false)}
              disabled={saving}
            >
              {tc("cancel")}
            </Button>
            <Button
              onClick={handleEduSave}
              disabled={saving}
              data-testid="employee-edu-btn-save"
            >
              {saving ? t("saving") : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Compensation dialog (GF5) */}
      <Dialog open={compOpen} onOpenChange={setCompOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {compEditId ? t("compEditTitle") : t("compAddTitle")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("colType")}</Label>
                <Select
                  value={compForm.type}
                  onValueChange={(val) => setCompForm({ ...compForm, type: val })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue>
                      {compForm.type === "salary"
                        ? t("compTypeSalary")
                        : compForm.type === "bonus"
                          ? t("compTypeBonus")
                          : compForm.type === "allowance"
                            ? t("compTypeAllowance")
                            : ""}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="salary">{t("compTypeSalary")}</SelectItem>
                    <SelectItem value="bonus">{t("compTypeBonus")}</SelectItem>
                    <SelectItem value="allowance">
                      {t("compTypeAllowance")}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{t("currency")}</Label>
                <Select
                  value={compForm.currency}
                  onValueChange={(val) => setCompForm({ ...compForm, currency: val })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  {/* HRP-439: the installation's currency leads the list;
                      the codes themselves are machine-readable and stay
                      untranslated. */}
                  <SelectContent>
                    {getCurrencyOptions().map((code) => (
                      <SelectItem key={code} value={code}>
                        {code}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-2">
              <Label>{t("amount")}</Label>
              <Input
                type="number"
                step="0.01"
                min="0"
                value={compForm.amount}
                onChange={(e) => setCompForm({ ...compForm, amount: e.target.value })}
                placeholder={t("amountPlaceholder")}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("effectiveDate")} *</Label>
                <DatePicker
                  value={compForm.effective_date}
                  onChange={(value) =>
                    setCompForm({ ...compForm, effective_date: value })
                  }
                  max={compForm.end_date || undefined}
                  data-testid="employee-compensation-effective-date"
                />
              </div>
              <div className="space-y-2">
                <Label>{t("endDate")}</Label>
                <DatePicker
                  value={compForm.end_date}
                  onChange={(value) =>
                    setCompForm({ ...compForm, end_date: value })
                  }
                  min={compForm.effective_date || undefined}
                  data-testid="employee-compensation-end-date"
                />
              </div>
            </div>
            {compForm.effective_date &&
              compForm.end_date &&
              compForm.end_date < compForm.effective_date && (
                <p className="text-sm text-destructive">
                  {t("errorCompEndAfterEffective")}
                </p>
              )}
            <div className="space-y-2">
              <Label>{t("notes")}</Label>
              <Textarea
                value={compForm.notes}
                onChange={(e) => setCompForm({ ...compForm, notes: e.target.value })}
                rows={2}
                placeholder={t("notesPlaceholder")}
              />
            </div>
            {compError && (
              <p
                className="text-sm text-destructive"
                data-testid="employee-compensation-error"
              >
                {compError}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCompOpen(false)} disabled={saving}>
              {tc("cancel")}
            </Button>
            <Button
              onClick={handleCompSave}
              disabled={
                saving ||
                !compForm.amount ||
                !compForm.effective_date ||
                (!!compForm.end_date && compForm.end_date < compForm.effective_date)
              }
            >
              {saving ? t("saving") : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Course dialog */}
      <Dialog open={courseOpen} onOpenChange={setCourseOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {courseEditId ? t("courseEditTitle") : t("courseAddTitle")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>{t("colTitle")} *</Label>
              <Input
                value={courseForm.title}
                onChange={(e) =>
                  setCourseForm({ ...courseForm, title: e.target.value })
                }
                placeholder={t("courseTitlePlaceholder")}
                data-testid="employee-course-title"
              />
            </div>
            <div className="space-y-2">
              <Label>{t("provider")}</Label>
              <Input
                value={courseForm.provider}
                onChange={(e) =>
                  setCourseForm({ ...courseForm, provider: e.target.value })
                }
                placeholder={t("courseProviderPlaceholder")}
              />
            </div>
            <div className="space-y-2">
              <Label>{t("certificateUrl")}</Label>
              <Input
                value={courseForm.certificate_url}
                onChange={(e) =>
                  setCourseForm({
                    ...courseForm,
                    certificate_url: e.target.value,
                  })
                }
                placeholder="https://..."
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("completedDate")} *</Label>
                <DatePicker
                  value={courseForm.completed_date}
                  onChange={(value) =>
                    setCourseForm({ ...courseForm, completed_date: value })
                  }
                  max={courseForm.expiry_date || yesterdayIso()}
                  data-testid="employee-course-completed-date"
                />
              </div>
              <div className="space-y-2">
                <Label>{t("expiryDate")}</Label>
                <DatePicker
                  value={courseForm.expiry_date}
                  onChange={(value) =>
                    setCourseForm({ ...courseForm, expiry_date: value })
                  }
                  min={courseForm.completed_date || undefined}
                  data-testid="employee-course-expiry-date"
                />
              </div>
            </div>
            {competenceTree.length > 0 && (
              <div className="space-y-2">
                <Label>{t("competencesDeveloped")}</Label>
                <CompetenceTreePicker
                  tree={competenceTree}
                  selectedIds={new Set(courseCompetenceIds)}
                  onChange={(next) => setCourseCompetenceIds(Array.from(next))}
                  testIdPrefix="employee-course-competence-tree"
                />
              </div>
            )}
            {courseError && (
              <p
                className="text-sm text-destructive"
                data-testid="employee-course-error"
              >
                {courseError}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setCourseOpen(false)}
              disabled={saving}
            >
              {tc("cancel")}
            </Button>
            <Button onClick={handleCourseSave} disabled={saving}>
              {saving ? t("saving") : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
