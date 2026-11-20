// R5: the guided journey's fixture replays. Each is synthetic, written for the
// public demo, never sent to or read from a server, and always shown under a
// "Fixture replay" label. They show how a private workbench feature treats the
// journey's public example; they are not records.
//
// JourneyFixtures.test.ts verifies each replay against the synthetic catalog the
// public artifact is built from (scripts/demo/flh073/fixtures/catalog.json).

// A person's correction of an analysis (FLH feedback). In the workbench a
// correction is a new, immutable record about one analysis; the analysis itself
// is never changed, and the effective interpretation becomes the correction.
export interface CorrectionReplay {
  // The guided example whose analysis it corrects.
  example: string;
  // That analysis's explanation, verbatim (the test checks it against the catalog).
  corrects: string;
  // The corrected explanation, recorded in both explanation languages (FLH-095).
  corrected: { en: string; zh: string };
}

export const CORRECTION_REPLAY: CorrectionReplay = {
  example: "en-train-de",
  corrects: "French has no « je suis cuisinant »: use the present, or « être en train de » + infinitive to stress that it is happening now.",
  corrected: {
    en: "« Je suis cuisinant » is not French. For an action happening now, French uses the present: « je cuisine ». « Être en train de » + infinitive (« je suis en train de cuisiner ») stresses that the action is in progress.",
    zh: "« Je suis cuisinant » 不是法语。表示正在发生的动作，法语用现在时：« je cuisine »。« être en train de » + 不定式（« je suis en train de cuisiner »）强调动作正在进行。",
  },
};
