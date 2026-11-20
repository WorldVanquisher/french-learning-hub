import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { markMatches } from "../pages/libraryHighlight";
import { markSharedWords, sharedWords } from "./ExampleScreen";

// R4-DEM-029: repeated wording is marked by whole words, across accents, case,
// Unicode normalization (composed or decomposed accents) and punctuation.

const marked = (node: ReturnType<typeof markSharedWords>) => {
  const { container } = render(<p>{node}</p>);
  return [...container.querySelectorAll("mark")].map((m) => m.textContent);
};

describe("the question's words that reappear in its rules", () => {
  it("marks whole words without case or accents", () => {
    expect(sharedWords("Quand j'étais petit, je jouais au foot.", ["imparfait pour le contexte", "etais petit"])).toEqual(["étais", "petit"]);
    expect(sharedWords("QUAND J'ETAIS PETIT", ["étais"])).toEqual(["ETAIS"]);
  });

  it("marks a word written with decomposed accents as one whole word", () => {
    const nfd = "Je suis allé au marché.";
    expect(marked(markSharedWords(nfd, ["passé composé avec être", "aller au marché"]))).toEqual(["au", "marché"]);
    expect(sharedWords(nfd, ["marché"])).toEqual(["marché"]);
    // A rule written with decomposed accents reaches the composed question too.
    expect(sharedWords("Je suis allé au marché.", ["marché"])).toEqual(["marché"]);
  });

  it("stops at punctuation, guillemets and apostrophes, and never marks inside a longer short word", () => {
    expect(marked(markSharedWords("« marché », marché; (marché)", ["marché"]))).toEqual(["marché", "marché", "marché"]);
    expect(sharedWords("Il faut que tu viennes demain.", ["subjonctif de venir"])).toEqual([]);
    expect(sharedWords("l'imparfait, d'un passé", ["imparfait"])).toEqual(["imparfait"]);
    // A rule word of five letters or more also marks its longer form.
    expect(sharedWords("qu'est-ce que « y » et « en » remplacent ?", ["y remplace à + lieu"])).toEqual(["remplacent"]);
  });
});

describe("a search's matched words", () => {
  it("marks whole words across accents and decomposed forms, not punctuation", () => {
    const { container } = render(<p>{markMatches("« Marché », marché.", ["marche"])}</p>);
    expect([...container.querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["Marché", "marché"]);
  });
});
