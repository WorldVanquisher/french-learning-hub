package embedding

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/application"
)

const embeddingTestAPIKey = "embedding-test-secret"

func newEmbeddingTestProvider(t *testing.T, handler http.HandlerFunc) (*httptest.Server, *HTTPProvider) {
	t.Helper()
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	return server, NewHTTPProviderWithClient(embeddingTestAPIKey, "multilingual-test", server.URL, server.Client())
}

func writeEmbeddingResponse(t *testing.T, w http.ResponseWriter, items []embeddingResponseItem) {
	t.Helper()
	if err := json.NewEncoder(w).Encode(embeddingResponse{Data: items}); err != nil {
		t.Fatalf("encode response: %v", err)
	}
}

func TestHTTPProvider_BatchRequestAndOrderedResponse(t *testing.T) {
	var gotMethod, gotPath, gotAuth, gotContentType string
	var gotRequest embeddingRequest
	_, provider := newEmbeddingTestProvider(t, func(w http.ResponseWriter, r *http.Request) {
		gotMethod, gotPath = r.Method, r.URL.Path
		gotAuth, gotContentType = r.Header.Get("Authorization"), r.Header.Get("Content-Type")
		if err := json.NewDecoder(r.Body).Decode(&gotRequest); err != nil {
			t.Fatalf("decode request: %v", err)
		}
		writeEmbeddingResponse(t, w, []embeddingResponseItem{
			{Index: 1, Embedding: []float64{0, 1}},
			{Index: 0, Embedding: []float64{1, 0}},
		})
	})

	vectors, err := provider.Embed(context.Background(), []string{"query", "document"})
	if err != nil {
		t.Fatalf("Embed: %v", err)
	}
	if gotMethod != http.MethodPost || gotPath != "/embeddings" || gotContentType != "application/json" || gotAuth != "Bearer "+embeddingTestAPIKey {
		t.Fatalf("request method/path/content/auth = %q %q %q %q", gotMethod, gotPath, gotContentType, gotAuth)
	}
	if gotRequest.Model != "multilingual-test" || !reflect.DeepEqual(gotRequest.Input, []string{"query", "document"}) {
		t.Fatalf("request = %+v", gotRequest)
	}
	if !reflect.DeepEqual(vectors, [][]float64{{1, 0}, {0, 1}}) {
		t.Fatalf("vectors = %#v", vectors)
	}
	if provider.Name() != "http:multilingual-test" {
		t.Fatalf("Name = %q", provider.Name())
	}
}

func TestHTTPProvider_OptionalAuthorizationAndEmptyBatch(t *testing.T) {
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if got := r.Header.Get("Authorization"); got != "" {
			t.Fatalf("authorization = %q", got)
		}
		writeEmbeddingResponse(t, w, []embeddingResponseItem{{Index: 0, Embedding: []float64{1}}})
	}))
	t.Cleanup(server.Close)
	provider := NewHTTPProviderWithClient("", "local-model", server.URL, server.Client())
	if vectors, err := provider.Embed(context.Background(), nil); err != nil || vectors == nil || len(vectors) != 0 || calls != 0 {
		t.Fatalf("empty vectors = %#v, calls = %d, err = %v", vectors, calls, err)
	}
	if _, err := provider.Embed(context.Background(), []string{"text"}); err != nil || calls != 1 {
		t.Fatalf("Embed calls = %d, err = %v", calls, err)
	}
}

func TestHTTPProvider_RejectsMalformedAndInvalidResponses(t *testing.T) {
	for _, tc := range []struct {
		name    string
		handler http.HandlerFunc
	}{
		{name: "non-2xx", handler: func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusUnauthorized)
			io.WriteString(w, `{"error":"secret body"}`)
		}},
		{name: "malformed JSON", handler: func(w http.ResponseWriter, r *http.Request) { io.WriteString(w, `{bad`) }},
		{name: "provider error", handler: func(w http.ResponseWriter, r *http.Request) { io.WriteString(w, `{"error":{"type":"upstream"}}`) }},
		{name: "wrong count", handler: func(w http.ResponseWriter, r *http.Request) {
			writeEmbeddingResponse(t, w, []embeddingResponseItem{{Index: 0, Embedding: []float64{1, 0}}})
		}},
		{name: "duplicate index", handler: func(w http.ResponseWriter, r *http.Request) {
			writeEmbeddingResponse(t, w, []embeddingResponseItem{{Index: 0, Embedding: []float64{1}}, {Index: 0, Embedding: []float64{1}}})
		}},
		{name: "out-of-range index", handler: func(w http.ResponseWriter, r *http.Request) {
			writeEmbeddingResponse(t, w, []embeddingResponseItem{{Index: 0, Embedding: []float64{1}}, {Index: 3, Embedding: []float64{1}}})
		}},
		{name: "empty vector", handler: func(w http.ResponseWriter, r *http.Request) {
			writeEmbeddingResponse(t, w, []embeddingResponseItem{{Index: 0, Embedding: []float64{1}}, {Index: 1, Embedding: []float64{}}})
		}},
		{name: "inconsistent dimensions", handler: func(w http.ResponseWriter, r *http.Request) {
			writeEmbeddingResponse(t, w, []embeddingResponseItem{{Index: 0, Embedding: []float64{1}}, {Index: 1, Embedding: []float64{1, 0}}})
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, provider := newEmbeddingTestProvider(t, tc.handler)
			_, err := provider.Embed(context.Background(), []string{"query", "document"})
			if !errors.Is(err, application.ErrEmbeddingProviderUnavailable) {
				t.Fatalf("error = %v", err)
			}
			if strings.Contains(err.Error(), embeddingTestAPIKey) || strings.Contains(err.Error(), "secret body") {
				t.Fatalf("error leaked secret provider detail: %q", err.Error())
			}
		})
	}
}

func TestHTTPProvider_TimeoutAndCancellation(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-r.Context().Done():
		case <-time.After(2 * time.Second):
		}
	}))
	t.Cleanup(server.Close)

	timeoutProvider := NewHTTPProviderWithClient("", "model", server.URL, &http.Client{Timeout: 30 * time.Millisecond})
	if _, err := timeoutProvider.Embed(context.Background(), []string{"text"}); !errors.Is(err, application.ErrEmbeddingProviderTimeout) {
		t.Fatalf("timeout error = %v", err)
	}

	bodyServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, `{"data":[`)
		w.(http.Flusher).Flush()
		<-r.Context().Done()
	}))
	t.Cleanup(bodyServer.Close)
	bodyTimeoutProvider := NewHTTPProviderWithClient("", "model", bodyServer.URL, &http.Client{Timeout: 30 * time.Millisecond})
	if _, err := bodyTimeoutProvider.Embed(context.Background(), []string{"text"}); !errors.Is(err, application.ErrEmbeddingProviderTimeout) {
		t.Fatalf("response-body timeout error = %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	canceledProvider := NewHTTPProviderWithClient("", "model", server.URL, server.Client())
	if _, err := canceledProvider.Embed(ctx, []string{"text"}); !errors.Is(err, application.ErrEmbeddingProviderUnavailable) {
		t.Fatalf("cancellation error = %v", err)
	}
}
