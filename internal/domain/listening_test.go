package domain

import (
	"errors"
	"strings"
	"testing"
)

func TestParseYouTubeURL(t *testing.T) {
	const want = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
	for _, raw := range []string{
		"https://www.youtube.com/watch?v=dQw4w9WgXcQ",
		" https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s ",
		"http://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ",
		"https://youtu.be/dQw4w9WgXcQ?si=abc",
		"https://www.youtube.com/shorts/dQw4w9WgXcQ",
		"https://www.youtube.com/embed/dQw4w9WgXcQ",
		"https://www.youtube.com/live/dQw4w9WgXcQ",
	} {
		id, canonical, err := ParseYouTubeURL(raw)
		if err != nil || id != "dQw4w9WgXcQ" || canonical != want {
			t.Errorf("%q: %q %q %v", raw, id, canonical, err)
		}
	}
	for _, raw := range []string{
		"", "dQw4w9WgXcQ", "ftp://youtube.com/watch?v=dQw4w9WgXcQ", "https://evil.example/watch?v=dQw4w9WgXcQ",
		"https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ", "https://user:pw@youtube.com/watch?v=dQw4w9WgXcQ",
		"https://youtube.com:8443/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/watch?v=short",
		"https://www.youtube.com/playlist?list=PL123", "https://www.youtube.com/channel/UC123",
		"javascript:alert(1)", "https://youtu.be/dQw4w9WgXcQ/extra", "https://www.youtube.com/watch?v=dQw4w9WgXc!",
	} {
		if _, _, err := ParseYouTubeURL(raw); !errors.Is(err, ErrValidation) {
			t.Errorf("%q accepted: %v", raw, err)
		} else if raw != "" && strings.Contains(err.Error(), raw) {
			t.Errorf("%q echoed in error %v", raw, err)
		}
	}
}

func TestParseTranscript(t *testing.T) {
	segs, timed, err := ParseTranscript("[00:04] Bonjour.\n\n  [1:02:03]   Ça va ?  \n")
	if err != nil || !timed || len(segs) != 2 {
		t.Fatalf("%v %v %v", segs, timed, err)
	}
	if segs[0].Index != 1 || *segs[0].StartSeconds != 4 || segs[0].Text != "Bonjour." || segs[1].Index != 2 || *segs[1].StartSeconds != 3723 || segs[1].Text != "Ça va ?" {
		t.Fatalf("segments = %+v %+v", segs[0], segs[1])
	}
	segs, timed, err = ParseTranscript("Bonjour à tous.\r\nIl fait beau.")
	if err != nil || timed || len(segs) != 2 || segs[0].StartSeconds != nil {
		t.Fatalf("untimed: %v %v %v", segs, timed, err)
	}
	for name, text := range map[string]string{
		"empty":          " \n \n",
		"mixed":          "[00:01] Bonjour.\nSans heure.",
		"backwards":      "[00:10] Un.\n[00:05] Deux.",
		"too long":       strings.Repeat("a", MaxTranscriptBytes+1),
		"long segment":   strings.Repeat("é", MaxSegmentRunes+1),
		"too many lines": strings.Repeat("ligne\n", MaxTranscriptSegments+1),
		"control chars":  "Bonjour\x07 !",
	} {
		if _, _, err := ParseTranscript(text); !errors.Is(err, ErrValidation) {
			t.Errorf("%s accepted: %v", name, err)
		}
	}
}

func listeningSegments() []TranscriptSegment {
	segs, _, err := ParseTranscript("[00:00] Bienvenue dans la chronique.\n[00:04] La bibliothèque ouvre samedi, rue des Lilas.\n[00:10] L'inscription est gratuite avec un justificatif de domicile.\n[00:16] N'hésitez pas à passer, il y aura un concert.")
	if err != nil {
		panic(err)
	}
	return segs
}

func validContent() ListeningExerciseContent {
	return ListeningExerciseContent{
		Items: []ListeningItem{
			{Kind: ListeningMainIdea, Question: "De quoi parle la chronique ?", ExpectedAnswer: "De l'ouverture d'une bibliothèque.", RationaleEN: "Segment 2 announces it.", RationaleZH: "第2段宣布了这件事。", Segments: []int{2}},
			{Kind: ListeningDetail, Question: "Que faut-il pour s'inscrire ?", ExpectedAnswer: "Un justificatif de domicile.", RationaleEN: "Stated in segment 3.", RationaleZH: "第3段说明了。", Segments: []int{3}},
			{Kind: ListeningInference, Question: "Quelle est l'attitude du chroniqueur ?", ExpectedAnswer: "Il encourage les auditeurs.", RationaleEN: "« N'hésitez pas » invites them.", RationaleZH: "« N'hésitez pas » 是邀请。", Segments: []int{4}},
		},
		Annotations: []ListeningAnnotation{
			{Kind: "vocabulary", Segment: 3, Excerpt: "justificatif de domicile", NoteEN: "proof of address", NoteZH: "住址证明"},
		},
	}
}

func TestValidateListeningExercise(t *testing.T) {
	segs := listeningSegments()
	c := validContent()
	if err := ValidateListeningExercise(segs, &c); err != nil {
		t.Fatalf("valid content refused: %v", err)
	}
	cases := map[string]func(c *ListeningExerciseContent){
		"segment out of range":     func(c *ListeningExerciseContent) { c.Items[1].Segments = []int{9} },
		"segment zero":             func(c *ListeningExerciseContent) { c.Items[0].Segments = []int{0} },
		"no segment":               func(c *ListeningExerciseContent) { c.Items[0].Segments = nil },
		"duplicate segment":        func(c *ListeningExerciseContent) { c.Items[0].Segments = []int{2, 2} },
		"no main idea":             func(c *ListeningExerciseContent) { c.Items[0].Kind = ListeningDetail },
		"two inferences":           func(c *ListeningExerciseContent) { c.Items[1].Kind = ListeningInference },
		"unknown kind":             func(c *ListeningExerciseContent) { c.Items[2].Kind = "opinion" },
		"one item":                 func(c *ListeningExerciseContent) { c.Items = c.Items[:1] },
		"empty answer":             func(c *ListeningExerciseContent) { c.Items[0].ExpectedAnswer = "  " },
		"missing chinese":          func(c *ListeningExerciseContent) { c.Items[0].RationaleZH = "" },
		"fabricated time":          func(c *ListeningExerciseContent) { c.Items[0].RationaleEN = "It is said at 00:04." },
		"fabricated time in note":  func(c *ListeningExerciseContent) { c.Annotations[0].NoteEN = "heard at 1:12" },
		"fabricated excerpt":       func(c *ListeningExerciseContent) { c.Annotations[0].Excerpt = "pièce d'identité" },
		"excerpt in other segment": func(c *ListeningExerciseContent) { c.Annotations[0].Segment = 2 },
		"annotation out of range":  func(c *ListeningExerciseContent) { c.Annotations[0].Segment = 5 },
		"no annotation":            func(c *ListeningExerciseContent) { c.Annotations = nil },
		"unknown annotation kind":  func(c *ListeningExerciseContent) { c.Annotations[0].Kind = "culture" },
	}
	for name, mutate := range cases {
		c := validContent()
		mutate(&c)
		if err := ValidateListeningExercise(segs, &c); !errors.Is(err, ErrValidation) {
			t.Errorf("%s accepted: %v", name, err)
		}
	}
	// A time that the transcript text itself contains is not fabricated.
	timed, _, _ := ParseTranscript("Le train part à 8:30.\nIl arrive à midi.")
	c = ListeningExerciseContent{
		Items: []ListeningItem{
			{Kind: ListeningMainIdea, Question: "Q ?", ExpectedAnswer: "Un voyage.", RationaleEN: "Departure at 8:30.", RationaleZH: "8:30 出发。", Segments: []int{1}},
			{Kind: ListeningDetail, Question: "Q ?", ExpectedAnswer: "À 8:30.", RationaleEN: "Segment 1.", RationaleZH: "第1段。", Segments: []int{1}},
		},
		Annotations: []ListeningAnnotation{{Kind: "vocabulary", Segment: 2, Excerpt: "à midi", NoteEN: "at noon", NoteZH: "中午"}},
	}
	if err := ValidateListeningExercise(timed, &c); err != nil {
		t.Fatalf("a time quoted from the transcript was refused: %v", err)
	}
}

func TestListeningFailureCode(t *testing.T) {
	for err, want := range map[error]string{
		ErrProviderTimeout:     ListeningFailureTimeout,
		ErrProviderUnavailable: ListeningFailureUnavailable,
		ErrValidation:          ListeningFailureInvalidOutput,
		errors.New("other"):    ListeningFailureUnavailable,
	} {
		if got := ListeningFailureCode(err); got != want {
			t.Errorf("%v -> %s, want %s", err, got, want)
		}
	}
}
