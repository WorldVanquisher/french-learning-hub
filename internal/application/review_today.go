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
	// Also lists other marked notebook records for the same question (the same
	// lesson and item, saved from another revision): one queue item stands for
	// all of them, so the learner never sees two equivalent actions, and
	// "Done for today" clears every one (R4-WB-008).
	Also []int64
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
	return BuildReviewTodayCounted(practice, notebook, len(notebook), now)
}

// BuildReviewTodayCounted is BuildReviewToday when the notebook items given
// are only some of the records (MistakeNotebookService.ReviewItems: the marked
// ones) and notebookTotal counts them all. Unmarked items are skipped either
// way, so the queue is the same.
func BuildReviewTodayCounted(practice *SpeakingPractice, notebook []NotebookItem, notebookTotal int, now time.Time) ReviewToday {
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
	out.History.NotebookItems = notebookTotal
	for i := range notebook {
		it := notebook[i]
		if it.Mark == nil || !it.Mark.Marked {
			continue // saved history, not due: the Mistake Notebook keeps it
		}
		out.Items = append(out.Items, ReviewItem{Key: fmt.Sprintf("notebook:entry:%d", it.Source.EntryID), Source: ReviewSourceNotebook,
			Reason: ReviewRetryMarked, Priority: reviewRetryPriority, Since: it.Mark.At, Notebook: &it})
	}
	out.Items = groupEquivalentNotebookItems(out.Items)
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

// sameQuestion is the identity of a workbook question across revisions: the
// lesson and the item position (pack corrections keep item positions). Only
// listening and reading items have revisions; others never group.
func sameQuestion(it *NotebookItem) (string, bool) {
	l := it.Resolved.Link
	switch {
	case it.Source.Ref.Type == domain.SourceListeningItem && l.ListeningMaterialID != 0:
		return fmt.Sprintf("listening:%d:%d", l.ListeningMaterialID, it.Source.Ref.Item), true
	case it.Source.Ref.Type == domain.SourceReadingItem && l.ReadingLessonID != 0:
		return fmt.Sprintf("reading:%d:%d", l.ReadingLessonID, it.Source.Ref.Item), true
	}
	return "", false
}

func sourceVersion(it *NotebookItem) int {
	return max(it.Resolved.Link.ListeningTranscriptVersion, it.Resolved.Link.ReadingPassageVersion)
}

// groupEquivalentNotebookItems keeps one notebook item per question: the one
// saved from the newest source version (then the newest record), so "Open the
// lesson" opens the current wording. It waits since the earliest mark of the
// group; the others are listed in Also. Items without a question identity
// pass through unchanged.
func groupEquivalentNotebookItems(items []ReviewItem) []ReviewItem {
	lead := map[string]int{}
	out := make([]ReviewItem, 0, len(items))
	for _, it := range items {
		if it.Notebook == nil {
			out = append(out, it)
			continue
		}
		k, ok := sameQuestion(it.Notebook)
		if !ok || it.Notebook.SourceState != domain.SourceResolved {
			out = append(out, it)
			continue
		}
		i, seen := lead[k]
		if !seen {
			lead[k] = len(out)
			out = append(out, it)
			continue
		}
		cur := &out[i]
		earliest := cur.Since
		if it.Since.Before(earliest) {
			earliest = it.Since
		}
		newer := sourceVersion(it.Notebook) > sourceVersion(cur.Notebook) ||
			(sourceVersion(it.Notebook) == sourceVersion(cur.Notebook) && it.Notebook.Source.EntryID > cur.Notebook.Source.EntryID)
		if newer {
			also := append(append([]int64{}, cur.Also...), cur.Notebook.Source.EntryID)
			*cur = it
			cur.Also = also
		} else {
			cur.Also = append(cur.Also, it.Notebook.Source.EntryID)
		}
		cur.Since = earliest
	}
	for i := range out {
		sort.Slice(out[i].Also, func(a, b int) bool { return out[i].Also[a] < out[i].Also[b] })
	}
	return out
}

// ReviewSchedule is the readable next-review recommendation of one queue
// item (R4-WB-011, R4-WB-014), from NextRecommendation: when it is due now,
// and when it would be due after a completed or a missed attempt today.
// Nothing is stored or applied: the queue itself stays what the learner marked.
type ReviewSchedule struct {
	Now         Recommendation
	IfCompleted Recommendation
	IfMissed    Recommendation
}

// speakingRecovery are Speaking steps where something the learner started is
// stuck (a failed or unknown request, a transcript to add or confirm).
var speakingRecovery = map[string]bool{
	domain.SpeakingQueueCheckUnknown: true, domain.SpeakingQueueRequestFailed: true,
	domain.SpeakingQueueConfirmTranscript: true, domain.SpeakingQueueAddTranscript: true,
}

// ScheduleInputFor maps a queue item onto the scheduling inputs the way
// ScheduleInputsFromExport maps the history export: a notebook record marked
// for retry is a review completed when it was saved. A Speaking step's
// completed attempts are its takes (only the latest take's time is known
// here: earlier takes count without a timestamp); it is a recovery when
// something is stuck, a review after a first take, else new.
func ScheduleInputFor(it ReviewItem) ScheduleInput {
	in := ScheduleInput{Key: it.Key}
	switch {
	case it.Notebook != nil:
		saved := it.Notebook.Source.CreatedAt
		in.Class, in.Completed, in.CreatedAt = SchedReview, []time.Time{saved}, saved
	case it.Speaking != nil:
		if it.Speaking.TakeNumber > 0 {
			in.Completed = make([]time.Time, it.Speaking.TakeNumber)
			if it.Speaking.Since != nil {
				in.Completed[len(in.Completed)-1] = *it.Speaking.Since
			}
		}
		switch {
		case speakingRecovery[it.Reason]:
			in.Class = SchedRecovery
		case it.Speaking.TakeNumber > 0:
			in.Class = SchedReview
		default:
			in.Class = SchedNew
		}
	default:
		in.Class = SchedNew
	}
	return in
}

// ScheduleFor gives the item's recommendation now and after one more
// attempt today, completed or missed.
func ScheduleFor(it ReviewItem, now time.Time, loc *time.Location) ReviewSchedule {
	in := ScheduleInputFor(it)
	next := func(missed bool) Recommendation {
		x := in
		x.Class = SchedReview // after an attempt, a new or stuck item is a review
		x.Completed = append(append([]time.Time{}, in.Completed...), now)
		x.LastMissed = missed
		return NextRecommendation(x, now, loc)
	}
	if in.Class == SchedRecovery {
		r := NextRecommendation(in, now, loc)
		return ReviewSchedule{Now: r, IfCompleted: next(false), IfMissed: r}
	}
	return ReviewSchedule{Now: NextRecommendation(in, now, loc), IfCompleted: next(false), IfMissed: next(true)}
}

// IntervalDays counts local calendar days from the day of now to r's day.
func IntervalDays(r Recommendation, now time.Time, loc *time.Location) int {
	y1, m1, d1 := now.In(loc).Date()
	y2, m2, d2 := r.Due.In(loc).Date()
	return int(time.Date(y2, m2, d2, 0, 0, 0, 0, time.UTC).Sub(time.Date(y1, m1, d1, 0, 0, 0, 0, time.UTC)).Hours() / 24)
}
