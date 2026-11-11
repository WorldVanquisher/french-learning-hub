import { useI18n, type MessageKey } from "../i18n";

// Learning home (FLH sections v1): one page that names the seven learning
// sections and opens each of them. It reads nothing and writes nothing; every
// section keeps its own explicit save and review paths. Grammar and
// Vocabulary open the Mistake Notebook's views over existing Concepts, whose
// detail pages show their source records and start Recall Practice.
export type HomeTarget = "listening" | "reading" | "writing" | "speaking" | "grammar" | "vocabulary" | "notebook";

export interface HomeSection {
  target: HomeTarget;
  title: MessageKey;
  body: MessageKey;
  action: MessageKey;
}

export const HOME_SECTIONS: HomeSection[] = [
  { target: "listening", title: "home.listening.title", body: "home.listening.body", action: "home.listening.action" },
  { target: "reading", title: "home.reading.title", body: "home.reading.body", action: "home.reading.action" },
  { target: "writing", title: "home.writing.title", body: "home.writing.body", action: "home.writing.action" },
  { target: "speaking", title: "home.speaking.title", body: "home.speaking.body", action: "home.speaking.action" },
  { target: "grammar", title: "home.grammar.title", body: "home.grammar.body", action: "home.grammar.action" },
  { target: "vocabulary", title: "home.vocabulary.title", body: "home.vocabulary.body", action: "home.vocabulary.action" },
  { target: "notebook", title: "home.notebook.title", body: "home.notebook.body", action: "home.notebook.action" },
];

export function LearningHome<T extends string = HomeTarget>({
  sections = HOME_SECTIONS as unknown as { target: T; title: MessageKey; body: MessageKey; action: MessageKey }[],
  onOpen,
}: {
  sections?: { target: T; title: MessageKey; body: MessageKey; action: MessageKey }[];
  onOpen: (target: T) => void;
}) {
  const { t } = useI18n();
  return (
    <main className="learning-home">
      <section className="panel" aria-labelledby="learning-home-heading">
        <h2 id="learning-home-heading">{t("home.heading")}</h2>
        <p className="hint">{t("home.intro")}</p>
        <ul className="home-sections">
          {sections.map((s) => (
            <li key={s.target} className={`home-card home-card-${s.target}`}>
              <h3>{t(s.title)}</h3>
              <p>{t(s.body)}</p>
              <button type="button" onClick={() => onOpen(s.target)}>
                {t(s.action)}
              </button>
            </li>
          ))}
        </ul>
        <p className="hint">{t("home.explicit")}</p>
      </section>
    </main>
  );
}
