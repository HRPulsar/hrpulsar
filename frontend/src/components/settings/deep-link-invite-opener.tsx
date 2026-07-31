"use client";

import { useEffect, useRef } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

/**
 * HRP-174: opens the Send invitation dialog when the page is reached via
 * `/settings/invitations?open=invite` (the "+ Invite" link inside the
 * division Add-employee modal).
 *
 * The deep link must be consumed exactly once. `onOpen` is a fresh closure
 * on every render of the parent, so an unguarded effect re-ran after each
 * state change and re-opened the dialog the instant the user closed it —
 * Cancel, the X icon and the outside click all appeared dead. The ref
 * guard fixes that; dropping `open` from the URL additionally stops a
 * reload (F5) or a Back navigation from re-triggering the dialog.
 *
 * Lives in its own file so the behaviour can be unit-tested without
 * mounting the whole Invitations page.
 */
export function DeepLinkInviteOpener({ onOpen }: { onOpen: () => void }) {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const consumed = useRef(false);

  useEffect(() => {
    if (searchParams.get("open") !== "invite") {
      // Parameter gone (we stripped it, or the user navigated away from
      // the deep link) — re-arm so a later deep link still works.
      consumed.current = false;
      return;
    }
    if (consumed.current) return;
    consumed.current = true;
    onOpen();
    const next = new URLSearchParams(searchParams.toString());
    next.delete("open");
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, {
      scroll: false,
    });
  }, [searchParams, pathname, router, onOpen]);

  return null;
}
