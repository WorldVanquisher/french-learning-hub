package domain

import (
	"errors"
	"strings"
	"testing"
)

func TestExtractedUnit_Validate(t *testing.T) {
	cases := map[string]struct {
		unit    ExtractedUnit
		wantErr bool
	}{
		"valid": {
			unit:    ExtractedUnit{Kind: KindGrammar, Canonical: "vouloir + inf", Statement: "vouloir takes a bare infinitive", Confidence: 0.8},
			wantErr: false,
		},
		"valid with example": {
			unit:    ExtractedUnit{Kind: KindVocabulary, Canonical: "marché", Statement: "market", Example: strptr("au marché"), Confidence: 0.5},
			wantErr: false,
		},
		"invalid kind": {
			unit:    ExtractedUnit{Kind: KnowledgeKind("conjugation"), Canonical: "x", Statement: "y", Confidence: 0.5},
			wantErr: true,
		},
		"empty canonical": {
			unit:    ExtractedUnit{Kind: KindGrammar, Canonical: "   ", Statement: "y", Confidence: 0.5},
			wantErr: true,
		},
		"empty statement": {
			unit:    ExtractedUnit{Kind: KindGrammar, Canonical: "x", Statement: "  ", Confidence: 0.5},
			wantErr: true,
		},
		"confidence too high": {
			unit:    ExtractedUnit{Kind: KindGrammar, Canonical: "x", Statement: "y", Confidence: 1.5},
			wantErr: true,
		},
		"confidence negative": {
			unit:    ExtractedUnit{Kind: KindGrammar, Canonical: "x", Statement: "y", Confidence: -0.1},
			wantErr: true,
		},
		"canonical too long": {
			unit:    ExtractedUnit{Kind: KindGrammar, Canonical: strings.Repeat("a", maxCanonicalLen+1), Statement: "y", Confidence: 0.5},
			wantErr: true,
		},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			u := tc.unit
			err := u.Validate()
			if tc.wantErr && !errors.Is(err, ErrValidation) {
				t.Fatalf("expected ErrValidation, got %v", err)
			}
			if !tc.wantErr && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
		})
	}
}

func TestExtractedUnit_ValidateTrimsFields(t *testing.T) {
	u := ExtractedUnit{Kind: KindGrammar, Canonical: "  x  ", Statement: "  y  ", Example: strptr("  z  "), Confidence: 0.5}
	if err := u.Validate(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if u.Canonical != "x" || u.Statement != "y" {
		t.Fatalf("fields not trimmed: %+v", u)
	}
	if u.Example == nil || *u.Example != "z" {
		t.Fatalf("example not trimmed: %+v", u.Example)
	}
}

func TestExtractedUnit_BlankExampleBecomesNil(t *testing.T) {
	u := ExtractedUnit{Kind: KindGrammar, Canonical: "x", Statement: "y", Example: strptr("   "), Confidence: 0.5}
	if err := u.Validate(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if u.Example != nil {
		t.Fatalf("blank example should become nil, got %q", *u.Example)
	}
}

func TestExtractionResult_EmptyIsValid(t *testing.T) {
	r := ExtractionResult{}
	if err := r.Validate(); err != nil {
		t.Fatalf("empty result must be valid, got %v", err)
	}
}

func TestExtractionResult_RejectsExactDuplicates(t *testing.T) {
	r := ExtractionResult{Units: []ExtractedUnit{
		{Kind: KindGrammar, Canonical: "vouloir", Statement: "same", Confidence: 0.8},
		{Kind: KindGrammar, Canonical: "Vouloir", Statement: "SAME", Confidence: 0.9}, // normalizes identical
	}}
	if err := r.Validate(); !errors.Is(err, ErrValidation) {
		t.Fatalf("expected ErrValidation for exact duplicate, got %v", err)
	}
}

func TestExtractionResult_DistinctUnitsAreValid(t *testing.T) {
	r := ExtractionResult{Units: []ExtractedUnit{
		{Kind: KindGrammar, Canonical: "vouloir", Statement: "a", Confidence: 0.8},
		{Kind: KindVocabulary, Canonical: "vouloir", Statement: "a", Confidence: 0.8}, // different kind
	}}
	if err := r.Validate(); err != nil {
		t.Fatalf("distinct units (different kind) must be valid, got %v", err)
	}
}

func TestNormalizeCanonical(t *testing.T) {
	cases := map[string]string{
		"  Vouloir  ":            "vouloir",
		"le   Marché":            "le marché", // accents preserved, whitespace collapsed
		"PRÉSENT de l'indicatif": "présent de l'indicatif",
	}
	for in, want := range cases {
		if got := NormalizeCanonical(in); got != want {
			t.Errorf("NormalizeCanonical(%q) = %q, want %q", in, got, want)
		}
	}
}
