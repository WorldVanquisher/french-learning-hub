package http_test

import (
	"context"
	"net/http"
	"testing"
	"time"

	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
)

// FLH sections v1: the notebook keeps "what I got wrong" apart from "what the
// system suggested", keeps every item on the exact version it came from, and
// degrades one unreadable source without hiding the rest.

func notebookItems(t *testing.T, f *notebookFixture, query string) []map[string]any {
	t.Helper()
	code, out := doJSON(t, http.MethodGet, f.srv.URL+"/mistake-notebook/items"+query, "")
	if code != http.StatusOK {
		t.Fatalf("list = %d %v", code, out)
	}
	items := []map[string]any{}
	for _, it := range out["items"].([]any) {
		items = append(items, it.(map[string]any))
	}
	return items
}

func itemBySkill(t *testing.T, items []map[string]any, skill string) map[string]any {
	t.Helper()
	for _, it := range items {
		if it["skill"] == skill {
			return it
		}
	}
	t.Fatalf("no %s item in %v", skill, items)
	return nil
}

func saveAllFour(t *testing.T, f *notebookFixture) {
	t.Helper()
	for _, c := range []struct {
		id  string
		ref map[string]any
	}{
		{"sec-listening", ref("listening_item", f.ids["listeningExercise"], 2)},
		{"sec-reading", ref("reading_item", f.ids["readingExercise"], 1)},
		{"sec-writing", ref("writing_correction", f.ids["writingFeedback"], 1)},
		{"sec-speaking", ref("speaking_improvement", f.ids["speakingFeedback"], 2)},
	} {
		if code, out := f.save(t, c.id, c.ref, "Ce que j'ai raté"); code != http.StatusCreated {
			t.Fatalf("save %s = %d %v", c.id, code, out)
		}
	}
}

func TestSections_ReferenceOriginSeparatesAuthoredAnswersFromSuggestions(t *testing.T) {
	f := newNotebookFixture(t)
	saveAllFour(t, f)
	items := notebookItems(t, f, "")
	want := map[string][2]string{
		"reading":   {"authored", "authored:" + domain.ReadingPackID},
		"listening": {"generated", "openai:fake-model:listening_exercise_v1"},
		"writing":   {"generated", ""},
		"speaking":  {"generated", ""},
	}
	for skill, w := range want {
		it := itemBySkill(t, items, skill)
		if it["source_status"] != "resolved" || it["reference_origin"] != w[0] {
			t.Errorf("%s: status %v origin %v, want resolved %s", skill, it["source_status"], it["reference_origin"], w[0])
		}
		if w[1] != "" && it["generator"] != w[1] {
			t.Errorf("%s: generator %v, want %s", skill, it["generator"], w[1])
		}
		if gen, _ := it["generator"].(string); gen == "" {
			t.Errorf("%s: the stored provenance must be shown", skill)
		}
		// The learner's own side is never the model's: writing and speaking
		// quote the learner's version, and the record is the learner's text.
		if rec := it["record"].(map[string]any); rec["original_input"] != "Ce que j'ai raté" {
			t.Errorf("%s: record %v", skill, rec)
		}
	}
	if q := itemBySkill(t, items, "writing")["quote"]; q == nil || q == itemBySkill(t, items, "writing")["reference"] {
		t.Errorf("writing: the learner's quote and the suggestion must differ, got quote %v", q)
	}
}

// learnerReadingItem stores a learner lesson with one generated exercise on
// passage version 1 (authored examples cannot get new versions) and saves its
// first item.
func learnerReadingItem(t *testing.T, f *notebookFixture) int64 {
	t.Helper()
	ctx := context.Background()
	repo := sqlite.NewReadingRepository(f.db)
	now := time.Now().UTC()
	lesson, _, err := repo.CreateLesson(ctx, domain.ReadingLesson{Title: "Affiche de la médiathèque", Origin: domain.ReadingOriginLearner},
		[]domain.ReadingSegment{{ID: "p1", Text: "La médiathèque ouvre le mardi à dix heures."}}, now)
	if err != nil {
		t.Fatal(err)
	}
	prep, passage, _, err := repo.StartPreparation(ctx, domain.NewReadingPreparation{OperationID: "4b3c1d2e-0000-4000-8000-000000000001", LessonID: lesson.ID, Now: now, Deadline: now.Add(time.Minute)})
	if err != nil {
		t.Fatal(err)
	}
	content := domain.ReadingExerciseContent{Items: []domain.ReadingItem{{Kind: "detail", Question: "Quel jour ouvre la médiathèque ?", ReferenceAnswer: "Le mardi.",
		AcceptedAlternatives: []string{}, WrongAnswers: []domain.ReadingWrongAnswer{}, Evidence: []domain.ReadingEvidence{{Segment: "p1", Excerpt: "le mardi"}},
		ExplanationEN: "p1 names Tuesday.", ExplanationZH: "第 1 段写的是星期二。"}}}
	_, ex, err := repo.FinishPreparation(ctx, prep.ID, domain.PreparationOutcome(nil),
		domain.ReadingExercise{LessonID: lesson.ID, PassageID: passage.ID, Status: domain.ListeningExerciseCompleted, Generator: "openai:fake-model:reading_exercise_v1", Content: &content}, now)
	if err != nil {
		t.Fatal(err)
	}
	if code, out := f.save(t, "sec-learner-reading", ref("reading_item", ex.ID, 1), "Je pensais que c'était le lundi"); code != http.StatusCreated {
		t.Fatalf("save learner reading = %d %v", code, out)
	}
	return lesson.ID
}

func TestSections_ItemsStayOnTheExactVersionTheyCameFrom(t *testing.T) {
	f := newNotebookFixture(t)
	saveAllFour(t, f)
	learnerLesson := learnerReadingItem(t, f)
	before := notebookItems(t, f, "")
	ctx := context.Background()
	// Newer source versions after the save: a second listening transcript and
	// a second reading passage version (written directly to the repositories).
	if _, err := sqlite.NewListeningRepository(f.db).AddTranscript(ctx, f.ids["material"],
		[]domain.TranscriptSegment{{Index: 1, Text: "Le train pour Lyon partira avec trente minutes de retard."}}, false); err != nil {
		t.Fatal(err)
	}
	if _, err := sqlite.NewReadingRepository(f.db).AddPassage(ctx, learnerLesson,
		[]domain.ReadingSegment{{ID: "p1", Text: "La médiathèque ouvre le mercredi à dix heures."}}, time.Now().UTC()); err != nil {
		t.Fatal(err)
	}
	after := notebookItems(t, f, "")
	if len(after) != len(before) || len(after) != 5 {
		t.Fatalf("items %d -> %d, want 5", len(before), len(after))
	}
	for i := range after {
		b, a := before[i], after[i]
		skill := a["skill"]
		for _, k := range []string{"prompt", "reference", "quote", "explanation_en"} {
			if a[k] != b[k] {
				t.Errorf("%s: %s changed after a newer version: %v -> %v", skill, k, b[k], a[k])
			}
		}
		if b["latest_version"] != nil {
			t.Errorf("%s: latest_version %v before any newer version", skill, b["latest_version"])
		}
	}
	l, r := itemBySkill(t, after, "listening"), after[0] // newest first: the learner reading item
	if r["skill"] != "reading" || r["link"].(map[string]any)["reading_lesson_id"] != float64(learnerLesson) {
		t.Fatalf("newest item = %v", r)
	}
	if r["prompt"] != "Quel jour ouvre la médiathèque ?" || r["reference"] != "Le mardi." || r["reference_origin"] != "generated" {
		t.Errorf("learner reading item = %v", r)
	}
	if authored := itemBySkill(t, after[1:], "reading"); authored["latest_version"] != nil {
		t.Errorf("authored reading item: latest_version %v", authored["latest_version"])
	}
	if l["link"].(map[string]any)["listening_transcript_version"] != float64(1) || l["latest_version"] != float64(2) {
		t.Errorf("listening: link %v latest %v, want transcript 1 and latest 2", l["link"], l["latest_version"])
	}
	if r["link"].(map[string]any)["reading_passage_version"] != float64(1) || r["latest_version"] != float64(2) {
		t.Errorf("reading: link %v latest %v, want passage 1 and latest 2", r["link"], r["latest_version"])
	}
}

func TestSections_AnUnreadableSourceDegradesOneItemOnly(t *testing.T) {
	f := newNotebookFixture(t)
	saveAllFour(t, f)
	// Simulate a damaged or partially restored database: the listening
	// exercise row behind one saved item is gone.
	if _, err := f.db.Exec(`PRAGMA foreign_keys = OFF`); err != nil {
		t.Fatal(err)
	}
	if _, err := f.db.Exec(`DELETE FROM listening_exercises WHERE id = ?`, f.ids["listeningExercise"]); err != nil {
		t.Fatal(err)
	}
	items := notebookItems(t, f, "")
	if len(items) != 4 {
		t.Fatalf("got %d items, want all 4", len(items))
	}
	l := itemBySkill(t, items, "listening")
	if l["source_status"] != "missing" || l["prompt"] != "" || l["reference"] != "" {
		t.Errorf("listening: %v, want missing with nothing guessed", l)
	}
	if src := l["source"].(map[string]any); src["record_id"] != float64(f.ids["listeningExercise"]) || src["item"] != float64(2) {
		t.Errorf("listening: the stored reference must still be shown, got %v", src)
	}
	for _, skill := range []string{"reading", "writing", "speaking"} {
		if itemBySkill(t, items, skill)["source_status"] != "resolved" {
			t.Errorf("%s must still resolve", skill)
		}
	}
	entry := int64(l["entry_id"].(float64))
	code, out := doJSON(t, http.MethodGet, f.srv.URL+"/entries/"+itoa(entry)+"/source", "")
	if code != http.StatusOK || out["linked"] != true || out["item"].(map[string]any)["source_status"] != "missing" {
		t.Errorf("record source = %d %v", code, out)
	}
	if code, out := doJSON(t, http.MethodPut, f.srv.URL+"/mistake-notebook/items/"+itoa(entry)+"/retry", `{"marked": true}`); code != http.StatusOK {
		t.Errorf("marking an item with a missing source = %d %v", code, out)
	}
}

func TestSections_RepeatPracticeAppendsOnlyExplicitDecisions(t *testing.T) {
	f := newNotebookFixture(t)
	saveAllFour(t, f)
	w := itemBySkill(t, notebookItems(t, f, ""), "writing")
	entry := itoa(int64(w["entry_id"].(float64)))
	marks := func() int {
		var n int
		if err := f.db.QueryRow(`SELECT COUNT(*) FROM mistake_retry_marks`).Scan(&n); err != nil {
			t.Fatal(err)
		}
		return n
	}
	for i, marked := range []bool{true, false, true} {
		body := `{"marked": false}`
		if marked {
			body = `{"marked": true}`
		}
		if code, out := doJSON(t, http.MethodPut, f.srv.URL+"/mistake-notebook/items/"+entry+"/retry", body); code != http.StatusOK {
			t.Fatalf("decision %d = %d %v", i, code, out)
		}
	}
	if n := marks(); n != 3 {
		t.Fatalf("marks = %d, want 3 appended decisions", n)
	}
	// Two retry sessions read the marked list twice; reading writes nothing.
	for range 2 {
		got := notebookItems(t, f, "?marked=true")
		if len(got) != 1 || got[0]["entry_id"] != w["entry_id"] {
			t.Fatalf("marked list = %v", got)
		}
	}
	if n := marks(); n != 3 {
		t.Fatalf("marks = %d after reading, want 3", n)
	}
}
