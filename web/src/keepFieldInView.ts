// keepFieldInView: when the viewport shrinks while a text field has focus (a
// phone's on-screen keyboard opening), bring that field back into view.
// Browsers differ here: some scroll the field into view themselves, others
// leave it under the keyboard. Moving it only as far as needed ("nearest")
// leaves a field that is already visible where it is.
const TEXT_FIELD = "input:not([type=button]):not([type=submit]):not([type=checkbox]):not([type=radio]):not([type=file]), textarea, select, [contenteditable=true]";

export function installKeepFieldInView(win: Window = window): () => void {
  let lastHeight = win.visualViewport?.height ?? win.innerHeight;
  const onResize = () => {
    const height = win.visualViewport?.height ?? win.innerHeight;
    const shrank = height < lastHeight;
    lastHeight = height;
    if (!shrank) return;
    const el = win.document.activeElement;
    if (el instanceof HTMLElement && el.matches(TEXT_FIELD)) el.scrollIntoView({ block: "nearest" });
  };
  const target: EventTarget = win.visualViewport ?? win;
  target.addEventListener("resize", onResize);
  return () => target.removeEventListener("resize", onResize);
}
