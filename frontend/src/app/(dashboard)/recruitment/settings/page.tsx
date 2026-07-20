import Link from "next/link";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { RecruitmentBreadcrumbs, RecruitmentTabs } from "@/components/recruitment";
import {
  Activity,
  FileText,
  Globe2,
  Image as ImageIcon,
  ListChecks,
  Mic,
  Ruler,
  ScrollText,
  ShieldCheck,
  UsersRound,
} from "lucide-react";

const TILES = [
  {
    href: "/recruitment/settings/scales",
    label: "Rating scales",
    description: "Configure scales (1–5, 1–10) and level labels",
    icon: Ruler,
    testId: "rec-settings-card-scales",
  },
  {
    href: "/recruitment/settings/llm-providers",
    label: "LLM providers",
    description: "Anthropic, OpenAI, Gemini, Yandex, GigaChat (BYOK)",
    icon: Globe2,
    testId: "rec-settings-card-llm",
  },
  {
    href: "/recruitment/settings/transcription-providers",
    label: "Transcription",
    description: "Whisper, Deepgram, AssemblyAI, faster-whisper",
    icon: Mic,
    testId: "rec-settings-card-stt",
  },
  {
    href: "/recruitment/settings/branding",
    label: "Branding",
    description: "Logo, accent colors, report watermark",
    icon: ImageIcon,
    testId: "rec-settings-card-branding",
  },
  {
    href: "/recruitment/settings/retention",
    label: "Data retention",
    description: "Retention periods for resumes, interviews, consents, reports",
    icon: ShieldCheck,
    testId: "rec-settings-card-retention",
  },
  {
    href: "/recruitment/settings/roles",
    label: "Roles",
    description: "Permissions for recruiter / hiring_manager / hr / hrd",
    icon: UsersRound,
    testId: "rec-settings-card-roles",
  },
  {
    href: "/recruitment/settings/report-templates",
    label: "Report templates",
    description: "Sections included in the vacancy XLSX report",
    icon: FileText,
    testId: "rec-settings-card-report-templates",
  },
  {
    href: "/recruitment/settings/consent-templates",
    label: "Consent templates",
    description: "Consent text for personal data processing and interview recording",
    icon: ScrollText,
    testId: "rec-settings-card-consent-templates",
  },
  {
    href: "/recruitment/audit-log",
    label: "Audit log",
    description: "All mutating actions in the recruitment module",
    icon: Activity,
    testId: "rec-settings-card-audit",
  },
];

export default function RecruitmentSettingsHubPage() {
  return (
    <div className="space-y-5" data-testid="recruitment-settings-hub">
      <RecruitmentBreadcrumbs segments={[{ label: "Settings" }]} />
      <RecruitmentTabs />
      <header>
        <h1 className="text-xl font-semibold tracking-tight">
          Recruitment settings
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          A single hub for recruitment module settings: scales, AI and
          transcription providers, report branding, data retention policy, audit
          log.
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {TILES.map((tile) => {
          const Icon = tile.icon;
          return (
            <Card
              key={tile.href}
              className="transition-colors hover:border-[var(--rec-accent,theme(colors.cyan.500))]"
              data-testid={tile.testId}
            >
              <CardHeader className="flex-row items-start gap-3 space-y-0 pb-2">
                <div className="rounded-lg bg-cyan-50 p-2 text-cyan-600 dark:bg-cyan-950/40 dark:text-cyan-300">
                  <Icon className="size-4" />
                </div>
                <div className="space-y-0.5">
                  <CardTitle className="text-sm">{tile.label}</CardTitle>
                  <CardDescription className="text-xs">
                    {tile.description}
                  </CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                <Link
                  href={tile.href}
                  className="text-xs font-medium text-cyan-700 underline-offset-2 hover:underline"
                >
                  Open →
                </Link>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Card className="bg-muted/40">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <ListChecks className="size-4" />
            What else can be configured?
          </CardTitle>
        </CardHeader>
        <CardContent className="text-xs text-muted-foreground">
          GDPR export and data erasure for a candidate are available on the
          candidate page → &ldquo;GDPR&rdquo; tab. The stage funnel is configured
          inside each vacancy.
        </CardContent>
      </Card>
    </div>
  );
}
