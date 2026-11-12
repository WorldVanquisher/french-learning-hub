package http_test

// Mistake Notebook v1 end to end: the real handler, capture service (with the
// source resolver), SQLite repositories and Knowledge Library over one
// database. Each skill's item is produced by its real service or repository
// (fake model for writing and speaking feedback), then saved through
// POST /captures with a source_ref, exactly as the workbench does.

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/listening/listeningfake"
	"french-learning-app/internal/reading"
	"french-learning-app/internal/speaking"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
	"french-learning-app/internal/writing"
)

type notebookFixture struct {
	srv    *httptest.Server
	routes http.Handler
	db     *sql.DB
	ids    map[string]int64
}

// newNotebookFixture stores one completed item per skill, plus a failed
// listening exercise, and Concepts whose supporting units have known kinds.
func newNotebookFixture(t *testing.T) *notebookFixture {
	t.Helper()
	ctx := context.Background()
	db, err := sqlite.Open(filepath.Join(t.TempDir(), "notebook.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })
	must := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	ids := map[string]int64{}
	// Listening: a material, a transcript and two exercises (one failed).
	lrepo := sqlite.NewListeningRepository(db)
	mat, tr, err := lrepo.CreateMaterial(ctx, domain.ListeningMaterial{VideoID: "aBcDeFgHiJk", SourceURL: "https://www.youtube.com/watch?v=aBcDeFgHiJk", Title: "Annonce en gare"},
		[]domain.TranscriptSegment{{Index: 1, Text: "Le train pour Lyon partira avec vingt minutes de retard."}, {Index: 2, Text: "Merci de votre compréhension."}}, false)
	must(err)
	content := domain.ListeningExerciseContent{Items: []domain.ListeningItem{
		{Kind: "gist", Question: "De quoi parle l'annonce ?", ExpectedAnswer: "D'un retard de train.", RationaleEN: "Segment 1 announces a delay.", RationaleZH: "第 1 段宣布了晚点。", Segments: []int{1}},
		{Kind: "detail", Question: "Combien de minutes de retard ?", ExpectedAnswer: "Vingt minutes.", RationaleEN: "Segment 1 says twenty.", RationaleZH: "第 1 段说是二十分钟。", Segments: []int{1}},
	}, Annotations: []domain.ListeningAnnotation{}}
	ex, err := lrepo.CreateExercise(ctx, domain.ListeningExercise{MaterialID: mat.ID, TranscriptID: tr.ID, Status: domain.ListeningExerciseCompleted, Generator: "openai:fake-model:listening_exercise_v1", Content: &content})
	must(err)
	failed, err := lrepo.CreateExercise(ctx, domain.ListeningExercise{MaterialID: mat.ID, TranscriptID: tr.ID, Status: domain.ListeningExerciseFailed, FailureCode: domain.ListeningFailureTimeout, Generator: "openai:fake-model:listening_exercise_v1"})
	must(err)
	ids["material"], ids["listeningExercise"], ids["failedListening"] = mat.ID, ex.ID, failed.ID
	// Reading: an authored example (no provider call).
	rsvc, err := application.NewReadingService(sqlite.NewReadingRepository(db), nil, reading.ExamplePack())
	must(err)
	rv, _, err := rsvc.ImportExample(ctx, "rd-notice-piscine")
	must(err)
	ids["readingLesson"], ids["readingExercise"] = rv.Lesson.ID, rv.Exercises[0].ID
	// Writing: v1 of the authored invitation and its grounded feedback.
	wmodel := listeningfake.NewResponses(t, writingKey, feedbackFixture(t))
	wsvc, err := application.NewWritingService(sqlite.NewWritingRepository(db), writing.NewOpenAI(writingKey, "fake-model", wmodel.URL(), 2*time.Second), writing.ExamplePrompts())
	must(err)
	task, _, err := wsvc.StartPrompt(ctx, "wr-invitation-anniversaire")
	must(err)
	wv, err := wsvc.AddDraft(ctx, task.Task.ID, exampleDraft(t))
	must(err)
	wres, _, err := wsvc.RequestFeedback(ctx, application.WritingFeedbackRequestInput{DraftID: wv.Drafts[0].ID})
	must(err)
	ids["writingTask"], ids["writingDraft"], ids["writingFeedback"] = task.Task.ID, wv.Drafts[0].ID, wres.Feedback.ID
	// Speaking: a typed take, its confirmed transcript and grounded feedback.
	smodel := listeningfake.NewResponses(t, speakingKey, speakingFeedbackFixture(t))
	ssvc, err := application.NewSpeakingService(sqlite.NewSpeakingRepository(db), nil, speaking.NewOpenAI(speakingKey, "fake-model", smodel.URL(), 2*time.Second), speaking.ExamplePrompts())
	must(err)
	sex, _, err := ssvc.StartPrompt(ctx, "sp-invitation-reponse")
	must(err)
	sv, err := ssvc.AddTake(ctx, sex.Exercise.ID, domain.SpeakingTake{AudioSource: domain.SpeakingAudioNone})
	must(err)
	sv, err = ssvc.AddTranscript(ctx, sv.Takes[0].ID, speakingExample(t), nil)
	must(err)
	sres, _, err := ssvc.RequestFeedback(ctx, application.SpeakingFeedbackRequestInput{TranscriptID: sv.Transcripts[0].ID})
	must(err)
	ids["speakingExercise"], ids["speakingTake"], ids["speakingTranscript"], ids["speakingFeedback"] = sex.Exercise.ID, sv.Takes[0].ID, sv.Transcripts[0].ID, sres.Feedback.ID

	// Concepts with known supporting kinds (Grammar / Vocabulary views).
	entryRepo := sqlite.NewEntryRepository(db)
	analysisRepo := sqlite.NewAnalysisRepository(db)
	feedbackRepo := sqlite.NewFeedbackRepository(db)
	knowledgeRepo := sqlite.NewKnowledgeRepository(db)
	conceptRepo := sqlite.NewConceptRepository(db)
	extractor := &scriptedExtractor{calls: [][]domain.ExtractedUnit{
		{{Kind: domain.KindGrammar, Canonical: "accord du participe passé avec être", Statement: "Avec être, le participe s'accorde avec le sujet.", Confidence: 0.9},
			{Kind: domain.KindVocabulary, Canonical: "apporter", Statement: "Apporter : faire venir une chose avec soi.", Confidence: 0.9},
			{Kind: domain.KindGrammar, Canonical: "futur simple de venir", Statement: "Je viendrai : futur de venir.", Confidence: 0.9},
			{Kind: domain.KindVocabulary, Canonical: "venir", Statement: "Venir : se déplacer vers ici.", Confidence: 0.9},
			{Kind: domain.KindMorphology, Canonical: "conjugaison de prendre", Statement: "Que je prenne : subjonctif de prendre.", Confidence: 0.9}},
		{{Kind: domain.KindVocabulary, Canonical: "amener", Statement: "Amener : faire venir une personne.", Confidence: 0.9}},
		{{Kind: domain.KindUsage, Canonical: "registre", Statement: "Forme orale.", Confidence: 0.9}},
	}}
	knowledgeSvc := application.NewKnowledgeService(entryRepo, analysisRepo, feedbackRepo, knowledgeRepo, sqlite.NewAdmissionRepository(db), extractor)
	conceptSvc := application.NewConceptService(knowledgeRepo, conceptRepo, conceptRepo)
	newEntry := func(input string) int64 {
		e, err := entryRepo.Create(ctx, domain.NewEntryInput{OriginalInput: input, OriginalContext: "contexte synthétique"})
		must(err)
		_, err = analysisRepo.Create(ctx, e.ID, domain.AnalysisResult{Category: "grammar", Explanation: "explication", Confidence: 0.8}, "rule-based:test")
		must(err)
		return e.ID
	}
	extract := func(entryID int64) []int64 {
		v, err := knowledgeSvc.Extract(ctx, entryID)
		must(err)
		out := []int64{}
		for _, u := range v.Units {
			out = append(out, u.Unit.ID)
		}
		return out
	}
	concept := func(target, intent string, seed int64) int64 {
		c, _, err := conceptSvc.CreateConcept(ctx, domain.ConceptIdentity{Target: target, PedagogicalIntent: intent}, &seed, true)
		must(err)
		return c.ID
	}
	u := extract(newEntry("Questions sur une invitation"))
	ids["Cgrammar"] = concept("accord du participe passé avec être", "grammar", u[0])
	ids["Cvocab"] = concept("apporter", "vocabulary", u[1])
	ids["Cmixed"] = concept("venir au futur", "grammar", u[2])
	_, err = conceptSvc.ResolveSame(ctx, u[3], ids["Cmixed"])
	must(err)
	ids["Cother"] = concept("subjonctif de prendre", "morphology", u[4])
	orphan := newEntry("Amener ou apporter ?")
	ids["Corphan"] = concept("amener", "vocabulary", extract(orphan)[0])
	extract(orphan) // a new extraction: the seed unit is historical, the Concept is orphaned

	library := application.NewKnowledgeLibraryService(conceptRepo, knowledgeRepo, entryRepo, analysisRepo, feedbackRepo, application.NewEffectiveAnnotationService(conceptRepo, conceptRepo))
	resolver := application.NewMistakeSourceResolver(lrepo, sqlite.NewReadingRepository(db), sqlite.NewWritingRepository(db), sqlite.NewSpeakingRepository(db))
	notebook := application.NewMistakeNotebookService(sqlite.NewNotebookRepository(db), resolver, entryRepo, library)
	annotation := application.NewEffectiveAnnotationService(conceptRepo, conceptRepo)
	handler := transporthttp.NewHandler(
		application.NewEntryService(entryRepo), application.NewAnalysisService(entryRepo, analysisRepo, nil),
		application.NewFeedbackService(feedbackRepo), application.NewEffectiveAnalysisService(analysisRepo, feedbackRepo),
		application.NewInventoryService(sqlite.NewInventoryRepository(db)),
		application.NewCaptureService(sqlite.NewCaptureRepository(db), application.WithSourceResolver(resolver)),
		knowledgeSvc, conceptSvc, annotation, application.NewConceptAnnotationDatasetService(annotation, knowledgeRepo, conceptRepo),
		transporthttp.WithKnowledgeLibrary(library), transporthttp.WithMistakeNotebook(notebook),
	)
	f := &notebookFixture{routes: handler.Routes(), db: db, ids: ids}
	f.srv = httptest.NewServer(f.routes)
	t.Cleanup(f.srv.Close)
	return f
}

func (f *notebookFixture) save(t *testing.T, captureID string, ref map[string]any, input string) (int, map[string]any) {
	t.Helper()
	doc := map[string]any{"schema_version": "learning_capture_v1", "capture_id": captureID, "source": "manual", "original_input": input, "original_context": "contexte"}
	if ref != nil {
		doc["source_ref"] = ref
	}
	raw, _ := json.Marshal(doc)
	return doJSON(t, http.MethodPost, f.srv.URL+"/captures", string(raw))
}

func ref(typ string, record int64, item int) map[string]any {
	return map[string]any{"type": typ, "record_id": record, "item": item}
}

func TestNotebook_EachSkillSavesWithAnExactSourceLink(t *testing.T) {
	f := newNotebookFixture(t)
	rr := ref("reading_item", f.ids["readingExercise"], 2)
	rr["attempt"] = "  Le lundi.  "
	cases := []struct {
		name, captureID string
		ref             map[string]any
		link            map[string]any
	}{
		{"listening", "listening-nb-1", ref("listening_item", f.ids["listeningExercise"], 2),
			map[string]any{"listening_material_id": f.ids["material"], "listening_exercise_id": f.ids["listeningExercise"], "listening_transcript_version": 1}},
		{"reading", "reading-nb-1", rr,
			map[string]any{"reading_lesson_id": f.ids["readingLesson"], "reading_passage_version": 1, "reading_exercise_id": f.ids["readingExercise"]}},
		{"writing", "writing-nb-1", ref("writing_correction", f.ids["writingFeedback"], 1),
			map[string]any{"writing_task_id": f.ids["writingTask"], "writing_draft_id": f.ids["writingDraft"], "writing_draft_version": 1, "writing_feedback_id": f.ids["writingFeedback"]}},
		{"speaking", "speaking-nb-1", ref("speaking_improvement", f.ids["speakingFeedback"], 2),
			map[string]any{"speaking_exercise_id": f.ids["speakingExercise"], "speaking_take_id": f.ids["speakingTake"], "speaking_take_number": 1,
				"speaking_transcript_id": f.ids["speakingTranscript"], "speaking_transcript_version": 1, "speaking_feedback_id": f.ids["speakingFeedback"]}},
	}
	entries := map[string]int64{}
	for _, c := range cases {
		status, out := f.save(t, c.captureID, c.ref, "Ce que j'ai manqué ("+c.name+")")
		if status != http.StatusCreated {
			t.Fatalf("%s: %d %v", c.name, status, out)
		}
		entries[c.name] = int64(out["entry_id"].(float64))
		_, src := doJSON(t, http.MethodGet, fmt.Sprintf("%s/entries/%d/source", f.srv.URL, entries[c.name]), "")
		if src["linked"] != true || path(src, "item", "skill") != c.name {
			t.Fatalf("%s source: %v", c.name, src)
		}
		got := path(src, "item", "link").(map[string]any)
		for k, v := range c.link {
			if fmt.Sprint(got[k]) != fmt.Sprint(v) {
				t.Errorf("%s link %s = %v, want %v (%v)", c.name, k, got[k], v, got)
			}
		}
		if len(got) != len(c.link) {
			t.Errorf("%s link has extra fields: %v", c.name, got)
		}
	}
	// What each item shows comes from its stored source, not from the prose.
	_, list := doJSON(t, http.MethodGet, f.srv.URL+"/mistake-notebook/items", "")
	items := list["items"].([]any)
	if len(items) != 4 || path(items[0], "skill") != "speaking" || path(items[3], "skill") != "listening" || !strings.Contains(list["unlinked_notice"].(string), "never linked by guessing") {
		t.Fatalf("list: %v", list)
	}
	byskill := map[string]any{}
	for _, it := range items {
		byskill[path(it, "skill").(string)] = it
	}
	if path(byskill["listening"], "prompt") != "Combien de minutes de retard ?" || path(byskill["listening"], "reference") != "Vingt minutes." || path(byskill["listening"], "quote") != nil ||
		path(byskill["listening"], "source", "attempt") != nil {
		t.Errorf("listening item: %v", byskill["listening"])
	}
	if path(byskill["reading"], "source", "attempt") != "Le lundi." || path(byskill["reading"], "title") == "" {
		t.Errorf("reading item: %v", byskill["reading"])
	}
	if path(byskill["writing"], "quote") != "Je suis arrivé vers 20 heures" || path(byskill["writing"], "reference") == "" || path(byskill["writing"], "hint_en") == nil {
		t.Errorf("writing item: %v", byskill["writing"])
	}
	if path(byskill["speaking"], "quote") != "Je vais amener un dessert" || path(byskill["speaking"], "reference") != "Je vais apporter un dessert" ||
		path(byskill["speaking"], "record", "original_input") != "Ce que j'ai manqué (speaking)" {
		t.Errorf("speaking item: %v", byskill["speaking"])
	}
	for _, skill := range []string{"listening", "reading", "writing", "speaking"} {
		_, one := doJSON(t, http.MethodGet, f.srv.URL+"/mistake-notebook/items?skill="+skill, "")
		if n := len(one["items"].([]any)); n != 1 || path(one["items"].([]any)[0], "entry_id") != float64(entries[skill]) {
			t.Errorf("skill=%s: %v", skill, one)
		}
	}
	if status, _ := doJSON(t, http.MethodGet, f.srv.URL+"/mistake-notebook/items?skill=grammar", ""); status != http.StatusBadRequest {
		t.Errorf("unknown skill: %d", status)
	}
	// Saving creates ordinary records only: no Concept, no analysis.
	if countRows(t, f.db, "learning_capture_sources") != 4 || countRows(t, f.db, "entry_analyses") != 2 {
		t.Fatalf("rows: sources %d analyses %d", countRows(t, f.db, "learning_capture_sources"), countRows(t, f.db, "entry_analyses"))
	}
}

func TestNotebook_DuplicatesReplaysInvalidSourcesAndOldRecords(t *testing.T) {
	f := newNotebookFixture(t)
	wr := ref("writing_correction", f.ids["writingFeedback"], 2)
	status, first := f.save(t, "writing-dup-a", wr, "« Je suis pas sûr » → « Je ne suis pas sûr »")
	if status != http.StatusCreated {
		t.Fatalf("first save: %d %v", status, first)
	}
	entry := first["entry_id"]
	// The same capture replays (a lost response resent).
	if status, again := f.save(t, "writing-dup-a", wr, "« Je suis pas sûr » → « Je ne suis pas sûr »"); status != http.StatusOK || again["entry_id"] != entry || again["created"] != false {
		t.Fatalf("replay: %d %v", status, again)
	}
	// The same item from a second form (a new capture_id) names the existing record.
	status, dup := f.save(t, "writing-dup-b", wr, "un autre texte")
	if status != http.StatusConflict || dup["code"] != "source_already_saved" || dup["entry_id"] != entry {
		t.Fatalf("duplicate: %d %v", status, dup)
	}
	// The same capture_id with another source is a conflicting capture.
	if status, _ := f.save(t, "writing-dup-a", ref("writing_correction", f.ids["writingFeedback"], 1), "« Je suis pas sûr » → « Je ne suis pas sûr »"); status != http.StatusConflict {
		t.Fatalf("same id, other source: %d", status)
	}
	entriesBefore := countRows(t, f.db, "learning_entries")
	for name, r := range map[string]map[string]any{
		"unknown record":            ref("listening_item", 9999, 1),
		"failed exercise":           ref("listening_item", f.ids["failedListening"], 1),
		"item out of range":         ref("listening_item", f.ids["listeningExercise"], 3),
		"writing quote not found":   ref("writing_correction", f.ids["writingFeedback"], 4),
		"speaking quote not found":  ref("speaking_improvement", f.ids["speakingFeedback"], 4),
		"unknown type":              ref("writing_draft", f.ids["writingDraft"], 1),
		"attempt on writing":        {"type": "writing_correction", "record_id": f.ids["writingFeedback"], "item": 1, "attempt": "mon texte"},
		"reading record as writing": ref("writing_correction", f.ids["readingExercise"]+5000, 1),
	} {
		if status, out := f.save(t, "invalid-"+strings.ReplaceAll(name, " ", "-"), r, "x"); status != http.StatusUnprocessableEntity {
			t.Errorf("%s: %d %v", name, status, out)
		}
	}
	if status, _ := f.save(t, "bad-shape", map[string]any{"type": "listening_item", "record_id": 1, "item": 1, "extra": true}, "x"); status != http.StatusBadRequest {
		t.Errorf("unknown source_ref field: %d", status)
	}
	if countRows(t, f.db, "learning_entries") != entriesBefore {
		t.Fatal("a refused source stored a record")
	}
	// A record saved without a source (as before Mistake Notebook v1) is shown honestly.
	status, old := f.save(t, "reading-old-style", nil, "Un point manqué, sans lien")
	if status != http.StatusCreated {
		t.Fatalf("old-style save: %d", status)
	}
	_, src := doJSON(t, http.MethodGet, fmt.Sprintf("%s/entries/%d/source", f.srv.URL, int64(old["entry_id"].(float64))), "")
	if src["linked"] != false || !strings.Contains(src["notice"].(string), "not linked by guessing") {
		t.Fatalf("unlinked record: %v", src)
	}
	if status, _ := doJSON(t, http.MethodGet, f.srv.URL+"/entries/99999/source", ""); status != http.StatusNotFound {
		t.Errorf("unknown record: %d", status)
	}
	_, list := doJSON(t, http.MethodGet, f.srv.URL+"/mistake-notebook/items", "")
	if len(list["items"].([]any)) != 1 {
		t.Fatalf("only the linked record is a notebook item: %v", list)
	}
}

func TestNotebook_RetryMarksAreExplicitAndAppendOnly(t *testing.T) {
	f := newNotebookFixture(t)
	_, a := f.save(t, "listening-mark", ref("listening_item", f.ids["listeningExercise"], 1), "a")
	_, b := f.save(t, "speaking-mark", ref("speaking_improvement", f.ids["speakingFeedback"], 1), "b")
	_, plain := f.save(t, "plain-mark", nil, "c")
	put := func(entry any, marked bool) (int, map[string]any) {
		t.Helper()
		status, out, _, err := keyed(t, http.DefaultClient, http.MethodPut, fmt.Sprintf("%s/mistake-notebook/items/%d/retry", f.srv.URL, int64(entry.(float64))), "", fmt.Sprintf(`{"marked":%v}`, marked))
		if err != nil {
			t.Fatal(err)
		}
		return status, out
	}
	if status, out := put(a["entry_id"], true); status != http.StatusOK || out["changed"] != true || path(out, "item", "retry", "marked") != true {
		t.Fatalf("mark: %d %v", status, out)
	}
	if _, out := put(a["entry_id"], true); out["changed"] != false {
		t.Fatalf("marking again must not add a row: %v", out)
	}
	put(b["entry_id"], true)
	_, marked := doJSON(t, http.MethodGet, f.srv.URL+"/mistake-notebook/items?marked=true", "")
	if len(marked["items"].([]any)) != 2 {
		t.Fatalf("marked list: %v", marked)
	}
	if _, out := put(a["entry_id"], false); out["changed"] != true || path(out, "item", "retry", "marked") != false {
		t.Fatalf("unmark: %v", out)
	}
	if countRows(t, f.db, "mistake_retry_marks") != 3 {
		t.Fatalf("append-only rows: %d", countRows(t, f.db, "mistake_retry_marks"))
	}
	_, marked = doJSON(t, http.MethodGet, f.srv.URL+"/mistake-notebook/items?marked=true", "")
	if items := marked["items"].([]any); len(items) != 1 || path(items[0], "skill") != "speaking" {
		t.Fatalf("marked after unmark: %v", marked)
	}
	if status, _ := put(plain["entry_id"], true); status != http.StatusNotFound {
		t.Errorf("a record without a source is not a notebook record: %d", status)
	}
	if status, _, _, _ := keyed(t, http.DefaultClient, http.MethodPut, fmt.Sprintf("%s/mistake-notebook/items/%d/retry", f.srv.URL, int64(a["entry_id"].(float64))), "", `{}`); status != http.StatusUnprocessableEntity {
		t.Errorf("missing marked: %d", status)
	}
	// A mark is not a Concept judgment or a score.
	if countRows(t, f.db, "unit_concept_links") != 6 || countRows(t, f.db, "unit_resolution_judgments") != 0 {
		t.Fatalf("marks touched annotation tables: links %d", countRows(t, f.db, "unit_concept_links"))
	}
}

func TestNotebook_GrammarAndVocabularyViewsClassifyOnlyBySupportingKinds(t *testing.T) {
	f := newNotebookFixture(t)
	view := func(kind, q string) (int, map[string]any) {
		return doJSON(t, http.MethodGet, f.srv.URL+"/mistake-notebook/concepts?kind="+kind+"&q="+q, "")
	}
	ids := func(out map[string]any) []int64 {
		got := []int64{}
		for _, c := range out["concepts"].([]any) {
			got = append(got, int64(path(c, "concept_id").(float64)))
		}
		return got
	}
	_, g := view("grammar", "")
	if fmt.Sprint(ids(g)) != fmt.Sprint([]int64{f.ids["Cgrammar"]}) || g["rule"] != "concept_kind_view_v1" || path(g["concepts"].([]any)[0], "kinds").([]any)[0] != "grammar" {
		t.Fatalf("grammar: %v", g)
	}
	_, v := view("vocabulary", "")
	if fmt.Sprint(ids(v)) != fmt.Sprint([]int64{f.ids["Cvocab"]}) {
		t.Fatalf("vocabulary (the orphaned 'amener' has no support and is not listed): %v", v)
	}
	_, u := view("unclassified", "")
	reasons := map[int64]any{}
	for _, c := range u["concepts"].([]any) {
		reasons[int64(path(c, "concept_id").(float64))] = path(c, "reason")
	}
	if len(reasons) != 2 || reasons[f.ids["Cmixed"]] != "mixed_kinds" || reasons[f.ids["Cother"]] != "other_kind" || g["classified"] != float64(4) {
		t.Fatalf("unclassified: %v (classified %v)", u, g["classified"])
	}
	// The library's search narrows the view; Concept IDs are the library's.
	if _, out := view("vocabulary", "apporter"); len(ids(out)) != 1 {
		t.Fatalf("query: %v", out)
	}
	if _, out := view("grammar", "apporter"); len(ids(out)) != 0 {
		t.Fatalf("query in another class: %v", out)
	}
	if status, _ := view("pronunciation", ""); status != http.StatusBadRequest {
		t.Errorf("unknown kind: %d", status)
	}
	if status, _ := view("grammar", "x"); status != http.StatusBadRequest {
		t.Errorf("unsearchable query: %d", status)
	}
}

func TestNotebook_NotInThePublicDemo(t *testing.T) {
	f := newNotebookFixture(t)
	demo := httptest.NewServer(transporthttp.NewPublicDemoBoundary(f.routes, false))
	t.Cleanup(demo.Close)
	for _, prefix := range []string{"", "/api"} {
		for _, p := range []string{"/mistake-notebook/items", "/mistake-notebook/concepts?kind=grammar", "/entries/1/source"} {
			if status, _ := doJSON(t, http.MethodGet, demo.URL+prefix+p, ""); status != http.StatusNotFound {
				t.Errorf("GET %s%s in the demo: %d", prefix, p, status)
			}
		}
		if status, _, _, _ := keyed(t, http.DefaultClient, http.MethodPut, demo.URL+prefix+"/mistake-notebook/items/1/retry", "", `{"marked":true}`); status != http.StatusMethodNotAllowed {
			t.Errorf("PUT %s retry in the demo: %d", prefix, status)
		}
	}
}
