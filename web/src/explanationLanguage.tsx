import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { useI18n } from "./i18n";
import type { ExplanationLanguage, ExplanationVariants } from "./types/learning";

// FLH-095: which stored explanation languages to show. This is a reading
// preference, separate from the application UI language (i18n): switching the UI
// to 简体中文 never hides or replaces stored English explanations, and switching
// this preference never changes application text. It is read-only: it changes
// what is shown, never what is stored, and never triggers a request.
//
// The default is "both" (show every stored variant), regardless of the UI
// language. An explicit choice is kept in localStorage under its own key;
// unavailable storage or an invalid value means "both".

export type ExplanationMode = "both" | ExplanationLanguage;
export const EXPLANATION_STORAGE_KEY = "flh.explanation-language.v1";
const MODES: ExplanationMode[] = ["both", "en", "zh"];

function readStoredMode(): ExplanationMode {
  try {
    const value = window.localStorage.getItem(EXPLANATION_STORAGE_KEY);
    return MODES.includes(value as ExplanationMode) ? (value as ExplanationMode) : "both";
  } catch {
    return "both";
  }
}

type ExplanationPreference = {
  mode: ExplanationMode;
  setMode: (mode: ExplanationMode) => void;
  persisted: boolean;
};

const DEFAULT_PREFERENCE: ExplanationPreference = { mode: "both", setMode: () => undefined, persisted: true };
const PreferenceContext = createContext<ExplanationPreference>(DEFAULT_PREFERENCE);

export function ExplanationLanguageProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ExplanationMode>(() => readStoredMode());
  const [persisted, setPersisted] = useState(true);
  const setMode = useCallback((next: ExplanationMode) => {
    setModeState(next);
    try {
      window.localStorage.setItem(EXPLANATION_STORAGE_KEY, next);
      setPersisted(true);
    } catch {
      setPersisted(false);
    }
  }, []);
  const value = useMemo(() => ({ mode, setMode, persisted }), [mode, setMode, persisted]);
  return <PreferenceContext.Provider value={value}>{children}</PreferenceContext.Provider>;
}

export const useExplanationLanguage = (): ExplanationPreference => useContext(PreferenceContext);

// recorded reports whether a text has any stored language variant.
export function recorded(v: ExplanationVariants | undefined | null): v is ExplanationVariants {
  return !!v && (v.en !== null || v.zh !== null);
}

// shownLanguages lists, in order, the languages the preference shows.
export function shownLanguages(mode: ExplanationMode): ExplanationLanguage[] {
  return mode === "both" ? ["en", "zh"] : [mode];
}

// reviewedLanguages is what a decision may truthfully record as shown: the
// shown languages that are actually stored on the analysis.
export function reviewedLanguages(mode: ExplanationMode, v: ExplanationVariants | undefined | null): ExplanationLanguage[] {
  if (!recorded(v)) return [];
  return shownLanguages(mode).filter((l) => v[l] !== null);
}

export function ExplanationLanguageSelect() {
  const { t } = useI18n();
  const { mode, setMode, persisted } = useExplanationLanguage();
  return (
    <div className="language-select">
      <label>
        {t("explanationLanguage.label")}{" "}
        <select value={mode} onChange={(event) => setMode(event.target.value as ExplanationMode)}>
          <option value="both">{t("explanationLanguage.both")}</option>
          <option value="en" lang="en">
            English
          </option>
          <option value="zh" lang="zh-Hans">
            中文
          </option>
        </select>
      </label>
      {!persisted ? (
        <p className="hint" role="status">
          {t("explanationLanguage.notSaved")}
        </p>
      ) : null}
    </div>
  );
}
