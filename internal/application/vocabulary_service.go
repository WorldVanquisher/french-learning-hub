package application

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"french-learning-app/internal/domain"
)

// VocabularyService is the learner's private saved vocabulary (Workbooks).
//
// What can be saved (VOC-011): a Concept that concept_kind_view_v1 classifies
// as vocabulary (every current supporting unit is of kind vocabulary), that is
// not retired, with the example unit chosen among its CURRENT supporting units
// (current extraction, effective admission active, CURRENT SAME). A unit from a
// rejected analysis, a suppressed or pending unit, or one from an older
// extraction is not supporting, so it cannot be saved (VOC-049).
//
// Identity (VOC-013, VOC-014): the saved term is the Concept, never its text.
// The list reads every saved Concept and each example's source again; nothing
// learner-facing is copied into the vocabulary tables.
type VocabularyService struct {
	repo    domain.VocabularyRepository
	library vocabularyLibrary
	now     func() time.Time
}

type vocabularyLibrary interface {
	GetConcept(ctx context.Context, conceptID int64) (*LibraryConceptDetail, error)
	GetUnitSource(ctx context.Context, unitID int64) (*LibrarySource, error)
}

// NewVocabularyService builds the service over the Knowledge Library reads.
func NewVocabularyService(repo domain.VocabularyRepository, library vocabularyLibrary) *VocabularyService {
	return &VocabularyService{repo: repo, library: library, now: func() time.Time { return time.Now().UTC() }}
}

// WithClock replaces the service's clock (tests: a fixed time near midnight).
func (s *VocabularyService) WithClock(now func() time.Time) *VocabularyService {
	s.now = now
	return s
}

// Example states of a saved term's source example.
const (
	VocabularyExampleCurrent    = "current"     // the unit still supports the Concept
	VocabularyExampleNotCurrent = "not_current" // a newer extraction, an admission change or a reassignment
	VocabularyExampleMissing    = "missing"     // its unit or record can no longer be read
)

// VocabularyExampleView is one example as read now.
type VocabularyExampleView struct {
	Example domain.VocabularyExample
	Source  *LibrarySource // nil when it cannot be read (Status missing)
	Status  string
	// NewerExtraction: the record's current extraction is newer than the one
	// this example was saved from (the example is still shown as it was).
	NewerExtraction bool
}

// VocabularyItem is one saved term.
type VocabularyItem struct {
	Mark     domain.VocabularyMark
	Concept  *domain.KnowledgeConcept // nil when the Concept cannot be read
	Examples []VocabularyExampleView
	// ReviewUnits counts the Concept's current supporting units: the units
	// Recall Practice can offer. 0 means no review is available now.
	ReviewUnits int
}

// VocabularyList is GET /vocabulary.
type VocabularyList struct {
	Query  string
	Tokens []string
	Items  []VocabularyItem
	Saved  int // every saved term, before the query
}

// ErrVocabularyQuery is a bad query (400).
var ErrVocabularyQuery = errors.New("invalid vocabulary query")

// VocabularyMaxQueryBytes bounds q.
const VocabularyMaxQueryBytes = 200

func savableUnit(d *LibraryConceptDetail, unitID int64) (*LibraryUnit, error) {
	if d.Concept.State == domain.ConceptRetired {
		return nil, &domain.VocabularyNotSavableError{Reason: domain.VocabularyConceptRetired}
	}
	kinds := make([]domain.KnowledgeKind, 0, len(d.SupportingUnits))
	for _, u := range d.SupportingUnits {
		kinds = append(kinds, u.Unit.Kind)
	}
	if class, _ := domain.ClassifyConceptKinds(kinds); class != domain.KindViewVocabulary {
		return nil, &domain.VocabularyNotSavableError{Reason: domain.VocabularyNotVocabulary}
	}
	for i := range d.SupportingUnits {
		if d.SupportingUnits[i].Unit.ID == unitID {
			return &d.SupportingUnits[i], nil
		}
	}
	return nil, &domain.VocabularyNotSavableError{Reason: domain.VocabularyUnitNotSupporting}
}

// Save saves the Concept with one example. Repeating it changes nothing
// (VOC-022); a new example of a saved Concept is attached to it (VOC-015).
func (s *VocabularyService) Save(ctx context.Context, conceptID, unitID int64) (*VocabularyItem, bool, bool, error) {
	if conceptID < 1 || unitID < 1 {
		return nil, false, false, fmt.Errorf("%w: concept and unit ids must be positive", domain.ErrValidation)
	}
	d, err := s.library.GetConcept(ctx, conceptID)
	if err != nil {
		return nil, false, false, err
	}
	u, err := savableUnit(d, unitID)
	if err != nil {
		return nil, false, false, err
	}
	ex := domain.VocabularyExample{ConceptID: conceptID, UnitID: unitID, EntryID: u.EntryID, ExtractionID: u.Unit.ExtractionID, ExtractionVersion: u.ExtractionVersion}
	_, saved, added, err := s.repo.Save(ctx, ex, s.now())
	if err != nil {
		return nil, false, false, err
	}
	item, err := s.item(ctx, conceptID)
	return item, saved, added, err
}

// Remove removes a saved Concept from the list. ErrNotFound when it was never
// saved; removing it again changes nothing (VOC-029). Examples, the Concept,
// its units and review history stay (VOC-027).
func (s *VocabularyService) Remove(ctx context.Context, conceptID int64) (domain.VocabularyMark, bool, error) {
	if conceptID < 1 {
		return domain.VocabularyMark{}, false, fmt.Errorf("%w: concept id must be positive", domain.ErrValidation)
	}
	return s.repo.Remove(ctx, conceptID, s.now())
}

func (s *VocabularyService) item(ctx context.Context, conceptID int64) (*VocabularyItem, error) {
	marks, err := s.repo.Marks(ctx)
	if err != nil {
		return nil, err
	}
	exs, err := s.repo.Examples(ctx, []int64{conceptID})
	if err != nil {
		return nil, err
	}
	it, err := s.read(ctx, marks[conceptID], exs[conceptID])
	return &it, err
}

// read builds one item; an unreadable Concept or example degrades that part
// only (VOC-054, VOC-059), never the list.
func (s *VocabularyService) read(ctx context.Context, m domain.VocabularyMark, exs []domain.VocabularyExample) (VocabularyItem, error) {
	it := VocabularyItem{Mark: m}
	d, err := s.library.GetConcept(ctx, m.ConceptID)
	switch {
	case err == nil:
		c := d.Concept
		it.Concept = &c
		it.ReviewUnits = len(d.SupportingUnits)
	case errors.Is(err, domain.ErrNotFound):
	default:
		return it, err
	}
	supporting := map[int64]bool{}
	if d != nil {
		for _, u := range d.SupportingUnits {
			supporting[u.Unit.ID] = true
		}
	}
	for _, e := range exs {
		v := VocabularyExampleView{Example: e, Status: VocabularyExampleMissing}
		src, err := s.library.GetUnitSource(ctx, e.UnitID)
		switch {
		case err == nil:
			v.Source = src
			v.Status = VocabularyExampleNotCurrent
			if supporting[e.UnitID] {
				v.Status = VocabularyExampleCurrent
			}
			if src.CurrentSelection.ExtractionID != nil && *src.CurrentSelection.ExtractionID != e.ExtractionID {
				v.NewerExtraction = true
			}
		case errors.Is(err, domain.ErrNotFound):
		default:
			return it, err
		}
		it.Examples = append(it.Examples, v)
	}
	return it, nil
}

// vocabularyFields are the item's searchable texts (VOC-031 to VOC-033): the
// Concept's identity, each example's wording, meaning in both languages, the
// example sentence and the learner's own question and context.
func vocabularyFields(it VocabularyItem) []string {
	var out []string
	add := func(s string) { out = append(out, NormalizeConceptLexicalTokens(s)...) }
	if it.Concept != nil {
		add(it.Concept.Target)
		add(it.Concept.PedagogicalIntent)
		add(it.Concept.Scope)
	}
	for _, e := range it.Examples {
		if e.Source == nil {
			continue
		}
		u := e.Source.Unit.Unit
		add(u.Canonical)
		add(u.Statement)
		for _, v := range []*string{u.Statements.EN, u.Statements.ZH, u.Example} {
			if v != nil {
				add(*v)
			}
		}
		add(e.Source.Entry.OriginalInput)
		add(e.Source.Entry.OriginalContext)
	}
	return out
}

// sortKey orders by the Concept's target, accent- and case-insensitively, then
// its exact text, then the Concept ID, so equal names keep one order (VOC-034).
func sortKey(it VocabularyItem) (string, string, int64) {
	if it.Concept == nil {
		return "￿", "", it.Mark.ConceptID
	}
	return strings.Join(NormalizeConceptLexicalTokens(it.Concept.Target), " "), it.Concept.Target, it.Mark.ConceptID
}

// List returns the saved terms matching q (every query token is a prefix of a
// token of the item, under concept_lexical_normalization_v1, as the Knowledge
// Library search does: accents and case are ignored).
func (s *VocabularyService) List(ctx context.Context, q string) (*VocabularyList, error) {
	q = strings.TrimSpace(q)
	if len(q) > VocabularyMaxQueryBytes {
		return nil, fmt.Errorf("%w: q must be at most %d bytes", ErrVocabularyQuery, VocabularyMaxQueryBytes)
	}
	tokens := domainUniqueTokens(q)
	if q != "" && len(tokens) == 0 {
		return nil, fmt.Errorf("%w: q has no searchable term (letters or digits, two or more)", ErrVocabularyQuery)
	}
	marks, err := s.repo.Marks(ctx)
	if err != nil {
		return nil, err
	}
	ids := []int64{}
	for id, m := range marks {
		if m.Saved {
			ids = append(ids, id)
		}
	}
	exs, err := s.repo.Examples(ctx, ids)
	if err != nil {
		return nil, err
	}
	out := &VocabularyList{Query: q, Tokens: tokens, Items: []VocabularyItem{}, Saved: len(ids)}
	for _, id := range ids {
		it, err := s.read(ctx, marks[id], exs[id])
		if err != nil {
			return nil, err
		}
		if len(tokens) > 0 {
			fields := vocabularyFields(it)
			ok := true
			for _, t := range tokens {
				found := false
				for _, f := range fields {
					if strings.HasPrefix(f, t) {
						found = true
						break
					}
				}
				if !found {
					ok = false
					break
				}
			}
			if !ok {
				continue
			}
		}
		out.Items = append(out.Items, it)
	}
	sort.SliceStable(out.Items, func(i, j int) bool {
		a1, a2, a3 := sortKey(out.Items[i])
		b1, b2, b3 := sortKey(out.Items[j])
		if a1 != b1 {
			return a1 < b1
		}
		if a2 != b2 {
			return a2 < b2
		}
		return a3 < b3
	})
	return out, nil
}
