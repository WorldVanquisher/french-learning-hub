package http

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// ConceptService is the subset of concept-resolution behavior the handlers depend
// on. The transport layer depends only on this narrow interface, not on the
// concrete application service.
type ConceptService interface {
	ResolveCandidate(ctx context.Context, unitID int64) (*application.ResolutionOutcome, error)
	ResolveSame(ctx context.Context, unitID, conceptID int64) (*domain.UnitConceptLink, error)
	CreateConcept(ctx context.Context, identity domain.ConceptIdentity, seedUnitID *int64, linkSeedAsSame bool) (*domain.KnowledgeConcept, *domain.UnitConceptLink, error)
	RecordRelation(ctx context.Context, unitID, conceptID int64, relation domain.ConceptRelation) (*domain.UnitConceptLink, error)
	SetPreferredUnit(ctx context.Context, conceptID, unitID int64) (*domain.KnowledgeConcept, error)
	GetConcept(ctx context.Context, conceptID int64) (*domain.ConceptView, error)
	ListConcepts(ctx context.Context, state *domain.ConceptState) ([]domain.KnowledgeConcept, error)
	ListReviewableUnits(ctx context.Context, entryID *int64) ([]domain.ReviewableUnit, error)
	GetCurrentExtraction(ctx context.Context, entryID int64) (*int64, error)
	SetCurrentExtraction(ctx context.Context, entryID, extractionID int64) error
}

// ---- response DTOs ----

// conceptResponse is the wire shape of one durable concept. It exposes the
// identity under its explicit schema version, the stable signature, the chosen
// preferred unit (null when unset), and the lifecycle state.
type conceptResponse struct {
	ID                    int64             `json:"id"`
	IdentitySchemaVersion string            `json:"identity_schema_version"`
	Target                string            `json:"target"`
	PedagogicalIntent     string            `json:"pedagogical_intent"`
	Scope                 string            `json:"scope"`
	IdentityFeatures      map[string]string `json:"identity_features"`
	Signature             string            `json:"signature"`
	PreferredUnitID       *int64            `json:"preferred_unit_id"`
	State                 string            `json:"state"`
	CreatedAt             string            `json:"created_at"`
	UpdatedAt             string            `json:"updated_at"`
}

func toConceptResponse(c domain.KnowledgeConcept) conceptResponse {
	features := c.IdentityFeatures
	if features == nil {
		features = map[string]string{}
	}
	return conceptResponse{
		ID:                    c.ID,
		IdentitySchemaVersion: c.IdentitySchemaVersion,
		Target:                c.Target,
		PedagogicalIntent:     c.PedagogicalIntent,
		Scope:                 c.Scope,
		IdentityFeatures:      features,
		Signature:             c.Signature,
		PreferredUnitID:       c.PreferredUnitID,
		State:                 string(c.State),
		CreatedAt:             c.CreatedAt.Format(time.RFC3339Nano),
		UpdatedAt:             c.UpdatedAt.Format(time.RFC3339Nano),
	}
}

// unitConceptLinkResponse is the wire shape of one append-only resolution
// decision. It carries the full auditable record.
type unitConceptLinkResponse struct {
	ID              int64    `json:"id"`
	UnitID          int64    `json:"unit_id"`
	ConceptID       int64    `json:"concept_id"`
	Relation        string   `json:"relation"`
	Status          string   `json:"status"`
	DecisionSource  string   `json:"decision_source"`
	ResolverVersion string   `json:"resolver_version"`
	Score           *float64 `json:"score"`
	Evidence        string   `json:"evidence"`
	CreatedAt       string   `json:"created_at"`
}

func toLinkResponse(l domain.UnitConceptLink) unitConceptLinkResponse {
	return unitConceptLinkResponse{
		ID:              l.ID,
		UnitID:          l.UnitID,
		ConceptID:       l.ConceptID,
		Relation:        string(l.Relation),
		Status:          string(l.Status),
		DecisionSource:  string(l.DecisionSource),
		ResolverVersion: l.ResolverVersion,
		Score:           l.Score,
		Evidence:        l.Evidence,
		CreatedAt:       l.CreatedAt.Format(time.RFC3339Nano),
	}
}

// conceptViewResponse is one concept plus its resolution links.
type conceptViewResponse struct {
	Concept conceptResponse           `json:"concept"`
	Links   []unitConceptLinkResponse `json:"links"`
}

func toConceptViewResponse(v *domain.ConceptView) conceptViewResponse {
	links := make([]unitConceptLinkResponse, 0, len(v.Links))
	for _, l := range v.Links {
		links = append(links, toLinkResponse(l))
	}
	return conceptViewResponse{Concept: toConceptResponse(v.Concept), Links: links}
}

// conceptIdentityDTO is the identity payload used in request bodies and the
// candidate part of a resolution outcome.
type conceptIdentityDTO struct {
	Target            string            `json:"target"`
	PedagogicalIntent string            `json:"pedagogical_intent"`
	Scope             string            `json:"scope"`
	IdentityFeatures  map[string]string `json:"identity_features"`
}

func (d conceptIdentityDTO) toDomain() domain.ConceptIdentity {
	return domain.ConceptIdentity{
		Target:            d.Target,
		PedagogicalIntent: d.PedagogicalIntent,
		Scope:             d.Scope,
		IdentityFeatures:  d.IdentityFeatures,
	}
}

func toIdentityDTO(ci domain.ConceptIdentity) conceptIdentityDTO {
	features := ci.IdentityFeatures
	if features == nil {
		features = map[string]string{}
	}
	return conceptIdentityDTO{
		Target:            ci.Target,
		PedagogicalIntent: ci.PedagogicalIntent,
		Scope:             ci.Scope,
		IdentityFeatures:  features,
	}
}

// reviewableUnitResponse is one current-extraction unit awaiting SAME resolution,
// with its derived default candidate identity to seed a review UI.
type reviewableUnitResponse struct {
	UnitID    int64              `json:"unit_id"`
	Kind      string             `json:"kind"`
	Canonical string             `json:"canonical"`
	Statement string             `json:"statement"`
	Candidate conceptIdentityDTO `json:"candidate_identity"`
	Signature string             `json:"signature"`
}

func toReviewableUnitResponse(ru domain.ReviewableUnit) reviewableUnitResponse {
	return reviewableUnitResponse{
		UnitID:    ru.Unit.ID,
		Kind:      string(ru.Unit.Kind),
		Canonical: ru.Unit.Canonical,
		Statement: ru.Unit.Statement,
		Candidate: toIdentityDTO(ru.Candidate),
		Signature: ru.Candidate.Signature(),
	}
}

// resolutionOutcomeResponse reports the deterministic resolver decision for a unit
// and any active concepts sharing its signature. It records nothing.
type resolutionOutcomeResponse struct {
	UnitID    int64              `json:"unit_id"`
	Candidate conceptIdentityDTO `json:"candidate_identity"`
	Signature string             `json:"signature"`
	Decision  string             `json:"decision"`
	Matches   []conceptResponse  `json:"matches"`
}

func toResolutionOutcomeResponse(o *application.ResolutionOutcome) resolutionOutcomeResponse {
	matches := make([]conceptResponse, 0, len(o.Matches))
	for _, c := range o.Matches {
		matches = append(matches, toConceptResponse(c))
	}
	return resolutionOutcomeResponse{
		UnitID:    o.UnitID,
		Candidate: toIdentityDTO(o.Candidate),
		Signature: o.Candidate.Signature(),
		Decision:  string(o.Kind),
		Matches:   matches,
	}
}

// ---- request DTOs ----

type resolveSameRequest struct {
	ConceptID int64 `json:"concept_id"`
}

type createConceptRequest struct {
	Identity       conceptIdentityDTO `json:"identity"`
	SeedUnitID     *int64             `json:"seed_unit_id"`
	LinkSeedAsSame bool               `json:"link_seed_as_same"`
}

type recordRelationRequest struct {
	ConceptID int64  `json:"concept_id"`
	Relation  string `json:"relation"`
}

type setPreferredUnitRequest struct {
	UnitID int64 `json:"unit_id"`
}

type setCurrentExtractionRequest struct {
	ExtractionID int64 `json:"extraction_id"`
}

// ---- handlers ----

// handleListConcepts lists durable concepts, optionally filtered by ?state=. It
// is read-only and performs no AI call.
func (h *Handler) handleListConcepts(w http.ResponseWriter, r *http.Request) {
	var state *domain.ConceptState
	if v := r.URL.Query().Get("state"); v != "" {
		s := domain.ConceptState(v)
		state = &s
	}
	concepts, err := h.concept.ListConcepts(r.Context(), state)
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list concepts")
		return
	}
	resp := make([]conceptResponse, 0, len(concepts))
	for _, c := range concepts {
		resp = append(resp, toConceptResponse(c))
	}
	writeJSON(w, http.StatusOK, map[string]any{"concepts": resp})
}

// handleGetConcept returns one concept with its resolution links. Read-only.
func (h *Handler) handleGetConcept(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	view, err := h.concept.GetConcept(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "concept not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not fetch concept")
		return
	}
	writeJSON(w, http.StatusOK, toConceptViewResponse(view))
}

// handleCreateConcept creates a new durable concept from an explicit identity. It
// rejects a duplicate active identity with 409. Status: 201 created, 400 invalid
// JSON/id, 404 seed unit not found, 409 duplicate active identity, 422 invalid
// identity, 500 storage failure.
func (h *Handler) handleCreateConcept(w http.ResponseWriter, r *http.Request) {
	var req createConceptRequest
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}

	concept, link, err := h.concept.CreateConcept(r.Context(), req.Identity.toDomain(), req.SeedUnitID, req.LinkSeedAsSame)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "seed unit not found")
		return
	}
	if errors.Is(err, domain.ErrConceptConflict) {
		writeError(w, http.StatusConflict, err.Error())
		return
	}
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not create concept")
		return
	}

	resp := map[string]any{"concept": toConceptResponse(*concept)}
	if link != nil {
		l := toLinkResponse(*link)
		resp["link"] = &l
	} else {
		resp["link"] = nil
	}
	writeJSON(w, http.StatusCreated, resp)
}

// handleResolveUnit runs the deterministic resolver for a unit without recording
// anything. Read-only. Status: 200 ok, 400 invalid id, 404 unit not found.
func (h *Handler) handleResolveUnit(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	outcome, err := h.concept.ResolveCandidate(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "knowledge unit not found")
		return
	}
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not resolve unit")
		return
	}
	writeJSON(w, http.StatusOK, toResolutionOutcomeResponse(outcome))
}

// handleResolveSame records an explicit human accepted SAME membership from a unit
// to an existing concept. Status: 201 created, 400 invalid JSON/id, 404 unit or
// concept not found, 409 unit already has an accepted SAME to another concept,
// 500 storage failure.
func (h *Handler) handleResolveSame(w http.ResponseWriter, r *http.Request) {
	unitID, ok := parseID(w, r)
	if !ok {
		return
	}
	var req resolveSameRequest
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	link, err := h.concept.ResolveSame(r.Context(), unitID, req.ConceptID)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "unit or concept not found")
		return
	}
	if errors.Is(err, domain.ErrConceptConflict) {
		writeError(w, http.StatusConflict, err.Error())
		return
	}
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not record SAME membership")
		return
	}
	writeJSON(w, http.StatusCreated, toLinkResponse(*link))
}

// handleRecordRelation records a non-membership BROADER/NARROWER/RELATED decision
// for a unit. It never affects SAME membership. Status: 201 created, 400 invalid
// JSON/id, 404 unit or concept not found, 422 invalid relation (including
// 'same'), 500 storage failure.
func (h *Handler) handleRecordRelation(w http.ResponseWriter, r *http.Request) {
	unitID, ok := parseID(w, r)
	if !ok {
		return
	}
	var req recordRelationRequest
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	link, err := h.concept.RecordRelation(r.Context(), unitID, req.ConceptID, domain.ConceptRelation(req.Relation))
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "unit or concept not found")
		return
	}
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not record relation")
		return
	}
	writeJSON(w, http.StatusCreated, toLinkResponse(*link))
}

// handleSetPreferredUnit sets a concept's preferred representation. The unit must
// have an accepted SAME membership to the concept. Status: 200 ok, 400 invalid
// JSON/id, 404 concept not found, 422 unit lacks SAME membership, 500 storage
// failure.
func (h *Handler) handleSetPreferredUnit(w http.ResponseWriter, r *http.Request) {
	conceptID, ok := parseID(w, r)
	if !ok {
		return
	}
	var req setPreferredUnitRequest
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	concept, err := h.concept.SetPreferredUnit(r.Context(), conceptID, req.UnitID)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "concept not found")
		return
	}
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not set preferred unit")
		return
	}
	writeJSON(w, http.StatusOK, toConceptResponse(*concept))
}

// handleListReviewableUnits lists current-extraction units awaiting SAME
// resolution, optionally scoped to ?entry_id=. Read-only.
func (h *Handler) handleListReviewableUnits(w http.ResponseWriter, r *http.Request) {
	var entryID *int64
	if v := r.URL.Query().Get("entry_id"); v != "" {
		n, err := parseInt64(v)
		if err != nil || n <= 0 {
			writeError(w, http.StatusBadRequest, "invalid entry_id")
			return
		}
		entryID = &n
	}
	units, err := h.concept.ListReviewableUnits(r.Context(), entryID)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "entry not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list reviewable units")
		return
	}
	resp := make([]reviewableUnitResponse, 0, len(units))
	for _, u := range units {
		resp = append(resp, toReviewableUnitResponse(u))
	}
	writeJSON(w, http.StatusOK, map[string]any{"reviewable_units": resp})
}

// handleGetCurrentExtraction returns the entry's selected current extraction id
// (null when the entry has no successful extraction). Read-only.
func (h *Handler) handleGetCurrentExtraction(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	extractionID, err := h.concept.GetCurrentExtraction(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "entry not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not fetch current extraction")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"entry_id": id, "current_extraction_id": extractionID})
}

// handleSetCurrentExtraction explicitly selects a successful extraction as current
// (human rollback). Status: 200 ok, 400 invalid JSON/id, 404 entry not found, 422
// extraction not owned by entry, 500 storage failure.
func (h *Handler) handleSetCurrentExtraction(w http.ResponseWriter, r *http.Request) {
	entryID, ok := parseID(w, r)
	if !ok {
		return
	}
	var req setCurrentExtractionRequest
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	err := h.concept.SetCurrentExtraction(r.Context(), entryID, req.ExtractionID)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "entry not found")
		return
	}
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not set current extraction")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"entry_id": entryID, "current_extraction_id": req.ExtractionID})
}
