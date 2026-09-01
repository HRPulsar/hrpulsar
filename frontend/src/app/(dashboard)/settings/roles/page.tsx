"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { Role } from "@/lib/types";
import { RequireRole } from "@/components/require-role";
import { FALLBACK_ROLE_CODE, SYSTEM_ROLE_KEYS } from "@/lib/user-role-label";
import { Badge } from "@/components/ui/badge";
import { BADGE_COLOR } from "@/lib/badge-tones";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Hint } from "@/components/ui/hint";

// HRP-634: what each role can really do. The `permissions` rows the API also
// returns are seeded but dead — no gate reads a `Permission.codename`, access
// resolves through `require_role` on the role code — so printing them would
// claim a recruiter can do nothing while they run the whole hiring surface.
// These strings mirror docs/core/docs/rbac.md instead.
const CAPABILITY_KEYS: Record<string, string> = {
  platform_admin: "rolesCapPlatformAdmin",
  admin: "rolesCapAdmin",
  hr: "rolesCapHr",
  manager: "rolesCapManager",
  recruiter: "rolesCapRecruiter",
  hiring_manager: "rolesCapHiringManager",
  employee: "rolesCapEmployee",
};

/** Where the holder count drills down to.
 *
 * The employee list's `?role=` filter is plain membership — the same set the
 * counter counts — with one exception: `employee` there means "holds *only*
 * the baseline" (a membership test would return the whole workspace, since
 * every account carries it). That is a different question from "who holds
 * this role", so the baseline row drills down to the unfiltered list, which
 * is the honest answer to "everyone".
 */
function holdersHref(code: string): string {
  return code === FALLBACK_ROLE_CODE
    ? "/employees"
    : `/employees?role=${encodeURIComponent(code)}`;
}

/** Seeded roles strongest first; tenant-custom roles follow, alphabetically. */
const ROLE_ORDER = [
  "platform_admin",
  "admin",
  "hr",
  "manager",
  "recruiter",
  "hiring_manager",
  "employee",
];

function rank(code: string): number {
  const i = ROLE_ORDER.indexOf(code);
  return i === -1 ? ROLE_ORDER.length : i;
}

export default function RolesPage() {
  return (
    <RequireRole admin>
      <RolesPageContent />
    </RequireRole>
  );
}

function RolesPageContent() {
  const t = useTranslations("settings");
  const tSections = useTranslations("sections");
  const tSidebar = useTranslations("sidebar");
  const [roles, setRoles] = useState<Role[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api
      .get<Role[]>("/roles")
      .then((r) =>
        setRoles(
          [...r].sort(
            (a, b) => rank(a.code) - rank(b.code) || a.code.localeCompare(b.code),
          ),
        ),
      )
      .catch(() => setFailed(true));
  }, []);

  return (
    <div className="space-y-6" data-testid="roles-page">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("rolesTitle")}
          </h1>
          <Hint text={tSections("roles.hint")} data-testid="roles-hint-title" />
        </div>
        <p className="text-sm text-muted-foreground">{t("rolesSubtitle")}</p>
      </div>

      <Card>
        <CardContent className="pt-6">
          {failed ? (
            <p className="text-sm text-muted-foreground">
              {t("rolesLoadFailed")}
            </p>
          ) : roles === null ? (
            <p className="text-sm text-muted-foreground">{t("rolesLoading")}</p>
          ) : (
            <Table data-testid="roles-table">
              <TableHeader>
                <TableRow>
                  <TableHead>{t("rolesColRole")}</TableHead>
                  <TableHead>{t("rolesColCan")}</TableHead>
                  <TableHead className="w-[110px] text-right">
                    {t("rolesColHolders")}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {roles.map((role) => {
                  const nameKey = SYSTEM_ROLE_KEYS[role.code];
                  const capKey = CAPABILITY_KEYS[role.code];
                  return (
                    <TableRow key={role.id} data-testid={`roles-row-${role.code}`}>
                      <TableCell className="align-top">
                        <div className="font-medium">
                          {nameKey ? tSidebar(nameKey) : role.name}
                        </div>
                        <div className="mt-1 flex items-center gap-2">
                          <code className="text-xs text-muted-foreground">
                            {role.code}
                          </code>
                          <Badge
                            className={
                              role.is_system
                                ? BADGE_COLOR.neutral
                                : BADGE_COLOR.blue
                            }
                          >
                            {role.is_system
                              ? t("rolesKindSystem")
                              : t("rolesKindCustom")}
                          </Badge>
                        </div>
                      </TableCell>
                      <TableCell className="align-top text-sm text-muted-foreground">
                        {capKey
                          ? t(capKey)
                          : role.description || t("rolesCapCustom")}
                      </TableCell>
                      <TableCell className="align-top text-right tabular-nums">
                        <Link
                          href={holdersHref(role.code)}
                          data-testid={`roles-count-${role.code}`}
                          title={t("rolesHoldersLink")}
                          className="rounded underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          {role.user_count ?? 0}
                        </Link>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
          {roles !== null && !failed && (
            // Everyone keeps the baseline `employee` role alongside whatever
            // else they hold, so the column sums past the headcount — say so
            // rather than let it read as a broken counter.
            <p className="mt-4 text-xs text-muted-foreground">
              {t("rolesHoldersHint")}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
