package domain

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSpeakingAudioTypeAcceptsOnlyFormatsBothProviderPagesList(t *testing.T) {
	for declared, want := range map[string]SpeakingAudioFormat{
		"audio/webm;codecs=opus": {"audio/webm", "webm"},
		"Audio/WebM":             {"audio/webm", "webm"},
		"audio/mp4":              {"audio/mp4", "mp4"},
		"audio/x-m4a":            {"audio/mp4", "m4a"},
		"audio/mpeg":             {"audio/mpeg", "mp3"},
		"audio/wav":              {"audio/wav", "wav"},
		"audio/x-wav":            {"audio/wav", "wav"},
	} {
		got, err := SpeakingAudioType(declared)
		if err != nil || got != want {
			t.Errorf("%s: %+v %v", declared, got, err)
		}
	}
	// flac and ogg appear in only one of the two provider pages; video and junk never.
	for _, declared := range []string{"audio/ogg;codecs=opus", "audio/flac", "video/webm", "text/plain", "", "audio"} {
		if _, err := SpeakingAudioType(declared); !errors.Is(err, ErrValidation) {
			t.Errorf("%q accepted: %v", declared, err)
		}
	}
}

func TestCheckSpeakingAudioMatchesMagicBytesAndBounds(t *testing.T) {
	wav := append([]byte("RIFF\x24\x00\x00\x00WAVEfmt "), make([]byte, 32)...)
	webm := append([]byte{0x1A, 0x45, 0xDF, 0xA3}, make([]byte, 32)...)
	mp4 := append([]byte("\x00\x00\x00\x18ftypM4A "), make([]byte, 32)...)
	mp3 := append([]byte("ID3\x04"), make([]byte, 32)...)
	f := func(m string) SpeakingAudioFormat { x, _ := SpeakingAudioType(m); return x }
	for _, ok := range []struct {
		mime string
		data []byte
	}{{"audio/wav", wav}, {"audio/webm", webm}, {"audio/mp4", mp4}, {"audio/mpeg", mp3}, {"audio/mpeg", []byte{0xFF, 0xFB, 0x90, 0x00}}} {
		if err := CheckSpeakingAudio(f(ok.mime), ok.data); err != nil {
			t.Errorf("%s refused: %v", ok.mime, err)
		}
	}
	for name, bad := range map[string]struct {
		mime string
		data []byte
	}{
		"wav declared as webm": {"audio/webm", wav},
		"webm declared as wav": {"audio/wav", webm},
		"text as mp3":          {"audio/mpeg", []byte("hello world")},
		"empty":                {"audio/wav", nil},
		"too large":            {"audio/wav", append(wav, make([]byte, MaxSpeakingAudioBytes)...)},
	} {
		if err := CheckSpeakingAudio(f(bad.mime), bad.data); !errors.Is(err, ErrValidation) {
			t.Errorf("%s: %v", name, err)
		}
	}
}

func TestNormalizeSpeakingTakeKeepsOnlyBoundedMetadata(t *testing.T) {
	sha := strings.Repeat("AB", 32)
	got, err := NormalizeSpeakingTake(SpeakingTake{AudioSource: SpeakingAudioRecording, AudioMIME: "audio/webm;codecs=opus", AudioBytes: 2048, AudioSHA256: sha, DurationMS: 41_500})
	if err != nil || got.AudioMIME != "audio/webm" || got.AudioSHA256 != strings.ToLower(sha) {
		t.Fatalf("recording: %+v %v", got, err)
	}
	if _, err := NormalizeSpeakingTake(SpeakingTake{AudioSource: SpeakingAudioNone}); err != nil {
		t.Fatalf("typed take: %v", err)
	}
	for name, bad := range map[string]SpeakingTake{
		"typed with metadata": {AudioSource: SpeakingAudioNone, DurationMS: 10},
		"unknown source":      {AudioSource: "upload"},
		"no duration":         {AudioSource: SpeakingAudioFile, AudioMIME: "audio/wav", AudioBytes: 10, AudioSHA256: sha},
		"over two minutes":    {AudioSource: SpeakingAudioRecording, AudioMIME: "audio/webm", AudioBytes: 10, AudioSHA256: sha, DurationMS: MaxSpeakingDurationMS + 1},
		"too many bytes":      {AudioSource: SpeakingAudioRecording, AudioMIME: "audio/webm", AudioBytes: MaxSpeakingAudioBytes + 1, AudioSHA256: sha, DurationMS: 10},
		"bad digest":          {AudioSource: SpeakingAudioRecording, AudioMIME: "audio/webm", AudioBytes: 10, AudioSHA256: "abc", DurationMS: 10},
		"ogg":                 {AudioSource: SpeakingAudioRecording, AudioMIME: "audio/ogg", AudioBytes: 10, AudioSHA256: sha, DurationMS: 10},
	} {
		if _, err := NormalizeSpeakingTake(bad); !errors.Is(err, ErrValidation) {
			t.Errorf("%s: %v", name, err)
		}
	}
}

func speakingFixture(t *testing.T) (string, SpeakingFeedbackContent) {
	t.Helper()
	var set SpeakingPromptSet
	raw, err := os.ReadFile(filepath.Join("..", "speaking", "prompts", "speaking_prompts_v1.json"))
	if err != nil {
		t.Fatal(err)
	}
	if set, err = ParseSpeakingPrompts(raw); err != nil {
		t.Fatal(err)
	}
	raw, err = os.ReadFile(filepath.Join("..", "speaking", "testdata", "invitation_feedback.json"))
	if err != nil {
		t.Fatal(err)
	}
	var c SpeakingFeedbackContent
	if err := json.Unmarshal(raw, &c); err != nil {
		t.Fatal(err)
	}
	return set.Prompts[0].ExampleTranscript, c
}

func TestValidateSpeakingFeedbackGroundsQuotesAgainstTheExactTranscript(t *testing.T) {
	transcript, c := speakingFixture(t)
	if err := ValidateSpeakingFeedback(transcript, &c); err != nil {
		t.Fatal(err)
	}
	got := []string{}
	for _, k := range c.Improvements {
		got = append(got, k.Grounding)
	}
	if strings.Join(got, ",") != "located,located,ambiguous,not_found" || *c.Improvements[0].Start != 100 || *c.Improvements[1].Start != 166 ||
		c.Improvements[2].Start != nil || c.Improvements[3].Start != nil {
		t.Fatalf("grounding = %v", c.Improvements)
	}
	// The same report against a corrected transcript: the fixed quote is gone.
	_, c2 := speakingFixture(t)
	fixed := strings.Replace(transcript, "je suis arrivé vers midi et demi", "j'arriverai vers midi et demi", 1)
	if err := ValidateSpeakingFeedback(fixed, &c2); err != nil || c2.Improvements[0].Grounding != WritingNotFound {
		t.Fatalf("against another version: %v %v", err, c2.Improvements[0])
	}
}

func TestValidateSpeakingFeedbackRefusesPronunciationScoresAndUnknownShapes(t *testing.T) {
	transcript, _ := speakingFixture(t)
	for name, mutate := range map[string]func(c *SpeakingFeedbackContent){
		"pronunciation (en)": func(c *SpeakingFeedbackContent) { c.Clarity.CommentEN = "Your pronunciation of « tarte » is clear." },
		"accent (en)":        func(c *SpeakingFeedbackContent) { c.TaskFulfilment.CommentEN = "Your accent sounds natural." },
		"intonation hint": func(c *SpeakingFeedbackContent) {
			c.Improvements[0].HintEN = "Use a rising intonation for the question."
		},
		"pronunciation (zh)":   func(c *SpeakingFeedbackContent) { c.Clarity.CommentZH = "你的发音很清楚。" },
		"score":                func(c *SpeakingFeedbackContent) { c.TaskFulfilment.CommentEN = "This would score 18/25." },
		"CEFR level":           func(c *SpeakingFeedbackContent) { c.Clarity.CommentEN = "Solid CEFR B1 work." },
		"exam (zh)":            func(c *SpeakingFeedbackContent) { c.Improvements[1].ReasonZH = "考试评分会扣分。" },
		"spelling category":    func(c *SpeakingFeedbackContent) { c.Improvements[0].Category = "spelling" },
		"pronunciation cat.":   func(c *SpeakingFeedbackContent) { c.Improvements[0].Category = "pronunciation" },
		"unknown rating":       func(c *SpeakingFeedbackContent) { c.TaskFulfilment.Rating = "excellent" },
		"blank comment":        func(c *SpeakingFeedbackContent) { c.Clarity.CommentZH = " " },
		"empty quote":          func(c *SpeakingFeedbackContent) { c.Improvements[0].Quote = " " },
		"same as quote":        func(c *SpeakingFeedbackContent) { c.Improvements[0].Suggestion = c.Improvements[0].Quote },
		"five improvements":    func(c *SpeakingFeedbackContent) { c.Improvements = append(c.Improvements, c.Improvements[0]) },
		"oversized suggestion": func(c *SpeakingFeedbackContent) { c.Improvements[0].Suggestion = strings.Repeat("a", 301) },
	} {
		_, c := speakingFixture(t)
		mutate(&c)
		if err := ValidateSpeakingFeedback(transcript, &c); !errors.Is(err, ErrValidation) {
			t.Errorf("%s accepted: %v", name, err)
		}
	}
	// The French suggestion is the learner's language material and is not
	// scanned: « accent » there is a word, not a judgment.
	_, c := speakingFixture(t)
	c.Improvements[2].Suggestion = "avec un accent de joie"
	if err := ValidateSpeakingFeedback(transcript, &c); err != nil {
		t.Fatalf("French suggestion refused: %v", err)
	}
}

func TestParseSpeakingPromptsRefusesMalformedSets(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "speaking", "prompts", "speaking_prompts_v1.json"))
	if err != nil {
		t.Fatal(err)
	}
	set, err := ParseSpeakingPrompts(raw)
	if err != nil || len(set.Prompts) != 3 || set.Prompts[0].ID != "sp-invitation-reponse" || set.Prompts[1].ID != "sp-demande-renseignements" || set.Prompts[2].ID != "sp-changement-programme" {
		t.Fatalf("embedded set: %v %+v", err, set)
	}
	for name, edit := range map[string][2]string{
		"bad id":         {`"sp-invitation-reponse"`, `"Invitation"`},
		"unknown field":  {`"format": "message vocal",`, `"format": "message vocal", "score": 3,`},
		"too long":       {`"seconds_max": 90,`, `"seconds_max": 600,`},
		"wrong schema":   {`flh_speaking_prompts_v1`, `flh_writing_prompts_v1`},
		"inverted range": {`"seconds_min": 30,`, `"seconds_min": 95,`},
	} {
		bad := strings.Replace(string(raw), edit[0], edit[1], 1)
		if bad == string(raw) {
			t.Fatalf("%s: edit did not apply", name)
		}
		if _, err := ParseSpeakingPrompts([]byte(bad)); !errors.Is(err, ErrValidation) {
			t.Errorf("%s accepted: %v", name, err)
		}
	}
	var generic map[string]any
	if err := json.Unmarshal(raw, &generic); err != nil {
		t.Fatal(err)
	}
	generic["prompts"].([]any)[1].(map[string]any)["example_transcript"] = "  "
	blank, _ := json.Marshal(generic)
	if _, err := ParseSpeakingPrompts(blank); !errors.Is(err, ErrValidation) || !strings.Contains(err.Error(), "example transcript") {
		t.Errorf("blank example accepted: %v", err)
	}
}

func TestNormalizeSpeakingTranscriptKeepsWording(t *testing.T) {
	got, words, err := NormalizeSpeakingTranscript("  Salut Léa,\r\nc'est Sam.  ")
	if err != nil || got != "Salut Léa,\nc'est Sam." || words != 4 {
		t.Fatalf("%q %d %v", got, words, err)
	}
	if _, _, err := NormalizeSpeakingTranscript(strings.Repeat("é", MaxSpeakingTranscriptRunes+1)); !errors.Is(err, ErrValidation) {
		t.Fatalf("oversized: %v", err)
	}
}
