// @vitest-environment jsdom
//
// HRP-829 REDO (QA 14.10): an employee's name is a link to their card only
// where the viewer may open that card - and that is the backend's answer
// (GET /employees/card-access, the rule of GET /employees/{id}), asked once
// per page for every name on it. With the employees section closed nothing
// is asked and every name is text. Who may open whose card - role, subtree,
// status - is pinned on the backend (test_employee_section_access.py).

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => ({ api: { get } }));

let user: { id: string; sections: Record<string, string> } | null = null;
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user }) }));

const { EmployeeName, resetCardAccess } = await import("@/components/employees/employee-name");

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  resetCardAccess();
  get.mockReset();
  user = { id: "u-1", sections: { employees: "view" } };
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(ids: (string | null)[]) {
  await act(async () => {
    root.render(
      <>
        {ids.map((id, i) => (
          <EmployeeName key={i} employeeId={id} testId={`name-${id ?? "none"}`} linkClassName="link">
            {`Person ${id}`}
          </EmployeeName>
        ))}
      </>,
    );
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 5));
  });
}

const cell = (id: string) => container.querySelector(`[data-testid="name-${id}"]`)!;
const asked = () => get.mock.calls.map(([url]) => String(url));

describe("EmployeeName", () => {
  it("links the names the backend opens and leaves the rest as text", async () => {
    get.mockResolvedValue(["active"]);
    await render(["active", "left"]);
    expect(cell("active").tagName).toBe("A");
    expect(cell("active").getAttribute("href")).toBe("/employees/active");
    expect(cell("active").className).toContain("link");
    expect(cell("left").tagName).toBe("SPAN");
    expect(cell("left").textContent).toBe("Person left");
  });

  it("asks once for every name on the page", async () => {
    get.mockResolvedValue([]);
    await render(["a", "b", "c", "a"]);
    expect(asked()).toEqual(["/employees/card-access?ids=a&ids=b&ids=c"]);
    // Rendered again (another tab of the page): answered from memory.
    await render(["b", "c"]);
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("asks nothing with the employees section closed: every name is text", async () => {
    user = { id: "u-1", sections: {} };
    get.mockResolvedValue(["a"]);
    await render(["a"]);
    expect(get).not.toHaveBeenCalled();
    expect(cell("a").tagName).toBe("SPAN");
  });

  it("is text without an employee id, and asks nothing for it", async () => {
    get.mockResolvedValue([]);
    await render([null]);
    expect(get).not.toHaveBeenCalled();
    expect(cell("none").tagName).toBe("SPAN");
  });

  it("stays text when the check fails", async () => {
    get.mockRejectedValue(new Error("offline"));
    await render(["a"]);
    expect(cell("a").tagName).toBe("SPAN");
  });

  it("asks again for another user or another level", async () => {
    get.mockResolvedValue(["a"]);
    await render(["a"]);
    expect(cell("a").tagName).toBe("A");
    user = { id: "u-2", sections: { employees: "view" } };
    get.mockResolvedValue([]);
    await render(["a"]);
    expect(get).toHaveBeenCalledTimes(2);
    expect(cell("a").tagName).toBe("SPAN");
  });

  it("splits a long page into requests of 100", async () => {
    get.mockResolvedValue([]);
    await render(Array.from({ length: 150 }, (_, i) => `e${i}`));
    expect(get).toHaveBeenCalledTimes(2);
    expect(asked()[0].split("ids=").length - 1).toBe(100);
    expect(asked()[1].split("ids=").length - 1).toBe(50);
  });
});
