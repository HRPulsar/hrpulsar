// @vitest-environment jsdom
//
// A page translator (Yandex Browser's built-in one here, Google Translate
// likewise) swaps React's text nodes for its own wrappers. The next commit
// that removes that text, or inserts next to it, used to throw NotFoundError
// and blank the app through global-error — seen on /coverage/[id] right
// after creating an initiative. The first test pins the crash, so it runs
// before the guard patches Node.prototype for the rest of the file.

import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import { guardDomAgainstTranslators } from "@/lib/translator-dom-guard";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function Label({ show, badge }: { show: boolean; badge: boolean }) {
  return (
    <p>
      {badge && <b>new</b>}
      {show ? "Coverage" : null}
    </p>
  );
}

function renderTranslated(next: { show: boolean; badge: boolean }) {
  const container = document.createElement("div");
  const root = createRoot(container);
  act(() => root.render(<Label show badge={false} />));
  const p = container.querySelector("p")!;
  const wrapper = document.createElement("ya-tr-span");
  wrapper.textContent = "Abdeckung";
  p.replaceChild(wrapper, p.firstChild!);
  act(() => root.render(<Label {...next} />));
  return p;
}

describe("translator DOM guard", () => {
  it("without the guard, a translated text node crashes the commit", () => {
    const crash = (fn: () => void) => {
      try {
        fn();
      } catch (e) {
        return (e as Error).name;
      }
    };
    expect(crash(() => renderTranslated({ show: false, badge: false }))).toBe("NotFoundError");
    expect(crash(() => renderTranslated({ show: true, badge: true }))).toBe("NotFoundError");
  });

  it("with the guard, removing and inserting next to translated text is survivable", () => {
    guardDomAgainstTranslators();
    expect(() => renderTranslated({ show: false, badge: false })).not.toThrow();
    // The inserted element stays visible, just after the translated text.
    expect(renderTranslated({ show: true, badge: true }).innerHTML).toBe(
      "<ya-tr-span>Abdeckung</ya-tr-span><b>new</b>",
    );
  });
});
