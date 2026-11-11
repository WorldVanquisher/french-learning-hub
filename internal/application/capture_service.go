package application

import (
	"context"
	"errors"
	"fmt"

	"french-learning-app/internal/domain"
)

// CaptureService implements the structured-capture import use case. It
// normalizes and validates a capture, derives server-side analyzer provenance,
// computes the deterministic content fingerprint, and delegates atomic
// persistence to the capture repository. It contains no SQL and no HTTP details.
type CaptureService struct {
	repo    domain.CaptureRepository
	sources domain.SourceResolver // nil: source_ref is refused
}

// CaptureOption configures a CaptureService.
type CaptureOption func(*CaptureService)

// WithSourceResolver enables the optional source_ref (Mistake Notebook v1):
// a reference is accepted only when the resolver finds that exact stored item.
func WithSourceResolver(r domain.SourceResolver) CaptureOption {
	return func(s *CaptureService) { s.sources = r }
}

// NewCaptureService wires the service to its repository.
func NewCaptureService(repo domain.CaptureRepository, opts ...CaptureOption) *CaptureService {
	s := &CaptureService{repo: repo}
	for _, o := range opts {
		o(s)
	}
	return s
}

// ImportCapture validates and normalizes the capture, then persists it. On a new
// capture it returns Created=true; on an exact idempotent replay Created=false;
// on a same-id/different-content submission it returns domain.ErrConflict.
// Validation failures are wrapped domain.ErrValidation and nothing is stored.
func (s *CaptureService) ImportCapture(ctx context.Context, in domain.NewLearningCaptureInput) (domain.LearningCaptureResult, error) {
	// Validate + normalize in place (schema version, capture id, source, entry
	// data via the reused entry validation, discussion summary, and — if present
	// — the analysis via the reused analysis validation).
	if err := in.Validate(); err != nil {
		return domain.LearningCaptureResult{}, err
	}

	// A structured source must name a stored item: checked before anything is
	// stored. Stored items are append-only, so the check cannot go stale.
	if in.SourceRef != nil {
		if s.sources == nil {
			return domain.LearningCaptureResult{}, fmt.Errorf("%w: source_ref is not supported by this server", domain.ErrValidation)
		}
		if _, err := s.sources.ResolveSource(ctx, *in.SourceRef); err != nil {
			if errors.Is(err, domain.ErrNotFound) {
				return domain.LearningCaptureResult{}, fmt.Errorf("%w: source_ref does not name a stored item", domain.ErrValidation)
			}
			return domain.LearningCaptureResult{}, err
		}
	}

	prepared := domain.PreparedLearningCapture{
		CaptureID:         in.CaptureID,
		Source:            in.Source,
		SchemaVersion:     in.SchemaVersion,
		OriginalInput:     in.OriginalInput,
		OriginalContext:   in.OriginalContext,
		DiscussionSummary: in.DiscussionSummary,
		SourceRef:         in.SourceRef,
	}
	if in.Analysis != nil {
		result := in.Analysis.AsAnalysisResult()
		prepared.Analysis = &result
		// Provenance is constructed on the server, in one place; the client never
		// supplies or overrides it.
		prepared.AnalyzerProvenance = domain.ImportedAnalysisProvenance(in.Source)
	}

	// Fingerprint over the normalized content, so JSON ordering/whitespace never
	// affects idempotency decisions. Computed once, here.
	prepared.ContentFingerprint = domain.CaptureFingerprint(prepared)

	return s.repo.Create(ctx, prepared)
}

// GetCapture returns the stored capture receipt for captureID. The captureID is
// validated (trimmed + portable charset) so lookups reject malformed ids the
// same way creation does. Returns domain.ErrNotFound if no capture exists and a
// wrapped domain.ErrValidation for a malformed id.
func (s *CaptureService) GetCapture(ctx context.Context, captureID string) (*domain.LearningCapture, error) {
	normalized, err := domain.NormalizeCaptureID(captureID)
	if err != nil {
		return nil, err
	}
	return s.repo.GetByCaptureID(ctx, normalized)
}
