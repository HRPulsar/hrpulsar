/**
 * Module-level WebSocket event bus.
 *
 * Both `WebSocketProvider` (React) and `postAndWait` (plain function in
 * api.ts) need the same subscribe / dispatch primitives. Hoisting them out
 * of the provider's refs lets non-React callers attach without a context.
 */

export type WsBusState = "connecting" | "open" | "closed" | "reconnecting";

export type WsBusMessage<T = unknown> = { type: string; payload?: T } & Record<
  string,
  unknown
>;

type Handler = (msg: WsBusMessage) => void;

const handlers: Map<string, Set<Handler>> = new Map();
let currentState: WsBusState = "closed";
const stateListeners: Set<(state: WsBusState) => void> = new Set();

export function subscribeWs(eventType: string, handler: Handler): () => void {
  let bucket = handlers.get(eventType);
  if (!bucket) {
    bucket = new Set();
    handlers.set(eventType, bucket);
  }
  bucket.add(handler);
  return () => {
    const cur = handlers.get(eventType);
    if (!cur) return;
    cur.delete(handler);
    if (cur.size === 0) handlers.delete(eventType);
  };
}

export function dispatchWs(msg: WsBusMessage): void {
  const bucket = handlers.get(msg.type);
  if (!bucket) return;
  for (const h of bucket) {
    try {
      h(msg);
    } catch (err) {
      console.error("ws handler error", err);
    }
  }
}

export function setWsState(state: WsBusState): void {
  if (state === currentState) return;
  currentState = state;
  for (const l of stateListeners) {
    try {
      l(state);
    } catch (err) {
      console.error("ws state listener error", err);
    }
  }
}

export function getWsState(): WsBusState {
  return currentState;
}

export function onWsStateChange(
  listener: (state: WsBusState) => void,
): () => void {
  stateListeners.add(listener);
  return () => {
    stateListeners.delete(listener);
  };
}
