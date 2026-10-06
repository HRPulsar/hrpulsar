"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useTranslations } from "next-intl";
import { Loader2, Mic, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { VOICE_MAX_SECONDS, transcribe } from "@/lib/api/public-check";
import { cn } from "@/lib/utils";

/** What the recorder writes, best first: Opus in WebM (Chromium, Firefox),
 * MP4 (Safari), Ogg (older Firefox). The backend takes each of them. */
const MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

/** The container this browser records in; undefined when it cannot record
 * at all (no `MediaRecorder` or `getUserMedia`, e.g. outside a secure
 * context) or only in a format the backend does not take. */
export function recorderMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    return undefined;
  }
  return MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
}

/** `publicCheck` keys for a refused transcription, by error code. */
const ERROR_KEYS: Record<string, string> = {
  public_check_rate_limited: "voiceErrorRateLimited",
  public_check_daily_limit: "voiceErrorDailyLimit",
  public_check_voice_too_large: "voiceErrorTooLong",
  public_check_voice_too_long: "voiceErrorTooLong",
  public_check_voice_unsupported: "voiceErrorFormat",
  public_check_voice_unavailable: "voiceErrorUnavailable",
  public_check_not_found: "voiceErrorUnavailable",
  public_check_unavailable: "voiceErrorUnavailable",
};

// Shorter is a tap, not a recording: no provider call (the provider refuses
// a near-empty file, which would read as "unavailable").
const MIN_RECORDING_MS = 1000;

const clock = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

const noSubscription = () => () => {};

type Phase = "idle" | "recording" | "transcribing";

interface DictateButtonProps {
  /** The recognised text, trimmed, never empty. */
  onText: (text: string) => void;
}

/** The microphone button of the description (HRP-947): record, stop (by
 * hand or at `VOICE_MAX_SECONDS`), the text comes back through `onText`.
 * Renders flex items for the parent's row - the button with its timer, and
 * a full-width status line - and nothing where the browser cannot record. */
export function DictateButton({ onText }: DictateButtonProps) {
  const t = useTranslations("publicCheck");
  // Undefined on the server render: the button appears after hydration.
  const mimeType = useSyncExternalStore(noSubscription, recorderMimeType, () => undefined);
  const [phase, setPhase] = useState<Phase>("idle");
  const [seconds, setSeconds] = useState(0);
  const [atLimit, setAtLimit] = useState(false);
  const [message, setMessage] = useState<{ key: string; error: boolean } | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<number | undefined>(undefined);
  // Asking for the microphone: the prompt can stay open for a while, and a
  // second click meanwhile must not start a second recorder.
  const starting = useRef(false);
  const mounted = useRef(false);

  // Leaving the page mid-recording: the microphone goes off, nothing is sent.
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      window.clearInterval(timer.current);
      const rec = recorder.current;
      if (!rec) return;
      rec.onstop = null;
      if (rec.state !== "inactive") rec.stop();
      rec.stream.getTracks().forEach((track) => track.stop());
    };
  }, []);

  if (!mimeType) return null;

  function stop() {
    if (recorder.current?.state === "recording") recorder.current.stop();
  }

  async function send(audio: Blob) {
    setPhase("transcribing");
    try {
      const text = (await transcribe(audio)).text.trim();
      if (text) onText(text);
      setMessage(text ? { key: "voiceAdded", error: false } : { key: "voiceErrorEmpty", error: true });
    } catch (err) {
      // The page gave up waiting (`VOICE_TIMEOUT_MS`): the server's 503 too late.
      const timedOut = err instanceof DOMException && err.name === "TimeoutError";
      const key = err instanceof ApiError && err.code ? ERROR_KEYS[err.code] : undefined;
      setMessage({ key: timedOut ? "voiceErrorUnavailable" : (key ?? "voiceErrorGeneric"), error: true });
    }
    setPhase("idle");
  }

  async function start() {
    if (starting.current || recorder.current) return;
    starting.current = true;
    setMessage(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      const denied =
        err instanceof DOMException && (err.name === "NotAllowedError" || err.name === "SecurityError");
      setMessage({ key: denied ? "voiceErrorDenied" : "voiceErrorNoMic", error: true });
      return;
    } finally {
      starting.current = false;
    }
    // Granted after the visitor left the page, or with a recording already
    // running: release the microphone at once, never leave it on unowned.
    if (!mounted.current || recorder.current) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    const chunks: Blob[] = [];
    const startedAt = Date.now();
    let rec: MediaRecorder;
    try {
      rec = new MediaRecorder(stream, { mimeType });
      rec.ondataavailable = (event) => {
        if (event.data.size > 0) chunks.push(event.data);
      };
      rec.onstop = () => {
        window.clearInterval(timer.current);
        stream.getTracks().forEach((track) => track.stop());
        recorder.current = null;
        if (Date.now() - startedAt < MIN_RECORDING_MS) {
          setMessage({ key: "voiceErrorEmpty", error: true });
          setPhase("idle");
          return;
        }
        void send(new Blob(chunks, { type: rec.mimeType || mimeType }));
      };
      rec.start();
    } catch {
      // Never leave the microphone on behind a recorder that did not start.
      stream.getTracks().forEach((track) => track.stop());
      setMessage({ key: "voiceErrorGeneric", error: true });
      return;
    }
    recorder.current = rec;
    setSeconds(0);
    setAtLimit(false);
    setPhase("recording");
    timer.current = window.setInterval(() => {
      const elapsed = Math.min(VOICE_MAX_SECONDS, Math.floor((Date.now() - startedAt) / 1000));
      setSeconds(elapsed);
      if (elapsed >= VOICE_MAX_SECONDS) {
        setAtLimit(true);
        stop();
      }
    }, 1000);
  }

  const recording = phase === "recording";
  const state = phase !== "idle" ? phase : message ? (message.error ? "error" : "added") : "idle";
  const status =
    phase === "recording"
      ? t("voiceRecording")
      : phase === "transcribing"
        ? atLimit
          ? t("voiceTranscribingAtLimit", { max: VOICE_MAX_SECONDS / 60 })
          : t("voiceTranscribing")
        : message && t(message.key);

  return (
    <>
      <div className="flex items-center gap-2">
        {recording ? (
          <span className="text-sm tabular-nums text-destructive" data-testid="check-dictate-timer">
            {t("voiceTimer", { elapsed: clock(seconds), max: clock(VOICE_MAX_SECONDS) })}
          </span>
        ) : null}
        <Button
          type="button"
          variant={recording ? "destructive" : "outline"}
          size="sm"
          aria-pressed={recording}
          disabled={phase === "transcribing"}
          onClick={recording ? stop : start}
          data-testid="check-btn-dictate"
        >
          {phase === "transcribing" ? (
            <Loader2 className="animate-spin" />
          ) : recording ? (
            <Square />
          ) : (
            <Mic />
          )}
          {t("voiceDictate")}
        </Button>
      </div>
      <p
        role="status"
        aria-live="polite"
        data-testid="check-dictate-status"
        data-state={state}
        className={cn(
          "basis-full text-xs empty:sr-only",
          state === "error" ? "text-destructive" : "text-muted-foreground",
        )}
      >
        {status}
      </p>
    </>
  );
}
