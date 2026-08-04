package domain

import (
	"errors"
	"strings"
	"testing"
)

// validCaptureInput returns a fully valid ChatGPT capture with an analysis.
func validCaptureInput() NewLearningCaptureInput {
	return NewLearningCaptureInput{
		SchemaVersion:   CaptureSchemaV1,
		CaptureID:       "fcf91250-b66c-43d8-9a52-f2a05642e772",
		Source:          CaptureSourceChatGPTWeb,
		OriginalInput:   "Je parle japonais ou je parle le japonais ?",
		OriginalContext: "Whether French language names require an article after parler.",
		Analysis: &ImportedAnalysisInput{
			Category:    "grammar",
			Explanation: "After parler, a language name is normally used without an article.",
			Confidence:  0.91,
			Uncertainty: "Usage may vary when referring to the language as an object.",
		},
		DiscussionSummary: "Compared parler japonais with apprendre le japonais.",
	}
}

func TestCaptureValidate_ValidChatGPT(t *testing.T) {
	in := validCaptureInput()
	if err := in.Validate(); err != nil {
		t.Fatalf("valid ChatGPT capture rejected: %v", err)
	}
}

func TestCaptureValidate_ValidManual(t *testing.T) {
	in := validCaptureInput()
	in.Source = CaptureSourceManual
	in.CaptureID = "manual-2026-08-04-001"
	if err := in.Validate(); err != nil {
		t.Fatalf("valid manual capture rejected: %v", err)
	}
}

func TestCaptureValidate_NoAnalysis(t *testing.T) {
	in := validCaptureInput()
	in.Analysis = nil
	if err := in.Validate(); err != nil {
		t.Fatalf("capture without analysis rejected: %v", err)
	}
}

func TestCaptureValidate_Failures(t *testing.T) {
	longID := strings.Repeat("a", maxCaptureIDLen+1)
	longSummary := strings.Repeat("x", maxDiscussionSummaryLen+1)
	longUncertainty := strings.Repeat("u", maxUncertaintyLen+1)

	cases := []struct {
		name   string
		mutate func(*NewLearningCaptureInput)
	}{
		{"missing schema version", func(in *NewLearningCaptureInput) { in.SchemaVersion = "" }},
		{"unsupported schema version", func(in *NewLearningCaptureInput) { in.SchemaVersion = "learning_capture_v2" }},
		{"missing capture id", func(in *NewLearningCaptureInput) { in.CaptureID = "   " }},
		{"malformed capture id", func(in *NewLearningCaptureInput) { in.CaptureID = "bad id!" }},
		{"capture id bad leading char", func(in *NewLearningCaptureInput) { in.CaptureID = "-leading" }},
		{"over-length capture id", func(in *NewLearningCaptureInput) { in.CaptureID = longID }},
		{"unknown source", func(in *NewLearningCaptureInput) { in.Source = CaptureSource("api") }},
		{"empty source", func(in *NewLearningCaptureInput) { in.Source = CaptureSource("") }},
		{"invalid entry input (empty)", func(in *NewLearningCaptureInput) { in.OriginalInput = "   " }},
		{"invalid category", func(in *NewLearningCaptureInput) { in.Analysis.Category = "syntax" }},
		{"missing analysis explanation", func(in *NewLearningCaptureInput) { in.Analysis.Explanation = "  " }},
		{"confidence below zero", func(in *NewLearningCaptureInput) { in.Analysis.Confidence = -0.01 }},
		{"confidence above one", func(in *NewLearningCaptureInput) { in.Analysis.Confidence = 1.01 }},
		{"over-length uncertainty", func(in *NewLearningCaptureInput) { in.Analysis.Uncertainty = longUncertainty }},
		{"over-length discussion summary", func(in *NewLearningCaptureInput) { in.DiscussionSummary = longSummary }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			in := validCaptureInput()
			tc.mutate(&in)
			err := in.Validate()
			if !errors.Is(err, ErrValidation) {
				t.Fatalf("expected ErrValidation, got %v", err)
			}
		})
	}
}

func TestCaptureValidate_NormalizesInPlace(t *testing.T) {
	in := validCaptureInput()
	in.CaptureID = "  keep-me  "
	in.OriginalInput = "  padded input  "
	in.OriginalContext = "  padded context  "
	in.DiscussionSummary = "  padded summary  "
	in.Analysis.Category = "  GRAMMAR  "
	if err := in.Validate(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if in.CaptureID != "keep-me" {
		t.Fatalf("capture id not trimmed: %q", in.CaptureID)
	}
	if in.OriginalInput != "padded input" || in.OriginalContext != "padded context" {
		t.Fatalf("entry data not normalized: %q / %q", in.OriginalInput, in.OriginalContext)
	}
	if in.DiscussionSummary != "padded summary" {
		t.Fatalf("summary not trimmed: %q", in.DiscussionSummary)
	}
	if in.Analysis.Category != "grammar" {
		t.Fatalf("category not normalized: %q", in.Analysis.Category)
	}
}

func TestImportedAnalysisProvenance(t *testing.T) {
	if got := ImportedAnalysisProvenance(CaptureSourceChatGPTWeb); got != "imported:chatgpt-web:learning_capture_v1" {
		t.Fatalf("chatgpt provenance = %q", got)
	}
	if got := ImportedAnalysisProvenance(CaptureSourceManual); got != "imported:manual:learning_capture_v1" {
		t.Fatalf("manual provenance = %q", got)
	}
}

func TestNormalizeCaptureID(t *testing.T) {
	if got, err := NormalizeCaptureID("  abc-123  "); err != nil || got != "abc-123" {
		t.Fatalf("NormalizeCaptureID trim = %q, %v", got, err)
	}
	for _, bad := range []string{"", "   ", "has space", "bad!", "-lead", strings.Repeat("a", maxCaptureIDLen+1)} {
		if _, err := NormalizeCaptureID(bad); !errors.Is(err, ErrValidation) {
			t.Fatalf("NormalizeCaptureID(%q) should be ErrValidation, got %v", bad, err)
		}
	}
}

// preparedFrom validates an input and builds the PreparedLearningCapture exactly
// as the application service does, so fingerprint tests exercise the real path.
func preparedFrom(t *testing.T, in NewLearningCaptureInput) PreparedLearningCapture {
	t.Helper()
	if err := in.Validate(); err != nil {
		t.Fatalf("validate: %v", err)
	}
	p := PreparedLearningCapture{
		CaptureID:         in.CaptureID,
		Source:            in.Source,
		SchemaVersion:     in.SchemaVersion,
		OriginalInput:     in.OriginalInput,
		OriginalContext:   in.OriginalContext,
		DiscussionSummary: in.DiscussionSummary,
	}
	if in.Analysis != nil {
		r := in.Analysis.AsAnalysisResult()
		p.Analysis = &r
		p.AnalyzerProvenance = ImportedAnalysisProvenance(in.Source)
	}
	p.ContentFingerprint = CaptureFingerprint(p)
	return p
}

func TestFingerprint_SameInputSameFingerprint(t *testing.T) {
	a := preparedFrom(t, validCaptureInput())
	b := preparedFrom(t, validCaptureInput())
	if a.ContentFingerprint != b.ContentFingerprint {
		t.Fatal("identical input produced different fingerprints")
	}
}

func TestFingerprint_Deterministic(t *testing.T) {
	p := preparedFrom(t, validCaptureInput())
	first := CaptureFingerprint(p)
	for i := 0; i < 5; i++ {
		if CaptureFingerprint(p) != first {
			t.Fatal("fingerprint not deterministic across calls")
		}
	}
}

func TestFingerprint_WhitespaceNormalized(t *testing.T) {
	// Two inputs differing only by surrounding whitespace normalize to the same
	// content, so their fingerprints must match (documented normalization).
	clean := validCaptureInput()
	padded := validCaptureInput()
	padded.OriginalInput = "  " + padded.OriginalInput + "  "
	padded.DiscussionSummary = "\t" + padded.DiscussionSummary + "\n"
	padded.Analysis.Explanation = "  " + padded.Analysis.Explanation + "  "

	if preparedFrom(t, clean).ContentFingerprint != preparedFrom(t, padded).ContentFingerprint {
		t.Fatal("surrounding whitespace should not change the fingerprint after normalization")
	}
}

func TestFingerprint_MeaningfulChanges(t *testing.T) {
	base := preparedFrom(t, validCaptureInput())

	cases := []struct {
		name   string
		mutate func(*NewLearningCaptureInput)
	}{
		{"different source", func(in *NewLearningCaptureInput) { in.Source = CaptureSourceManual }},
		{"different original input", func(in *NewLearningCaptureInput) { in.OriginalInput = "totally different" }},
		{"different context", func(in *NewLearningCaptureInput) { in.OriginalContext = "totally different context" }},
		{"different summary", func(in *NewLearningCaptureInput) { in.DiscussionSummary = "different summary" }},
		{"remove analysis", func(in *NewLearningCaptureInput) { in.Analysis = nil }},
		{"different category", func(in *NewLearningCaptureInput) { in.Analysis.Category = "vocabulary" }},
		{"different confidence", func(in *NewLearningCaptureInput) { in.Analysis.Confidence = 0.5 }},
		{"different explanation", func(in *NewLearningCaptureInput) { in.Analysis.Explanation = "different explanation entirely" }},
		{"different uncertainty", func(in *NewLearningCaptureInput) { in.Analysis.Uncertainty = "different uncertainty" }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			in := validCaptureInput()
			tc.mutate(&in)
			other := preparedFrom(t, in)
			if other.ContentFingerprint == base.ContentFingerprint {
				t.Fatalf("%s should change the fingerprint but did not", tc.name)
			}
		})
	}
}

func TestFingerprint_AddingAnalysisChangesIt(t *testing.T) {
	noAnalysis := validCaptureInput()
	noAnalysis.Analysis = nil
	withAnalysis := validCaptureInput()
	if preparedFrom(t, noAnalysis).ContentFingerprint == preparedFrom(t, withAnalysis).ContentFingerprint {
		t.Fatal("adding an analysis should change the fingerprint")
	}
}
