"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import type { TenantInfo, User } from "@/lib/types";
import {
  fetchCurrentUser,
  fetchUserTenants,
  isAuthenticated,
  logout,
  switchTenant as doSwitchTenant,
} from "@/lib/auth";

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
      const [u, t] = await Promise.all([
        fetchCurrentUser(),
        fetchUserTenants(),
      ]);
      setUser(u);
      setTenants(t);
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

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-muted-foreground">Loading...</div>
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
