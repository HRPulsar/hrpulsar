"use client";

// O8-b: "I already use this" - the company names the agent it runs for
// this step and it lands in the (otherwise headless) agent registry, which
// is what turns "an agent type could do this" into "we automated it".
// Shown on the Coverage row, in the agent guide and on the To do tab.
//
// HRP-1199: the agents named before are offered first, so the next step
// does not ask for the same name again. Picking one binds it to this step:
// an agent is matched to a step by codes, so the step's codes are added to
// that agent - a second agent with the same name would be refused (the
// registry keeps names unique) and would split one tool in two.
//
// HRP-1182 (QA 20.11): a link, so it reads as something to click, and what it
// opens is a window over the page, not a form pushing the row apart.

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { type RegisteredAgent, workApi } from "@/lib/api/work";

type Overrides = RegisteredAgent["primitive_overrides"];

/** The agent's overrides with the step's missing codes added, or null when
 * the agent covers them already. One entry per code: a "remove" of a code
 * the step needs gives way to an "add". */
export function coverOverrides(agent: RegisteredAgent, codes: string[]): Overrides | null {
  const have = new Set(agent.effective_primitive_codes);
  const missing = [...new Set(codes)].filter((code) => !have.has(code));
  if (missing.length === 0) return null;
  return [
    ...agent.primitive_overrides.filter((o) => !missing.includes(o.code)),
    ...missing.map((code) => ({ code, mode: "add" as const })),
  ];
}

export function RegisterAgentInline({
  packId,
  codes,
  packManual = false,
  testId,
  onRegistered,
}: {
  packId: string;
  /** Every code of the step (or the steps) the agent is named for. */
  codes: string[];
  /** HRP-863: the company named this pack on the step. Such a step is
   * matched to an agent of that pack only, whatever its codes - so only
   * those are offered. */
  packManual?: boolean;
  /** Prefix: the window is `${testId}-dialog`, its input `${testId}-input`,
   * the submit `${testId}-save`, a known agent `${testId}-agent-${id}`. */
  testId: string;
  onRegistered: () => void;
}) {
  const t = useTranslations("coverage");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [agents, setAgents] = useState<RegisteredAgent[]>([]);

  // Asked on every open; an answer that lands after Cancel, a reopen or
  // the row going away is dropped.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    workApi
      .listAgents()
      .then(({ items }) => {
        if (!cancelled) setAgents(items.filter((a) => !packManual || a.pack_id === packId));
      })
      // No list (no right to read the registry, a network blip): the field
      // for a new name is still there.
      .catch(() => {
        if (!cancelled) setAgents([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, packId, packManual]);

  async function run(action: () => Promise<string>) {
    setSaving(true);
    try {
      toast.success(await action());
      setOpen(false);
      setName("");
      onRegistered();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function bind(agent: RegisteredAgent): Promise<string> {
    // Read fresh, not from the list: the overrides are written whole.
    // ponytail: read-modify-write of one agent's overrides; two people
    // binding the same agent in the same second may lose one add - a
    // server-side "add codes" call if that ever shows up.
    const fresh = await workApi.getAgent(agent.id);
    const next = coverOverrides(fresh, codes);
    if (next) await workApi.setAgentPrimitives(agent.id, next);
    return t("agentLinked");
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    const known = agents.find((a) => a.name.toLowerCase() === trimmed.toLowerCase());
    void run(async () => {
      if (known) return bind(known);
      await workApi.registerAgent({ name: trimmed, pack_id: packId });
      return t("agentRegistered");
    });
  }

  return (
    <>
      <Button
        size="sm"
        variant="link"
        className="h-auto p-0 underline"
        onClick={() => setOpen(true)}
        data-testid={testId}
      >
        {t("useAgent")}
      </Button>
      {open && (
        <Dialog open onOpenChange={(next) => !next && setOpen(false)}>
          <DialogContent className="sm:max-w-md" data-testid={`${testId}-dialog`}>
            <DialogHeader>
              <DialogTitle>{t("useAgentTitle")}</DialogTitle>
            </DialogHeader>
            {agents.length > 0 && (
              <div className="flex flex-wrap items-center gap-2" data-testid={`${testId}-known`}>
                <span className="text-sm text-muted-foreground">{t("agentPickExisting")}</span>
                {agents.map((agent) => (
                  <Button
                    key={agent.id}
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={saving}
                    onClick={() => void run(() => bind(agent))}
                    data-testid={`${testId}-agent-${agent.id}`}
                  >
                    {agent.name}
                  </Button>
                ))}
              </div>
            )}
            <form onSubmit={submit} className="grid gap-4">
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t("agentNamePlaceholder")}
                maxLength={200}
                autoFocus
                data-testid={`${testId}-input`}
              />
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                  {t("cancel")}
                </Button>
                <Button type="submit" disabled={saving || !name.trim()} data-testid={`${testId}-save`}>
                  {t("registerAgent")}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
