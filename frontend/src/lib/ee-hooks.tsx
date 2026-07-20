/**
 * Enterprise hooks and providers.
 *
 * Community edition stubs — all functions are no-ops.
 * Monorepo ee-hooks.tsx contains the full enterprise version;
 * sync script swaps this file in for the public repo.
 */

/** Analytics provider wrapper — no-op in community */
export function EEProvider({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

/** Track analytics event — no-op in community */
export function useEEAnalytics() {
  return {
    track: (_event: string, _props?: Record<string, unknown>) => { void _event; void _props; },
  };
}

/** Enterprise nav items — empty in community */
interface EENavItem {
  name: string;
  href: string;
  icon: React.ReactNode;
  requireAdmin?: boolean;
  requireManage?: boolean;
}

export function useEENavItems(_isAdmin: boolean): { items: EENavItem[]; credits: { total: number } | null } {
  void _isAdmin;
  return { items: [], credits: null };
}

/** Enterprise settings sections — empty in community */
export function useEESettings() {
  return [];
}
