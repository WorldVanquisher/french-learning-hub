package sqlite

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"french-learning-app/internal/domain"
)

// timeMustParse parses an RFC3339 timestamp for tests, failing on error.
func timeMustParse(t *testing.T, s string) time.Time {
	t.Helper()
	ts, err := time.Parse(time.RFC3339, s)
	if err != nil {
		t.Fatalf("parse time %q: %v", s, err)
	}
	return ts.UTC()
}

func newTestFeedbackRepos(t *testing.T) (*EntryRepository, *AnalysisRepository, *FeedbackRepository) {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "test.db")
	db, err := Open(dbPath)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return NewEntryRepository(db), NewAnalysisRepository(db), NewFeedbackRepository(db)
}

// seedAnalysis creates an entry and an analysis, returning the analysis.
func seedAnalysis(t *testing.T, entries *EntryRepository, analyses *AnalysisRepository) *domain.Analysis {
	t.Helper()
	ctx := context.Background()
	entry, err := entries.Create(ctx, domain.NewEntryInput{OriginalInput: "bonjour"})
	if err != nil {
		t.Fatalf("create entry: %v", err)
	}
	analysis, err := analyses.Create(ctx, entry.ID, domain.AnalysisResult{
		Category: "vocabulary", Explanation: "means hello", Confidence: 0.7,
	}, "rule-based")
	if err != nil {
		t.Fatalf("create analysis: %v", err)
	}
	return analysis
}

func sptr(s string) *string { return &s }

func TestFeedbackRepository_Create_AllStatuses(t *testing.T) {
	entries, analyses, feedback := newTestFeedbackRepos(t)
	analysis := seedAnalysis(t, entries, analyses)
	ctx := context.Background()

	accepted, err := feedback.Create(ctx, analysis.ID, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})
	if err != nil {
		t.Fatalf("create accepted: %v", err)
	}
	if accepted.ID == 0 || accepted.CreatedAt.IsZero() {
		t.Fatal("expected id and created_at to be set")
	}
	if accepted.CorrectedCategory != nil || accepted.CorrectedExplanation != nil {
		t.Fatal("accepted feedback should have no corrected content")
	}

	corrected, err := feedback.Create(ctx, analysis.ID, domain.NewFeedbackInput{
		Status:               domain.FeedbackCorrected,
		CorrectedCategory:    sptr("grammar"),
		CorrectedExplanation: sptr("verb conjugation"),
		UserNote:             "actually a grammar point",
	})
	if err != nil {
		t.Fatalf("create corrected: %v", err)
	}
	if corrected.CorrectedCategory == nil || *corrected.CorrectedCategory != "grammar" {
		t.Fatalf("corrected category not stored: %v", corrected.CorrectedCategory)
	}
	if corrected.CorrectedExplanation == nil || *corrected.CorrectedExplanation != "verb conjugation" {
		t.Fatalf("corrected explanation not stored: %v", corrected.CorrectedExplanation)
	}
}

func TestFeedbackRepository_Create_AnalysisNotFound(t *testing.T) {
	_, _, feedback := newTestFeedbackRepos(t)
	_, err := feedback.Create(context.Background(), 9999, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

// countFeedback returns the number of analysis_feedback rows.
func countFeedback(t *testing.T, r *FeedbackRepository) int {
	t.Helper()
	var n int
	if err := r.db.QueryRowContext(context.Background(), `SELECT COUNT(*) FROM analysis_feedback`).Scan(&n); err != nil {
		t.Fatalf("count feedback: %v", err)
	}
	return n
}

// TestFeedbackRepository_Create_RejectsInvalidWithoutInsert proves the
// repository validates input directly (not only via the service) and writes no
// row when validation fails.
func TestFeedbackRepository_Create_RejectsInvalidWithoutInsert(t *testing.T) {
	entries, analyses, feedback := newTestFeedbackRepos(t)
	analysis := seedAnalysis(t, entries, analyses)
	ctx := context.Background()

	invalid := []struct {
		name string
		in   domain.NewFeedbackInput
	}{
		{"corrected with neither field", domain.NewFeedbackInput{Status: domain.FeedbackCorrected}},
		{"corrected with both blank", domain.NewFeedbackInput{Status: domain.FeedbackCorrected, CorrectedCategory: sptr("  "), CorrectedExplanation: sptr("  ")}},
		{"unknown status", domain.NewFeedbackInput{Status: domain.FeedbackStatus("maybe")}},
		{"accepted with corrected category", domain.NewFeedbackInput{Status: domain.FeedbackAccepted, CorrectedCategory: sptr("grammar")}},
		{"rejected with corrected explanation", domain.NewFeedbackInput{Status: domain.FeedbackRejected, CorrectedExplanation: sptr("x")}},
	}

	for _, tc := range invalid {
		t.Run(tc.name, func(t *testing.T) {
			_, err := feedback.Create(ctx, analysis.ID, tc.in)
			if !errors.Is(err, domain.ErrValidation) {
				t.Fatalf("expected ErrValidation, got %v", err)
			}
		})
	}

	if got := countFeedback(t, feedback); got != 0 {
		t.Fatalf("expected no feedback rows after validation failures, got %d", got)
	}
}

func TestFeedbackRepository_Create_CorrectedSingleField(t *testing.T) {
	entries, analyses, feedback := newTestFeedbackRepos(t)
	analysis := seedAnalysis(t, entries, analyses)
	ctx := context.Background()

	// Only corrected_category.
	catOnly, err := feedback.Create(ctx, analysis.ID, domain.NewFeedbackInput{
		Status:            domain.FeedbackCorrected,
		CorrectedCategory: sptr("grammar"),
	})
	if err != nil {
		t.Fatalf("create corrected (category only): %v", err)
	}
	if catOnly.CorrectedCategory == nil || *catOnly.CorrectedCategory != "grammar" {
		t.Fatalf("category not stored: %v", catOnly.CorrectedCategory)
	}
	if catOnly.CorrectedExplanation != nil {
		t.Fatalf("explanation should be absent: %v", catOnly.CorrectedExplanation)
	}

	// Only corrected_explanation.
	explOnly, err := feedback.Create(ctx, analysis.ID, domain.NewFeedbackInput{
		Status:               domain.FeedbackCorrected,
		CorrectedExplanation: sptr("present tense"),
	})
	if err != nil {
		t.Fatalf("create corrected (explanation only): %v", err)
	}
	if explOnly.CorrectedExplanation == nil || *explOnly.CorrectedExplanation != "present tense" {
		t.Fatalf("explanation not stored: %v", explOnly.CorrectedExplanation)
	}
	if explOnly.CorrectedCategory != nil {
		t.Fatalf("category should be absent: %v", explOnly.CorrectedCategory)
	}

	if got := countFeedback(t, feedback); got != 2 {
		t.Fatalf("expected 2 feedback rows, got %d", got)
	}
}

func TestFeedbackRepository_ListByAnalysis_PreservesHistory(t *testing.T) {
	entries, analyses, feedback := newTestFeedbackRepos(t)
	analysis := seedAnalysis(t, entries, analyses)
	ctx := context.Background()

	// Empty first.
	got, err := feedback.ListByAnalysis(ctx, analysis.ID)
	if err != nil {
		t.Fatalf("list empty: %v", err)
	}
	if len(got) != 0 {
		t.Fatalf("expected 0 feedback, got %d", len(got))
	}

	inputs := []domain.NewFeedbackInput{
		{Status: domain.FeedbackRejected, UserNote: "wrong"},
		{Status: domain.FeedbackCorrected, CorrectedCategory: sptr("grammar"), CorrectedExplanation: sptr("x")},
		{Status: domain.FeedbackAccepted},
	}
	for _, in := range inputs {
		if _, err := feedback.Create(ctx, analysis.ID, in); err != nil {
			t.Fatalf("create feedback: %v", err)
		}
	}

	got, err = feedback.ListByAnalysis(ctx, analysis.ID)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(got) != 3 {
		t.Fatalf("expected 3 feedback records (history preserved), got %d", len(got))
	}
	// Oldest first.
	if got[0].Status != domain.FeedbackRejected || got[2].Status != domain.FeedbackAccepted {
		t.Fatalf("unexpected order: %+v", got)
	}
}

func TestFeedbackRepository_ListByAnalysis_NotFound(t *testing.T) {
	_, _, feedback := newTestFeedbackRepos(t)
	_, err := feedback.ListByAnalysis(context.Background(), 9999)
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

func TestFeedbackRepository_GetLatestByAnalysis_MissingAnalysis(t *testing.T) {
	_, _, feedback := newTestFeedbackRepos(t)
	_, err := feedback.GetLatestByAnalysis(context.Background(), 9999)
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound for missing analysis, got %v", err)
	}
}

func TestFeedbackRepository_GetLatestByAnalysis_NoFeedback(t *testing.T) {
	entries, analyses, feedback := newTestFeedbackRepos(t)
	analysis := seedAnalysis(t, entries, analyses)

	// Existing analysis, no feedback: (nil, nil), distinct from ErrNotFound.
	latest, err := feedback.GetLatestByAnalysis(context.Background(), analysis.ID)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if latest != nil {
		t.Fatalf("expected nil feedback for analysis with no feedback, got %+v", latest)
	}
}

func TestFeedbackRepository_GetLatestByAnalysis_MultipleRecords(t *testing.T) {
	entries, analyses, feedback := newTestFeedbackRepos(t)
	analysis := seedAnalysis(t, entries, analyses)
	ctx := context.Background()

	// created_at increments with each Create (real clock); the last one wins.
	for _, in := range []domain.NewFeedbackInput{
		{Status: domain.FeedbackRejected, UserNote: "first"},
		{Status: domain.FeedbackCorrected, CorrectedCategory: sptr("grammar")},
		{Status: domain.FeedbackAccepted, UserNote: "last"},
	} {
		if _, err := feedback.Create(ctx, analysis.ID, in); err != nil {
			t.Fatalf("create feedback: %v", err)
		}
	}

	latest, err := feedback.GetLatestByAnalysis(ctx, analysis.ID)
	if err != nil {
		t.Fatalf("get latest: %v", err)
	}
	if latest == nil || latest.Status != domain.FeedbackAccepted {
		t.Fatalf("expected latest to be the accepted record, got %+v", latest)
	}
}

func TestFeedbackRepository_GetLatestByAnalysis_IdenticalTimestampsTieByID(t *testing.T) {
	entries, analyses, feedback := newTestFeedbackRepos(t)
	analysis := seedAnalysis(t, entries, analyses)
	ctx := context.Background()

	// Force identical created_at for every record so ordering must fall back to
	// id DESC. The repository's now hook is settable within the sqlite package.
	fixed := timeMustParse(t, "2026-07-29T12:00:00Z")
	feedback.now = func() time.Time { return fixed }

	// Insert three; the highest id (last inserted) must win despite equal times.
	first, err := feedback.Create(ctx, analysis.ID, domain.NewFeedbackInput{Status: domain.FeedbackRejected})
	if err != nil {
		t.Fatalf("create first: %v", err)
	}
	if _, err := feedback.Create(ctx, analysis.ID, domain.NewFeedbackInput{Status: domain.FeedbackCorrected, CorrectedCategory: sptr("grammar")}); err != nil {
		t.Fatalf("create second: %v", err)
	}
	last, err := feedback.Create(ctx, analysis.ID, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})
	if err != nil {
		t.Fatalf("create last: %v", err)
	}

	latest, err := feedback.GetLatestByAnalysis(ctx, analysis.ID)
	if err != nil {
		t.Fatalf("get latest: %v", err)
	}
	if latest.ID != last.ID {
		t.Fatalf("tiebreak should pick highest id %d, got %d", last.ID, latest.ID)
	}
	if latest.ID == first.ID {
		t.Fatal("tiebreak picked the oldest row")
	}
	if latest.Status != domain.FeedbackAccepted {
		t.Fatalf("expected accepted (highest id), got %q", latest.Status)
	}
}

func TestFeedbackRepository_GetLatestByAnalysis_ByStatus(t *testing.T) {
	// Each subtest seeds a fresh analysis whose latest feedback has the target
	// status, confirming that status is surfaced correctly.
	cases := []struct {
		name string
		in   domain.NewFeedbackInput
		want domain.FeedbackStatus
	}{
		{"accepted", domain.NewFeedbackInput{Status: domain.FeedbackAccepted}, domain.FeedbackAccepted},
		{"corrected", domain.NewFeedbackInput{Status: domain.FeedbackCorrected, CorrectedCategory: sptr("morphology")}, domain.FeedbackCorrected},
		{"rejected", domain.NewFeedbackInput{Status: domain.FeedbackRejected}, domain.FeedbackRejected},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			entries, analyses, feedback := newTestFeedbackRepos(t)
			analysis := seedAnalysis(t, entries, analyses)
			ctx := context.Background()
			if _, err := feedback.Create(ctx, analysis.ID, tc.in); err != nil {
				t.Fatalf("create: %v", err)
			}
			latest, err := feedback.GetLatestByAnalysis(ctx, analysis.ID)
			if err != nil {
				t.Fatalf("get latest: %v", err)
			}
			if latest == nil || latest.Status != tc.want {
				t.Fatalf("latest status = %v, want %v", latest, tc.want)
			}
		})
	}
}

// TestFeedbackRepository_DoesNotMutateEntryOrAnalysis proves feedback never
// modifies the original entry or the analysis it references.
func TestFeedbackRepository_DoesNotMutateEntryOrAnalysis(t *testing.T) {
	entries, analyses, feedback := newTestFeedbackRepos(t)
	ctx := context.Background()

	entry, err := entries.Create(ctx, domain.NewEntryInput{OriginalInput: "Je suis", OriginalContext: "texting"})
	if err != nil {
		t.Fatalf("create entry: %v", err)
	}
	analysis, err := analyses.Create(ctx, entry.ID, domain.AnalysisResult{
		Category: "phrase", Explanation: "means I am", Confidence: 0.6, Uncertainty: "placeholder",
	}, "rule-based")
	if err != nil {
		t.Fatalf("create analysis: %v", err)
	}

	// Add a correction that proposes different metadata.
	if _, err := feedback.Create(ctx, analysis.ID, domain.NewFeedbackInput{
		Status:               domain.FeedbackCorrected,
		CorrectedCategory:    sptr("grammar"),
		CorrectedExplanation: sptr("completely different"),
	}); err != nil {
		t.Fatalf("create feedback: %v", err)
	}

	// Entry must be unchanged.
	gotEntry, err := entries.GetByID(ctx, entry.ID)
	if err != nil {
		t.Fatalf("reload entry: %v", err)
	}
	if gotEntry.OriginalInput != "Je suis" || gotEntry.OriginalContext != "texting" {
		t.Fatalf("entry mutated: %+v", gotEntry)
	}

	// Analysis must be unchanged.
	list, err := analyses.ListByEntry(ctx, entry.ID)
	if err != nil {
		t.Fatalf("reload analyses: %v", err)
	}
	if len(list) != 1 {
		t.Fatalf("expected 1 analysis, got %d", len(list))
	}
	got := list[0]
	if got.Category != "phrase" || got.Explanation != "means I am" || got.Confidence != 0.6 {
		t.Fatalf("analysis mutated by feedback: %+v", got)
	}
}
