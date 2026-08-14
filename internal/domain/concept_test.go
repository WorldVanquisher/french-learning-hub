package domain

import (
	"errors"
	"testing"
)

func TestConceptIdentity_SignatureEqualForSameNormalizedIdentity(t *testing.T) {
	// Two different surface wordings that normalize to the same identity must
	// produce the same signature, so they can resolve SAME (required case 1).
	a := ConceptIdentity{
		Target:            "  Vouloir + Infinitif ",
		PedagogicalIntent: "Grammar",
		IdentityFeatures:  map[string]string{"Mood": "Indicatif"},
	}
	b := ConceptIdentity{
		Target:            "vouloir + infinitif",
		PedagogicalIntent: "grammar",
		IdentityFeatures:  map[string]string{"mood": "indicatif"},
	}
	if a.Signature() != b.Signature() {
		t.Fatalf("expected identical signatures, got %q vs %q", a.Signature(), b.Signature())
	}
}

func TestConceptIdentity_SignatureDiffersOnIdentityFeatures(t *testing.T) {
	// Differing identity-bearing features must NOT collide (required case 2 at the
	// signature level).
	a := ConceptIdentity{Target: "parler", PedagogicalIntent: "morphology", IdentityFeatures: map[string]string{"tense": "present"}}
	b := ConceptIdentity{Target: "parler", PedagogicalIntent: "morphology", IdentityFeatures: map[string]string{"tense": "imparfait"}}
	if a.Signature() == b.Signature() {
		t.Fatal("expected differing signatures for differing identity features")
	}

	// Differing scope also separates identity.
	c := ConceptIdentity{Target: "de", PedagogicalIntent: "usage", Scope: "partitive"}
	d := ConceptIdentity{Target: "de", PedagogicalIntent: "usage", Scope: "possession"}
	if c.Signature() == d.Signature() {
		t.Fatal("expected differing signatures for differing scope")
	}
}

func TestConceptIdentity_SignatureFeatureOrderIndependent(t *testing.T) {
	a := ConceptIdentity{Target: "x", PedagogicalIntent: "grammar", IdentityFeatures: map[string]string{"a": "1", "b": "2"}}
	b := ConceptIdentity{Target: "x", PedagogicalIntent: "grammar", IdentityFeatures: map[string]string{"b": "2", "a": "1"}}
	if a.Signature() != b.Signature() {
		t.Fatal("signature must be independent of feature insertion order")
	}
}

func TestConceptIdentity_Validate(t *testing.T) {
	valid := ConceptIdentity{Target: "vouloir", PedagogicalIntent: "grammar"}
	if err := valid.Validate(); err != nil {
		t.Fatalf("expected valid, got %v", err)
	}

	missingTarget := ConceptIdentity{PedagogicalIntent: "grammar"}
	if err := missingTarget.Validate(); !errors.Is(err, ErrValidation) {
		t.Fatalf("expected ErrValidation for missing target, got %v", err)
	}
	missingIntent := ConceptIdentity{Target: "vouloir"}
	if err := missingIntent.Validate(); !errors.Is(err, ErrValidation) {
		t.Fatalf("expected ErrValidation for missing pedagogical_intent, got %v", err)
	}
}

func TestResolveConcept_DeterministicOutcomes(t *testing.T) {
	cand := ConceptIdentity{Target: "vouloir", PedagogicalIntent: "grammar"}

	if got := ResolveConcept(cand, nil); got != ResolutionNoMatch {
		t.Fatalf("no matches => no_match, got %q", got)
	}
	if got := ResolveConcept(cand, []KnowledgeConcept{{ID: 1}}); got != ResolutionMatched {
		t.Fatalf("one match => matched, got %q", got)
	}
	// More than one match must NOT force-merge; it stays reviewable (ambiguous).
	if got := ResolveConcept(cand, []KnowledgeConcept{{ID: 1}, {ID: 2}}); got != ResolutionAmbiguous {
		t.Fatalf("multiple matches => ambiguous, got %q", got)
	}
}

func TestDeriveCandidateIdentity(t *testing.T) {
	u := KnowledgeUnit{Kind: KindGrammar, Canonical: "  Vouloir + Inf "}
	id := DeriveCandidateIdentity(u)
	if id.Target != "vouloir + inf" {
		t.Fatalf("target = %q, want normalized canonical", id.Target)
	}
	if id.PedagogicalIntent != "grammar" {
		t.Fatalf("pedagogical_intent = %q, want kind", id.PedagogicalIntent)
	}
}
