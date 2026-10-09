package application

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"
	"unicode/utf8"

	"french-learning-app/internal/domain"
)

// Knowledge Library (FLH-034) is a read-only, user-facing view over existing
// authority: durable Concepts, their derived support, CURRENT SAME membership,
// M11-A effective relations, and the provenance of each unit back to its source
// entry and the versioned interpretation its extraction used. It records no
// annotation and calls no analyzer, extractor, embedding or other provider. Its
// dependencies are deliberately read-only interfaces.

const (
	KnowledgeLibrarySearchSchemaVersion  = "knowledge_library_search_v1"
	KnowledgeLibraryConceptSchemaVersion = "knowledge_library_concept_v1"
	KnowledgeLibrarySourceSchemaVersion  = "knowledge_library_source_v1"

	KnowledgeLibraryDefaultLimit = 20
	KnowledgeLibraryMaxLimit     = 50
	// KnowledgeLibraryMaxQueryBytes and KnowledgeLibraryMaxQueryTokens bound one
	// search request.
	KnowledgeLibraryMaxQueryBytes  = 200
	KnowledgeLibraryMaxQueryTokens = 8
)

// ErrKnowledgeLibraryQuery reports an invalid search request (bad limit/state,
// over-long query, or a query with no searchable term).
var ErrKnowledgeLibraryQuery = errors.New("invalid knowledge library query")

// KnowledgeLibraryConceptReader is the read-only subset of concept storage used
// by the library. It has no write method by construction.
type KnowledgeLibraryConceptReader interface {
	ListConcepts(ctx context.Context, state *domain.ConceptState) ([]domain.KnowledgeConcept, error)
	GetConcept(ctx context.Context, conceptID int64) (*domain.ConceptView, error)
	GetCurrentMembership(ctx context.Context, unitID int64) (*domain.CurrentConceptMembership, error)
	ActiveSupportUnitIDs(ctx context.Context, conceptID int64) ([]int64, error)
	UnitByID(ctx context.Context, unitID int64) (*domain.KnowledgeUnit, error)
	GetCurrentExtractionSelection(ctx context.Context, entryID int64) (domain.CurrentExtractionSelection, error)
}

// KnowledgeLibraryExtractionReader reads one extraction with its units' admission.
type KnowledgeLibraryExtractionReader interface {
	GetByID(ctx context.Context, extractionID int64) (*domain.ExtractionView, error)
}

// KnowledgeLibraryEntryReader reads one learner-authored entry.
type KnowledgeLibraryEntryReader interface {
	GetByID(ctx context.Context, id int64) (*domain.Entry, error)
}

// KnowledgeLibraryAnalysisReader reads versioned analyses.
type KnowledgeLibraryAnalysisReader interface {
	GetByID(ctx context.Context, id int64) (*domain.Analysis, error)
	ListByEntry(ctx context.Context, entryID int64) ([]*domain.Analysis, error)
}

// KnowledgeLibraryFeedbackReader reads analysis feedback.
type KnowledgeLibraryFeedbackReader interface {
	ListByAnalysis(ctx context.Context, analysisID int64) ([]*domain.Feedback, error)
}

// KnowledgeLibraryAnnotationReader is the M11-A effective annotation projection.
type KnowledgeLibraryAnnotationReader interface {
	GetEffectiveAnnotationSnapshot(ctx context.Context, unitID int64) (domain.EffectiveAnnotationSnapshot, error)
}

// KnowledgeLibraryService composes the read models above.
type KnowledgeLibraryService struct {
	concepts    KnowledgeLibraryConceptReader
	extractions KnowledgeLibraryExtractionReader
	entries     KnowledgeLibraryEntryReader
	analyses    KnowledgeLibraryAnalysisReader
	feedback    KnowledgeLibraryFeedbackReader
	annotations KnowledgeLibraryAnnotationReader
}

func NewKnowledgeLibraryService(
	concepts KnowledgeLibraryConceptReader,
	extractions KnowledgeLibraryExtractionReader,
	entries KnowledgeLibraryEntryReader,
	analyses KnowledgeLibraryAnalysisReader,
	feedback KnowledgeLibraryFeedbackReader,
	annotations KnowledgeLibraryAnnotationReader,
) *KnowledgeLibraryService {
	return &KnowledgeLibraryService{concepts: concepts, extractions: extractions, entries: entries, analyses: analyses, feedback: feedback, annotations: annotations}
}

// ---- read models ----

// LibraryUnit is one KnowledgeUnit with the provenance facts needed to label it:
// its extraction version, whether that extraction is the entry's CURRENT one,
// and its effective admission state.
type LibraryUnit struct {
	Unit                domain.KnowledgeUnit
	EntryID             int64
	ExtractionVersion   int64
	InCurrentExtraction bool
	Admission           domain.MachineAdmissionState
}

// LibrarySearchQuery is one validated search or browse request.
type LibrarySearchQuery struct {
	Text  string
	State *domain.ConceptState
	Limit int
}

// LibrarySearchResult is one ranked Concept.
type LibrarySearchResult struct {
	Concept             domain.KnowledgeConcept
	MatchTier           string // "identity", "unit_evidence", or "browse"
	MatchedFields       []string
	CurrentMemberCount  int
	SupportingUnitCount int
}

// LibrarySearchReport is the bounded result page.
type LibrarySearchReport struct {
	Query        string
	Tokens       []string
	Limit        int
	TotalMatches int
	Truncated    bool
	Results      []LibrarySearchResult
}

// LibraryRelation is one CURRENT effective non-membership relation of a unit to
// the Concept (M11-A authority).
type LibraryRelation struct {
	Unit LibraryUnit
	Link domain.UnitConceptLink
}

// LibraryHistoricalUnit is a unit that has events for this Concept but holds no
// current membership or current relation to it. Its present facts explain why.
type LibraryHistoricalUnit struct {
	Unit             LibraryUnit
	LatestEvent      domain.UnitConceptLink
	EffectiveStatus  domain.EffectiveAnnotationStatus
	CurrentConceptID *int64
}

// LibraryConceptDetail is one Concept with its current representation, support,
// relations, and clearly separated history.
type LibraryConceptDetail struct {
	Concept              domain.KnowledgeConcept
	PreferredUnit        *LibraryUnit
	SupportingUnits      []LibraryUnit
	NonSupportingMembers []LibraryUnit
	CurrentRelations     []LibraryRelation
	HistoricalUnits      []LibraryHistoricalUnit
	HistoryEventCount    int
}

// LibrarySourceInterpretation is the exact versioned interpretation an
// extraction was derived from: that analysis, the feedback in force then, and
// the effective values they resolve to.
type LibrarySourceInterpretation struct {
	Analysis  domain.Analysis
	Feedback  *domain.Feedback
	Effective domain.EffectiveAnalysis
}

// LibrarySource is the provenance chain of one unit.
type LibrarySource struct {
	Unit                 LibraryUnit
	Entry                domain.Entry
	Extraction           domain.KnowledgeExtraction
	CurrentSelection     domain.CurrentExtractionSelection
	SourceInterpretation LibrarySourceInterpretation
	LatestAnalysis       *domain.Analysis
	Annotation           domain.EffectiveAnnotationSnapshot
}

// ---- search ----

// ParseLibrarySearchQuery validates raw request values.
func ParseLibrarySearchQuery(text, state string, limit *int) (LibrarySearchQuery, error) {
	q := LibrarySearchQuery{Text: strings.TrimSpace(text), Limit: KnowledgeLibraryDefaultLimit}
	if len(q.Text) > KnowledgeLibraryMaxQueryBytes || !utf8.ValidString(q.Text) {
		return q, fmt.Errorf("%w: q must be valid UTF-8 of at most %d bytes", ErrKnowledgeLibraryQuery, KnowledgeLibraryMaxQueryBytes)
	}
	switch state {
	case "", "all":
	case string(domain.ConceptActive), string(domain.ConceptOrphaned), string(domain.ConceptRetired):
		s := domain.ConceptState(state)
		q.State = &s
	default:
		return q, fmt.Errorf("%w: state must be all, active, orphaned or retired", ErrKnowledgeLibraryQuery)
	}
	if limit != nil {
		if *limit < 1 || *limit > KnowledgeLibraryMaxLimit {
			return q, fmt.Errorf("%w: limit must be between 1 and %d", ErrKnowledgeLibraryQuery, KnowledgeLibraryMaxLimit)
		}
		q.Limit = *limit
	}
	return q, nil
}

type libraryCandidate struct {
	concept domain.KnowledgeConcept
	tier    string
	fields  []string
}

// Search returns a bounded, deterministically ordered page of Concepts. An empty
// query browses every Concept in the state filter.
func (s *KnowledgeLibraryService) Search(ctx context.Context, q LibrarySearchQuery) (*LibrarySearchReport, error) {
	tokens := domainUniqueTokens(q.Text)
	if q.Text != "" && len(tokens) == 0 {
		return nil, fmt.Errorf("%w: q has no searchable term (terms need at least two letters or digits)", ErrKnowledgeLibraryQuery)
	}
	if len(tokens) > KnowledgeLibraryMaxQueryTokens {
		return nil, fmt.Errorf("%w: q has more than %d terms", ErrKnowledgeLibraryQuery, KnowledgeLibraryMaxQueryTokens)
	}
	concepts, err := s.concepts.ListConcepts(ctx, q.State)
	if err != nil {
		return nil, err
	}
	cache := newLibraryCache()
	var candidates []libraryCandidate
	for _, c := range concepts {
		if len(tokens) == 0 {
			candidates = append(candidates, libraryCandidate{concept: c, tier: "browse"})
			continue
		}
		identity := map[string][]string{
			"target":             NormalizeConceptLexicalTokens(c.Target),
			"pedagogical_intent": NormalizeConceptLexicalTokens(c.PedagogicalIntent),
			"scope":              NormalizeConceptLexicalTokens(c.Scope),
			"identity_features":  featureTokens(c.IdentityFeatures),
		}
		if fields, ok := matchAll(tokens, identity); ok {
			candidates = append(candidates, libraryCandidate{concept: c, tier: "identity", fields: fields})
			continue
		}
		members, err := s.currentMembers(ctx, c.ID, cache)
		if err != nil {
			return nil, err
		}
		evidence := map[string][]string{}
		for k, v := range identity {
			evidence[k] = v
		}
		for _, m := range members {
			evidence["unit_canonical"] = append(evidence["unit_canonical"], NormalizeConceptLexicalTokens(m.Unit.Canonical)...)
			evidence["unit_statement"] = append(evidence["unit_statement"], NormalizeConceptLexicalTokens(m.Unit.Statement)...)
			if m.Unit.Example != nil {
				evidence["unit_example"] = append(evidence["unit_example"], NormalizeConceptLexicalTokens(*m.Unit.Example)...)
			}
		}
		if fields, ok := matchAll(tokens, evidence); ok {
			candidates = append(candidates, libraryCandidate{concept: c, tier: "unit_evidence", fields: fields})
		}
	}
	sort.SliceStable(candidates, func(i, j int) bool {
		a, b := candidates[i], candidates[j]
		if tierRank(a.tier) != tierRank(b.tier) {
			return tierRank(a.tier) < tierRank(b.tier)
		}
		if stateRank(a.concept.State) != stateRank(b.concept.State) {
			return stateRank(a.concept.State) < stateRank(b.concept.State)
		}
		at, bt := strings.ToLower(a.concept.Target), strings.ToLower(b.concept.Target)
		if at != bt {
			return at < bt
		}
		return a.concept.ID < b.concept.ID
	})
	report := &LibrarySearchReport{Query: q.Text, Tokens: tokens, Limit: q.Limit, TotalMatches: len(candidates)}
	if len(candidates) > q.Limit {
		candidates = candidates[:q.Limit]
		report.Truncated = true
	}
	report.Results = make([]LibrarySearchResult, 0, len(candidates))
	for _, cand := range candidates {
		members, err := s.currentMembers(ctx, cand.concept.ID, cache)
		if err != nil {
			return nil, err
		}
		supporting, err := s.concepts.ActiveSupportUnitIDs(ctx, cand.concept.ID)
		if err != nil {
			return nil, err
		}
		fields := cand.fields
		if fields == nil {
			fields = []string{}
		}
		report.Results = append(report.Results, LibrarySearchResult{
			Concept: cand.concept, MatchTier: cand.tier, MatchedFields: fields,
			CurrentMemberCount: len(members), SupportingUnitCount: len(supporting),
		})
	}
	return report, nil
}

func domainUniqueTokens(text string) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, t := range NormalizeConceptLexicalTokens(text) {
		if !seen[t] {
			seen[t] = true
			out = append(out, t)
		}
	}
	return out
}

func featureTokens(features map[string]string) []string {
	var out []string
	for k, v := range features {
		out = append(out, NormalizeConceptLexicalTokens(k)...)
		out = append(out, NormalizeConceptLexicalTokens(v)...)
	}
	return out
}

// matchAll reports whether every query token is a prefix of some field token,
// and which fields matched at least one query token (sorted).
func matchAll(tokens []string, fields map[string][]string) ([]string, bool) {
	matchedFields := map[string]bool{}
	for _, q := range tokens {
		found := false
		for name, values := range fields {
			for _, v := range values {
				if strings.HasPrefix(v, q) {
					found = true
					matchedFields[name] = true
					break
				}
			}
		}
		if !found {
			return nil, false
		}
	}
	out := make([]string, 0, len(matchedFields))
	for name := range matchedFields {
		out = append(out, name)
	}
	sort.Strings(out)
	return out, true
}

func tierRank(tier string) int {
	switch tier {
	case "identity", "browse":
		return 0
	default:
		return 1
	}
}

func stateRank(state domain.ConceptState) int {
	switch state {
	case domain.ConceptActive:
		return 0
	case domain.ConceptOrphaned:
		return 1
	default:
		return 2
	}
}

// ---- concept detail ----

// GetConcept returns the Concept's current representation, support, relations,
// and history. Each unit appears in exactly one section, in this priority:
// supporting, current non-supporting member, current relation, historical.
func (s *KnowledgeLibraryService) GetConcept(ctx context.Context, conceptID int64) (*LibraryConceptDetail, error) {
	view, err := s.concepts.GetConcept(ctx, conceptID)
	if err != nil {
		return nil, err
	}
	cache := newLibraryCache()
	cache.views[conceptID] = view
	members, err := s.currentMembers(ctx, conceptID, cache)
	if err != nil {
		return nil, err
	}
	supportingIDs, err := s.concepts.ActiveSupportUnitIDs(ctx, conceptID)
	if err != nil {
		return nil, err
	}
	supporting := map[int64]bool{}
	for _, id := range supportingIDs {
		supporting[id] = true
	}
	detail := &LibraryConceptDetail{
		Concept: view.Concept, HistoryEventCount: len(view.Links),
		SupportingUnits: []LibraryUnit{}, NonSupportingMembers: []LibraryUnit{},
		CurrentRelations: []LibraryRelation{}, HistoricalUnits: []LibraryHistoricalUnit{},
	}
	placed := map[int64]bool{}
	for _, m := range members {
		placed[m.Unit.ID] = true
		if supporting[m.Unit.ID] {
			detail.SupportingUnits = append(detail.SupportingUnits, m)
		} else {
			detail.NonSupportingMembers = append(detail.NonSupportingMembers, m)
		}
		if view.Concept.PreferredUnitID != nil && *view.Concept.PreferredUnitID == m.Unit.ID {
			preferred := m
			detail.PreferredUnit = &preferred
		}
	}
	if view.Concept.PreferredUnitID != nil && detail.PreferredUnit == nil {
		// SetPreferredUnit requires a current member and membership changes clear
		// it, so this indicates inconsistent storage rather than a display case.
		return nil, fmt.Errorf("concept %d preferred unit %d is not a current member", conceptID, *view.Concept.PreferredUnitID)
	}

	latestByUnit := map[int64]domain.UnitConceptLink{}
	var unitOrder []int64
	for _, l := range view.Links {
		prev, ok := latestByUnit[l.UnitID]
		if !ok {
			unitOrder = append(unitOrder, l.UnitID)
		}
		if !ok || l.CreatedAt.After(prev.CreatedAt) || (l.CreatedAt.Equal(prev.CreatedAt) && l.ID > prev.ID) {
			latestByUnit[l.UnitID] = l
		}
	}
	sort.Slice(unitOrder, func(i, j int) bool { return unitOrder[i] < unitOrder[j] })
	for _, unitID := range unitOrder {
		if placed[unitID] {
			continue
		}
		unit, err := s.libraryUnit(ctx, unitID, cache)
		if err != nil {
			return nil, err
		}
		snapshot, err := s.annotations.GetEffectiveAnnotationSnapshot(ctx, unitID)
		if err != nil {
			return nil, err
		}
		var current []domain.UnitConceptLink
		if unit.InCurrentExtraction && snapshot.Status != domain.EffectiveAnnotationInvalid {
			for _, r := range snapshot.Relations {
				if r.ConceptID == conceptID {
					current = append(current, r)
				}
			}
		}
		if len(current) > 0 {
			for _, r := range current {
				detail.CurrentRelations = append(detail.CurrentRelations, LibraryRelation{Unit: unit, Link: r})
			}
			continue
		}
		h := LibraryHistoricalUnit{Unit: unit, LatestEvent: latestByUnit[unitID], EffectiveStatus: snapshot.Status}
		if snapshot.CurrentSame != nil {
			id := snapshot.CurrentSame.Membership.ConceptID
			h.CurrentConceptID = &id
		}
		detail.HistoricalUnits = append(detail.HistoricalUnits, h)
	}
	return detail, nil
}

// ---- source ----

// GetUnitSource returns the provenance chain of one unit.
func (s *KnowledgeLibraryService) GetUnitSource(ctx context.Context, unitID int64) (*LibrarySource, error) {
	cache := newLibraryCache()
	unit, err := s.libraryUnit(ctx, unitID, cache)
	if err != nil {
		return nil, err
	}
	extraction := cache.extractions[unit.Unit.ExtractionID].Extraction
	entry, err := s.entries.GetByID(ctx, extraction.EntryID)
	if err != nil {
		return nil, err
	}
	analysis, err := s.analyses.GetByID(ctx, extraction.SourceAnalysisID)
	if err != nil {
		return nil, err
	}
	var feedback *domain.Feedback
	if extraction.SourceFeedbackID != nil {
		all, err := s.feedback.ListByAnalysis(ctx, analysis.ID)
		if err != nil {
			return nil, err
		}
		for _, f := range all {
			if f.ID == *extraction.SourceFeedbackID {
				feedback = f
			}
		}
		if feedback == nil {
			return nil, fmt.Errorf("extraction %d source feedback %d not found for analysis %d", extraction.ID, *extraction.SourceFeedbackID, analysis.ID)
		}
	}
	analyses, err := s.analyses.ListByEntry(ctx, entry.ID)
	if err != nil {
		return nil, err
	}
	var latest *domain.Analysis
	if len(analyses) > 0 {
		latest = analyses[len(analyses)-1]
	}
	snapshot, err := s.annotations.GetEffectiveAnnotationSnapshot(ctx, unitID)
	if err != nil {
		return nil, err
	}
	return &LibrarySource{
		Unit: unit, Entry: *entry, Extraction: extraction,
		CurrentSelection: cache.selections[entry.ID],
		SourceInterpretation: LibrarySourceInterpretation{
			Analysis: *analysis, Feedback: feedback, Effective: domain.ResolveEffective(analysis, feedback),
		},
		LatestAnalysis: latest,
		Annotation:     snapshot,
	}, nil
}

// ---- shared lookups ----

type libraryCache struct {
	views       map[int64]*domain.ConceptView
	members     map[int64][]LibraryUnit
	units       map[int64]LibraryUnit
	extractions map[int64]*domain.ExtractionView
	selections  map[int64]domain.CurrentExtractionSelection
}

func newLibraryCache() *libraryCache {
	return &libraryCache{
		views: map[int64]*domain.ConceptView{}, members: map[int64][]LibraryUnit{}, units: map[int64]LibraryUnit{},
		extractions: map[int64]*domain.ExtractionView{}, selections: map[int64]domain.CurrentExtractionSelection{},
	}
}

// currentMembers returns the units whose CURRENT SAME membership (the projection,
// never the event log) is this Concept, by unit id. Candidates come from the
// Concept's SAME events, since membership is only ever established by one.
func (s *KnowledgeLibraryService) currentMembers(ctx context.Context, conceptID int64, cache *libraryCache) ([]LibraryUnit, error) {
	if m, ok := cache.members[conceptID]; ok {
		return m, nil
	}
	view, ok := cache.views[conceptID]
	if !ok {
		v, err := s.concepts.GetConcept(ctx, conceptID)
		if err != nil {
			return nil, err
		}
		view = v
		cache.views[conceptID] = v
	}
	seen := map[int64]bool{}
	var ids []int64
	for _, l := range view.Links {
		if l.Relation == domain.RelationSame && !seen[l.UnitID] {
			seen[l.UnitID] = true
			ids = append(ids, l.UnitID)
		}
	}
	sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })
	members := []LibraryUnit{}
	for _, id := range ids {
		m, err := s.concepts.GetCurrentMembership(ctx, id)
		if err != nil {
			return nil, err
		}
		if m == nil || m.ConceptID != conceptID {
			continue
		}
		u, err := s.libraryUnit(ctx, id, cache)
		if err != nil {
			return nil, err
		}
		members = append(members, u)
	}
	cache.members[conceptID] = members
	return members, nil
}

func (s *KnowledgeLibraryService) libraryUnit(ctx context.Context, unitID int64, cache *libraryCache) (LibraryUnit, error) {
	if u, ok := cache.units[unitID]; ok {
		return u, nil
	}
	unit, err := s.concepts.UnitByID(ctx, unitID)
	if err != nil {
		return LibraryUnit{}, err
	}
	view, ok := cache.extractions[unit.ExtractionID]
	if !ok {
		view, err = s.extractions.GetByID(ctx, unit.ExtractionID)
		if err != nil {
			return LibraryUnit{}, err
		}
		cache.extractions[unit.ExtractionID] = view
	}
	entryID := view.Extraction.EntryID
	selection, ok := cache.selections[entryID]
	if !ok {
		selection, err = s.concepts.GetCurrentExtractionSelection(ctx, entryID)
		if err != nil {
			return LibraryUnit{}, err
		}
		cache.selections[entryID] = selection
	}
	out := LibraryUnit{
		Unit: *unit, EntryID: entryID, ExtractionVersion: view.Extraction.Version,
		InCurrentExtraction: selection.ExtractionID != nil && *selection.ExtractionID == unit.ExtractionID,
	}
	found := false
	for _, uv := range view.Units {
		if uv.Unit.ID == unitID {
			out.Admission = uv.Admission.Effective
			found = true
		}
	}
	if !found {
		return LibraryUnit{}, fmt.Errorf("unit %d missing from extraction %d", unitID, unit.ExtractionID)
	}
	cache.units[unitID] = out
	return out, nil
}
