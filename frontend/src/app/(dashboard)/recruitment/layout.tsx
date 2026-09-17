import { RecruitmentOnboardingBanner } from "@/components/recruitment/onboarding-banner";
import { RequireRole } from "@/components/require-role";

// HRP-622: every recruitment route (requisitions, candidates, interviews,
// reports, settings, audit log) is behind RECRUITMENT_VIEWER_ROLES on the
// API. Without this gate a bookmarked deep link rendered the shell for
// anyone and turned into a cascade of 403 toasts instead of the standard
// "no permission" bounce.
export default function RecruitmentLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <RequireRole recruit>
      <RecruitmentOnboardingBanner />
      {children}
    </RequireRole>
  );
}
