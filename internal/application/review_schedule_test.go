package application

import (
	"fmt"
	"os"
	"strings"
	"testing"
	"time"
	_ "time/tzdata" // the zones below, whatever the host has installed
)

func zone(t *testing.T, name string) *time.Location {
	t.Helper()
	loc, err := time.LoadLocation(name)
	if err != nil {
		t.Fatal(err)
	}
	return loc
}

func TestNextRecommendation_ClassesLadderAndStableOrder(t *testing.T) {
	ny := zone(t, "America/New_York")
	now := time.Date(2026, 11, 19, 10, 0, 0, 0, ny)
	last := time.Date(2026, 11, 18, 21, 0, 0, 0, ny)
	cases := []struct {
		in       ScheduleInput
		day      string
		priority int
		rule     string
	}{
		{ScheduleInput{Key: "a", Class: SchedRecovery, Completed: []time.Time{last}}, "2026-11-19", 0, "recovery: due today"},
		{ScheduleInput{Key: "b", Class: SchedNew}, "2026-11-19", 2, "new: no completed attempt, due today"},
		{ScheduleInput{Key: "c", Class: SchedReview, Completed: []time.Time{last}}, "2026-11-19", 1, "ladder n=1 +1d from 2026-11-18 (last attempt)"},
		{ScheduleInput{Key: "d", Class: SchedReview, Completed: []time.Time{last.AddDate(0, 0, -3), last}}, "2026-11-21", 1, "ladder n=2 +3d from 2026-11-18 (last attempt)"},
		{ScheduleInput{Key: "e", Class: SchedReview, Completed: make([]time.Time, 0)}, "2026-11-19", 1, "review: no completed attempt, due today"},
		{ScheduleInput{Key: "f", Class: SchedReview, Completed: []time.Time{last, last, last, last, last}}, "2026-12-02", 1, "ladder n=5 +14d from 2026-11-18 (last attempt)"},
	}
	var recs []Recommendation
	for _, c := range cases {
		r := NextRecommendation(c.in, now, ny)
		if r.Day != c.day || r.Priority != c.priority || r.Rule != c.rule || r.Due.In(ny).Hour() != 0 {
			t.Errorf("%s: got %s p%d %q (due %s), want %s p%d %q", c.in.Key, r.Day, r.Priority, r.Rule, r.Due, c.day, c.priority, c.rule)
		}
		recs = append(recs, r)
	}
	// Due today, most urgent first, ties by key: the same order however the input is shuffled.
	var keys []string
	for _, r := range DueOn([]Recommendation{recs[4], recs[1], recs[2], recs[0], recs[5], recs[3]}, now, ny) {
		keys = append(keys, r.Key)
	}
	if strings.Join(keys, ",") != "a,c,e,b" {
		t.Fatalf("due today: %v", keys)
	}
}

func TestNextRecommendation_LocalDayBoundaryMidnightAndZones(t *testing.T) {
	sh := zone(t, "Asia/Shanghai")
	// One minute apart across local midnight: different days, different due days.
	before := time.Date(2026, 11, 18, 23, 59, 59, 0, sh)
	after := time.Date(2026, 11, 19, 0, 0, 0, 0, sh)
	now := time.Date(2026, 11, 19, 12, 0, 0, 0, sh)
	r1 := NextRecommendation(ScheduleInput{Class: SchedReview, Completed: []time.Time{before}}, now, sh)
	r2 := NextRecommendation(ScheduleInput{Class: SchedReview, Completed: []time.Time{after}}, now, sh)
	if r1.Day != "2026-11-19" || r2.Day != "2026-11-20" {
		t.Fatalf("midnight: %s %s", r1.Day, r2.Day)
	}
	// The same instant is a different day in another zone: grouping uses the learner's.
	instant := time.Date(2026, 11, 18, 17, 30, 0, 0, time.UTC) // 01:30 on the 19th in Shanghai
	if LocalDay(instant, sh) != "2026-11-19" || LocalDay(instant, time.UTC) != "2026-11-18" {
		t.Fatalf("zones: %s %s", LocalDay(instant, sh), LocalDay(instant, time.UTC))
	}
}

func TestNextRecommendation_DaylightSavingKeepsCalendarDays(t *testing.T) {
	ny := zone(t, "America/New_York")
	for _, c := range []struct {
		attempt time.Time
		n       int
		day     string
		offset  string
	}{
		{time.Date(2026, 3, 7, 12, 0, 0, 0, ny), 1, "2026-03-08", "-05:00"},    // the night clocks spring forward
		{time.Date(2026, 3, 7, 12, 0, 0, 0, ny), 2, "2026-03-10", "-04:00"},    // three days later, now EDT
		{time.Date(2026, 10, 31, 23, 30, 0, 0, ny), 1, "2026-11-01", "-04:00"}, // the night clocks fall back
		{time.Date(2026, 10, 31, 23, 30, 0, 0, ny), 2, "2026-11-03", "-05:00"}, // now EST
	} {
		completed := make([]time.Time, c.n)
		for i := range completed {
			completed[i] = c.attempt
		}
		now := c.attempt.Add(time.Hour)
		r := NextRecommendation(ScheduleInput{Class: SchedReview, Completed: completed}, now, ny)
		if r.Day != c.day || r.Due.In(ny).Hour() != 0 || r.Due.In(ny).Format("-07:00") != c.offset {
			t.Errorf("attempt %s n=%d: due %s (%s), want %s at local midnight %s", c.attempt, c.n, r.Day, r.Due.In(ny), c.day, c.offset)
		}
	}
}

func TestNextRecommendation_MissingTimestampsAndOlderRecords(t *testing.T) {
	loc := time.UTC
	now := time.Date(2026, 11, 19, 9, 0, 0, 0, loc)
	created := time.Date(2026, 11, 17, 8, 0, 0, 0, loc)
	var zero time.Time
	got := []string{}
	for _, in := range []ScheduleInput{
		{Key: "mixed", Class: SchedReview, Completed: []time.Time{zero, time.Date(2026, 11, 18, 7, 0, 0, 0, loc)}, CreatedAt: created},
		{Key: "created", Class: SchedReview, Completed: []time.Time{zero, zero}, CreatedAt: created},
		{Key: "nothing", Class: SchedReview, Completed: []time.Time{zero}},
		{Key: "legacy", CreatedAt: created},
		{Key: "overdue", Class: SchedReview, Completed: []time.Time{time.Date(2026, 10, 1, 9, 0, 0, 0, loc)}},
	} {
		r := NextRecommendation(in, now, loc)
		got = append(got, fmt.Sprintf("%s %s p%d %s", in.Key, r.Day, r.Priority, r.Rule))
	}
	want := []string{
		"mixed 2026-11-21 p1 ladder n=2 +3d from 2026-11-18 (last attempt)",
		"created 2026-11-20 p1 ladder n=2 +3d from 2026-11-17 (created (attempt times missing))",
		"nothing 2026-11-20 p1 ladder n=1 +1d from 2026-11-19 (today (fallback: no timestamp))",
		"legacy 2026-11-19 p1 legacy: no scheduling fields, due today",
		"overdue 2026-11-19 p1 ladder n=1 +1d from 2026-10-01 (last attempt), overdue: due today",
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("got:\n%s\nwant:\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
}

// One synthetic week (worked by hand in docs/validation/REVIEW-TODAY.md):
// two new items, a recovery, a review due on day 0 (n=1) and one due on day 2 (n=2).
func TestSimulateWeek_DailyWorkload(t *testing.T) {
	loc := zone(t, "Europe/Paris")
	start := time.Date(2026, 11, 16, 9, 0, 0, 0, loc) // a Monday
	yesterday := time.Date(2026, 11, 15, 18, 0, 0, 0, loc)
	items := []ScheduleInput{
		{Key: "A", Class: SchedNew},
		{Key: "B", Class: SchedNew},
		{Key: "C", Class: SchedReview, Completed: []time.Time{yesterday}},
		{Key: "D", Class: SchedReview, Completed: []time.Time{yesterday, yesterday}},
		{Key: "E", Class: SchedRecovery},
	}
	if got := fmt.Sprint(SimulateWeek(items, start, loc)); got != "[4 3 1 1 3 0 0]" {
		t.Fatalf("daily workload: %s", got)
	}
	if len(items[0].Completed) != 0 {
		t.Fatal("the simulation changed its input")
	}
}

// Inputs read from an export: a reviewed exercise, a new one, a retry mark,
// and an older line without timestamps (which falls back, as documented).
func TestScheduleInputsFromExport_SyntheticFile(t *testing.T) {
	file := strings.Join([]string{
		`{"kind":"header","format":"learning_history_export_v1"}`,
		`{"kind":"speaking_take","exercise":{"ref":"speaking:exercise:1"},"number":1,"created_at":"2026-11-17T09:00:00Z","transcripts":[{"created_at":"2026-11-17T09:05:00Z"}]}`,
		`{"kind":"speaking_take","exercise":{"ref":"speaking:exercise:1"},"number":2,"created_at":"2026-11-18T09:00:00Z","transcripts":[{"created_at":"2026-11-18T09:05:00Z"}]}`,
		`{"kind":"speaking_take","exercise":{"ref":"speaking:exercise:2"},"number":1,"created_at":"2026-11-18T10:00:00Z","transcripts":[]}`,
		`{"kind":"speaking_take","exercise":{"ref":"speaking:exercise:3"},"number":1,"transcripts":[{}]}`,
		`{"kind":"notebook_record","key":"notebook:capture:c1","saved_at":"2026-11-18T08:00:00Z","retry":{"marked":true}}`,
		`{"kind":"notebook_record","key":"notebook:capture:c2","saved_at":"2026-11-18T08:00:00Z","retry":{"marked":false}}`,
		`{"kind":"footer","records":6}`,
	}, "\n")
	ins, err := ScheduleInputsFromExport([]byte(file))
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 11, 19, 10, 0, 0, 0, time.UTC)
	var got []string
	for _, in := range ins {
		r := NextRecommendation(in, now, time.UTC)
		got = append(got, fmt.Sprintf("%s %s %s", in.Key, r.Day, r.Rule))
	}
	want := []string{
		"notebook:capture:c1 2026-11-19 ladder n=1 +1d from 2026-11-18 (last attempt)",
		"speaking:exercise:1 2026-11-21 ladder n=2 +3d from 2026-11-18 (last attempt)",
		"speaking:exercise:2 2026-11-19 new: no completed attempt, due today",
		"speaking:exercise:3 2026-11-20 ladder n=1 +1d from 2026-11-19 (today (fallback: no timestamp))",
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("got:\n%s\nwant:\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
}

// FLH_SCHEDULE_EXPORT names an export file (for example one written from an
// older fixture by scripts/validation/compat/older_fixtures.py). Every input
// it yields must get a due day and a rule. Skipped when unset.
func TestScheduleInputsFromExport_File(t *testing.T) {
	p := os.Getenv("FLH_SCHEDULE_EXPORT")
	if p == "" {
		t.Skip("FLH_SCHEDULE_EXPORT not set")
	}
	data, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	ins, err := ScheduleInputsFromExport(data)
	if err != nil {
		t.Fatal(err)
	}
	paris := zone(t, "Europe/Paris")
	now := time.Now()
	for _, in := range ins {
		r := NextRecommendation(in, now, paris)
		if r.Day == "" || r.Rule == "" || r.Due.In(paris).Hour() != 0 {
			t.Fatalf("%s: %+v", in.Key, r)
		}
		t.Logf("%s class=%s day=%s rule=%s", in.Key, r.Class, r.Day, r.Rule)
	}
	t.Logf("%d inputs from %s", len(ins), p)
}
