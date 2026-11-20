import { useRef, useState } from "react";
import { useI18n, type MessageKey } from "../i18n";

// CopyLink (R2): a button that copies one of the demo's public links (a
// fragment link on this page, made absolute) and says so in a status line. The
// link names a screen only, never progress (practice answers, an open card).
// Copying uses the browser's clipboard on request; when the browser refuses
// (an insecure address, a denied permission), the link is shown selected in a
// read-only field so it can be copied by hand. Nothing is stored or sent.
export function CopyLink({
  fragment,
  id,
  label,
  vars,
  done,
}: {
  fragment: string;
  id: string;
  label: MessageKey;
  vars?: Readonly<Record<string, string | number>>;
  done: MessageKey;
}) {
  const { t } = useI18n();
  const [state, setState] = useState<"idle" | "copied" | "manual">("idle");
  const field = useRef<HTMLInputElement>(null);
  const url = `${window.location.origin}${window.location.pathname}${fragment}`;
  const copy = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("no clipboard");
      await navigator.clipboard.writeText(url);
      setState("copied");
    } catch {
      setState("manual");
      const select = () => {
        field.current?.focus();
        field.current?.select();
      };
      if (typeof requestAnimationFrame === "function") requestAnimationFrame(select);
      else setTimeout(select, 0);
    }
  };
  return (
    <span className="demo-copy-link">
      <button type="button" className="ghost" id={id} onClick={copy}>
        {t(label, vars)}
      </button>
      <span role="status" className="hint demo-copy-status">
        {state === "copied" ? t(done, { link: fragment }) : state === "manual" ? t("demo.link.copyManual") : ""}
      </span>
      {state === "manual" ? (
        <input ref={field} className="demo-copy-field" readOnly value={url} aria-label={t("demo.link.field")} onFocus={(e) => e.currentTarget.select()} />
      ) : null}
    </span>
  );
}
