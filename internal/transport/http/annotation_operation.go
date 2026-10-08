package http

import (
	"context"
	"errors"
	"french-learning-app/internal/domain"
	"net/http"
)

type annotationOperationService interface {
	GetAnnotationOperation(context.Context, string) (*domain.AnnotationOperation, error)
	CommitAnnotationOperation(context.Context, string, domain.AnnotationOperationInput) (*domain.AnnotationOperation, bool, error)
}

func operationResult(op *domain.AnnotationOperation) any {
	if op.Distinction != nil {
		return toUnitDistinctionResponse(*op.Distinction)
	}
	return toLinkResponse(*op.Link)
}
func annotationOperationError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, domain.ErrValidation):
		writeError(w, 400, "invalid annotation operation")
	case errors.Is(err, domain.ErrNotFound):
		writeError(w, 404, "annotation operation or target not found")
	case errors.Is(err, domain.ErrConceptConflict):
		writeError(w, 409, "annotation operation conflicts")
	default:
		writeError(w, 500, "could not process annotation operation")
	}
}
func (h *Handler) handleGetAnnotationOperation(w http.ResponseWriter, r *http.Request) {
	svc, ok := h.concept.(annotationOperationService)
	if !ok {
		writeError(w, 503, "annotation operations unavailable")
		return
	}
	op, err := svc.GetAnnotationOperation(r.Context(), r.PathValue("id"))
	if err != nil {
		annotationOperationError(w, err)
		return
	}
	writeJSON(w, 200, map[string]any{"schema_version": "annotation_operation_v1", "id": op.ID, "state": "committed", "request": op.Input, "status": 201, "result": operationResult(op)})
}

// Returns true when a keyed request has been handled (including invalid keys).
func (h *Handler) keyedAnnotation(w http.ResponseWriter, r *http.Request, in domain.AnnotationOperationInput) bool {
	keys := r.Header.Values("Idempotency-Key")
	if len(keys) == 0 {
		return false
	}
	if len(keys) != 1 {
		writeError(w, 400, "invalid idempotency key")
		return true
	}
	if _, err := domain.NormalizeAnnotationOperationID(keys[0]); err != nil {
		writeError(w, 400, "invalid idempotency key")
		return true
	}
	svc, ok := h.concept.(annotationOperationService)
	if !ok {
		writeError(w, 503, "annotation operations unavailable")
		return true
	}
	op, replay, err := svc.CommitAnnotationOperation(r.Context(), keys[0], in)
	if err != nil {
		annotationOperationError(w, err)
		return true
	}
	w.Header().Set("Idempotency-Key", op.ID)
	if replay {
		w.Header().Set("Idempotency-Replayed", "true")
	}
	writeJSON(w, 201, operationResult(op))
	return true
}
