package sqlite

import (
	"strings"
	"testing"

	"french-learning-app/internal/domain"
)

// FLH-090: the learning-record text filter is a bounded literal substring test
// over learner-authored input and context only.

func textQuery(text string, limit int) domain.LearningRecordQuery {
	q := domain.LearningRecordQuery{Text: &text}
	if err := q.Normalize(20, 200); err != nil {
		panic(err)
	}
	q.Limit = limit
	return q
}

func entryIDs(recs []*domain.LearningRecord) []int64 {
	out := make([]int64, 0, len(recs))
	for _, r := range recs {
		out = append(out, r.EntryID)
	}
	return out
}

func equalIDs(a, b []int64) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func TestInventoryText_LiteralWildcardsAndUnicodeCase(t *testing.T) {
	r := newTestInventoryRepos(t)
	pct := r.newEntry(t, "Il a réussi à 100% !", "")
	plain := r.newEntry(t, "Il a réussi à 1000 !", "")
	under := r.newEntry(t, "le mot_clé", "")
	under2 := r.newEntry(t, "le motXclé", "")
	slash := r.newEntry(t, `chemin C:\cours`, "")
	upper := r.newEntry(t, "ÉTAT et Être", "")
	ctx := r.newEntry(t, "question", "Contexte : Subjonctif après « bien que »")
	decomposed := r.newEntry(t, "e\u0301te\u0301", "") // "été" with combining accents

	cases := []struct {
		q    string
		want []int64
	}{
		{"100%", []int64{pct.ID}},                   // % is literal, not "anything"
		{"%", []int64{pct.ID}},                      // matches only text that contains %
		{"mot_clé", []int64{under.ID}},              // _ is literal, not "any one character"
		{"_", []int64{under.ID}},                    //
		{`C:\cours`, []int64{slash.ID}},             // backslash is literal
		{"état", []int64{upper.ID}},                 // Unicode case-insensitive (É vs é)
		{"ÊTRE", []int64{upper.ID}},                 //
		{"subjonctif", []int64{ctx.ID}},             // original context is searched
		{"« bien que »", []int64{ctx.ID}},           // punctuation and spaces are literal
		{"etat", nil},                               // no accent folding
		{"été", nil},                                // no Unicode normalization (composed vs decomposed)
		{"e\u0301te\u0301", []int64{decomposed.ID}}, // the same code points match
		{"réussi à 1", []int64{plain.ID, pct.ID}},   // descending entry order
	}
	for _, c := range cases {
		recs, err := r.inventory.ListLearningRecords(context2(), textQuery(c.q, 50))
		if err != nil {
			t.Fatalf("%q: %v", c.q, err)
		}
		if got := entryIDs(recs); !equalIDs(got, c.want) {
			t.Errorf("q=%q: got %v, want %v", c.q, got, c.want)
		}
	}
	_ = under2 // negative control: "_" and "mot_clé" must not match "motXclé"
}

func TestInventoryText_NeverMatchesInterpretations(t *testing.T) {
	r := newTestInventoryRepos(t)
	e := r.newEntry(t, "Pourquoi « il faut que » ?", "")
	a := r.newAnalysis(t, e.ID, "grammar", "Explanation mentioning SUBJONCTIF only here.", "rule-based:v2:fr_l2_taxonomy_v1")
	expl := "Corrected explanation: zanzibar"
	r.newFeedback(t, a.ID, domain.NewFeedbackInput{Status: domain.FeedbackCorrected, CorrectedExplanation: &expl})
	for _, q := range []string{"subjonctif", "zanzibar", "grammar", "rule-based"} {
		recs, err := r.inventory.ListLearningRecords(context2(), textQuery(q, 50))
		if err != nil {
			t.Fatal(err)
		}
		if len(recs) != 0 {
			t.Errorf("q=%q matched generated or provenance text: %v", q, entryIDs(recs))
		}
	}
}

func TestInventoryText_PaginatesBeyondFirstPageAndComposesWithFilters(t *testing.T) {
	r := newTestInventoryRepos(t)
	var matching []int64
	for i := 0; i < 25; i++ {
		input := "sans rapport"
		if i%2 == 0 {
			input = "Subjonctif numéro " + strings.Repeat("x", i)
		}
		e := r.newEntry(t, input, "")
		if i%2 == 0 {
			matching = append([]int64{e.ID}, matching...) // descending
			if i%4 == 0 {
				r.newAnalysis(t, e.ID, "grammar", "g", "rule-based:v2:fr_l2_taxonomy_v1")
			}
		}
	}
	// Walk the matches in pages of 5 with the descending cursor.
	var walked []int64
	var cursor *int64
	for pages := 0; ; pages++ {
		q := textQuery("subjonctif", 5)
		q.BeforeEntryID = cursor
		recs, err := r.inventory.ListLearningRecords(context2(), q)
		if err != nil {
			t.Fatal(err)
		}
		walked = append(walked, entryIDs(recs)...)
		if len(recs) < 5 {
			break
		}
		last := recs[len(recs)-1].EntryID
		cursor = &last
		if pages > 10 {
			t.Fatal("pagination did not terminate")
		}
	}
	if !equalIDs(walked, matching) {
		t.Fatalf("walked %v, want %v", walked, matching)
	}

	// Combined with the state filter and a jump position.
	state := domain.LearningRecordState("unreviewed")
	q := textQuery("subjonctif", 50)
	q.State = &state
	jump := matching[2] + 1
	q.BeforeEntryID = &jump
	recs, err := r.inventory.ListLearningRecords(context2(), q)
	if err != nil {
		t.Fatal(err)
	}
	for _, rec := range recs {
		if rec.State != state || rec.EntryID >= jump || !strings.Contains(rec.OriginalInput, "Subjonctif") {
			t.Fatalf("combined filter returned %+v", rec)
		}
	}
	if len(recs) == 0 {
		t.Fatal("combined filter returned nothing")
	}
}

func TestLearningRecordQuery_TextBounds(t *testing.T) {
	for _, blank := range []string{"", "   ", "\t\n"} {
		q := domain.LearningRecordQuery{Text: &blank}
		if err := q.Normalize(20, 200); err != nil || q.Text != nil {
			t.Fatalf("blank %q: err=%v text=%v, want no filter", blank, err, q.Text)
		}
	}
	padded := "  subjonctif  "
	q := domain.LearningRecordQuery{Text: &padded}
	if err := q.Normalize(20, 200); err != nil || *q.Text != "subjonctif" {
		t.Fatalf("trim: err=%v text=%v", err, q.Text)
	}
	max := strings.Repeat("é", domain.MaxLearningRecordTextQuery) // 200 characters, 400 bytes
	q = domain.LearningRecordQuery{Text: &max}
	if err := q.Normalize(20, 200); err != nil {
		t.Fatalf("200 characters must be accepted: %v", err)
	}
	long := max + "x"
	q = domain.LearningRecordQuery{Text: &long}
	if err := q.Normalize(20, 200); err == nil {
		t.Fatal("201 characters must be rejected")
	}
	bad := "a\xffb"
	q = domain.LearningRecordQuery{Text: &bad}
	if err := q.Normalize(20, 200); err == nil {
		t.Fatal("invalid UTF-8 must be rejected")
	}
}
