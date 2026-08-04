package application

import (
	"context"
	"errors"
	"testing"

	"french-learning-app/internal/domain"
)

// fakeCaptureRepo records what the service hands the repository and returns
// scripted results, so service tests never touch SQL.
type fakeCaptureRepo struct {
	created   *domain.PreparedLearningCapture
	createRes domain.LearningCaptureResult
	createErr error

	lookupID  string
	lookupRes *domain.LearningCapture
	lookupErr error
}

func (f *fakeCaptureRepo) Create(_ context.Context, in domain.PreparedLearningCapture) (domain.LearningCaptureResult, error) {
	f.created = &in
	return f.createRes, f.createErr
}

func (f *fakeCaptureRepo) GetByCaptureID(_ context.Context, captureID string) (*domain.LearningCapture, error) {
	f.lookupID = captureID
	return f.lookupRes, f.lookupErr
}

func validServiceInput() domain.NewLearningCaptureInput {
	return domain.NewLearningCaptureInput{
		SchemaVersion:   domain.CaptureSchemaV1,
		CaptureID:       "cap-svc-1",
		Source:          domain.CaptureSourceChatGPTWeb,
		OriginalInput:   "Je parle japonais ?",
		OriginalContext: "article after parler",
		Analysis: &domain.ImportedAnalysisInput{
			Category:    "grammar",
			Explanation: "no article after parler",
			Confidence:  0.9,
			Uncertainty: "varies",
		},
		DiscussionSummary: "compared two phrasings",
	}
}

func TestImportCapture_PreparesAndDelegates(t *testing.T) {
	repo := &fakeCaptureRepo{createRes: domain.LearningCaptureResult{CaptureID: "cap-svc-1", EntryID: 5, Created: true}}
	svc := NewCaptureService(repo)

	res, err := svc.ImportCapture(context.Background(), validServiceInput())
	if err != nil {
		t.Fatalf("import: %v", err)
	}
	if !res.Created || res.EntryID != 5 {
		t.Fatalf("unexpected result: %+v", res)
	}
	if repo.created == nil {
		t.Fatal("repo.Create was not called")
	}
	p := repo.created

	// Server-derived provenance, never client-supplied.
	if p.AnalyzerProvenance != "imported:chatgpt-web:learning_capture_v1" {
		t.Fatalf("provenance = %q", p.AnalyzerProvenance)
	}
	// Fingerprint is computed by the service (non-empty and matches the canonical).
	if p.ContentFingerprint == "" {
		t.Fatal("fingerprint not computed")
	}
	if p.ContentFingerprint != domain.CaptureFingerprint(*p) {
		t.Fatal("fingerprint does not match canonical fingerprint of prepared content")
	}
	if p.Analysis == nil || p.Analysis.Category != "grammar" {
		t.Fatalf("analysis not carried through: %+v", p.Analysis)
	}
}

func TestImportCapture_NormalizesBeforeDelegating(t *testing.T) {
	repo := &fakeCaptureRepo{createRes: domain.LearningCaptureResult{Created: true}}
	svc := NewCaptureService(repo)

	in := validServiceInput()
	in.CaptureID = "  cap-svc-1  "
	in.OriginalInput = "  padded  "
	in.Analysis.Category = "  GRAMMAR  "

	if _, err := svc.ImportCapture(context.Background(), in); err != nil {
		t.Fatalf("import: %v", err)
	}
	p := repo.created
	if p.CaptureID != "cap-svc-1" {
		t.Fatalf("capture id not normalized: %q", p.CaptureID)
	}
	if p.OriginalInput != "padded" {
		t.Fatalf("input not normalized: %q", p.OriginalInput)
	}
	if p.Analysis.Category != "grammar" {
		t.Fatalf("category not normalized: %q", p.Analysis.Category)
	}
}

func TestImportCapture_NoAnalysisHasNoProvenance(t *testing.T) {
	repo := &fakeCaptureRepo{createRes: domain.LearningCaptureResult{Created: true}}
	svc := NewCaptureService(repo)

	in := validServiceInput()
	in.Analysis = nil
	if _, err := svc.ImportCapture(context.Background(), in); err != nil {
		t.Fatalf("import: %v", err)
	}
	if repo.created.Analysis != nil {
		t.Fatal("expected no analysis")
	}
	if repo.created.AnalyzerProvenance != "" {
		t.Fatalf("expected empty provenance without analysis, got %q", repo.created.AnalyzerProvenance)
	}
}

func TestImportCapture_ValidationErrorSkipsRepo(t *testing.T) {
	repo := &fakeCaptureRepo{}
	svc := NewCaptureService(repo)

	in := validServiceInput()
	in.SchemaVersion = "learning_capture_v2" // unsupported
	_, err := svc.ImportCapture(context.Background(), in)
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("expected ErrValidation, got %v", err)
	}
	if repo.created != nil {
		t.Fatal("repo should not be called on validation failure")
	}
}

func TestImportCapture_PassesThroughConflict(t *testing.T) {
	repo := &fakeCaptureRepo{createErr: domain.ErrConflict}
	svc := NewCaptureService(repo)

	_, err := svc.ImportCapture(context.Background(), validServiceInput())
	if !errors.Is(err, domain.ErrConflict) {
		t.Fatalf("expected ErrConflict passthrough, got %v", err)
	}
}

func TestImportCapture_PassesThroughReplay(t *testing.T) {
	repo := &fakeCaptureRepo{createRes: domain.LearningCaptureResult{CaptureID: "cap-svc-1", EntryID: 9, Created: false}}
	svc := NewCaptureService(repo)

	res, err := svc.ImportCapture(context.Background(), validServiceInput())
	if err != nil {
		t.Fatalf("import: %v", err)
	}
	if res.Created {
		t.Fatal("expected replay (Created=false)")
	}
}

func TestGetCapture_NormalizesID(t *testing.T) {
	repo := &fakeCaptureRepo{lookupRes: &domain.LearningCapture{CaptureID: "cap-svc-1"}}
	svc := NewCaptureService(repo)

	if _, err := svc.GetCapture(context.Background(), "  cap-svc-1  "); err != nil {
		t.Fatalf("lookup: %v", err)
	}
	if repo.lookupID != "cap-svc-1" {
		t.Fatalf("repo received un-normalized id: %q", repo.lookupID)
	}
}

func TestGetCapture_MalformedIDRejected(t *testing.T) {
	repo := &fakeCaptureRepo{}
	svc := NewCaptureService(repo)

	_, err := svc.GetCapture(context.Background(), "bad id!")
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("expected ErrValidation, got %v", err)
	}
	if repo.lookupID != "" {
		t.Fatal("repo should not be called for a malformed id")
	}
}

func TestGetCapture_NotFoundPassthrough(t *testing.T) {
	repo := &fakeCaptureRepo{lookupErr: domain.ErrNotFound}
	svc := NewCaptureService(repo)

	_, err := svc.GetCapture(context.Background(), "cap-missing")
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound passthrough, got %v", err)
	}
}
