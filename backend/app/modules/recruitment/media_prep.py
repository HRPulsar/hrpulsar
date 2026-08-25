"""ffmpeg pre-processing of interview recordings (HRP-646).

A transcription provider is sent speech, not a screen recording: the video
track is dropped and the audio re-encoded to mono 16 kHz — the sample rate
every ASR model resamples to anyway — which turns an hour of interview
into a few MB instead of half a gigabyte.

That is also what makes the size-capped providers usable. Only they are
ever split: Deepgram takes the file whole, and its diarization numbers
speakers per request, so ``speaker_0`` of a second chunk need not be the
same person. Whisper — the one with the 25 MB ceiling — has no diarization
at all, so cutting a recording for it costs nothing.

ffmpeg is a soft dependency. Where the binary is missing, or the container
is one it cannot demux, every helper here returns nothing and the caller
sends the original file exactly as before.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

import httpx

logger = logging.getLogger(__name__)

# Mono opus at 32 kbps, resampled to 16 kHz: speech-grade, an hour of
# interview lands around 14 MB, and every provider in the chain reads ogg.
# Measured against a real interview, opus at this bitrate transcribes as
# well as uncompressed PCM eight times its size, and better than mp3 at
# the same bitrate — mp3 dropped words opus kept. This is the only place
# the encoding is decided.
_SAMPLE_RATE = "16000"
_BITRATE = "32k"
_CODEC = "libopus"
AUDIO_SUFFIX = ".ogg"

# ffmpeg runs against a local file, but a 500 MB source still takes a while
# to decode on a small worker.
_FFMPEG_TIMEOUT = 900
_PROBE_TIMEOUT = 60
_DOWNLOAD_TIMEOUT = 600

# Chunks overlap so a sentence cut in half is still transcribed whole by
# one side of the seam; the merge drops what the overlap duplicates.
CHUNK_OVERLAP_SECONDS = 5.0

# Aim below the provider's ceiling: the cut is by duration and the bitrate
# of a chunk is only approximately the file's average. The flat allowance
# on top covers the container headers every chunk carries whatever its
# length — proportional safety alone cannot.
_CHUNK_SAFETY = 0.9
_CHUNK_HEADER_ALLOWANCE = 16 * 1024

# Below this the arithmetic is telling us the file is not long but broken
# (a huge bitrate over a few seconds); chunking it would produce hundreds
# of requests, so we decline and let the caller fall through.
_MIN_CHUNK_SECONDS = 30.0


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("%s failed: %s", args[0], exc)
        return None


def fetch_to_file(url: str, dest: str) -> str:
    """Stream a presigned URL onto the worker's disk.

    The whole original lands there — up to the 500 MB upload cap — because
    ffmpeg needs a seekable input: an mp4 piped through stdin with its moov
    atom at the end cannot be demuxed.
    """

    with httpx.stream(
        "GET", url, timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True
    ) as response:
        response.raise_for_status()
        with open(dest, "wb") as handle:
            for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                handle.write(chunk)
    return dest


def extract_audio(source: str, dest: str) -> str | None:
    """Re-encode ``source`` into mono 16 kHz opus at ``dest``.

    Returns ``None`` when ffmpeg is unavailable or refuses the container —
    the caller then sends the untouched original, so a codec we cannot
    handle costs quality, never the interview.
    """

    if not ffmpeg_available():
        return None
    proc = _run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-i",
            source,
            "-vn",
            "-ac",
            "1",
            "-ar",
            _SAMPLE_RATE,
            "-c:a",
            _CODEC,
            "-b:a",
            _BITRATE,
            dest,
        ],
        _FFMPEG_TIMEOUT,
    )
    if proc is None or proc.returncode != 0 or not _size(dest):
        detail = proc.stderr.strip()[-400:] if proc is not None else "ffmpeg missing"
        logger.warning("Audio extraction failed, sending the original: %s", detail)
        return None
    logger.info(
        "Extracted audio: %s bytes -> %s bytes", _size(source), _size(dest)
    )
    return dest


def probe_duration(path: str) -> float | None:
    proc = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            path,
        ],
        _PROBE_TIMEOUT,
    )
    if proc is None or proc.returncode != 0:
        return None
    try:
        duration = float(proc.stdout.strip())
    except ValueError:
        return None
    return duration if duration > 0 else None


def split_audio(
    path: str, dest_dir: str, *, max_bytes: int
) -> list[tuple[str, float]]:
    """Cut ``path`` into overlapping chunks that fit ``max_bytes``.

    Returns ``(chunk_path, offset_seconds)`` pairs — the offset is what the
    caller adds to the chunk's timecodes to put it back on the recording's
    own clock. An empty list means the file cannot be split here (no
    ffprobe, unreadable duration, a failed cut); the caller falls through
    to the next provider.

    The cut is by time, not by byte count: chunk boundaries have to be
    expressible as timecodes for the merge, and the stream is copied rather
    than re-encoded, so the pass is cheap.
    """

    size = _size(path)
    duration = probe_duration(path)
    if not size or duration is None:
        return []

    usable = max_bytes * _CHUNK_SAFETY - _CHUNK_HEADER_ALLOWANCE
    chunk_seconds = usable / (size / duration) if usable > 0 else 0.0
    if chunk_seconds < _MIN_CHUNK_SECONDS:
        return []
    if chunk_seconds >= duration:
        return [(path, 0.0)]

    overlap = min(CHUNK_OVERLAP_SECONDS, chunk_seconds / 4)
    step = chunk_seconds - overlap
    suffix = os.path.splitext(path)[1] or AUDIO_SUFFIX
    chunks: list[tuple[str, float]] = []
    offset = 0.0
    while True:
        dest = os.path.join(dest_dir, f"chunk_{len(chunks):03d}{suffix}")
        proc = _run(
            [
                "ffmpeg",
                "-nostdin",
                "-y",
                "-ss",
                f"{offset:.3f}",
                "-t",
                f"{chunk_seconds:.3f}",
                "-i",
                path,
                "-c",
                "copy",
                dest,
            ],
            _FFMPEG_TIMEOUT,
        )
        if proc is None or proc.returncode != 0 or not _size(dest):
            logger.warning("Chunking failed at offset %.1fs, giving up", offset)
            return []
        chunks.append((dest, offset))
        if offset + chunk_seconds >= duration:
            return chunks
        offset += step


__all__ = [
    "AUDIO_SUFFIX",
    "CHUNK_OVERLAP_SECONDS",
    "extract_audio",
    "fetch_to_file",
    "ffmpeg_available",
    "probe_duration",
    "split_audio",
]
