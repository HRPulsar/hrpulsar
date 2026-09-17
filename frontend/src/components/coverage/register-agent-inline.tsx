"use client";

// O8-b: "I already use this" - the company names the agent it runs for
// this step and it lands in the (otherwise headless) agent registry, which
// is what turns "an agent type could do this" into "we automated it".
// Shown on the Coverage row and on the To do tab's second section.

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { workApi } from "@/lib/api/work";

export function RegisterAgentInline({
  packId,
  testId,
  onRegistered,
}: {
  packId: string;
  /** Prefix: the input is `${testId}-input`, the submit `${testId}-save`. */
  testId: string;
  onRegistered: () => void;
}) {
  const t = useTranslations("coverage");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setSaving(true);
    try {
      await workApi.registerAgent({ name: trimmed, pack_id: packId });
      toast.success(t("agentRegistered"));
      setOpen(false);
      setName("");
      onRegistered();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <Button
        size="sm"
        variant="link"
        className="h-auto p-0"
        onClick={() => setOpen(true)}
        data-testid={testId}
      >
        {t("useAgent")}
      </Button>
    );
  }

  return (
    <form onSubmit={submit} className="flex max-w-md gap-2">
      <Input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder={t("agentNamePlaceholder")}
        maxLength={200}
        autoFocus
        data-testid={`${testId}-input`}
      />
      <Button type="submit" size="sm" disabled={saving || !name.trim()} data-testid={`${testId}-save`}>
        {t("registerAgent")}
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>
        {t("cancel")}
      </Button>
    </form>
  );
}
