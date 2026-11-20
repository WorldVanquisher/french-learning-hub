package application

import (
	"reflect"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/domain"
)

// R4-WB-011 to R4-WB-014: the readable next-review recommendation of each
// Review Today item, from NextRecommendation; R4-WB-008: one queue item per
// workbook question.

func TestNextRecommendation_MissedRestartsTheLadder(t *testing.T) {
	paris := zone(t, "Europe/Paris")
	now := time.Date(2026, 11, 20, 9, 0, 0, 0, paris)
	three := []time.Time{now.AddDate(0, 0, -10), now.AddDate(0, 0, -5), now}
	ok := NextRecommendation(ScheduleInput{Key: "k", Class: SchedReview, Completed: three}, now, paris)
	missed := NextRecommendation(ScheduleInput{Key: "k", Class: SchedReview, Completed: three, LastMissed: true}, now, paris)
	if ok.Day != "2026-11-27" || !strings.HasPrefix(ok.Rule, "ladder n=3 +7d from 2026-11-20") {
		t.Fatalf("completed: %s %q", ok.Day, ok.Rule)
	}
	if missed.Day != "2026-11-21" || missed.Rule != "missed: ladder n=1 +1d from 2026-11-20 (last attempt)" {
		t.Fatalf("missed: %s %q", missed.Day, missed.Rule)
	}
}

// Both Paris daylight-saving transitions of 2026: the due day is a calendar
// day at local midnight with that day's offset, also for an attempt inside the
// skipped hour (normalised forward by Go) and inside the repeated hour (either
// occurrence).
func TestNextRecommendation_ParisDaylightSavingBothWays(t *testing.T) {
	paris := zone(t, "Europe/Paris")
	cases := []struct {
		name    string
		attempt time.Time
		missed  bool
		n       int
		day     string
		offset  string
	}{
		{"spring: evening before, n=1", time.Date(2026, 3, 28, 22, 30, 0, 0, paris), false, 1, "2026-03-29", "+01:00"},
		{"spring: inside the skipped hour", time.Date(2026, 3, 29, 2, 30, 0, 0, paris), false, 1, "2026-03-30", "+02:00"},
		{"spring: missed across the change", time.Date(2026, 3, 28, 23, 59, 59, 0, paris), true, 3, "2026-03-29", "+01:00"},
		{"autumn: first 02:30 (CEST)", time.Date(2026, 10, 25, 0, 30, 0, 0, time.UTC), false, 2, "2026-10-28", "+01:00"},
		{"autumn: second 02:30 (CET)", time.Date(2026, 10, 25, 1, 30, 0, 0, time.UTC), false, 2, "2026-10-28", "+01:00"},
		{"autumn: evening before, n=1", time.Date(2026, 10, 24, 23, 0, 0, 0, paris), false, 1, "2026-10-25", "+02:00"},
	}
	for _, c := range cases {
		done := make([]time.Time, c.n)
		done[c.n-1] = c.attempt
		r := NextRecommendation(ScheduleInput{Key: "k", Class: SchedReview, Completed: done, LastMissed: c.missed}, c.attempt, paris)
		if r.Day != c.day || r.Due.Format("15:04 -07:00") != "00:00 "+c.offset {
			t.Errorf("%s: due %s %s (%s), want %s at 00:00 %s", c.name, r.Day, r.Due.Format("15:04 -07:00"), r.Rule, c.day, c.offset)
		}
	}
}

// A learner who travels: the same attempt and the same instant, read in two
// zones, gives each zone's own calendar days (never a mix of the two).
func TestNextRecommendation_TimeZoneChange(t *testing.T) {
	paris, tokyo := zone(t, "Europe/Paris"), zone(t, "Asia/Tokyo")
	attempt := time.Date(2026, 11, 19, 20, 0, 0, 0, time.UTC) // 21:00 in Paris, 05:00 next day in Tokyo
	now := attempt.Add(time.Hour)
	in := ScheduleInput{Key: "k", Class: SchedReview, Completed: []time.Time{attempt}}
	p, k := NextRecommendation(in, now, paris), NextRecommendation(in, now, tokyo)
	if p.Day != "2026-11-20" || !strings.Contains(p.Rule, "from 2026-11-19") {
		t.Fatalf("paris: %s %q", p.Day, p.Rule)
	}
	if k.Day != "2026-11-21" || !strings.Contains(k.Rule, "from 2026-11-20") {
		t.Fatalf("tokyo: %s %q", k.Day, k.Rule)
	}
	if IntervalDays(p, now, paris) != 1 || IntervalDays(k, now, tokyo) != 1 {
		t.Fatalf("intervals: %d %d", IntervalDays(p, now, paris), IntervalDays(k, now, tokyo))
	}
}

func notebookItem(entry int64, material int64, version, item int, saved, marked time.Time) ReviewItem {
	nb := &NotebookItem{
		Source:      domain.LearningCaptureSource{EntryID: entry, CreatedAt: saved, Ref: domain.CaptureSourceRef{Type: domain.SourceListeningItem, RecordID: entry * 10, Item: item}},
		Resolved:    domain.ResolvedSource{Skill: domain.SkillListening, Link: domain.SourceLink{ListeningMaterialID: material, ListeningTranscriptVersion: version}},
		Mark:        &domain.RetryMark{EntryID: entry, Marked: true, At: marked},
		SourceState: domain.SourceResolved,
	}
	return ReviewItem{Key: "notebook:entry:" + string(rune('0'+entry)), Source: ReviewSourceNotebook, Reason: ReviewRetryMarked, Since: marked, Notebook: nb}
}

func TestScheduleFor_ReadableNowCompletedAndMissed(t *testing.T) {
	paris := zone(t, "Europe/Paris")
	now := time.Date(2026, 11, 20, 9, 0, 0, 0, paris)
	saved := time.Date(2026, 11, 18, 10, 0, 0, 0, paris)
	s := ScheduleFor(notebookItem(1, 5, 1, 2, saved, saved), now, paris)
	got := []string{s.Now.Day, s.Now.Rule, s.IfCompleted.Day, s.IfCompleted.Rule, s.IfMissed.Day, s.IfMissed.Rule}
	want := []string{"2026-11-20", "ladder n=1 +1d from 2026-11-18 (last attempt), overdue: due today",
		"2026-11-23", "ladder n=2 +3d from 2026-11-20 (last attempt)",
		"2026-11-21", "missed: ladder n=1 +1d from 2026-11-20 (last attempt)"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("notebook:\n got %q\nwant %q", got, want)
	}
	if IntervalDays(s.IfCompleted, now, paris) != 3 || IntervalDays(s.IfMissed, now, paris) != 1 {
		t.Fatalf("intervals %d %d", IntervalDays(s.IfCompleted, now, paris), IntervalDays(s.IfMissed, now, paris))
	}

	// Speaking: stuck (recovery) stays due today when missed; two takes with
	// only the latest time known count as two attempts.
	ex, take := int64(4), int64(9)
	since := time.Date(2026, 11, 19, 18, 0, 0, 0, paris)
	stuck := ScheduleFor(ReviewItem{Key: "speaking:exercise:4", Source: ReviewSourceSpeaking, Reason: domain.SpeakingQueueCheckUnknown,
		Speaking: &SpeakingQueueItem{ExerciseID: &ex, TakeID: &take, TakeNumber: 2, Since: &since}}, now, paris)
	if stuck.Now.Class != SchedRecovery || stuck.Now.Day != "2026-11-20" || stuck.IfMissed.Day != "2026-11-20" || stuck.IfCompleted.Day != "2026-11-27" {
		t.Fatalf("recovery: %+v", stuck)
	}
	review := ScheduleFor(ReviewItem{Key: "speaking:exercise:4", Source: ReviewSourceSpeaking, Reason: domain.SpeakingQueueReviewWithoutFeedback,
		Speaking: &SpeakingQueueItem{ExerciseID: &ex, TakeID: &take, TakeNumber: 2, Since: &since}}, now, paris)
	if review.Now.Rule != "ladder n=2 +3d from 2026-11-19 (last attempt)" || review.Now.Day != "2026-11-22" || review.IfCompleted.Day != "2026-11-27" {
		t.Fatalf("review: %+v", review.Now)
	}
}

// R4-WB-013: a previous attempt without a date. The step still counts it; the
// start is the record's creation, and when that is unknown too, today, and
// the rule says which.
func TestScheduleFor_MissingPreviousAttemptDate(t *testing.T) {
	paris := zone(t, "Europe/Paris")
	now := time.Date(2026, 11, 20, 9, 0, 0, 0, paris)
	ex := int64(4)
	noTime := ScheduleFor(ReviewItem{Key: "speaking:exercise:4", Source: ReviewSourceSpeaking, Reason: domain.SpeakingQueueAnswerAgain,
		Speaking: &SpeakingQueueItem{ExerciseID: &ex, TakeNumber: 1}}, now, paris)
	if noTime.Now.Day != "2026-11-21" || noTime.Now.Rule != "ladder n=1 +1d from 2026-11-20 (today (fallback: no timestamp))" {
		t.Fatalf("no attempt time: %s %q", noTime.Now.Day, noTime.Now.Rule)
	}
	nb := notebookItem(1, 5, 1, 2, time.Time{}, now)
	unknownSave := ScheduleFor(nb, now, paris)
	if unknownSave.Now.Day != "2026-11-21" || !strings.Contains(unknownSave.Now.Rule, "fallback") {
		t.Fatalf("no saved time: %s %q", unknownSave.Now.Day, unknownSave.Now.Rule)
	}
}

func TestBuildReviewToday_OneItemPerWorkbookQuestion(t *testing.T) {
	now := time.Date(2026, 11, 20, 9, 0, 0, 0, time.UTC)
	at := func(h int) time.Time { return now.Add(-time.Duration(h) * time.Hour) }
	a := notebookItem(1, 5, 1, 2, at(50), at(40)).Notebook // revision 1, question 2, marked first
	b := notebookItem(2, 5, 2, 2, at(30), at(20)).Notebook // revision 2, same question
	c := notebookItem(3, 5, 2, 3, at(30), at(10)).Notebook // another question
	d := notebookItem(4, 6, 1, 2, at(30), at(5)).Notebook  // another lesson
	gone := notebookItem(5, 5, 1, 2, at(30), at(1)).Notebook
	gone.SourceState = domain.SourceMissing // identity unknown: never grouped
	got := BuildReviewTodayCounted(nil, []NotebookItem{*a, *b, *c, *d, *gone}, 9, now)
	var keys []string
	for _, it := range got.Items {
		keys = append(keys, it.Key)
	}
	want := []string{"notebook:entry:2", "notebook:entry:3", "notebook:entry:4", "notebook:entry:5"}
	if !reflect.DeepEqual(keys, want) {
		t.Fatalf("keys %v, want %v", keys, want)
	}
	lead := got.Items[0]
	if !reflect.DeepEqual(lead.Also, []int64{1}) || !lead.Since.Equal(at(40)) || lead.Notebook.Source.EntryID != 2 {
		t.Fatalf("lead: entry %d also %v since %v", lead.Notebook.Source.EntryID, lead.Also, lead.Since)
	}
	if got.History.NotebookItems != 9 {
		t.Fatalf("history counts every record: %d", got.History.NotebookItems)
	}
	// The same records in another order give the same queue.
	again := BuildReviewTodayCounted(nil, []NotebookItem{*gone, *d, *c, *b, *a}, 9, now)
	if !reflect.DeepEqual(again.Items, got.Items) {
		t.Fatalf("order-dependent grouping")
	}
}
