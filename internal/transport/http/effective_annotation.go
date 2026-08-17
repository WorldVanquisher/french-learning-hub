package http

import (
	"context"
	"errors"
	"net/http"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// EffectiveAnnotationInspectorService is the narrow read-only application
// behavior required by the inspector endpoints.
type EffectiveAnnotationInspectorService interface {
	GetEffectiveAnnotation(ctx context.Context, unitID int64) (*application.EffectiveAnnotationItem, error)
	ListEffectiveAnnotations(ctx context.Context) ([]application.EffectiveAnnotationItem, error)
}

type effectiveAnnotationUnitResponse struct {
	ID           int64   `json:"id"`
	ExtractionID int64   `json:"extraction_id"`
	Ordinal      int     `json:"ordinal"`
	Kind         string  `json:"kind"`
	Canonical    string  `json:"canonical"`
	Statement    string  `json:"statement"`
	Example      *string `json:"example"`
	Confidence   float64 `json:"confidence"`
	CreatedAt    string  `json:"created_at"`
}

func toEffectiveAnnotationUnitResponse(unit domain.KnowledgeUnit) effectiveAnnotationUnitResponse {
	return effectiveAnnotationUnitResponse{
		ID:           unit.ID,
		ExtractionID: unit.ExtractionID,
		Ordinal:      unit.Ordinal,
		Kind:         string(unit.Kind),
		Canonical:    unit.Canonical,
		Statement:    unit.Statement,
		Example:      unit.Example,
		Confidence:   unit.Confidence,
		CreatedAt:    unit.CreatedAt.Format(time.RFC3339Nano),
	}
}

type effectiveSameResponse struct {
	Membership currentMembershipResponse `json:"membership"`
	Decision   unitConceptLinkResponse   `json:"decision"`
}

type effectiveAnnotationSnapshotResponse struct {
	UnitID             int64                     `json:"unit_id"`
	Status             string                    `json:"status"`
	LatestUnitJudgment *unitJudgmentResponse     `json:"latest_unit_judgment"`
	CurrentSame        *effectiveSameResponse    `json:"current_same"`
	Distinctions       []unitDistinctionResponse `json:"distinctions"`
	Relations          []unitConceptLinkResponse `json:"relations"`
}

func toEffectiveAnnotationSnapshotResponse(snapshot domain.EffectiveAnnotationSnapshot) effectiveAnnotationSnapshotResponse {
	resp := effectiveAnnotationSnapshotResponse{
		UnitID:       snapshot.UnitID,
		Status:       string(snapshot.Status),
		Distinctions: make([]unitDistinctionResponse, 0, len(snapshot.Distinctions)),
		Relations:    make([]unitConceptLinkResponse, 0, len(snapshot.Relations)),
	}
	if snapshot.LatestUnitJudgment != nil {
		judgment := toUnitJudgmentResponse(*snapshot.LatestUnitJudgment)
		resp.LatestUnitJudgment = &judgment
	}
	if snapshot.CurrentSame != nil {
		membership := toCurrentMembershipResponse(&snapshot.CurrentSame.Membership)
		resp.CurrentSame = &effectiveSameResponse{
			Membership: *membership,
			Decision:   toLinkResponse(snapshot.CurrentSame.Decision),
		}
	}
	for _, distinction := range snapshot.Distinctions {
		resp.Distinctions = append(resp.Distinctions, toUnitDistinctionResponse(distinction))
	}
	for _, relation := range snapshot.Relations {
		resp.Relations = append(resp.Relations, toLinkResponse(relation))
	}
	return resp
}

type effectiveAnnotationItemResponse struct {
	Unit     effectiveAnnotationUnitResponse     `json:"unit"`
	Snapshot effectiveAnnotationSnapshotResponse `json:"snapshot"`
}

func toEffectiveAnnotationItemResponse(item application.EffectiveAnnotationItem) effectiveAnnotationItemResponse {
	return effectiveAnnotationItemResponse{
		Unit:     toEffectiveAnnotationUnitResponse(item.Unit),
		Snapshot: toEffectiveAnnotationSnapshotResponse(item.Snapshot),
	}
}

// handleGetEffectiveAnnotation returns one unit plus its M11-A effective
// annotation snapshot. It is read-only and never creates annotation authority.
func (h *Handler) handleGetEffectiveAnnotation(w http.ResponseWriter, r *http.Request) {
	unitID, ok := parseID(w, r)
	if !ok {
		return
	}
	item, err := h.effectiveAnnotation.GetEffectiveAnnotation(r.Context(), unitID)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "knowledge unit not found")
		return
	}
	if errors.Is(err, domain.ErrEffectiveAnnotationCorrupt) {
		writeError(w, http.StatusInternalServerError, "effective annotation is internally inconsistent")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not build effective annotation")
		return
	}
	writeJSON(w, http.StatusOK, toEffectiveAnnotationItemResponse(*item))
}

// handleListEffectiveAnnotations returns all current-extraction units with their
// M11-A snapshots. Client-side filters do not alter this backend read model.
func (h *Handler) handleListEffectiveAnnotations(w http.ResponseWriter, r *http.Request) {
	items, err := h.effectiveAnnotation.ListEffectiveAnnotations(r.Context())
	if errors.Is(err, domain.ErrEffectiveAnnotationCorrupt) {
		writeError(w, http.StatusInternalServerError, "effective annotation is internally inconsistent")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list effective annotations")
		return
	}
	resp := make([]effectiveAnnotationItemResponse, 0, len(items))
	for _, item := range items {
		resp = append(resp, toEffectiveAnnotationItemResponse(item))
	}
	writeJSON(w, http.StatusOK, map[string]any{"effective_annotations": resp})
}
