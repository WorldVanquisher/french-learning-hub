package writing_test

import (
	"context"
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
	"french-learning-app/internal/writing"
)

const key = "sk-writing-generator-secret"

func fixture(t *testing.T) (string, string) {
	t.Helper()
	raw, err := os.ReadFile("testdata/invitation_feedback.json")
	if err != nil {
		t.Fatal(err)
	}
	set, err := domain.ParseWritingPrompts(writing.ExamplePrompts())
	if err != nil {
		t.Fatal(err)
	}
	return set.Prompts[0].ExampleDraft, string(raw)
}

func input(draft string) domain.WritingFeedbackInput {
	return domain.WritingFeedbackInput{Title: "Répondre", Prompt: "Répondez.", Requirements: []string{"Remerciez-la."}, WordMin: 60, WordMax: 90,
		Draft: draft, WordCount: domain.CountWritingWords(draft)}
}

func TestOpenAI_RequestDisciplineAndServerSideGrounding(t *testing.T) {
	draft, output := fixture(t)
	var body map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(raw, &body)
		resp, _ := json.Marshal(map[string]any{"status": "completed", "output": []any{map[string]any{"type": "message",
			"content": []any{map[string]any{"type": "output_text", "text": output}}}}})
		_, _ = w.Write(resp)
	}))
	t.Cleanup(srv.Close)
	gen := writing.NewOpenAI(key, "m", srv.URL, time.Second)
	got, err := gen.Generate(context.Background(), input(draft))
	if err != nil {
		t.Fatal(err)
	}
	if gen.Name() != "openai:m:writing_feedback_v1" || got.Corrections[0].Grounding != domain.WritingLocated || got.Corrections[2].Grounding != domain.WritingAmbiguous ||
		got.Corrections[3].Grounding != domain.WritingNotFound {
		t.Fatalf("feedback = %+v", got.Corrections)
	}
	format := body["text"].(map[string]any)["format"].(map[string]any)
	if body["store"] != false || len(body["tools"].([]any)) != 0 || format["strict"] != true || format["name"] != "writing_feedback" {
		t.Fatalf("request discipline: %v", body)
	}
	user := body["input"].([]any)[1].(map[string]any)["content"].([]any)[0].(map[string]any)["text"].(string)
	if !strings.Contains(user, "Je suis arrivé vers 20 heures") || !strings.Contains(user, `"word_count"`) || strings.Contains(user, key) {
		t.Fatalf("user payload = %s", user)
	}
}

func TestOpenAI_RefusesClaimedLocationsScoresAndLostAnswers(t *testing.T) {
	draft, output := fixture(t)
	cases := map[string]struct {
		output string
		mode   string
		want   error
	}{
		"claimed grounding": {strings.Replace(output, `"category": "grammar",`, `"category": "grammar", "grounding": "located", "start": 3,`, 1), listeningfake.ModeOK, domain.ErrValidation},
		"a score":           {strings.Replace(output, `"rating": "partly_met",`, `"rating": "partly_met", "score": 14,`, 1), listeningfake.ModeOK, domain.ErrValidation},
		"not json":          {"Très bien !", listeningfake.ModeOK, domain.ErrValidation},
		"dropped":           {output, listeningfake.ModeDrop, domain.ErrOutcomeUnknown},
		"timeout":           {output, listeningfake.ModeHang, domain.ErrProviderTimeout},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			fake := listeningfake.NewResponses(t, key, c.output)
			fake.Set(c.mode, 0, 2*time.Second)
			_, err := writing.NewOpenAI(key, "m", fake.URL(), 300*time.Millisecond).Generate(context.Background(), input(draft))
			if !errors.Is(err, c.want) {
				t.Fatalf("err = %v, want %v", err, c.want)
			}
			if strings.Contains(err.Error(), key) || strings.Contains(err.Error(), "Sophie") {
				t.Fatalf("error leaks: %v", err)
			}
		})
	}
}
