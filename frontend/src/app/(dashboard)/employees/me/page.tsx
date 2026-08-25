"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { Employee } from "@/lib/types";

/**
 * HRP-624: "My profile" without the UI having to learn its own employee id.
 * The route resolves the id through `GET /employees/me` and hands over to the
 * regular card, so every deep link, breadcrumb and refresh keeps working on
 * the canonical `/employees/{id}` URL.
 */
export default function MyProfilePage() {
  const router = useRouter();
  const t = useTranslations("employees");
  const tc = useTranslations("common");
  // A workspace owner invited without an employee row is an ordinary case:
  // the backend answers 404 employee_profile_not_found and we say so.
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Employee>("/employees/me")
      .then((emp) => router.replace(`/employees/${emp.id}`))
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : t("notFound")),
      );
  }, [router, t]);

  return (
    <div
      className="py-12 text-center text-sm text-muted-foreground"
      data-testid="employees-me-status"
    >
      {error ?? tc("loading")}
    </div>
  );
}
