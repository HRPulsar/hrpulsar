"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { getBrandName } from "@/lib/brand";
import type { Division } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import {
  Building2,
  GitBranch,
  Users,
  BookOpen,
  Check,
  ArrowRight,
  ArrowLeft,
} from "lucide-react";

const COMPANY_SIZES = [
  "1-10",
  "11-50",
  "51-200",
  "201-500",
  "501-1000",
  "1001-5000",
  "5000+",
];

const STEPS = [
  { title: "Company Info", icon: Building2 },
  { title: "First Division", icon: GitBranch },
  { title: "Invite Team", icon: Users },
  { title: "Competences", icon: BookOpen },
];

interface OnboardingStatus {
  needs_onboarding: boolean;
  onboarding_completed: boolean;
  employee_count: number;
  division_count: number;
  has_invitations: boolean;
}

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Step 1: Company Info
  const [companyForm, setCompanyForm] = useState({
    industry: "",
    company_size: "",
    website: "",
    description: "",
  });

  // Step 2: Division
  const [divisionName, setDivisionName] = useState("");
  const [divisionDesc, setDivisionDesc] = useState("");
  const [createdDivisions, setCreatedDivisions] = useState<Division[]>([]);

  // Step 3: Invitations
  const [inviteEmails, setInviteEmails] = useState<string[]>([""]);
  const [sentCount, setSentCount] = useState(0);

  // Check if onboarding is needed
  useEffect(() => {
    async function check() {
      try {
        const status = await api.get<OnboardingStatus>("/onboarding/status");
        if (!status.needs_onboarding) {
          router.replace("/dashboard");
          return;
        }
      } catch {
        router.replace("/dashboard");
        return;
      } finally {
        setLoading(false);
      }
    }
    check();
  }, [router]);

  // Step 1: Save company profile
  async function saveCompanyInfo() {
    setSaving(true);
    try {
      const payload: Record<string, string | null> = {};
      if (companyForm.industry) payload.industry = companyForm.industry;
      if (companyForm.company_size) payload.company_size = companyForm.company_size;
      if (companyForm.website) payload.website = companyForm.website;
      if (companyForm.description) payload.description = companyForm.description;

      if (Object.keys(payload).length > 0) {
        await api.put("/settings/company-profile", payload);
        toast.success("Company info saved");
      }
      setStep(1);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  // Step 2: Create division
  async function createDivision() {
    if (!divisionName.trim()) {
      setStep(2);
      return;
    }
    setSaving(true);
    try {
      const div = await api.post<Division>("/divisions", {
        name: divisionName.trim(),
        description: divisionDesc.trim() || null,
      });
      setCreatedDivisions((prev) => [...prev, div]);
      setDivisionName("");
      setDivisionDesc("");
      toast.success(`Division "${div.name}" created`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create division");
    } finally {
      setSaving(false);
    }
  }

  // Step 3: Send invitations
  async function sendInvitations() {
    const emails = inviteEmails.filter((e) => e.trim());
    if (emails.length === 0) {
      setStep(3);
      return;
    }
    setSaving(true);
    let sent = 0;
    for (const email of emails) {
      try {
        await api.post("/invitations", { email: email.trim(), role_code: "employee" });
        sent++;
      } catch {
        // skip failed
      }
    }
    setSentCount(sent);
    if (sent > 0) toast.success(`${sent} invitation${sent > 1 ? "s" : ""} sent`);
    setSaving(false);
    setStep(3);
  }

  // Complete onboarding
  async function completeOnboarding() {
    setSaving(true);
    try {
      await api.post("/onboarding/complete");
      toast.success("Setup complete!");
      router.replace("/dashboard");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to complete setup");
    } finally {
      setSaving(false);
    }
  }

  // Skip entire wizard
  async function skipOnboarding() {
    await completeOnboarding();
  }

  const updateInviteEmail = useCallback(
    (index: number, value: string) => {
      setInviteEmails((prev) => {
        const next = [...prev];
        next[index] = value;
        return next;
      });
    },
    [],
  );

  function addEmailField() {
    setInviteEmails((prev) => [...prev, ""]);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        Loading...
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6 py-8">
      <div className="text-center">
        <h1 className="text-2xl font-semibold tracking-tight">
          Welcome to {getBrandName()}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Let&apos;s set up your organization in a few quick steps
        </p>
      </div>

      {/* Step indicator */}
      <div className="flex items-center justify-center gap-2">
        {STEPS.map((s, i) => {
          const Icon = s.icon;
          const isActive = i === step;
          const isDone = i < step;
          return (
            <div key={s.title} className="flex items-center gap-2">
              {i > 0 && (
                <div
                  className={`h-px w-8 ${isDone ? "bg-primary" : "bg-border"}`}
                />
              )}
              <div
                data-testid={`onboarding-step-${i}`}
                className={`flex h-8 w-8 items-center justify-center rounded-full text-xs ${
                  isDone
                    ? "bg-primary text-primary-foreground"
                    : isActive
                      ? "border-2 border-primary text-primary"
                      : "border border-border text-muted-foreground"
                }`}
              >
                {isDone ? <Check className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
              </div>
            </div>
          );
        })}
      </div>

      {/* Step content */}
      <Card data-testid="onboarding-form">
        <CardHeader>
          <CardTitle className="text-lg">
            {STEPS[step].title}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {step === 0 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Tell us about your company so we can tailor the experience.
              </p>
              <div className="space-y-2">
                <Label>Industry</Label>
                <Input
                  placeholder="e.g. Technology, Healthcare, Finance"
                  value={companyForm.industry}
                  onChange={(e) =>
                    setCompanyForm({ ...companyForm, industry: e.target.value })
                  }
                />
              </div>
              <div className="space-y-2">
                <Label>Company size</Label>
                <Select
                  value={companyForm.company_size}
                  onValueChange={(val) =>
                    setCompanyForm({ ...companyForm, company_size: val })
                  }
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Select size" />
                  </SelectTrigger>
                  <SelectContent>
                    {COMPANY_SIZES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s} employees
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Website (optional)</Label>
                <Input
                  placeholder="https://company.com"
                  value={companyForm.website}
                  onChange={(e) =>
                    setCompanyForm({ ...companyForm, website: e.target.value })
                  }
                />
              </div>
              <div className="space-y-2">
                <Label>Description (optional)</Label>
                <Textarea
                  placeholder="Brief description of your company"
                  value={companyForm.description}
                  onChange={(e) =>
                    setCompanyForm({ ...companyForm, description: e.target.value })
                  }
                  rows={3}
                />
              </div>
              <div className="flex justify-between pt-2">
                <Button variant="ghost" onClick={skipOnboarding} disabled={saving}>
                  Skip setup
                </Button>
                <Button onClick={saveCompanyInfo} disabled={saving} data-testid="onboarding-btn-next">
                  {saving ? "Saving..." : "Next"}
                  <ArrowRight className="ml-1 h-4 w-4" />
                </Button>
              </div>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Create your first department or division. You can add more later.
              </p>
              {createdDivisions.length > 0 && (
                <div className="space-y-1">
                  <Label className="text-muted-foreground">Created</Label>
                  {createdDivisions.map((d) => (
                    <div
                      key={d.id}
                      className="flex items-center gap-2 rounded-md bg-muted/50 px-3 py-1.5 text-sm"
                    >
                      <Check className="h-3.5 w-3.5 text-green-600" />
                      {d.name}
                    </div>
                  ))}
                </div>
              )}
              <div className="space-y-2">
                <Label>Division name</Label>
                <Input
                  placeholder="e.g. Engineering, Marketing, HR"
                  value={divisionName}
                  onChange={(e) => setDivisionName(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label>Description (optional)</Label>
                <Input
                  placeholder="What this division does"
                  value={divisionDesc}
                  onChange={(e) => setDivisionDesc(e.target.value)}
                />
              </div>
              <div className="flex items-center justify-between pt-2">
                <Button variant="outline" onClick={() => setStep(0)} disabled={saving} data-testid="onboarding-btn-back">
                  <ArrowLeft className="mr-1 h-4 w-4" />
                  Back
                </Button>
                <div className="flex gap-2">
                  {divisionName.trim() && (
                    <Button variant="outline" onClick={createDivision} disabled={saving}>
                      {saving ? "Creating..." : "Add & create another"}
                    </Button>
                  )}
                  <Button
                    onClick={async () => {
                      if (divisionName.trim()) await createDivision();
                      setStep(2);
                    }}
                    disabled={saving}
                    data-testid="onboarding-btn-next"
                  >
                    {saving ? "Creating..." : "Next"}
                    <ArrowRight className="ml-1 h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Invite team members by email. They&apos;ll receive an invitation
                to join your organization.
              </p>
              {inviteEmails.map((email, i) => (
                <div key={i} className="space-y-2">
                  <Label>{i === 0 ? "Email addresses" : ""}</Label>
                  <Input
                    type="email"
                    placeholder="colleague@company.com"
                    value={email}
                    onChange={(e) => updateInviteEmail(i, e.target.value)}
                  />
                </div>
              ))}
              <Button
                variant="ghost"
                size="sm"
                onClick={addEmailField}
                className="text-muted-foreground"
              >
                + Add another
              </Button>
              <div className="flex items-center justify-between pt-2">
                <Button variant="outline" onClick={() => setStep(1)} disabled={saving} data-testid="onboarding-btn-back">
                  <ArrowLeft className="mr-1 h-4 w-4" />
                  Back
                </Button>
                <Button
                  onClick={async () => {
                    await sendInvitations();
                  }}
                  disabled={saving}
                  data-testid="onboarding-btn-next"
                >
                  {saving
                    ? "Sending..."
                    : inviteEmails.some((e) => e.trim())
                      ? "Send & next"
                      : "Skip"}
                  <ArrowRight className="ml-1 h-4 w-4" />
                </Button>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Choose how to set up competences for your organization.
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={() => {
                    completeOnboarding();
                    router.replace("/competences");
                  }}
                  className="rounded-lg border p-4 text-left transition-colors hover:bg-muted/50"
                >
                  <BookOpen className="mb-2 h-5 w-5 text-primary" />
                  <div className="font-medium">Browse & import</div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Choose from the built-in competence library
                  </p>
                </button>
                <button
                  type="button"
                  onClick={completeOnboarding}
                  className="rounded-lg border p-4 text-left transition-colors hover:bg-muted/50"
                >
                  <Users className="mb-2 h-5 w-5 text-primary" />
                  <div className="font-medium">Set up later</div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Go to the dashboard and configure competences when ready
                  </p>
                </button>
              </div>
              {sentCount > 0 && (
                <p className="text-sm text-muted-foreground">
                  {sentCount} invitation{sentCount > 1 ? "s" : ""} sent successfully.
                </p>
              )}
              <div className="flex items-center justify-between pt-2">
                <Button variant="outline" onClick={() => setStep(2)} disabled={saving} data-testid="onboarding-btn-back">
                  <ArrowLeft className="mr-1 h-4 w-4" />
                  Back
                </Button>
                <Button onClick={completeOnboarding} disabled={saving} data-testid="onboarding-btn-finish">
                  {saving ? "Finishing..." : "Finish setup"}
                  <Check className="ml-1 h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
