package listening

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
)

const testKey = "sk-listening-test-secret"

func segments(t *testing.T) []domain.TranscriptSegment {
	t.Helper()
	s, _, err := domain.ParseTranscript("[00:00] La bibliothèque ouvre samedi.\n[00:05] L'inscription est gratuite avec un justificatif de domicile.")
	if err != nil {
		t.Fatal(err)
	}
	return s
}

const validOutput = `{"items":[
 {"kind":"main_idea","question":"De quoi parle-t-on ?","expected_answer":"D'une bibliothèque qui ouvre.","rationale_en":"Segment 1.","rationale_zh":"第1段。","segments":[1]},
 {"kind":"detail","question":"Que faut-il apporter ?","expected_answer":"Un justificatif de domicile.","rationale_en":"Segment 2.","rationale_zh":"第2段。","segments":[2]}],
 "annotations":[{"kind":"vocabulary","segment":2,"excerpt":"justificatif de domicile","note_en":"proof of address","note_zh":"住址证明"}]}`

// fake answers like the Responses API and records the last request.
func fake(t *testing.T, status int, output string) (*httptest.Server, *map[string]any) {
	t.Helper()
	var last map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(raw, &last)
		if r.URL.Path != "/responses" || r.Header.Get("Authorization") != "Bearer "+testKey {
			http.Error(w, "unexpected", http.StatusTeapot)
			return
		}
		w.WriteHeader(status)
		body, _ := json.Marshal(map[string]any{"status": "completed", "output": []any{map[string]any{
			"type": "message", "content": []any{map[string]any{"type": "output_text", "text": output}}}}})
		_, _ = w.Write(body)
	}))
	t.Cleanup(srv.Close)
	return srv, &last
}

func TestGenerate_ValidOutputAndRequestDiscipline(t *testing.T) {
	srv, last := fake(t, http.StatusOK, validOutput)
	g := NewOpenAI(testKey, "fake-model", srv.URL, 5*time.Second)
	content, err := g.Generate(context.Background(), domain.ListeningGenerationRequest{Title: "Radio", Segments: segments(t)})
	if err != nil {
		t.Fatal(err)
	}
	if len(content.Items) != 2 || content.Annotations[0].Excerpt != "justificatif de domicile" {
		t.Fatalf("content = %+v", content)
	}
	req := *last
	if req["store"] != false || req["tool_choice"] != "none" || len(req["tools"].([]any)) != 0 || req["model"] != "fake-model" {
		t.Fatalf("request discipline: %v", req)
	}
	format := req["text"].(map[string]any)["format"].(map[string]any)
	if format["type"] != "json_schema" || format["strict"] != true || format["name"] != "listening_exercise" {
		t.Fatalf("format = %v", format)
	}
	raw, _ := json.Marshal(req["input"])
	// Segments are sent by number; their timestamps are not sent at all.
	if !strings.Contains(string(raw), `\"number\":2`) || strings.Contains(string(raw), "start_seconds") {
		t.Fatalf("user payload = %s", raw)
	}
	if g.Name() != "openai:fake-model:listening_exercise_v1" {
		t.Fatalf("name = %s", g.Name())
	}
}

func TestGenerate_RefusesUnusableOutputWithoutLeaking(t *testing.T) {
	cases := map[string]struct {
		status int
		output string
		want   error
	}{
		"http 500":           {http.StatusInternalServerError, validOutput, domain.ErrProviderUnavailable},
		"not json":           {http.StatusOK, "voici l'exercice", domain.ErrValidation},
		"extra time field":   {http.StatusOK, strings.Replace(validOutput, `"segments":[1]}`, `"segments":[1],"timestamp":"00:42"}`, 1), domain.ErrValidation},
		"unknown segment":    {http.StatusOK, strings.Replace(validOutput, `"segments":[2]}`, `"segments":[7]}`, 1), domain.ErrValidation},
		"fabricated excerpt": {http.StatusOK, strings.Replace(validOutput, `"excerpt":"justificatif de domicile"`, `"excerpt":"carte d'identité"`, 1), domain.ErrValidation},
		"trailing content":   {http.StatusOK, validOutput + ` {}`, domain.ErrValidation},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			srv, _ := fake(t, c.status, c.output)
			_, err := NewOpenAI(testKey, "fake-model", srv.URL, 5*time.Second).Generate(context.Background(),
				domain.ListeningGenerationRequest{Title: "Radio", Segments: segments(t)})
			if !errors.Is(err, c.want) {
				t.Fatalf("err = %v, want %v", err, c.want)
			}
			if strings.Contains(err.Error(), testKey) || strings.Contains(err.Error(), "bibliothèque") || strings.Contains(err.Error(), "justificatif") {
				t.Fatalf("error leaks key or text: %v", err)
			}
		})
	}
}

func TestGenerate_TimeoutIsReported(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { time.Sleep(300 * time.Millisecond) }))
	t.Cleanup(srv.Close)
	_, err := NewOpenAI(testKey, "m", srv.URL, 50*time.Millisecond).Generate(context.Background(),
		domain.ListeningGenerationRequest{Title: "Radio", Segments: segments(t)})
	if !errors.Is(err, domain.ErrProviderTimeout) {
		t.Fatalf("err = %v", err)
	}
}
