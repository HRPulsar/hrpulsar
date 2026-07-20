"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import {
  ChevronsLeft,
  ChevronsRight,
  Maximize,
  Pause,
  Play,
} from "lucide-react";

interface InterviewPlayerProps {
  src: string;
  kind: "audio" | "video";
  onTime?: (sec: number) => void;
  refSetter?: (el: HTMLMediaElement | null) => void;
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
}: InterviewPlayerProps) {
  const mediaRef = useRef<HTMLMediaElement | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [speed, setSpeed] = useState(1);
  const [playing, setPlaying] = useState(false);

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
        className={
          kind === "video"
            ? "h-[360px] w-full rounded-md bg-black"
            : "w-full"
        }
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
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
          {playing ? "Pause" : "Play"}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => seekBy(-15)}
          data-testid="recruitment-interview-player-back15"
          aria-label="Back 15 seconds"
        >
          <ChevronsLeft className="size-3.5" />
          −15s
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => seekBy(15)}
          data-testid="recruitment-interview-player-fwd15"
          aria-label="Forward 15 seconds"
        >
          +15s
          <ChevronsRight className="size-3.5" />
        </Button>
        <select
          value={speed}
          onChange={(e) => setSpeed(Number(e.target.value))}
          className="h-8 rounded-md border border-input bg-transparent px-2 text-xs"
          data-testid="recruitment-interview-player-speed"
          aria-label="Playback speed"
        >
          {SPEED_STEPS.map((s) => (
            <option key={s} value={s}>
              {s.toFixed(2)}x
            </option>
          ))}
        </select>
        {kind === "video" && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void toggleFullscreen()}
            data-testid="recruitment-interview-player-fullscreen"
            aria-label="Fullscreen"
          >
            <Maximize className="size-3.5" />
          </Button>
        )}
      </div>
    </div>
  );
}
