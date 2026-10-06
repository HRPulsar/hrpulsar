"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Check, Copy } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { stepCounts, trackEvent, type CheckResult, type CheckUtm } from "@/lib/api/public-check";
import { cn } from "@/lib/utils";

/**
 * Sharing a ready result (HRP-928): LinkedIn, X and the link itself. Plain
 * share URLs - no SDK or script of a network. `url` is the canonical
 * `https://<check host>/r/<token>` from the server, whatever host the page
 * is open on: the app host's robots.txt keeps preview crawlers out, so a
 * link there would never show its card.
 */
export function ShareButtons({
  url,
  result,
  title,
  utm,
}: {
  url: string;
  result: CheckResult;
  title: string;
  /** The check's campaign, for the funnel's "shared" (HRP-931). */
  utm?: CheckUtm | null;
}) {
  const t = useTranslations("publicCheck");
  const input = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState(false);
  // One "shared" per result page, whichever button and however often.
  const shared = useRef(false);
  function onShare() {
    if (shared.current) return;
    shared.current = true;
    trackEvent("shared", utm);
  }
  const counts = stepCounts(result);
  const text =
    counts.total > 0
      ? t("shareTitle", { headline: t("shareHeadline", counts), process: title })
      : t("metaTitle");

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      // No Clipboard API (plain http, an old browser, a denied permission):
      // copy the selected field the old way - or leave it selected.
      input.current?.select();
      if (!document.execCommand("copy")) return;
    }
    // Shared once the link is really on the clipboard.
    onShare();
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  }

  // cn, as Button does: the outline border must win over the base one.
  const link = cn(buttonVariants({ variant: "outline" }));
  return (
    <section className="space-y-3" data-testid="check-social" aria-labelledby="check-social-title">
      <h2 id="check-social-title" className="text-lg font-semibold">
        {t("shareHeading")}
      </h2>
      <div className="flex flex-wrap gap-2">
        <a
          href={`https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`}
          target="_blank"
          rel="noopener noreferrer"
          className={link}
          onClick={onShare}
          data-testid="check-social-linkedin"
        >
          {t("shareOnLinkedIn")}
        </a>
        <a
          href={`https://x.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`}
          target="_blank"
          rel="noopener noreferrer"
          className={link}
          onClick={onShare}
          data-testid="check-social-x"
        >
          {t("shareOnX")}
        </a>
      </div>
      <div className="flex gap-2">
        <Input
          ref={input}
          readOnly
          value={url}
          aria-label={t("shareLinkLabel")}
          onFocus={(e) => e.currentTarget.select()}
          data-testid="check-social-url"
        />
        <Button variant="outline" onClick={copy} data-testid="check-social-copy">
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          {copied ? t("shareCopied") : t("shareCopy")}
        </Button>
      </div>
      <p className="sr-only" aria-live="polite">
        {copied ? t("shareCopied") : ""}
      </p>
    </section>
  );
}
