"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getAccessToken } from "./auth";
import {
  dispatchWs,
  getWsState,
  onWsStateChange,
  setWsState,
  subscribeWs,
  type WsBusMessage,
  type WsBusState,
} from "./ws-bus";

export type WsState = WsBusState;

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30_000;
const PING_TIMEOUT_MS = 60_000;

function buildWsUrl(token: string): string {
  if (typeof window === "undefined") return "";
  const apiBase = process.env.NEXT_PUBLIC_API_URL || "/api";
  // /api proxied path → ws on current origin
  if (apiBase.startsWith("/")) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}${apiBase}/ws?token=${encodeURIComponent(token)}`;
  }
  // Absolute http(s) URL → swap scheme
  const url = new URL(apiBase, window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `${url.pathname.replace(/\/$/, "")}/ws`;
  url.searchParams.set("token", token);
  return url.toString();
}

export function WebSocketProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedByUserRef = useRef(false);

  const armPingWatchdog = useCallback(() => {
    if (pingTimerRef.current) clearTimeout(pingTimerRef.current);
    pingTimerRef.current = setTimeout(() => {
      // Server should ping every 30s; if 60s passed — force a reconnect.
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.close(4000, "ping-timeout");
        } catch {
          /* noop */
        }
      }
    }, PING_TIMEOUT_MS);
  }, []);

  const clearTimers = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (pingTimerRef.current) {
      clearTimeout(pingTimerRef.current);
      pingTimerRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (typeof window === "undefined") return;
    const token = getAccessToken();
    if (!token) {
      setWsState("closed");
      return;
    }

    setWsState(reconnectAttemptsRef.current === 0 ? "connecting" : "reconnecting");

    let ws: WebSocket;
    try {
      ws = new WebSocket(buildWsUrl(token));
    } catch (err) {
      console.warn("ws ctor failed", err);
      scheduleReconnect();
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectAttemptsRef.current = 0;
      setWsState("open");
      armPingWatchdog();
    };

    ws.onmessage = (ev) => {
      armPingWatchdog();
      let parsed: WsBusMessage;
      try {
        parsed = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (!parsed || typeof parsed !== "object" || typeof parsed.type !== "string") {
        return;
      }
      // Heartbeat: respond to server ping; do not bubble to handlers.
      if (parsed.type === "ping") {
        try {
          ws.send(JSON.stringify({ type: "pong" }));
        } catch {
          /* noop */
        }
        return;
      }
      dispatchWs(parsed);
    };

    ws.onerror = () => {
      // Browsers fire `error` then `close`; reconnect logic lives in onclose.
    };

    ws.onclose = (ev) => {
      clearTimers();
      wsRef.current = null;
      if (closedByUserRef.current) {
        setWsState("closed");
        return;
      }
      // 1008 = policy violation (invalid/expired JWT). Don't loop forever:
      // the backend rejected our token, so wait longer between retries —
      // a separate refresh path in api.ts will eventually update the token.
      if (ev.code === 1008) {
        reconnectAttemptsRef.current = Math.max(reconnectAttemptsRef.current, 3);
      }
      scheduleReconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [armPingWatchdog, clearTimers]);

  const scheduleReconnect = useCallback(() => {
    setWsState("reconnecting");
    const attempt = reconnectAttemptsRef.current;
    const delay = Math.min(
      RECONNECT_BASE_MS * 2 ** attempt,
      RECONNECT_MAX_MS,
    );
    reconnectAttemptsRef.current = attempt + 1;
    reconnectTimerRef.current = setTimeout(() => {
      connect();
    }, delay);
  }, [connect]);

  useEffect(() => {
    closedByUserRef.current = false;
    connect();
    return () => {
      closedByUserRef.current = true;
      clearTimers();
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws) {
        try {
          ws.close(1000, "unmount");
        } catch {
          /* noop */
        }
      }
    };
  }, [connect, clearTimers]);

  return <>{children}</>;
}

export function useWebSocketState(): WsState {
  const [state, setState] = useState<WsState>(getWsState());
  useEffect(() => onWsStateChange(setState), []);
  return state;
}

/**
 * Subscribe to WS events of a given `type`. Handler is captured in a ref so
 * callers can pass inline closures without re-subscribing on every render.
 */
export function useWebSocketEvent<T = unknown>(
  eventType: string,
  handler: (msg: WsBusMessage<T>) => void,
): void {
  const handlerRef = useRef(handler);
  useEffect(() => {
    handlerRef.current = handler;
  }, [handler]);
  useEffect(() => {
    return subscribeWs(eventType, (msg) => handlerRef.current(msg as WsBusMessage<T>));
  }, [eventType]);
}
