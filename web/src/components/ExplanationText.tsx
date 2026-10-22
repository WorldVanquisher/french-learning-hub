import { recorded, shownLanguages, useExplanationLanguage } from "../explanationLanguage";
import { useI18n, type MessageKey } from "../i18n";
import type { EffectiveExplanations, ExplanationBasis, ExplanationLanguage, ExplanationVariants } from "../types/learning";

// FLH-095 rendering of generated explanatory text in its stored languages.
// Learner text, French examples and IDs are never passed through here. The text
// shown is always stored text: a missing language is stated, never filled with
// another language's text, and a text whose language was not recorded is
// labelled as such rather than as English or Chinese.

const LANG_ATTR: Record<ExplanationLanguage, string> = { en: "en", zh: "zh-Hans" };
const LANG_NAME: Record<ExplanationLanguage, string> = { en: "English", zh: "中文" };
const MISSING: Record<"explanation" | "statement", Record<ExplanationLanguage, MessageKey>> = {
  explanation: { en: "explanationText.missing.explanation.en", zh: "explanationText.missing.explanation.zh" },
  statement: { en: "explanationText.missing.statement.en", zh: "explanationText.missing.statement.zh" },
};
const BASIS: Record<ExplanationBasis, MessageKey> = {
  unreviewed: "explanationText.basis.unreviewed",
  reviewed: "explanationText.basis.reviewed",
  not_reviewed: "explanationText.basis.not_reviewed",
  corrected: "explanationText.basis.corrected",
  outdated: "explanationText.basis.outdated",
  unavailable: "explanationText.basis.unavailable",
};

// StoredText shows a generated text with its stored variants (an analysis's
// original explanation or a unit statement).
export function StoredText({
  primary,
  variants,
  kind,
  className = "",
}: {
  primary: string;
  variants: ExplanationVariants | undefined | null;
  kind: "explanation" | "statement";
  className?: string;
}) {
  const { t } = useI18n();
  const { mode } = useExplanationLanguage();
  if (!recorded(variants)) {
    return (
      <span className={`explanation-text ${className}`}>
        <span>{primary}</span> <span className="lang-tag">{t("explanationText.notRecorded")}</span>
      </span>
    );
  }
  return (
    <span className={`explanation-text ${className}`}>
      {shownLanguages(mode).map((lang) => {
        const text = variants[lang];
        return (
          <span key={lang} className="explanation-variant" data-lang={lang}>
            <span className="lang-tag">{LANG_NAME[lang]}</span>{" "}
            {text !== null ? (
              <span lang={LANG_ATTR[lang]}>{text}</span>
            ) : (
              <em className="hint">{t(MISSING[kind][lang])}</em>
            )}
          </span>
        );
      })}
    </span>
  );
}

// EffectiveText shows the backend's per-language effective explanation with its
// basis. `fallback` is the language-independent effective explanation; it is
// shown on its own when the analysis has no recorded languages, and labelled
// when it is a person's correction whose language was not recorded.
export function EffectiveText({
  fallback,
  original,
  originalVariants,
  effective,
}: {
  fallback: string;
  original: string;
  originalVariants: ExplanationVariants | undefined | null;
  effective: EffectiveExplanations | undefined | null;
}) {
  const { t } = useI18n();
  const { mode } = useExplanationLanguage();
  if (!effective || (!recorded(originalVariants) && effective.en.basis !== "corrected" && effective.zh.basis !== "corrected")) {
    return <StoredText primary={fallback} variants={null} kind="explanation" />;
  }
  const unspecifiedCorrection =
    fallback !== original && effective.en.basis !== "corrected" && effective.zh.basis !== "corrected";
  return (
    <span className="explanation-text">
      {unspecifiedCorrection ? (
        <span className="explanation-variant" data-lang="unrecorded">
          <span className="lang-tag">{t("explanationText.unspecifiedCorrection")}</span> <span>{fallback}</span>
        </span>
      ) : null}
      {shownLanguages(mode).map((lang) => {
        const v = effective[lang];
        return (
          <span key={lang} className="explanation-variant" data-lang={lang}>
            <span className="lang-tag">{LANG_NAME[lang]}</span>{" "}
            {v.text !== null ? (
              <>
                <span lang={LANG_ATTR[lang]}>{v.text}</span>{" "}
                <span className={`basis-tag ${v.basis}`}>{t(BASIS[v.basis])}</span>
              </>
            ) : (
              <em className="hint">{t(MISSING.explanation[lang])}</em>
            )}
          </span>
        );
      })}
    </span>
  );
}
