package domain

import (
	"errors"
	"strings"
	"testing"
)

func TestCaptureSourceRefValidate(t *testing.T) {
	ok := []CaptureSourceRef{
		{Type: SourceListeningItem, RecordID: 1, Item: 1},
		{Type: SourceReadingItem, RecordID: 9, Item: 3, Attempt: "  Le mardi.\r\n "},
		{Type: SourceWritingCorrection, RecordID: 2, Item: 4},
		{Type: SourceSpeakingImprovement, RecordID: 5, Item: 1},
	}
	for _, r := range ok {
		if err := r.Validate(); err != nil {
			t.Errorf("%+v refused: %v", r, err)
		}
	}
	r := CaptureSourceRef{Type: SourceReadingItem, RecordID: 9, Item: 3, Attempt: "  Le mardi.\r\n "}
	if err := r.Validate(); err != nil || r.Attempt != "Le mardi." {
		t.Fatalf("attempt not trimmed: %q %v", r.Attempt, err)
	}
	for name, bad := range map[string]CaptureSourceRef{
		"unknown type":        {Type: "writing_draft", RecordID: 1, Item: 1},
		"zero record":         {Type: SourceListeningItem, RecordID: 0, Item: 1},
		"zero item":           {Type: SourceListeningItem, RecordID: 1, Item: 0},
		"item too large":      {Type: SourceListeningItem, RecordID: 1, Item: 51},
		"attempt on writing":  {Type: SourceWritingCorrection, RecordID: 1, Item: 1, Attempt: "mon texte"},
		"attempt on speaking": {Type: SourceSpeakingImprovement, RecordID: 1, Item: 1, Attempt: "ce que j'ai dit"},
		"control characters":  {Type: SourceReadingItem, RecordID: 1, Item: 1, Attempt: "a\x00b"},
		"oversized attempt":   {Type: SourceReadingItem, RecordID: 1, Item: 1, Attempt: strings.Repeat("é", 1001)},
	} {
		if err := bad.Validate(); !errors.Is(err, ErrValidation) {
			t.Errorf("%s: %v", name, err)
		}
	}
}

func TestSourceSkills(t *testing.T) {
	for typ, skill := range map[string]string{SourceListeningItem: "listening", SourceReadingItem: "reading", SourceWritingCorrection: "writing", SourceSpeakingImprovement: "speaking", "x": ""} {
		if SourceSkill(typ) != skill {
			t.Errorf("%s → %q", typ, SourceSkill(typ))
		}
	}
	if !ValidSkill("speaking") || ValidSkill("grammar") || ValidSkill("") {
		t.Fatal("skill vocabulary")
	}
}

// Captures without a source_ref keep the fingerprint they had before Mistake
// Notebook v1 (goldens computed with the unchanged pre-notebook code), so
// existing captures still replay instead of conflicting.
func TestCaptureFingerprintUnchangedWithoutSourceRef(t *testing.T) {
	in := PreparedLearningCapture{CaptureID: "writing-3-101-12-1-golden", Source: CaptureSourceManual, SchemaVersion: CaptureSchemaV1,
		OriginalInput: "« Je suis arrivé » → « J'arriverai »", OriginalContext: "Writing task #3"}
	if got := CaptureFingerprint(in); got != "bcee62b23462f879c79daabb22e06d749c04bf667dab49c78802298b49dbf5ad" {
		t.Fatalf("fingerprint without source changed: %s", got)
	}
	a := AnalysisResult{Category: "grammar", Explanation: "e", Confidence: 0.5}
	in.Analysis = &a
	if got := CaptureFingerprint(in); got != "c9c021f48c872e6a2e77ac6cf07c2ee50e202e56483a7fe91fe2bdddc5e2404a" {
		t.Fatalf("fingerprint with analysis changed: %s", got)
	}
	// A source is part of the content: a different source is a different capture.
	in.Analysis = nil
	in.SourceRef = &CaptureSourceRef{Type: SourceWritingCorrection, RecordID: 12, Item: 1}
	with := CaptureFingerprint(in)
	in.SourceRef = &CaptureSourceRef{Type: SourceWritingCorrection, RecordID: 12, Item: 2}
	if with == "bcee62b23462f879c79daabb22e06d749c04bf667dab49c78802298b49dbf5ad" || with == CaptureFingerprint(in) {
		t.Fatal("the source_ref must change the fingerprint")
	}
}

func TestClassifyConceptKindsNeverGuesses(t *testing.T) {
	for name, tc := range map[string]struct {
		kinds         []KnowledgeKind
		class, reason string
	}{
		"grammar only":     {[]KnowledgeKind{KindGrammar, KindGrammar}, KindViewGrammar, ""},
		"vocabulary only":  {[]KnowledgeKind{KindVocabulary}, KindViewVocabulary, ""},
		"no support":       {nil, KindViewUnclassified, UnclassifiedNoSupport},
		"mixed":            {[]KnowledgeKind{KindGrammar, KindVocabulary}, KindViewUnclassified, UnclassifiedMixedKinds},
		"morphology":       {[]KnowledgeKind{KindMorphology}, KindViewUnclassified, UnclassifiedOtherKind},
		"expression":       {[]KnowledgeKind{KindExpression, KindExpression}, KindViewUnclassified, UnclassifiedOtherKind},
		"grammar + usage":  {[]KnowledgeKind{KindGrammar, KindUsage}, KindViewUnclassified, UnclassifiedMixedKinds},
		"vocabulary + exp": {[]KnowledgeKind{KindVocabulary, KindExpression}, KindViewUnclassified, UnclassifiedMixedKinds},
	} {
		class, reason := ClassifyConceptKinds(tc.kinds)
		if class != tc.class || reason != tc.reason {
			t.Errorf("%s: %s/%s", name, class, reason)
		}
	}
}
