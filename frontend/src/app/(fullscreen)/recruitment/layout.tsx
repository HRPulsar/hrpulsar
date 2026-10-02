import { RequireSection } from "@/components/require-section";

// HRP-830: the fullscreen shell has no SectionGate of its own - the canvas
// follows the recruitment section like the dashboard pages do.
export default function FullscreenRecruitmentLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <RequireSection code="recruitment">{children}</RequireSection>;
}
