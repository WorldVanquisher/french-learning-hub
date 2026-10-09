package http

import (
	"context"
	"errors"
	"net/http"
	"strconv"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// KnowledgeLibraryService is the read-only FLH-034 Knowledge Library. Every route
// is GET and delegates to existing authority; nothing is recorded and no provider
// is called.
type KnowledgeLibraryService interface {
	Search(ctx context.Context, q application.LibrarySearchQuery) (*application.LibrarySearchReport, error)
	GetConcept(ctx context.Context, conceptID int64) (*application.LibraryConceptDetail, error)
	GetUnitSource(ctx context.Context, unitID int64) (*application.LibrarySource, error)
}

// WithKnowledgeLibrary wires the read-only Knowledge Library routes.
func WithKnowledgeLibrary(service KnowledgeLibraryService) HandlerOption {
	return func(handler *Handler) { handler.library = service }
}

// ---- DTOs ----

type libraryUnitResponse struct {
	UnitID              int64   `json:"unit_id"`
	Kind                string  `json:"kind"`
	Canonical           string  `json:"canonical"`
	Statement           string  `json:"statement"`
	Example             *string `json:"example"`
	EntryID             int64   `json:"entry_id"`
	ExtractionID        int64   `json:"extraction_id"`
	ExtractionVersion   int64   `json:"extraction_version"`
	InCurrentExtraction bool    `json:"in_current_extraction"`
	Admission           string  `json:"admission"`
}

func toLibraryUnit(u application.LibraryUnit) libraryUnitResponse {
	return libraryUnitResponse{
		UnitID: u.Unit.ID, Kind: string(u.Unit.Kind), Canonical: u.Unit.Canonical, Statement: u.Unit.Statement,
		Example: u.Unit.Example, EntryID: u.EntryID, ExtractionID: u.Unit.ExtractionID,
		ExtractionVersion: u.ExtractionVersion, InCurrentExtraction: u.InCurrentExtraction, Admission: string(u.Admission),
	}
}

func toLibraryUnits(units []application.LibraryUnit) []libraryUnitResponse {
	out := make([]libraryUnitResponse, 0, len(units))
	for _, u := range units {
		out = append(out, toLibraryUnit(u))
	}
	return out
}

type librarySearchResultResponse struct {
	Concept             conceptResponse `json:"concept"`
	MatchTier           string          `json:"match_tier"`
	MatchedFields       []string        `json:"matched_fields"`
	CurrentMemberCount  int             `json:"current_member_count"`
	SupportingUnitCount int             `json:"supporting_unit_count"`
}

type librarySearchResponse struct {
	SchemaVersion string                        `json:"schema_version"`
	Query         string                        `json:"query"`
	Tokens        []string                      `json:"tokens"`
	State         string                        `json:"state"`
	Limit         int                           `json:"limit"`
	TotalMatches  int                           `json:"total_matches"`
	Truncated     bool                          `json:"truncated"`
	Results       []librarySearchResultResponse `json:"results"`
}

type libraryRelationResponse struct {
	Relation       string              `json:"relation"`
	LinkID         int64               `json:"link_id"`
	DecisionSource string              `json:"decision_source"`
	DecidedAt      string              `json:"decided_at"`
	Unit           libraryUnitResponse `json:"unit"`
}

type libraryHistoricalUnitResponse struct {
	Unit             libraryUnitResponse     `json:"unit"`
	LatestEvent      unitConceptLinkResponse `json:"latest_event"`
	EffectiveStatus  string                  `json:"effective_status"`
	CurrentConceptID *int64                  `json:"current_concept_id"`
}

type libraryConceptResponse struct {
	SchemaVersion        string                          `json:"schema_version"`
	Concept              conceptResponse                 `json:"concept"`
	PreferredUnit        *libraryUnitResponse            `json:"preferred_unit"`
	SupportingUnits      []libraryUnitResponse           `json:"supporting_units"`
	NonSupportingMembers []libraryUnitResponse           `json:"non_supporting_members"`
	CurrentRelations     []libraryRelationResponse       `json:"current_relations"`
	HistoricalUnits      []libraryHistoricalUnitResponse `json:"historical_units"`
	HistoryEventCount    int                             `json:"history_event_count"`
}

type libraryExtractionResponse struct {
	ID               int64  `json:"id"`
	Version          int64  `json:"version"`
	Extractor        string `json:"extractor"`
	SourceAnalysisID int64  `json:"source_analysis_id"`
	SourceFeedbackID *int64 `json:"source_feedback_id"`
	CreatedAt        string `json:"created_at"`
}

type librarySelectionResponse struct {
	ExtractionID  *int64 `json:"extraction_id"`
	SelectionMode string `json:"selection_mode"`
}

type libraryInterpretationResponse struct {
	Analysis  analysisResponse          `json:"analysis"`
	Feedback  *feedbackResponse         `json:"feedback"`
	Effective effectiveAnalysisResponse `json:"effective"`
}

type libraryAnalysisRefResponse struct {
	ID        int64  `json:"id"`
	Version   int64  `json:"version"`
	CreatedAt string `json:"created_at"`
}

type libraryAnnotationResponse struct {
	Status           string `json:"status"`
	CurrentConceptID *int64 `json:"current_concept_id"`
}

type librarySourceResponse struct {
	SchemaVersion        string                        `json:"schema_version"`
	Unit                 libraryUnitResponse           `json:"unit"`
	Entry                entryResponse                 `json:"entry"`
	Extraction           libraryExtractionResponse     `json:"extraction"`
	CurrentExtraction    librarySelectionResponse      `json:"current_extraction"`
	SourceInterpretation libraryInterpretationResponse `json:"source_interpretation"`
	LatestAnalysis       *libraryAnalysisRefResponse   `json:"latest_analysis"`
	Annotation           libraryAnnotationResponse     `json:"annotation"`
}

// ---- handlers ----

// handleSearchLibrary searches or browses Concepts: 200, 400 invalid query, 500.
func (h *Handler) handleSearchLibrary(w http.ResponseWriter, r *http.Request) {
	if h.library == nil {
		writeError(w, http.StatusInternalServerError, "knowledge library is not configured")
		return
	}
	values := r.URL.Query()
	var limit *int
	if raw := values.Get("limit"); raw != "" {
		n, err := strconv.Atoi(raw)
		if err != nil {
			writeError(w, http.StatusBadRequest, "limit must be an integer")
			return
		}
		limit = &n
	}
	state := values.Get("state")
	q, err := application.ParseLibrarySearchQuery(values.Get("q"), state, limit)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	report, err := h.library.Search(r.Context(), q)
	if errors.Is(err, application.ErrKnowledgeLibraryQuery) {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not search the knowledge library")
		return
	}
	if state == "" {
		state = "all"
	}
	resp := librarySearchResponse{
		SchemaVersion: application.KnowledgeLibrarySearchSchemaVersion, Query: report.Query, Tokens: report.Tokens,
		State: state, Limit: report.Limit, TotalMatches: report.TotalMatches, Truncated: report.Truncated,
		Results: make([]librarySearchResultResponse, 0, len(report.Results)),
	}
	for _, res := range report.Results {
		resp.Results = append(resp.Results, librarySearchResultResponse{
			Concept: toConceptResponse(res.Concept), MatchTier: res.MatchTier, MatchedFields: res.MatchedFields,
			CurrentMemberCount: res.CurrentMemberCount, SupportingUnitCount: res.SupportingUnitCount,
		})
	}
	writeJSON(w, http.StatusOK, resp)
}

// handleGetLibraryConcept returns one Concept's library detail: 200, 400, 404, 500.
func (h *Handler) handleGetLibraryConcept(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	if h.library == nil {
		writeError(w, http.StatusInternalServerError, "knowledge library is not configured")
		return
	}
	d, err := h.library.GetConcept(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "concept not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not read the concept")
		return
	}
	resp := libraryConceptResponse{
		SchemaVersion: application.KnowledgeLibraryConceptSchemaVersion, Concept: toConceptResponse(d.Concept),
		SupportingUnits: toLibraryUnits(d.SupportingUnits), NonSupportingMembers: toLibraryUnits(d.NonSupportingMembers),
		CurrentRelations:  make([]libraryRelationResponse, 0, len(d.CurrentRelations)),
		HistoricalUnits:   make([]libraryHistoricalUnitResponse, 0, len(d.HistoricalUnits)),
		HistoryEventCount: d.HistoryEventCount,
	}
	if d.PreferredUnit != nil {
		u := toLibraryUnit(*d.PreferredUnit)
		resp.PreferredUnit = &u
	}
	for _, rel := range d.CurrentRelations {
		resp.CurrentRelations = append(resp.CurrentRelations, libraryRelationResponse{
			Relation: string(rel.Link.Relation), LinkID: rel.Link.ID, DecisionSource: string(rel.Link.DecisionSource),
			DecidedAt: rel.Link.CreatedAt.Format(time.RFC3339Nano), Unit: toLibraryUnit(rel.Unit),
		})
	}
	for _, hu := range d.HistoricalUnits {
		resp.HistoricalUnits = append(resp.HistoricalUnits, libraryHistoricalUnitResponse{
			Unit: toLibraryUnit(hu.Unit), LatestEvent: toLinkResponse(hu.LatestEvent),
			EffectiveStatus: string(hu.EffectiveStatus), CurrentConceptID: hu.CurrentConceptID,
		})
	}
	writeJSON(w, http.StatusOK, resp)
}

// handleGetLibraryUnitSource returns one unit's provenance: 200, 400, 404, 500.
func (h *Handler) handleGetLibraryUnitSource(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	if h.library == nil {
		writeError(w, http.StatusInternalServerError, "knowledge library is not configured")
		return
	}
	src, err := h.library.GetUnitSource(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "knowledge unit not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not read the unit source")
		return
	}
	interp := src.SourceInterpretation
	resp := librarySourceResponse{
		SchemaVersion: application.KnowledgeLibrarySourceSchemaVersion,
		Unit:          toLibraryUnit(src.Unit),
		Entry:         toResponse(&src.Entry),
		Extraction: libraryExtractionResponse{
			ID: src.Extraction.ID, Version: src.Extraction.Version, Extractor: src.Extraction.Extractor,
			SourceAnalysisID: src.Extraction.SourceAnalysisID, SourceFeedbackID: src.Extraction.SourceFeedbackID,
			CreatedAt: src.Extraction.CreatedAt.Format(time.RFC3339Nano),
		},
		CurrentExtraction: librarySelectionResponse{ExtractionID: src.CurrentSelection.ExtractionID, SelectionMode: string(src.CurrentSelection.Mode)},
		SourceInterpretation: libraryInterpretationResponse{
			Analysis: toAnalysisResponse(&interp.Analysis), Effective: toEffectiveResponse(interp.Effective),
		},
		Annotation: libraryAnnotationResponse{Status: string(src.Annotation.Status)},
	}
	if interp.Feedback != nil {
		f := toFeedbackResponse(interp.Feedback)
		resp.SourceInterpretation.Feedback = &f
	}
	if src.LatestAnalysis != nil {
		resp.LatestAnalysis = &libraryAnalysisRefResponse{
			ID: src.LatestAnalysis.ID, Version: src.LatestAnalysis.Version,
			CreatedAt: src.LatestAnalysis.CreatedAt.Format(time.RFC3339Nano),
		}
	}
	if src.Annotation.CurrentSame != nil {
		cid := src.Annotation.CurrentSame.Membership.ConceptID
		resp.Annotation.CurrentConceptID = &cid
	}
	writeJSON(w, http.StatusOK, resp)
}
