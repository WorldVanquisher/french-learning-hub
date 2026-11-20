import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

// Item 047: the startup placeholder in index.html. When a file the page names
// cannot be loaded (an expired cached page after an upgrade removed its old
// files), it says so at once, instead of the generic "still not loaded" line
// after eight seconds. Plain HTML, CSS and one inline listener.
const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
const inline = /<script>([\s\S]*?)<\/script>/.exec(html)![1];
const boot = /<div id="root">([\s\S]*?)<\/div><\/div>/.exec(html)![1] + "</div>";

afterEach(() => {
  document.body.innerHTML = "";
});

describe("the startup placeholder", () => {
  it("names the out-of-date page as soon as a script or stylesheet fails to load", () => {
    document.body.innerHTML = `<div id="root">${boot}</div>`;
    new Function(inline)();
    const gone = document.querySelector<HTMLElement>(".flh-boot-gone")!;
    expect(gone.hidden).toBe(true);
    const img = document.createElement("img");
    document.body.appendChild(img);
    img.dispatchEvent(new Event("error"));
    expect(gone.hidden).toBe(true);
    const script = document.createElement("script");
    document.body.appendChild(script);
    script.dispatchEvent(new Event("error"));
    expect(gone.hidden).toBe(false);
    expect(document.querySelector(".flh-boot")!.className).toBe("flh-boot flh-boot-stale");
    expect(gone.textContent).toMatch(/This copy of the page is out of date/);
    expect(gone.textContent).toMatch(/此页面副本已过期/);
  });

  it("does nothing once the application has replaced it", () => {
    document.body.innerHTML = `<div id="root"><main>app</main></div>`;
    new Function(inline)();
    const script = document.createElement("script");
    document.body.appendChild(script);
    expect(() => script.dispatchEvent(new Event("error"))).not.toThrow();
  });

  it("keeps the page's entry script the only module script", () => {
    expect(html.match(/<script\b[^>]*type="module"/g)).toHaveLength(1);
    expect(inline).not.toMatch(/fetch|XMLHttpRequest|location\s*=|reload\(/);
  });
});
