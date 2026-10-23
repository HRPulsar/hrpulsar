// @vitest-environment jsdom
//
// HRP-1067: the global search loaded one page per type (50 employees, 100
// assessments...) and filtered it in the browser, so anyone past that page
// was never found - and a manager's employee list stopped at their subtree.
// It now sends the query to the server, with `tenant_wide` for employees,
// and a slow answer to an earlier query cannot replace a newer one.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

const get = vi.fn();

vi.mock("@/lib/api", () => ({ api: { get } }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
// HRP-829 REDO: employee results need the employees section open.
const auth = { user: { id: "u-1", roles: ["employee"], sections: { employees: "view" } as Record<string, string> } };
vi.mock("@/context/auth-context", () => ({ useAuth: () => auth }));

const { GlobalSearch } = await import("@/components/global-search");

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  get.mockReset();
  auth.user.sections = { employees: "view" };
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const employee = (name: string) => ({
  items: [{ id: `e-${name}`, user_name: name, user_email: null, position_title: "Engineer" }],
});
const empty = { items: [] };

async function render() {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <GlobalSearch />
      </NextIntlClientProvider>,
    );
  });
}

async function type(value: string) {
  const input = container.querySelector<HTMLInputElement>('[data-testid="header-search"]')!;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  await act(async () => {
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function settle() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 350));
  });
}

it("asks the server with the query, tenant-wide for employees", async () => {
  get.mockImplementation((url: string) =>
    // The server matched on something the row does not show (an email
    // fragment, say): the old client filter would have dropped it.
    Promise.resolve(url.startsWith("/employees") ? employee("Bob Server-Matched") : empty),
  );
  await render();
  await type("zoe p");
  await settle();

  const urls = get.mock.calls.map(([url]) => url as string);
  expect(urls).toContain("/employees?q=zoe%20p&limit=5&tenant_wide=true");
  expect(urls).toContain("/assessments?q=zoe%20p&limit=5");
  expect(urls).toContain("/recruitment/vacancies?q=zoe%20p&limit=5");
  expect(urls).toContain("/recruitment/candidates?q=zoe%20p&limit=5");
  // The server already matched: nothing is filtered away client-side.
  expect(container.textContent).toContain("Bob Server-Matched");
});

it("sends the trimmed text and treats a blank query as none", async () => {
  get.mockResolvedValue(empty);
  await render();
  await type("   ");
  await settle();
  expect(get).not.toHaveBeenCalled();
  await type("  ab ");
  await settle();
  expect(get.mock.calls.map(([url]) => url)).toContain("/employees?q=ab&limit=5&tenant_wide=true");
});

it("keeps the newer query's results when an older answer arrives late", async () => {
  let releaseOld: (v: unknown) => void = () => undefined;
  get.mockImplementation((url: string) => {
    if (url.startsWith("/employees?q=al&")) return new Promise((r) => (releaseOld = r));
    if (url.startsWith("/employees?q=bob&")) return Promise.resolve(employee("Bob New"));
    return Promise.resolve(empty);
  });
  await render();
  await type("al");
  await settle();
  await type("bob");
  await settle();
  expect(container.textContent).toContain("Bob New");

  await act(async () => {
    releaseOld(employee("Al Old"));
  });
  expect(container.textContent).toContain("Bob New");
  expect(container.textContent).not.toContain("Al Old");
});

it("finds no employees where no employee card opens (HRP-829 REDO)", async () => {
  auth.user.sections = {};
  get.mockImplementation((url: string) =>
    Promise.resolve(url.startsWith("/employees") ? employee("Bob Hidden") : empty),
  );
  await render();
  await type("bob");
  await settle();
  const urls = get.mock.calls.map(([url]) => url as string);
  expect(urls.some((url) => url.startsWith("/employees"))).toBe(false);
  expect(urls).toContain("/assessments?q=bob&limit=5");
  expect(container.textContent).not.toContain("Bob Hidden");
});
