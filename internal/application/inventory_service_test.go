package application

import (
	"context"
	"errors"
	"testing"

	"french-learning-app/internal/domain"
)

// fakeInventoryRepo records the query it received and returns canned results, so
// tests can assert the service normalizes before delegating.
type fakeInventoryRepo struct {
	gotQuery  domain.LearningRecordQuery
	listCalls int
	records   []*domain.LearningRecord
	listErr   error

	summary     *domain.LearningInventorySummary
	summaryErr  error
	summaryCall int
}

func (f *fakeInventoryRepo) ListLearningRecords(_ context.Context, q domain.LearningRecordQuery) ([]*domain.LearningRecord, error) {
	f.gotQuery = q
	f.listCalls++
	return f.records, f.listErr
}

func (f *fakeInventoryRepo) SummarizeLearningRecords(context.Context) (*domain.LearningInventorySummary, error) {
	f.summaryCall++
	return f.summary, f.summaryErr
}

func TestInventoryService_ListRecords_NormalizesDefaultLimit(t *testing.T) {
	repo := &fakeInventoryRepo{records: []*domain.LearningRecord{{EntryID: 1}}}
	svc := NewInventoryService(repo)

	_, limit, err := svc.ListRecords(context.Background(), domain.LearningRecordQuery{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if repo.gotQuery.Limit != defaultListLimit {
		t.Fatalf("repo saw limit %d, want default %d", repo.gotQuery.Limit, defaultListLimit)
	}
	if limit != defaultListLimit {
		t.Fatalf("returned limit %d, want %d", limit, defaultListLimit)
	}
}

func TestInventoryService_ListRecords_ClampsToMax(t *testing.T) {
	repo := &fakeInventoryRepo{}
	svc := NewInventoryService(repo)

	_, limit, err := svc.ListRecords(context.Background(), domain.LearningRecordQuery{Limit: 100000})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if repo.gotQuery.Limit != maxListLimit {
		t.Fatalf("repo saw limit %d, want clamped %d", repo.gotQuery.Limit, maxListLimit)
	}
	if limit != maxListLimit {
		t.Fatalf("returned limit %d, want %d", limit, maxListLimit)
	}
}

func TestInventoryService_ExportRecords_UsesExportLimits(t *testing.T) {
	repo := &fakeInventoryRepo{}
	svc := NewInventoryService(repo)

	// Default export limit when unset.
	if _, err := svc.ExportRecords(context.Background(), domain.LearningRecordQuery{}); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if repo.gotQuery.Limit != defaultExportLimit {
		t.Fatalf("export default limit = %d, want %d", repo.gotQuery.Limit, defaultExportLimit)
	}

	// Clamp to export max.
	if _, err := svc.ExportRecords(context.Background(), domain.LearningRecordQuery{Limit: 999999}); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if repo.gotQuery.Limit != maxExportLimit {
		t.Fatalf("export clamped limit = %d, want %d", repo.gotQuery.Limit, maxExportLimit)
	}
}

func TestInventoryService_ListRecords_InvalidState(t *testing.T) {
	repo := &fakeInventoryRepo{}
	svc := NewInventoryService(repo)

	bad := domain.LearningRecordState("bogus")
	_, _, err := svc.ListRecords(context.Background(), domain.LearningRecordQuery{State: &bad})
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("expected ErrValidation, got %v", err)
	}
	if repo.listCalls != 0 {
		t.Fatalf("repo should not be called on validation failure, calls=%d", repo.listCalls)
	}
}

func TestInventoryService_ListRecords_InvalidCategory(t *testing.T) {
	repo := &fakeInventoryRepo{}
	svc := NewInventoryService(repo)

	bad := domain.Category("not-a-category")
	_, _, err := svc.ListRecords(context.Background(), domain.LearningRecordQuery{Category: &bad})
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("expected ErrValidation, got %v", err)
	}
	if repo.listCalls != 0 {
		t.Fatalf("repo should not be called on validation failure")
	}
}

func TestInventoryService_ListRecords_InvalidCursor(t *testing.T) {
	repo := &fakeInventoryRepo{}
	svc := NewInventoryService(repo)

	zero := int64(0)
	_, _, err := svc.ListRecords(context.Background(), domain.LearningRecordQuery{BeforeEntryID: &zero})
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("expected ErrValidation for non-positive cursor, got %v", err)
	}
	if repo.listCalls != 0 {
		t.Fatalf("repo should not be called on validation failure")
	}
}

func TestInventoryService_ListRecords_DelegatesFilters(t *testing.T) {
	repo := &fakeInventoryRepo{}
	svc := NewInventoryService(repo)

	state := domain.LearningRecordState("ACCEPTED") // upper-case, should be normalized
	cat := domain.Category(" Grammar ")             // padded/mixed case, should be normalized
	cursor := int64(42)
	analyzer := "  rule-based:v2:fr_l2_taxonomy_v1  "
	_, _, err := svc.ListRecords(context.Background(), domain.LearningRecordQuery{
		State:         &state,
		Category:      &cat,
		Analyzer:      &analyzer,
		BeforeEntryID: &cursor,
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if repo.gotQuery.State == nil || *repo.gotQuery.State != domain.LearningRecordAccepted {
		t.Fatalf("state not normalized/delegated: %v", repo.gotQuery.State)
	}
	if repo.gotQuery.Category == nil || *repo.gotQuery.Category != "grammar" {
		t.Fatalf("category not normalized/delegated: %v", repo.gotQuery.Category)
	}
	if repo.gotQuery.Analyzer == nil || *repo.gotQuery.Analyzer != "rule-based:v2:fr_l2_taxonomy_v1" {
		t.Fatalf("analyzer not trimmed/delegated: %v", repo.gotQuery.Analyzer)
	}
	if repo.gotQuery.BeforeEntryID == nil || *repo.gotQuery.BeforeEntryID != 42 {
		t.Fatalf("cursor not delegated: %v", repo.gotQuery.BeforeEntryID)
	}
}

func TestInventoryService_Summary_Delegates(t *testing.T) {
	want := &domain.LearningInventorySummary{TotalEntries: 3}
	repo := &fakeInventoryRepo{summary: want}
	svc := NewInventoryService(repo)

	got, err := svc.Summary(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != want {
		t.Fatalf("summary not delegated")
	}
	if repo.summaryCall != 1 {
		t.Fatalf("expected 1 summary call, got %d", repo.summaryCall)
	}
}

func TestInventoryService_ListRecords_RepoErrorPassthrough(t *testing.T) {
	repoErr := errors.New("db down")
	repo := &fakeInventoryRepo{listErr: repoErr}
	svc := NewInventoryService(repo)

	_, _, err := svc.ListRecords(context.Background(), domain.LearningRecordQuery{})
	if !errors.Is(err, repoErr) {
		t.Fatalf("expected repo error to pass through, got %v", err)
	}
}
