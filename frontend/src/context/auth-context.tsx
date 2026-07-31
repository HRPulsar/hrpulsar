"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import type { TenantInfo, User } from "@/lib/types";
import {
  fetchCurrentUser,
  fetchUserTenants,
  isAuthenticated,
  logout,
  switchTenant as doSwitchTenant,
} from "@/lib/auth";
import {
  normalizeLocale,
  readLocaleCookie,
  setLocaleCookie,
} from "@/i18n/config";

interface AuthContextValue {
  user: User | null;
  tenants: TenantInfo[];
  loading: boolean;
  refresh: () => Promise<void>;
  switchTenant: (tenantId: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  tenants: [],
  loading: true,
  refresh: async () => {},
  switchTenant: async () => {},
  signOut: () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [tenants, setTenants] = useState<TenantInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const t = useTranslations("common");

  const refresh = useCallback(async () => {
    if (!isAuthenticated()) {
      setUser(null);
      setTenants([]);
      setLoading(false);
      document.cookie =
        "has_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
      router.replace("/login");
      return;
    }
    try {
      const [u, tenantList] = await Promise.all([
        fetchCurrentUser(),
        fetchUserTenants(),
      ]);
      setUser(u);
      setTenants(tenantList);
    } catch (err) {
      // Don't clear auth state on aborted fetches — when a client-side
      // navigation (router.push) tears down the current page mid-fetch,
      // Chromium rejects the in-flight request as a plain TypeError
      // "Failed to fetch" rather than the canonical AbortError. Either
      // shape just means "this caller went away", not "the user is
      // logged out", so we leave the auth state alone.
      const isAbort =
        (err instanceof DOMException && err.name === "AbortError") ||
        (err instanceof TypeError && /fetch/i.test(err.message));
      if (isAbort) return;
      setUser(null);
      setTenants([]);
      document.cookie =
        "has_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
      router.replace("/login");
    } finally {
      setLoading(false);
    }
  }, [router]);

  const switchTenant = useCallback(
    async (tenantId: string) => {
      await doSwitchTenant(tenantId);
      // Full page reload to reset all cached data for the new tenant
      window.location.href = "/dashboard";
    },
    [],
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  // i18n (F1): reconcile the account's language into the device cookie.
  // SSR resolves the locale from the NEXT_LOCALE cookie only (Bearer
  // auth — the server never sees the user), so once the user is known,
  // an account-level preference (User.language, else Tenant.default_locale)
  // that differs from the cookie wins: the choice follows the account
  // across devices. Users without an account preference keep the
  // cookie's Accept-Language-derived value. No loop: after the refresh
  // the cookie equals the preference, so the effect no-ops.
  useEffect(() => {
    if (!user) return;
    const desired = normalizeLocale(
      user.language || user.tenant_default_locale,
    );
    if (!desired) return;
    if (readLocaleCookie() === desired) return;
    setLocaleCookie(desired);
    router.refresh();
  }, [user, router]);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-muted-foreground">{t("loading")}</div>
      </div>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <AuthContext.Provider
      value={{ user, tenants, loading, refresh, switchTenant, signOut: logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
