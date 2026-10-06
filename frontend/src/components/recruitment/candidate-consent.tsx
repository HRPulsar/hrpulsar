"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { ShieldAlert } from "lucide-react";
import { api } from "@/lib/api";
import { ALERT_TONE } from "@/lib/badge-tones";
import type { ConsentRequest } from "@/lib/types";

/**
 * HRP-979: whether the candidate's consent to AI processing is in force.
 *
 * `blocked` stays true until the answer is in, so an AI button never fires
 * on a guess (the backend refuses with `consent_required` either way).
 */
export function useCandidateConsent(candidateId: string) {
  // Keyed by candidate, so a stale answer never gates another candidate.
  const [result, setResult] = useState<{
    candidateId: string;
    consent: ConsentRequest | null;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .get<ConsentRequest | null>(
          `/recruitment/candidates/${candidateId}/consent/latest`,
        )
        .then((consent) => {
          if (!cancelled) setResult({ candidateId, consent });
        })
        .catch(() => {
          if (!cancelled) setResult({ candidateId, consent: null });
        });
    void load();
    // The candidate signs or withdraws in their own mailbox, not here:
    // coming back to the tab re-reads the answer (no polling).
    const onVisible = () => {
      if (!document.hidden) void load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [candidateId]);

  const loaded = result?.candidateId === candidateId;
  const consent = loaded ? result.consent : null;
  const active = consent?.active === true;
  return {
    blocked: !loaded || !active,
    showHint: loaded && !active,
    revoked: consent?.status === "revoked",
  };
}

export function ConsentRequiredHint({
  revoked,
  testId,
}: {
  revoked: boolean;
  testId: string;
}) {
  const t = useTranslations("recruitment");
  return (
    <p
      data-testid={testId}
      className={`flex items-start gap-2 rounded-md border p-2 text-xs ${ALERT_TONE.amber}`}
    >
      <ShieldAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      {revoked ? t("aiConsentRevokedHint") : t("aiConsentMissingHint")}
    </p>
  );
}
