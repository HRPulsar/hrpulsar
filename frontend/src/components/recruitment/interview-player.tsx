"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import {
  ChevronsLeft,
  ChevronsRight,
  Download,
  Maximize,
  Pause,
  Play,
} from "lucide-react";

interface InterviewPlayerProps {
  src: string;
  kind: "audio" | "video";
  onTime?: (sec: number) => void;
  refSetter?: (el: HTMLMediaElement | null) => void;
  /** HRP-980: shown only to whoever may download the recording. */
  onDownload?: () => void;
  /** HRP-980: the playback link expires after 5 minutes. Called when the
   * player can no longer load from it, to hand in a fresh `src`; playback
   * picks up where it stopped. */
  onExpired?: () => void;
}

const SPEED_STEPS = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0];

/**
 * In-app player with speed (0.75x–2x), ±15s, fullscreen, keyboard
 * shortcuts (Space, J/L for ±15s, ←/→ for ±5s) — HRP-202 AC.
 */
export function InterviewPlayer({
  src,
  kind,
  onTime,
  refSetter,
  onDownload,
  onExpired,
}: InterviewPlayerProps) {
  const t = useTranslations("recruitment");
  const mediaRef = useRef<HTMLMediaElement | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [speed, setSpeed] = useState(1);
  const [playing, setPlaying] = useState(false);
  // Where to pick up once a fresh link replaces an expired one.
  const resumeAt = useRef<{ time: number; play: boolean } | null>(null);
  const lastRenewal = useRef(0);

  useEffect(() => {
    if (mediaRef.current) mediaRef.current.playbackRate = speed;
  }, [speed]);

  function seekBy(delta: number) {
    if (mediaRef.current) {
      mediaRef.current.currentTime = Math.max(
        0,
        mediaRef.current.currentTime + delta,
      );
    }
  }

  async function togglePlay() {
    if (!mediaRef.current) return;
    if (mediaRef.current.paused) {
      await mediaRef.current.play();
    } else {
      mediaRef.current.pause();
    }
  }

  async function toggleFullscreen() {
    const el = containerRef.current;
    if (!el) return;
    if (document.fullscreenElement) {
      await document.exitFullscreen();
    } else if (el.requestFullscreen) {
      await el.requestFullscreen();
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.target instanceof HTMLInputElement) return;
    if (e.key === " ") {
      e.preventDefault();
      void togglePlay();
    } else if (e.key === "j" || e.key === "J") {
      seekBy(-15);
    } else if (e.key === "l" || e.key === "L") {
      seekBy(15);
    } else if (e.key === "ArrowLeft") {
      seekBy(-5);
    } else if (e.key === "ArrowRight") {
      seekBy(5);
    } else if (e.key === "f" || e.key === "F") {
      void toggleFullscreen();
    }
  }

  const MediaElement = kind === "video" ? "video" : "audio";

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      onKeyDown={onKeyDown}
      className="space-y-2 outline-none"
      data-testid="recruitment-interview-player-wrapper"
    >
      <MediaElement
        ref={(node: HTMLMediaElement | null) => {
          mediaRef.current = node;
          refSetter?.(node);
        }}
        src={src}
        controls
        // HRP-980: the browser's own Save reuses the 5-minute playback
        // link, and an expired one downloads S3's XML error. Downloads go
        // through the Download button, which signs a fresh link.
        controlsList="nodownload"
        className={
          kind === "video"
            ? "h-[360px] w-full rounded-md bg-black"
            : "w-full"
        }
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onError={() => {
          const el = mediaRef.current;
          // One renewal per 10 s: a file that is really gone must not loop.
          if (!el || !onExpired || Date.now() - lastRenewal.current < 10_000)
            return;
          lastRenewal.current = Date.now();
          resumeAt.current = { time: el.currentTime, play: !el.paused };
          onExpired();
        }}
        onLoadedMetadata={() => {
          const el = mediaRef.current;
          const resume = resumeAt.current;
          if (!el || !resume) return;
          resumeAt.current = null;
          el.currentTime = resume.time;
          if (resume.play) void el.play().catch(() => undefined);
        }}
        onTimeUpdate={(e) =>
          onTime?.((e.target as HTMLMediaElement).currentTime)
        }
        data-testid="recruitment-interview-player"
      />
      <div className="flex flex-wrap items-center gap-1.5">
        <Button
          size="sm"
          variant="outline"
          onClick={() => void togglePlay()}
          data-testid="recruitment-interview-player-toggle"
        >
          {playing ? (
            <Pause className="size-3.5" />
          ) : (
            <Play className="size-3.5" />
          )}
          {playing ? t("playerPause") : t("playerPlay")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => seekBy(-15)}
          data-testid="recruitment-interview-player-back15"
          aria-label={t("playerBack15Aria")}
        >
          <ChevronsLeft className="size-3.5" />
          {t("playerBack15")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => seekBy(15)}
          data-testid="recruitment-interview-player-fwd15"
          aria-label={t("playerFwd15Aria")}
        >
          {t("playerFwd15")}
          <ChevronsRight className="size-3.5" />
        </Button>
        <select
          value={speed}
          onChange={(e) => setSpeed(Number(e.target.value))}
          className="h-8 rounded-md border border-input bg-transparent px-2 text-xs"
          data-testid="recruitment-interview-player-speed"
          aria-label={t("playerSpeedAria")}
        >
          {SPEED_STEPS.map((s) => (
            <option key={s} value={s}>
              {t("playerSpeedOption", { speed: s.toFixed(2) })}
            </option>
          ))}
        </select>
        {kind === "video" && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void toggleFullscreen()}
            data-testid="recruitment-interview-player-fullscreen"
            aria-label={t("playerFullscreenAria")}
          >
            <Maximize className="size-3.5" />
          </Button>
        )}
        {onDownload && (
          <Button
            size="sm"
            variant="outline"
            className="ml-auto"
            onClick={onDownload}
            data-testid="recruitment-interview-player-download"
          >
            <Download className="size-3.5" />
            {t("playerDownload")}
          </Button>
        )}
      </div>
    </div>
  );
}
