// UI localization for the workbench and the public demo (FLH-083).
//
// Only application-owned text is translated: navigation, controls, labels,
// confirmations, empty/loading states, outcome banners, accessibility labels and
// explanations. Learner content, stored or AI-generated text, Concept identities,
// IDs, wire values, provider/retriever names, provenance and raw server error
// details are always shown as they are. Known status values get a display label
// only; the raw value still drives logic and CSS.
//
// English is the default on first use, whatever the browser language. An explicit
// choice is kept in localStorage; if storage is unavailable or holds anything but a
// supported locale, English is used. Switching re-renders in place, so drafts,
// navigation, selections and pending or unknown operations are kept.
import { createContext, Fragment, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { en, type MessageKey } from "./en";
import { zhCN } from "./zh-CN";

export type Locale = "en" | "zh-CN";
export type { MessageKey };

// The language names are shown in their own language, never translated.
export const LOCALES: ReadonlyArray<{ code: Locale; name: string }> = [
  { code: "en", name: "English" },
  { code: "zh-CN", name: "简体中文" },
];
export const DEFAULT_LOCALE: Locale = "en";
export const LOCALE_STORAGE_KEY = "flh.ui-locale.v1";

const catalogs: Record<Locale, Record<MessageKey, string>> = { en, "zh-CN": zhCN };

export const isLocale = (value: unknown): value is Locale => value === "en" || value === "zh-CN";

// readStoredLocale never throws: unavailable storage or an invalid value means English.
export function readStoredLocale(): Locale {
  try {
    const value = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    return isLocale(value) ? value : DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
}

// storeLocale reports whether the explicit choice could be saved.
export function storeLocale(locale: Locale): boolean {
  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
    return true;
  } catch {
    return false;
  }
}

// A message to be rendered later in whatever locale is current then. Helpers that
// run outside React (and async results kept in state) return these, so a language
// switch also re-renders text that was produced before the switch.
export type MessageRef = { readonly msgKey: MessageKey; readonly vars?: Vars };
export type VarValue = string | number | MessageRef;
export type Vars = Readonly<Record<string, VarValue>>;
export const msg = (key: MessageKey, vars?: Vars): MessageRef => ({ msgKey: key, vars });
const isMessageRef = (value: unknown): value is MessageRef =>
  typeof value === "object" && value !== null && "msgKey" in value;

// Msg is anything a banner or notice can show: a message reference, a render
// function evaluated with the current locale, or plain content. Plain strings are
// shown verbatim (used for raw server error details, which are never translated).
export type Msg = MessageRef | ((i18n: I18n) => ReactNode) | ReactNode;

// A key that has `.one` and `.other` variants.
type PluralBase<K = MessageKey> = K extends `${infer B}.one` ? (`${B}.other` extends MessageKey ? B : never) : never;

export interface I18n {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  // False when the last explicit choice could not be saved (it still applies now).
  persisted: boolean;
  t: (key: MessageKey, vars?: Vars) => string;
  // Plural selection on `count` (also available as {count} in the message).
  tp: (base: PluralBase, count: number, vars?: Vars) => string;
  // A whole-sentence template whose {placeholders} are filled with React nodes, so
  // markup never lives inside translated strings.
  tn: (key: MessageKey, nodes: Readonly<Record<string, ReactNode>>) => ReactNode;
  // Display label for a known status value; unknown values are shown as given.
  status: (value: string) => string;
  render: (message: Msg | null | undefined) => ReactNode;
}

const placeholder = /\{(\w+)\}/g;

export function format(locale: Locale, key: MessageKey, vars?: Vars): string {
  const template = catalogs[locale][key] ?? en[key] ?? key;
  if (!vars) return template;
  return template.replace(placeholder, (whole, name: string) => {
    const value = vars[name];
    if (value === undefined) return whole;
    return isMessageRef(value) ? format(locale, value.msgKey, value.vars) : String(value);
  });
}

// English text of a message reference, for code and tests outside React.
export const formatEn = (message: MessageRef): string => format("en", message.msgKey, message.vars);

function pluralKey(locale: Locale, base: string, count: number): MessageKey {
  // English distinguishes one from other; Chinese has no grammatical plural.
  const form = locale === "en" && count === 1 ? "one" : "other";
  return `${base}.${form}` as MessageKey;
}

export function statusKey(value: string): MessageKey | null {
  const key = `status.${value}` as MessageKey;
  return key in en ? key : null;
}

function makeI18n(locale: Locale, setLocale: (l: Locale) => void, persisted: boolean): I18n {
  const t = (key: MessageKey, vars?: Vars) => format(locale, key, vars);
  const i18n: I18n = {
    locale,
    setLocale,
    persisted,
    t,
    tp: (base, count, vars) => format(locale, pluralKey(locale, base, count), { count, ...vars }),
    tn: (key, nodes) => {
      const template = format(locale, key);
      const parts: ReactNode[] = [];
      let last = 0;
      for (const match of template.matchAll(placeholder)) {
        const at = match.index ?? 0;
        if (at > last) parts.push(template.slice(last, at));
        const name = match[1];
        parts.push(name in nodes ? <Fragment key={`${name}-${at}`}>{nodes[name]}</Fragment> : match[0]);
        last = at + match[0].length;
      }
      if (last < template.length) parts.push(template.slice(last));
      return <>{parts}</>;
    },
    status: (value) => {
      const key = statusKey(value);
      return key ? t(key) : value;
    },
    render: (message) => {
      if (message === null || message === undefined) return null;
      if (typeof message === "function") return message(i18n);
      if (isMessageRef(message)) return t(message.msgKey, message.vars);
      return message;
    },
  };
  return i18n;
}

// Outside a provider (for example a component rendered alone in a test) text is English.
const EnglishContext = createContext<I18n>(makeI18n(DEFAULT_LOCALE, () => undefined, true));

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => readStoredLocale());
  const [persisted, setPersisted] = useState(true);
  const setLocale = useCallback((next: Locale) => {
    if (!isLocale(next)) return;
    setPersisted(storeLocale(next));
    setLocaleState(next);
  }, []);
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);
  const value = useMemo(() => makeI18n(locale, setLocale, persisted), [locale, setLocale, persisted]);
  return <EnglishContext.Provider value={value}>{children}</EnglishContext.Provider>;
}

export const useI18n = (): I18n => useContext(EnglishContext);

// LanguageSelect is the explicit English / 简体中文 choice.
export function LanguageSelect() {
  const { locale, setLocale, persisted, t } = useI18n();
  return (
    <div className="language-select">
      <label>
        {t("language.label")}{" "}
        <select value={locale} onChange={(event) => setLocale(event.target.value as Locale)}>
          {LOCALES.map((l) => (
            <option key={l.code} value={l.code} lang={l.code}>
              {l.name}
            </option>
          ))}
        </select>
      </label>
      {!persisted ? (
        <p className="hint" role="status">
          {t("language.notSaved")}
        </p>
      ) : null}
    </div>
  );
}

// Text renders a Msg with the current locale.
export function Text({ message }: { message: Msg | null | undefined }) {
  const i18n = useI18n();
  return <>{i18n.render(message)}</>;
}
