package application

import (
	"fmt"
	"testing"
	"time"
	_ "time/tzdata"
)

// The handwritten sequence of docs/validation/LEARNING-WEEK.md: every total
// below was worked out by hand from this list.
func handwrittenEvents(paris *time.Location) []LearningEvent {
	at := func(day, hour, min int) time.Time { return time.Date(2026, 11, day, hour, min, 0, 0, paris) }
	return []LearningEvent{
		{Kind: EventProduction, Key: "speaking:take:1", Exercise: "speaking:exercise:1", At: at(13, 9, 0)}, // e1
		{Kind: EventProduction, Key: "speaking:take:1", Exercise: "speaking:exercise:1", At: at(13, 9, 5)}, // e2 duplicate
		{Kind: EventOwnCorrection, Key: "speaking:transcript:5", Exercise: "speaking:exercise:1", At: at(13, 9, 10), Correction: &LearningCorrection{Skill: "speaking", Title: "Invitation", ExerciseID: 1, TakeID: 1, TakeNumber: 1, Version: 2, PriorVersion: 1}}, // e3
		{Kind: EventProviderFeedback, Key: "speaking:feedback:7", Exercise: "speaking:exercise:1", At: at(14, 20, 0)},                                                                                                                                               // e4
		{Kind: EventProduction, Key: "writing:draft:3", Exercise: "writing:task:2", At: time.Date(2026, 11, 16, 23, 30, 0, 0, time.UTC)},                                                                                                                            // e5: 00:30 on the 17th in Paris
		{Kind: EventOwnCorrection, Key: "writing:draft:4", Exercise: "writing:task:2", At: at(17, 8, 0), Correction: &LearningCorrection{Skill: "writing", Title: "Lettre", TaskID: 2, Version: 2, PriorVersion: 1}},                                                // e6
		{Kind: EventReviewed, Key: "notebook:saved:41", At: at(19, 8, 0)},                                   // e7
		{Kind: EventReviewed, Key: "notebook:done:41", At: at(19, 9, 0)},                                    // e8
		{Kind: EventReviewed, Key: "notebook:done:41", At: at(19, 9, 30)},                                   // e9 duplicate
		{Kind: EventProduction, Key: "speaking:take:2", Exercise: "speaking:exercise:1", At: at(12, 23, 0)}, // e10 before the week
		{Kind: EventProduction, Key: "speaking:take:3", Exercise: "speaking:exercise:4", At: at(19, 9, 45)}, // e11
		{Kind: EventReviewed, Key: "notebook:done:41", At: at(18, 10, 0)},                                   // e12 another day
	}
}

func dayLine(w LearningWeek) string {
	s := ""
	for _, d := range w.Days {
		s += fmt.Sprintf("%s:P%dR%dO%dF%d ", d.Day[5:], d.Production, d.Reviewed, d.OwnCorrections, d.ProviderFeedback)
	}
	return s
}

func TestBuildLearningWeek_HandwrittenSequence(t *testing.T) {
	paris := zone(t, "Europe/Paris")
	now := time.Date(2026, 11, 19, 10, 0, 0, 0, paris)
	w := BuildLearningWeek(handwrittenEvents(paris), now, paris)
	if got := dayLine(w); got != "11-13:P1R0O1F0 11-14:P0R0O0F1 11-15:P0R0O0F0 11-16:P0R0O0F0 11-17:P1R0O1F0 11-18:P0R1O0F0 11-19:P1R2O0F0 " {
		t.Fatalf("days: %s", got)
	}
	if w.Production != 3 || w.Reviewed != 3 || w.OwnCorrections != 2 || w.ProviderFeedback != 1 || w.DistinctExercises != 3 || w.ActiveDays != 5 || w.Duplicates != 2 {
		t.Fatalf("totals: %+v", w)
	}
	if !w.Sparse || w.ProductionShare != nil || w.From != "2026-11-13" || w.To != "2026-11-19" || w.Zone != "Europe/Paris" {
		t.Fatalf("sparse/share/window: %+v", w)
	}
	// Corrections: newest first, each with where to reopen it.
	if len(w.Corrections) != 2 || w.Corrections[0].Skill != "writing" || w.Corrections[0].Day != "2026-11-17" || w.Corrections[1].TakeNumber != 1 || w.Corrections[1].Version != 2 {
		t.Fatalf("corrections: %+v", w.Corrections)
	}
	// The same input in the same order or shuffled gives the same week.
	ev := handwrittenEvents(paris)
	for i, j := 0, len(ev)-1; i < j; i, j = i+1, j-1 {
		ev[i], ev[j] = ev[j], ev[i]
	}
	if got := BuildLearningWeek(ev, now, paris); dayLine(got) != dayLine(w) || got.Duplicates != 2 {
		t.Fatalf("order changed the week: %s", dayLine(got))
	}
}

// The learner's zone decides the day: e5 is Monday 23:30 in UTC but Tuesday
// 00:30 in Paris.
func TestBuildLearningWeek_ZoneDecidesTheDay(t *testing.T) {
	paris := zone(t, "Europe/Paris")
	now := time.Date(2026, 11, 19, 9, 0, 0, 0, time.UTC)
	w := BuildLearningWeek(handwrittenEvents(paris), now, time.UTC)
	if got := dayLine(w); got != "11-13:P1R0O1F0 11-14:P0R0O0F1 11-15:P0R0O0F0 11-16:P1R0O0F0 11-17:P0R0O1F0 11-18:P0R1O0F0 11-19:P1R2O0F0 " {
		t.Fatalf("UTC days: %s", got)
	}
	if w.ActiveDays != 6 || w.Production != 3 {
		t.Fatalf("UTC totals: %+v", w)
	}
}

// Shares appear only from LearningWeekMinForShares counted actions.
func TestBuildLearningWeek_NoPercentFromTinySamples(t *testing.T) {
	loc := time.UTC
	now := time.Date(2026, 11, 19, 12, 0, 0, 0, loc)
	var ev []LearningEvent
	for i := 0; i < 15; i++ {
		ev = append(ev, LearningEvent{Kind: EventProduction, Key: fmt.Sprintf("speaking:take:%d", i), At: now.Add(-time.Hour)})
	}
	for i := 0; i < 4; i++ {
		ev = append(ev, LearningEvent{Kind: EventReviewed, Key: fmt.Sprintf("notebook:saved:%d", i), At: now.Add(-time.Hour)})
	}
	if w := BuildLearningWeek(ev, now, loc); !w.Sparse || w.ProductionShare != nil {
		t.Fatalf("19 actions must stay counts only: %+v", w)
	}
	ev = append(ev, LearningEvent{Kind: EventReviewed, Key: "notebook:saved:99", At: now.Add(-time.Hour)})
	w := BuildLearningWeek(ev, now, loc)
	if w.Sparse || w.ProductionShare == nil || *w.ProductionShare != 75 {
		t.Fatalf("20 actions: %+v", w)
	}
	// Duplicates never reach the threshold: the same 20 events twice are still 20.
	if w2 := BuildLearningWeek(append(ev, ev...), now, loc); w2.Production+w2.Reviewed != 20 || w2.Duplicates != 20 {
		t.Fatalf("duplicates inflated the totals: %+v", w2)
	}
}
