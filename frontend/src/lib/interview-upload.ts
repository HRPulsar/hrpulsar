/**
 * Shared chunked-upload client for interview media (HRP-202 REDO).
 *
 * The candidate-card bulk flow and the interview-detail upload zone both
 * speak the same TUS-style protocol: init -> per-part presigned PUT ->
 * complete. This module owns the protocol so the two surfaces cannot
 * drift; the detail-page zone keeps its own pause/resume UX on top.
 */

import { api } from "@/lib/api";
import type {
  InitUploadResponse,
  Interview,
  PartUrlResponse,
} from "@/lib/types";

export const MEDIA_MAX_BYTES = 500 * 1024 * 1024;
export const TRANSCRIPT_MAX_BYTES = 10 * 1024 * 1024;

export const AUDIO_MIME = new Set([
  "audio/mpeg",
  "audio/mp3",
  "audio/wav",
  "audio/x-wav",
  "audio/wave",
  "audio/mp4",
  "audio/x-m4a",
  "audio/m4a",
]);
export const VIDEO_MIME = new Set([
  "video/mp4",
  "video/webm",
  "video/quicktime",
  "video/x-msvideo",
  "video/avi",
]);
export const TRANSCRIPT_MIME = new Set(["application/pdf", "text/plain"]);

// Browsers leave `File.type` empty for formats they do not recognise
// (AVI is the usual offender), so extension is the fallback signal.
const EXT_KIND: Record<string, "audio" | "video" | "text_transcript"> = {
  mp3: "audio",
  wav: "audio",
  m4a: "audio",
  mp4: "video",
  webm: "video",
  mov: "video",
  avi: "video",
  pdf: "text_transcript",
  txt: "text_transcript",
};

const EXT_MIME: Record<string, string> = {
  mp3: "audio/mpeg",
  wav: "audio/wav",
  m4a: "audio/x-m4a",
  mp4: "video/mp4",
  webm: "video/webm",
  mov: "video/quicktime",
  avi: "video/x-msvideo",
  pdf: "application/pdf",
  txt: "text/plain",
};

export function fileExtension(name: string): string {
  const idx = name.lastIndexOf(".");
  return idx >= 0 ? name.slice(idx + 1).toLowerCase() : "";
}

export function detectKind(
  file: File,
): "audio" | "video" | "text_transcript" | null {
  const mime = (file.type || "").toLowerCase();
  if (AUDIO_MIME.has(mime) || mime.startsWith("audio/")) return "audio";
  if (VIDEO_MIME.has(mime) || mime.startsWith("video/")) return "video";
  if (TRANSCRIPT_MIME.has(mime)) return "text_transcript";
  return EXT_KIND[fileExtension(file.name)] ?? null;
}

// Single source of truth for both upload surfaces' <input accept=…>.
export const UPLOAD_ACCEPT_ATTR =
  ".mp3,.wav,.m4a,.mp4,.webm,.mov,.avi,.pdf,.txt," +
  "audio/*,video/*,application/pdf,text/plain";

export function effectiveMime(file: File): string {
  return (
    file.type ||
    EXT_MIME[fileExtension(file.name)] ||
    "application/octet-stream"
  );
}

async function putChunk(url: string, chunk: Blob, attempt = 0): Promise<string> {
  try {
    const res = await fetch(url, { method: "PUT", body: chunk });
    if (!res.ok) {
      throw new Error(`S3 PUT failed (HTTP ${res.status})`);
    }
    const etag = res.headers.get("ETag") || res.headers.get("etag");
    if (!etag) {
      throw new Error("S3 did not return an ETag");
    }
    return etag.replace(/"/g, "");
  } catch (err) {
    if (attempt < 2) {
      await new Promise((r) => setTimeout(r, 500 * Math.pow(3, attempt)));
      return putChunk(url, chunk, attempt + 1);
    }
    throw err;
  }
}

export interface UploadMediaOptions {
  autoProcess?: boolean;
  onProgress?: (fraction: number) => void;
}

/**
 * Upload one media/transcript file to an existing interview and finalize
 * it. Aborts the S3 multipart on failure so no orphan parts survive.
 */
export async function uploadInterviewMedia(
  interviewId: string,
  file: File,
  { autoProcess = false, onProgress }: UploadMediaOptions = {},
): Promise<Interview> {
  const kind = detectKind(file);
  if (kind === null) {
    throw new Error(`Unsupported file type: ${file.name}`);
  }
  const limit = kind === "text_transcript" ? TRANSCRIPT_MAX_BYTES : MEDIA_MAX_BYTES;
  if (file.size > limit) {
    throw new Error(
      `${file.name} is larger than ${Math.floor(limit / (1024 * 1024))} MB`,
    );
  }

  const mimeType = effectiveMime(file);
  const init = await api.post<InitUploadResponse>(
    `/recruitment/interviews/${interviewId}/upload/init`,
    {
      filename: file.name,
      mime_type: mimeType,
      size_bytes: file.size,
      kind: kind === "text_transcript" ? "audio" : kind,
    },
  );

  const parts: Array<{ part_number: number; etag: string }> = [];
  try {
    for (let n = 1; n <= init.total_parts; n++) {
      const start = (n - 1) * init.part_size;
      const end = Math.min(start + init.part_size, file.size);
      const partUrl = await api.post<PartUrlResponse>(
        `/recruitment/interviews/${interviewId}/upload/part-url`,
        { upload_id: init.upload_id, part_number: n },
      );
      const etag = await putChunk(partUrl.url, file.slice(start, end));
      parts.push({ part_number: n, etag });
      onProgress?.(end / file.size);
    }
    const query = `kind=${kind}&filename=${encodeURIComponent(
      file.name,
    )}&mime_type=${encodeURIComponent(mimeType)}`;
    return await api.post<Interview>(
      `/recruitment/interviews/${interviewId}/upload/complete?${query}`,
      {
        upload_id: init.upload_id,
        parts,
        // Text transcripts skip the chain — there is nothing to transcribe.
        auto_process: autoProcess && kind !== "text_transcript",
      },
    );
  } catch (err) {
    try {
      await api.post(`/recruitment/interviews/${interviewId}/upload/abort`, {
        upload_id: init.upload_id,
      });
    } catch {
      /* orphan cleanup job covers the rest */
    }
    throw err;
  }
}
