package application

import (
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/domain"
)

func TestBuildReviewToday_ExplicitReasonsStableOrderAndScope(t *testing.T) {
	now := time.Date(2026, 11, 19, 9, 0, 0, 0, time.UTC)
	at := func(m int) *time.Time { x := now.Add(time.Duration(m) * time.Minute); return &x }
	id := func(n int64) *int64 { return &n }
	practice := &SpeakingPractice{
		Summary: SpeakingPracticeSummary{Started: 3, Takes: 4},
		Queue: []SpeakingQueueItem{
			{Reason: domain.SpeakingQueueAnswerAgain, ExerciseID: id(7), Since: at(-30)},
			{Reason: domain.SpeakingQueueCheckUnknown, ExerciseID: id(9), Since: at(-5)},
			{Reason: domain.SpeakingQueueAnswerAgain, ExerciseID: id(3), Since: at(-30)}, // same priority and time as 7
			{Reason: domain.SpeakingQueueNotStarted, PromptID: "sp-x"},                   // not due
		},
	}
	mark := func(entry int64, marked bool, m int) NotebookItem {
		return NotebookItem{Source: domain.LearningCaptureSource{EntryID: entry}, Mark: &domain.RetryMark{EntryID: entry, Marked: marked, At: *at(m)}}
	}
	notebook := []NotebookItem{
		mark(41, true, -30),  // same priority and time as the answer_again steps
		mark(42, false, -60), // mark removed: history only
		{Source: domain.LearningCaptureSource{EntryID: 43}}, // never marked: history only
	}
	got := BuildReviewToday(practice, notebook, now)
	var keys []string
	for _, it := range got.Items {
		keys = append(keys, it.Key+"="+it.Reason)
	}
	want := "speaking:exercise:9=check_unknown_outcome notebook:entry:41=retry_marked speaking:exercise:3=answer_again speaking:exercise:7=answer_again"
	if strings.Join(keys, " ") != want {
		t.Fatalf("order:\n got %s\nwant %s", strings.Join(keys, " "), want)
	}
	// The same input in another order gives the same queue.
	practice.Queue[0], practice.Queue[2] = practice.Queue[2], practice.Queue[0]
	again := BuildReviewToday(practice, []NotebookItem{notebook[2], notebook[0], notebook[1]}, now)
	for i := range got.Items {
		if again.Items[i].Key != got.Items[i].Key {
			t.Fatalf("unstable order at %d: %s vs %s", i, again.Items[i].Key, got.Items[i].Key)
		}
	}
	if got.History != (ReviewHistory{NotebookItems: 3, SpeakingExercises: 3, SpeakingTakes: 4}) {
		t.Fatalf("history: %+v", got.History)
	}
	// Without Speaking the notebook items still come through.
	if only := BuildReviewToday(nil, notebook, now); len(only.Items) != 1 || only.Items[0].Source != ReviewSourceNotebook {
		t.Fatalf("notebook only: %+v", only.Items)
	}
}
