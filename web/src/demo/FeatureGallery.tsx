import { useI18n, type MessageKey } from "../i18n";

// R5: a compact gallery of FLH's major features that do not fit the guided
// journey. Each card says what the feature does and why the public demo cannot
// run it (it needs a learner's own records, an AI provider or saving), and,
// where this demo shows something related, links there. The cards are
// application text only: no data, no request, no fixture.

export type GalleryLink = { kind: "hash"; hash: string; label: MessageKey } | { kind: "retry"; label: MessageKey };

export interface GalleryCard {
  key: string;
  title: MessageKey;
  body: MessageKey;
  // Private-only (not run here), or shown in this demo.
  privateOnly: boolean;
  link?: GalleryLink;
}

export const GALLERY: readonly GalleryCard[] = [
  { key: "capture", title: "demo.gallery.capture.title", body: "demo.gallery.capture.body", privateOnly: true },
  { key: "review", title: "demo.gallery.review.title", body: "demo.gallery.review.body", privateOnly: true, link: { kind: "hash", hash: "#concept=13", label: "demo.gallery.review.link" } },
  { key: "notebook", title: "demo.gallery.notebook.title", body: "demo.gallery.notebook.body", privateOnly: true, link: { kind: "retry", label: "demo.gallery.notebook.link" } },
  { key: "listening", title: "demo.gallery.listening.title", body: "demo.gallery.listening.body", privateOnly: true },
  { key: "reading", title: "demo.gallery.reading.title", body: "demo.gallery.reading.body", privateOnly: true },
  { key: "writing", title: "demo.gallery.writing.title", body: "demo.gallery.writing.body", privateOnly: true },
  { key: "speaking", title: "demo.gallery.speaking.title", body: "demo.gallery.speaking.body", privateOnly: true },
  { key: "recall", title: "demo.gallery.recall.title", body: "demo.gallery.recall.body", privateOnly: true },
  { key: "experiments", title: "demo.gallery.experiments.title", body: "demo.gallery.experiments.body", privateOnly: true },
  { key: "semantic", title: "demo.gallery.semantic.title", body: "demo.gallery.semantic.body", privateOnly: false, link: { kind: "hash", hash: "#mode=semantic&preset=right-now", label: "demo.gallery.semantic.link" } },
];

export function FeatureGallery({ onOpenHash, onRetry, presets }: { onOpenHash: (hash: string) => void; onRetry: () => void; presets: readonly string[] }) {
  const { t } = useI18n();
  return (
    <section className="panel demo-gallery" aria-labelledby="demo-gallery-heading">
      <h2 id="demo-gallery-heading" className="library-title" tabIndex={-1}>
        {t("demo.gallery.heading")}
      </h2>
      <p className="hint">{t("demo.gallery.hint")}</p>
      <ul className="demo-gallery-list">
        {GALLERY.map((c) => {
          // A preset link needs the preset in this build.
          const link = c.link?.kind === "hash" && c.link.hash.includes("preset=") && !presets.some((p) => c.link?.kind === "hash" && c.link.hash.endsWith(`preset=${p}`)) ? undefined : c.link;
          return (
            <li key={c.key} className="demo-gallery-card" data-gallery={c.key}>
              <h3>{t(c.title)}</h3>
              <p className={c.privateOnly ? "demo-gallery-tag private" : "demo-gallery-tag shown"}>{t(c.privateOnly ? "demo.gallery.private" : "demo.gallery.inDemo")}</p>
              <p className="hint">{t(c.body)}</p>
              {link ? (
                <button
                  type="button"
                  className="ghost"
                  id={`demo-gallery-${c.key}`}
                  onClick={() => (link.kind === "retry" ? onRetry() : onOpenHash(link.hash))}
                >
                  {t(link.label)}
                </button>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
