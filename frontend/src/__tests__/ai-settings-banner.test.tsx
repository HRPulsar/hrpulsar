// @vitest-environment jsdom
//
// HRP-1241: the banner on generation pages names the temperature only when
// the workspace's model takes it.

import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { AISettings } from "@/lib/api/ai-settings";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ canViewSection: () => true }),
}));
vi.mock("@/lib/api/ai-settings", () => ({ aiSettingsApi: { get: vi.fn() } }));

const { AISettingsBanner } = await import(
  "@/components/specialization/ai-settings-banner"
);
const { aiSettingsApi } = await import("@/lib/api/ai-settings");

const settings = (applies: boolean) =>
  ({
    effective_model: "claude-sonnet-5-5",
    effort_level: "balanced",
    effective_temperature: 0.3,
    effective_temperature_applies: applies,
  }) as AISettings;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(applies: boolean): Promise<string> {
  vi.mocked(aiSettingsApi.get).mockResolvedValue(settings(applies));
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <AISettingsBanner />
      </NextIntlClientProvider>,
    );
  });
  return container.querySelector('[data-testid="ai-settings-banner"]')!.textContent!;
}

describe("AISettingsBanner", () => {
  it("names the temperature when the model takes it", async () => {
    expect(await render(true)).toContain("temperature 0.30");
  });

  it("leaves the temperature out when the model sets its own sampling", async () => {
    const text = await render(false);
    expect(text).toContain("claude-sonnet-5-5");
    expect(text).toContain("balanced");
    expect(text).not.toContain("temperature");
  });
});
