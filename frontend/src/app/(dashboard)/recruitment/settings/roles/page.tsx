"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, Lock } from "lucide-react";
import { RecruitmentBreadcrumbs } from "@/components/recruitment";

type Role = {
  code: string;
  name: string;
  description: string;
  permissions: { code: string; description: string }[];
};

export default function RolesPage() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get<Role[]>("/recruitment/settings/roles");
      setRoles(data);
    } catch {
      setRoles([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-5" data-testid="recruitment-roles-page">
      <RecruitmentBreadcrumbs
        segments={[
          { label: "Settings", href: "/recruitment/settings" },
          { label: "Roles" },
        ]}
      />
      <header className="flex items-start justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Recruitment roles
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Read-only view of each role&apos;s permissions. Permission editing
            is part of global RBAC and will ship as a separate feature.
          </p>
        </div>
        <Badge variant="outline" className="gap-1">
          <Lock className="size-3" /> Read-only
        </Badge>
      </header>

      {loading ? (
        <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
          <Loader2 className="mr-2 size-4 animate-spin" />
          Loading…
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {roles.map((role) => (
            <Card key={role.code} data-testid={`role-card-${role.code}`}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">{role.name}</CardTitle>
                <p className="text-xs text-muted-foreground">
                  {role.description}
                </p>
              </CardHeader>
              <CardContent>
                <ul className="space-y-1 text-xs">
                  {role.permissions.map((perm) => (
                    <li key={perm.code}>
                      <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                        {perm.code}
                      </code>{" "}
                      <span className="text-muted-foreground">
                        — {perm.description}
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
