// practice_draft_v1: drafts are built from the stored source only, keep their
// source revision, never guess for an unreadable source, and collapse versions
// of one record into one retry mark.
import { describe, expect, it } from "vitest";
import { accentItem } from "./practiceDraft.fixture";
import { approvalTargets, buildDraft, draftProblem, draftReady, nextCopy } from "./practiceDraft";

describe("practice_draft_v1", () => {
  it("builds a draft from the stored question with its source revision", () => {
    const d = buildDraft(accentItem(2))!;
    expect(d.key).toBe("2:1");
    expect(d.question).toBe("Pourquoi Hélène choisit-elle le cours du soir à l'école Saint-Éloi ?");
    expect(d.sourceWords).toBe("Parce qu'elle préfère l'été.");
    expect(d.action).toBe("answer_again");
    expect(d.provenance).toEqual({ entryId: 2, type: "listening_item", recordId: 900, item: 2, version: 1, latestVersion: null });
  });

  it("starts a correction from the learner's own words and the skill's action", () => {
    const w = buildDraft(
      accentItem(5, {
        skill: "writing",
        source: { type: "writing_correction", record_id: 31, item: 1, attempt: null },
        quote: "Je suis allé à la bibliothèque hier soir, c'était fermé.",
        prompt: "Écrivez un message à un ami.",
        link: { writing_task_id: 4, writing_draft_id: 9, writing_draft_version: 2, writing_feedback_id: 31 },
      }),
    )!;
    expect(w.question).toBe("Je suis allé à la bibliothèque hier soir, c'était fermé.");
    expect(w.sourcePrompt).toBe("Écrivez un message à un ami.");
    expect(w.action).toBe("write_corrected");
    expect(w.provenance.version).toBe(2);
    const s = buildDraft(accentItem(6, { skill: "speaking", quote: "J'ai rendez-vous à midi", link: { speaking_transcript_version: 3 } }))!;
    expect(s.action).toBe("say_corrected");
    expect(s.provenance.version).toBe(3);
  });

  it("never builds a draft for a source that moved away or disappeared, and flags a newer revision", () => {
    expect(buildDraft(accentItem(1, { source_status: "missing" }))).toBeNull();
    expect(buildDraft(accentItem(1, { source_status: "unusable" }))).toBeNull();
    expect(draftProblem(accentItem(1, { source_status: "missing" }))).toBe("missing");
    const newer = accentItem(1, { latest_version: 2 });
    expect(draftProblem(newer)).toBe("newer");
    expect(buildDraft(newer)!.provenance).toMatchObject({ version: 1, latestVersion: 2 });
  });

  it("numbers deliberate versions and collapses them into one retry mark per record", () => {
    const a = buildDraft(accentItem(2))!;
    const b = buildDraft(accentItem(2), nextCopy([a], 2))!;
    const c = buildDraft(accentItem(3))!;
    expect(b.key).toBe("2:2");
    expect(nextCopy([a, b, c], 2)).toBe(3);
    expect(nextCopy([a, b, c], 9)).toBe(1);
    expect(approvalTargets([a, b, c, a])).toEqual([2, 3]);
  });

  it("keeps edited text exactly as typed, accents and line breaks included", () => {
    const d = buildDraft(accentItem(2))!;
    const typed = "Où Hélène a-t-elle garé sa voiture ?\nÇa s'est passé à Noël… « près de l'hôpital ».";
    const edited = { ...d, question: typed };
    expect(edited.question).toBe(typed);
    expect(edited.question.normalize("NFC")).toBe(typed);
    expect(draftReady(edited)).toBe(true);
    expect(draftReady({ ...d, question: "  \n " })).toBe(false);
  });
});
