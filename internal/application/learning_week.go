package application

import (
	"context"
	"fmt"
	"sort"
	"time"

	"french-learning-app/internal/domain"
)

// Learning week (learning_week_v1, private workbench): a small summary of the
// last seven local days, derived on every read from records that already
// exist. Nothing is stored, scored or scheduled, and no provider is called.
//
// Event kinds, each traceable to one stored row:
//   - production: completed production practice. A Speaking take with a
//     confirmed transcript (at its first confirmation), or a Writing draft
//     version 1.
//   - own_correction: the learner's own correction. A Speaking transcript
//     version the learner corrected, or a Writing draft version 2+.
//   - provider_feedback: a completed feedback report (Speaking or Writing),
//     with the generator that wrote it.
//   - reviewed: reviewed material. A Mistake Notebook record saved from a
//     revealed answer, or a record whose current retry state is "done"
//     (unmarked).
//
// An event counts once per (kind, key, local day): a repeated or replayed
// completion of the same item on the same day never inflates a total.

const LearningWeekVersion = "learning_week_v1"

// Event kinds.
const (
	EventProduction       = "production"
	EventOwnCorrection    = "own_correction"
	EventProviderFeedback = "provider_feedback"
	EventReviewed         = "reviewed"
)

// LearningWeekMinForShares is the smallest number of counted actions for
// which the week shows a share as a percentage; below it, only counts.
const LearningWeekMinForShares = 20

// LearningEvent is one stored fact.
type LearningEvent struct {
	Kind     string
	Key      string // identity of the item, e.g. speaking:take:12
	Exercise string // the exercise it belongs to, e.g. speaking:exercise:3 ("" for reviewed)
	At       time.Time
	// For own corrections: where to reopen it with its source context.
	Correction *LearningCorrection
}

// LearningCorrection is a learner's own correction with its source context.
type LearningCorrection struct {
	Skill        string // speaking or writing
	Title        string
	ExerciseID   int64 // speaking exercise
	TakeID       int64
	TakeNumber   int
	TaskID       int64 // writing task
	Version      int   // transcript or draft version
	PriorVersion int   // the version it corrects (0: the machine transcript)
	Day          string
	At           time.Time
}

// LearningDay is one local day's counts.
type LearningDay struct {
	Day              string
	Production       int
	Reviewed         int
	OwnCorrections   int
	ProviderFeedback int
}

// LearningWeek is the summary.
type LearningWeek struct {
	Zone              string
	From, To          string // first and last local day
	Days              []LearningDay
	Production        int
	Reviewed          int
	OwnCorrections    int
	ProviderFeedback  int
	DistinctExercises int
	ActiveDays        int
	Duplicates        int // events not counted again (same kind, key and day)
	Sparse            bool
	ProductionShare   *int // percent of counted actions that were production; nil when sparse
	Corrections       []LearningCorrection
}

// BuildLearningWeek counts events in the seven local days ending today
// (now in loc). It is pure: the same events, clock and zone give the same
// week.
func BuildLearningWeek(events []LearningEvent, now time.Time, loc *time.Location) LearningWeek {
	today := localMidnight(now, loc)
	start := addDays(today, -6, loc)
	w := LearningWeek{Zone: loc.String(), From: LocalDay(start, loc), To: LocalDay(today, loc), Corrections: []LearningCorrection{}}
	index := map[string]int{}
	for d := 0; d < 7; d++ {
		day := LocalDay(addDays(start, d, loc), loc)
		index[day] = d
		w.Days = append(w.Days, LearningDay{Day: day})
	}
	sorted := append([]LearningEvent(nil), events...)
	sort.SliceStable(sorted, func(i, j int) bool { return sorted[i].At.Before(sorted[j].At) })
	seen := map[string]bool{}
	exercises := map[string]bool{}
	for _, e := range sorted {
		day := LocalDay(e.At, loc)
		d, ok := index[day]
		if !ok || e.At.IsZero() {
			continue
		}
		id := e.Kind + "|" + e.Key + "|" + day
		if seen[id] {
			w.Duplicates++
			continue
		}
		seen[id] = true
		switch e.Kind {
		case EventProduction:
			w.Days[d].Production++
			w.Production++
			if e.Exercise != "" {
				exercises[e.Exercise] = true
			}
		case EventReviewed:
			w.Days[d].Reviewed++
			w.Reviewed++
		case EventOwnCorrection:
			w.Days[d].OwnCorrections++
			w.OwnCorrections++
			if e.Correction != nil {
				c := *e.Correction
				c.Day, c.At = day, e.At
				w.Corrections = append(w.Corrections, c)
			}
		case EventProviderFeedback:
			w.Days[d].ProviderFeedback++
			w.ProviderFeedback++
		}
	}
	for _, d := range w.Days {
		if d.Production+d.Reviewed+d.OwnCorrections+d.ProviderFeedback > 0 {
			w.ActiveDays++
		}
	}
	w.DistinctExercises = len(exercises)
	actions := w.Production + w.Reviewed
	w.Sparse = actions < LearningWeekMinForShares
	if !w.Sparse {
		share := (w.Production*100 + actions/2) / actions
		w.ProductionShare = &share
	}
	// Newest correction first.
	sort.SliceStable(w.Corrections, func(i, j int) bool { return w.Corrections[i].At.After(w.Corrections[j].At) })
	return w
}

type weekSpeakingReader interface {
	ListExercises(ctx context.Context) ([]domain.SpeakingExercise, error)
	ListTakes(ctx context.Context, exerciseID int64) ([]domain.SpeakingTake, error)
	ListTranscripts(ctx context.Context, exerciseID int64) ([]domain.SpeakingTranscript, error)
	ListFeedback(ctx context.Context, exerciseID int64) ([]domain.SpeakingFeedback, error)
}

type weekWritingReader interface {
	ListTasks(ctx context.Context) ([]domain.WritingTask, error)
	ListDrafts(ctx context.Context, taskID int64) ([]domain.WritingDraft, error)
	ListFeedback(ctx context.Context, taskID int64) ([]domain.WritingFeedback, error)
}

type weekNotebookReader interface {
	ListSources(ctx context.Context) ([]domain.LearningCaptureSource, error)
	CurrentMarks(ctx context.Context) (map[int64]domain.RetryMark, error)
}

// LearningWeekService gathers the events from the stored records. Any reader
// may be nil (that skill is then absent from the week, and Sources says so).
type LearningWeekService struct {
	speaking weekSpeakingReader
	writing  weekWritingReader
	notebook weekNotebookReader
	now      func() time.Time
}

// NewLearningWeekService builds the service.
func NewLearningWeekService(s weekSpeakingReader, w weekWritingReader, n weekNotebookReader) *LearningWeekService {
	return &LearningWeekService{speaking: s, writing: w, notebook: n, now: func() time.Time { return time.Now().UTC() }}
}

// Sources reports which skills feed the week.
func (s *LearningWeekService) Sources() map[string]bool {
	return map[string]bool{"speaking": s.speaking != nil, "writing": s.writing != nil, "notebook": s.notebook != nil}
}

// Now is the service clock.
func (s *LearningWeekService) Now() time.Time { return s.now() }

// Events reads every event from the stored records.
func (s *LearningWeekService) Events(ctx context.Context) ([]LearningEvent, error) {
	var out []LearningEvent
	if s.speaking != nil {
		exs, err := s.speaking.ListExercises(ctx)
		if err != nil {
			return nil, err
		}
		for _, ex := range exs {
			takes, err := s.speaking.ListTakes(ctx, ex.ID)
			if err != nil {
				return nil, err
			}
			transcripts, err := s.speaking.ListTranscripts(ctx, ex.ID)
			if err != nil {
				return nil, err
			}
			feedback, err := s.speaking.ListFeedback(ctx, ex.ID)
			if err != nil {
				return nil, err
			}
			number := map[int64]int{}
			for _, k := range takes {
				number[k.ID] = k.Number
			}
			exKey := fmt.Sprintf("speaking:exercise:%d", ex.ID)
			first := map[int64]bool{}
			for _, tr := range transcripts {
				if !first[tr.TakeID] {
					first[tr.TakeID] = true
					out = append(out, LearningEvent{Kind: EventProduction, Key: fmt.Sprintf("speaking:take:%d", tr.TakeID), Exercise: exKey, At: tr.CreatedAt})
				}
				if tr.Origin == domain.SpeakingTranscriptCorrected {
					prior := tr.Version - 1
					out = append(out, LearningEvent{Kind: EventOwnCorrection, Key: fmt.Sprintf("speaking:transcript:%d", tr.ID), Exercise: exKey, At: tr.CreatedAt,
						Correction: &LearningCorrection{Skill: "speaking", Title: ex.Title, ExerciseID: ex.ID, TakeID: tr.TakeID, TakeNumber: number[tr.TakeID], Version: tr.Version, PriorVersion: prior}})
				}
			}
			for _, f := range feedback {
				if f.Status == domain.ListeningExerciseCompleted {
					out = append(out, LearningEvent{Kind: EventProviderFeedback, Key: fmt.Sprintf("speaking:feedback:%d", f.ID), Exercise: exKey, At: f.CreatedAt})
				}
			}
		}
	}
	if s.writing != nil {
		tasks, err := s.writing.ListTasks(ctx)
		if err != nil {
			return nil, err
		}
		for _, task := range tasks {
			drafts, err := s.writing.ListDrafts(ctx, task.ID)
			if err != nil {
				return nil, err
			}
			feedback, err := s.writing.ListFeedback(ctx, task.ID)
			if err != nil {
				return nil, err
			}
			exKey := fmt.Sprintf("writing:task:%d", task.ID)
			for _, d := range drafts {
				key := fmt.Sprintf("writing:draft:%d", d.ID)
				if d.Version == 1 {
					out = append(out, LearningEvent{Kind: EventProduction, Key: key, Exercise: exKey, At: d.CreatedAt})
				} else {
					out = append(out, LearningEvent{Kind: EventOwnCorrection, Key: key, Exercise: exKey, At: d.CreatedAt,
						Correction: &LearningCorrection{Skill: "writing", Title: task.Title, TaskID: task.ID, Version: d.Version, PriorVersion: d.Version - 1}})
				}
			}
			for _, f := range feedback {
				if f.Status == domain.ListeningExerciseCompleted {
					out = append(out, LearningEvent{Kind: EventProviderFeedback, Key: fmt.Sprintf("writing:feedback:%d", f.ID), Exercise: exKey, At: f.CreatedAt})
				}
			}
		}
	}
	if s.notebook != nil {
		srcs, err := s.notebook.ListSources(ctx)
		if err != nil {
			return nil, err
		}
		for _, src := range srcs {
			out = append(out, LearningEvent{Kind: EventReviewed, Key: fmt.Sprintf("notebook:saved:%d", src.EntryID), At: src.CreatedAt})
		}
		marks, err := s.notebook.CurrentMarks(ctx)
		if err != nil {
			return nil, err
		}
		for id, m := range marks {
			if !m.Marked {
				out = append(out, LearningEvent{Kind: EventReviewed, Key: fmt.Sprintf("notebook:done:%d", id), At: m.At})
			}
		}
	}
	return out, nil
}

// Week is the summary for the learner's zone.
func (s *LearningWeekService) Week(ctx context.Context, loc *time.Location) (LearningWeek, error) {
	events, err := s.Events(ctx)
	if err != nil {
		return LearningWeek{}, err
	}
	return BuildLearningWeek(events, s.now(), loc), nil
}
