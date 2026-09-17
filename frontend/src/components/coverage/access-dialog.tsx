"use client";

// HRP-810: who reads a process besides the section's managers. The owner
// and the managers set the visibility and the rules; only a manager hands
// the process to another owner. Every change lands in the history.

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { X } from "lucide-react";

import { PeopleSelectList } from "@/components/people-select-list";
import { PositionCombobox } from "@/components/position-combobox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  type AccessLogEntry,
  type AccessRule,
  type ContainerAccess,
  type ProcessPerson,
  RULE_ROLE_CODES,
  type RuleRoleCode,
  type Visibility,
  workApi,
} from "@/lib/api/work";
import { formatDateTime } from "@/lib/date-format";
import { SYSTEM_ROLE_KEYS } from "@/lib/user-role-label";

type RuleKind = "role" | "position" | "employee";
const KINDS: RuleKind[] = ["role", "position", "employee"];
const KIND_KEY: Record<RuleKind, string> = {
  role: "accessKindRole",
  position: "accessKindPosition",
  employee: "accessKindEmployee",
};
const VISIBILITIES: Visibility[] = ["company", "restricted"];
const VISIBILITY_KEY: Record<Visibility, string> = {
  company: "accessVisibilityCompany",
  restricted: "accessVisibilityRestricted",
};

function ruleKey(rule: AccessRule): string {
  if (rule.role_code) return `role-${rule.role_code}`;
  if (rule.position_id) return `position-${rule.position_id}`;
  return `employee-${rule.employee_id}`;
}

export function AccessDialog({
  containerId,
  canChangeOwner,
  onClose,
  onOwnerChanged,
}: {
  containerId: string;
  canChangeOwner: boolean;
  onClose: () => void;
  onOwnerChanged: () => void;
}) {
  const t = useTranslations("coverage");
  const tc = useTranslations("common");
  const tRole = useTranslations("sidebar");
  const [data, setData] = useState<ContainerAccess | null>(null);
  const [failed, setFailed] = useState(false);
  const [visibility, setVisibility] = useState<Visibility>("restricted");
  const [rules, setRules] = useState<AccessRule[]>([]);
  const [kind, setKind] = useState<RuleKind>("role");
  const [people, setPeople] = useState<ProcessPerson[] | null>(null);
  // HRP-728: a failed people call is an error with a retry, not the "no
  // match" empty state - the `people !== null` guard below would otherwise
  // never let the effect run again.
  const [peopleFailed, setPeopleFailed] = useState(false);
  // One box per picker: typing in the owner search used to filter the rule
  // picker as well, and the other way round.
  const [ownerSearch, setOwnerSearch] = useState("");
  const [ruleSearch, setRuleSearch] = useState("");
  const [pickOwner, setPickOwner] = useState(false);
  const [saving, setSaving] = useState(false);
  // Remounts the position picker after each add: it keeps the last pick.
  const [positionPickerKey, setPositionPickerKey] = useState(0);

  function apply(next: ContainerAccess) {
    setData(next);
    setVisibility(next.visibility);
    setRules(next.rules);
  }

  useEffect(() => {
    let cancelled = false;
    workApi
      .getAccess(containerId)
      .then((next) => !cancelled && apply(next))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [containerId]);

  // The employee list is loaded once, and only when a picker needs it.
  const needPeople = kind === "employee" || pickOwner;
  useEffect(() => {
    if (!needPeople || people !== null || peopleFailed) return;
    let cancelled = false;
    // The process's own list: the directory is scoped for a division head.
    workApi
      .listPeople(containerId)
      .then((res) => !cancelled && setPeople(res))
      .catch(() => !cancelled && setPeopleFailed(true));
    return () => {
      cancelled = true;
    };
  }, [needPeople, people, peopleFailed, containerId]);

  const rowsFor = useCallback(
    (query: string, onlyAssignable: boolean) => {
      const q = query.trim().toLowerCase();
      return (people ?? [])
        .filter((p) => !onlyAssignable || p.assignable)
        .filter(
          (p) =>
            !q ||
            [p.name, p.email, p.position_title].some((v) => v?.toLowerCase().includes(q)),
        )
        .map((p) => ({
          id: p.employee_id,
          name: p.name || p.email || p.employee_id,
          subtitle: p.position_title ?? p.email,
        }));
    },
    [people],
  );

  function roleLabel(code: string): string {
    const key = SYSTEM_ROLE_KEYS[code];
    return key ? tRole(key) : code;
  }

  function ruleLabel(rule: AccessRule): string {
    if (rule.role_code) return roleLabel(rule.role_code);
    // A person with no name on record still has to be readable - and
    // removable - so the chip falls back to what identifies them.
    return rule.label || rule.employee_id || rule.position_id || "";
  }

  function add(rule: AccessRule) {
    setRules((prev) => (prev.some((r) => ruleKey(r) === ruleKey(rule)) ? prev : [...prev, rule]));
  }

  async function save() {
    setSaving(true);
    try {
      apply(
        await workApi.setAccess(containerId, {
          visibility,
          rules: rules.map(({ role_code, position_id, employee_id }) => ({
            role_code,
            position_id,
            employee_id,
          })),
        }),
      );
      toast.success(t("accessSaved"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function changeOwner(employeeId: string) {
    const person = people?.find((p) => p.employee_id === employeeId);
    if (!person) return;
    setSaving(true);
    try {
      await workApi.updateContainer(containerId, { owner_id: person.user_id });
      // Owner and history only: visibility and rules may hold unsaved edits.
      setData(await workApi.getAccess(containerId));
      setPickOwner(false);
      onOwnerChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setSaving(false);
    }
  }

  function logLine(entry: AccessLogEntry): string {
    const payload = entry.payload ?? {};
    const to = payload.to === "company" || payload.to === "restricted" ? payload.to : null;
    const ownerName = (name: string | null | undefined) => name || t("accessOwnerNone");
    return t(`accessLog_${entry.action}`, {
      actor: entry.actor_name ?? t("accessSomeone"),
      to: entry.action === "owner_changed" ? ownerName(payload.to_name) : to ? t(VISIBILITY_KEY[to]) : "",
      from: ownerName(payload.from_name),
      label: payload.role_code ? roleLabel(payload.role_code) : (payload.label ?? ""),
    });
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-xl" data-testid="coverage-access-dialog">
        <DialogHeader>
          <DialogTitle>{t("accessTitle")}</DialogTitle>
          <DialogDescription>{t("accessText")}</DialogDescription>
        </DialogHeader>

        {failed ? (
          <p className="text-sm text-destructive">{tc("loadFailed")}</p>
        ) : !data ? (
          <p className="text-sm text-muted-foreground">{tc("loading")}</p>
        ) : (
          <div className="space-y-5">
            {peopleFailed && (
              <div className="flex flex-wrap items-center gap-2 text-sm text-destructive">
                <span>{tc("loadFailed")}</span>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setPeopleFailed(false)}
                  data-testid="coverage-access-people-retry"
                >
                  {tc("tryAgain")}
                </Button>
              </div>
            )}
            <section className="space-y-2">
              <Label>{t("accessOwner")}</Label>
              <div className="flex flex-wrap items-center gap-2" data-testid="coverage-access-owner">
                <span>{data.owner?.name || t("accessOwnerNone")}</span>
                {data.owner && !data.owner.active && (
                  <Badge variant="outline" data-testid="coverage-access-owner-inactive">
                    {t("accessOwnerInactive")}
                  </Badge>
                )}
                {canChangeOwner && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setPickOwner((v) => !v)}
                    data-testid="coverage-access-btn-owner"
                  >
                    {t("accessOwnerChange")}
                  </Button>
                )}
              </div>
              {pickOwner && (
                <>
                <Input
                  value={ownerSearch}
                  onChange={(e) => setOwnerSearch(e.target.value)}
                  placeholder={t("assignSearchPlaceholder")}
                  data-testid="coverage-access-owner-search"
                />
                <PeopleSelectList
                  // Only people at work can own a process, the same rule
                  // the executor picker follows.
                  rows={rowsFor(ownerSearch, true).map((row) => ({ ...row, disabled: saving }))}
                  isSelected={() => false}
                  onToggle={(id) => void changeOwner(id)}
                  loading={people === null && !peopleFailed}
                  loadingLabel={tc("loading")}
                  emptyLabel={peopleFailed ? tc("loadFailed") : t("assignNoMatch")}
                  className="max-h-56"
                  testId="coverage-access-owner-list"
                  rowTestId={(id) => `coverage-access-owner-option-${id}`}
                />
                </>
              )}
            </section>

            <section className="space-y-2">
              <Label>{t("accessVisibility")}</Label>
              <div className="flex gap-1" role="group" aria-label={t("accessVisibility")}>
                {VISIBILITIES.map((v) => (
                  <Button
                    key={v}
                    size="sm"
                    variant={visibility === v ? "default" : "outline"}
                    onClick={() => setVisibility(v)}
                    data-testid={`coverage-access-visibility-${v}`}
                  >
                    {t(VISIBILITY_KEY[v])}
                  </Button>
                ))}
              </div>
            </section>

            <section className="space-y-2">
              <Label>{t("accessRules")}</Label>
              {rules.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("accessRulesEmpty")}</p>
              ) : (
                <ul className="flex flex-wrap gap-2" data-testid="coverage-access-rules">
                  {rules.map((rule) => (
                    <li key={ruleKey(rule)}>
                      <Badge
                        variant="secondary"
                        className="gap-1"
                        data-testid={`coverage-access-rule-${ruleKey(rule)}`}
                      >
                        {ruleLabel(rule)}
                        <button
                          type="button"
                          aria-label={t("accessRemoveRule")}
                          onClick={() =>
                            setRules((prev) => prev.filter((r) => ruleKey(r) !== ruleKey(rule)))
                          }
                          data-testid={`coverage-access-rule-remove-${ruleKey(rule)}`}
                        >
                          <X className="size-3" />
                        </button>
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
              <div className="flex flex-wrap items-center gap-2">
                <Select value={kind} onValueChange={(v) => setKind((v as RuleKind) || "role")}>
                  <SelectTrigger className="w-40" data-testid="coverage-access-add-kind">
                    <SelectValue>{t(KIND_KEY[kind])}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {KINDS.map((k) => (
                      <SelectItem key={k} value={k} data-testid={`coverage-access-add-kind-${k}`}>
                        {t(KIND_KEY[k])}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {kind === "role" && (
                  <Select
                    value=""
                    onValueChange={(code) =>
                      code &&
                      add({ role_code: code as RuleRoleCode, position_id: null, employee_id: null })
                    }
                  >
                    <SelectTrigger className="w-48" data-testid="coverage-access-add-role">
                      <SelectValue placeholder={t("accessAddKind")} />
                    </SelectTrigger>
                    <SelectContent>
                      {RULE_ROLE_CODES.map((code) => (
                        <SelectItem key={code} value={code} data-testid={`coverage-access-add-role-${code}`}>
                          {roleLabel(code)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
                {kind === "position" && (
                  <PositionCombobox
                    key={positionPickerKey}
                    value={null}
                    allowCreate={false}
                    onValueChange={(id, title) => {
                      if (!id) return;
                      add({ role_code: null, position_id: id, employee_id: null, label: title });
                      setPositionPickerKey((k) => k + 1);
                    }}
                    data-testid="coverage-access-add-position"
                  />
                )}
              </div>
              {kind === "employee" && (
                <>
                  <Input
                    value={ruleSearch}
                    onChange={(e) => setRuleSearch(e.target.value)}
                    placeholder={t("assignSearchPlaceholder")}
                    data-testid="coverage-access-add-employee-search"
                  />
                  <PeopleSelectList
                    // Reading is not doing: someone who has left can still
                    // be named in a rule.
                    rows={rowsFor(ruleSearch, false)}
                    isSelected={(id) => rules.some((r) => r.employee_id === id)}
                    onToggle={(id) => {
                      // A checked box unchecks: the same rule the chip's X
                      // drops. Role and position rules have no employee_id.
                      if (rules.some((r) => r.employee_id === id)) {
                        setRules((prev) => prev.filter((r) => r.employee_id !== id));
                        return;
                      }
                      const person = people?.find((p) => p.employee_id === id);
                      add({
                        role_code: null,
                        position_id: null,
                        employee_id: id,
                        label: person?.name || person?.email || null,
                      });
                    }}
                    loading={people === null && !peopleFailed}
                    loadingLabel={tc("loading")}
                    emptyLabel={peopleFailed ? tc("loadFailed") : t("assignNoMatch")}
                    className="max-h-56"
                    testId="coverage-access-add-employee"
                    rowTestId={(id) => `coverage-access-add-employee-option-${id}`}
                  />
                </>
              )}
            </section>

            <section className="space-y-1" data-testid="coverage-access-history">
              <Label>{t("accessHistory")}</Label>
              {data.history.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("accessHistoryEmpty")}</p>
              ) : (
                <ul className="max-h-40 space-y-1 overflow-y-auto text-sm">
                  {data.history.map((entry, i) => (
                    <li key={`${entry.created_at}-${i}`} className="flex justify-between gap-3">
                      <span>{logLine(entry)}</span>
                      <span className="shrink-0 text-muted-foreground">
                        {formatDateTime(entry.created_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose} data-testid="coverage-access-btn-cancel">
            {t("cancel")}
          </Button>
          <Button
            disabled={!data || saving}
            onClick={() => void save()}
            data-testid="coverage-access-btn-save"
          >
            {t("accessSave")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
