package domain_test

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"french-learning-app/internal/domain"
	"french-learning-app/internal/reading"
)

func TestParseReadingText_StableParagraphIDsAndExactWording(t *testing.T) {
	segs, err := domain.ParseReadingText("  Premier paragraphe,\nsur deux lignes.  \n\n\n  Deuxième.\r\n \r\nTroisième ; « citation ».\n")
	if err != nil {
		t.Fatal(err)
	}
	if len(segs) != 3 || segs[0].ID != "p1" || segs[2].ID != "p3" || segs[0].Text != "Premier paragraphe,\nsur deux lignes." || segs[2].Text != "Troisième ; « citation »." {
		t.Fatalf("segments = %#v", segs)
	}
	for name, text := range map[string]string{
		"empty":          " \n\n ",
		"control":        "Bonjour\u0007",
		"long paragraph": strings.Repeat("é", domain.MaxReadingParagraphRunes+1),
		"long text":      strings.Repeat("Un mot.\n\n", 700),
	} {
		if _, err := domain.ParseReadingText(text); !errors.Is(err, domain.ErrValidation) {
			t.Errorf("%s: err = %v", name, err)
		}
	}
}

func TestNormalizeReadingSourceURL(t *testing.T) {
	if got, err := domain.NormalizeReadingSourceURL(""); err != nil || got != "" {
		t.Fatalf("empty: %q %v", got, err)
	}
	if got, err := domain.NormalizeReadingSourceURL(" https://example.org/article?id=1 "); err != nil || got != "https://example.org/article?id=1" {
		t.Fatalf("https: %q %v", got, err)
	}
	for _, bad := range []string{"http://example.org/a", "ftp://example.org", "https://user:pw@example.org/", "example.org/a"} {
		if _, err := domain.NormalizeReadingSourceURL(bad); !errors.Is(err, domain.ErrValidation) || strings.Contains(err.Error(), "pw") {
			t.Errorf("%s: %v", bad, err)
		}
	}
}

var passage = []domain.ReadingSegment{
	{ID: "p1", Text: "La médiathèque ouvrira aussi le dimanche, de 14 h à 18 h."},
	{ID: "p2", Text: "Vous avez dix jours pour venir le chercher. Dix jours, pas plus."},
}

func validContent() domain.ReadingExerciseContent {
	return domain.ReadingExerciseContent{Items: []domain.ReadingItem{
		{Kind: "main_idea", Question: "De quoi parle le texte ?", ReferenceAnswer: "Des nouveaux horaires.", Evidence: []domain.ReadingEvidence{{Segment: "p1", Excerpt: "ouvrira aussi le dimanche"}},
			ExplanationEN: "p1 says so.", ExplanationZH: "p1 说明了。"},
		{Kind: "detail", Question: "Combien de jours ?", ReferenceAnswer: "Dix jours.", AcceptedAlternatives: []string{"10 jours"},
			Evidence: []domain.ReadingEvidence{{Segment: "p2", Excerpt: "pour venir le chercher"}}, ExplanationEN: "p2.", ExplanationZH: "p2。"},
	}}
}

func TestValidateReadingExercise(t *testing.T) {
	c := validContent()
	if err := domain.ValidateReadingExercise(passage, &c, false); err != nil {
		t.Fatalf("valid generated content refused: %v", err)
	}
	cases := map[string]func(*domain.ReadingExerciseContent){
		"unknown paragraph": func(c *domain.ReadingExerciseContent) { c.Items[0].Evidence[0].Segment = "p7" },
		"invented excerpt":  func(c *domain.ReadingExerciseContent) { c.Items[0].Evidence[0].Excerpt = "ouvrira le samedi" },
		"ambiguous excerpt": func(c *domain.ReadingExerciseContent) { c.Items[1].Evidence[0].Excerpt = "jours" },
		"no evidence":       func(c *domain.ReadingExerciseContent) { c.Items[1].Evidence = nil },
		"two main ideas":    func(c *domain.ReadingExerciseContent) { c.Items[1].Kind = "main_idea" },
		"two inferences": func(c *domain.ReadingExerciseContent) {
			inf := c.Items[1]
			inf.Kind = "inference"
			c.Items = append(c.Items, inf, inf)
		},
		"blank explanation": func(c *domain.ReadingExerciseContent) { c.Items[0].ExplanationZH = " " },
		"accepted and wrong": func(c *domain.ReadingExerciseContent) {
			c.Items[1].WrongAnswers = []domain.ReadingWrongAnswer{{Answer: "10 jours.", WhyWrongEN: "x", WhyWrongZH: "x"}}
		},
	}
	for name, mutate := range cases {
		c := validContent()
		mutate(&c)
		if err := domain.ValidateReadingExercise(passage, &c, false); !errors.Is(err, domain.ErrValidation) {
			t.Errorf("%s: err = %v", name, err)
		}
	}
	c = validContent()
	if err := domain.ValidateReadingExercise(passage, &c, true); !errors.Is(err, domain.ErrValidation) {
		t.Fatal("authored content needs wrong answers and a no-inference reason")
	}
}

func TestParseReadingPack_EmbeddedPackIsValidAndDefectsAreRefused(t *testing.T) {
	pack, err := domain.ParseReadingPack(reading.ExamplePack())
	if err != nil {
		t.Fatal(err)
	}
	inference := 0
	for _, p := range pack.Passages {
		for _, q := range p.Questions {
			if q.Kind == "inference" {
				inference++
			}
		}
	}
	if len(pack.Passages) != 6 || inference != 3 {
		t.Fatalf("pack: %d passages, %d inference items", len(pack.Passages), inference)
	}
	mutate := func(f func(m map[string]any)) []byte {
		var m map[string]any
		_ = json.Unmarshal(reading.ExamplePack(), &m)
		f(m)
		raw, _ := json.Marshal(m)
		return raw
	}
	first := func(m map[string]any) map[string]any { return m["passages"].([]any)[0].(map[string]any) }
	for name, raw := range map[string][]byte{
		"invented citation": mutate(func(m map[string]any) {
			first(m)["questions"].([]any)[1].(map[string]any)["evidence"].([]any)[0].(map[string]any)["excerpt"] = "les cours sont déplacés"
		}),
		"missing source": mutate(func(m map[string]any) { delete(first(m), "source") }),
		"ambiguous key": mutate(func(m map[string]any) {
			q := first(m)["questions"].([]any)[1].(map[string]any)
			q["wrong_answers"].([]any)[0].(map[string]any)["answer"] = q["reference_answer"]
		}),
		"wrong schema": mutate(func(m map[string]any) { m["schema_version"] = "other" }),
	} {
		if _, err := domain.ParseReadingPack(raw); !errors.Is(err, domain.ErrValidation) {
			t.Errorf("%s: err = %v", name, err)
		}
	}
}
