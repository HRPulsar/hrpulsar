"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { Notification } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Bell } from "lucide-react";

export function NotificationBell() {
  const t = useTranslations("common");
  const [unreadCount, setUnreadCount] = useState(0);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);
  const [timeSnapshot, setTimeSnapshot] = useState(0);

  useEffect(() => {
    let active = true;
    async function fetchCount() {
      try {
        const data = await api.get<{ count: number }>("/notifications/unread-count");
        if (active) setUnreadCount(data.count);
      } catch {
        // ignore
      }
    }
    fetchCount();
    const interval = setInterval(fetchCount, 30000);
    return () => { active = false; clearInterval(interval); };
  }, []);

  async function loadNotifications() {
    try {
      const data = await api.get<Notification[]>("/notifications");
      setTimeSnapshot(Date.now());
      setNotifications(data.slice(0, 5));
    } catch {
      // ignore
    }
  }

  async function handleOpen(isOpen: boolean) {
    setOpen(isOpen);
    if (isOpen) {
      await loadNotifications();
    }
  }

  async function markAllRead() {
    try {
      await api.post("/notifications/mark-read", {});
      setUnreadCount(0);
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
    } catch {
      // ignore
    }
  }

  function formatTime(dateStr: string) {
    const diff = timeSnapshot - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return t("justNow");
    if (mins < 60) return t("minutesAgo", { count: mins });
    const hours = Math.floor(mins / 60);
    if (hours < 24) return t("hoursAgo", { count: hours });
    const days = Math.floor(hours / 24);
    return t("daysAgo", { count: days });
  }

  return (
    <DropdownMenu open={open} onOpenChange={handleOpen}>
      <DropdownMenuTrigger data-testid="header-btn-notifications" render={<Button variant="ghost" size="icon-sm" className="relative" />}>
        <Bell className="h-4 w-4" />
        {unreadCount > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-medium text-destructive-foreground">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <div className="flex items-center justify-between px-3 py-2">
          <p className="text-sm font-medium">{t("notifications")}</p>
          {unreadCount > 0 && (
            <button
              type="button"
              onClick={markAllRead}
              className="text-xs text-primary hover:underline"
            >
              {t("markAllRead")}
            </button>
          )}
        </div>
        <DropdownMenuSeparator />
        {notifications.length === 0 ? (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            {t("noNotifications")}
          </div>
        ) : (
          notifications.map((n) => (
            <DropdownMenuItem
              key={n.id}
              className="flex-col items-start gap-0.5 px-3 py-2"
              // HRP-442: notifications that carry a deep link open it.
              render={
                typeof n.context?.link === "string" ? (
                  <Link href={n.context.link as string} />
                ) : undefined
              }
            >
              <p className={`text-sm ${n.is_read ? "text-muted-foreground" : "font-medium"}`}>
                {(n.context?.title as string) || (n.context?.message as string) || t("notification")}
              </p>
              <p className="text-xs text-muted-foreground">
                {formatTime(n.created_at)}
              </p>
            </DropdownMenuItem>
          ))
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem render={<Link href="/settings/notifications" />} className="justify-center text-sm text-primary">
          {t("viewAllNotifications")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
