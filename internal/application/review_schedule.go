package application

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"
)

// Spaced practice recommendations (prototype; not stored, not yet applied to
// Review Today). A pure function of its inputs: the caller supplies the clock
// (now) and the learner's time zone, so the same inputs always give the same
// recommendation and every result names the rule that produced it.

// Priority classes, most urgent first (documented with examples in
// docs/validation/REVIEW-TODAY.md):
//   - recovery: something the learner started is stuck (a failed or unknown
//     request, a transcript to check). Always due today.
//   - review: practised before; due on the interval ladder below.
//   - new: never practised (started, no completed attempt). Due today, after
//     recovery and review.
const (
	SchedRecovery = "recovery"
	SchedReview   = "review"
	SchedNew      = "new"
)

var schedPriority = map[string]int{SchedRecovery: 0, SchedReview: 1, SchedNew: 2}

// SchedLadderDays is the review interval after the n-th completed attempt
// (n = 1, 2, 3, 4+), in local calendar days.
var SchedLadderDays = []int{1, 3, 7, 14}

// ScheduleInput is what the recommendation reads about one item.
type ScheduleInput struct {
	Key       string
	Class     string      // recovery, review or new; "" for an older record without scheduling fields
	Completed []time.Time // completed attempts; a zero time is a completed attempt without a timestamp
	CreatedAt time.Time   // zero when unknown
}

// Recommendation is when to practise an item next, and why.
type Recommendation struct {
	Key      string
	Class    string
	Priority int
	Due      time.Time // local midnight of the due day, in the given location
	Day      string    // the due day, YYYY-MM-DD in the learner's zone
	Rule     string    // the traceable rule, e.g. "ladder n=2 +3d from 2026-11-18 (last attempt)"
}

// LocalDay is the learner's calendar day for t.
func LocalDay(t time.Time, loc *time.Location) string { return t.In(loc).Format("2006-01-02") }

func localMidnight(t time.Time, loc *time.Location) time.Time {
	y, m, d := t.In(loc).Date()
	return time.Date(y, m, d, 0, 0, 0, 0, loc)
}

// addDays moves by calendar days (AddDate on the local date), so a daylight-
// saving change never shifts the due day.
func addDays(day time.Time, n int, loc *time.Location) time.Time {
	y, m, d := day.In(loc).Date()
	return time.Date(y, m, d+n, 0, 0, 0, 0, loc)
}

// NextRecommendation applies the rules in order:
//  1. recovery: due today;
//  2. no scheduling fields (Class ""): conservative, due today as a review
//     ("legacy");
//  3. new, or review without any completed attempt: due today;
//  4. review: the ladder step for the number of completed attempts, counted
//     from the latest attempt that has a timestamp; when none has one, from
//     CreatedAt; when that is unknown too, from today ("fallback").
//
// A due day before today is reported as today (overdue items are due now).
func NextRecommendation(in ScheduleInput, now time.Time, loc *time.Location) Recommendation {
	today := localMidnight(now, loc)
	rec := Recommendation{Key: in.Key, Class: in.Class, Priority: schedPriority[in.Class], Due: today}
	switch {
	case in.Class == SchedRecovery:
		rec.Rule = "recovery: due today"
	case in.Class == "":
		rec.Class, rec.Priority, rec.Rule = SchedReview, schedPriority[SchedReview], "legacy: no scheduling fields, due today"
	case len(in.Completed) == 0:
		rec.Rule = fmt.Sprintf("%s: no completed attempt, due today", in.Class)
	default:
		n := len(in.Completed)
		step := SchedLadderDays[min(n, len(SchedLadderDays))-1]
		var base time.Time
		from := "last attempt"
		for _, t := range in.Completed {
			if !t.IsZero() && t.After(base) {
				base = t
			}
		}
		if base.IsZero() {
			base, from = in.CreatedAt, "created (attempt times missing)"
		}
		if base.IsZero() {
			base, from = now, "today (fallback: no timestamp)"
		}
		start := localMidnight(base, loc)
		rec.Due = addDays(start, step, loc)
		rec.Rule = fmt.Sprintf("ladder n=%d +%dd from %s (%s)", n, step, LocalDay(start, loc), from)
		if rec.Due.Before(today) {
			rec.Due = today
			rec.Rule += ", overdue: due today"
		}
	}
	rec.Day = LocalDay(rec.Due, loc)
	return rec
}

// DueOn returns the recommendations due on or before the local day of now,
// in priority order, then key: a stable order for equal priorities.
func DueOn(recs []Recommendation, now time.Time, loc *time.Location) []Recommendation {
	today := LocalDay(now, loc)
	out := []Recommendation{}
	for _, r := range recs {
		if r.Day <= today {
			out = append(out, r)
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].Priority != out[j].Priority {
			return out[i].Priority < out[j].Priority
		}
		return out[i].Key < out[j].Key
	})
	return out
}

// SimulateWeek plays seven local days from start: each day every due item is
// practised once (a completed attempt at 18:00 local time) and rescheduled.
// It returns how many items were due each day: the daily workload.
func SimulateWeek(items []ScheduleInput, start time.Time, loc *time.Location) []int {
	state := make([]ScheduleInput, len(items))
	copy(state, items)
	load := make([]int, 7)
	for d := 0; d < 7; d++ {
		day := addDays(localMidnight(start, loc), d, loc)
		noon := day.Add(12 * time.Hour)
		for i := range state {
			if r := NextRecommendation(state[i], noon, loc); r.Day <= LocalDay(noon, loc) {
				load[d]++
				state[i].Completed = append(append([]time.Time{}, state[i].Completed...), day.Add(18*time.Hour))
				if state[i].Class != SchedReview {
					state[i].Class = SchedReview // once practised, an item is reviewed
				}
			}
		}
	}
	return load
}

// ScheduleInputsFromExport (prototype) reads the Speaking takes of a
// learning_history_export_v1 file into one ScheduleInput per exercise, so the
// recommendation rules can be checked against older databases without
// storing anything: an exercise with a confirmed transcript on its latest
// take is a review (each take with a transcript is a completed attempt, at
// its first version's time); one whose latest take has none is new. Notebook
// records marked for retry are reviews completed when they were saved. Older
// files without timestamps fall back as NextRecommendation documents.
func ScheduleInputsFromExport(data []byte) ([]ScheduleInput, error) {
	type version struct {
		CreatedAt string `json:"created_at"`
	}
	type rec struct {
		Kind     string `json:"kind"`
		Key      string `json:"key"`
		Exercise struct {
			Ref string `json:"ref"`
		} `json:"exercise"`
		Number      int       `json:"number"`
		CreatedAt   string    `json:"created_at"`
		SavedAt     string    `json:"saved_at"`
		Transcripts []version `json:"transcripts"`
		Retry       struct {
			Marked bool `json:"marked"`
		} `json:"retry"`
	}
	parse := func(s string) time.Time {
		t, _ := time.Parse(time.RFC3339Nano, s)
		return t
	}
	byExercise := map[string]*ScheduleInput{}
	latest := map[string]int{}
	latestHas := map[string]bool{}
	var order []string
	var out []ScheduleInput
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var r rec
		if err := json.Unmarshal([]byte(line), &r); err != nil {
			return nil, fmt.Errorf("not an export line: %w", err)
		}
		switch r.Kind {
		case "speaking_take":
			in, ok := byExercise[r.Exercise.Ref]
			if !ok {
				in = &ScheduleInput{Key: r.Exercise.Ref, Class: SchedNew, Completed: []time.Time{}}
				byExercise[r.Exercise.Ref] = in
				order = append(order, r.Exercise.Ref)
			}
			if in.CreatedAt.IsZero() || parse(r.CreatedAt).Before(in.CreatedAt) {
				in.CreatedAt = parse(r.CreatedAt)
			}
			if len(r.Transcripts) > 0 {
				in.Completed = append(in.Completed, parse(r.Transcripts[0].CreatedAt))
			}
			if r.Number >= latest[r.Exercise.Ref] {
				latest[r.Exercise.Ref], latestHas[r.Exercise.Ref] = r.Number, len(r.Transcripts) > 0
			}
		case "notebook_record":
			if r.Retry.Marked {
				out = append(out, ScheduleInput{Key: r.Key, Class: SchedReview, Completed: []time.Time{parse(r.SavedAt)}, CreatedAt: parse(r.SavedAt)})
			}
		}
	}
	for _, k := range order {
		in := byExercise[k]
		if latestHas[k] {
			in.Class = SchedReview
		} else {
			in.Class = SchedNew
		}
		out = append(out, *in)
	}
	return out, nil
}
