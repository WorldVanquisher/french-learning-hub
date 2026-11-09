package reading_test

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/domain"
	"french-learning-app/internal/listening/listeningfake"
	"french-learning-app/internal/reading"
)

const key = "sk-reading-generator-secret"

var segments = []domain.ReadingSegment{
	{ID: "p1", Text: "Le technicien passera le mardi 14 octobre, entre 9 h et 12 h."},
	{ID: "p2", Text: "Si vous n'êtes pas disponible, merci de me prévenir avant jeudi soir."},
}

const output = `{"items":[
 {"kind":"main_idea","question":"Pourquoi écrit-on ?","reference_answer":"Pour annoncer une visite.","accepted_alternatives":[],"evidence":[{"segment":"p1","excerpt":"Le technicien passera"}],"explanation_en":"p1.","explanation_zh":"p1。"},
 {"kind":"detail","question":"Avant quand prévenir ?","reference_answer":"Avant jeudi soir.","accepted_alternatives":["jeudi soir"],"evidence":[{"segment":"p2","excerpt":"avant jeudi soir"}],"explanation_en":"p2.","explanation_zh":"p2。"},
 {"kind":"inference","question":"Faut-il répondre vite ?","reference_answer":"Oui, sinon le rendez-vous est perdu.","accepted_alternatives":[],"evidence":[{"segment":"p2","excerpt":"merci de me prévenir"}],"explanation_en":"Inference from the deadline.","explanation_zh":"从截止时间推断。"}]}`

func TestOpenAI_RequestDisciplineAndValidOutput(t *testing.T) {
	var body map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(raw, &body)
		resp, _ := json.Marshal(map[string]any{"status": "completed", "output": []any{map[string]any{"type": "message",
			"content": []any{map[string]any{"type": "output_text", "text": output}}}}})
		_, _ = w.Write(resp)
	}))
	t.Cleanup(srv.Close)
	gen := reading.NewOpenAI(key, "m", srv.URL, time.Second)
	got, err := gen.Generate(context.Background(), domain.ReadingGenerationRequest{Title: "Visite", Segments: segments})
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Items) != 3 || got.Items[2].Kind != "inference" || gen.Name() != "openai:m:reading_exercise_v1" {
		t.Fatalf("content = %+v", got)
	}
	format := body["text"].(map[string]any)["format"].(map[string]any)
	if body["store"] != false || len(body["tools"].([]any)) != 0 || body["tool_choice"] != "none" || format["strict"] != true || format["name"] != "reading_exercise" {
		t.Fatalf("request discipline: %v", body)
	}
	user := body["input"].([]any)[1].(map[string]any)["content"].([]any)[0].(map[string]any)["text"].(string)
	if !strings.Contains(user, `"id":"p1"`) || !strings.Contains(user, "jeudi soir") || strings.Contains(user, key) {
		t.Fatalf("user payload = %s", user)
	}
}

func TestOpenAI_UnusableOutputAndLostResponses(t *testing.T) {
	cases := map[string]struct {
		output string
		mode   string
		want   error
	}{
		"invented excerpt":  {strings.Replace(output, `"excerpt":"avant jeudi soir"`, `"excerpt":"avant vendredi"`, 1), listeningfake.ModeOK, domain.ErrValidation},
		"unknown paragraph": {strings.Replace(output, `"segment":"p2","excerpt":"avant jeudi soir"`, `"segment":"p5","excerpt":"avant jeudi soir"`, 1), listeningfake.ModeOK, domain.ErrValidation},
		"extra field":       {strings.Replace(output, `"kind":"main_idea",`, `"kind":"main_idea","line":3,`, 1), listeningfake.ModeOK, domain.ErrValidation},
		"not json":          {"pas du JSON", listeningfake.ModeOK, domain.ErrValidation},
		"dropped":           {output, listeningfake.ModeDrop, domain.ErrOutcomeUnknown},
		"timeout":           {output, listeningfake.ModeHang, domain.ErrProviderTimeout},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			fake := listeningfake.NewResponses(t, key, c.output)
			fake.Set(c.mode, 0, 2*time.Second)
			_, err := reading.NewOpenAI(key, "m", fake.URL(), 300*time.Millisecond).Generate(context.Background(), domain.ReadingGenerationRequest{Title: "t", Segments: segments})
			if !errors.Is(err, c.want) {
				t.Fatalf("err = %v, want %v", err, c.want)
			}
			if strings.Contains(err.Error(), key) || strings.Contains(err.Error(), "jeudi") {
				t.Fatalf("error leaks: %v", err)
			}
		})
	}
}
