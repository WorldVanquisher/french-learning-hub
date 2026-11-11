import { useEffect, useState } from "react";
import { useI18n } from "./i18n";

// Workbench theme (overnight stack): the standard look stays the default; the
// "Endfield preview" is opt-in. The choice is a per-device convenience kept in
// localStorage (flh.ui-theme.v1); unavailable storage or any other value means
// the standard theme. Only the private workbench sets the attribute, so the
// public demo always keeps the standard look.
export type Theme = "standard" | "endfield";
export const THEME_STORAGE_KEY = "flh.ui-theme.v1";

export function readStoredTheme(): Theme {
  try {
    return window.localStorage.getItem(THEME_STORAGE_KEY) === "endfield" ? "endfield" : "standard";
  } catch {
    return "standard";
  }
}

export function applyTheme(theme: Theme) {
  if (theme === "endfield") document.documentElement.dataset.theme = "endfield";
  else delete document.documentElement.dataset.theme;
}

export function ThemeSelect() {
  const { t } = useI18n();
  const [theme, setTheme] = useState<Theme>(readStoredTheme);
  const [persisted, setPersisted] = useState(true);
  useEffect(() => applyTheme(theme), [theme]);
  // Leaving the workbench (tests, or another app on the page) restores the standard look.
  useEffect(() => () => applyTheme("standard"), []);
  const change = (next: Theme) => {
    setTheme(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
      setPersisted(true);
    } catch {
      setPersisted(false);
    }
  };
  return (
    <div className="language-select theme-select">
      <label>
        {t("theme.label")}{" "}
        <select value={theme} onChange={(event) => change(event.target.value === "endfield" ? "endfield" : "standard")}>
          <option value="standard">{t("theme.standard")}</option>
          <option value="endfield">{t("theme.endfield")}</option>
        </select>
      </label>
      {!persisted ? (
        <p className="hint" role="status">
          {t("theme.notSaved")}
        </p>
      ) : null}
    </div>
  );
}
