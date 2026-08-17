// Package http adapts HTTP requests to the application use cases. It contains
// no business logic and no direct database access.
package http

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"time"

	"french-learning-app/internal/domain"
)

// EntryService is the subset of application behavior the handlers depend on.
type EntryService interface {
	CreateEntry(ctx context.Context, in domain.NewEntryInput) (*domain.Entry, error)
	GetEntry(ctx context.Context, id int64) (*domain.Entry, error)
	ListEntries(ctx context.Context, limit int) ([]*domain.Entry, error)
}

// AnalysisService is the subset of analysis behavior the handlers depend on.
type AnalysisService interface {
	AnalyzeEntry(ctx context.Context, entryID int64) (*domain.Analysis, error)
	ListAnalyses(ctx context.Context, entryID int64) ([]*domain.Analysis, error)
}

// FeedbackService is the subset of feedback behavior the handlers depend on.
type FeedbackService interface {
	AddFeedback(ctx context.Context, analysisID int64, in domain.NewFeedbackInput) (*domain.Feedback, error)
	ListFeedback(ctx context.Context, analysisID int64) ([]*domain.Feedback, error)
}

// EffectiveService is the subset of effective-analysis behavior the handlers
// depend on.
type EffectiveService interface {
	Resolve(ctx context.Context, analysisID int64) (domain.EffectiveAnalysis, error)
}

// InventoryService is the subset of learning-inventory behavior the handlers
// depend on. The transport layer depends only on this narrow interface, not on
// the concrete application service.
type InventoryService interface {
	// ListRecords returns the matching records and the applied (bounded) limit,
	// so the handler can decide whether a next-page cursor exists.
	ListRecords(ctx context.Context, q domain.LearningRecordQuery) ([]*domain.LearningRecord, int, error)
	// ExportRecords returns the matching records for a JSONL export (larger
	// bound than the list endpoint).
	ExportRecords(ctx context.Context, q domain.LearningRecordQuery) ([]*domain.LearningRecord, error)
	// Summary returns aggregate counts across all learning entries.
	Summary(ctx context.Context) (*domain.LearningInventorySummary, error)
}

// CaptureService is the subset of structured-capture behavior the handlers
// depend on. The transport layer depends only on this narrow interface.
type CaptureService interface {
	// ImportCapture validates and atomically persists a capture, returning the
	// result (Created distinguishes a new capture from an idempotent replay) or
	// domain.ErrConflict / domain.ErrValidation.
	ImportCapture(ctx context.Context, in domain.NewLearningCaptureInput) (domain.LearningCaptureResult, error)
	// GetCapture returns the stored capture receipt for captureID.
	GetCapture(ctx context.Context, captureID string) (*domain.LearningCapture, error)
}

// Handler holds dependencies for the HTTP layer.
type Handler struct {
	svc                 EntryService
	analysis            AnalysisService
	feedback            FeedbackService
	effective           EffectiveService
	inventory           InventoryService
	capture             CaptureService
	knowledge           KnowledgeService
	concept             ConceptService
	effectiveAnnotation EffectiveAnnotationInspectorService
	annotationDataset   AnnotationDatasetService
}

// NewHandler builds a Handler over the given services.
func NewHandler(svc EntryService, analysis AnalysisService, feedback FeedbackService, effective EffectiveService, inventory InventoryService, capture CaptureService, knowledge KnowledgeService, concept ConceptService, effectiveAnnotation EffectiveAnnotationInspectorService, annotationDataset AnnotationDatasetService) *Handler {
	return &Handler{svc: svc, analysis: analysis, feedback: feedback, effective: effective, inventory: inventory, capture: capture, knowledge: knowledge, concept: concept, effectiveAnnotation: effectiveAnnotation, annotationDataset: annotationDataset}
}

// Routes returns the configured HTTP mux for the API.
func (h *Handler) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", h.handleHealth)
	mux.HandleFunc("POST /entries", h.handleCreateEntry)
	mux.HandleFunc("GET /entries", h.handleListEntries)
	mux.HandleFunc("GET /entries/{id}", h.handleGetEntry)
	mux.HandleFunc("POST /entries/{id}/analysis", h.handleCreateAnalysis)
	mux.HandleFunc("GET /entries/{id}/analyses", h.handleListAnalyses)
	mux.HandleFunc("POST /analyses/{id}/feedback", h.handleCreateFeedback)
	mux.HandleFunc("GET /analyses/{id}/feedback", h.handleListFeedback)
	mux.HandleFunc("GET /analyses/{id}/effective", h.handleEffectiveAnalysis)
	mux.HandleFunc("GET /learning-records", h.handleListLearningRecords)
	mux.HandleFunc("GET /learning-records/summary", h.handleLearningRecordsSummary)
	mux.HandleFunc("GET /learning-records/export", h.handleExportLearningRecords)
	mux.HandleFunc("POST /captures", h.handleCreateCapture)
	mux.HandleFunc("GET /captures/{capture_id}", h.handleGetCapture)
	mux.HandleFunc("POST /entries/{id}/extractions", h.handleCreateExtraction)
	mux.HandleFunc("GET /entries/{id}/extractions", h.handleListExtractions)
	mux.HandleFunc("GET /extractions/{id}", h.handleGetExtraction)
	mux.HandleFunc("POST /knowledge-units/{id}/admission-overrides", h.handleCreateOverride)
	mux.HandleFunc("GET /knowledge-units/{id}/admission-overrides", h.handleListOverrides)
	mux.HandleFunc("GET /knowledge-units/{id}/admission", h.handleGetAdmission)
	// Knowledge concept resolution (milestone 10.5).
	mux.HandleFunc("GET /concepts", h.handleListConcepts)
	mux.HandleFunc("POST /concepts", h.handleCreateConcept)
	mux.HandleFunc("GET /concepts/{id}", h.handleGetConcept)
	mux.HandleFunc("POST /concepts/{id}/preferred-unit", h.handleSetPreferredUnit)
	mux.HandleFunc("GET /knowledge-units/{id}/concept-resolution", h.handleResolveUnit)
	mux.HandleFunc("POST /knowledge-units/{id}/concept-links/same", h.handleResolveSame)
	// Current SAME membership read model (milestone 10.5, UI-prep): the authoritative
	// "which concept this unit belongs to now", read from the membership projection —
	// never inferred from the append-only resolution events.
	mux.HandleFunc("GET /knowledge-units/{id}/concept-membership", h.handleGetCurrentMembership)
	// Explicit human correction of a wrong SAME membership (milestone 10.5.1): moves
	// the unit to a different concept even when it already has one, preserving the
	// prior decision as history.
	mux.HandleFunc("PUT /knowledge-units/{id}/concept-membership", h.handleReassignSame)
	// Explicit human INVALID judgment (milestone 10.6): clears the unit's current
	// SAME membership and records the rejection as immutable append-only negative
	// evidence, never merely deleting the projection.
	mux.HandleFunc("POST /knowledge-units/{id}/concept-membership/reject", h.handleRejectSame)
	// Unit-level INVALID judgment (milestone 10.6 correctness patch): an explicit,
	// append-only human judgment that a KnowledgeUnit is an invalid candidate for
	// concept resolution — recordable even for a freshly extracted unit that never
	// had a SAME membership (distinct from the membership-level reject above). It
	// atomically clears any current SAME membership so no contradictory authority
	// remains, is reversible via restore, and removes the unit from the review queue.
	mux.HandleFunc("POST /knowledge-units/{id}/invalid", h.handleMarkUnitInvalid)
	mux.HandleFunc("POST /knowledge-units/{id}/invalid/restore", h.handleRestoreUnit)
	mux.HandleFunc("GET /knowledge-units/{id}/invalid", h.handleGetUnitInvalid)
	// Explicit DISTINCT negative pair (milestone 10.6 correctness patch): the unit is
	// NOT the same learning identity as the given concept. Append-only evidence for
	// future ML training; it creates no membership and no relation and never changes
	// SAME membership, so the unit stays reviewable.
	mux.HandleFunc("POST /knowledge-units/{id}/concept-distinctions", h.handleRecordDistinction)
	mux.HandleFunc("GET /knowledge-units/{id}/concept-distinctions", h.handleListDistinctions)
	mux.HandleFunc("POST /knowledge-units/{id}/concept-links/relation", h.handleRecordRelation)
	mux.HandleFunc("GET /reviewable-units", h.handleListReviewableUnits)
	mux.HandleFunc("GET /entries/{id}/current-extraction", h.handleGetCurrentExtraction)
	mux.HandleFunc("PUT /entries/{id}/current-extraction", h.handleSetCurrentExtraction)
	// M11-B read-only effective annotation inspector. Both routes delegate to the
	// existing M11-A projection and create no annotation authority.
	mux.HandleFunc("GET /knowledge-units/{id}/effective-annotation", h.handleGetEffectiveAnnotation)
	mux.HandleFunc("GET /effective-annotations", h.handleListEffectiveAnnotations)
	// M11-C exposes one versioned, current-snapshot dataset through equivalent
	// JSON and JSONL read representations. Both consume M11-A authority.
	mux.HandleFunc("GET /annotation-dataset/v1", h.handleGetAnnotationDatasetV1)
	mux.HandleFunc("GET /annotation-dataset/v1/export", h.handleExportAnnotationDatasetV1)
	return mux
}

// ---- request / response DTOs ----

type createEntryRequest struct {
	OriginalInput   string `json:"original_input"`
	OriginalContext string `json:"original_context"`
}

type entryResponse struct {
	ID              int64    `json:"id"`
	OriginalInput   string   `json:"original_input"`
	OriginalContext string   `json:"original_context"`
	CreatedAt       string   `json:"created_at"`
	UpdatedAt       string   `json:"updated_at"`
	Category        *string  `json:"category,omitempty"`
	Explanation     *string  `json:"explanation,omitempty"`
	Confidence      *float64 `json:"confidence,omitempty"`
}

func toResponse(e *domain.Entry) entryResponse {
	return entryResponse{
		ID:              e.ID,
		OriginalInput:   e.OriginalInput,
		OriginalContext: e.OriginalContext,
		CreatedAt:       e.CreatedAt.Format(time.RFC3339Nano),
		UpdatedAt:       e.UpdatedAt.Format(time.RFC3339Nano),
		Category:        e.Category,
		Explanation:     e.Explanation,
		Confidence:      e.Confidence,
	}
}

type analysisResponse struct {
	ID          int64   `json:"id"`
	EntryID     int64   `json:"entry_id"`
	Version     int64   `json:"version"`
	Category    string  `json:"category"`
	Explanation string  `json:"explanation"`
	Confidence  float64 `json:"confidence"`
	Uncertainty string  `json:"uncertainty"`
	Analyzer    string  `json:"analyzer"`
	CreatedAt   string  `json:"created_at"`
}

func toAnalysisResponse(a *domain.Analysis) analysisResponse {
	return analysisResponse{
		ID:          a.ID,
		EntryID:     a.EntryID,
		Version:     a.Version,
		Category:    a.Category,
		Explanation: a.Explanation,
		Confidence:  a.Confidence,
		Uncertainty: a.Uncertainty,
		Analyzer:    a.Analyzer,
		CreatedAt:   a.CreatedAt.Format(time.RFC3339Nano),
	}
}

type createFeedbackRequest struct {
	Status               string  `json:"status"`
	CorrectedCategory    *string `json:"corrected_category"`
	CorrectedExplanation *string `json:"corrected_explanation"`
	UserNote             string  `json:"user_note"`
}

type feedbackResponse struct {
	ID                   int64   `json:"id"`
	AnalysisID           int64   `json:"analysis_id"`
	Status               string  `json:"status"`
	CorrectedCategory    *string `json:"corrected_category,omitempty"`
	CorrectedExplanation *string `json:"corrected_explanation,omitempty"`
	UserNote             string  `json:"user_note"`
	CreatedAt            string  `json:"created_at"`
}

func toFeedbackResponse(f *domain.Feedback) feedbackResponse {
	return feedbackResponse{
		ID:                   f.ID,
		AnalysisID:           f.AnalysisID,
		Status:               string(f.Status),
		CorrectedCategory:    f.CorrectedCategory,
		CorrectedExplanation: f.CorrectedExplanation,
		UserNote:             f.UserNote,
		CreatedAt:            f.CreatedAt.Format(time.RFC3339Nano),
	}
}

// analysisValues is the category/explanation pair shared by the original and
// effective views in the effective-analysis response.
type analysisValues struct {
	Category    string `json:"category"`
	Explanation string `json:"explanation"`
}

type effectiveAnalysisResponse struct {
	AnalysisID int64          `json:"analysis_id"`
	EntryID    int64          `json:"entry_id"`
	Version    int64          `json:"version"`
	Original   analysisValues `json:"original"`
	// Effective is null for a rejected analysis (no current interpretation).
	Effective  *analysisValues `json:"effective"`
	Resolution string          `json:"resolution"`
	// FeedbackID is null for an unreviewed analysis.
	FeedbackID *int64 `json:"feedback_id"`
}

func toEffectiveResponse(e domain.EffectiveAnalysis) effectiveAnalysisResponse {
	resp := effectiveAnalysisResponse{
		AnalysisID: e.AnalysisID,
		EntryID:    e.EntryID,
		Version:    e.Version,
		Original:   analysisValues{Category: e.Original.Category, Explanation: e.Original.Explanation},
		Resolution: string(e.Resolution),
		FeedbackID: e.FeedbackID,
	}
	if e.Effective != nil {
		resp.Effective = &analysisValues{Category: e.Effective.Category, Explanation: e.Effective.Explanation}
	}
	return resp
}

// learningRecordResponse is the wire shape of one inventory record. It is a
// read-only projection combining an entry, its latest analysis, and that
// analysis's latest feedback. Analysis-related fields and effective/original are
// null for an unanalyzed entry; effective is null for a rejected record. It
// never carries API keys, environment values, or other internal data.
type learningRecordResponse struct {
	EntryID         int64  `json:"entry_id"`
	OriginalInput   string `json:"original_input"`
	OriginalContext string `json:"original_context"`
	EntryCreatedAt  string `json:"entry_created_at"`
	State           string `json:"state"`

	AnalysisID        *int64   `json:"analysis_id"`
	AnalysisVersion   *int64   `json:"analysis_version"`
	Analyzer          *string  `json:"analyzer"`
	Confidence        *float64 `json:"confidence"`
	Uncertainty       *string  `json:"uncertainty"`
	AnalysisCreatedAt *string  `json:"analysis_created_at"`

	Original   *analysisValues `json:"original"`
	Effective  *analysisValues `json:"effective"`
	FeedbackID *int64          `json:"feedback_id"`
}

func toLearningRecordResponse(r *domain.LearningRecord) learningRecordResponse {
	resp := learningRecordResponse{
		EntryID:         r.EntryID,
		OriginalInput:   r.OriginalInput,
		OriginalContext: r.OriginalContext,
		EntryCreatedAt:  r.EntryCreatedAt.Format(time.RFC3339Nano),
		State:           string(r.State),
		AnalysisID:      r.AnalysisID,
		AnalysisVersion: r.AnalysisVersion,
		Analyzer:        r.Analyzer,
		Confidence:      r.Confidence,
		Uncertainty:     r.Uncertainty,
		FeedbackID:      r.FeedbackID,
	}
	if r.AnalysisCreatedAt != nil {
		s := r.AnalysisCreatedAt.Format(time.RFC3339Nano)
		resp.AnalysisCreatedAt = &s
	}
	if r.Original != nil {
		resp.Original = &analysisValues{Category: r.Original.Category, Explanation: r.Original.Explanation}
	}
	if r.Effective != nil {
		resp.Effective = &analysisValues{Category: r.Effective.Category, Explanation: r.Effective.Explanation}
	}
	return resp
}

// learningInventorySummaryResponse is the wire shape of the aggregate summary.
// State counts sum to total_entries; analyzed_entries + unanalyzed_entries ==
// total_entries. by_effective_category excludes rejected and unanalyzed records
// (they have no effective category); by_analyzer counts the latest analysis per
// analyzed entry.
type learningInventorySummaryResponse struct {
	TotalEntries        int64            `json:"total_entries"`
	AnalyzedEntries     int64            `json:"analyzed_entries"`
	UnanalyzedEntries   int64            `json:"unanalyzed_entries"`
	ByState             map[string]int64 `json:"by_state"`
	ByEffectiveCategory map[string]int64 `json:"by_effective_category"`
	ByAnalyzer          map[string]int64 `json:"by_analyzer"`
}

func toSummaryResponse(s *domain.LearningInventorySummary) learningInventorySummaryResponse {
	byState := make(map[string]int64, len(s.ByState))
	for k, v := range s.ByState {
		byState[string(k)] = v
	}
	byCategory := make(map[string]int64, len(s.ByEffectiveCategory))
	for k, v := range s.ByEffectiveCategory {
		byCategory[string(k)] = v
	}
	byAnalyzer := make(map[string]int64, len(s.ByAnalyzer))
	for k, v := range s.ByAnalyzer {
		byAnalyzer[k] = v
	}
	return learningInventorySummaryResponse{
		TotalEntries:        s.TotalEntries,
		AnalyzedEntries:     s.AnalyzedEntries,
		UnanalyzedEntries:   s.UnanalyzedEntries,
		ByState:             byState,
		ByEffectiveCategory: byCategory,
		ByAnalyzer:          byAnalyzer,
	}
}

// captureAnalysisRequest is the optional analysis object inside a capture. It is
// a typed struct, so strict decoding rejects unknown nested fields too.
type captureAnalysisRequest struct {
	Category    string  `json:"category"`
	Explanation string  `json:"explanation"`
	Confidence  float64 `json:"confidence"`
	Uncertainty string  `json:"uncertainty"`
}

// createCaptureRequest is the learning_capture_v1 request body. Clients supply
// only the fields below; database ids, analysis version, timestamps, analyzer
// provenance, feedback status, and effective resolution are never accepted.
type createCaptureRequest struct {
	SchemaVersion     string                  `json:"schema_version"`
	CaptureID         string                  `json:"capture_id"`
	Source            string                  `json:"source"`
	OriginalInput     string                  `json:"original_input"`
	OriginalContext   string                  `json:"original_context"`
	Analysis          *captureAnalysisRequest `json:"analysis"`
	DiscussionSummary string                  `json:"discussion_summary"`
}

// captureResultResponse is the POST /captures response. analysis_id is an
// explicit JSON null when the capture carried no analysis.
type captureResultResponse struct {
	CaptureID  string `json:"capture_id"`
	EntryID    int64  `json:"entry_id"`
	AnalysisID *int64 `json:"analysis_id"`
	Created    bool   `json:"created"`
}

func toCaptureResultResponse(r domain.LearningCaptureResult) captureResultResponse {
	return captureResultResponse{
		CaptureID:  r.CaptureID,
		EntryID:    r.EntryID,
		AnalysisID: r.AnalysisID,
		Created:    r.Created,
	}
}

// captureLookupResponse is the GET /captures/{capture_id} response. It returns
// metadata and references only; it never returns the content fingerprint and
// never duplicates the full entry or analysis content (available via the
// existing entry/analysis/inventory endpoints).
type captureLookupResponse struct {
	CaptureID         string `json:"capture_id"`
	SchemaVersion     string `json:"schema_version"`
	Source            string `json:"source"`
	EntryID           int64  `json:"entry_id"`
	AnalysisID        *int64 `json:"analysis_id"`
	DiscussionSummary string `json:"discussion_summary"`
	CreatedAt         string `json:"created_at"`
}

func toCaptureLookupResponse(c *domain.LearningCapture) captureLookupResponse {
	return captureLookupResponse{
		CaptureID:         c.CaptureID,
		SchemaVersion:     c.SchemaVersion,
		Source:            string(c.Source),
		EntryID:           c.EntryID,
		AnalysisID:        c.AnalysisID,
		DiscussionSummary: c.DiscussionSummary,
		CreatedAt:         c.CreatedAt.Format(time.RFC3339Nano),
	}
}

// ---- handlers ----

func (h *Handler) handleHealth(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (h *Handler) handleCreateEntry(w http.ResponseWriter, r *http.Request) {
	var req createEntryRequest
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}

	entry, err := h.svc.CreateEntry(r.Context(), domain.NewEntryInput{
		OriginalInput:   req.OriginalInput,
		OriginalContext: req.OriginalContext,
	})
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not create entry")
		return
	}
	writeJSON(w, http.StatusCreated, toResponse(entry))
}

func (h *Handler) handleGetEntry(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}

	entry, err := h.svc.GetEntry(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "entry not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not fetch entry")
		return
	}
	writeJSON(w, http.StatusOK, toResponse(entry))
}

func (h *Handler) handleListEntries(w http.ResponseWriter, r *http.Request) {
	limit := 0
	if v := r.URL.Query().Get("limit"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			limit = n
		}
	}

	entries, err := h.svc.ListEntries(r.Context(), limit)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list entries")
		return
	}

	resp := make([]entryResponse, 0, len(entries))
	for _, e := range entries {
		resp = append(resp, toResponse(e))
	}
	writeJSON(w, http.StatusOK, map[string]any{"entries": resp})
}

func (h *Handler) handleCreateAnalysis(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}

	analysis, err := h.analysis.AnalyzeEntry(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "entry not found")
		return
	}
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}
	// Provider failures map to gateway statuses. The message is generic on
	// purpose: the underlying error may reference the provider, but never the
	// API key, Authorization header, full provider response, or original
	// learning content. Detail stays in the wrapped error for server logs.
	if errors.Is(err, domain.ErrProviderTimeout) {
		writeError(w, http.StatusGatewayTimeout, "analysis provider timed out")
		return
	}
	if errors.Is(err, domain.ErrProviderUnavailable) {
		writeError(w, http.StatusBadGateway, "analysis provider unavailable")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not analyze entry")
		return
	}
	writeJSON(w, http.StatusCreated, toAnalysisResponse(analysis))
}

func (h *Handler) handleListAnalyses(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}

	analyses, err := h.analysis.ListAnalyses(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "entry not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list analyses")
		return
	}

	resp := make([]analysisResponse, 0, len(analyses))
	for _, a := range analyses {
		resp = append(resp, toAnalysisResponse(a))
	}
	writeJSON(w, http.StatusOK, map[string]any{"analyses": resp})
}

func (h *Handler) handleCreateFeedback(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}

	var req createFeedbackRequest
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}

	feedback, err := h.feedback.AddFeedback(r.Context(), id, domain.NewFeedbackInput{
		Status:               domain.FeedbackStatus(req.Status),
		CorrectedCategory:    req.CorrectedCategory,
		CorrectedExplanation: req.CorrectedExplanation,
		UserNote:             req.UserNote,
	})
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "analysis not found")
		return
	}
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not create feedback")
		return
	}
	writeJSON(w, http.StatusCreated, toFeedbackResponse(feedback))
}

func (h *Handler) handleListFeedback(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}

	feedback, err := h.feedback.ListFeedback(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "analysis not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list feedback")
		return
	}

	resp := make([]feedbackResponse, 0, len(feedback))
	for _, f := range feedback {
		resp = append(resp, toFeedbackResponse(f))
	}
	writeJSON(w, http.StatusOK, map[string]any{"feedback": resp})
}

// handleEffectiveAnalysis resolves and returns the current effective
// interpretation of one analysis. It is read-only and never writes.
func (h *Handler) handleEffectiveAnalysis(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}

	eff, err := h.effective.Resolve(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "analysis not found")
		return
	}
	if err != nil {
		// Do not expose internal database errors.
		writeError(w, http.StatusInternalServerError, "could not resolve effective analysis")
		return
	}
	writeJSON(w, http.StatusOK, toEffectiveResponse(eff))
}

// handleCreateCapture accepts one structured learning_capture_v1 capture,
// validates it, and atomically persists it. It performs no AI call. Status
// mapping: 201 new capture, 200 exact idempotent replay, 400 invalid JSON, 422
// unsupported schema / invalid content, 409 same id with changed content, 500
// unexpected storage failure.
func (h *Handler) handleCreateCapture(w http.ResponseWriter, r *http.Request) {
	var req createCaptureRequest
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	// Reject trailing JSON after the first complete object (e.g. two objects, or
	// junk after the body). io.EOF is the only acceptable next token.
	if dec.More() {
		writeError(w, http.StatusBadRequest, "unexpected trailing JSON content")
		return
	}

	in := domain.NewLearningCaptureInput{
		SchemaVersion:     req.SchemaVersion,
		CaptureID:         req.CaptureID,
		Source:            domain.CaptureSource(req.Source),
		OriginalInput:     req.OriginalInput,
		OriginalContext:   req.OriginalContext,
		DiscussionSummary: req.DiscussionSummary,
	}
	if req.Analysis != nil {
		in.Analysis = &domain.ImportedAnalysisInput{
			Category:    req.Analysis.Category,
			Explanation: req.Analysis.Explanation,
			Confidence:  req.Analysis.Confidence,
			Uncertainty: req.Analysis.Uncertainty,
		}
	}

	result, err := h.capture.ImportCapture(r.Context(), in)
	if errors.Is(err, domain.ErrValidation) {
		// Unsupported schema version and invalid content both surface as 422.
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}
	if errors.Is(err, domain.ErrConflict) {
		writeError(w, http.StatusConflict, "capture_id already exists with different content")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not import capture")
		return
	}

	status := http.StatusCreated
	if !result.Created {
		status = http.StatusOK
	}
	writeJSON(w, status, toCaptureResultResponse(result))
}

// handleGetCapture returns a capture receipt by its capture_id. The id is
// URL-decoded by the router (net/http PathValue) and validated. A malformed id
// returns 400; a missing capture returns 404. The content fingerprint is never
// returned.
func (h *Handler) handleGetCapture(w http.ResponseWriter, r *http.Request) {
	captureID := r.PathValue("capture_id")

	c, err := h.capture.GetCapture(r.Context(), captureID)
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusBadRequest, "invalid capture_id")
		return
	}
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "capture not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not fetch capture")
		return
	}
	writeJSON(w, http.StatusOK, toCaptureLookupResponse(c))
}

// parseLearningRecordQuery reads the shared inventory filters from the query
// string into a domain.LearningRecordQuery. It only parses; validation and
// normalization (including the limit bounds) happen in the application service.
// A malformed limit or before_entry_id is reported as a wrapped
// domain.ErrValidation so the handler maps it to 400. Empty filter params are
// treated as "no filter".
func parseLearningRecordQuery(r *http.Request) (domain.LearningRecordQuery, error) {
	q := r.URL.Query()
	var out domain.LearningRecordQuery

	if v := q.Get("state"); v != "" {
		state := domain.LearningRecordState(v)
		out.State = &state
	}
	if v := q.Get("category"); v != "" {
		cat := domain.Category(v)
		out.Category = &cat
	}
	if v := q.Get("analyzer"); v != "" {
		out.Analyzer = &v
	}
	if v := q.Get("limit"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil {
			return domain.LearningRecordQuery{}, domain.NewValidationError("limit must be an integer")
		}
		out.Limit = n
	}
	if v := q.Get("before_entry_id"); v != "" {
		n, err := strconv.ParseInt(v, 10, 64)
		if err != nil {
			return domain.LearningRecordQuery{}, domain.NewValidationError("before_entry_id must be an integer")
		}
		out.BeforeEntryID = &n
	}
	return out, nil
}

// handleListLearningRecords lists inventory records (one per entry) with
// optional filters and descending cursor pagination. It is read-only and
// performs no AI call. The response carries the page and a next_before_entry_id
// cursor (null when there is no further page).
func (h *Handler) handleListLearningRecords(w http.ResponseWriter, r *http.Request) {
	q, err := parseLearningRecordQuery(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	records, limit, err := h.inventory.ListRecords(r.Context(), q)
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list learning records")
		return
	}

	resp := make([]learningRecordResponse, 0, len(records))
	for _, rec := range records {
		resp = append(resp, toLearningRecordResponse(rec))
	}

	// A full page implies there may be more; the cursor is the last (smallest,
	// since order is descending) entry id. A short page means we reached the end.
	var nextCursor *int64
	if len(records) == limit && limit > 0 {
		last := records[len(records)-1].EntryID
		nextCursor = &last
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"records":              resp,
		"next_before_entry_id": nextCursor,
	})
}

// handleLearningRecordsSummary returns aggregate counts across all entries. It
// is read-only and performs no AI call.
func (h *Handler) handleLearningRecordsSummary(w http.ResponseWriter, r *http.Request) {
	summary, err := h.inventory.Summary(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not summarize learning records")
		return
	}
	writeJSON(w, http.StatusOK, toSummaryResponse(summary))
}

// handleExportLearningRecords streams the inventory as JSONL (newline-delimited
// JSON): one record object per line, no enclosing array. It is read-only and
// performs no AI call. Records are written one at a time so the whole export is
// not buffered in memory; on a write/encode failure it stops (a partial stream
// with a broken connection, not a silent truncation dressed up as success).
func (h *Handler) handleExportLearningRecords(w http.ResponseWriter, r *http.Request) {
	q, err := parseLearningRecordQuery(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	records, err := h.inventory.ExportRecords(r.Context(), q)
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not export learning records")
		return
	}

	// Headers are committed before the body; any error mid-stream can no longer
	// change the status code, so validation/retrieval must finish above first.
	w.Header().Set("Content-Type", "application/x-ndjson; charset=utf-8")
	w.WriteHeader(http.StatusOK)

	enc := json.NewEncoder(w)
	for _, rec := range records {
		// Encode writes the object followed by a newline, giving one JSON object
		// per line with no outer array.
		if err := enc.Encode(toLearningRecordResponse(rec)); err != nil {
			// The connection is broken; stop rather than spin writing to a dead
			// stream. Nothing further can be signaled to the client.
			return
		}
	}
}

// ---- helpers ----

// parseID reads and validates the {id} path value, writing a 400 response and
// returning ok=false when it is missing or malformed.
func parseID(w http.ResponseWriter, r *http.Request) (int64, bool) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil || id <= 0 {
		writeError(w, http.StatusBadRequest, "invalid id")
		return 0, false
	}
	return id, true
}

// parseInt64 parses a base-10 int64 from a query-string value. The caller decides
// how to treat a parse error or a non-positive result.
func parseInt64(s string) (int64, error) {
	return strconv.ParseInt(s, 10, 64)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
