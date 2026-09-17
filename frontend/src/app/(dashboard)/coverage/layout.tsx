"use client";

// HRP-810: open to the section's roles and to anyone who reads a process.
// Anyone else following a direct link is bounced to the dashboard with the
// permission toast, like the admin pages - the API would answer 404 anyway.
import { RequireRole } from "@/components/require-role";

export default function CoverageLayout({ children }: { children: React.ReactNode }) {
  return <RequireRole coverage>{children}</RequireRole>;
}
