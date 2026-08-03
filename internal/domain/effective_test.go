package domain

import "testing"

func sampleAnalysis() *Analysis {
	return &Analysis{
		ID:          12,
		EntryID:     5,
		Version:     2,
		Category:    "grammar",
		Explanation: "Original explanation",
	}
}

func TestResolveEffective_Unreviewed(t *testing.T) {
	a := sampleAnalysis()
	eff := ResolveEffective(a, nil)

	if eff.Resolution != ResolutionUnreviewed {
		t.Fatalf("resolution = %q, want unreviewed", eff.Resolution)
	}
	if eff.Effective == nil {
		t.Fatal("effective must be present for unreviewed")
	}
	if eff.Effective.Category != a.Category || eff.Effective.Explanation != a.Explanation {
		t.Fatalf("effective should equal original, got %+v", eff.Effective)
	}
	if eff.FeedbackID != nil {
		t.Fatalf("feedback id must be nil for unreviewed, got %v", *eff.FeedbackID)
	}
	if eff.AnalysisID != a.ID || eff.EntryID != a.EntryID || eff.Version != a.Version {
		t.Fatalf("identity fields not carried through: %+v", eff)
	}
}

func TestResolveEffective_Accepted(t *testing.T) {
	a := sampleAnalysis()
	fb := &Feedback{ID: 7, AnalysisID: a.ID, Status: FeedbackAccepted}
	eff := ResolveEffective(a, fb)

	if eff.Resolution != ResolutionAccepted {
		t.Fatalf("resolution = %q, want accepted", eff.Resolution)
	}
	if eff.Effective == nil || eff.Effective.Category != "grammar" || eff.Effective.Explanation != "Original explanation" {
		t.Fatalf("accepted effective should equal original, got %+v", eff.Effective)
	}
	if eff.FeedbackID == nil || *eff.FeedbackID != 7 {
		t.Fatalf("feedback id = %v, want 7", eff.FeedbackID)
	}
}

func TestResolveEffective_CorrectedBothFields(t *testing.T) {
	a := sampleAnalysis()
	fb := &Feedback{ID: 9, AnalysisID: a.ID, Status: FeedbackCorrected,
		CorrectedCategory: strptr("morphology"), CorrectedExplanation: strptr("Corrected explanation")}
	eff := ResolveEffective(a, fb)

	if eff.Resolution != ResolutionCorrected {
		t.Fatalf("resolution = %q, want corrected", eff.Resolution)
	}
	if eff.Effective.Category != "morphology" || eff.Effective.Explanation != "Corrected explanation" {
		t.Fatalf("both fields should be overridden, got %+v", eff.Effective)
	}
	if *eff.FeedbackID != 9 {
		t.Fatalf("feedback id = %v, want 9", *eff.FeedbackID)
	}
}

func TestResolveEffective_CorrectedCategoryOnly(t *testing.T) {
	a := sampleAnalysis()
	fb := &Feedback{ID: 3, AnalysisID: a.ID, Status: FeedbackCorrected, CorrectedCategory: strptr("morphology")}
	eff := ResolveEffective(a, fb)

	if eff.Effective.Category != "morphology" {
		t.Fatalf("category should be overridden, got %q", eff.Effective.Category)
	}
	if eff.Effective.Explanation != a.Explanation {
		t.Fatalf("explanation should retain original, got %q", eff.Effective.Explanation)
	}
}

func TestResolveEffective_CorrectedExplanationOnly(t *testing.T) {
	a := sampleAnalysis()
	fb := &Feedback{ID: 3, AnalysisID: a.ID, Status: FeedbackCorrected, CorrectedExplanation: strptr("Corrected explanation")}
	eff := ResolveEffective(a, fb)

	if eff.Effective.Category != a.Category {
		t.Fatalf("category should retain original, got %q", eff.Effective.Category)
	}
	if eff.Effective.Explanation != "Corrected explanation" {
		t.Fatalf("explanation should be overridden, got %q", eff.Effective.Explanation)
	}
}

func TestResolveEffective_Rejected(t *testing.T) {
	a := sampleAnalysis()
	fb := &Feedback{ID: 21, AnalysisID: a.ID, Status: FeedbackRejected}
	eff := ResolveEffective(a, fb)

	if eff.Resolution != ResolutionRejected {
		t.Fatalf("resolution = %q, want rejected", eff.Resolution)
	}
	if eff.Effective != nil {
		t.Fatalf("rejected must have absent (nil) effective, got %+v", eff.Effective)
	}
	// Original must still be present.
	if eff.Original.Category != "grammar" || eff.Original.Explanation != "Original explanation" {
		t.Fatalf("original should be preserved, got %+v", eff.Original)
	}
	if *eff.FeedbackID != 21 {
		t.Fatalf("feedback id = %v, want 21", *eff.FeedbackID)
	}
}

func TestResolveEffective_DoesNotMutateAnalysis(t *testing.T) {
	a := sampleAnalysis()
	fb := &Feedback{ID: 9, AnalysisID: a.ID, Status: FeedbackCorrected,
		CorrectedCategory: strptr("morphology"), CorrectedExplanation: strptr("Corrected explanation")}
	_ = ResolveEffective(a, fb)

	if a.Category != "grammar" || a.Explanation != "Original explanation" {
		t.Fatalf("original analysis was mutated: %+v", a)
	}
}
