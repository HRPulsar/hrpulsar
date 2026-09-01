"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Building2, Loader2 } from "lucide-react";

import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ALERT_TONE, BADGE_OUTLINE } from "@/lib/badge-tones";
import { usePermissions } from "@/hooks/use-permissions";
import type { VacancyInternalCandidates } from "@/lib/recruitment-types";

/** HRP-667 + HRP-663 — "look inside before you hire outside", as an action.
 *
 *  The offer and the answer are the same block on purpose: before the
 *  vacancy is posted to the internal talent market this is the prompt to
 *  post it, and afterwards it is the shortlist that posting produced. A
 *  recruiter never sees an empty panel asking them to imagine what it
 *  would contain.
 *
 *  The percentages are the talent market's own deterministic competence
 *  match — there is no second matcher here, only a different place to
 *  read the first one from.
 */
export function InternalCandidatesBlock({
  vacancyId,
  reloadToken = 0,
}: {
  vacancyId: string;
  /** HRP-687: bumped when the vacancy's library competences change, so
   *  `has_library_competences` (and the Post button) refresh without an F5. */
  reloadToken?: number;
}) {
  const t = useTranslations("recruitment");
  // HRP-667: POST /talent-card is require_role("admin", "recruiter") — the
  // rest of RECRUITMENT_VIEWER_ROLES sees this block. They keep the button,
  // greyed out and with the reason next to it, rather than a 403 toast.
  const { isAdmin, isRecruiter } = usePermissions();
  const canPost = isAdmin || isRecruiter;
  const [data, setData] = useState<VacancyInternalCandidates | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(
        await api.get<VacancyInternalCandidates>(
          `/recruitment/vacancies/${vacancyId}/internal-candidates`,
        ),
      );
    } catch {
      setData(null);
    }
  }, [vacancyId]);

  useEffect(() => {
    void load();
  }, [load, reloadToken]);

  const post = useCallback(async () => {
    setBusy(true);
    try {
      setData(
        await api.post<VacancyInternalCandidates>(
          `/recruitment/vacancies/${vacancyId}/talent-card`,
          {},
        ),
      );
    } catch (err) {
      toast.error(
        err instanceof ApiError && err.message
          ? err.message
          : t("internalCandidatesPostFailed"),
      );
    } finally {
      setBusy(false);
    }
  }, [vacancyId, t]);

  if (!data) return null;

  // Not posted yet — the offer. This is the whole point of HRP-667: the
  // suggestion sits on the vacancy the recruiter already has open, and it
  // is a button, not a sentence telling them to go somewhere else.
  if (!data.talent_card_id) {
    return (
      <div
        className={cn(
          "mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md border p-3 text-sm",
          ALERT_TONE.neutral,
        )}
        data-testid="vacancy-internal-candidates-offer"
      >
        <div className="flex items-start gap-2">
          <Building2 className="mt-0.5 size-4 shrink-0" aria-hidden />
          <div>
            <p className="font-medium">{t("internalCandidatesOfferTitle")}</p>
            <p className="text-muted-foreground">
              {/* HRP-678: the switch is a third reason the button can be
                  dead, and it is the one the recruiter set themselves —
                  so say which of the three it is. */}
              {!canPost
                ? t("internalCandidatesOfferNoPermission")
                : !data.internal_search_allowed
                  ? t("internalCandidatesOfferSearchDisabled")
                  : data.has_library_competences
                    ? t("internalCandidatesOfferHint")
                    : t("internalCandidatesOfferNoCompetences")}
            </p>
          </div>
        </div>
        <Button
          size="sm"
          onClick={post}
          disabled={
            busy ||
            !canPost ||
            !data.internal_search_allowed ||
            !data.has_library_competences
          }
          data-testid="vacancy-internal-candidates-post-btn"
        >
          {busy && <Loader2 className="mr-1 size-3.5 animate-spin" aria-hidden />}
          {t("internalCandidatesPostBtn")}
        </Button>
      </div>
    );
  }

  return (
    <div
      className="mb-4 rounded-md border p-3"
      data-testid="vacancy-internal-candidates"
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Building2 className="size-4" aria-hidden />
          {t("internalCandidatesTitle", { count: data.items.length })}
        </div>
        <Button
          size="sm"
          variant="outline"
          render={<Link href={`/talent-market/${data.talent_card_id}`} />}
          data-testid="vacancy-internal-candidates-card-link"
        >
          {t("internalCandidatesOpenCard")}
        </Button>
      </div>
      {data.items.length === 0 ? (
        <p
          className="text-sm text-muted-foreground"
          data-testid="vacancy-internal-candidates-empty"
        >
          {t("internalCandidatesEmpty")}
        </p>
      ) : (
        <ul className="divide-y text-sm">
          {data.items.map((item) => (
            <li
              key={item.employee_id}
              className="flex flex-wrap items-center justify-between gap-2 py-1.5"
              data-testid={`vacancy-internal-candidate-${item.employee_id}`}
            >
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-medium">
                  {item.employee_name ?? t("internalCandidatesUnnamed")}
                </span>
                <Badge
                  variant="outline"
                  className={cn("border text-[10px]", BADGE_OUTLINE.indigo)}
                >
                  {t("internalCandidateBadge")}
                </Badge>
                {item.position_title && (
                  <span className="text-muted-foreground">
                    {item.position_title}
                  </span>
                )}
              </span>
              <span className="flex items-center gap-2">
                {/* HRP-693: `not_matched` is the matcher's word for "a
                    person somebody added by hand who does not clear the
                    bar". A bare dash read as a broken score; say what the
                    row actually is. */}
                {item.status === "not_matched" && (
                  <Badge
                    variant="outline"
                    className={cn("border text-[10px]", BADGE_OUTLINE.amber)}
                    data-testid={`vacancy-internal-candidate-manual-${item.employee_id}`}
                  >
                    {t("internalCandidateManualBadge")}
                  </Badge>
                )}
                {item.match_score !== null ? (
                  <span className="tabular-nums text-muted-foreground">
                    {t("internalCandidatesMatch", { percent: item.match_score })}
                  </span>
                ) : (
                  item.status !== "not_matched" && (
                    <span className="text-muted-foreground">{"—"}</span>
                  )
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-muted-foreground">
        {t("internalCandidatesSource")}
        {/* The bridge creates the card as a draft on purpose — publishing
            mails every matched employee, and that call belongs to whoever
            owns the talent market. Say so, or the recruiter assumes the
            people below have been told. */}
        {data.talent_card_status === "draft" && (
          <> {t("internalCandidatesDraftHint")}</>
        )}
      </p>
    </div>
  );
}
