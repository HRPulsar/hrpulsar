// @vitest-environment jsdom
//
// HRP-986: the server address on the recruitment LLM providers page.
// Azure and GigaChat are reached only through their own endpoint, so the
// form refuses them without one; the "leave it empty" hint is OpenAI's.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

const post = vi.fn<(...args: unknown[]) => Promise<unknown>>(() =>
  Promise.resolve({}),
);
const toastError = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(() => Promise.resolve([])),
    post: (...args: unknown[]) => post(...args),
  },
}));
vi.mock("sonner", () => ({
  toast: { error: (msg: string) => toastError(msg), success: vi.fn() },
}));
vi.mock("@/components/require-role", () => ({
  RequireRole: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/components/recruitment", () => ({
  RecruitmentBreadcrumbs: () => null,
}));

const Page = (
  await import("@/app/(dashboard)/recruitment/settings/llm-providers/page")
).default;

const rec = enMessages.recruitment;
let container: HTMLDivElement;
let root: Root;

beforeEach(async () => {
  post.mockClear();
  toastError.mockClear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <Page />
      </NextIntlClientProvider>,
    );
  });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const byTestId = <T extends HTMLElement>(id: string) =>
  container.querySelector(`[data-testid="${id}"]`) as T | null;

async function pick(provider: string) {
  const select = byTestId<HTMLSelectElement>("llm-input-provider")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(
      select,
      provider,
    );
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function type(id: string, value: string) {
  const input = byTestId<HTMLInputElement>(id)!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(
      input,
      value,
    );
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function create() {
  await act(async () => {
    byTestId<HTMLButtonElement>("llm-btn-create")!.click();
  });
}

it.each(["azure", "gigachat"])(
  "%s is not saved without its server address",
  async (provider) => {
    await pick(provider);
    await type("llm-input-model", "gpt-4o");
    expect(container.textContent).not.toContain(rec.llmBaseUrlHintOpenai);

    await create();

    expect(toastError).toHaveBeenCalledWith(rec.llmBaseUrlRequired);
    expect(post).not.toHaveBeenCalled();
  },
);

it("sends the address of a self-hosted server, with no key", async () => {
  await pick("openai");
  expect(container.textContent).toContain(rec.llmBaseUrlHintOpenai);
  await type("llm-input-model", "llama3.1");
  await type("llm-input-base-url", " http://localhost:11434/v1 ");

  await create();

  expect(post).toHaveBeenCalledWith("/recruitment/settings/llm-providers", {
    provider: "openai",
    model: "llama3.1",
    api_key: null,
    is_active: true,
    settings: { base_url: "http://localhost:11434/v1" },
  });
});

it("hides the address for providers that take none", async () => {
  await pick("gemini");
  expect(byTestId("llm-input-base-url")).toBeNull();
});
