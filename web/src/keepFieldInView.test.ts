import { afterEach, describe, expect, it, vi } from "vitest";
import { installKeepFieldInView } from "./keepFieldInView";

describe("keepFieldInView", () => {
  let remove: (() => void) | null = null;
  afterEach(() => {
    remove?.();
    document.body.innerHTML = "";
  });

  it("brings the focused text field into view when the viewport shrinks, and only then", () => {
    document.body.innerHTML = `<input id="q" type="search"><button id="b">Go</button>`;
    const input = document.getElementById("q") as HTMLInputElement;
    const scroll = vi.fn();
    input.scrollIntoView = scroll;
    const win = { innerHeight: 844, visualViewport: null, document } as unknown as Window;
    const listeners: Array<() => void> = [];
    (win as unknown as { addEventListener: (t: string, f: () => void) => void }).addEventListener = (_t, f) => listeners.push(f);
    (win as unknown as { removeEventListener: () => void }).removeEventListener = () => undefined;
    remove = installKeepFieldInView(win);
    input.focus();
    (win as { innerHeight: number }).innerHeight = 420;
    listeners.forEach((f) => f());
    expect(scroll).toHaveBeenCalledWith({ block: "nearest" });
    scroll.mockClear();
    (win as { innerHeight: number }).innerHeight = 844;
    listeners.forEach((f) => f());
    expect(scroll).not.toHaveBeenCalled();
    (document.getElementById("b") as HTMLButtonElement).focus();
    (win as { innerHeight: number }).innerHeight = 400;
    listeners.forEach((f) => f());
    expect(scroll).not.toHaveBeenCalled();
  });
});
