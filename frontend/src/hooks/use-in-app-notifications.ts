"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useWebSocketEvent } from "@/lib/ws";

export interface InAppNotificationPayload {
  id: string;
  template_code: string;
  status: string;
  context: Record<string, unknown> | null;
  is_read: boolean;
  created_at: string | null;
}

interface UseInAppNotificationsOptions {
  /** Called for every incoming notification — typical use: re-fetch unread counter. */
  onAny?: (payload: InAppNotificationPayload) => void;
}

const COMPGEN_READY = "competence_generation_ready";
const COMPGEN_ERROR = "competence_generation_error";

/**
 * Subscribes to the realtime `notification.new` channel and surfaces toasts.
 *
 * Mount once near the top of the dashboard (so it lives for the whole
 * authenticated session) — duplicate mounts will produce duplicate toasts.
 */
export function useInAppNotifications(
  options: UseInAppNotificationsOptions = {},
): void {
  const router = useRouter();
  const { onAny } = options;

  useWebSocketEvent<InAppNotificationPayload>(
    "notification.new",
    useCallback(
      (msg) => {
        const payload = msg.payload;
        if (!payload) return;
        if (onAny) onAny(payload);

        const ctx = payload.context ?? {};
        const title =
          (typeof ctx.title === "string" && ctx.title) ||
          (typeof ctx.message === "string" && ctx.message) ||
          payload.template_code;

        if (payload.template_code === COMPGEN_READY) {
          toast.success(title || "AI generation ready", {
            action: {
              label: "Open session",
              onClick: () => router.push("/competences?compgen=open"),
            },
          });
          return;
        }
        if (payload.template_code === COMPGEN_ERROR) {
          toast.error(title || "AI generation failed", {
            action: {
              label: "Open session",
              onClick: () => router.push("/competences?compgen=open"),
            },
          });
          return;
        }

        toast(title);
      },
      [onAny, router],
    ),
  );
}
