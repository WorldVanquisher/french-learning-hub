package application

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"time"

	"french-learning-app/internal/domain"
)

// Mistake Notebook v1: one place to revisit misses from all four skills.
// Notebook items are ordinary learning records saved with a structured
// source_ref; MistakeSourceResolver reads that exact stored item from its own
// records (never from the record's prose). The Grammar and Vocabulary views
// reuse the Knowledge Library search, Concept IDs and support rules, and
// classify a Concept only by the kinds of its current supporting units.
// Nothing here calls a provider or writes anything but a retry mark.

type notebookListeningReader interface {
	GetExercise(ctx context.Context, id int64) (domain.ListeningExercise, error)
	GetMaterial(ctx context.Context, id int64) (domain.ListeningMaterial, error)
	GetTranscript(ctx context.Context, id int64) (domain.ListeningTranscript, error)
}

type notebookReadingReader interface {
	GetExercise(ctx context.Context, id int64) (domain.ReadingExercise, error)
	GetLesson(ctx context.Context, id int64) (domain.ReadingLesson, error)
	ListPassages(ctx context.Context, lessonID int64) ([]domain.ReadingPassage, error)
}

type notebookWritingReader interface {
	GetFeedback(ctx context.Context, id int64) (domain.WritingFeedback, error)
	GetDraft(ctx context.Context, id int64) (domain.WritingDraft, error)
	GetTask(ctx context.Context, id int64) (domain.WritingTask, error)
}

type notebookSpeakingReader interface {
	GetFeedback(ctx context.Context, id int64) (domain.SpeakingFeedback, error)
	GetTranscript(ctx context.Context, id int64) (domain.SpeakingTranscript, error)
	GetTake(ctx context.Context, id int64) (domain.SpeakingTake, error)
	GetExercise(ctx context.Context, id int64) (domain.SpeakingExercise, error)
}

// MistakeSourceResolver resolves a source_ref against the four skills' stored
// records. It is the capture service's SourceResolver and the notebook's.
type MistakeSourceResolver struct {
	listening notebookListeningReader
	reading   notebookReadingReader
	writing   notebookWritingReader
	speaking  notebookSpeakingReader
}

var _ domain.SourceResolver = (*MistakeSourceResolver)(nil)

// NewMistakeSourceResolver builds the resolver over the skills' repositories.
func NewMistakeSourceResolver(l notebookListeningReader, r notebookReadingReader, w notebookWritingReader, s notebookSpeakingReader) *MistakeSourceResolver {
	return &MistakeSourceResolver{listening: l, reading: r, writing: w, speaking: s}
}

func notUsable(what string, id int64) error {
	return fmt.Errorf("%w: %s %d has no completed content to save from", domain.ErrValidation, what, id)
}

func outOfRange(what string, id int64, item, n int) error {
	return fmt.Errorf("%w: %s %d has %d items; item %d does not exist", domain.ErrValidation, what, id, n, item)
}

// ResolveSource reads the referenced item. Missing records are ErrNotFound;
// failed content, an item out of range, or a writing/speaking quote that the
// server did not find in its version are ErrValidation.
func (r *MistakeSourceResolver) ResolveSource(ctx context.Context, ref domain.CaptureSourceRef) (domain.ResolvedSource, error) {
	var out domain.ResolvedSource
	out.Skill = domain.SourceSkill(ref.Type)
	switch ref.Type {
	case domain.SourceListeningItem:
		e, err := r.listening.GetExercise(ctx, ref.RecordID)
		if err != nil {
			return out, err
		}
		if e.Status != domain.ListeningExerciseCompleted || e.Content == nil {
			return out, notUsable("listening exercise", e.ID)
		}
		if ref.Item > len(e.Content.Items) {
			return out, outOfRange("listening exercise", e.ID, ref.Item, len(e.Content.Items))
		}
		m, err := r.listening.GetMaterial(ctx, e.MaterialID)
		if err != nil {
			return out, err
		}
		tr, err := r.listening.GetTranscript(ctx, e.TranscriptID)
		if err != nil {
			return out, err
		}
		it := e.Content.Items[ref.Item-1]
		out.Title, out.Prompt, out.Category, out.Reference = m.Title, it.Question, it.Kind, it.ExpectedAnswer
		out.ExplanationEN, out.ExplanationZH = it.RationaleEN, it.RationaleZH
		out.Link = domain.SourceLink{ListeningMaterialID: m.ID, ListeningExerciseID: e.ID, ListeningTranscriptVersion: tr.Version}
	case domain.SourceReadingItem:
		e, err := r.reading.GetExercise(ctx, ref.RecordID)
		if err != nil {
			return out, err
		}
		if e.Status != domain.ListeningExerciseCompleted || e.Content == nil {
			return out, notUsable("reading exercise", e.ID)
		}
		if ref.Item > len(e.Content.Items) {
			return out, outOfRange("reading exercise", e.ID, ref.Item, len(e.Content.Items))
		}
		l, err := r.reading.GetLesson(ctx, e.LessonID)
		if err != nil {
			return out, err
		}
		passages, err := r.reading.ListPassages(ctx, l.ID)
		if err != nil {
			return out, err
		}
		version := 0
		for _, p := range passages {
			if p.ID == e.PassageID {
				version = p.Version
			}
		}
		it := e.Content.Items[ref.Item-1]
		out.Title, out.Prompt, out.Category, out.Reference = l.Title, it.Question, it.Kind, it.ReferenceAnswer
		out.ExplanationEN, out.ExplanationZH = it.ExplanationEN, it.ExplanationZH
		out.Link = domain.SourceLink{ReadingLessonID: l.ID, ReadingPassageVersion: version, ReadingExerciseID: e.ID}
	case domain.SourceWritingCorrection:
		f, err := r.writing.GetFeedback(ctx, ref.RecordID)
		if err != nil {
			return out, err
		}
		if f.Status != domain.ListeningExerciseCompleted || f.Content == nil {
			return out, notUsable("writing feedback", f.ID)
		}
		if ref.Item > len(f.Content.Corrections) {
			return out, outOfRange("writing feedback", f.ID, ref.Item, len(f.Content.Corrections))
		}
		k := f.Content.Corrections[ref.Item-1]
		if k.Grounding == domain.WritingNotFound {
			return out, fmt.Errorf("%w: correction %d quotes words that are not in that version", domain.ErrValidation, ref.Item)
		}
		d, err := r.writing.GetDraft(ctx, f.DraftID)
		if err != nil {
			return out, err
		}
		t, err := r.writing.GetTask(ctx, f.TaskID)
		if err != nil {
			return out, err
		}
		out.Title, out.Prompt, out.Category, out.Quote, out.Reference = t.Title, t.Prompt, k.Category, k.Quote, k.Suggestion
		out.ExplanationEN, out.ExplanationZH, out.HintEN, out.HintZH = k.ReasonEN, k.ReasonZH, k.HintEN, k.HintZH
		out.Link = domain.SourceLink{WritingTaskID: t.ID, WritingDraftID: d.ID, WritingDraftVersion: d.Version, WritingFeedbackID: f.ID}
	case domain.SourceSpeakingImprovement:
		f, err := r.speaking.GetFeedback(ctx, ref.RecordID)
		if err != nil {
			return out, err
		}
		if f.Status != domain.ListeningExerciseCompleted || f.Content == nil {
			return out, notUsable("speaking feedback", f.ID)
		}
		if ref.Item > len(f.Content.Improvements) {
			return out, outOfRange("speaking feedback", f.ID, ref.Item, len(f.Content.Improvements))
		}
		k := f.Content.Improvements[ref.Item-1]
		if k.Grounding == domain.WritingNotFound {
			return out, fmt.Errorf("%w: improvement %d quotes words that are not in that transcript", domain.ErrValidation, ref.Item)
		}
		tr, err := r.speaking.GetTranscript(ctx, f.TranscriptID)
		if err != nil {
			return out, err
		}
		take, err := r.speaking.GetTake(ctx, tr.TakeID)
		if err != nil {
			return out, err
		}
		ex, err := r.speaking.GetExercise(ctx, take.ExerciseID)
		if err != nil {
			return out, err
		}
		out.Title, out.Prompt, out.Category, out.Quote, out.Reference = ex.Title, ex.Situation, k.Category, k.Quote, k.Suggestion
		out.ExplanationEN, out.ExplanationZH, out.HintEN, out.HintZH = k.ReasonEN, k.ReasonZH, k.HintEN, k.HintZH
		out.Link = domain.SourceLink{SpeakingExerciseID: ex.ID, SpeakingTakeID: take.ID, SpeakingTakeNumber: take.Number,
			SpeakingTranscriptID: tr.ID, SpeakingTranscriptVersion: tr.Version, SpeakingFeedbackID: f.ID}
	default:
		return out, fmt.Errorf("%w: unknown source type", domain.ErrValidation)
	}
	return out, nil
}

type notebookEntryReader interface {
	GetByID(ctx context.Context, id int64) (*domain.Entry, error)
}

type notebookLibrary interface {
	Search(ctx context.Context, q LibrarySearchQuery) (*LibrarySearchReport, error)
	GetConcept(ctx context.Context, conceptID int64) (*LibraryConceptDetail, error)
}

// MistakeNotebookService lists notebook items, records retry marks, and serves
// the Grammar / Vocabulary views.
type MistakeNotebookService struct {
	repo     domain.NotebookRepository
	sources  domain.SourceResolver
	entries  notebookEntryReader
	library  notebookLibrary
	now      func() time.Time
	maxClass int
}

// NewMistakeNotebookService builds the service. library may be nil (no kind views).
func NewMistakeNotebookService(repo domain.NotebookRepository, sources domain.SourceResolver, entries notebookEntryReader, library notebookLibrary) *MistakeNotebookService {
	return &MistakeNotebookService{repo: repo, sources: sources, entries: entries, library: library, now: func() time.Time { return time.Now().UTC() }, maxClass: 500}
}

// NotebookItem is one record with its stored source and current retry mark.
type NotebookItem struct {
	Source   domain.LearningCaptureSource
	Resolved domain.ResolvedSource
	Entry    domain.Entry
	Mark     *domain.RetryMark // nil: never marked
}

func (s *MistakeNotebookService) item(ctx context.Context, src domain.LearningCaptureSource, marks map[int64]domain.RetryMark) (NotebookItem, error) {
	res, err := s.sources.ResolveSource(ctx, src.Ref)
	if err != nil {
		return NotebookItem{}, fmt.Errorf("resolve source of record %d: %w", src.EntryID, err)
	}
	e, err := s.entries.GetByID(ctx, src.EntryID)
	if err != nil {
		return NotebookItem{}, err
	}
	it := NotebookItem{Source: src, Resolved: res, Entry: *e}
	if m, ok := marks[src.EntryID]; ok {
		it.Mark = &m
	}
	return it, nil
}

// ListItems returns notebook items, newest first, optionally only one skill's
// or only those marked for retry.
func (s *MistakeNotebookService) ListItems(ctx context.Context, skill string, markedOnly bool) ([]NotebookItem, error) {
	if skill != "" && !domain.ValidSkill(skill) {
		return nil, fmt.Errorf("%w: skill must be listening, reading, writing or speaking", domain.ErrValidation)
	}
	srcs, err := s.repo.ListSources(ctx)
	if err != nil {
		return nil, err
	}
	marks, err := s.repo.CurrentMarks(ctx)
	if err != nil {
		return nil, err
	}
	out := []NotebookItem{}
	for _, src := range srcs {
		if skill != "" && domain.SourceSkill(src.Ref.Type) != skill {
			continue
		}
		if markedOnly && !marks[src.EntryID].Marked {
			continue
		}
		it, err := s.item(ctx, src, marks)
		if err != nil {
			return nil, err
		}
		out = append(out, it)
	}
	return out, nil
}

// EntrySource returns the notebook item for one record, or ErrNotFound when
// the record has no structured source (saved without one, or before source
// links existed): it is never inferred.
func (s *MistakeNotebookService) EntrySource(ctx context.Context, entryID int64) (*NotebookItem, error) {
	src, err := s.repo.GetSourceByEntry(ctx, entryID)
	if err != nil {
		return nil, err
	}
	marks, err := s.repo.CurrentMarks(ctx)
	if err != nil {
		return nil, err
	}
	it, err := s.item(ctx, src, marks)
	if err != nil {
		return nil, err
	}
	return &it, nil
}

// SetRetry records the learner's explicit decision for one notebook record.
func (s *MistakeNotebookService) SetRetry(ctx context.Context, entryID int64, marked bool) (*NotebookItem, bool, error) {
	_, changed, err := s.repo.SetMark(ctx, entryID, marked, s.now())
	if err != nil {
		return nil, false, err
	}
	it, err := s.EntrySource(ctx, entryID)
	return it, changed, err
}

// ConceptKindRow is one Concept in a Grammar / Vocabulary / Unclassified view.
type ConceptKindRow struct {
	Concept             domain.KnowledgeConcept
	Class               string
	Reason              string
	Kinds               []domain.KnowledgeKind // distinct kinds of the supporting units, sorted
	SupportingUnitCount int
	MatchTier           string
}

// ConceptKindView is one view's rows.
type ConceptKindView struct {
	Kind       string
	Query      string
	Tokens     []string
	Classified int  // active Concepts classified for this query
	Truncated  bool // more active Concepts matched than were classified
	Rows       []ConceptKindRow
}

// ErrNotebookKindViewsUnavailable is returned when no Knowledge Library is wired.
var ErrNotebookKindViewsUnavailable = errors.New("the Grammar and Vocabulary views need the Knowledge Library")

// ConceptsByKind classifies the active Concepts the Knowledge Library search
// finds for text (empty: all) with concept_kind_view_v1 and returns those of
// the requested class. Search tokens, ordering and support are the library's.
func (s *MistakeNotebookService) ConceptsByKind(ctx context.Context, kind, text string) (*ConceptKindView, error) {
	if kind != domain.KindViewGrammar && kind != domain.KindViewVocabulary && kind != domain.KindViewUnclassified {
		return nil, fmt.Errorf("%w: kind must be grammar, vocabulary or unclassified", domain.ErrValidation)
	}
	if s.library == nil {
		return nil, ErrNotebookKindViewsUnavailable
	}
	q, err := ParseLibrarySearchQuery(text, string(domain.ConceptActive), nil)
	if err != nil {
		return nil, err
	}
	q.Limit = s.maxClass
	report, err := s.library.Search(ctx, q)
	if err != nil {
		return nil, err
	}
	view := &ConceptKindView{Kind: kind, Query: report.Query, Tokens: report.Tokens, Classified: len(report.Results), Truncated: report.Truncated, Rows: []ConceptKindRow{}}
	for _, r := range report.Results {
		d, err := s.library.GetConcept(ctx, r.Concept.ID)
		if err != nil {
			return nil, err
		}
		seen := map[domain.KnowledgeKind]bool{}
		kinds := []domain.KnowledgeKind{}
		all := make([]domain.KnowledgeKind, 0, len(d.SupportingUnits))
		for _, u := range d.SupportingUnits {
			all = append(all, u.Unit.Kind)
			if !seen[u.Unit.Kind] {
				seen[u.Unit.Kind] = true
				kinds = append(kinds, u.Unit.Kind)
			}
		}
		sort.Slice(kinds, func(i, j int) bool { return kinds[i] < kinds[j] })
		class, reason := domain.ClassifyConceptKinds(all)
		if class != kind {
			continue
		}
		view.Rows = append(view.Rows, ConceptKindRow{Concept: r.Concept, Class: class, Reason: reason, Kinds: kinds, SupportingUnitCount: len(d.SupportingUnits), MatchTier: r.MatchTier})
	}
	return view, nil
}
