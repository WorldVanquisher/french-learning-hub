package http

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"french-learning-app/internal/domain"
)

// KnowledgeService is the subset of knowledge-extraction and admission behavior
// the handlers depend on. The transport layer depends only on this narrow
// interface, not on the concrete application service.
type KnowledgeService interface {
	// Extract runs the configured extractor over an entry and persists a new
	// versioned extraction. It returns domain.ErrExtractorDisabled when no
	// extractor is configured and domain.ErrNotEligible when the entry is not in
	// an eligible state.
	Extract(ctx context.Context, entryID int64) (*domain.ExtractionView, error)
	// ListExtractions returns every extraction for an entry, newest first.
	ListExtractions(ctx context.Context, entryID int64) ([]*domain.ExtractionView, error)
	// GetExtraction returns one extraction with its units and admission state.
	GetExtraction(ctx context.Context, extractionID int64) (*domain.ExtractionView, error)
	// AddOverride records an append-only human admission override for a unit.
	AddOverride(ctx context.Context, unitID int64, in domain.NewAdmissionOverrideInput) (*domain.AdmissionOverride, error)
	// GetAdmission returns the resolved admission state for a unit.
	GetAdmission(ctx context.Context, unitID int64) (*domain.AdmissionState, error)
	// ListOverrides returns the full override history for a unit, oldest first.
	ListOverrides(ctx context.Context, unitID int64) ([]*domain.AdmissionOverride, error)
}

// ---- response DTOs ----

// admissionResponse is the resolved admission view for one unit: the immutable
// machine recommendation, the latest human override (null when none), and the
// derived effective state. It never carries internal data.
type admissionResponse struct {
	Ruleset        string                     `json:"ruleset"`
	MachineState   string                     `json:"machine_state"`
	MachineReason  string                     `json:"machine_reason"`
	Effective      string                     `json:"effective_state"`
	LatestOverride *admissionOverrideResponse `json:"latest_override"`
}

func toAdmissionResponse(a domain.AdmissionState) admissionResponse {
	resp := admissionResponse{
		Ruleset:       a.Recommendation.Ruleset,
		MachineState:  string(a.Recommendation.State),
		MachineReason: a.Recommendation.Reason,
		Effective:     string(a.Effective),
	}
	if a.LatestOverride != nil {
		o := toAdmissionOverrideResponse(a.LatestOverride)
		resp.LatestOverride = &o
	}
	return resp
}

type admissionOverrideResponse struct {
	ID        int64  `json:"id"`
	UnitID    int64  `json:"unit_id"`
	Decision  string `json:"decision"`
	Reason    string `json:"reason,omitempty"`
	Note      string `json:"note,omitempty"`
	CreatedAt string `json:"created_at"`
}

func toAdmissionOverrideResponse(o *domain.AdmissionOverride) admissionOverrideResponse {
	return admissionOverrideResponse{
		ID:        o.ID,
		UnitID:    o.UnitID,
		Decision:  string(o.Decision),
		Reason:    o.Reason,
		Note:      o.Note,
		CreatedAt: o.CreatedAt.Format(time.RFC3339Nano),
	}
}

// knowledgeUnitResponse is the wire shape of one knowledge unit plus its resolved
// admission state.
type knowledgeUnitResponse struct {
	ID         int64             `json:"id"`
	Ordinal    int               `json:"ordinal"`
	Kind       string            `json:"kind"`
	Canonical  string            `json:"canonical"`
	Statement  string            `json:"statement"`
	Example    *string           `json:"example"`
	Confidence float64           `json:"confidence"`
	CreatedAt  string            `json:"created_at"`
	Admission  admissionResponse `json:"admission"`
}

func toKnowledgeUnitResponse(v domain.KnowledgeUnitView) knowledgeUnitResponse {
	return knowledgeUnitResponse{
		ID:         v.Unit.ID,
		Ordinal:    v.Unit.Ordinal,
		Kind:       string(v.Unit.Kind),
		Canonical:  v.Unit.Canonical,
		Statement:  v.Unit.Statement,
		Example:    v.Unit.Example,
		Confidence: v.Unit.Confidence,
		CreatedAt:  v.Unit.CreatedAt.Format(time.RFC3339Nano),
		Admission:  toAdmissionResponse(v.Admission),
	}
}

// extractionResponse is the wire shape of one extraction with its units. The
// source_analysis_id / source_feedback_id fields record the exact effective
// interpretation the extraction was derived from (provenance); source_feedback_id
// is null when the source analysis was unreviewed.
type extractionResponse struct {
	ID               int64                   `json:"id"`
	EntryID          int64                   `json:"entry_id"`
	Version          int64                   `json:"version"`
	SourceAnalysisID int64                   `json:"source_analysis_id"`
	SourceFeedbackID *int64                  `json:"source_feedback_id"`
	Extractor        string                  `json:"extractor"`
	CreatedAt        string                  `json:"created_at"`
	Units            []knowledgeUnitResponse `json:"units"`
}

func toExtractionResponse(v *domain.ExtractionView) extractionResponse {
	units := make([]knowledgeUnitResponse, 0, len(v.Units))
	for _, u := range v.Units {
		units = append(units, toKnowledgeUnitResponse(u))
	}
	return extractionResponse{
		ID:               v.Extraction.ID,
		EntryID:          v.Extraction.EntryID,
		Version:          v.Extraction.Version,
		SourceAnalysisID: v.Extraction.SourceAnalysisID,
		SourceFeedbackID: v.Extraction.SourceFeedbackID,
		Extractor:        v.Extraction.Extractor,
		CreatedAt:        v.Extraction.CreatedAt.Format(time.RFC3339Nano),
		Units:            units,
	}
}

// createOverrideRequest is the admission-override request body.
type createOverrideRequest struct {
	Decision string `json:"decision"`
	Reason   string `json:"reason"`
	Note     string `json:"note"`
}

// ---- handlers ----

// handleCreateExtraction runs a new knowledge extraction for an entry and
// persists it. It is the only knowledge endpoint that invokes the extractor.
// Status mapping: 201 created, 400 invalid id, 404 entry not found, 409 not
// eligible (unanalyzed / rejected current analysis), 422 invalid extractor
// output, 503 extractor disabled, 504 provider timeout, 502 provider
// unavailable, 500 storage failure. No partial data is persisted on failure.
func (h *Handler) handleCreateExtraction(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}

	view, err := h.knowledge.Extract(r.Context(), id)
	if errors.Is(err, domain.ErrExtractorDisabled) {
		// The feature is switched off; report it as unavailable rather than
		// silently doing nothing or falling back to another provider.
		writeError(w, http.StatusServiceUnavailable, "knowledge extraction is not enabled")
		return
	}
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "entry not found")
		return
	}
	if errors.Is(err, domain.ErrNotEligible) {
		writeError(w, http.StatusConflict, err.Error())
		return
	}
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}
	// Provider failures map to gateway statuses. The message is generic: the
	// wrapped error never carries the API key, Authorization header, full
	// provider body, or original learning content.
	if errors.Is(err, domain.ErrProviderTimeout) {
		writeError(w, http.StatusGatewayTimeout, "extraction provider timed out")
		return
	}
	if errors.Is(err, domain.ErrProviderUnavailable) {
		writeError(w, http.StatusBadGateway, "extraction provider unavailable")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not extract knowledge")
		return
	}
	writeJSON(w, http.StatusCreated, toExtractionResponse(view))
}

// handleListExtractions lists every extraction for an entry, newest first. It is
// read-only and performs no AI call.
func (h *Handler) handleListExtractions(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}

	views, err := h.knowledge.ListExtractions(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "entry not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list extractions")
		return
	}

	resp := make([]extractionResponse, 0, len(views))
	for _, v := range views {
		resp = append(resp, toExtractionResponse(v))
	}
	writeJSON(w, http.StatusOK, map[string]any{"extractions": resp})
}

// handleGetExtraction returns one extraction with its units and admission state.
// It is read-only and performs no AI call.
func (h *Handler) handleGetExtraction(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}

	view, err := h.knowledge.GetExtraction(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "extraction not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not fetch extraction")
		return
	}
	writeJSON(w, http.StatusOK, toExtractionResponse(view))
}

// handleCreateOverride records an append-only human admission override for a
// knowledge unit. Status mapping: 201 created, 400 invalid id / invalid JSON, 404
// unit not found, 422 invalid override, 500 storage failure.
func (h *Handler) handleCreateOverride(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}

	var req createOverrideRequest
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}

	override, err := h.knowledge.AddOverride(r.Context(), id, domain.NewAdmissionOverrideInput{
		Decision: domain.HumanAdmissionDecision(req.Decision),
		Reason:   req.Reason,
		Note:     req.Note,
	})
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "knowledge unit not found")
		return
	}
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not create admission override")
		return
	}
	writeJSON(w, http.StatusCreated, toAdmissionOverrideResponse(override))
}

// handleGetAdmission returns the resolved admission state for a knowledge unit. It
// is read-only and performs no AI call.
func (h *Handler) handleGetAdmission(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}

	state, err := h.knowledge.GetAdmission(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "knowledge unit not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not fetch admission state")
		return
	}
	writeJSON(w, http.StatusOK, toAdmissionResponse(*state))
}

// handleListOverrides returns the append-only override history for a knowledge
// unit, oldest first. It is read-only and performs no AI call.
func (h *Handler) handleListOverrides(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}

	overrides, err := h.knowledge.ListOverrides(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "knowledge unit not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list admission overrides")
		return
	}

	resp := make([]admissionOverrideResponse, 0, len(overrides))
	for _, o := range overrides {
		resp = append(resp, toAdmissionOverrideResponse(o))
	}
	writeJSON(w, http.StatusOK, map[string]any{"overrides": resp})
}
