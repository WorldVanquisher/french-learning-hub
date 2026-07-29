package application

import (
	"context"
	"errors"
	"testing"

	"french-learning-app/internal/domain"
)

// fakeFeedbackRepo is a small hand-written fake domain.FeedbackRepository.
// It records how it was called so tests can assert delegation and, crucially,
// whether Create was reached at all (to prove validation happens first).
type fakeFeedbackRepo struct {
	createCalls int
	lastCreteID int64
	lastInput   domain.NewFeedbackInput

	listCalls  int
	lastListID int64

	createResult *domain.Feedback
	createErr    error
	listResult   []*domain.Feedback
	listErr      error
}

func (f *fakeFeedbackRepo) Create(_ context.Context, analysisID int64, in domain.NewFeedbackInput) (*domain.Feedback, error) {
	f.createCalls++
	f.lastCreteID = analysisID
	f.lastInput = in
	return f.createResult, f.createErr
}

func (f *fakeFeedbackRepo) ListByAnalysis(_ context.Context, analysisID int64) ([]*domain.Feedback, error) {
	f.listCalls++
	f.lastListID = analysisID
	return f.listResult, f.listErr
}

func strptr(s string) *string { return &s }

func TestFeedbackService_AddFeedback_ValidPassedToRepository(t *testing.T) {
	want := &domain.Feedback{ID: 5, AnalysisID: 3, Status: domain.FeedbackAccepted}
	repo := &fakeFeedbackRepo{createResult: want}
	svc := NewFeedbackService(repo)

	got, err := svc.AddFeedback(context.Background(), 3, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != want {
		t.Fatalf("got %+v, want %+v", got, want)
	}
	if repo.createCalls != 1 {
		t.Fatalf("expected Create to be called once, got %d", repo.createCalls)
	}
	if repo.lastCreteID != 3 {
		t.Fatalf("expected analysisID 3, got %d", repo.lastCreteID)
	}
	if repo.lastInput.Status != domain.FeedbackAccepted {
		t.Fatalf("unexpected input passed: %+v", repo.lastInput)
	}
}

func TestFeedbackService_AddFeedback_InvalidRejectedBeforeRepository(t *testing.T) {
	repo := &fakeFeedbackRepo{}
	svc := NewFeedbackService(repo)

	// "corrected" with no corrected fields is invalid under the relaxed rule.
	_, err := svc.AddFeedback(context.Background(), 3, domain.NewFeedbackInput{Status: domain.FeedbackCorrected})
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("expected ErrValidation, got %v", err)
	}
	if repo.createCalls != 0 {
		t.Fatalf("repository Create must not be called on invalid input, got %d calls", repo.createCalls)
	}
}

func TestFeedbackService_AddFeedback_PropagatesRepositoryError(t *testing.T) {
	repo := &fakeFeedbackRepo{createErr: domain.ErrNotFound}
	svc := NewFeedbackService(repo)

	_, err := svc.AddFeedback(context.Background(), 999, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound to propagate, got %v", err)
	}
	if repo.createCalls != 1 {
		t.Fatalf("expected Create to be called once, got %d", repo.createCalls)
	}
}

func TestFeedbackService_AddFeedback_PropagatesGenericError(t *testing.T) {
	sentinel := errors.New("boom")
	repo := &fakeFeedbackRepo{createErr: sentinel}
	svc := NewFeedbackService(repo)

	_, err := svc.AddFeedback(context.Background(), 3, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})
	if !errors.Is(err, sentinel) {
		t.Fatalf("expected sentinel error to propagate, got %v", err)
	}
}

func TestFeedbackService_ListFeedback_Delegates(t *testing.T) {
	want := []*domain.Feedback{{ID: 1, AnalysisID: 7}, {ID: 2, AnalysisID: 7}}
	repo := &fakeFeedbackRepo{listResult: want}
	svc := NewFeedbackService(repo)

	got, err := svc.ListFeedback(context.Background(), 7)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(got) != 2 {
		t.Fatalf("expected 2 records, got %d", len(got))
	}
	if repo.listCalls != 1 || repo.lastListID != 7 {
		t.Fatalf("expected ListByAnalysis(7) once, got calls=%d id=%d", repo.listCalls, repo.lastListID)
	}
}

func TestFeedbackService_ListFeedback_PropagatesNotFound(t *testing.T) {
	repo := &fakeFeedbackRepo{listErr: domain.ErrNotFound}
	svc := NewFeedbackService(repo)

	_, err := svc.ListFeedback(context.Background(), 999)
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound to remain detectable via errors.Is, got %v", err)
	}
}
