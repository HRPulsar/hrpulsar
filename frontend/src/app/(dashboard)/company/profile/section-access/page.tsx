"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Hint } from "@/components/ui/hint";
import { RequireRole } from "@/components/require-role";
import { navigation } from "@/components/sidebar";
import { useAuth } from "@/context/auth-context";
import {
  type MatrixLevel,
  type SectionAccess,
  type SectionAccessSection,
  sectionAccessApi,
} from "@/lib/api/section-access";
import { cn } from "@/lib/utils";
// HRP-820: the role→sidebar-key map already exists for exactly this job
// (role-management screen) — reuse it instead of a local duplicate.
import { SYSTEM_ROLE_KEYS } from "@/lib/user-role-label";

const LEVELS: MatrixLevel[] = ["none", "view", "manage"];
const LEVEL_KEYS: Record<MatrixLevel, string> = {
  none: "sectionAccessLevelNone",
  view: "sectionAccessLevelView",
  manage: "sectionAccessLevelManage",
};

// HRP-998: every account holds the employee baseline (HRP-832) and a
// caller's level is their strongest role's, so the Employee column is the
// floor of every other role in its row - a level below it does nothing.
const BASELINE_ROLE = "employee";

function sectionLabelKey(code: string): string | undefined {
  return navigation.find((item) => item.id === code)?.labelKey;
}

export default function SectionAccessPage() {
  const t = useTranslations("company");
  const tSidebar = useTranslations("sidebar");
  const tc = useTranslations("common");
  const { refresh } = useAuth();
  const [data, setData] = useState<SectionAccess | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await sectionAccessApi.get());
    } catch {
      toast.error(t("toastSectionAccessLoadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  function patchSection(code: string, patch: Partial<SectionAccessSection>) {
    setData((d) =>
      d
        ? { ...d, sections: d.sections.map((s) => (s.code === code ? { ...s, ...patch } : s)) }
        : d,
    );
  }

  async function save() {
    if (!data) return;
    setSaving(true);
    try {
      const saved = await sectionAccessApi.update({
        sections: data.sections.map((s) => ({ code: s.code, hidden: s.hidden, levels: s.levels })),
      });
      setData(saved);
      toast.success(t("toastSectionAccessSaved"));
      // The admin's own sidebar/section gate read /auth/me — refresh it so
      // a section this save just opened or closed applies without a hard
      // reload. A refresh hiccup must not turn a successful save into an
      // error toast, so it's swallowed here rather than in the outer catch.
      try {
        await refresh();
      } catch {
        // best-effort — the next navigation re-reads /auth/me anyway
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastSaveFailed"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <RequireRole admin>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight" data-testid="section-access-title">
            {t("sectionAccess")}
          </h1>
          <p className="text-sm text-muted-foreground">{t("sectionAccessHint")}</p>
          <p
            className="text-sm text-muted-foreground"
            data-testid="section-access-employee-floor"
          >
            {t("sectionAccessEmployeeFloor")}
          </p>
          <Link
            href="/company/profile"
            className="text-sm text-accent hover:underline"
            data-testid="section-access-link-back"
          >
            {t("sectionAccessBack")}
          </Link>
        </div>

        {loading || !data ? (
          <div className="py-12 text-center text-muted-foreground">{tc("loading")}</div>
        ) : (
          <>
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full text-sm" data-testid="section-access-table">
                <thead className="bg-muted/40 text-left">
                  <tr>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t("sectionAccessColumnSection")}
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t("sectionAccessColumnHidden")}
                    </th>
                    {data.roles.map((role) => (
                      <th key={role} scope="col" className="px-3 py-2 font-medium">
                        {tSidebar(SYSTEM_ROLE_KEYS[role] ?? role)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.sections.map((section) => {
                    const labelKey = sectionLabelKey(section.code);
                    const sectionLabel = labelKey ? tSidebar(labelKey) : section.code;
                    return (
                      <tr
                        key={section.code}
                        className="border-t"
                        data-testid={`section-access-row-${section.code}`}
                      >
                        <th
                          scope="row"
                          className={cn(
                            "px-3 py-2 text-left font-medium",
                            section.hidden && "opacity-50",
                          )}
                        >
                          {sectionLabel}
                        </th>
                        <td className="px-3 py-2">
                          <span className="inline-flex items-center gap-1.5">
                            <Checkbox
                              checked={section.hidden}
                              disabled={section.never_hidden}
                              aria-label={`${t("sectionAccessColumnHidden")} — ${sectionLabel}`}
                              onCheckedChange={(checked) =>
                                patchSection(section.code, { hidden: checked === true })
                              }
                              data-testid={`section-access-hidden-${section.code}`}
                            />
                            {section.never_hidden && <Hint text={t("sectionAccessCannotHide")} />}
                          </span>
                        </td>
                        {data.roles.map((role) => {
                          const locked = section.admin_locked && role === "admin";
                          const roleLabel = tSidebar(SYSTEM_ROLE_KEYS[role] ?? role);
                          const floor =
                            role === BASELINE_ROLE
                              ? 0
                              : LEVELS.indexOf(section.levels[BASELINE_ROLE]);
                          const belowFloor = LEVELS.indexOf(section.levels[role]) < floor;
                          return (
                            <td
                              key={role}
                              className={cn("px-3 py-2", section.hidden && "opacity-50")}
                            >
                              <span className="inline-flex items-center gap-1.5">
                                <select
                                  className={cn(
                                    "h-8 rounded-md border bg-background px-2 text-sm",
                                    locked && "opacity-50",
                                  )}
                                  aria-label={`${sectionLabel} — ${roleLabel}`}
                                  value={section.levels[role]}
                                  disabled={locked || section.hidden}
                                  onChange={(e) =>
                                    patchSection(section.code, {
                                      levels: { ...section.levels, [role]: e.target.value as MatrixLevel },
                                    })
                                  }
                                  data-testid={`section-access-select-${section.code}-${role}`}
                                >
                                  {LEVELS.map((level, rank) => (
                                    <option key={level} value={level} disabled={rank < floor}>
                                      {t(LEVEL_KEYS[level])}
                                    </option>
                                  ))}
                                </select>
                                {locked && <Hint text={t("sectionAccessLockedAdmin")} />}
                                {belowFloor && !section.hidden && (
                                  <Hint
                                    text={t("sectionAccessBelowEmployee", {
                                      level: t(LEVEL_KEYS[section.levels[BASELINE_ROLE]]),
                                    })}
                                    data-testid={`section-access-below-employee-${section.code}-${role}`}
                                  />
                                )}
                              </span>
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Button onClick={save} disabled={saving} data-testid="section-access-btn-save">
              {saving ? t("saving") : t("saveChanges")}
            </Button>
          </>
        )}
      </div>
    </RequireRole>
  );
}
