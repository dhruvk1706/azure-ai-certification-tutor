// @vitest-environment jsdom
// Design system: tabs follow the WAI-ARIA keyboard pattern.
import { useState } from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test } from "vitest";
import { Tabs } from "../../frontend/src/ui";

const TABS = [
  ["a", "Alpha"],
  ["b", "Beta"],
  ["c", "Gamma"],
] as const;

function Demo() {
  const [tab, setTab] = useState<"a" | "b" | "c">("a");
  return (
    <Tabs label="Demo" tabs={TABS} value={tab} onChange={setTab}>
      Panel {tab}
    </Tabs>
  );
}

test("arrow keys, Home and End move focus and selection, with one tab stop", () => {
  (
    globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  act(() => root.render(<Demo />));

  const tabs = () => [
    ...container.querySelectorAll<HTMLElement>('[role="tab"]'),
  ];
  const press = (key: string) =>
    act(() => {
      document.activeElement!.dispatchEvent(
        new KeyboardEvent("keydown", { key, bubbles: true }),
      );
    });
  const selected = () =>
    tabs().find((t) => t.getAttribute("aria-selected") === "true")!.textContent;

  expect(tabs().map((t) => t.tabIndex)).toEqual([0, -1, -1]);
  tabs()[0].focus();

  press("ArrowLeft");
  expect(selected()).toBe("Gamma");
  expect(document.activeElement?.textContent).toBe("Gamma");
  press("Home");
  expect(selected()).toBe("Alpha");
  press("ArrowRight");
  expect(selected()).toBe("Beta");
  press("End");
  expect(selected()).toBe("Gamma");
  expect(tabs().map((t) => t.tabIndex)).toEqual([-1, -1, 0]);
  expect(container.querySelector('[role="tabpanel"]')?.textContent).toBe(
    "Panel c",
  );

  act(() => root.unmount());
  container.remove();
});
