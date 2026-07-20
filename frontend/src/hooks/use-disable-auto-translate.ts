"use client";

import { useEffect } from "react";

/**
 * Disables browser auto-translation (Google Translate, etc.) for the
 * subtree it is mounted under. Auto-translation mutates React-managed
 * text nodes (wrapping them in <font> elements) and breaks the
 * reconciler — the AI generation drawer shipped a `NotFoundError:
 * Failed to execute 'insertBefore'` regression because of this
 * (HRP-46).
 *
 * Pass `enabled=false` to leave auto-translation alone. HRP-133 narrows
 * the original dashboard-wide scope to "only while the AI drawer is
 * open" so that the rest of the app stays translatable.
 */
export function useDisableAutoTranslate(enabled: boolean = true): void {
  useEffect(() => {
    if (!enabled) return;

    const html = document.documentElement;
    const prevTranslate = html.getAttribute("translate");
    html.setAttribute("translate", "no");

    let metaElement: HTMLMetaElement | null = document.querySelector(
      'meta[name="google"][content="notranslate"]',
    );
    let metaWasInjected = false;
    if (!metaElement) {
      metaElement = document.createElement("meta");
      metaElement.name = "google";
      metaElement.content = "notranslate";
      document.head.appendChild(metaElement);
      metaWasInjected = true;
    }

    return () => {
      if (prevTranslate === null) {
        html.removeAttribute("translate");
      } else {
        html.setAttribute("translate", prevTranslate);
      }
      if (metaWasInjected && metaElement?.parentNode) {
        metaElement.parentNode.removeChild(metaElement);
      }
    };
  }, [enabled]);
}
