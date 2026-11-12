package speaking_test

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/domain"
	"french-learning-app/internal/listening/listeningfake"
	"french-learning-app/internal/speaking"
	"french-learning-app/internal/speaking/speakingfake"
)

const key = "sk-speaking-adapter-secret"

// synthWAV is a tiny synthetic WAV header plus silence: enough for the magic check.
func synthWAV() []byte {
	return append([]byte("RIFF\x24\x08\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80\x3e\x00\x00\x00\x7d\x00\x00\x02\x00\x10\x00data\x00\x08\x00\x00"), make([]byte, 2048)...)
}

func wavFormat(t *testing.T) domain.SpeakingAudioFormat {
	f, err := domain.SpeakingAudioType("audio/x-wav")
	if err != nil {
		t.Fatal(err)
	}
	return f
}

func TestTranscriberSendsOnlyTheAudioModelAndFormat(t *testing.T) {
	fake := speakingfake.New(t, key, "Salut Léa, c'est Sam.")
	tr := speaking.NewTranscriber(key, "gpt-transcribe", fake.URL()+"/", 2*time.Second)
	audio := synthWAV()
	text, err := tr.Transcribe(context.Background(), domain.SpeakingTranscriptionInput{Audio: audio, Format: wavFormat(t)})
	if err != nil || text != "Salut Léa, c'est Sam." {
		t.Fatalf("transcribe: %q %v", text, err)
	}
	sum := sha256.Sum256(audio)
	got := fake.Received()
	if len(got) != 1 {
		t.Fatalf("calls = %d", len(got))
	}
	r := got[0]
	// No language field (its name differs between models) and no prompt: the
	// transcript must not be nudged towards the expected answer.
	if r.Auth != "Bearer "+key || r.Filename != "take.wav" || r.PartType != "audio/wav" || r.AudioBytes != len(audio) || r.AudioSHA256 != hex.EncodeToString(sum[:]) ||
		len(r.Fields) != 2 || r.Fields["model"] != "gpt-transcribe" || r.Fields["response_format"] != "json" {
		t.Fatalf("received = %+v", r)
	}
	if tr.Name() != "openai:gpt-transcribe:speaking_transcription_v1" {
		t.Fatalf("name = %s", tr.Name())
	}
}

func TestTranscriberErrorsAreClassifiedAndSecretSafe(t *testing.T) {
	for name, tc := range map[string]struct {
		mode    string
		status  int
		delay   time.Duration
		is      error
		unknown bool
	}{
		"http 500":     {speakingfake.ModeStatus, http.StatusInternalServerError, 0, domain.ErrProviderUnavailable, false},
		"malformed":    {speakingfake.ModeMalformed, 0, 0, domain.ErrValidation, false},
		"empty text":   {speakingfake.ModeEmpty, 0, 0, domain.ErrValidation, false},
		"dropped":      {speakingfake.ModeDrop, 0, 0, domain.ErrOutcomeUnknown, true},
		"timeout":      {speakingfake.ModeHang, 0, time.Second, domain.ErrProviderTimeout, false},
		"unauthorized": {speakingfake.ModeOK, 0, 0, domain.ErrProviderUnavailable, false},
	} {
		t.Run(name, func(t *testing.T) {
			fake := speakingfake.New(t, key, "texte")
			fake.Set(tc.mode, tc.status, tc.delay)
			apiKey := key
			if name == "unauthorized" {
				apiKey = "sk-wrong"
			}
			tr := speaking.NewTranscriber(apiKey, "m", fake.URL(), 200*time.Millisecond)
			_, err := tr.Transcribe(context.Background(), domain.SpeakingTranscriptionInput{Audio: synthWAV(), Format: wavFormat(t)})
			if !errors.Is(err, tc.is) || errors.Is(err, domain.ErrOutcomeUnknown) != tc.unknown || strings.Contains(err.Error(), key) || strings.Contains(err.Error(), "fake failure") {
				t.Fatalf("err = %v", err)
			}
		})
	}
	// A request that never left the process is a definite failure, not unknown.
	dead := httptest.NewServer(http.NotFoundHandler())
	url := dead.URL
	dead.Close()
	_, err := speaking.NewTranscriber(key, "m", url, time.Second).Transcribe(context.Background(), domain.SpeakingTranscriptionInput{Audio: synthWAV(), Format: wavFormat(t)})
	if !errors.Is(err, domain.ErrProviderUnavailable) || errors.Is(err, domain.ErrOutcomeUnknown) {
		t.Fatalf("connection refused: %v", err)
	}
}

func fixture(t *testing.T) string {
	raw, err := os.ReadFile("testdata/invitation_feedback.json")
	if err != nil {
		t.Fatal(err)
	}
	return string(raw)
}

func example(t *testing.T) string {
	set, err := domain.ParseSpeakingPrompts(speaking.ExamplePrompts())
	if err != nil {
		t.Fatal(err)
	}
	return set.Prompts[0].ExampleTranscript
}

func TestFeedbackGeneratorRequestIsStrictAndOutputIsGrounded(t *testing.T) {
	var captured map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(raw, &captured)
		body, _ := json.Marshal(map[string]any{"status": "completed", "output": []any{map[string]any{"type": "message",
			"content": []any{map[string]any{"type": "output_text", "text": fixture(t)}}}}})
		_, _ = w.Write(body)
	}))
	t.Cleanup(srv.Close)
	gen := speaking.NewOpenAI(key, "gpt-test", srv.URL, time.Second)
	c, err := gen.Generate(context.Background(), domain.SpeakingFeedbackInput{Title: "Répondre", Situation: "Léa vous invite.", Requirements: []string{"Remerciez-la."},
		SecondsMin: 30, SecondsMax: 90, DurationMS: 41_400, Transcript: example(t), WordCount: 70})
	if err != nil || c.Improvements[0].Grounding != domain.WritingLocated || c.Improvements[2].Grounding != domain.WritingAmbiguous || c.Improvements[3].Grounding != domain.WritingNotFound {
		t.Fatalf("generate: %v %+v", err, c)
	}
	if captured["store"] != false || captured["tool_choice"] != "none" || len(captured["tools"].([]any)) != 0 {
		t.Fatalf("request = %v", captured)
	}
	schema, _ := json.Marshal(captured["text"])
	for _, forbidden := range []string{"grounding", "start", "score", "pronunciation", "spelling"} {
		if strings.Contains(string(schema), `"`+forbidden+`"`) {
			t.Errorf("schema offers %q", forbidden)
		}
	}
	input, _ := json.Marshal(captured["input"])
	if !strings.Contains(string(input), "never comment on pronunciation") || !strings.Contains(string(input), `\"recorded_seconds\":41`) {
		t.Fatalf("input = %s", input)
	}
	if gen.Name() != "openai:gpt-test:speaking_feedback_v1" {
		t.Fatalf("name = %s", gen.Name())
	}
}

func TestFeedbackGeneratorRefusesClaimsTheTranscriptCannotSupport(t *testing.T) {
	for name, edit := range map[string][2]string{
		"pronunciation": {`"comment_en": "The message is short`, `"comment_en": "Your pronunciation is clear and the message is short`},
		"grounding":     {`"category": "grammar",`, `"category": "grammar", "grounding": "located",`},
		"score field":   {`"rating": "partly_met",`, `"rating": "partly_met", "score": 14,`},
	} {
		t.Run(name, func(t *testing.T) {
			out := strings.Replace(fixture(t), edit[0], edit[1], 1)
			if out == fixture(t) {
				t.Fatal("edit did not apply")
			}
			model := listeningfake.NewResponses(t, key, out)
			_, err := speaking.NewOpenAI(key, "m", model.URL(), time.Second).Generate(context.Background(), domain.SpeakingFeedbackInput{Transcript: example(t)})
			if !errors.Is(err, domain.ErrValidation) {
				t.Fatalf("err = %v", err)
			}
		})
	}
}

func TestEmbeddedPromptsAreThreeOriginalPracticalTasks(t *testing.T) {
	set, err := domain.ParseSpeakingPrompts(speaking.ExamplePrompts())
	if err != nil {
		t.Fatal(err)
	}
	if len(set.Prompts) != 3 || !strings.Contains(set.Notice, "Not official exam items") || !strings.Contains(set.Notice, "cannot judge pronunciation") {
		t.Fatalf("set = %+v", set)
	}
	for _, p := range set.Prompts {
		if p.SecondsMax*1000 > domain.MaxSpeakingDurationMS || len(p.Requirements) < 3 {
			t.Errorf("%s: %+v", p.ID, p)
		}
	}
}
