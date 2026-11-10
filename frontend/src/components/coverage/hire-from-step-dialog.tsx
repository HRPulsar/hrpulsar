"use client";

// W6 (§5.9): open a hire need for one step straight from its Coverage
// row, without a detour through the To do tab. Three routes, one call -
// the same create_hire_need the tab uses, which already pre-fills the
// draft vacancy with the step's competences. HRP-801 (QA 23.10, e): the
// To do tab opens the same window for one row or for its selection - one
// component, the title says which.
//
// All three land a draft vacancy in Recruitment. "Look inside first" also
// puts it on the talent market, when the draft has a library competence to
// match on; "Agency" marks the draft's title. Publishing stays a
// recruiter's action.

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioItem } from "@/components/ui/radio";
import { workApi } from "@/lib/api/work";

type Route = "internal_first" | "external" | "agency";

const ROUTES: Route[] = ["internal_first", "external", "agency"];

/** What each route asks the backend for. */
const BODY: Record<Route, { label: "hire" | "agency"; internal_search_allowed: boolean }> = {
  internal_first: { label: "hire", internal_search_allowed: true },
  external: { label: "hire", internal_search_allowed: false },
  // Nothing to search for inside when the work is going to a provider.
  agency: { label: "agency", internal_search_allowed: false },
};

export function HireFromStepDialog({
  containerId,
  steps,
  onClose,
  onCreated,
}: {
  containerId: string;
  /** One step from its row, or the To do tab's selection. */
  steps: { id: string; title: string }[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const t = useTranslations("coverage");
  const [route, setRoute] = useState<Route>("internal_first");
  const [saving, setSaving] = useState(false);
  const one = steps.length === 1;

  async function submit() {
    setSaving(true);
    try {
      const need = await workApi.createHireNeed(containerId, {
        step_ids: steps.map((s) => s.id),
        label: BODY[route].label,
        internal_search_allowed: BODY[route].internal_search_allowed,
      });
      // The talent market needs a library competence on the draft; without
      // one the vacancy stays in Recruitment and says so, not silently.
      if (route === "internal_first" && !need.talent_card_id) {
        toast.warning(t("hireNeedNotOnTalentMarket"));
      } else {
        toast.success(t("hireNeedCreated"));
      }
      onCreated();
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="coverage-modal-hire">
        <DialogHeader>
          <DialogTitle>
            {one ? t("hireFromStepTitle", { title: steps[0].title }) : t("hireFromStepsTitle")}
          </DialogTitle>
          <DialogDescription>{t(one ? "hireFromStepText" : "hireFromStepsText")}</DialogDescription>
        </DialogHeader>
        <RadioGroup
          value={route}
          onValueChange={(v) => setRoute(v as Route)}
          data-testid="coverage-hire-route"
        >
          {ROUTES.map((option) => (
            <Label key={option} className="flex items-start gap-2 text-sm font-normal">
              <RadioItem
                className="mt-0.5"
                value={option}
                data-testid={`coverage-hire-route-${option}`}
              />
              <span>
                <span className="font-medium">{t(`hireRoute_${option}`)}</span>
                <span className="block text-xs text-muted-foreground">
                  {t(`hireRouteHint_${option}`)}
                </span>
              </span>
            </Label>
          ))}
        </RadioGroup>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button disabled={saving} onClick={submit} data-testid="coverage-btn-hire-submit">
            {t("openHireNeedOne")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
