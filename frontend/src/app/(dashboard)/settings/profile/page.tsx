"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useAuth } from "@/context/auth-context";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { formatDate } from "@/lib/date-format";
import { getAvailableLocales, getDefaultLocale, localeLabel } from "@/lib/locale";

/** Sentinel select value for "no personal choice" — sent as null so the
 * backend falls back to the tenant/deployment default. */
const DEFAULT_LANGUAGE = "default";

export default function ProfilePage() {
  const { user, refresh } = useAuth();
  const t = useTranslations("settings");
  const tc = useTranslations("common");

  const [profileForm, setProfileForm] = useState({
    first_name: user?.first_name || "",
    last_name: user?.last_name || "",
    language: user?.language || DEFAULT_LANGUAGE,
  });
  const [profileSaving, setProfileSaving] = useState(false);

  const availableLocales = getAvailableLocales();
  const inheritedLocale = user?.tenant_default_locale || getDefaultLocale();

  const [avatarUploading, setAvatarUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function handleAvatarUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      toast.error(t("avatarNotImage"));
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      toast.error(t("avatarTooLarge"));
      return;
    }
    setAvatarUploading(true);
    try {
      await api.upload<User>("/auth/avatar", file);
      toast.success(t("avatarUpdated"));
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("avatarUploadFailed"));
    } finally {
      setAvatarUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleRemoveAvatar() {
    setAvatarUploading(true);
    try {
      await api.delete("/auth/avatar");
      toast.success(t("avatarRemoved"));
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("avatarRemoveFailed"));
    } finally {
      setAvatarUploading(false);
    }
  }

  const [passwordForm, setPasswordForm] = useState({
    current_password: "",
    new_password: "",
    confirm_password: "",
  });
  const [passwordSaving, setPasswordSaving] = useState(false);

  async function handleProfileUpdate() {
    setProfileSaving(true);
    try {
      await api.put<User>("/auth/me", {
        first_name: profileForm.first_name,
        last_name: profileForm.last_name,
        language:
          profileForm.language === DEFAULT_LANGUAGE ? null : profileForm.language,
      });
      toast.success(t("profileUpdated"));
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("profileUpdateFailed"));
    } finally {
      setProfileSaving(false);
    }
  }

  async function handleChangePassword() {
    if (passwordForm.new_password !== passwordForm.confirm_password) {
      toast.error(t("passwordsDoNotMatch"));
      return;
    }
    if (passwordForm.new_password.length < 8) {
      toast.error(t("passwordTooShort"));
      return;
    }
    setPasswordSaving(true);
    try {
      await api.post("/auth/change-password", {
        current_password: passwordForm.current_password,
        new_password: passwordForm.new_password,
      });
      toast.success(t("passwordChanged"));
      setPasswordForm({ current_password: "", new_password: "", confirm_password: "" });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("passwordChangeFailed"));
    } finally {
      setPasswordSaving(false);
    }
  }

  if (!user) return null;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{tc("settings")}</h1>
        <p className="text-sm text-muted-foreground">{t("manageAccount")}</p>
      </div>

      {/* Profile info */}
      <Card>
        <CardHeader>
          <CardTitle>{t("profileTitle")}</CardTitle>
          <CardDescription>{t("profileDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-4">
            <div className="relative group">
              <Avatar size="lg" className="h-16 w-16 text-xl" data-testid="settings-profile-avatar">
                {user.avatar_url && <AvatarImage src={user.avatar_url} />}
                <AvatarFallback className="bg-accent text-accent-foreground text-xl font-semibold">
                  {user.first_name[0] ?? ""}{user.last_name[0] ?? ""}
                </AvatarFallback>
              </Avatar>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={handleAvatarUpload}
              />
              <div className="absolute inset-0 flex items-center justify-center rounded-full bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
                   data-testid="settings-profile-btn-upload-avatar"
                   onClick={() => fileInputRef.current?.click()}>
                <span className="text-white text-xs font-medium">
                  {avatarUploading ? "..." : t("avatarEdit")}
                </span>
              </div>
            </div>
            <div>
              <p className="font-medium">{user.first_name} {user.last_name}</p>
              <p className="text-sm text-muted-foreground">{user.email}</p>
              <div className="mt-1 flex items-center gap-2">
                <div className="flex gap-1">
                  {user.roles.map((role) => (
                    <Badge key={role} variant="secondary" className="text-xs">{role}</Badge>
                  ))}
                </div>
                {user.avatar_url && (
                  <button
                    onClick={handleRemoveAvatar}
                    disabled={avatarUploading}
                    data-testid="settings-profile-btn-remove-avatar"
                    className="text-xs text-muted-foreground hover:text-destructive transition-colors"
                  >
                    {t("removePhoto")}
                  </button>
                )}
              </div>
            </div>
          </div>

          <div className="grid gap-4 pt-2 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>{t("firstName")}</Label>
              <Input
                data-testid="settings-profile-input-firstname"
                value={profileForm.first_name}
                onChange={(e) => setProfileForm({ ...profileForm, first_name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>{t("lastName")}</Label>
              <Input
                data-testid="settings-profile-input-lastname"
                value={profileForm.last_name}
                onChange={(e) => setProfileForm({ ...profileForm, last_name: e.target.value })}
              />
            </div>
            {availableLocales.length > 1 && (
              <div className="space-y-2">
                <Label>{t("language")}</Label>
                <Select
                  value={profileForm.language}
                  onValueChange={(v) => setProfileForm({ ...profileForm, language: v })}
                >
                  <SelectTrigger
                    className="w-full"
                    data-testid="settings-profile-select-language"
                  >
                    {/* Radix renders the raw value until the portal
                        content mounts — pass the label explicitly. */}
                    <SelectValue>
                      {profileForm.language === DEFAULT_LANGUAGE
                        ? t("languageDefault", {
                            locale: localeLabel(inheritedLocale),
                          })
                        : localeLabel(profileForm.language)}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={DEFAULT_LANGUAGE}>
                      {t("languageDefault", {
                        locale: localeLabel(inheritedLocale),
                      })}
                    </SelectItem>
                    {availableLocales.map((locale) => (
                      <SelectItem key={locale} value={locale}>
                        {localeLabel(locale)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {t("languageHint")}
                </p>
              </div>
            )}
          </div>

          <div className="flex justify-end">
            <Button
              size="sm"
              data-testid="settings-profile-btn-save"
              onClick={handleProfileUpdate}
              disabled={profileSaving || (!profileForm.first_name.trim() && !profileForm.last_name.trim())}
            >
              {profileSaving ? t("saving") : t("saveChanges")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Change password */}
      <Card>
        <CardHeader>
          <CardTitle>{t("changePassword")}</CardTitle>
          <CardDescription>{t("changePasswordDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>{t("currentPassword")}</Label>
            <Input
              type="password"
              data-testid="settings-password-input-current"
              value={passwordForm.current_password}
              onChange={(e) => setPasswordForm({ ...passwordForm, current_password: e.target.value })}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>{t("newPassword")}</Label>
              <Input
                type="password"
                data-testid="settings-password-input-new"
                value={passwordForm.new_password}
                onChange={(e) => setPasswordForm({ ...passwordForm, new_password: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>{t("confirmNewPassword")}</Label>
              <Input
                type="password"
                data-testid="settings-password-input-confirm"
                value={passwordForm.confirm_password}
                onChange={(e) => setPasswordForm({ ...passwordForm, confirm_password: e.target.value })}
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">{t("passwordMinLength")}</p>

          <div className="flex justify-end">
            <Button
              size="sm"
              data-testid="settings-password-btn-submit"
              onClick={handleChangePassword}
              disabled={passwordSaving || !passwordForm.current_password || !passwordForm.new_password || !passwordForm.confirm_password}
            >
              {passwordSaving ? t("changing") : t("changePassword")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Account info */}
      <Card>
        <CardHeader>
          <CardTitle>{t("accountTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-muted-foreground">{t("email")}</p>
              <p className="font-medium" data-testid="settings-profile-info-email">{user.email}</p>
            </div>
            <div>
              <p className="text-muted-foreground">{t("accountId")}</p>
              <p className="font-mono text-xs">{user.id}</p>
            </div>
            <div>
              <p className="text-muted-foreground">{t("tenantId")}</p>
              <p className="font-mono text-xs">{user.tenant_id}</p>
            </div>
            <div>
              <p className="text-muted-foreground">{t("memberSince")}</p>
              <p className="font-medium">{formatDate(user.created_at)}</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
