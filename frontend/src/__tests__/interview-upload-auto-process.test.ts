import { afterEach, describe, expect, it, vi } from "vitest";

const post = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { post: (...args: unknown[]) => post(...args) },
}));

import { uploadInterviewMedia } from "@/lib/interview-upload";

// HRP-1031: with "Transcribe and run AI analysis automatically" ticked, a
// ready pdf/txt transcript must still ask for the chain - the backend skips
// only the transcribe hop and runs the analysis.
describe("uploadInterviewMedia - auto_process", () => {
  afterEach(() => {
    post.mockReset();
    vi.unstubAllGlobals();
  });

  async function completeBody(
    name: string,
    type: string,
    autoProcess: boolean,
  ) {
    post.mockImplementation(async (url: string) => {
      if (url.endsWith("/upload/init")) {
        return { upload_id: "u1", part_size: 1024, total_parts: 1 };
      }
      if (url.endsWith("/upload/part-url")) return { url: "https://s3/part" };
      return { id: "iv" };
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(null, { status: 200, headers: { ETag: '"e1"' } }),
      ),
    );
    await uploadInterviewMedia(
      "iv",
      new File(["Interviewer: Hi"], name, { type }),
      {
        autoProcess,
      },
    );
    const complete = post.mock.calls.find(([url]) =>
      String(url).includes("/upload/complete"),
    );
    return complete?.[1] as { auto_process: boolean };
  }

  it("sends the ticked box for a text transcript", async () => {
    expect((await completeBody("t.txt", "text/plain", true)).auto_process).toBe(
      true,
    );
  });

  it("sends an unticked box as off", async () => {
    expect(
      (await completeBody("t.pdf", "application/pdf", false)).auto_process,
    ).toBe(false);
  });

  it("keeps sending the box for a recording", async () => {
    expect((await completeBody("a.mp3", "audio/mpeg", true)).auto_process).toBe(
      true,
    );
  });
});
