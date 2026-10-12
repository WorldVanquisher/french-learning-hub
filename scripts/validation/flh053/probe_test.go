package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/embedding"
)

func responseServer(t *testing.T, mode string) (*httptest.Server, *atomic.Int32) {
	t.Helper()
	calls := &atomic.Int32{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		call := calls.Add(1)
		if r.Method != "POST" || r.URL.Path != "/v1/embeddings" || r.Header.Get("Content-Type") != "application/json" || r.Header.Get("Authorization") != "" {
			t.Errorf("wire method/path/header drift")
		}
		var request struct {
			Model string   `json:"model"`
			Input []string `json:"input"`
		}
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Error("request decode failed")
			return
		}
		if request.Model != "flh053-synthetic-deployment" {
			t.Error("model selection changed")
		}
		switch mode {
		case "malformed":
			fmt.Fprint(w, `{bad`)
			return
		case "http_error":
			w.WriteHeader(503)
			fmt.Fprint(w, `SYNTHETIC_BODY_MUST_NOT_ESCAPE`)
			return
		case "provider_error_type":
			fmt.Fprint(w, `{"error":{"type":"SYNTHETIC_TYPE_ECHO"}}`)
			return
		case "slow":
			select {
			case <-r.Context().Done():
				return
			case <-time.After(time.Second):
			}
			return
		case "nonfinite":
			fmt.Fprint(w, `{"data":[{"index":0,"embedding":[1e400]}]}`)
			return
		case "nan":
			fmt.Fprint(w, `{"data":[{"index":0,"embedding":[NaN]}]}`)
			return
		case "redirect":
			w.Header().Set("Location", "/unexpected")
			w.WriteHeader(307)
			return
		}
		rows := []map[string]any{}
		for i := len(request.Input) - 1; i >= 0; i-- {
			vector := fakeVector(request.Input[i], 8)
			if mode == "wrong_dimensions" {
				vector = vector[:7]
			}
			if mode == "unequal_dimensions" && i == 1 {
				vector = vector[:7]
			}
			if mode == "empty_vector" {
				vector = []float64{}
			}
			if mode == "zero" {
				vector = make([]float64, 8)
			}
			if mode == "scaled" {
				for j := range vector {
					vector[j] *= 2
				}
			}
			if mode == "float32_overflow" {
				vector[0] = 1e40
			}
			if mode == "float32_underflow" {
				for j := range vector {
					vector[j] = 1e-50
				}
			}
			if mode == "inconsistent_repeat" && call > 1 {
				vector[0] += 0.02
			}
			row := map[string]any{"index": i, "embedding": vector}
			if mode == "missing_index" && i == 0 {
				delete(row, "index")
			}
			if mode == "null_index" && i == 0 {
				row["index"] = nil
			}
			if mode == "duplicate_index" {
				row["index"] = 0
			}
			if mode == "out_of_range" {
				row["index"] = 999
			}
			rows = append(rows, row)
		}
		if mode == "missing_vector" {
			rows = rows[:len(rows)-1]
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"data": rows})
	}))
	t.Cleanup(server.Close)
	return server, calls
}

func TestLoopbackContractAndAdditionalChecks(t *testing.T) {
	inputs, err := fixtures("plain")
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		mode, state, errorCategory string
		calls                      int
		providerReject             bool
	}{
		{"valid", "passed", "", 2, false},
		{"malformed", "failed", "provider_unavailable", 1, true},
		{"missing_vector", "failed", "provider_unavailable", 1, true},
		{"duplicate_index", "failed", "provider_unavailable", 1, true},
		{"out_of_range", "failed", "provider_unavailable", 1, true},
		{"unequal_dimensions", "failed", "provider_unavailable", 1, true},
		{"empty_vector", "failed", "provider_unavailable", 1, true},
		{"nan", "failed", "provider_unavailable", 1, true},
		{"nonfinite", "failed", "provider_unavailable", 1, true},
		{"http_error", "failed", "provider_unavailable", 1, true},
		{"provider_error_type", "failed", "provider_unavailable", 1, true},
		{"slow", "failed", "provider_timeout", 1, true},
		{"redirect", "failed", "provider_unavailable", 1, true},
		{"missing_index", "failed", "missing_explicit_index", 1, false},
		{"null_index", "failed", "missing_explicit_index", 1, false},
		{"wrong_dimensions", "failed", "dimensions_finite_nonzero_float32", 1, false},
		{"zero", "failed", "dimensions_finite_nonzero_float32", 1, false},
		{"float32_overflow", "failed", "dimensions_finite_nonzero_float32", 1, false},
		{"float32_underflow", "failed", "dimensions_finite_nonzero_float32", 1, false},
		{"scaled", "failed", "unit_norm", 1, false},
		{"inconsistent_repeat", "failed", "repeated_input_inconsistent", 2, false},
	} {
		t.Run(tc.mode, func(t *testing.T) {
			server, calls := responseServer(t, tc.mode)
			p, tape := newProvider(server.URL+"/v1///", "flh053-synthetic-deployment", 100*time.Millisecond, 5, 16, 2048)
			s := settings{Dimensions: 8, AbsTolerance: 1e-5, RelTolerance: 1e-4, RequireUnitNorm: tc.mode == "scaled", UnitNormTolerance: 1e-3}
			r := exercise(context.Background(), p, tape, inputs, s)
			if r.State != tc.state || int(calls.Load()) != tc.calls {
				t.Fatalf("state/calls = %s/%d", r.State, calls.Load())
			}
			last := r.Batches[len(r.Batches)-1]
			if last.Error != tc.errorCategory {
				t.Fatalf("error category = %s", last.Error)
			}
			if tc.providerReject != (last.State == "provider_rejected") {
				t.Fatal("provider/probe rejection conflated")
			}
			encoded, _ := json.Marshal(r)
			if strings.Contains(string(encoded), "SYNTHETIC_BODY_MUST_NOT_ESCAPE") || strings.Contains(string(encoded), "SYNTHETIC_TYPE_ECHO") {
				t.Fatal("probe emitted provider detail")
			}
			if tc.mode == "valid" {
				for i, v := range r.Batches[0].Vectors {
					if !reflect.DeepEqual(v, fakeVector(inputs[0].Inputs[i], 8)) {
						t.Fatal("provider did not restore input order")
					}
				}
			}
		})
	}
}

func TestProviderErrorBlindSpotsDocumented(t *testing.T) {
	server, calls := responseServer(t, "provider_error_type")
	p := embedding.NewHTTPProvider("", "flh053-synthetic-deployment", server.URL+"/v1", time.Second)
	_, err := p.Embed(context.Background(), []string{english})
	if !errors.Is(err, application.ErrEmbeddingProviderUnavailable) || !strings.Contains(err.Error(), "SYNTHETIC_TYPE_ECHO") || calls.Load() != 1 {
		t.Fatal("provider error.type echo observation changed")
	}
	t.Log("HTTPProvider echoes error.type; probe reports category only")
}

func TestRenderedPathsAndRoleAmbiguity(t *testing.T) {
	batches, err := fixtures("rendered")
	if err != nil {
		t.Fatal(err)
	}
	var query, document map[string]any
	if json.Unmarshal([]byte(batches[0].Inputs[0]), &query) != nil || json.Unmarshal([]byte(batches[0].Inputs[1]), &document) != nil {
		t.Fatal("typed production rendering missing")
	}
	if query["type"] != "query" || document["type"] != "concept" || query["representation"] != "concept_embedding_text_v1" || document["representation"] != "concept_embedding_text_v1" {
		t.Fatal("role/version drift")
	}
	if batches[1].Inputs[1] != batches[0].Inputs[1] || batches[2].Inputs[0] != searchInput(english) || batches[3].Inputs[0] != searchInput(french) {
		t.Fatal("index/search text mismatch")
	}
	// Use a real rendered document small enough to pass the actual 200-byte
	// free-text request boundary, rather than assuming arbitrary long JSON fits.
	minimal, err := application.BuildSemanticIndexDocument(domain.KnowledgeConcept{ID: 99, Target: "pain", PedagogicalIntent: "vocabulary", IdentityFeatures: map[string]string{}})
	if err != nil {
		t.Fatal(err)
	}
	parsed, err := application.ParseLibrarySearchQuery(minimal.Text, "", nil)
	if err != nil || parsed.Text != minimal.Text {
		t.Fatalf("raw query ambiguity witness rejected: %v", err)
	}
	wrapped := searchInput(minimal.Text)
	var envelope map[string]any
	if json.Unmarshal([]byte(wrapped), &envelope) != nil || envelope["representation"] != "concept_search_query_v2" || envelope["type"] != "query" || envelope["text"] != minimal.Text {
		t.Fatal("search role envelope does not preserve user text")
	}
	negative, err := fixtures("raw-negative")
	if err != nil || negative[0].Inputs[0] != english {
		t.Fatal("raw negative case lost")
	}
	t.Log("typed mixed/document/search-v2 roles are explicit; raw-text rejection remains a separate negative fixture")
}

func TestCapsTimeoutAndOptIn(t *testing.T) {
	server, calls := responseServer(t, "valid")
	p, _ := newProvider(server.URL+"/v1", "flh053-synthetic-deployment", time.Second, 1, 3, 2048)
	if _, err := p.Embed(context.Background(), []string{english, french, english}); err != nil {
		t.Fatal(err)
	}
	if _, err := p.Embed(context.Background(), []string{english}); err == nil || calls.Load() != 1 {
		t.Fatal("runtime cap bypassed")
	}
	for _, args := range [][]string{
		{"-base-url", server.URL}, {"-model", "do-not-call"}, {"-max-inputs", "1"}, {"-max-requests", "1"}, {"-max-input-bytes", "1"}, {"-timeout", "0"}, {"-atol", "NaN"},
		{"-allow-real-endpoint", "-base-url", server.URL, "-model", "synthetic"},
		{"-allow-real-endpoint", "-base-url", "http://8.8.8.8/v1", "-model", "synthetic", "-dimensions", "8", "-max-requests", "2", "-max-inputs", "6"},
	} {
		var stdout, stderr bytes.Buffer
		if code := run(args, &stdout, &stderr); code != 2 {
			t.Fatalf("invalid configuration exit %d", code)
		}
	}
	if calls.Load() != 1 {
		t.Fatal("configuration refusal made network call")
	}
	for _, base := range []string{"http://name.example/v1", "http://user:pass@127.0.0.1/v1", "http://127.0.0.1/v1?x=y", "http://127.0.0.1/v1#fragment"} {
		if validateURL(base) == nil {
			t.Fatal("unsafe/unresolved base allowed")
		}
	}
	if validateURL("http://192.168.1.50:8765/v1") != nil {
		t.Fatal("private endpoint refused")
	}
	var m settings = settings{Dimensions: 2, AbsTolerance: 1e-5, RelTolerance: 1e-4}
	if !closeVector([]float64{1, 0}, []float64{1.00005, 0}, m) || closeVector([]float64{1, 0}, []float64{1.02, 0}, m) {
		t.Fatal("declared coordinate tolerance not enforced")
	}
	path := filepath.Join(t.TempDir(), "existing")
	if writeNew(path, []byte("keep")) != nil || writeNew(path, []byte("replace")) == nil {
		t.Fatal("overwrite allowed")
	}
	owned, err := os.MkdirTemp("", "flh053-output-selftest-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(owned)
	link := filepath.Join(owned, "alias")
	if err := os.Symlink(t.TempDir(), link); err != nil {
		t.Fatal(err)
	}
	if _, err := outputDir(filepath.Join(link, "new-output")); err == nil {
		t.Fatal("symlink output accepted")
	}
	if _, err := os.Stat(filepath.Join(link, "new-output")); !os.IsNotExist(err) {
		t.Fatal("symlink rejection still created output")
	}
	var stdout, stderr bytes.Buffer
	code := run([]string{"-allow-real-endpoint", "-base-url", server.URL + "/v1/", "-model", "flh053-synthetic-deployment", "-dimensions", "8", "-max-requests", "2", "-max-inputs", "6", "-out", filepath.Join(owned, "explicit-loopback")}, &stdout, &stderr)
	if code != 0 || calls.Load() != 3 {
		t.Fatalf("explicit endpoint CLI exit/calls = %d/%d", code, calls.Load())
	}
}

func TestTailscaleRangeRequiresExplicitOptIn(t *testing.T) {
	for _, host := range []string{"100.64.0.0", "100.118.109.6", "100.127.255.255"} {
		base := "http://" + host + ":8765/v1"
		if validateEndpoint(base, false) == nil || validateEndpoint(base, true) != nil {
			t.Fatalf("CGNAT opt-in mismatch for %s", host)
		}
	}
	for _, host := range []string{"100.63.255.255", "100.128.0.0", "8.8.8.8", "1.1.1.1"} {
		if validateEndpoint("http://"+host+"/v1", true) == nil {
			t.Fatalf("public/outside range admitted: %s", host)
		}
	}
	for _, base := range []string{"http://name.example/v1", "http://user:pass@100.118.109.6/v1", "http://100.118.109.6/v1?x=y", "http://100.118.109.6/v1#fragment"} {
		if validateEndpoint(base, true) == nil {
			t.Fatal("unsafe URL admitted")
		}
	}
}

func TestIntegratedSearchGoldenParity(t *testing.T) {
	raw, err := os.ReadFile("../../../tools/embedding/e5/tests/golden_inputs.json")
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Accepted []struct {
			GoQueryText string `json:"go_query_text"`
			Input       string `json:"input"`
		} `json:"accepted"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	count := 0
	for _, item := range golden.Accepted {
		if item.GoQueryText == "" {
			continue
		}
		count++
		actual, err := application.ConceptSearchQueryEmbeddingText(item.GoQueryText)
		if err != nil || actual != item.Input || searchInput(item.GoQueryText) != actual {
			t.Fatalf("production/probe/golden search drift: %v", err)
		}
	}
	if count != 3 {
		t.Fatalf("search cases: %d", count)
	}
}
