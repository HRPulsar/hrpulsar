import { RequireRole } from "@/components/require-role";

// HRP-1045: the LLM provider credentials stay the admin role's, as every
// call behind the page does — the looser settings layout must not open it.
export default function LlmProvidersLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <RequireRole admin>{children}</RequireRole>;
}
