"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardDescription,
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
import { CompanyTabs } from "@/components/company/company-tabs";
import { usePermissions } from "@/hooks/use-permissions";

const COMPANY_SIZES = [
  "1-10",
  "11-50",
  "51-200",
  "201-500",
  "501-1000",
  "1001-5000",
  "5000+",
];

const NO_SIZE = "__none__";

interface CompanyProfile {
  id: string;
  name: string;
  slug: string;
  industry: string | null;
  company_size: string | null;
  website: string | null;
  description: string | null;
  logo_file_id: string | null;
  logo_url: string | null;
}

export default function CompanyProfilePage() {
  const { canAdminister } = usePermissions();
  const [profile, setProfile] = useState<CompanyProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [logoBusy, setLogoBusy] = useState(false);
  const [logoUrlInput, setLogoUrlInput] = useState("");
  const [logoDragging, setLogoDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [form, setForm] = useState({
    industry: "",
    company_size: "",
    website: "",
    description: "",
  });

  async function load() {
    try {
      const data = await api.get<CompanyProfile>("/settings/company-profile");
      setProfile(data);
      setForm({
        industry: data.industry ?? "",
        company_size: data.company_size ?? "",
        website: data.website ?? "",
        description: data.description ?? "",
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load profile");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function save() {
    setSaving(true);
    try {
      const payload = {
        industry: form.industry.trim() || null,
        company_size: form.company_size || null,
        website: form.website.trim() || null,
        description: form.description.trim() || null,
      };
      const data = await api.put<CompanyProfile>(
        "/settings/company-profile",
        payload,
      );
      setProfile(data);
      toast.success("Company profile saved");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function uploadLogoFile(file: File) {
    if (!file.type.startsWith("image/")) {
      toast.error("Please select an image file");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      toast.error("Image must be under 5 MB");
      return;
    }
    setLogoBusy(true);
    try {
      const data = await api.upload<CompanyProfile>(
        "/settings/company-profile/logo",
        file,
      );
      setProfile(data);
      toast.success("Logo updated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to upload logo");
    } finally {
      setLogoBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleLogoUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    await uploadLogoFile(file);
  }

  async function handleLogoFromUrl() {
    const url = logoUrlInput.trim();
    if (!url) {
      toast.error("Paste an image URL first");
      return;
    }
    setLogoBusy(true);
    try {
      const data = await api.post<CompanyProfile>(
        "/settings/company-profile/logo/from-url",
        { url },
      );
      setProfile(data);
      setLogoUrlInput("");
      toast.success("Logo updated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to fetch logo");
    } finally {
      setLogoBusy(false);
    }
  }

  function handleLogoDragOver(e: React.DragEvent) {
    if (readOnly || logoBusy) return;
    e.preventDefault();
    if (!logoDragging) setLogoDragging(true);
  }

  function handleLogoDragLeave(e: React.DragEvent) {
    e.preventDefault();
    setLogoDragging(false);
  }

  async function handleLogoDrop(e: React.DragEvent) {
    if (readOnly || logoBusy) return;
    e.preventDefault();
    setLogoDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) await uploadLogoFile(file);
  }

  async function handleLogoRemove() {
    setLogoBusy(true);
    try {
      const data = await api.delete<CompanyProfile>(
        "/settings/company-profile/logo",
      );
      setProfile(data);
      toast.success("Logo removed");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to remove logo");
    } finally {
      setLogoBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Company</h1>
          <p className="text-sm text-muted-foreground">Organization structure</p>
        </div>
        <CompanyTabs />
        <p className="py-8 text-center text-sm text-muted-foreground">Loading...</p>
      </div>
    );
  }

  const readOnly = !canAdminister;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Company</h1>
        <p className="text-sm text-muted-foreground">Organization structure</p>
      </div>

      <CompanyTabs />

      <div className="mx-auto max-w-2xl space-y-6">
        <Card data-testid="company-profile-card-logo">
          <CardHeader>
            <CardTitle className="text-base">Logo</CardTitle>
            <CardDescription>
              Shown on the public company page and in invitations.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div
              className={`flex items-center gap-4 rounded-md border-2 border-dashed p-3 transition-colors ${
                logoDragging
                  ? "border-primary bg-primary/5"
                  : "border-transparent"
              }`}
              onDragOver={handleLogoDragOver}
              onDragLeave={handleLogoDragLeave}
              onDrop={handleLogoDrop}
              data-testid="company-profile-logo-dropzone"
            >
              <div className="flex h-20 w-20 items-center justify-center overflow-hidden rounded-md border bg-muted/30">
                {profile?.logo_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={profile.logo_url}
                    alt="Company logo"
                    className="h-full w-full object-contain"
                    data-testid="company-profile-logo-preview"
                  />
                ) : (
                  <span className="text-xs text-muted-foreground">No logo</span>
                )}
              </div>
              <div className="flex flex-col gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/svg+xml,image/webp"
                  className="hidden"
                  onChange={handleLogoUpload}
                  data-testid="company-profile-input-logo"
                />
                <div className="flex gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={readOnly || logoBusy}
                    data-testid="company-profile-btn-upload-logo"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    {logoBusy ? "Working..." : profile?.logo_url ? "Replace" : "Upload"}
                  </Button>
                  {profile?.logo_url && (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={readOnly || logoBusy}
                      data-testid="company-profile-btn-remove-logo"
                      onClick={handleLogoRemove}
                    >
                      Remove
                    </Button>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">
                  PNG, JPEG, SVG, WebP — up to 5 MB. Drag &amp; drop or paste a URL below.
                </p>
              </div>
            </div>
            <div className="mt-4 flex gap-2">
              <Input
                type="url"
                placeholder="https://…/logo.png"
                value={logoUrlInput}
                disabled={readOnly || logoBusy}
                onChange={(e) => setLogoUrlInput(e.target.value)}
                data-testid="company-profile-input-logo-url"
              />
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={readOnly || logoBusy || !logoUrlInput.trim()}
                onClick={handleLogoFromUrl}
                data-testid="company-profile-btn-logo-from-url"
              >
                Import URL
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card data-testid="company-profile-card-fields">
          <CardHeader>
            <CardTitle className="text-base">Profile</CardTitle>
            <CardDescription>
              Used by AI generation, the public company page, and team invitations.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="company-profile-description">Description</Label>
              <Textarea
                id="company-profile-description"
                rows={4}
                placeholder="What does your company do? (helps AI pick relevant competences)"
                value={form.description}
                disabled={readOnly}
                onChange={(e) =>
                  setForm({ ...form, description: e.target.value })
                }
                data-testid="company-profile-input-description"
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="company-profile-industry">Industry</Label>
                <Input
                  id="company-profile-industry"
                  placeholder="e.g. Software, Manufacturing"
                  value={form.industry}
                  disabled={readOnly}
                  onChange={(e) => setForm({ ...form, industry: e.target.value })}
                  data-testid="company-profile-input-industry"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="company-profile-size">Company size</Label>
                <Select
                  value={form.company_size || NO_SIZE}
                  onValueChange={(v) =>
                    setForm({ ...form, company_size: v === NO_SIZE ? "" : v })
                  }
                  disabled={readOnly}
                >
                  <SelectTrigger
                    id="company-profile-size"
                    className="w-full"
                    data-testid="company-profile-input-size"
                  >
                    <SelectValue placeholder="Select size" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_SIZE}>Not specified</SelectItem>
                    {COMPANY_SIZES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s} employees
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="company-profile-website">Website</Label>
              <Input
                id="company-profile-website"
                type="url"
                placeholder="https://company.com"
                value={form.website}
                disabled={readOnly}
                onChange={(e) => setForm({ ...form, website: e.target.value })}
                data-testid="company-profile-input-website"
              />
            </div>

            {!readOnly && (
              <div className="flex justify-end pt-2">
                <Button
                  size="sm"
                  onClick={save}
                  disabled={saving}
                  data-testid="company-profile-btn-save"
                >
                  {saving ? "Saving..." : "Save changes"}
                </Button>
              </div>
            )}
            {readOnly && (
              <p className="text-xs text-muted-foreground">
                Only admins can edit the company profile.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
