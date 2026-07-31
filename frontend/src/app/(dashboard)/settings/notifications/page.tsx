"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { Notification } from "@/lib/types";
import { formatDateTime } from "@/lib/date-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";
import { Bell, CheckCheck } from "lucide-react";
import { BADGE_COLOR } from "@/lib/badge-tones";

const statusColors: Record<string, string> = {
  pending: BADGE_COLOR.yellow,
  sent: BADGE_COLOR.green,
  failed: BADGE_COLOR.red,
};

export default function NotificationsPage() {
  const t = useTranslations("settings");
  const tc = useTranslations("common");
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const data = await api.get<Notification[]>("/notifications");
      setNotifications(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function markAllRead() {
    try {
      await api.post("/notifications/mark-read", {});
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
      toast.success(t("notifAllRead"));
    } catch {
      toast.error(t("notifMarkReadFailed"));
    }
  }

  async function markRead(ids: string[]) {
    try {
      await api.post("/notifications/mark-read", { notification_ids: ids });
      setNotifications((prev) =>
        prev.map((n) => (ids.includes(n.id) ? { ...n, is_read: true } : n))
      );
    } catch {
      // ignore
    }
  }

  const unreadCount = notifications.filter((n) => !n.is_read).length;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        {tc("loading")}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {tc("notifications")}
          </h1>
          <p className="text-sm text-muted-foreground">
            {t("notifCount", { count: notifications.length })}
            {unreadCount > 0 && ` ${t("notifUnread", { count: unreadCount })}`}
          </p>
        </div>
        {unreadCount > 0 && (
          <Button size="sm" variant="outline" onClick={markAllRead}>
            <CheckCheck className="mr-1 h-4 w-4" />
            {tc("markAllRead")}
          </Button>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("notifAllTitle")}</CardTitle>
          <CardDescription>{t("notifHistoryDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {notifications.length === 0 ? (
            <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed p-12 text-center">
              <Bell className="h-8 w-8 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                {t("notifEmpty")}
              </p>
            </div>
          ) : (
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8" />
                    <TableHead>{t("notifColMessage")}</TableHead>
                    <TableHead>{t("notifColStatus")}</TableHead>
                    <TableHead>{t("notifColDate")}</TableHead>
                    <TableHead className="w-20" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {notifications.map((n) => (
                    <TableRow key={n.id} className={n.is_read ? "opacity-60" : ""}>
                      <TableCell>
                        {!n.is_read && (
                          <div className="h-2 w-2 rounded-full bg-primary" />
                        )}
                      </TableCell>
                      <TableCell>
                        <p className={`text-sm ${n.is_read ? "" : "font-medium"}`}>
                          {(n.context?.title as string) ||
                            (n.context?.message as string) ||
                            tc("notification")}
                        </p>
                        {typeof n.context?.description === "string" && (
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {n.context.description}
                          </p>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className={statusColors[n.status] || ""}>
                          {n.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm">
                        {formatDateTime(n.created_at)}
                      </TableCell>
                      <TableCell>
                        {!n.is_read && (
                          <Button
                            size="xs"
                            variant="ghost"
                            onClick={() => markRead([n.id])}
                          >
                            {t("notifRead")}
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Email settings */}
      <Card>
        <CardHeader>
          <CardTitle>{t("notifEmailTitle")}</CardTitle>
          <CardDescription>{t("notifEmailDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">
                  {t("notifAssessmentAssigned")}
                </p>
                <p className="text-xs text-muted-foreground">
                  {t("notifAssessmentAssignedHint")}
                </p>
              </div>
              <Badge variant="secondary">{t("notifEnabled")}</Badge>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">{t("notifPdpReminder")}</p>
                <p className="text-xs text-muted-foreground">
                  {t("notifPdpReminderHint")}
                </p>
              </div>
              <Badge variant="secondary">{t("notifEnabled")}</Badge>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">{t("notifExamInvitation")}</p>
                <p className="text-xs text-muted-foreground">
                  {t("notifExamInvitationHint")}
                </p>
              </div>
              <Badge variant="secondary">{t("notifEnabled")}</Badge>
            </div>
            <p className="text-xs text-muted-foreground pt-2">
              {t("notifEmailFuture")}
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
