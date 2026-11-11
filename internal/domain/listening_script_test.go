package domain

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"
)

func scriptFixture() ListeningScript {
	return ListeningScript{
		ID: "ls-test-u01", Title: "À l'accueil", Genre: "dialogue", StyleLevel: "A2",
		Source: &ListeningScriptSource{Kind: "authored", Pack: "test_pack", Notice: "Synthetic, unreviewed."},
		Lines: []ListeningScriptLine{
			{ID: "s1", Speaker: "Agent", Text: "Bonjour, vous avez rendez-vous à quelle heure ?"},
			{ID: "s2", Speaker: "Mei", Text: "À onze heures et demie, avec le docteur Roche."},
			{ID: "s3", Speaker: "Agent", Text: "Très bien, la salle d'attente est au premier étage."},
		},
		Questions: []ListeningItem{
			{ID: "u01-l01", Kind: ListeningMainIdea, Question: "Où est Mei ?", ExpectedAnswer: "Dans un cabinet médical.",
				RationaleEN: "She has an appointment with a doctor.", RationaleZH: "她和医生有预约。", Segments: []int{2},
				Choices:      []string{"Dans un cabinet médical.", "À la gare."},
				WrongAnswers: []ListeningWrongAnswer{{Answer: "À la gare.", WhyWrongEN: "She sees a doctor (s2).", WhyWrongZH: "她看医生（s2）。"}},
				Evidence:     []ListeningEvidence{{Segment: 2, Excerpt: "avec le docteur Roche"}}},
			{ID: "u01-l02", Kind: ListeningDetail, Question: "À quelle heure ?", ExpectedAnswer: "onze heures et demie",
				AcceptedAlternatives: []string{"11 h 30"}, RationaleEN: "At 11:30.", RationaleZH: "十一点半。", Segments: []int{2},
				Evidence: []ListeningEvidence{{Segment: 2, Excerpt: "À onze heures et demie"}}},
			{ID: "u01-l03", Kind: ListeningInference, Question: "Mei connaît-elle le cabinet ?", ExpectedAnswer: "Non.",
				RationaleEN: "She is told where the waiting room is.", RationaleZH: "有人告诉她候诊室在哪。", Segments: []int{3},
				Evidence: []ListeningEvidence{{Segment: 3, Excerpt: "la salle d'attente est au premier étage"}}},
			{ID: "u01-l04", Kind: ListeningInference, Question: "Est-elle en avance ?", ExpectedAnswer: "On ne sait pas.",
				RationaleEN: "No arrival time is given.", RationaleZH: "没有说到达时间。", Segments: []int{1},
				Evidence: []ListeningEvidence{{Segment: 1, Excerpt: "vous avez rendez-vous"}}},
		},
	}
}

func TestValidateListeningScript_AcceptsAWellFormedScript(t *testing.T) {
	s := scriptFixture()
	if err := ValidateListeningScript(&s); err != nil {
		t.Fatalf("valid script refused: %v", err)
	}
	segs := s.Segments()
	if len(segs) != 3 || segs[1].Index != 2 || segs[1].Speaker != "Mei" || segs[1].StartSeconds != nil {
		t.Fatalf("segments = %+v", segs)
	}
	if s.PackScriptID() != "flh_listening_script_pack_v1/ls-test-u01" {
		t.Fatalf("pack script id = %q", s.PackScriptID())
	}
}

func TestValidateListeningScript_RefusesBrokenAuthoredItems(t *testing.T) {
	cases := map[string]func(*ListeningScript){
		"expected answer not among the choices": func(s *ListeningScript) { s.Questions[0].ExpectedAnswer = "Chez elle." },
		"a choice without a reason":             func(s *ListeningScript) { s.Questions[0].Choices = append(s.Questions[0].Choices, "Au marché.") },
		"a reason for an answer that is not a choice": func(s *ListeningScript) {
			s.Questions[0].WrongAnswers = append(s.Questions[0].WrongAnswers, ListeningWrongAnswer{Answer: "Au cinéma.", WhyWrongEN: "x", WhyWrongZH: "x"})
		},
		"repeated choice":                      func(s *ListeningScript) { s.Questions[0].Choices[1] = "dans un cabinet médical" },
		"evidence absent from its segment":     func(s *ListeningScript) { s.Questions[1].Evidence[0].Excerpt = "midi" },
		"evidence in a segment the item skips": func(s *ListeningScript) { s.Questions[1].Evidence[0].Segment = 1 },
		"no evidence":                          func(s *ListeningScript) { s.Questions[2].Evidence = nil },
		"repeated item id":                     func(s *ListeningScript) { s.Questions[3].ID = "u01-l01" },
		"answer both accepted and wrong": func(s *ListeningScript) {
			s.Questions[1].WrongAnswers = []ListeningWrongAnswer{{Answer: "11 h 30", WhyWrongEN: "x", WhyWrongZH: "x"}}
		},
		"no main idea":            func(s *ListeningScript) { s.Questions[0].Kind = ListeningDetail },
		"line out of order":       func(s *ListeningScript) { s.Lines[1].ID = "s3" },
		"line without speaker":    func(s *ListeningScript) { s.Lines[0].Speaker = " " },
		"line starting with time": func(s *ListeningScript) { s.Lines[0].Text = "0:12 Bonjour." },
		"no authored source":      func(s *ListeningScript) { s.Source = nil },
		"bad script id":           func(s *ListeningScript) { s.ID = "u01" },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			s := scriptFixture()
			mutate(&s)
			if err := ValidateListeningScript(&s); !errors.Is(err, ErrValidation) {
				t.Fatalf("want a validation error, got %v", err)
			}
		})
	}
}

// Generated content keeps its contract: no authored-only field, at most one
// inference, and no clock time absent from the transcript.
func TestValidateListeningExercise_GeneratedContentKeepsItsRules(t *testing.T) {
	s := scriptFixture()
	segs := s.Segments()
	generated := func() ListeningExerciseContent {
		return ListeningExerciseContent{
			Items: []ListeningItem{
				{Kind: ListeningMainIdea, Question: "Où ?", ExpectedAnswer: "Au cabinet.", RationaleEN: "a", RationaleZH: "a", Segments: []int{2}},
				{Kind: ListeningDetail, Question: "Quand ?", ExpectedAnswer: "Onze heures et demie.", RationaleEN: "b", RationaleZH: "b", Segments: []int{2}},
			},
			Annotations: []ListeningAnnotation{{Kind: "vocabulary", Segment: 3, Excerpt: "salle d'attente", NoteEN: "waiting room", NoteZH: "候诊室"}},
		}
	}
	c := generated()
	if err := ValidateListeningExercise(segs, &c); err != nil {
		t.Fatalf("valid generated content refused: %v", err)
	}
	for name, mutate := range map[string]func(*ListeningExerciseContent){
		"authored choices": func(c *ListeningExerciseContent) { c.Items[0].Choices = []string{"Au cabinet.", "À la gare."} },
		"authored id":      func(c *ListeningExerciseContent) { c.Items[0].ID = "x-1" },
		"authored evidence": func(c *ListeningExerciseContent) {
			c.Items[0].Evidence = []ListeningEvidence{{Segment: 2, Excerpt: "docteur"}}
		},
		"invented time": func(c *ListeningExerciseContent) { c.Items[1].RationaleEN = "At 11:30." },
		"two inferences": func(c *ListeningExerciseContent) {
			inf := ListeningItem{Kind: ListeningInference, Question: "?", ExpectedAnswer: "x", RationaleEN: "x", RationaleZH: "x", Segments: []int{1}}
			c.Items = append(c.Items, inf, inf)
		},
		"no annotation": func(c *ListeningExerciseContent) { c.Annotations = nil },
	} {
		t.Run(name, func(t *testing.T) {
			c := generated()
			mutate(&c)
			if err := ValidateListeningExercise(segs, &c); !errors.Is(err, ErrValidation) {
				t.Fatalf("want a validation error, got %v", err)
			}
		})
	}
}

func TestParseListeningScriptPack(t *testing.T) {
	pack := ListeningScriptPack{SchemaVersion: ListeningScriptPackID, Notice: "n", Scripts: []ListeningScript{scriptFixture()}}
	raw, _ := json.Marshal(pack)
	if _, err := ParseListeningScriptPack(raw); err != nil {
		t.Fatalf("valid pack refused: %v", err)
	}
	// Unknown fields are refused, so a link or timestamp cannot ride along.
	withURL := strings.Replace(string(raw), `"genre":`, `"source_url":"https://youtu.be/aBcDeFgHiJk","genre":`, 1)
	if _, err := ParseListeningScriptPack([]byte(withURL)); !errors.Is(err, ErrValidation) {
		t.Fatalf("a pack with a link: %v", err)
	}
	withTime := strings.Replace(string(raw), `"speaker":"Agent"`, `"speaker":"Agent","start_seconds":12`, 1)
	if _, err := ParseListeningScriptPack([]byte(withTime)); !errors.Is(err, ErrValidation) {
		t.Fatalf("a pack with a timestamp: %v", err)
	}
	pack.Scripts = append(pack.Scripts, scriptFixture())
	raw, _ = json.Marshal(pack)
	if _, err := ParseListeningScriptPack(raw); !errors.Is(err, ErrValidation) {
		t.Fatalf("a repeated script: %v", err)
	}
	if _, err := ParseListeningScriptPack([]byte(`{"schema_version":"flh_reading_pack_v1","scripts":[]}`)); !errors.Is(err, ErrValidation) {
		t.Fatalf("a wrong schema: %v", err)
	}
}
