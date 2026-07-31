// Two-layer API convention (review item [31]):
//   1. This module (`@/lib/api`) is the transport layer — the sanctioned
//      HTTP client with central auth, 401-refresh, 402-credit and error
//      handling. Calling `api.get/post/...` with an inline path from a
//      component is the DEFAULT style, not legacy.
//   2. `@/lib/api/<domain>.ts` modules wrap endpoint families that are
//      reused across several components or carry nontrivial payloads.
//      An endpoint wrapped by a domain module must not also be called
//      inline elsewhere — one wrapper, one owner.
// Raw `fetch(API_BASE...)` outside `src/lib/` is reserved for
// unauthenticated/public-token pages that must not trigger the
// auto-logout pipeline.
import { API_BASE } from "../api-base";
import { clearLocaleCookie } from "@/i18n/config";

export { API_BASE };

export class ApiError extends Error {
  // HRP-33: structured `detail` from the response body. Used by callers
  // that need to introspect a non-OK response (e.g. the AI generate
  // 409 carries the active session's id + scope so the UI can redirect
  // the user to the review page instead of showing a dead-end toast).
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
  }
}

let refreshPromise: Promise<boolean> | null = null;

// FastAPI returns 422 validation errors as detail: [{loc, msg, type, ...}].
// Custom HTTPException(detail=...) may pass a string, dict, or list. Render
// each shape to a readable message so toasts never show "[object Object]".
function formatApiError(detail: unknown): string {
  if (detail == null) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((entry) => {
        if (entry && typeof entry === "object") {
          const e = entry as { msg?: unknown; loc?: unknown };
          const msg = typeof e.msg === "string" ? e.msg : "";
          const loc = Array.isArray(e.loc)
            ? e.loc
                .filter((seg) => seg !== "body" && typeof seg !== "number")
                .join(".")
            : "";
          return loc && msg ? `${loc}: ${msg}` : msg || loc;
        }
        return String(entry);
      })
      .filter(Boolean)
      .join("; ");
  }
  if (typeof detail === "object") {
    const obj = detail as Record<string, unknown>;
    if (typeof obj.msg === "string") return obj.msg;
    if (typeof obj.message === "string") return obj.message;
    try {
      return JSON.stringify(obj);
    } catch {
      return String(obj);
    }
  }
  return String(detail);
}

async function tryRefreshToken(): Promise<boolean> {
  const refreshToken = localStorage.getItem("refresh_token");
  if (!refreshToken) return false;

  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    localStorage.setItem("access_token", data.access_token);
    localStorage.setItem("refresh_token", data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

function forceLogout() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  document.cookie = "has_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  document.cookie =
    "demo_session=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  // Mirror clearTokens() in lib/auth.ts: an expired session on a shared
  // device must not leak the previous user's language to the next one.
  clearLocaleCookie();
  window.location.href = "/login";
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  isRetry = false,
): Promise<T> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("access_token") : null;

  const isFormData = options.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...((options.headers as Record<string, string>) || {}),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    const isAuthEndpoint = path.startsWith("/auth/");
    if (res.status === 401 && typeof window !== "undefined" && !isAuthEndpoint) {
      if (!isRetry) {
        // Deduplicate concurrent refresh attempts
        if (!refreshPromise) {
          refreshPromise = tryRefreshToken().finally(() => {
            refreshPromise = null;
          });
        }
        const refreshed = await refreshPromise;
        if (refreshed) {
          return request<T>(path, options, true);
        }
      }
      forceLogout();
      return new Promise<never>(() => {});
    }
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    const message = formatApiError(body.detail) || res.statusText;

    // Credit limit — show user-friendly message via global event
    if (res.status === 402 && typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("hrpulsar:credit-limit", { detail: message }),
      );
    }

    throw new ApiError(res.status, message, body.detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

// Header-aware variant of `request`: returns the parsed body alongside the
// response Headers. Used by call sites that need ETag / If-Match optimistic
// concurrency, so they can go through the same central auth + 401-refresh +
// 402-credit handling instead of hand-rolling fetch with localStorage tokens.
async function requestWithMeta<T>(
  path: string,
  options: RequestInit = {},
  isRetry = false,
): Promise<{ data: T; headers: Headers }> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("access_token") : null;

  const isFormData = options.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...((options.headers as Record<string, string>) || {}),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    const isAuthEndpoint = path.startsWith("/auth/");
    if (res.status === 401 && typeof window !== "undefined" && !isAuthEndpoint) {
      if (!isRetry) {
        if (!refreshPromise) {
          refreshPromise = tryRefreshToken().finally(() => {
            refreshPromise = null;
          });
        }
        if (await refreshPromise) {
          return requestWithMeta<T>(path, options, true);
        }
      }
      forceLogout();
      return new Promise<never>(() => {});
    }
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    const message = formatApiError(body.detail) || res.statusText;
    if (res.status === 402 && typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("hrpulsar:credit-limit", { detail: message }),
      );
    }
    throw new ApiError(res.status, message, body.detail);
  }

  const data =
    res.status === 204 ? (undefined as T) : ((await res.json()) as T);
  return { data, headers: res.headers };
}

// Generic Celery task status shape returned by GET /api/tasks/{id}
type TaskStatus<T> = {
  task_id: string;
  status: "PENDING" | "STARTED" | "RETRY" | "SUCCESS" | "FAILURE";
  result?: T;
  error?: string;
};

type TaskUpdatePayload<T> = {
  task_id: string;
  status: TaskStatus<T>["status"];
  result: T | null;
  error: string | null;
  module: string | null;
  action: string | null;
};

/**
 * CR15: WebSocket-first wait for a Celery task. Polling kicks in only while
 * the WS isn't open (mobile drop, corporate proxy stripping the upgrade).
 *
 * Order matters:
 *   1. Subscribe FIRST so events fired between cold-fetch and subscribe
 *      aren't lost.
 *   2. Cold-fetch ONCE — covers "task already finished by the time we
 *      subscribed" (page opened after SUCCESS). One fetch is enough; any
 *      transition that fires between the fetch and the subscribe is captured
 *      by the subscription which is already live.
 *   3. Polling loop runs in parallel and fetches only when the WS reports
 *      a non-open state. As soon as WS reconnects the loop becomes a noop;
 *      the WS event resolves the promise.
 */
async function waitForTask<T>(
  taskId: string,
  { intervalMs = 2000, timeoutMs = 300_000 }: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<T> {
  // Lazy-import to keep this file usable from non-browser callers (the WS bus
  // is browser-only) and to avoid a hard dependency cycle with ws-bus.
  const { subscribeWs, getWsState } = await import("../ws-bus");

  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      try {
        unsubscribe();
      } catch {
        /* noop */
      }
      clearTimeout(deadlineTimer);
      clearInterval(pollHandle);
      fn();
    };

    const handleStatus = (status: TaskStatus<T>["status"], result: T | null, error: string | null) => {
      if (status === "SUCCESS") {
        finish(() => resolve(result as T));
      } else if (status === "FAILURE") {
        finish(() => reject(new ApiError(500, error || "Background task failed")));
      }
    };

    const unsubscribe = subscribeWs("task.updated", (msg) => {
      const payload = msg.payload as TaskUpdatePayload<T> | undefined;
      if (!payload || payload.task_id !== taskId) return;
      handleStatus(payload.status, payload.result, payload.error);
    });

    // Cold-fetch — covers race "task done before subscribe". Best-effort.
    request<TaskStatus<T>>(`/tasks/${taskId}`)
      .then((res) => handleStatus(res.status, (res.result as T | undefined) ?? null, res.error ?? null))
      .catch(() => {
        /* WS or poll will deliver */
      });

    // Polling fallback. Runs continuously but only fetches when WS is closed
    // — when WS is open we trust the subscription. This means an open WS
    // contributes zero requests; a flaky WS still gets the answer.
    const pollHandle = setInterval(() => {
      if (settled) return;
      if (getWsState() === "open") return;
      request<TaskStatus<T>>(`/tasks/${taskId}`)
        .then((res) => handleStatus(res.status, (res.result as T | undefined) ?? null, res.error ?? null))
        .catch(() => {
          /* keep trying */
        });
    }, intervalMs);

    const deadlineTimer = setTimeout(() => {
      finish(() => reject(new ApiError(504, "Background task timed out")));
    }, timeoutMs);
  });
}

async function requestBlob(
  path: string,
  options: RequestInit = {},
  isRetry = false,
): Promise<Blob> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  const headers: Record<string, string> = {
    ...((options.headers as Record<string, string>) || {}),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined" && !isRetry) {
      if (!refreshPromise) {
        refreshPromise = tryRefreshToken().finally(() => {
          refreshPromise = null;
        });
      }
      if (await refreshPromise) {
        return requestBlob(path, options, true);
      }
      forceLogout();
      return new Promise<never>(() => {});
    }
    throw new ApiError(res.status, `Request failed (HTTP ${res.status})`);
  }
  return res.blob();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(
    path: string,
    body?: unknown,
    options?: { headers?: Record<string, string>; keepalive?: boolean },
  ) =>
    request<T>(path, {
      method: "POST",
      body: JSON.stringify(body),
      headers: options?.headers,
      // keepalive lets a fire-and-forget POST survive an immediate
      // navigation (router.push) without the browser aborting it.
      keepalive: options?.keepalive,
    }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  patch: <T>(
    path: string,
    body?: unknown,
    options?: { headers?: Record<string, string> },
  ) =>
    request<T>(path, {
      method: "PATCH",
      body: JSON.stringify(body),
      headers: options?.headers,
    }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: <T>(path: string, file: File, options?: { signal?: AbortSignal }) => {
    // HRP-14: callers can pass an AbortSignal to cancel an in-flight upload
    // (e.g. when the user closes the material modal mid-transfer).
    const formData = new FormData();
    formData.append("file", file);
    return request<T>(path, {
      method: "POST",
      body: formData,
      signal: options?.signal,
    });
  },
  // ETag-aware helpers: return the response Headers so callers can read
  // ETag and send If-Match without leaving the central request pipeline.
  getWithMeta: <T>(path: string) => requestWithMeta<T>(path),
  sendWithMeta: <T>(
    path: string,
    method: "PATCH" | "PUT" | "POST" | "DELETE",
    body?: unknown,
    options?: { headers?: Record<string, string> },
  ) =>
    requestWithMeta<T>(path, {
      method,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      headers: options?.headers,
    }),
  fetchBlob: (path: string) => requestBlob(path),
  postBlob: (path: string, body?: unknown) =>
    requestBlob(path, {
      method: "POST",
      body: JSON.stringify(body ?? {}),
      headers: { "Content-Type": "application/json" },
    }),
  postForm: <T>(path: string, form: FormData) =>
    request<T>(path, { method: "POST", body: form }),
  // POST that enqueues a Celery task (202 + task_id), waits via WS first
  // and polls /tasks/{id} as fallback, returns the task result.
  postAndWait: async <T>(
    path: string,
    body?: unknown,
    opts?: { intervalMs?: number; timeoutMs?: number },
  ): Promise<T> => {
    const { task_id } = await request<{ task_id: string }>(path, {
      method: "POST",
      body: JSON.stringify(body),
    });
    return waitForTask<T>(task_id, opts);
  },
};

export { waitForTask };
export type { TaskStatus };
