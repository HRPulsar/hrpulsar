// HRP-348: deterministic ids for manager-assessment scoring.
//
// Vacancy profile competences carry uuid5-normalized ids assigned by the
// backend (see backend `normalize_competence_id`); indicators are plain
// strings with no id at all. Score rows, however, are keyed by UUID. We
// mirror the backend algorithm — uuid5 over the same namespace — so the
// same competence/indicator text always maps to the same score row, across
// reloads and across regenerations that keep the wording.

const COMPETENCE_NS = "a4f1c2e3-0000-5000-8000-000000000001";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function uuidToBytes(uuid: string): Uint8Array {
  const hex = uuid.replace(/-/g, "");
  const bytes = new Uint8Array(16);
  for (let i = 0; i < 16; i++) {
    bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  }
  return bytes;
}

export async function uuid5(
  name: string,
  namespace: string = COMPETENCE_NS,
): Promise<string> {
  const ns = uuidToBytes(namespace);
  const nameBytes = new TextEncoder().encode(name);
  const data = new Uint8Array(ns.length + nameBytes.length);
  data.set(ns);
  data.set(nameBytes, ns.length);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-1", data));
  const b = digest.slice(0, 16);
  b[6] = (b[6]! & 0x0f) | 0x50;
  b[8] = (b[8]! & 0x3f) | 0x80;
  const hex = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** Stable UUID for a profile competence — pass through when already a UUID. */
export async function competenceScoreId(
  rawId: string | undefined,
  name: string,
): Promise<string> {
  // Trim before hashing — the backend strips the value the same way.
  const raw = (rawId || name).trim();
  if (UUID_RE.test(raw)) return raw.toLowerCase();
  return uuid5(raw);
}

/** Stable UUID for an indicator inside a competence. */
export function indicatorScoreId(
  competenceId: string,
  indicatorText: string,
): Promise<string> {
  return uuid5(`${competenceId}:${indicatorText.trim()}`);
}
