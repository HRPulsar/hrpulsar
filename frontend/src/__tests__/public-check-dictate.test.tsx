// @vitest-environment jsdom
//
// HRP-947: dictating the description of the public process check. The
// microphone button exists only where the browser can record in a format
// the backend takes; it records with the native MediaRecorder (WebM/Opus,
// else MP4 for Safari), stops by hand or at the length limit, and the
// recognised text goes after what is typed - never over it - with the
// cursor at its end and the check marked as dictated. A refused microphone
// and every refusal of the endpoint read as their own sentence.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import { ApiError } from "@/lib/api";
import { DESCRIPTION_MAX, VOICE_MAX_SECONDS, VOICE_TIMEOUT_MS } from "@/lib/api/public-check";

const { createCheck, transcribe, gate } = vi.hoisted(() => ({
  createCheck: vi.fn(),
  transcribe: vi.fn(),
  gate: { widget: null, token: null, isReady: true, failed: false, reset: () => {} },
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/turnstile", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/turnstile")>()),
  useTurnstileGate: () => gate,
}));
vi.mock("@/lib/api/public-check", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/public-check")>()),
  createCheck,
  transcribe,
}));

const { CheckForm } = await import("@/components/public-check/check-form");

const t = enMessages.publicCheck;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
Element.prototype.scrollIntoView = vi.fn();

/** The browser's recorder: records "voice" in the container it was given. */
class FakeRecorder {
  static supported: string[] = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  static instances: FakeRecorder[] = [];
  static isTypeSupported(type: string) {
    return FakeRecorder.supported.includes(type);
  }
  state: "inactive" | "recording" = "inactive";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  constructor(
    public stream: { getTracks: () => { stop: () => void }[] },
    public options: { mimeType?: string } = {},
  ) {
    FakeRecorder.instances.push(this);
  }
  get mimeType() {
    return this.options.mimeType ?? "";
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["voice"], { type: this.mimeType }) });
    this.onstop?.();
  }
}

const track = { stop: vi.fn() };
const getUserMedia = vi.fn();

function installRecorder() {
  Object.assign(globalThis, { MediaRecorder: FakeRecorder });
  Object.defineProperty(navigator, "mediaDevices", {
    value: { getUserMedia },
    configurable: true,
  });
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  // A clock the tests move; timers stay real (the cursor waits a frame).
  vi.useFakeTimers({ toFake: ["Date"] });
  createCheck.mockReset();
  transcribe.mockReset();
  getUserMedia.mockReset().mockResolvedValue({ getTracks: () => [track] });
  track.stop.mockReset();
  FakeRecorder.instances = [];
  FakeRecorder.supported = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  installRecorder();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
  delete (globalThis as { MediaRecorder?: unknown }).MediaRecorder;
  delete (navigator as { mediaDevices?: unknown }).mediaDevices;
});

async function render() {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages} timeZone="UTC">
        <CheckForm resultBase="/r" utm={null} />
      </NextIntlClientProvider>,
    );
  });
}

const byId = <T extends HTMLElement = HTMLElement>(id: string) =>
  container.querySelector<T>(`[data-testid="${id}"]`);

const button = () => byId<HTMLButtonElement>("check-btn-dictate")!;
const status = () => byId("check-dictate-status")!;
const field = () => byId<HTMLTextAreaElement>("check-input-description")!;

async function click(el: HTMLElement) {
  await act(async () => el.click());
}

async function type(value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
  await act(async () => {
    setter.call(field(), value);
    field().dispatchEvent(new Event("input", { bubbles: true }));
  });
}

/** Let ``ms`` of recording pass (the clock the recorder reads). */
function speak(ms = 2000) {
  vi.setSystemTime(Date.now() + ms);
}

/** Record a couple of seconds and stop by hand; the transcription answers
 * ``answer`` (or refuses with it). */
async function dictate(answer: unknown, refuse = false) {
  if (refuse) transcribe.mockRejectedValueOnce(answer);
  else transcribe.mockResolvedValueOnce(answer);
  await click(button());
  speak();
  await click(button());
  // The cursor is placed on the next frame.
  await act(async () => new Promise<void>((done) => requestAnimationFrame(() => done())));
}

describe("the microphone button", () => {
  it("is not there without MediaRecorder", async () => {
    delete (globalThis as { MediaRecorder?: unknown }).MediaRecorder;
    await render();
    expect(byId("check-btn-dictate")).toBeNull();
    expect(byId("check-dictate-status")).toBeNull();
  });

  it("is not there without getUserMedia (an insecure page)", async () => {
    Object.defineProperty(navigator, "mediaDevices", { value: undefined, configurable: true });
    await render();
    expect(byId("check-btn-dictate")).toBeNull();
  });

  it("is not there when the browser records in no format the backend takes", async () => {
    FakeRecorder.supported = ["audio/x-whatever"];
    await render();
    expect(byId("check-btn-dictate")).toBeNull();
  });

  it("records WebM/Opus where it can and MP4 on Safari", async () => {
    await render();
    await click(button());
    expect(FakeRecorder.instances[0].options.mimeType).toBe("audio/webm;codecs=opus");

    act(() => root.unmount());
    root = createRoot(container);
    FakeRecorder.supported = ["audio/mp4"];
    await render();
    await click(button());
    expect(FakeRecorder.instances[1].options.mimeType).toBe("audio/mp4");
  });
});

describe("a recording", () => {
  it("goes through recording, transcribing and back, the text after what is typed", async () => {
    await render();
    await type("We receive the goods.");
    expect(button().getAttribute("aria-pressed")).toBe("false");
    expect(status().getAttribute("aria-live")).toBe("polite");

    await click(button());
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(button().getAttribute("aria-pressed")).toBe("true");
    expect(status().dataset.state).toBe("recording");
    expect(status().textContent).toBe(t.voiceRecording);
    expect(byId("check-dictate-timer")!.textContent).toBe("0:00 / 3:00");

    let answer!: (value: unknown) => void;
    transcribe.mockReturnValueOnce(new Promise((done) => (answer = done)));
    speak();
    await click(button());
    expect(status().dataset.state).toBe("transcribing");
    expect(status().textContent).toBe(t.voiceTranscribing);
    expect(button().disabled).toBe(true);
    expect(byId("check-dictate-timer")).toBeNull();
    // The microphone is released as soon as the recording stops.
    expect(track.stop).toHaveBeenCalled();
    const sent = transcribe.mock.calls[0][0] as Blob;
    expect(sent.type).toBe("audio/webm;codecs=opus");

    await act(async () => answer({ text: "  Then we check them against the order. ", language: "english" }));
    await act(async () => new Promise<void>((done) => requestAnimationFrame(() => done())));
    expect(field().value).toBe("We receive the goods.\nThen we check them against the order.");
    expect(status().dataset.state).toBe("added");
    expect(status().textContent).toBe(t.voiceAdded);
    expect(button().disabled).toBe(false);
    expect(button().getAttribute("aria-pressed")).toBe("false");
    // The cursor waits at the end of the text for corrections.
    expect(document.activeElement).toBe(field());
    expect(field().selectionStart).toBe(field().value.length);
  });

  it("fills an empty field and marks the check as dictated, an example unmarks it", async () => {
    // Refused, so the form can be sent again (a created check leaves the page).
    createCheck.mockRejectedValue(new ApiError(429, "busy", undefined, "public_check_rate_limited"));
    await render();
    await dictate({ text: "Every month we close the books and report.", language: null });
    expect(field().value).toBe("Every month we close the books and report.");

    await act(async () => {
      byId("check-form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect(createCheck.mock.calls[0][0]).toMatchObject({
      description: "Every month we close the books and report.",
      dictated: true,
    });

    await click(byId("check-example-hiring")!);
    await act(async () => {
      byId("check-form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect(createCheck.mock.calls[1][0]).not.toHaveProperty("dictated");
  });

  it("stops itself at the length limit", async () => {
    vi.useRealTimers();
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    transcribe.mockReturnValueOnce(new Promise(() => {}));
    await render();
    await click(button());
    await act(async () => vi.advanceTimersByTime(65_000));
    expect(byId("check-dictate-timer")!.textContent).toBe("1:05 / 3:00");
    expect(FakeRecorder.instances[0].state).toBe("recording");

    await act(async () => vi.advanceTimersByTime((VOICE_MAX_SECONDS - 65) * 1000));
    expect(FakeRecorder.instances[0].state).toBe("inactive");
    expect(transcribe).toHaveBeenCalledTimes(1);
    expect(status().dataset.state).toBe("transcribing");
    expect(status().textContent).toBe(t.voiceTranscribingAtLimit.replace("{max}", "3"));
  });

  it("explains a refused microphone and records nothing", async () => {
    getUserMedia.mockRejectedValueOnce(new DOMException("denied", "NotAllowedError"));
    await render();
    await click(button());
    expect(FakeRecorder.instances).toHaveLength(0);
    expect(status().dataset.state).toBe("error");
    expect(status().textContent).toBe(t.voiceErrorDenied);
    expect(button().getAttribute("aria-pressed")).toBe("false");
  });

  it("tells a missing microphone from a refused one", async () => {
    getUserMedia.mockRejectedValueOnce(new DOMException("none", "NotFoundError"));
    await render();
    await click(button());
    expect(status().textContent).toBe(t.voiceErrorNoMic);
  });

  it("leaves the field alone when no speech was heard", async () => {
    await render();
    await type("We receive the goods.");
    await dictate({ text: "   ", language: null });
    expect(field().value).toBe("We receive the goods.");
    expect(status().textContent).toBe(t.voiceErrorEmpty);
  });

  it.each([
    ["public_check_rate_limited", 429, t.voiceErrorRateLimited],
    ["public_check_daily_limit", 429, t.voiceErrorDailyLimit],
    ["public_check_voice_too_large", 413, t.voiceErrorTooLong],
    ["public_check_voice_too_long", 413, t.voiceErrorTooLong],
    ["public_check_unavailable", 503, t.voiceErrorUnavailable],
    ["public_check_voice_unsupported", 415, t.voiceErrorFormat],
    ["public_check_voice_unavailable", 503, t.voiceErrorUnavailable],
    ["something_new", 500, t.voiceErrorGeneric],
  ])("reads %s as its own sentence", async (code, statusCode, sentence) => {
    await render();
    await type("We receive the goods.");
    await dictate(new ApiError(statusCode, "refused", undefined, code), true);
    expect(status().dataset.state).toBe("error");
    expect(status().textContent).toBe(sentence);
    expect(field().value).toBe("We receive the goods.");
  });

  it("does not send a tap shorter than a second", async () => {
    await render();
    await click(button());
    speak(400);
    await click(button());
    expect(transcribe).not.toHaveBeenCalled();
    expect(track.stop).toHaveBeenCalled();
    expect(status().dataset.state).toBe("error");
    expect(status().textContent).toBe(t.voiceErrorEmpty);
    expect(button().disabled).toBe(false);
  });

  it("releases the microphone and sends nothing when the page goes mid-recording", async () => {
    await render();
    await click(button());
    act(() => root.unmount());
    root = createRoot(container);
    expect(track.stop).toHaveBeenCalled();
    expect(transcribe).not.toHaveBeenCalled();
  });
});

describe("asking for the microphone (review M1)", () => {
  function pendingPermission() {
    let grant!: (stream: unknown) => void;
    getUserMedia.mockReturnValueOnce(new Promise((done) => (grant = done)));
    return (stream: unknown = { getTracks: () => [track] }) => grant(stream);
  }

  it("starts one recorder however often the button is clicked while the prompt is open", async () => {
    const grant = pendingPermission();
    await render();
    await click(button());
    await click(button());
    await click(button());
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    await act(async () => grant());
    expect(FakeRecorder.instances).toHaveLength(1);
    expect(status().dataset.state).toBe("recording");
    expect(track.stop).not.toHaveBeenCalled();
  });

  it("releases a microphone granted after the visitor left the page", async () => {
    const grant = pendingPermission();
    await render();
    await click(button());
    act(() => root.unmount());
    root = createRoot(container);
    await act(async () => grant());
    expect(FakeRecorder.instances).toHaveLength(0);
    expect(track.stop).toHaveBeenCalled();
  });
});

describe("a slow transcription (review m2)", () => {
  it("reads the page's own timeout as unavailable", async () => {
    await render();
    await dictate(new DOMException("signal timed out", "TimeoutError"), true);
    expect(status().dataset.state).toBe("error");
    expect(status().textContent).toBe(t.voiceErrorUnavailable);
  });

  it("sends the recording as multipart under a timeout a little past the server's", async () => {
    const actual = await vi.importActual<typeof import("@/lib/api/public-check")>(
      "@/lib/api/public-check",
    );
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ text: "ok", language: null }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const timeout = vi.spyOn(AbortSignal, "timeout");
    try {
      await actual.transcribe(new Blob(["voice"], { type: "audio/webm" }));
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toMatch(/\/public-check\/transcribe$/);
      expect(init.body).toBeInstanceOf(FormData);
      expect((init.body as FormData).get("audio")).toBeInstanceOf(Blob);
      // The browser sets the multipart type with its boundary.
      expect(init.headers).not.toHaveProperty("Content-Type");
      expect(timeout).toHaveBeenCalledWith(VOICE_TIMEOUT_MS);
      expect(init.signal).toBeInstanceOf(AbortSignal);
      expect(VOICE_TIMEOUT_MS).toBeGreaterThan(120_000);
    } finally {
      vi.unstubAllGlobals();
      timeout.mockRestore();
    }
  });
});

describe("the dictated text and the form (review m3, m4)", () => {
  async function submitForm() {
    await act(async () => {
      byId("check-form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
  }

  it("keeps a dictation past the limit whole, shows it and blocks sending", async () => {
    await render();
    await type("x".repeat(DESCRIPTION_MAX - 10));
    await dictate({ text: "and then we ship the goods to the customer.", language: null });
    // Never cut: the visitor shortens it.
    expect(field().value).toBe(`${"x".repeat(DESCRIPTION_MAX - 10)}\nand then we ship the goods to the customer.`);
    expect(byId("check-description-count")!.dataset.overLimit).toBe("true");
    expect(byId("check-description-hint")!.textContent).toBe(
      t.errorDescriptionLength.replace("{min}", "20").replace("{max}", String(DESCRIPTION_MAX)),
    );
    expect(field().getAttribute("aria-invalid")).toBe("true");
    expect(byId<HTMLButtonElement>("check-btn-submit")!.disabled).toBe(true);
    await submitForm();
    expect(createCheck).not.toHaveBeenCalled();

    await type("x".repeat(DESCRIPTION_MAX));
    expect(byId("check-description-count")!.dataset.overLimit).toBeUndefined();
    expect(byId<HTMLButtonElement>("check-btn-submit")!.disabled).toBe(false);
  });

  it("forgets the dictation once the field is emptied", async () => {
    createCheck.mockRejectedValue(new ApiError(429, "busy", undefined, "public_check_rate_limited"));
    await render();
    await dictate({ text: "Every month we close the books and report.", language: null });
    await type("");
    await type("We now type the process by hand, step by step.");
    await submitForm();
    expect(createCheck.mock.calls[0][0]).not.toHaveProperty("dictated");
  });
});
