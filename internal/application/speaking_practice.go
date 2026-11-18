package application

import (
	"context"
	"sort"
	"time"

	"french-learning-app/internal/domain"
)

// Speaking practice overview, attempt states and export. Everything here is
// derived on read from the stored Speaking records: nothing is written, no
// provider is called, and a state can never disagree with its records.

// SpeakingAttempt is one take and what its records say about it.
type SpeakingAttempt struct {
	Take             domain.SpeakingTake
	State            string
	Versions         int                        // confirmed transcript versions
	LatestTranscript *domain.SpeakingTranscript // the latest confirmed version
	// Feedback is the report that decides the state: the newest completed one
	// on the latest version, else the newest one on it (failed).
	Feedback     *domain.SpeakingFeedback
	Improvements int // of a completed Feedback
	ActivityAt   time.Time
}

// attempt derives one take's state. Only the latest confirmed version counts
// for feedback: a report on an earlier version is about other words.
func (v *SpeakingExerciseView) attempt(t domain.SpeakingTake) SpeakingAttempt {
	a := SpeakingAttempt{Take: t, ActivityAt: t.CreatedAt}
	bump := func(at time.Time) {
		if at.After(a.ActivityAt) {
			a.ActivityAt = at
		}
	}
	mine := map[int64]bool{}
	for i := range v.Transcripts {
		if tr := v.Transcripts[i]; tr.TakeID == t.ID {
			a.Versions++
			a.LatestTranscript = &v.Transcripts[i]
			mine[tr.ID] = true
			bump(tr.CreatedAt)
		}
	}
	var lastTranscription *domain.SpeakingTranscription
	machine := false
	for i := range v.Transcriptions {
		if x := v.Transcriptions[i]; x.TakeID == t.ID {
			if lastTranscription == nil {
				lastTranscription = &v.Transcriptions[i]
			}
			machine = machine || x.Status == domain.ListeningExerciseCompleted
			bump(x.CreatedAt)
		}
	}
	for _, f := range v.Feedback {
		if mine[f.TranscriptID] {
			bump(f.CreatedAt)
		}
	}
	if a.LatestTranscript == nil {
		trState := ""
		for _, r := range v.TranscriptionRequests { // newest first
			if r.TakeID == t.ID {
				trState = r.State(v.Now)
				break
			}
		}
		switch {
		case trState == domain.ListeningStateInProgress:
			a.State = domain.SpeakingTranscribing
		case trState == domain.ListeningOutcomeUnknown:
			a.State = domain.SpeakingTranscriptionUnknown
		case machine:
			a.State = domain.SpeakingTranscriptToConfirm
		case lastTranscription != nil && lastTranscription.Status == domain.ListeningExerciseFailed:
			a.State = domain.SpeakingTranscriptionFailed
		default:
			a.State = domain.SpeakingAwaitingTranscript
		}
		return a
	}
	latest := a.LatestTranscript.ID
	fbState := ""
	for _, r := range v.FeedbackRequests { // newest first
		if r.TranscriptID == latest {
			fbState = r.State(v.Now)
			break
		}
	}
	var newest, completed *domain.SpeakingFeedback
	for i := range v.Feedback { // newest first
		if f := v.Feedback[i]; f.TranscriptID == latest {
			if newest == nil {
				newest = &v.Feedback[i]
			}
			if completed == nil && f.Status == domain.ListeningExerciseCompleted && f.Content != nil {
				completed = &v.Feedback[i]
			}
		}
	}
	switch {
	case fbState == domain.ListeningStateInProgress:
		a.State = domain.SpeakingFeedbackInProgress
	case completed != nil:
		a.State, a.Feedback, a.Improvements = domain.SpeakingFeedbackReady, completed, len(completed.Content.Improvements)
	case fbState == domain.ListeningOutcomeUnknown:
		a.State = domain.SpeakingFeedbackUnknown
	case newest != nil:
		a.State, a.Feedback = domain.SpeakingFeedbackFailed, newest
	default:
		a.State = domain.SpeakingAwaitingFeedback
	}
	return a
}

// Attempts lists every take's attempt, by take number.
func (v *SpeakingExerciseView) Attempts() []SpeakingAttempt {
	out := make([]SpeakingAttempt, 0, len(v.Takes))
	for _, t := range v.Takes {
		out = append(out, v.attempt(t))
	}
	return out
}

// SpeakingPracticeExercise is one started exercise in the overview.
type SpeakingPracticeExercise struct {
	Exercise     domain.SpeakingExercise
	PackStatus   string
	Takes        int
	Completed    int // attempts whose latest version has completed feedback
	Latest       *SpeakingAttempt
	LastActivity time.Time
}

// SpeakingQueueItem is one suggested next step and why.
type SpeakingQueueItem struct {
	Reason       string
	PromptID     string
	Title        string
	ExerciseID   *int64 // nil for a prompt not started yet
	TakeID       *int64
	TakeNumber   int
	State        string
	Improvements int
	Since        *time.Time
}

// SpeakingPracticeSummary counts attempts by what they actually reached. Only
// an attempt with completed feedback on its latest confirmed version counts as
// completed; pending, failed and unknown outcomes are counted apart, and the
// counts always add up to Takes.
type SpeakingPracticeSummary struct {
	Prompts            int // in the embedded set
	Started            int // exercises
	Takes              int
	Completed          int
	ExercisesCompleted int
	AwaitingTranscript int // awaiting_transcript + transcript_to_confirm
	AwaitingFeedback   int
	InProgress         int // transcribing + feedback_in_progress
	Failed             int // transcription_failed + feedback_failed
	Unknown            int // transcription_unknown + feedback_unknown
	LastCompletedAt    *time.Time
}

// SpeakingPractice is the read-only practice overview.
type SpeakingPractice struct {
	Summary   SpeakingPracticeSummary
	Queue     []SpeakingQueueItem
	Exercises []SpeakingPracticeExercise
	Now       time.Time
}

// queueReason maps an exercise's latest attempt to a next step; "" means
// nothing to do now (in progress, or complete with nothing to improve).
func queueReason(a *SpeakingAttempt, feedbackEnabled bool) string {
	if a == nil {
		return domain.SpeakingQueueFirstTake
	}
	switch a.State {
	case domain.SpeakingTranscriptionUnknown, domain.SpeakingFeedbackUnknown:
		return domain.SpeakingQueueCheckUnknown
	case domain.SpeakingTranscriptionFailed, domain.SpeakingFeedbackFailed:
		return domain.SpeakingQueueRequestFailed
	case domain.SpeakingTranscriptToConfirm:
		return domain.SpeakingQueueConfirmTranscript
	case domain.SpeakingAwaitingTranscript:
		return domain.SpeakingQueueAddTranscript
	case domain.SpeakingAwaitingFeedback:
		if feedbackEnabled {
			return domain.SpeakingQueueRequestFeedback
		}
	case domain.SpeakingFeedbackReady:
		if a.Improvements > 0 {
			return domain.SpeakingQueueAnswerAgain
		}
	}
	return ""
}

// Practice builds the overview: per-exercise progress from every take, one
// queue item per exercise from its latest take (an earlier, abandoned take is
// not a task), and the prompts not started yet, last.
func (s *SpeakingService) Practice(ctx context.Context) (*SpeakingPractice, error) {
	views, err := s.allExercises(ctx)
	if err != nil {
		return nil, err
	}
	_, generator := s.Providers()
	p := &SpeakingPractice{Now: s.now(), Queue: []SpeakingQueueItem{}, Exercises: []SpeakingPracticeExercise{}}
	sum := &p.Summary
	sum.Prompts, sum.Started = len(s.prompts.Prompts), len(views)
	started := map[string]bool{}
	for _, v := range views {
		started[v.Exercise.PromptID] = true
		row := SpeakingPracticeExercise{Exercise: v.Exercise, PackStatus: v.PackStatus, Takes: len(v.Takes), LastActivity: v.Exercise.CreatedAt}
		for _, a := range v.Attempts() {
			a := a
			row.Latest = &a
			if a.ActivityAt.After(row.LastActivity) {
				row.LastActivity = a.ActivityAt
			}
			sum.Takes++
			switch a.State {
			case domain.SpeakingFeedbackReady:
				row.Completed++
				sum.Completed++
				if at := a.Feedback.CreatedAt; sum.LastCompletedAt == nil || at.After(*sum.LastCompletedAt) {
					sum.LastCompletedAt = &at
				}
			case domain.SpeakingAwaitingTranscript, domain.SpeakingTranscriptToConfirm:
				sum.AwaitingTranscript++
			case domain.SpeakingAwaitingFeedback:
				sum.AwaitingFeedback++
			case domain.SpeakingTranscribing, domain.SpeakingFeedbackInProgress:
				sum.InProgress++
			case domain.SpeakingTranscriptionFailed, domain.SpeakingFeedbackFailed:
				sum.Failed++
			case domain.SpeakingTranscriptionUnknown, domain.SpeakingFeedbackUnknown:
				sum.Unknown++
			}
		}
		if row.Completed > 0 {
			sum.ExercisesCompleted++
		}
		p.Exercises = append(p.Exercises, row)
		if reason := queueReason(row.Latest, generator != ""); reason != "" {
			id := v.Exercise.ID
			item := SpeakingQueueItem{Reason: reason, PromptID: v.Exercise.PromptID, Title: v.Exercise.Title, ExerciseID: &id}
			since := row.LastActivity
			item.Since = &since
			if a := row.Latest; a != nil {
				takeID := a.Take.ID
				item.TakeID, item.TakeNumber, item.State, item.Improvements = &takeID, a.Take.Number, a.State, a.Improvements
			}
			p.Queue = append(p.Queue, item)
		}
	}
	sort.SliceStable(p.Queue, func(i, j int) bool {
		a, b := p.Queue[i], p.Queue[j]
		if pa, pb := domain.SpeakingQueuePriority(a.Reason), domain.SpeakingQueuePriority(b.Reason); pa != pb {
			return pa < pb
		}
		if !a.Since.Equal(*b.Since) {
			return a.Since.After(*b.Since) // the most recent work first
		}
		return *a.ExerciseID < *b.ExerciseID
	})
	for _, pr := range s.prompts.Prompts { // set order
		if !started[pr.ID] {
			p.Queue = append(p.Queue, SpeakingQueueItem{Reason: domain.SpeakingQueueNotStarted, PromptID: pr.ID, Title: pr.Title})
		}
	}
	sort.SliceStable(p.Exercises, func(i, j int) bool {
		if a, b := p.Exercises[i].LastActivity, p.Exercises[j].LastActivity; !a.Equal(b) {
			return a.After(b)
		}
		return p.Exercises[i].Exercise.ID > p.Exercises[j].Exercise.ID
	})
	return p, nil
}

// SpeakingAttemptExport is one exported attempt with everything stored about
// it. There is never any audio: only its metadata was ever stored.
type SpeakingAttemptExport struct {
	Exercise       domain.SpeakingExercise
	PackStatus     string
	Attempt        SpeakingAttempt
	Transcriptions []domain.SpeakingTranscription // oldest first
	Transcripts    []domain.SpeakingTranscript    // by version
	Feedback       []domain.SpeakingFeedback      // oldest first, any version of the take
}

// Export lists every attempt, by exercise ID then take number.
func (s *SpeakingService) Export(ctx context.Context) ([]SpeakingAttemptExport, error) {
	views, err := s.allExercises(ctx)
	if err != nil {
		return nil, err
	}
	sort.Slice(views, func(i, j int) bool { return views[i].Exercise.ID < views[j].Exercise.ID })
	out := []SpeakingAttemptExport{}
	for _, v := range views {
		for _, a := range v.Attempts() {
			row := SpeakingAttemptExport{Exercise: v.Exercise, PackStatus: v.PackStatus, Attempt: a,
				Transcriptions: []domain.SpeakingTranscription{}, Transcripts: []domain.SpeakingTranscript{}, Feedback: []domain.SpeakingFeedback{}}
			mine := map[int64]bool{}
			for _, tr := range v.Transcripts {
				if tr.TakeID == a.Take.ID {
					row.Transcripts = append(row.Transcripts, tr)
					mine[tr.ID] = true
				}
			}
			for i := len(v.Transcriptions) - 1; i >= 0; i-- {
				if x := v.Transcriptions[i]; x.TakeID == a.Take.ID {
					row.Transcriptions = append(row.Transcriptions, x)
				}
			}
			for i := len(v.Feedback) - 1; i >= 0; i-- {
				if f := v.Feedback[i]; mine[f.TranscriptID] {
					row.Feedback = append(row.Feedback, f)
				}
			}
			out = append(out, row)
		}
	}
	return out, nil
}

// allExercises reads every exercise view; the set bounds their number (one
// exercise per prompt) and each holds at most MaxSpeakingTakes takes.
func (s *SpeakingService) allExercises(ctx context.Context) ([]*SpeakingExerciseView, error) {
	es, err := s.repo.ListExercises(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]*SpeakingExerciseView, 0, len(es))
	for _, e := range es {
		v, err := s.GetExercise(ctx, e.ID)
		if err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, nil
}
