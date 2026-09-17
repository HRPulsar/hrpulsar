"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { RequireRole } from "@/components/require-role";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { type ContainerType, workApi } from "@/lib/api/work";

const TYPES: ContainerType[] = ["process", "initiative"];

function NewContainerForm() {
  const t = useTranslations("coverage");
  const router = useRouter();
  const params = useSearchParams();
  const preset = params.get("type");
  const [type, setType] = useState<ContainerType>(
    preset === "initiative" ? "initiative" : "process",
  );
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [goal, setGoal] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setSaving(true);
    try {
      const created = await workApi.createContainer({
        type,
        title: title.trim(),
        description: description.trim() || null,
        goal: goal.trim() || null,
      });
      router.push(`/coverage/${created.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="max-w-2xl space-y-5" data-testid="coverage-form">
      <h1 className="text-2xl font-semibold">{t("newTitle")}</h1>
      <p className="text-sm text-muted-foreground">{t("newText")}</p>

      <div className="space-y-1.5">
        <Label htmlFor="coverage-type">{t("fieldType")}</Label>
        <Select value={type} onValueChange={(v) => setType((v as ContainerType) ?? "process")}>
          <SelectTrigger id="coverage-type" className="w-full" data-testid="coverage-select-type">
            <SelectValue>{t(`type_${type}`)}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {TYPES.map((v) => (
              <SelectItem key={v} value={v} data-testid={`coverage-select-type-${v}`}>
                <span className="flex flex-col gap-0.5">
                  <span>{t(`type_${v}`)}</span>
                  <span className="text-xs text-muted-foreground">{t(`typeHint_${v}`)}</span>
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="coverage-title">{t("fieldTitle")}</Label>
        <Input
          id="coverage-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={300}
          required
          data-testid="coverage-input-title"
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="coverage-description">{t("fieldDescription")}</Label>
        <Textarea
          id="coverage-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={8}
          placeholder={t("descriptionPlaceholder")}
          data-testid="coverage-textarea-description"
        />
        <p className="text-xs text-muted-foreground">{t("descriptionHint")}</p>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="coverage-goal">{t("fieldGoal")}</Label>
        <Textarea
          id="coverage-goal"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          rows={2}
          data-testid="coverage-textarea-goal"
        />
      </div>

      <div className="flex gap-2">
        <Button type="submit" disabled={saving || !title.trim()} data-testid="coverage-btn-submit">
          {t("saveAndContinue")}
        </Button>
        <Button type="button" variant="outline" onClick={() => router.push("/coverage")}>
          {t("cancel")}
        </Button>
      </div>
    </form>
  );
}

export default function NewContainerPage() {
  // HRP-810: a reader of one process opens the section, not this form.
  return (
    <RequireRole coverageManage>
      <Suspense fallback={null}>
        <NewContainerForm />
      </Suspense>
    </RequireRole>
  );
}
