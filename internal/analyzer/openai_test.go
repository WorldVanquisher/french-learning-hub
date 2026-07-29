package analyzer

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

// okResponseBody builds a well-formed Responses API body whose structured
// output encodes the given analysis payload.
func okResponseBody(t *testing.T, payload analysisPayload) string {
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

// newTestServer starts an httptest.Server with the given handler and returns an
// analyzer pointed at it using the default http client.
func newTestServer(t *testing.T, h http.HandlerFunc) (*httptest.Server, *OpenAI) {
	t.Helper()
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)
	an := NewOpenAIWithClient(testAPIKey, "gpt-test", srv.URL, srv.Client())
	return srv, an
}

func testEntry() *domain.Entry {
	return &domain.Entry{
		ID:              1,
		OriginalInput:   "Je suis fatigué",
		OriginalContext: "texting a friend",
	}
}

func TestOpenAI_SendsCorrectPathMethodAndAuth(t *testing.T) {
	var gotPath, gotMethod, gotAuth, gotContentType string
	_, an := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		gotMethod = r.Method
		gotAuth = r.Header.Get("Authorization")
		gotContentType = r.Header.Get("Content-Type")
		io.WriteString(w, okResponseBody(t, analysisPayload{
			Category: "grammar", Explanation: "ok", Confidence: 0.7,
		}))
	})

	if _, err := an.Analyze(context.Background(), testEntry()); err != nil {
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

func TestOpenAI_RequestBodyContract(t *testing.T) {
	var body responsesRequest
	var rawBody []byte
	_, an := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		rawBody, _ = io.ReadAll(r.Body)
		_ = json.Unmarshal(rawBody, &body)
		io.WriteString(w, okResponseBody(t, analysisPayload{
			Category: "grammar", Explanation: "ok", Confidence: 0.7,
		}))
	})

	entry := testEntry()
	if _, err := an.Analyze(context.Background(), entry); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if body.Store != false {
		t.Errorf("store = %v, want false", body.Store)
	}
	if body.Text.Format.Type != "json_schema" || !body.Text.Format.Strict {
		t.Errorf("expected strict json_schema format, got %+v", body.Text.Format)
	}
	if body.Text.Format.Schema["additionalProperties"] != false {
		t.Errorf("schema must disallow additional properties, got %v", body.Text.Format.Schema["additionalProperties"])
	}
	if len(body.Tools) != 0 {
		t.Errorf("tools must be empty, got %v", body.Tools)
	}
	if body.ToolChoice != "none" {
		t.Errorf("tool_choice = %q, want none", body.ToolChoice)
	}

	// Request must use the developer + user content-array shape, keeping the
	// trusted instruction and untrusted entry payload in separate messages.
	if len(body.Input) != 2 {
		t.Fatalf("expected 2 input messages (developer, user), got %d", len(body.Input))
	}
	dev, usr := body.Input[0], body.Input[1]
	if dev.Role != "developer" {
		t.Errorf("first message role = %q, want developer", dev.Role)
	}
	if usr.Role != "user" {
		t.Errorf("second message role = %q, want user", usr.Role)
	}
	if len(dev.Content) != 1 || dev.Content[0].Type != "input_text" {
		t.Errorf("developer content must be a single input_text part, got %+v", dev.Content)
	}
	if len(usr.Content) != 1 || usr.Content[0].Type != "input_text" {
		t.Errorf("user content must be a single input_text part, got %+v", usr.Content)
	}
	// The entry must live only in the user message, never in the developer one.
	if strings.Contains(dev.Content[0].Text, entry.OriginalInput) {
		t.Errorf("developer instruction must not contain the untrusted entry input")
	}
	if !strings.Contains(usr.Content[0].Text, entry.OriginalInput) {
		t.Errorf("user payload missing original input")
	}
	if !strings.Contains(usr.Content[0].Text, entry.OriginalContext) {
		t.Errorf("user payload missing original context")
	}

	// Category must be constrained to the shared domain taxonomy via enum.
	enum, ok := body.Text.Format.Schema["properties"].(map[string]any)["category"].(map[string]any)["enum"]
	if !ok {
		t.Fatalf("schema category is missing an enum: %+v", body.Text.Format.Schema["properties"])
	}
	enumVals, ok := enum.([]any)
	if !ok || len(enumVals) != len(domain.Categories()) {
		t.Fatalf("category enum should list all %d taxonomy values, got %v", len(domain.Categories()), enum)
	}
}

func TestOpenAI_ParsesValidResponse(t *testing.T) {
	_, an := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, okResponseBody(t, analysisPayload{
			Category:    "grammar",
			Explanation: "present tense of être",
			Confidence:  0.9,
			Uncertainty: "",
		}))
	})

	res, err := an.Analyze(context.Background(), testEntry())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if res.Category != "grammar" || res.Explanation != "present tense of être" {
		t.Fatalf("unexpected result: %+v", res)
	}
	if res.Confidence != 0.9 {
		t.Fatalf("confidence = %v, want 0.9", res.Confidence)
	}
}

func TestOpenAI_ProvenanceName(t *testing.T) {
	an := NewOpenAI(testAPIKey, "gpt-4o-mini", "https://api.openai.com/v1", time.Second)
	want := "openai:gpt-4o-mini:fr_l2_taxonomy_v1"
	if got := an.Name(); got != want {
		t.Fatalf("Name() = %q, want %q", got, want)
	}
}

func TestOpenAI_ContextCancellation(t *testing.T) {
	_, an := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		<-r.Context().Done() // never respond until the client gives up
	})

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // already canceled

	_, err := an.Analyze(ctx, testEntry())
	if err == nil {
		t.Fatal("expected error on canceled context")
	}
	if !errors.Is(err, domain.ErrProviderUnavailable) {
		t.Fatalf("expected ErrProviderUnavailable, got %v", err)
	}
}

func TestOpenAI_Timeout(t *testing.T) {
	// Stall longer than the client timeout so the client aborts first, but
	// return on context cancellation or a bounded timer so srv.Close() in
	// cleanup can never deadlock waiting on the handler.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-r.Context().Done():
		case <-time.After(2 * time.Second):
		}
	}))
	t.Cleanup(srv.Close)

	// Tiny client timeout so the request deadline fires quickly.
	an := NewOpenAIWithClient(testAPIKey, "gpt-test", srv.URL,
		&http.Client{Timeout: 50 * time.Millisecond})

	_, err := an.Analyze(context.Background(), testEntry())
	if err == nil {
		t.Fatal("expected timeout error")
	}
	if !errors.Is(err, domain.ErrProviderTimeout) {
		t.Fatalf("expected ErrProviderTimeout, got %v", err)
	}
}

func TestOpenAI_HTTPErrorStatuses(t *testing.T) {
	for _, status := range []int{http.StatusUnauthorized, http.StatusTooManyRequests, http.StatusInternalServerError} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			_, an := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(status)
				io.WriteString(w, `{"error":{"message":"nope","type":"x"}}`)
			})
			_, err := an.Analyze(context.Background(), testEntry())
			if !errors.Is(err, domain.ErrProviderUnavailable) {
				t.Fatalf("status %d: expected ErrProviderUnavailable, got %v", status, err)
			}
		})
	}
}

func TestOpenAI_MalformedJSON(t *testing.T) {
	_, an := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, `{not valid json`)
	})
	_, err := an.Analyze(context.Background(), testEntry())
	if !errors.Is(err, domain.ErrProviderUnavailable) {
		t.Fatalf("expected ErrProviderUnavailable, got %v", err)
	}
}

func TestOpenAI_MissingOutput(t *testing.T) {
	_, an := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, `{"status":"completed","output":[]}`)
	})
	_, err := an.Analyze(context.Background(), testEntry())
	if !errors.Is(err, domain.ErrProviderUnavailable) {
		t.Fatalf("expected ErrProviderUnavailable, got %v", err)
	}
}

func TestOpenAI_Refusal(t *testing.T) {
	_, an := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, `{"status":"completed","output":[{"type":"message","content":[{"type":"refusal","refusal":"I can't help with that."}]}]}`)
	})
	_, err := an.Analyze(context.Background(), testEntry())
	if !errors.Is(err, domain.ErrProviderUnavailable) {
		t.Fatalf("expected ErrProviderUnavailable, got %v", err)
	}
}

func TestOpenAI_IncompleteOutput(t *testing.T) {
	_, an := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, `{"status":"incomplete","incomplete_details":{"reason":"max_output_tokens"},"output":[]}`)
	})
	_, err := an.Analyze(context.Background(), testEntry())
	if !errors.Is(err, domain.ErrProviderUnavailable) {
		t.Fatalf("expected ErrProviderUnavailable, got %v", err)
	}
}

func TestOpenAI_InvalidConfidenceFailsValidation(t *testing.T) {
	_, an := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, okResponseBody(t, analysisPayload{
			Category: "grammar", Explanation: "ok", Confidence: 5, // out of range
		}))
	})
	_, err := an.Analyze(context.Background(), testEntry())
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("expected ErrValidation for bad confidence, got %v", err)
	}
}

func TestOpenAI_MissingRequiredFieldFailsValidation(t *testing.T) {
	_, an := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		// Empty category -> domain validation rejects.
		io.WriteString(w, okResponseBody(t, analysisPayload{
			Category: "", Explanation: "ok", Confidence: 0.5,
		}))
	})
	_, err := an.Analyze(context.Background(), testEntry())
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("expected ErrValidation for missing category, got %v", err)
	}
}

func TestOpenAI_OutOfTaxonomyCategoryFailsValidation(t *testing.T) {
	_, an := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		// A plausible-looking but non-taxonomy category must be rejected, so no
		// provider-specific category system can reach storage.
		io.WriteString(w, okResponseBody(t, analysisPayload{
			Category: "conjugation", Explanation: "ok", Confidence: 0.5,
		}))
	})
	_, err := an.Analyze(context.Background(), testEntry())
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("expected ErrValidation for out-of-taxonomy category, got %v", err)
	}
}

// TestOpenAI_ErrorsDoNotLeakAPIKey checks that no returned error string contains
// the API key, across a representative set of failure modes.
func TestOpenAI_ErrorsDoNotLeakAPIKey(t *testing.T) {
	cases := map[string]http.HandlerFunc{
		"401": func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusUnauthorized)
			io.WriteString(w, `{"error":{"message":"bad key `+testAPIKey+`"}}`)
		},
		"malformed": func(w http.ResponseWriter, r *http.Request) {
			io.WriteString(w, `{bad`)
		},
		"refusal": func(w http.ResponseWriter, r *http.Request) {
			io.WriteString(w, `{"status":"completed","output":[{"type":"message","content":[{"type":"refusal","refusal":"no"}]}]}`)
		},
	}
	for name, h := range cases {
		t.Run(name, func(t *testing.T) {
			_, an := newTestServer(t, h)
			_, err := an.Analyze(context.Background(), testEntry())
			if err == nil {
				t.Fatal("expected an error")
			}
			if strings.Contains(err.Error(), testAPIKey) {
				t.Fatalf("error leaked API key: %q", err.Error())
			}
		})
	}
}
