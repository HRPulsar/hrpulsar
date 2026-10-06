import { useSyncExternalStore } from "react";

/**
 * The owner key of a check (HRP-926): `POST /public-check/checks` hands it
 * once, and only the browser that ran the check keeps it - a shared result
 * link reads the result but cannot save it to an address. Kept per link
 * token in localStorage; private mode or a full quota simply means no save
 * block, never a broken page.
 *
 * A key has nothing left to do once its check is kept (no term) or gone
 * (404): the result page forgets it then. A check never opened again is
 * swept once its term is over - the terms sit in one index entry.
 */
const storageKey = (token: string) => `public-check:owner:${token}`;
const TERMS_KEY = "public-check:owner-terms";

function readTerms(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(TERMS_KEY) ?? "{}") as Record<string, string>;
  } catch {
    return {};
  }
}

export function rememberOwnerKey(
  token: string,
  ownerKey: string | undefined,
  expiresAt: string | null = null,
): void {
  if (!ownerKey) return;
  try {
    const terms = readTerms();
    for (const [other, term] of Object.entries(terms)) {
      if (Date.parse(term) > Date.now()) continue;
      localStorage.removeItem(storageKey(other));
      delete terms[other];
    }
    if (expiresAt) terms[token] = expiresAt;
    localStorage.setItem(TERMS_KEY, JSON.stringify(terms));
    localStorage.setItem(storageKey(token), ownerKey);
  } catch {
    // No storage: this browser cannot save the result, the check still runs.
  }
}

export function forgetOwnerKey(token: string): void {
  try {
    localStorage.removeItem(storageKey(token));
    const terms = readTerms();
    if (!(token in terms)) return;
    delete terms[token];
    localStorage.setItem(TERMS_KEY, JSON.stringify(terms));
  } catch {
    // No storage: nothing was kept.
  }
}

export function ownerKeyFor(token: string): string | null {
  try {
    return localStorage.getItem(storageKey(token));
  } catch {
    return null;
  }
}

const noSubscription = () => () => {};

/** The owner key of `token` in this browser; null on the server. */
export function useOwnerKey(token: string): string | null {
  return useSyncExternalStore(noSubscription, () => ownerKeyFor(token), () => null);
}
