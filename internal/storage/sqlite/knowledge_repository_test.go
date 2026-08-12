package sqlite

import (
	"context"
	"errors"
	"path/filepath"
	"testing"

	"french-learning-app/internal/domain"
)

// newKnowledgeTestRepos opens a fresh migrated database and returns the repos
// needed to exercise the knowledge-extraction and admission storage.
func newKnowledgeTestRepos(t *testing.T) (*EntryRepository, *KnowledgeRepository, *AdmissionRepository) {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "knowledge.db")
	db, err := Open(dbPath)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return NewEntryRepository(db), NewKnowledgeRepository(db), NewAdmissionRepository(db)
}

// seedEntryWithAnalysis creates an entry and an analysis so an extraction can
// reference a real source analysis id (the FK is ON DELETE RESTRICT).
func seedEntryWithAnalysis(t *testing.T, entries *EntryRepository, db *KnowledgeRepository) (entryID, analysisID int64) {
	t.Helper()
	ctx := context.Background()
	entry, err := entries.Create(ctx, domain.NewEntryInput{OriginalInput: "Je veux aller au marché"})
	if err != nil {
		t.Fatalf("create entry: %v", err)
	}
	analyses := NewAnalysisRepository(db.db)
	a, err := analyses.Create(ctx, entry.ID, domain.AnalysisResult{
		Category: "grammar", Explanation: "vouloir + infinitive", Confidence: 0.8,
	}, "rule-based:test")
	if err != nil {
		t.Fatalf("create analysis: %v", err)
	}
	return entry.ID, a.ID
}

func sampleUnits() []domain.ExtractedUnit {
	return []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "vouloir + inf", Statement: "vouloir takes a bare infinitive", Confidence: 0.9},
		{Kind: domain.KindVocabulary, Canonical: "le marché", Statement: "market", Confidence: 0.7},
	}
}

func TestKnowledgeRepository_CreateZeroUnits(t *testing.T) {
	entries, knowledge, _ := newKnowledgeTestRepos(t)
	entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)

	view, err := knowledge.Create(context.Background(), domain.NewExtractionInput{
		EntryID:          entryID,
		SourceAnalysisID: analysisID,
		Extractor:        "openai:test:knowledge_extraction_v1",
		Units:            nil,
		Recommendations:  nil,
	})
	if err != nil {
		t.Fatalf("create extraction: %v", err)
	}
	if view.Extraction.Version != 1 {
		t.Fatalf("version = %d, want 1", view.Extraction.Version)
	}
	if len(view.Units) != 0 {
		t.Fatalf("expected 0 units, got %d", len(view.Units))
	}
}

func TestKnowledgeRepository_CreateMultipleUnitsAndOrdinals(t *testing.T) {
	entries, knowledge, _ := newKnowledgeTestRepos(t)
	entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)

	units := sampleUnits()
	recs := domain.ApplyAdmissionV1(units)
	view, err := knowledge.Create(context.Background(), domain.NewExtractionInput{
		EntryID:          entryID,
		SourceAnalysisID: analysisID,
		Extractor:        "openai:test:knowledge_extraction_v1",
		Units:            units,
		Recommendations:  recs,
	})
	if err != nil {
		t.Fatalf("create extraction: %v", err)
	}
	if len(view.Units) != 2 {
		t.Fatalf("got %d units, want 2", len(view.Units))
	}
	if view.Units[0].Unit.Ordinal != 1 || view.Units[1].Unit.Ordinal != 2 {
		t.Fatalf("ordinals not deterministic: %d, %d", view.Units[0].Unit.Ordinal, view.Units[1].Unit.Ordinal)
	}
	// Each unit carries a machine recommendation with the fixed ruleset name.
	for _, u := range view.Units {
		if u.Admission.Recommendation.Ruleset != domain.AdmissionRulesetName {
			t.Fatalf("ruleset = %q", u.Admission.Recommendation.Ruleset)
		}
		if u.Admission.Effective != domain.AdmissionActive {
			t.Fatalf("expected active effective state, got %q", u.Admission.Effective)
		}
	}
}

func TestKnowledgeRepository_VersionIncrements(t *testing.T) {
	entries, knowledge, _ := newKnowledgeTestRepos(t)
	entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)
	ctx := context.Background()

	in := domain.NewExtractionInput{EntryID: entryID, SourceAnalysisID: analysisID, Extractor: "openai:test:knowledge_extraction_v1"}
	first, err := knowledge.Create(ctx, in)
	if err != nil {
		t.Fatalf("first: %v", err)
	}
	second, err := knowledge.Create(ctx, in)
	if err != nil {
		t.Fatalf("second: %v", err)
	}
	if first.Extraction.Version != 1 || second.Extraction.Version != 2 {
		t.Fatalf("versions = %d, %d; want 1, 2", first.Extraction.Version, second.Extraction.Version)
	}
}

func TestKnowledgeRepository_ProvenancePersisted(t *testing.T) {
	entries, knowledge, _ := newKnowledgeTestRepos(t)
	entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)
	feedbackID := int64(0)
	// Attach a feedback so we can record its id as provenance.
	fbRepo := NewFeedbackRepository(knowledge.db)
	fb, err := fbRepo.Create(context.Background(), analysisID, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})
	if err != nil {
		t.Fatalf("create feedback: %v", err)
	}
	feedbackID = fb.ID

	view, err := knowledge.Create(context.Background(), domain.NewExtractionInput{
		EntryID:          entryID,
		SourceAnalysisID: analysisID,
		SourceFeedbackID: &feedbackID,
		Extractor:        "openai:test:knowledge_extraction_v1",
	})
	if err != nil {
		t.Fatalf("create extraction: %v", err)
	}

	got, err := knowledge.GetByID(context.Background(), view.Extraction.ID)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.Extraction.SourceAnalysisID != analysisID {
		t.Fatalf("source analysis id = %d, want %d", got.Extraction.SourceAnalysisID, analysisID)
	}
	if got.Extraction.SourceFeedbackID == nil || *got.Extraction.SourceFeedbackID != feedbackID {
		t.Fatalf("source feedback id not persisted: %v", got.Extraction.SourceFeedbackID)
	}
}

func TestKnowledgeRepository_CreateEntryNotFound(t *testing.T) {
	_, knowledge, _ := newKnowledgeTestRepos(t)
	_, err := knowledge.Create(context.Background(), domain.NewExtractionInput{
		EntryID: 9999, SourceAnalysisID: 1, Extractor: "x",
	})
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

func TestKnowledgeRepository_AtomicRollbackOnBadRecommendationCount(t *testing.T) {
	entries, knowledge, _ := newKnowledgeTestRepos(t)
	entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)

	// Units and recommendations length mismatch -> the whole create must fail
	// before writing anything.
	_, err := knowledge.Create(context.Background(), domain.NewExtractionInput{
		EntryID:          entryID,
		SourceAnalysisID: analysisID,
		Extractor:        "x",
		Units:            sampleUnits(),
		Recommendations:  nil, // mismatch
	})
	if err == nil {
		t.Fatal("expected error on length mismatch")
	}
	// Nothing should have been persisted.
	list, err := knowledge.ListByEntry(context.Background(), entryID)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(list) != 0 {
		t.Fatalf("expected no extractions after failed create, got %d", len(list))
	}
}

func TestKnowledgeRepository_ListByEntryNewestFirst(t *testing.T) {
	entries, knowledge, _ := newKnowledgeTestRepos(t)
	entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)
	ctx := context.Background()
	in := domain.NewExtractionInput{EntryID: entryID, SourceAnalysisID: analysisID, Extractor: "x"}
	_, _ = knowledge.Create(ctx, in)
	_, _ = knowledge.Create(ctx, in)

	list, err := knowledge.ListByEntry(ctx, entryID)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(list) != 2 || list[0].Extraction.Version != 2 || list[1].Extraction.Version != 1 {
		t.Fatalf("expected newest-first [2,1], got %d items", len(list))
	}
}

func TestKnowledgeRepository_GetByIDNotFound(t *testing.T) {
	_, knowledge, _ := newKnowledgeTestRepos(t)
	_, err := knowledge.GetByID(context.Background(), 9999)
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

func TestKnowledgeRepository_ExactDuplicateRecommendationPersisted(t *testing.T) {
	entries, knowledge, _ := newKnowledgeTestRepos(t)
	entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)

	units := []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "vouloir", Statement: "a", Confidence: 0.9},
		{Kind: domain.KindGrammar, Canonical: "vouloir", Statement: "b", Confidence: 0.9},
	}
	recs := domain.ApplyAdmissionV1(units)
	view, err := knowledge.Create(context.Background(), domain.NewExtractionInput{
		EntryID: entryID, SourceAnalysisID: analysisID, Extractor: "x", Units: units, Recommendations: recs,
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if view.Units[1].Admission.Recommendation.State != domain.AdmissionSuppressed ||
		view.Units[1].Admission.Recommendation.Reason != domain.ReasonExactDuplicate {
		t.Fatalf("second unit should be suppressed exact_duplicate, got %+v", view.Units[1].Admission.Recommendation)
	}
	// The suppressed unit still exists historically.
	if view.Units[1].Unit.ID == 0 {
		t.Fatal("suppressed duplicate unit should still be persisted")
	}
}

// ---- admission overrides ----

func seedUnit(t *testing.T, entries *EntryRepository, knowledge *KnowledgeRepository) int64 {
	t.Helper()
	entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)
	units := []domain.ExtractedUnit{{Kind: domain.KindGrammar, Canonical: "x", Statement: "y", Confidence: 0.9}}
	view, err := knowledge.Create(context.Background(), domain.NewExtractionInput{
		EntryID: entryID, SourceAnalysisID: analysisID, Extractor: "x",
		Units: units, Recommendations: domain.ApplyAdmissionV1(units),
	})
	if err != nil {
		t.Fatalf("seed unit: %v", err)
	}
	return view.Units[0].Unit.ID
}

func TestAdmissionRepository_OverrideAppendOnlyAndEffective(t *testing.T) {
	entries, knowledge, admission := newKnowledgeTestRepos(t)
	unitID := seedUnit(t, entries, knowledge)
	ctx := context.Background()

	// Machine default is active. Human suppresses (mastered).
	if _, err := admission.Create(ctx, unitID, domain.NewAdmissionOverrideInput{
		Decision: domain.HumanAdmitSuppressed, Reason: domain.HumanReasonMastered,
	}); err != nil {
		t.Fatalf("first override: %v", err)
	}
	// Human then reactivates.
	if _, err := admission.Create(ctx, unitID, domain.NewAdmissionOverrideInput{
		Decision: domain.HumanAdmitActive,
	}); err != nil {
		t.Fatalf("second override: %v", err)
	}

	// History is preserved (append-only): both overrides present, oldest first.
	history, err := admission.ListByUnit(ctx, unitID)
	if err != nil {
		t.Fatalf("list overrides: %v", err)
	}
	if len(history) != 2 {
		t.Fatalf("expected 2 overrides, got %d", len(history))
	}
	if history[0].Decision != domain.HumanAdmitSuppressed || history[1].Decision != domain.HumanAdmitActive {
		t.Fatalf("override history order wrong: %+v", history)
	}

	// Effective state follows the latest override (active), and the machine
	// recommendation is unchanged.
	state, err := admission.GetAdmission(ctx, unitID)
	if err != nil {
		t.Fatalf("get admission: %v", err)
	}
	if state.Effective != domain.AdmissionActive {
		t.Fatalf("effective = %q, want active (latest override wins)", state.Effective)
	}
	if state.Recommendation.State != domain.AdmissionActive || state.Recommendation.Reason != domain.ReasonDefaultActive {
		t.Fatalf("machine recommendation must be unchanged, got %+v", state.Recommendation)
	}
}

func TestAdmissionRepository_OverrideUnitNotFound(t *testing.T) {
	_, _, admission := newKnowledgeTestRepos(t)
	_, err := admission.Create(context.Background(), 9999, domain.NewAdmissionOverrideInput{Decision: domain.HumanAdmitActive})
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

func TestAdmissionRepository_GetAdmissionUnitNotFound(t *testing.T) {
	_, _, admission := newKnowledgeTestRepos(t)
	_, err := admission.GetAdmission(context.Background(), 9999)
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

func TestKnowledgeRepository_LaterFeedbackDoesNotMutateOldExtraction(t *testing.T) {
	entries, knowledge, _ := newKnowledgeTestRepos(t)
	entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)
	ctx := context.Background()

	// First extraction with no feedback in provenance.
	first, err := knowledge.Create(ctx, domain.NewExtractionInput{
		EntryID: entryID, SourceAnalysisID: analysisID, Extractor: "x",
	})
	if err != nil {
		t.Fatalf("first extraction: %v", err)
	}

	// Add feedback afterwards, then a second extraction referencing it.
	fbRepo := NewFeedbackRepository(knowledge.db)
	fb, err := fbRepo.Create(ctx, analysisID, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})
	if err != nil {
		t.Fatalf("feedback: %v", err)
	}
	if _, err := knowledge.Create(ctx, domain.NewExtractionInput{
		EntryID: entryID, SourceAnalysisID: analysisID, SourceFeedbackID: &fb.ID, Extractor: "x",
	}); err != nil {
		t.Fatalf("second extraction: %v", err)
	}

	// The first extraction's provenance is unchanged (no feedback id).
	got, err := knowledge.GetByID(ctx, first.Extraction.ID)
	if err != nil {
		t.Fatalf("get first: %v", err)
	}
	if got.Extraction.SourceFeedbackID != nil {
		t.Fatalf("old extraction provenance was mutated: %v", got.Extraction.SourceFeedbackID)
	}
}
