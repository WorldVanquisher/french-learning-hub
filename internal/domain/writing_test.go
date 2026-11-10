package domain_test

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"french-learning-app/internal/domain"
	"french-learning-app/internal/writing"
)

func TestCountWritingWords_FollowsTheDisplayedConvention(t *testing.T) {
	for text, want := range map[string]int{
		"Bonjour Sophie,":                          2,
		"Merci pour l'invitation !":                3,
		"Je viendrai peut-être vers 20 heures.":    6,
		"« Oui » — c'est d'accord ; à samedi… 18h": 6,
		"   ": 0,
	} {
		if got := domain.CountWritingWords(text); got != want {
			t.Errorf("%q: %d words, want %d", text, got, want)
		}
	}
}

func invitation(t *testing.T) (draft string, fb domain.WritingFeedbackContent) {
	t.Helper()
	set, err := domain.ParseWritingPrompts(writing.ExamplePrompts())
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range set.Prompts {
		if p.ID == "wr-invitation-anniversaire" {
			draft = p.ExampleDraft
		}
	}
	raw, err := os.ReadFile(filepath.Join("..", "writing", "testdata", "invitation_feedback.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(raw, &fb); err != nil {
		t.Fatal(err)
	}
	return draft, fb
}

func TestValidateWritingFeedback_GroundsQuotesAgainstTheExactDraft(t *testing.T) {
	draft, fb := invitation(t)
	if err := domain.ValidateWritingFeedback(draft, &fb); err != nil {
		t.Fatal(err)
	}
	want := []string{domain.WritingLocated, domain.WritingLocated, domain.WritingAmbiguous, domain.WritingNotFound}
	for i, c := range fb.Corrections {
		if c.Grounding != want[i] {
			t.Fatalf("correction %d (%q) is %s, want %s", i+1, c.Quote, c.Grounding, want[i])
		}
	}
	first := fb.Corrections[0]
	runes := []rune(draft)
	if first.Start == nil || string(runes[*first.Start:*first.Start+len([]rune(first.Quote))]) != first.Quote {
		t.Fatalf("located start %v does not point at the quote", first.Start)
	}
	if fb.Corrections[2].Start != nil || fb.Corrections[3].Start != nil {
		t.Fatal("an ambiguous or missing quote must not get a location")
	}
	// The same feedback against a revised draft locates nothing it no longer contains.
	revised := "Bonjour Sophie,\n\nJ'arriverai vers 20 heures. Je ne suis pas sûr de l'adresse."
	_, again := invitation(t)
	if err := domain.ValidateWritingFeedback(revised, &again); err != nil {
		t.Fatal(err)
	}
	if again.Corrections[0].Grounding != domain.WritingNotFound || again.Corrections[1].Grounding != domain.WritingNotFound {
		t.Fatalf("v1 quotes must not be located in v2: %+v", again.Corrections[:2])
	}
}

func TestValidateWritingFeedback_RefusesUnusableOutput(t *testing.T) {
	cases := map[string]func(*domain.WritingFeedbackContent){
		"score-like rating":  func(c *domain.WritingFeedbackContent) { c.TaskFulfilment.Rating = "B1" },
		"blank chinese":      func(c *domain.WritingFeedbackContent) { c.Clarity.CommentZH = " " },
		"unknown category":   func(c *domain.WritingFeedbackContent) { c.Corrections[0].Category = "style" },
		"empty quote":        func(c *domain.WritingFeedbackContent) { c.Corrections[0].Quote = " " },
		"suggestion = quote": func(c *domain.WritingFeedbackContent) { c.Corrections[0].Suggestion = c.Corrections[0].Quote },
		"too many corrections": func(c *domain.WritingFeedbackContent) {
			c.Corrections = append(c.Corrections, append(c.Corrections, c.Corrections...)...)
		},
	}
	for name, mutate := range cases {
		draft, fb := invitation(t)
		mutate(&fb)
		if err := domain.ValidateWritingFeedback(draft, &fb); !errors.Is(err, domain.ErrValidation) {
			t.Errorf("%s: err = %v", name, err)
		}
	}
}

func TestParseWritingPrompts_EmbeddedSetIsValid(t *testing.T) {
	set, err := domain.ParseWritingPrompts(writing.ExamplePrompts())
	if err != nil {
		t.Fatal(err)
	}
	if len(set.Prompts) != 3 {
		t.Fatalf("prompts = %d", len(set.Prompts))
	}
	for _, p := range set.Prompts {
		if n := domain.CountWritingWords(p.ExampleDraft); n < p.WordMin-10 || n > p.WordMax+10 {
			t.Errorf("%s: example draft has %d words for %d–%d", p.ID, n, p.WordMin, p.WordMax)
		}
	}
	if _, err := domain.ParseWritingPrompts([]byte(`{"schema_version":"flh_writing_prompts_v1","prompts":[{"id":"bad id"}]}`)); !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("malformed prompt accepted: %v", err)
	}
	if _, err := domain.NormalizeWritingTask(domain.WritingTask{Title: "t", Prompt: "p", WordMin: 50, WordMax: 20}); !errors.Is(err, domain.ErrValidation) {
		t.Fatal("an inverted word range must be refused")
	}
}
