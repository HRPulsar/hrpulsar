"use client";

import { useCallback, useEffect, useState } from "react";
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
      toast.success("All notifications marked as read");
    } catch {
      toast.error("Failed to mark notifications as read");
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
    return <div className="flex items-center justify-center py-12 text-muted-foreground">Loading...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Notifications</h1>
          <p className="text-sm text-muted-foreground">
            {notifications.length} notification{notifications.length !== 1 ? "s" : ""}
            {unreadCount > 0 && ` (${unreadCount} unread)`}
          </p>
        </div>
        {unreadCount > 0 && (
          <Button size="sm" variant="outline" onClick={markAllRead}>
            <CheckCheck className="mr-1 h-4 w-4" />
            Mark all read
          </Button>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>All notifications</CardTitle>
          <CardDescription>Your notification history</CardDescription>
        </CardHeader>
        <CardContent>
          {notifications.length === 0 ? (
            <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed p-12 text-center">
              <Bell className="h-8 w-8 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">No notifications yet</p>
            </div>
          ) : (
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8" />
                    <TableHead>Message</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Date</TableHead>
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
                          {(n.context?.title as string) || (n.context?.message as string) || "Notification"}
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
                            Read
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
          <CardTitle>Email notifications</CardTitle>
          <CardDescription>
            Configure which notifications you receive by email
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">Assessment assigned</p>
                <p className="text-xs text-muted-foreground">Get notified when an assessment is assigned to you</p>
              </div>
              <Badge variant="secondary">Enabled</Badge>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">PDP deadline reminder</p>
                <p className="text-xs text-muted-foreground">Receive reminders about upcoming PDP deadlines</p>
              </div>
              <Badge variant="secondary">Enabled</Badge>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">Exam invitation</p>
                <p className="text-xs text-muted-foreground">Get notified when assigned to an exam</p>
              </div>
              <Badge variant="secondary">Enabled</Badge>
            </div>
            <p className="text-xs text-muted-foreground pt-2">
              Email notification preferences will be configurable in a future update.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
