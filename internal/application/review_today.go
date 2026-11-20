package application

import (
	"fmt"
	"sort"
	"time"

	"french-learning-app/internal/domain"
)

// Review Today: one private, read-only queue of what the learner can act on
// now, drawn from two existing sources and nothing else:
//   - Speaking practice steps (GET /speaking/practice) of started exercises
//     whose latest take is not complete (prompts not started are not due);
//   - Mistake Notebook items the learner explicitly marked for retry.
// Nothing is stored or scheduled: the queue is derived on every read, so a
// completed action (a take completed, a retry mark removed) leaves it at once.

// ReviewTodayVersion names the read contract.
const ReviewTodayVersion = "review_today_v1"

// Review Today sources and the notebook reason code.
const (
	ReviewSourceSpeaking = "speaking"
	ReviewSourceNotebook = "notebook"
	// ReviewRetryMarked: the learner marked a saved mistake for retry.
	ReviewRetryMarked = "retry_marked"
)

// ReviewItem is one actionable item. Reason is an explicit code: a Speaking
// queue reason (domain.SpeakingQueue*) or ReviewRetryMarked.
type ReviewItem struct {
	Key      string // stable: "speaking:exercise:<id>" or "notebook:entry:<id>"
	Source   string
	Reason   string
	Priority int
	Since    time.Time
	Speaking *SpeakingQueueItem // Source speaking
	Notebook *NotebookItem      // Source notebook
}

// ReviewHistory counts saved work that is not in the queue, so the page can
// link to it (Mistake Notebook, Speaking) and tell "nothing yet" from "all done".
type ReviewHistory struct {
	NotebookItems     int
	SpeakingExercises int
	SpeakingTakes     int
}

// ReviewToday is the derived queue.
type ReviewToday struct {
	Items   []ReviewItem
	History ReviewHistory
	Now     time.Time
}

// reviewRetryPriority places a marked retry with "answer again": both are
// practising again something already done once.
var reviewRetryPriority = domain.SpeakingQueuePriority(domain.SpeakingQueueAnswerAgain)

// BuildReviewToday merges the two sources. practice may be nil (Speaking
// unavailable); notebook holds every notebook item (marked or not). Order:
// priority (most urgent first), then the item waiting longest, then source,
// then key, so equal priorities always come out in the same order.
func BuildReviewToday(practice *SpeakingPractice, notebook []NotebookItem, now time.Time) ReviewToday {
	out := ReviewToday{Items: []ReviewItem{}, Now: now}
	if practice != nil {
		out.History.SpeakingExercises = practice.Summary.Started
		out.History.SpeakingTakes = practice.Summary.Takes
		for i := range practice.Queue {
			q := practice.Queue[i]
			if q.ExerciseID == nil || q.Reason == domain.SpeakingQueueNotStarted {
				continue // a prompt not started is not due
			}
			since := now
			if q.Since != nil {
				since = *q.Since
			}
			out.Items = append(out.Items, ReviewItem{Key: fmt.Sprintf("speaking:exercise:%d", *q.ExerciseID), Source: ReviewSourceSpeaking,
				Reason: q.Reason, Priority: domain.SpeakingQueuePriority(q.Reason), Since: since, Speaking: &q})
		}
	}
	out.History.NotebookItems = len(notebook)
	for i := range notebook {
		it := notebook[i]
		if it.Mark == nil || !it.Mark.Marked {
			continue // saved history, not due: the Mistake Notebook keeps it
		}
		out.Items = append(out.Items, ReviewItem{Key: fmt.Sprintf("notebook:entry:%d", it.Source.EntryID), Source: ReviewSourceNotebook,
			Reason: ReviewRetryMarked, Priority: reviewRetryPriority, Since: it.Mark.At, Notebook: &it})
	}
	sort.SliceStable(out.Items, func(i, j int) bool {
		a, b := out.Items[i], out.Items[j]
		if a.Priority != b.Priority {
			return a.Priority < b.Priority
		}
		if !a.Since.Equal(b.Since) {
			return a.Since.Before(b.Since)
		}
		if a.Source != b.Source {
			return a.Source < b.Source
		}
		return a.Key < b.Key
	})
	return out
}
