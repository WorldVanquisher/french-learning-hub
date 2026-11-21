package http_test

import (
	"context"
	"database/sql"
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

// Vocabulary (VOC): save an approved vocabulary Concept with its example, find
// it, remove it, and every edge the queue names, through the real handler and a
// fresh SQLite database (migrations 001-022). Synthetic French only.

// keyedExtractor answers by a phrase of the record's original input: each record has its own
// sequence of extractions, whatever order the test extracts in.
type keyedExtractor struct {
	scripts map[string][][]domain.ExtractedUnit
	calls   map[string]int
}

func (k *keyedExtractor) Name() string { return "stub:vocabulary:knowledge_extraction_v1" }
func (k *keyedExtractor) Extract(_ context.Context, src domain.ExtractionSource) (domain.ExtractionResult, error) {
	for key, versions := range k.scripts {
		if strings.Contains(src.OriginalInput, key) {
			n := k.calls[key]
			k.calls[key] = n + 1
			return domain.ExtractionResult{Units: versions[min(n, len(versions)-1)]}, nil
		}
	}
	return domain.ExtractionResult{}, nil
}

type vocabFixture struct {
	db      *sql.DB
	path    string
	srv     *httptest.Server
	routes  http.Handler
	ids     map[string]int64
	extract func(entryID int64) []int64
	concept *application.ConceptService
	vocab   *application.VocabularyService
}

func newVocabFixture(t *testing.T) *vocabFixture {
	t.Helper()
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "vocab.db")
	db, err := sqlite.Open(path)
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
	entryRepo := sqlite.NewEntryRepository(db)
	analysisRepo := sqlite.NewAnalysisRepository(db)
	feedbackRepo := sqlite.NewFeedbackRepository(db)
	knowledgeRepo := sqlite.NewKnowledgeRepository(db)
	conceptRepo := sqlite.NewConceptRepository(db)
	variants := func(en, zh string) domain.ExplanationVariants { return domain.ExplanationVariants{EN: &en, ZH: &zh} }
	ex := "Pouvez-vous apporter le dessert ?"
	vocab := func(canonical, statement string, v *domain.ExplanationVariants, example *string) domain.ExtractedUnit {
		u := domain.ExtractedUnit{Kind: domain.KindVocabulary, Canonical: canonical, Statement: statement, Example: example, Confidence: 0.9}
		if v != nil {
			u.Statements = *v
		}
		return u
	}
	vv := func(en, zh string) *domain.ExplanationVariants { x := variants(en, zh); return &x }
	long := "il pleut des cordes, n'est-ce pas ? — « oui » (vraiment) !"
	// Units are chosen by a phrase of the record (each record's own versions, in order), so a test
	// may add records and re-extract in any order.
	extractor := &keyedExtractor{calls: map[string]int{}, scripts: map[string][][]domain.ExtractedUnit{
		// entry A: a vocabulary unit with both meanings and a sentence, and a grammar unit; then a superseding extraction
		"dîner chez des amis": {
			{vocab("apporter", "to bring (a thing)", vv("to bring (a thing)", "带来（东西）"), &ex),
				{Kind: domain.KindGrammar, Canonical: "accord du participe passé", Statement: "Agreement with être.", Confidence: 0.9}},
			{vocab("apporter", "to bring", nil, nil)},
		},
		// entry B: the same word from another record, no recorded meaning languages
		"Apporter ou amener": {{vocab("apporter", "Apporter : faire venir une chose avec soi.", nil, nil)}},
		// entry C: a multiword phrase, spacing kept
		"grasse matinée": {{vocab("faire  la grasse matinée", "to sleep in", vv("to sleep in", "睡懒觉"), nil)}},
		// entry D: the same spelling, another meaning (a separate Concept)
		"apporter une solution": {{vocab("apporter", "to provide (a solution)", vv("to provide (a solution)", "提供（解决办法）"), nil)}},
		// identity edges (VOC-101 to VOC-104, VOC-039)
		"le chat dort":         {{vocab("chat", "cat (French word)", vv("cat (French word)", "猫"), nil)}},
		"un chat en ligne":     {{vocab("chat", "online chat (English loanword)", vv("online chat (English loanword)", "在线聊天"), nil)}},
		"aujourd’hui typo":     {{vocab("aujourd’hui", "today (typographic apostrophe)", nil, nil)}},
		"aujourd'hui droit":    {{vocab("aujourd'hui", "today (straight apostrophe)", nil, nil)}},
		"café composé":         {{vocab("café", "coffee (é as one character)", nil, nil)}},
		"cafe\u0301 décomposé": {{vocab("cafe\u0301", "coffee (e + combining accent)", nil, nil)}},
		"longue expression":    {{vocab(long, "it is raining cats and dogs, isn't it? — \"yes\" (really)!", nil, nil)}},
	}}
	knowledgeSvc := application.NewKnowledgeService(entryRepo, analysisRepo, feedbackRepo, knowledgeRepo, sqlite.NewAdmissionRepository(db), extractor)
	conceptSvc := application.NewConceptService(knowledgeRepo, conceptRepo, conceptRepo)
	ids := map[string]int64{}
	newEntry := func(input, context string) int64 {
		e, err := entryRepo.Create(ctx, domain.NewEntryInput{OriginalInput: input, OriginalContext: context})
		must(err)
		_, err = analysisRepo.Create(ctx, e.ID, domain.AnalysisResult{Category: "vocabulary", Explanation: "explication", Confidence: 0.8}, "rule-based:test")
		must(err)
		return e.ID
	}
	f := &vocabFixture{db: db, path: path, ids: ids, concept: conceptSvc}
	f.extract = func(entryID int64) []int64 {
		v, err := knowledgeSvc.Extract(ctx, entryID)
		must(err)
		out := []int64{}
		for _, u := range v.Units {
			out = append(out, u.Unit.ID)
		}
		return out
	}
	concept := func(target, intent, scope string, seed int64) int64 {
		c, _, err := conceptSvc.CreateConcept(ctx, domain.ConceptIdentity{Target: target, PedagogicalIntent: intent, Scope: scope}, &seed, true)
		must(err)
		return c.ID
	}
	ids["entryA"] = newEntry("Comment dit-on « bring » quand on va dîner chez des amis ?", "Invitation : « Pouvez-vous apporter le dessert ? »")
	a := f.extract(ids["entryA"])
	ids["unitA"], ids["unitGrammar"] = a[0], a[1]
	ids["Capporter"] = concept("apporter", "vocabulary", "", a[0])
	ids["Cgrammar"] = concept("accord du participe passé", "grammar", "", a[1])
	ids["entryB"] = newEntry("Apporter ou amener ?", "Un ami m'a corrigé : on apporte une chose.")
	ids["unitB"] = f.extract(ids["entryB"])[0]
	_, err = conceptSvc.ResolveSame(ctx, ids["unitB"], ids["Capporter"])
	must(err)
	ids["entryC"] = newEntry("Que veut dire « faire la grasse matinée » ?", "Le dimanche, je fais la grasse matinée jusqu'à dix heures.")
	ids["unitC"] = f.extract(ids["entryC"])[0]
	ids["Cphrase"] = concept("faire la grasse matinée", "vocabulary", "", ids["unitC"])
	ids["entryD"] = newEntry("« apporter une solution » : c'est le même verbe ?", "Le rapport apporte une solution au problème.")
	ids["unitD"] = f.extract(ids["entryD"])[0]
	ids["CapporterFig"] = concept("apporter", "vocabulary", "figuré: fournir", ids["unitD"])
	longContext := strings.Repeat("Il pleuvait depuis le matin, et « il pleut des cordes » revenait dans chaque conversation. ", 20)
	edge := func(key, input, target, scope string) {
		context := "contexte synthétique"
		if key == "Long" {
			context = longContext
		}
		ids["entry"+key] = newEntry(input, context)
		ids["unit"+key] = f.extract(ids["entry"+key])[0]
		ids["C"+key] = concept(target, "vocabulary", scope, ids["unit"+key])
	}
	edge("ChatFr", "« le chat dort » : chat veut dire quoi ?", "chat", "mot français: animal")
	edge("ChatEn", "« un chat en ligne » : c'est de l'anglais ?", "chat", "emprunt anglais: conversation en ligne")
	edge("AujTypo", "aujourd’hui typo : comment l'écrire ?", "aujourd’hui", "")
	edge("AujStraight", "aujourd'hui droit : avec une apostrophe droite ?", "aujourd'hui", "")
	edge("CafeNFC", "café composé : un seul caractère", "café", "")
	edge("CafeNFD", "cafe\u0301 décomposé : e et un accent combinant", "cafe\u0301", "")
	edge("Long", "longue expression : il pleut des cordes", long, "")

	library := application.NewKnowledgeLibraryService(conceptRepo, knowledgeRepo, entryRepo, analysisRepo, feedbackRepo, application.NewEffectiveAnnotationService(conceptRepo, conceptRepo))
	annotation := application.NewEffectiveAnnotationService(conceptRepo, conceptRepo)
	f.vocab = application.NewVocabularyService(sqlite.NewVocabularyRepository(db), library)
	build := func() http.Handler {
		return transporthttp.NewHandler(
			application.NewEntryService(entryRepo), application.NewAnalysisService(entryRepo, analysisRepo, nil),
			application.NewFeedbackService(feedbackRepo), application.NewEffectiveAnalysisService(analysisRepo, feedbackRepo),
			application.NewInventoryService(sqlite.NewInventoryRepository(db)),
			application.NewCaptureService(sqlite.NewCaptureRepository(db)),
			knowledgeSvc, conceptSvc, annotation, application.NewConceptAnnotationDatasetService(annotation, knowledgeRepo, conceptRepo),
			transporthttp.WithKnowledgeLibrary(library),
			transporthttp.WithVocabulary(f.vocab),
		).Routes()
	}
	f.routes = build()
	f.srv = httptest.NewServer(f.routes)
	t.Cleanup(f.srv.Close)
	return f
}

func (f *vocabFixture) save(t *testing.T, concept, unit int64) (int, map[string]any) {
	t.Helper()
	return doJSON(t, http.MethodPut, fmt.Sprintf("%s/vocabulary/%d", f.srv.URL, concept), fmt.Sprintf(`{"unit_id": %d}`, unit))
}

func (f *vocabFixture) list(t *testing.T, q string) map[string]any {
	t.Helper()
	status, out := doJSON(t, http.MethodGet, f.srv.URL+"/vocabulary?q="+strings.ReplaceAll(q, " ", "+"), "")
	if status != http.StatusOK {
		t.Fatalf("list %q: %d %v", q, status, out)
	}
	return out
}

func (f *vocabFixture) count(t *testing.T, table string) int {
	t.Helper()
	var n int
	if err := f.db.QueryRow("SELECT count(*) FROM " + table).Scan(&n); err != nil {
		t.Fatal(err)
	}
	return n
}

func itemIDs(out map[string]any) []int64 {
	ids := []int64{}
	for _, it := range out["items"].([]any) {
		ids = append(ids, int64(path(it, "concept_id").(float64)))
	}
	return ids
}

func TestVocabulary_SaveFindReloadAndShowItsSource(t *testing.T) {
	f := newVocabFixture(t)
	// VOC-036: an empty book is its own state (saved 0, no items).
	if out := f.list(t, ""); out["saved"] != 0.0 || len(out["items"].([]any)) != 0 || out["schema_version"] != "vocabulary_v1" {
		t.Fatalf("empty book: %v", out)
	}
	status, out := f.save(t, f.ids["Capporter"], f.ids["unitA"])
	if status != http.StatusOK || out["changed"] != true || out["saved_now"] != true || out["example_added"] != true {
		t.Fatalf("first save: %d %v", status, out)
	}
	item := out["item"]
	ex := path(item, "examples").([]any)[0]
	// VOC-008, VOC-051, VOC-052: the meaning (generated, with its extractor) and the learner's own words, exactly.
	if path(item, "concept", "target") != "apporter" || path(ex, "term") != "apporter" || path(ex, "meaning") != "to bring (a thing)" ||
		path(ex, "meanings", "zh") != "带来（东西）" || path(ex, "sentence") != "Pouvez-vous apporter le dessert ?" ||
		path(ex, "extractor") != "stub:vocabulary:knowledge_extraction_v1" || path(ex, "status") != "current" ||
		path(ex, "source", "original_input") != "Comment dit-on « bring » quand on va dîner chez des amis ?" ||
		path(ex, "source", "original_context") != "Invitation : « Pouvez-vous apporter le dessert ? »" {
		t.Fatalf("saved item: %v", item)
	}
	// VOC-017: the example records its source revision.
	if path(ex, "unit_id") != float64(f.ids["unitA"]) || path(ex, "entry_id") != float64(f.ids["entryA"]) || path(ex, "extraction_version") != 1.0 || path(ex, "newer_extraction") != false {
		t.Fatalf("revision: %v", ex)
	}
	// VOC-010: two units support the Concept, so Recall Practice has candidates.
	if path(item, "review_units") != 2.0 {
		t.Fatalf("review units: %v", path(item, "review_units"))
	}
	// VOC-007 / VOC-082: a fresh handler over the same database (a reload) lists it.
	f2 := httptest.NewServer(f.routes)
	defer f2.Close()
	_, again := doJSON(t, http.MethodGet, f2.URL+"/vocabulary", "")
	if fmt.Sprint(itemIDs(again)) != fmt.Sprint([]int64{f.ids["Capporter"]}) || again["saved"] != 1.0 {
		t.Fatalf("after reload: %v", again)
	}
}

func TestVocabulary_RepeatSavesAreIdempotentAndExamplesAccumulate(t *testing.T) {
	f := newVocabFixture(t)
	f.save(t, f.ids["Capporter"], f.ids["unitA"])
	// VOC-022 / VOC-023 / VOC-081: the same save again (a retry after a timeout) changes nothing.
	for i := 0; i < 3; i++ {
		status, out := f.save(t, f.ids["Capporter"], f.ids["unitA"])
		if status != http.StatusOK || out["changed"] != false || out["saved_now"] != false || out["example_added"] != false {
			t.Fatalf("repeat %d: %d %v", i, status, out)
		}
	}
	if f.count(t, "vocabulary_marks") != 1 || f.count(t, "vocabulary_examples") != 1 {
		t.Fatalf("rows after repeats: marks %d examples %d", f.count(t, "vocabulary_marks"), f.count(t, "vocabulary_examples"))
	}
	// VOC-015 / VOC-055 / VOC-105: a second example from another record joins the same saved Concept.
	status, out := f.save(t, f.ids["Capporter"], f.ids["unitB"])
	if status != http.StatusOK || out["saved_now"] != false || out["example_added"] != true {
		t.Fatalf("second example: %d %v", status, out)
	}
	exs := path(out["item"], "examples").([]any)
	if len(exs) != 2 || path(exs[0], "entry_id") != float64(f.ids["entryA"]) || path(exs[1], "entry_id") != float64(f.ids["entryB"]) {
		t.Fatalf("examples (first kept first): %v", exs)
	}
	// VOC-016: a meaning whose languages were not recorded is explicitly null in both.
	if path(exs[1], "meanings", "en") != nil || path(exs[1], "meanings", "zh") != nil || path(exs[1], "meaning") != "Apporter : faire venir une chose avec soi." {
		t.Fatalf("unrecorded languages: %v", exs[1])
	}
	if len(f.list(t, "")["items"].([]any)) != 1 {
		t.Fatal("one saved term, not two rows")
	}
}

func TestVocabulary_IdentityIsTheConceptNotTheText(t *testing.T) {
	f := newVocabFixture(t)
	// VOC-014 / VOC-101: the same spelling with another meaning is another Concept, another term.
	f.save(t, f.ids["Capporter"], f.ids["unitA"])
	status, out := f.save(t, f.ids["CapporterFig"], f.ids["unitD"])
	if status != http.StatusOK || out["saved_now"] != true {
		t.Fatalf("second meaning: %d %v", status, out)
	}
	got := itemIDs(f.list(t, ""))
	// VOC-034: equal targets order by Concept ID.
	if fmt.Sprint(got) != fmt.Sprint([]int64{f.ids["Capporter"], f.ids["CapporterFig"]}) {
		t.Fatalf("two terms in a stable order: %v", got)
	}
	// VOC-012 / VOC-106: the phrase is shown exactly as written (double space kept in the example's wording).
	f.save(t, f.ids["Cphrase"], f.ids["unitC"])
	for _, it := range f.list(t, "grasse")["items"].([]any) {
		if path(it, "examples").([]any)[0].(map[string]any)["term"] != "faire  la grasse matinée" || path(it, "concept", "target") != "faire la grasse matinée" {
			t.Fatalf("phrase wording: %v", it)
		}
	}
}

func TestVocabulary_SearchFollowsTheLibraryRules(t *testing.T) {
	f := newVocabFixture(t)
	f.save(t, f.ids["Capporter"], f.ids["unitA"])
	f.save(t, f.ids["Cphrase"], f.ids["unitC"])
	cases := map[string][]int64{
		"appor":                   {f.ids["Capporter"]}, // VOC-031: headword prefix
		"APPORTER":                {f.ids["Capporter"]}, // case-insensitive
		"faire la grasse matinée": {f.ids["Cphrase"]},   // VOC-032: full phrase
		"matinee":                 {f.ids["Cphrase"]},   // VOC-040 / VOC-104: accent-insensitive
		"bring":                   {f.ids["Capporter"]}, // VOC-033: translation
		"睡懒觉":                     {f.ids["Cphrase"]},   // Chinese meaning (one token)
		"dessert":                 {f.ids["Capporter"]}, // the example sentence
		"grasse apport":           {},                   // every token must match one item
		"zzz":                     {},                   // VOC-036: zero results, distinct from empty
	}
	for q, want := range cases {
		out := f.list(t, q)
		if fmt.Sprint(itemIDs(out)) != fmt.Sprint(want) || out["saved"] != 2.0 {
			t.Errorf("q=%q: %v (saved %v), want %v", q, itemIDs(out), out["saved"], want)
		}
	}
	if status, _ := doJSON(t, http.MethodGet, f.srv.URL+"/vocabulary?q=x", ""); status != http.StatusBadRequest {
		t.Errorf("a query with no searchable term: %d", status)
	}
}

func TestVocabulary_RefusesWhatIsNotApprovedVocabularyWithoutWriting(t *testing.T) {
	f := newVocabFixture(t)
	cases := []struct {
		name          string
		concept, unit int64
		status        int
		code          string
	}{
		{"a grammar Concept (VOC-011)", f.ids["Cgrammar"], f.ids["unitGrammar"], http.StatusConflict, "not_vocabulary"},
		{"a unit that does not support the Concept (VOC-049)", f.ids["Capporter"], f.ids["unitGrammar"], http.StatusConflict, "unit_not_supporting"},
		{"an unknown Concept", 99999, f.ids["unitA"], http.StatusNotFound, ""},
	}
	for _, c := range cases {
		status, out := f.save(t, c.concept, c.unit)
		if status != c.status || (c.code != "" && out["code"] != c.code) {
			t.Errorf("%s: %d %v", c.name, status, out)
		}
	}
	for _, body := range []string{`{}`, `{"unit_id": 0}`, `{"unit_id": "x"}`, `{"unit_id": 1, "extra": true}`, `not json`} {
		if status, _ := doJSON(t, http.MethodPut, fmt.Sprintf("%s/vocabulary/%d", f.srv.URL, f.ids["Capporter"]), body); status != http.StatusBadRequest {
			t.Errorf("body %s: %d", body, status)
		}
	}
	// VOC-108: nothing was written by any refusal.
	if f.count(t, "vocabulary_marks") != 0 || f.count(t, "vocabulary_examples") != 0 {
		t.Fatal("a refused save left rows")
	}
}

func TestVocabulary_RemoveKeepsHistoryAndIsSafeToRepeat(t *testing.T) {
	f := newVocabFixture(t)
	f.save(t, f.ids["Capporter"], f.ids["unitA"])
	first := path(f.list(t, "")["items"].([]any)[0], "first_saved_at")
	del := func(id int64) (int, map[string]any) {
		return doJSON(t, http.MethodDelete, fmt.Sprintf("%s/vocabulary/%d", f.srv.URL, id), "")
	}
	// VOC-026 / VOC-028: removed, and gone from the list on the next read.
	if status, out := del(f.ids["Capporter"]); status != http.StatusOK || out["changed"] != true || out["saved"] != false {
		t.Fatalf("remove: %d %v", status, out)
	}
	if out := f.list(t, ""); len(out["items"].([]any)) != 0 || out["saved"] != 0.0 {
		t.Fatalf("after removal: %v", out)
	}
	// VOC-028: a fresh handler over the same database (a reload) agrees.
	reload := httptest.NewServer(f.routes)
	_, again := doJSON(t, http.MethodGet, reload.URL+"/vocabulary", "")
	reload.Close()
	if again["saved"] != 0.0 || len(again["items"].([]any)) != 0 {
		t.Fatalf("after removal and a reload: %v", again)
	}
	// VOC-029: removing again is safe; a Concept never saved is 404.
	if status, out := del(f.ids["Capporter"]); status != http.StatusOK || out["changed"] != false {
		t.Fatalf("second removal: %d %v", status, out)
	}
	if status, _ := del(f.ids["Cgrammar"]); status != http.StatusNotFound {
		t.Fatalf("never saved: %d", status)
	}
	// VOC-027: the example, the Concept and its units are intact; saving again restores it with its example.
	if f.count(t, "vocabulary_examples") != 1 {
		t.Fatal("removal deleted an example")
	}
	if status, _ := doJSON(t, http.MethodGet, fmt.Sprintf("%s/knowledge-library/concepts/%d", f.srv.URL, f.ids["Capporter"]), ""); status != http.StatusOK {
		t.Fatalf("the Concept after removal: %d", status)
	}
	// VOC-136: a removed term's example link still resolves (the source read), consistently.
	if status, _ := doJSON(t, http.MethodGet, fmt.Sprintf("%s/knowledge-library/units/%d/source", f.srv.URL, f.ids["unitA"]), ""); status != http.StatusOK {
		t.Fatalf("a removed term's example source: %d", status)
	}
	_, out := f.save(t, f.ids["Capporter"], f.ids["unitA"])
	if out["saved_now"] != true || out["example_added"] != false || path(out["item"], "first_saved_at") != first || len(path(out["item"], "examples").([]any)) != 1 {
		t.Fatalf("saved again: %v", out)
	}
	if _, err := f.db.Exec("DELETE FROM vocabulary_marks"); err == nil || !strings.Contains(err.Error(), "append-only") {
		t.Fatalf("marks must be append-only: %v", err)
	}
}

func TestVocabulary_AnExampleWhoseExtractionIsSupersededStaysAsItWas(t *testing.T) {
	f := newVocabFixture(t)
	f.save(t, f.ids["Capporter"], f.ids["unitA"])
	// VOC-058 / VOC-117: a new extraction of the record supersedes the saved example's.
	f.extract(f.ids["entryA"])
	items := f.list(t, "")["items"].([]any)
	if len(items) != 1 {
		t.Fatalf("the saved term stays listed: %v", items)
	}
	ex := path(items[0], "examples").([]any)[0]
	// VOC-056: shown as the revision it was saved from, labelled, never replaced by the newer one.
	if path(ex, "status") != "not_current" || path(ex, "newer_extraction") != true || path(ex, "extraction_version") != 1.0 || path(ex, "meaning") != "to bring (a thing)" {
		t.Fatalf("superseded example: %v", ex)
	}
	// One example (entry B) still supports the Concept: review stays possible.
	if path(items[0], "review_units") != 1.0 {
		t.Fatalf("review units after supersession: %v", path(items[0], "review_units"))
	}
}

func TestVocabulary_NeverInThePublicDemo(t *testing.T) {
	f := newVocabFixture(t)
	f.save(t, f.ids["Capporter"], f.ids["unitA"])
	demo := httptest.NewServer(transporthttp.NewPublicDemoBoundary(f.routes, false))
	defer demo.Close()
	for _, prefix := range []string{"", "/api"} {
		if status, _ := doJSON(t, http.MethodGet, demo.URL+prefix+"/vocabulary", ""); status != http.StatusNotFound {
			t.Errorf("GET %s/vocabulary in the demo: %d", prefix, status)
		}
		for _, m := range []string{http.MethodPut, http.MethodDelete} {
			req, _ := http.NewRequest(m, fmt.Sprintf("%s%s/vocabulary/%d", demo.URL, prefix, f.ids["Capporter"]), strings.NewReader(`{"unit_id": 1}`))
			res, err := http.DefaultClient.Do(req)
			if err != nil {
				t.Fatal(err)
			}
			res.Body.Close()
			if res.StatusCode != http.StatusMethodNotAllowed && res.StatusCode != http.StatusNotFound {
				t.Errorf("%s %s/vocabulary in the demo: %d", m, prefix, res.StatusCode)
			}
		}
	}
	if f.count(t, "vocabulary_marks") != 1 {
		t.Fatal("the demo boundary changed saved vocabulary")
	}
}

// VOC-018 / VOC-057 / VOC-059: the lifecycle of what a saved term rests on.
// The term never disappears because its source changed; each state is shown.
func TestVocabulary_LifecycleStatesAreShownNotHidden(t *testing.T) {
	f := newVocabFixture(t)
	f.save(t, f.ids["Capporter"], f.ids["unitA"])
	f.save(t, f.ids["Capporter"], f.ids["unitB"])
	// An admission override suppresses unit B: that example no longer supports the term.
	if status, out := doJSON(t, http.MethodPost, fmt.Sprintf("%s/knowledge-units/%d/admission-overrides", f.srv.URL, f.ids["unitB"]),
		`{"decision": "suppressed", "reason": "mastered", "note": "synthetic"}`); status != http.StatusCreated && status != http.StatusOK {
		t.Fatalf("override: %d %v", status, out)
	}
	it := f.list(t, "")["items"].([]any)[0]
	exs := path(it, "examples").([]any)
	if path(exs[0], "status") != "current" || path(exs[1], "status") != "not_current" || path(it, "review_units") != 1.0 {
		t.Fatalf("after suppression: %v", it)
	}
	// VOC-049: a suppressed unit can never be (re)saved as an example or offered for review.
	if status, out := f.save(t, f.ids["Capporter"], f.ids["unitB"]); status != http.StatusConflict || out["code"] != "unit_not_supporting" {
		t.Fatalf("saving a suppressed unit: %d %v", status, out)
	}
	// VOC-047: every example superseded → the Concept is orphaned, no review offered, the term stays.
	f.extract(f.ids["entryA"])
	it = f.list(t, "")["items"].([]any)[0]
	if path(it, "concept", "state") != "orphaned" || path(it, "review_units") != 0.0 || len(path(it, "examples").([]any)) != 2 {
		t.Fatalf("orphaned: %v", it)
	}
	// Retired by a human: listed with its state, and no new example can be saved.
	if _, err := f.db.Exec("UPDATE knowledge_concepts SET lifecycle_state = 'retired' WHERE id = ?", f.ids["Capporter"]); err != nil {
		t.Fatal(err)
	}
	it = f.list(t, "")["items"].([]any)[0]
	if path(it, "concept", "state") != "retired" || path(it, "saved") != true {
		t.Fatalf("retired: %v", it)
	}
	if status, out := f.save(t, f.ids["Capporter"], f.ids["unitB"]); status != http.StatusConflict || out["code"] != "concept_retired" {
		t.Fatalf("save on a retired Concept: %d %v", status, out)
	}
}

// VOC-039 / VOC-101 to VOC-104 / VOC-106 / VOC-109: identity is the Concept's (no Unicode or
// apostrophe normalization), search is accent-, case- and punctuation-blind, and every text
// round-trips exactly.
func TestVocabulary_IdentityEdgesAndSearchNormalization(t *testing.T) {
	f := newVocabFixture(t)
	for _, k := range []string{"ChatFr", "ChatEn", "AujTypo", "AujStraight", "CafeNFC", "CafeNFD", "Long"} {
		if status, out := f.save(t, f.ids["C"+k], f.ids["unit"+k]); status != http.StatusOK || out["saved_now"] != true {
			t.Fatalf("save %s: %d %v", k, status, out)
		}
	}
	all := f.list(t, "")
	if all["saved"] != 7.0 {
		t.Fatalf("seven separate terms: %v", all["saved"])
	}
	byID := map[int64]any{}
	for _, it := range all["items"].([]any) {
		byID[int64(path(it, "concept_id").(float64))] = it
	}
	// Exact round trips: NFD stays NFD, each apostrophe stays itself, the long phrase and its
	// long source context are unchanged.
	exact := map[string]string{"CafeNFD": "cafe\u0301", "CafeNFC": "café", "AujTypo": "aujourd’hui", "AujStraight": "aujourd'hui",
		"Long": "il pleut des cordes, n'est-ce pas ? — « oui » (vraiment) !"}
	for k, want := range exact {
		it := byID[f.ids["C"+k]]
		if term := path(it, "examples").([]any)[0].(map[string]any)["term"]; term != want {
			t.Errorf("%s wording %q, want %q", k, term, want)
		}
	}
	longIt := byID[f.ids["CLong"]]
	if ctx := path(path(longIt, "examples").([]any)[0], "source", "original_context").(string); len([]rune(ctx)) < 1500 || !strings.HasPrefix(ctx, "Il pleuvait depuis le matin") {
		t.Errorf("long context round trip: %d runes", len([]rune(ctx)))
	}
	ids := func(q string) []int64 {
		got := itemIDs(f.list(t, q))
		return got
	}
	same := func(name string, got []int64, want ...int64) {
		t.Helper()
		if fmt.Sprint(got) != fmt.Sprint(want) {
			t.Errorf("%s: %v, want %v", name, got, want)
		}
	}
	// VOC-101: one spelling, two languages, two terms; a meaning word tells them apart.
	// equal targets: exact text, then Concept ID (VOC-034)
	same("chat", ids("chat"), f.ids["CChatFr"], f.ids["CChatEn"])
	same("loanword", ids("loanword"), f.ids["CChatEn"])
	// VOC-102: two apostrophes, two Concepts; search treats an apostrophe as a separator, so either finds both.
	same("aujourd'hui", ids("aujourd'hui"), f.ids["CAujStraight"], f.ids["CAujTypo"])
	same("aujourd’hui", ids("aujourd’hui"), f.ids["CAujStraight"], f.ids["CAujTypo"])
	// VOC-103 / VOC-104: NFC and NFD, accented or not, any case: one search finds both
	// (in order of exact text: "cafe" + U+0301 sorts before "café" with U+00E9).
	for _, q := range []string{"café", "cafe\u0301", "cafe", "CAFÉ"} {
		same("q="+q, ids(q), f.ids["CCafeNFD"], f.ids["CCafeNFC"])
	}
	// VOC-039 / VOC-106: a long multiword phrase with punctuation is found by any of its words.
	same("cordes", ids("cordes vraiment"), f.ids["CLong"])
}

// VOC-128: saves either side of midnight with a fixed clock. Times are stored exactly (UTC); the
// first save is kept across a removal; the page shows each in the learner's own zone, where the
// same two instants can be one day (Paris) or two (UTC).
func TestVocabulary_FixedClockAroundMidnight(t *testing.T) {
	f := newVocabFixture(t)
	clock := time.Date(2026, 11, 21, 23, 59, 59, 0, time.UTC)
	f.vocab.WithClock(func() time.Time { return clock })
	f.save(t, f.ids["Capporter"], f.ids["unitA"])
	clock = time.Date(2026, 11, 22, 0, 0, 1, 0, time.UTC)
	doJSON(t, http.MethodDelete, fmt.Sprintf("%s/vocabulary/%d", f.srv.URL, f.ids["Capporter"]), "")
	clock = clock.Add(time.Second)
	_, out := f.save(t, f.ids["Capporter"], f.ids["unitA"])
	first, saved := path(out["item"], "first_saved_at").(string), path(out["item"], "saved_at").(string)
	if first != "2026-11-21T23:59:59Z" || saved != "2026-11-22T00:00:02Z" {
		t.Fatalf("instants: first %s saved %s", first, saved)
	}
	paris, _ := time.LoadLocation("Europe/Paris")
	a, _ := time.Parse(time.RFC3339, first)
	b, _ := time.Parse(time.RFC3339, saved)
	if a.UTC().Day() == b.UTC().Day() || a.In(paris).Format("2006-01-02") != b.In(paris).Format("2006-01-02") {
		t.Fatalf("local days: UTC %d/%d, Paris %s/%s", a.Day(), b.Day(), a.In(paris).Format("01-02"), b.In(paris).Format("01-02"))
	}
}

// VOC-116: a transient storage error (another connection holds the write lock past the busy
// timeout) fails the save with a clear 500 and writes nothing; the retry then saves once.
func TestVocabulary_TransientStorageErrorThenRetryKeepsData(t *testing.T) {
	if testing.Short() {
		t.Skip("waits for the 5 s busy timeout")
	}
	f := newVocabFixture(t)
	f.save(t, f.ids["Cphrase"], f.ids["unitC"])
	other, err := sql.Open("sqlite", f.path)
	if err != nil {
		t.Fatal(err)
	}
	defer other.Close()
	conn, err := other.Conn(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := conn.ExecContext(context.Background(), "BEGIN IMMEDIATE"); err != nil {
		t.Fatal(err)
	}
	status, out := f.save(t, f.ids["Capporter"], f.ids["unitA"])
	if _, err := conn.ExecContext(context.Background(), "ROLLBACK"); err != nil {
		t.Fatal(err)
	}
	conn.Close()
	if status != http.StatusInternalServerError || out["error"] != "could not save the term" {
		t.Fatalf("under a held lock: %d %v", status, out)
	}
	if f.count(t, "vocabulary_marks") != 1 || f.count(t, "vocabulary_examples") != 1 {
		t.Fatal("a failed save left rows, or the earlier save was lost")
	}
	if status, out := f.save(t, f.ids["Capporter"], f.ids["unitA"]); status != http.StatusOK || out["saved_now"] != true {
		t.Fatalf("retry: %d %v", status, out)
	}
	if got := f.list(t, "")["saved"]; got != 2.0 {
		t.Fatalf("after the retry: %v", got)
	}
}

// VOC-119: concurrent saves (repeats included), removals and reads keep the counts consistent:
// every read's saved count equals its rows, and the end state has one mark per change of state.
func TestVocabulary_ConcurrentReadsAndWritesStayConsistent(t *testing.T) {
	f := newVocabFixture(t)
	pairs := [][2]int64{{f.ids["Capporter"], f.ids["unitA"]}, {f.ids["Cphrase"], f.ids["unitC"]}, {f.ids["CapporterFig"], f.ids["unitD"]}, {f.ids["CChatFr"], f.ids["unitChatFr"]}}
	var wg sync.WaitGroup
	errs := make(chan string, 200)
	for i := 0; i < 8; i++ {
		wg.Add(2)
		go func(i int) {
			defer wg.Done()
			for j := 0; j < 5; j++ {
				p := pairs[(i+j)%len(pairs)]
				if status, out := f.save(t, p[0], p[1]); status != http.StatusOK {
					errs <- fmt.Sprintf("save %d: %v", status, out)
				}
			}
		}(i)
		go func() {
			defer wg.Done()
			for j := 0; j < 5; j++ {
				out := f.list(t, "")
				if int(out["saved"].(float64)) != len(out["items"].([]any)) {
					errs <- fmt.Sprintf("read saved %v items %d", out["saved"], len(out["items"].([]any)))
				}
			}
		}()
	}
	wg.Wait()
	close(errs)
	for e := range errs {
		t.Error(e)
	}
	if out := f.list(t, ""); out["saved"] != 4.0 || len(out["items"].([]any)) != 4 {
		t.Fatalf("end state: %v", out["saved"])
	}
	if f.count(t, "vocabulary_marks") != 4 || f.count(t, "vocabulary_examples") != 4 {
		t.Fatalf("rows: marks %d examples %d", f.count(t, "vocabulary_marks"), f.count(t, "vocabulary_examples"))
	}
}
