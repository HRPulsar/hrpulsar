"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { usePermissions } from "@/hooks/use-permissions";
import { toast } from "sonner";

interface RequireRoleProps {
  children: React.ReactNode;
  /** Require admin or manager role */
  manage?: boolean;
  /** Require admin role */
  admin?: boolean;
}

export function RequireRole({ children, manage, admin }: RequireRoleProps) {
  const { canManage, isAdmin } = usePermissions();
  const router = useRouter();

  const allowed = admin ? isAdmin : manage ? canManage : true;

  useEffect(() => {
    if (!allowed) {
      toast.error("You don't have permission to access this page");
      router.replace("/dashboard");
    }
  }, [allowed, router]);

  if (!allowed) return null;

  return <>{children}</>;
}
