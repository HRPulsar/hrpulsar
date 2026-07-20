// Single source of truth for the API base URL, safe to import from both
// server and client code (no side effects).
//
// The fallback is the RELATIVE "/api" so that if NEXT_PUBLIC_API_URL is ever
// unset in production the app talks to its own origin behind the proxy —
// never a hardcoded "http://localhost:8100/api", which used to be duplicated
// across a dozen call sites and would silently point prod traffic at
// localhost (review P0-22).
export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";
