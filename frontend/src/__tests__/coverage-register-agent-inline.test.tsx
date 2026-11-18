// @vitest-environment jsdom
//
// HRP-1199: "I already use this" asked for the agent's name on every step,
// and typing the same name again was refused - the registry keeps names
// unique. The agents named before are offered now; picking one binds it to
// the step by adding the step's codes to it, never registering a twin.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { RegisteredAgent } from "@/lib/api/work";

const listAgents = vi.fn();
const getAgent = vi.fn();
const setAgentPrimitives = vi.fn();
const registerAgent = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { listAgents, getAgent, setAgentPrimitives, registerAgent },
}));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));

const { RegisterAgentInline, coverOverrides } = await import(
  "@/components/coverage/register-agent-inline"
);

const CHATGPT: RegisteredAgent = {
  id: "a-1",
  name: "ChatGPT",
  pack_id: "pack-extraction",
  primitive_overrides: [
    { code: "P3", mode: "add" },
    { code: "P5", mode: "remove" },
  ],
  effective_primitive_codes: ["P1", "P3"],
};
const CURSOR: RegisteredAgent = {
  id: "a-2",
  name: "Cursor",
  pack_id: "pack-drafting",
  primitive_overrides: [],
  effective_primitive_codes: ["P1", "P5"],
};

it("adds only the codes the agent lacks, and a needed code wins over its removal", () => {
  expect(coverOverrides(CHATGPT, ["P1", "P5", "P5"])).toEqual([
    { code: "P3", mode: "add" },
    { code: "P5", mode: "add" },
  ]);
  expect(coverOverrides(CHATGPT, ["P1", "P3"])).toBeNull();
});

let container: HTMLDivElement;
let root: Root;
const onRegistered = vi.fn();

beforeEach(() => {
  for (const fn of [
    listAgents,
    getAgent,
    setAgentPrimitives,
    registerAgent,
    toastSuccess,
    toastError,
    onRegistered,
  ]) {
    fn.mockReset();
  }
  listAgents.mockResolvedValue({ items: [CHATGPT, CURSOR], total: 2 });
  getAgent.mockImplementation(async (id: string) => (id === CHATGPT.id ? CHATGPT : CURSOR));
  setAgentPrimitives.mockResolvedValue(CHATGPT);
  registerAgent.mockResolvedValue({ id: "a-new" });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function open(packManual = false) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <RegisterAgentInline
          packId="pack-drafting"
          codes={["P1", "P5"]}
          packManual={packManual}
          testId="use"
          onRegistered={onRegistered}
        />
      </NextIntlClientProvider>,
    );
  });
  await act(async () => {
    byId("use")!.click();
  });
}

const byId = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);

async function type(value: string) {
  const input = byId("use-input") as HTMLInputElement;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    byId("use-save")!.click();
  });
}

it("offers the agents named before and binds the picked one to the step", async () => {
  await open();

  expect(byId("use-known")!.textContent).toContain(enMessages.coverage.agentPickExisting);
  expect(byId("use-agent-a-2")!.textContent).toBe("Cursor");
  await act(async () => {
    byId("use-agent-a-1")!.click();
  });

  expect(getAgent).toHaveBeenCalledWith("a-1");
  expect(setAgentPrimitives).toHaveBeenCalledWith("a-1", [
    { code: "P3", mode: "add" },
    { code: "P5", mode: "add" },
  ]);
  expect(registerAgent).not.toHaveBeenCalled();
  expect(toastSuccess).toHaveBeenCalledWith(enMessages.coverage.agentLinked);
  expect(onRegistered).toHaveBeenCalled();
});

it("binds an agent typed again by name instead of registering a twin", async () => {
  await open();
  await type("  cursor ");

  // Cursor covers P1 and P5 already: nothing to write, still linked.
  expect(getAgent).toHaveBeenCalledWith("a-2");
  expect(setAgentPrimitives).not.toHaveBeenCalled();
  expect(registerAgent).not.toHaveBeenCalled();
  expect(onRegistered).toHaveBeenCalled();
});

it("registers a new name as before", async () => {
  await open();
  await type("Claude");

  expect(registerAgent).toHaveBeenCalledWith({ name: "Claude", pack_id: "pack-drafting" });
  expect(toastSuccess).toHaveBeenCalledWith(enMessages.coverage.agentRegistered);
});

it("offers only the named pack's agents where the company named the pack", async () => {
  await open(true);

  expect(byId("use-agent-a-2")).not.toBeNull();
  expect(byId("use-agent-a-1")).toBeNull();
});

it("still takes a new name when the registry cannot be read", async () => {
  listAgents.mockRejectedValue(new Error("403"));
  await open();

  expect(byId("use-known")).toBeNull();
  expect(byId("use-input")).not.toBeNull();
});

it("drops an agent list that comes back after Cancel and a reopen", async () => {
  let first!: (value: { items: RegisteredAgent[]; total: number }) => void;
  listAgents
    .mockImplementationOnce(() => new Promise((resolve) => (first = resolve)))
    .mockResolvedValueOnce({ items: [CURSOR], total: 1 });

  await open();
  const cancel = [...document.querySelectorAll("button")].find(
    (b) => b.textContent === enMessages.coverage.cancel,
  )!;
  await act(async () => {
    cancel.click();
  });
  await act(async () => {
    byId("use")!.click();
  });
  await act(async () => {
    first({ items: [CHATGPT], total: 1 });
  });

  expect(byId("use-agent-a-2")).not.toBeNull();
  expect(byId("use-agent-a-1")).toBeNull();
});
