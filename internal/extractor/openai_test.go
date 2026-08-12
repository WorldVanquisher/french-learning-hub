package extractor

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

const testAPIKey = "sk-test-secret-value"

// okResponseBody builds a well-formed Responses API body whose structured output
// encodes the given units payload.
func okResponseBody(t *testing.T, payload unitsPayload) string {
	t.Helper()
	inner, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}
	resp := responsesResponse{
		Status: "completed",
		Output: []outputItem{{
			Type: "message",
			Content: []outputContent{{
				Type: "output_text",
				Text: string(inner),
			}},
		}},
	}
	out, err := json.Marshal(resp)
	if err != nil {
		t.Fatalf("marshal response: %v", err)
	}
	return string(out)
}

// rawResponseBody wraps an arbitrary structured-output string as a completed
// Responses body, so tests can inject output that is not a valid units payload.
func rawResponseBody(t *testing.T, structuredOutput string) string {
	t.Helper()
	resp := responsesResponse{
		Status: "completed",
		Output: []outputItem{{
			Type:    "message",
			Content: []outputContent{{Type: "output_text", Text: structuredOutput}},
		}},
	}
	out, err := json.Marshal(resp)
	if err != nil {
		t.Fatalf("marshal response: %v", err)
	}
	return string(out)
}

func newTestServer(t *testing.T, h http.HandlerFunc) (*httptest.Server, *OpenAI) {
	t.Helper()
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)
	ex := NewOpenAIWithClient(testAPIKey, "gpt-test", srv.URL, srv.Client())
	return srv, ex
}

func testSource() domain.ExtractionSource {
	fb := int64(7)
	return domain.ExtractionSource{
		EntryID:              1,
		OriginalInput:        "Je veux aller au marché",
		OriginalContext:      "practicing near-future plans",
		EffectiveCategory:    "grammar",
		EffectiveExplanation: "use of vouloir + infinitive",
		SourceAnalysisID:     3,
		SourceFeedbackID:     &fb,
		Resolution:           domain.ResolutionAccepted,
	}
}

func ptr(s string) *string { return &s }

func TestExtractor_SendsCorrectPathMethodAndAuth(t *testing.T) {
	var gotPath, gotMethod, gotAuth, gotContentType string
	_, ex := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		gotMethod = r.Method
		gotAuth = r.Header.Get("Authorization")
		gotContentType = r.Header.Get("Content-Type")
		io.WriteString(w, okResponseBody(t, unitsPayload{Units: []unitPayload{}}))
	})

	if _, err := ex.Extract(context.Background(), testSource()); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if gotMethod != http.MethodPost {
		t.Errorf("method = %q, want POST", gotMethod)
	}
	if gotPath != "/responses" {
		t.Errorf("path = %q, want /responses", gotPath)
	}
	if gotAuth != "Bearer "+testAPIKey {
		t.Errorf("authorization header = %q, want bearer key", gotAuth)
	}
	if gotContentType != "application/json" {
		t.Errorf("content-type = %q", gotContentType)
	}
}

func TestExtractor_RequestBodyContract(t *testing.T) {
	var body responsesRequest
	_, ex := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(raw, &body)
		io.WriteString(w, okResponseBody(t, unitsPayload{Units: []unitPayload{}}))
	})

	source := testSource()
	if _, err := ex.Extract(context.Background(), source); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if body.Store != false {
		t.Errorf("store = %v, want false", body.Store)
	}
	if body.Text.Format.Type != "json_schema" || !body.Text.Format.Strict {
		t.Errorf("expected strict json_schema format, got %+v", body.Text.Format)
	}
	if body.Text.Format.Schema["additionalProperties"] != false {
		t.Errorf("schema must disallow additional properties")
	}
	if len(body.Tools) != 0 {
		t.Errorf("tools must be empty, got %v", body.Tools)
	}
	if body.ToolChoice != "none" {
		t.Errorf("tool_choice = %q, want none", body.ToolChoice)
	}
	if len(body.Input) != 2 {
		t.Fatalf("expected 2 input messages, got %d", len(body.Input))
	}
	dev, usr := body.Input[0], body.Input[1]
	if dev.Role != "developer" || usr.Role != "user" {
		t.Errorf("roles = %q,%q want developer,user", dev.Role, usr.Role)
	}
	// The untrusted learner input must live only in the user message.
	if strings.Contains(dev.Content[0].Text, source.OriginalInput) {
		t.Errorf("developer instruction must not contain the untrusted original input")
	}
	if !strings.Contains(usr.Content[0].Text, source.OriginalInput) {
		t.Errorf("user payload missing original input")
	}
	if !strings.Contains(usr.Content[0].Text, source.EffectiveExplanation) {
		t.Errorf("user payload missing effective explanation (extraction source must include effective interpretation)")
	}

	// kind must be constrained to the shared knowledge-kind vocabulary via enum.
	units := body.Text.Format.Schema["properties"].(map[string]any)["units"].(map[string]any)
	item := units["items"].(map[string]any)
	enum, ok := item["properties"].(map[string]any)["kind"].(map[string]any)["enum"]
	if !ok {
		t.Fatalf("schema kind missing enum")
	}
	if enumVals, ok := enum.([]any); !ok || len(enumVals) != len(domain.KnowledgeKindStrings()) {
		t.Fatalf("kind enum should list all %d kinds, got %v", len(domain.KnowledgeKindStrings()), enum)
	}
}

func TestExtractor_ParsesMultipleUnits(t *testing.T) {
	_, ex := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, okResponseBody(t, unitsPayload{Units: []unitPayload{
			{Kind: "grammar", Canonical: "vouloir + infinitif", Statement: "vouloir takes a bare infinitive", Example: ptr("je veux partir"), Confidence: 0.9},
			{Kind: "vocabulary", Canonical: "le marché", Statement: "marché means market", Example: nil, Confidence: 0.8},
		}}))
	})

	res, err := ex.Extract(context.Background(), testSource())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(res.Units) != 2 {
		t.Fatalf("got %d units, want 2", len(res.Units))
	}
	if res.Units[0].Kind != domain.KindGrammar || res.Units[1].Kind != domain.KindVocabulary {
		t.Fatalf("unexpected kinds: %+v", res.Units)
	}
	if res.Units[0].Example == nil || *res.Units[0].Example != "je veux partir" {
		t.Fatalf("expected example on first unit")
	}
	if res.Units[1].Example != nil {
		t.Fatalf("expected nil example on second unit")
	}
}

func TestExtractor_ZeroUnitsIsValid(t *testing.T) {
	_, ex := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, okResponseBody(t, unitsPayload{Units: []unitPayload{}}))
	})

	res, err := ex.Extract(context.Background(), testSource())
	if err != nil {
		t.Fatalf("zero units must be a valid result, got error: %v", err)
	}
	if len(res.Units) != 0 {
		t.Fatalf("expected 0 units, got %d", len(res.Units))
	}
}

func TestExtractor_ProvenanceName(t *testing.T) {
	ex := NewOpenAI(testAPIKey, "gpt-4o-mini", "https://api.openai.com/v1", time.Second)
	want := "openai:gpt-4o-mini:knowledge_extraction_v1"
	if got := ex.Name(); got != want {
		t.Fatalf("Name() = %q, want %q", got, want)
	}
}

func TestExtractor_Timeout(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-r.Context().Done():
		case <-time.After(2 * time.Second):
		}
	}))
	t.Cleanup(srv.Close)
	ex := NewOpenAIWithClient(testAPIKey, "gpt-test", srv.URL, &http.Client{Timeout: 50 * time.Millisecond})

	_, err := ex.Extract(context.Background(), testSource())
	if !errors.Is(err, domain.ErrProviderTimeout) {
		t.Fatalf("expected ErrProviderTimeout, got %v", err)
	}
}

func TestExtractor_ContextCancellation(t *testing.T) {
	_, ex := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		<-r.Context().Done()
	})
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	_, err := ex.Extract(ctx, testSource())
	if !errors.Is(err, domain.ErrProviderUnavailable) {
		t.Fatalf("expected ErrProviderUnavailable, got %v", err)
	}
}

func TestExtractor_HTTPErrorStatuses(t *testing.T) {
	for _, status := range []int{http.StatusUnauthorized, http.StatusTooManyRequests, http.StatusInternalServerError} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			_, ex := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(status)
				io.WriteString(w, `{"error":{"message":"nope","type":"x"}}`)
			})
			_, err := ex.Extract(context.Background(), testSource())
			if !errors.Is(err, domain.ErrProviderUnavailable) {
				t.Fatalf("status %d: expected ErrProviderUnavailable, got %v", status, err)
			}
		})
	}
}

func TestExtractor_MalformedJSON(t *testing.T) {
	_, ex := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, `{not valid json`)
	})
	_, err := ex.Extract(context.Background(), testSource())
	if !errors.Is(err, domain.ErrProviderUnavailable) {
		t.Fatalf("expected ErrProviderUnavailable, got %v", err)
	}
}

func TestExtractor_Refusal(t *testing.T) {
	_, ex := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, `{"status":"completed","output":[{"type":"message","content":[{"type":"refusal","refusal":"I can't help with that."}]}]}`)
	})
	_, err := ex.Extract(context.Background(), testSource())
	if !errors.Is(err, domain.ErrProviderUnavailable) {
		t.Fatalf("expected ErrProviderUnavailable, got %v", err)
	}
}

func TestExtractor_IncompleteOutput(t *testing.T) {
	_, ex := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, `{"status":"incomplete","incomplete_details":{"reason":"max_output_tokens"},"output":[]}`)
	})
	_, err := ex.Extract(context.Background(), testSource())
	if !errors.Is(err, domain.ErrProviderUnavailable) {
		t.Fatalf("expected ErrProviderUnavailable, got %v", err)
	}
}

func TestExtractor_InvalidKindFailsValidation(t *testing.T) {
	_, ex := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, okResponseBody(t, unitsPayload{Units: []unitPayload{
			{Kind: "conjugation", Canonical: "x", Statement: "y", Confidence: 0.5}, // not a v1 kind
		}}))
	})
	_, err := ex.Extract(context.Background(), testSource())
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("expected ErrValidation for invalid kind, got %v", err)
	}
}

func TestExtractor_InvalidConfidenceFailsValidation(t *testing.T) {
	_, ex := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, okResponseBody(t, unitsPayload{Units: []unitPayload{
			{Kind: "grammar", Canonical: "x", Statement: "y", Confidence: 5}, // out of range
		}}))
	})
	_, err := ex.Extract(context.Background(), testSource())
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("expected ErrValidation for bad confidence, got %v", err)
	}
}

func TestExtractor_MissingCanonicalFailsValidation(t *testing.T) {
	_, ex := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, okResponseBody(t, unitsPayload{Units: []unitPayload{
			{Kind: "grammar", Canonical: "   ", Statement: "y", Confidence: 0.5},
		}}))
	})
	_, err := ex.Extract(context.Background(), testSource())
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("expected ErrValidation for missing canonical, got %v", err)
	}
}

func TestExtractor_StructuredOutputNotJSON(t *testing.T) {
	_, ex := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, rawResponseBody(t, `this is not json`))
	})
	_, err := ex.Extract(context.Background(), testSource())
	if !errors.Is(err, domain.ErrProviderUnavailable) {
		t.Fatalf("expected ErrProviderUnavailable for non-JSON structured output, got %v", err)
	}
}

// TestExtractor_ErrorsDoNotLeakAPIKey checks that no returned error string
// contains the API key across representative failure modes.
func TestExtractor_ErrorsDoNotLeakAPIKey(t *testing.T) {
	cases := map[string]http.HandlerFunc{
		"401": func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusUnauthorized)
			io.WriteString(w, `{"error":{"message":"bad key `+testAPIKey+`"}}`)
		},
		"malformed": func(w http.ResponseWriter, r *http.Request) { io.WriteString(w, `{bad`) },
		"refusal": func(w http.ResponseWriter, r *http.Request) {
			io.WriteString(w, `{"status":"completed","output":[{"type":"message","content":[{"type":"refusal","refusal":"no"}]}]}`)
		},
	}
	for name, h := range cases {
		t.Run(name, func(t *testing.T) {
			_, ex := newTestServer(t, h)
			_, err := ex.Extract(context.Background(), testSource())
			if err == nil {
				t.Fatal("expected an error")
			}
			if strings.Contains(err.Error(), testAPIKey) {
				t.Fatalf("error leaked API key: %q", err.Error())
			}
		})
	}
}
