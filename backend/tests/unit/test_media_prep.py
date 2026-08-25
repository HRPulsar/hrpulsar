"""Unit tests for app.modules.recruitment.media_prep (HRP-646).

The ffmpeg-backed tests are skipped where the binary is absent — it ships
in the backend image, but a bare dev machine or CI runner may not have it,
and its absence is a supported degradation, not a failure.
"""

import os
import subprocess

import pytest
from app.modules.recruitment import media_prep

ffmpeg_only = pytest.mark.skipif(
    not media_prep.ffmpeg_available(), reason="ffmpeg is not installed"
)


def _sine(path, seconds: int) -> str:
    """A synthetic recording — no fixture file to keep in the repo."""
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-b:a",
            "128k",
            str(path),
        ],
        capture_output=True,
        check=True,
    )
    return str(path)


@ffmpeg_only
def test_extract_audio_produces_mono_opus(tmp_path):
    source = _sine(tmp_path / "source.mp3", 20)
    dest = str(tmp_path / f"audio{media_prep.AUDIO_SUFFIX}")

    assert media_prep.extract_audio(source, dest) == dest

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=channels,codec_name",
            "-of",
            "default=nw=1:nk=1",
            dest,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    # opus always reports 48 kHz in the container whatever it was fed, so
    # the codec and the channel count are what can be asserted here.
    assert sorted(probe.stdout.split()) == ["1", "opus"]
    # The whole point: the provider gets a fraction of the original bytes.
    assert os.path.getsize(dest) < os.path.getsize(source)


@ffmpeg_only
def test_extract_audio_returns_none_for_a_container_ffmpeg_cannot_read(tmp_path):
    """A codec we cannot handle costs quality, never the interview: the
    caller falls back to sending the original file."""
    source = tmp_path / "broken.mp4"
    source.write_bytes(b"not a media file at all")

    assert media_prep.extract_audio(str(source), str(tmp_path / "out.mp3")) is None


@ffmpeg_only
def test_split_audio_cuts_overlapping_chunks_under_the_limit(tmp_path, monkeypatch):
    source = _sine(tmp_path / "source.mp3", 60)
    audio = media_prep.extract_audio(
        source, str(tmp_path / f"audio{media_prep.AUDIO_SUFFIX}")
    )
    assert audio is not None

    # Force several chunks out of a short file: a ceiling of a third of it.
    limit = os.path.getsize(audio) // 3
    monkeypatch.setattr(media_prep, "_MIN_CHUNK_SECONDS", 1.0)
    chunks = media_prep.split_audio(audio, str(tmp_path), max_bytes=limit)

    assert len(chunks) >= 3
    assert chunks[0][1] == 0.0
    offsets = [offset for _, offset in chunks]
    assert offsets == sorted(offsets)
    duration = media_prep.probe_duration(audio)
    assert duration is not None
    # Every chunk fits the ceiling, and together they cover the recording.
    for path, offset in chunks:
        assert 0 < os.path.getsize(path) <= limit
        assert offset < duration
    assert chunks[-1][1] + media_prep.probe_duration(chunks[-1][0]) >= duration - 1


@ffmpeg_only
def test_split_audio_leaves_a_recording_that_already_fits_alone(tmp_path):
    source = _sine(tmp_path / "source.mp3", 5)
    audio = media_prep.extract_audio(
        source, str(tmp_path / f"audio{media_prep.AUDIO_SUFFIX}")
    )
    assert audio is not None

    chunks = media_prep.split_audio(audio, str(tmp_path), max_bytes=25 * 1024 * 1024)

    assert chunks == [(audio, 0.0)]


def test_split_audio_declines_a_file_it_cannot_probe(tmp_path):
    """No ffprobe reading, no chunking — the caller moves to the next
    provider instead of slicing blind."""
    junk = tmp_path / "junk.mp3"
    junk.write_bytes(b"\x00" * 4096)

    assert media_prep.split_audio(str(junk), str(tmp_path), max_bytes=1024) == []
