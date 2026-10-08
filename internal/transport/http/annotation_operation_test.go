package http_test

import (
	"bytes"
	"encoding/json"
	"french-learning-app/internal/domain"
	"io"
	"net/http"
	"testing"
)

func TestAnnotationOperationHTTP(t *testing.T) {
	srv, entry := setupConceptServer(t, []domain.ExtractedUnit{{Kind: domain.KindGrammar, Canonical: "operation", Statement: "s", Confidence: .9}})
	unit := extractUnits(t, srv, entry)[0]
	concept := mkConceptIT(t, srv, "other operation")
	key := "01234567-89AB-CDEF-0123-456789ABCDEF"
	path := "/knowledge-units/" + itoa(unit) + "/concept-distinctions"
	body := `{"concept_id":` + itoa(concept) + `}`
	send := func(path, body, key string) (int, string, http.Header) {
		t.Helper()
		req, _ := http.NewRequest("POST", srv.URL+path, bytes.NewBufferString(body))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Idempotency-Key", key)
		res, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer res.Body.Close()
		b, _ := io.ReadAll(res.Body)
		return res.StatusCode, string(b), res.Header
	}
	for _, invalid := range []string{body + ` {}`, `{"concept_id":0}`, `{"concept_id":` + itoa(concept) + `,"reason":"unsupported"}`} {
		status, _, _ := send(path, invalid, "11234567-89ab-cdef-0123-456789abcdef")
		if status != 400 {
			t.Fatalf("invalid status %d", status)
		}
		res, err := http.Get(srv.URL + "/annotation-operations/11234567-89ab-cdef-0123-456789abcdef")
		if err != nil {
			t.Fatal(err)
		}
		res.Body.Close()
		if res.StatusCode != 404 {
			t.Fatal("invalid request persisted receipt")
		}
	}
	status, original, _ := send(path, body, key)
	if status != 201 {
		t.Fatalf("first %d %s", status, original)
	}
	status, replay, headers := send(path, `{ "concept_id" : `+itoa(concept)+` }`, key)
	if status != 201 || original != replay || headers.Get("Idempotency-Replayed") != "true" {
		t.Fatalf("replay %d %s", status, replay)
	}
	status, _, _ = send("/knowledge-units/"+itoa(unit)+"/concept-links/relation", `{"concept_id":`+itoa(concept)+`,"relation":"related"}`, key)
	if status != 409 {
		t.Fatalf("action conflict %d", status)
	}
	for _, bad := range []string{"", "secret-value", key + ", " + key} {
		status, text, _ := send(path, body, bad)
		if status != 400 || bytes.Contains([]byte(text), []byte("secret-value")) {
			t.Fatalf("key status %d %s", status, text)
		}
	}
	res, err := http.Get(srv.URL + "/annotation-operations/01234567-89ab-cdef-0123-456789abcdef")
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	var receipt struct {
		State  string          `json:"state"`
		Result json.RawMessage `json:"result"`
	}
	json.NewDecoder(res.Body).Decode(&receipt)
	var result, expected any
	json.Unmarshal(receipt.Result, &result)
	json.Unmarshal([]byte(original), &expected)
	if res.StatusCode != 200 || receipt.State != "committed" {
		t.Fatal("missing receipt")
	}
	a, _ := json.Marshal(result)
	b, _ := json.Marshal(expected)
	if !bytes.Equal(a, b) {
		t.Fatal("receipt result changed")
	}
	res2, err := http.Get(srv.URL + "/annotation-operations/11234567-89ab-cdef-0123-456789abcdef")
	if err != nil {
		t.Fatal(err)
	}
	res2.Body.Close()
	if res2.StatusCode != 404 {
		t.Fatal("unknown receipt")
	}
}
