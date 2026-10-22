package http_test

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
	"french-learning-app/internal/suggester"
	transporthttp "french-learning-app/internal/transport/http"
)

// FLH-097 end-to-end tests: real SQLite, real services, the real OpenAI
// suggester client pointed at a local fake provider. No paid call is made.

const suggestionTestKey = "sk-flh097-secret-test-key"

// fakeSuggestProvider is a programmable Responses API stand-in.
type fakeSuggestProvider struct {
	mu      sync.Mutex
	calls   int
	bodies  []string
	respond func(units []fakeSuggestUnit) (int, string)
	delay   time.Duration
}

type fakeSuggestUnit struct {
	UnitID     int64 `json:"unit_id"`
	Candidates []struct {
		ConceptID int64 `json:"concept_id"`
	} `json:"candidates"`
}

func (f *fakeSuggestProvider) handler(w http.ResponseWriter, r *http.Request) {
	raw, _ := io.ReadAll(r.Body)
	f.mu.Lock()
	f.calls++
	f.bodies = append(f.bodies, string(raw))
	respond, delay := f.respond, f.delay
	f.mu.Unlock()
	if delay > 0 {
		time.Sleep(delay)
	}
	var req struct {
		Input []struct {
			Content []struct {
				Text string `json:"text"`
			} `json:"content"`
		} `json:"input"`
	}
	_ = json.Unmarshal(raw, &req)
	var payload struct {
		Units []fakeSuggestUnit `json:"units"`
	}
	_ = json.Unmarshal([]byte(req.Input[1].Content[0].Text), &payload)
	status, body := respond(payload.Units)
	w.WriteHeader(status)
	io.WriteString(w, body)
}

func (f *fakeSuggestProvider) callCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.calls
}

// envelope wraps structured output text in a Responses API body.
func envelope(text string) string {
	out, _ := json.Marshal(map[string]any{"status": "completed", "output": []any{map[string]any{
		"type": "message", "content": []any{map[string]any{"type": "output_text", "text": text}}}}})
	return string(out)
}

// answerFirstCandidate suggests each unit's first candidate.
func answerFirstCandidate(units []fakeSuggestUnit) (int, string) {
	var items []map[string]any
	for _, u := range units {
		items = append(items, map[string]any{"unit_id": u.UnitID, "outcome": "suggested",
			"concept_id": u.Candidates[0].ConceptID, "reason": "Both teach « parler » + language without an article."})
	}
	b, _ := json.Marshal(map[string]any{"suggestions": items})
	return 200, envelope(string(b))
}

type suggestionFixture struct {
	srv      *httptest.Server
	db       *sql.DB
	dbPath   string
	provider *fakeSuggestProvider
	entryID  int64
	units    []int64 // parler (exact C1), vouloir (bm25 C2), zzz (no candidate)
	c1, c2   int64   // parler concept, vouloir concept
	c3       int64   // parler couramment concept (bm25 for parler)
}

var suggestionUnits = []domain.ExtractedUnit{
	{Kind: domain.KnowledgeKind("grammar"), Canonical: "parler langue sans article", Statement: "After « parler », a language takes no article.", Confidence: 0.9},
	{Kind: domain.KnowledgeKind("grammar"), Canonical: "vouloir présent", Statement: "« vouloir » in the present tense.", Confidence: 0.9},
	{Kind: domain.KnowledgeKind("vocabulary"), Canonical: "xylophone", Statement: "« xylophone » is masculine.", Confidence: 0.9},
}

// buildSuggestionServer wires the full stack over dbPath. sug may be nil
// (SUGGESTION_PROVIDER=disabled).
func buildSuggestionServer(t *testing.T, dbPath string, sug domain.ConceptSuggester) (*httptest.Server, *sql.DB, *sqlite.EntryRepository, *sqlite.AnalysisRepository) {
	t.Helper()
	db, err := sqlite.Open(dbPath)
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	entryRepo := sqlite.NewEntryRepository(db)
	analysisRepo := sqlite.NewAnalysisRepository(db)
	feedbackRepo := sqlite.NewFeedbackRepository(db)
	knowledgeRepo := sqlite.NewKnowledgeRepository(db)
	admissionRepo := sqlite.NewAdmissionRepository(db)
	conceptRepo := sqlite.NewConceptRepository(db)
	conceptSvc := application.NewConceptService(knowledgeRepo, conceptRepo, conceptRepo)
	effectiveAnnotationSvc := application.NewEffectiveAnnotationService(conceptRepo, conceptRepo)
	datasetSvc := application.NewConceptAnnotationDatasetService(effectiveAnnotationSvc, knowledgeRepo, conceptRepo)
	qualitySvc := application.NewConceptAnnotationDatasetQualityService(datasetSvc)
	evaluationSvc := application.NewConceptRetrievalEvaluationServiceWithRegistry(datasetSvc, qualitySvc, conceptSvc,
		application.NewConceptRetrieverRegistry(application.NewExactSignatureConceptRetriever(),
			application.NewWeightedLexicalConceptRetriever(), application.NewBM25ConceptRetriever()))
	comparisonSvc := application.NewConceptRetrievalComparisonService(evaluationSvc)
	handler := transporthttp.NewHandler(
		application.NewEntryService(entryRepo), application.NewAnalysisService(entryRepo, analysisRepo, nil),
		application.NewFeedbackService(feedbackRepo), application.NewEffectiveAnalysisService(analysisRepo, feedbackRepo),
		application.NewInventoryService(sqlite.NewInventoryRepository(db)), application.NewCaptureService(sqlite.NewCaptureRepository(db)),
		application.NewKnowledgeService(entryRepo, analysisRepo, feedbackRepo, knowledgeRepo, admissionRepo, &stubExtractor{units: suggestionUnits}),
		conceptSvc, effectiveAnnotationSvc, datasetSvc,
		transporthttp.WithAnnotationDatasetQuality(qualitySvc),
		transporthttp.WithRetrievalEvaluation(evaluationSvc),
		transporthttp.WithRetrievalComparison(comparisonSvc),
		transporthttp.WithConceptSuggestions(application.NewConceptSuggestionService(sqlite.NewConceptSuggestionRepository(db), sug)),
	)
	srv := httptest.NewServer(handler.Routes())
	t.Cleanup(srv.Close)
	return srv, db, entryRepo, analysisRepo
}

func newSuggestionFixture(t *testing.T, timeout time.Duration) *suggestionFixture {
	t.Helper()
	f := &suggestionFixture{provider: &fakeSuggestProvider{respond: answerFirstCandidate}}
	provider := httptest.NewServer(http.HandlerFunc(f.provider.handler))
	t.Cleanup(provider.Close)
	f.dbPath = filepath.Join(t.TempDir(), "flh097.db")
	sug := suggester.NewOpenAI(suggestionTestKey, "fake-model", provider.URL, timeout)
	var entries *sqlite.EntryRepository
	var analyses *sqlite.AnalysisRepository
	f.srv, f.db, entries, analyses = buildSuggestionServer(t, f.dbPath, sug)
	ctx := context.Background()
	entry, err := entries.Create(ctx, domain.NewEntryInput{OriginalInput: "Je parle japonais et je veux apprendre."})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := analyses.Create(ctx, entry.ID, domain.AnalysisResult{Category: "grammar", Explanation: "parler + language", Confidence: 0.9}, "rule-based:test"); err != nil {
		t.Fatal(err)
	}
	f.entryID = entry.ID
	f.units = extractUnits(t, f.srv, entry.ID)
	f.c1 = f.createConcept(t, "parler langue sans article", "grammar")
	f.c2 = f.createConcept(t, "vouloir au présent", "grammar")
	f.c3 = f.createConcept(t, "parler couramment", "usage")
	return f
}

func (f *suggestionFixture) createConcept(t *testing.T, target, intent string) int64 {
	t.Helper()
	status, body := doJSON(t, http.MethodPost, f.srv.URL+"/concepts",
		fmt.Sprintf(`{"identity":{"target":%q,"pedagogical_intent":%q,"scope":"","identity_features":{}}}`, target, intent))
	if status != http.StatusCreated {
		t.Fatalf("create concept %d %v", status, body)
	}
	c, ok := body["concept"].(map[string]any)
	if !ok {
		c = body
	}
	return int64(c["id"].(float64))
}

func (f *suggestionFixture) generate(t *testing.T, key string, unitIDs ...int64) (int, http.Header, map[string]any) {
	t.Helper()
	ids, _ := json.Marshal(unitIDs)
	req, _ := http.NewRequest(http.MethodPost, f.srv.URL+"/concept-suggestion-runs", bytes.NewReader([]byte(`{"unit_ids":`+string(ids)+`}`)))
	req.Header.Set("Content-Type", "application/json")
	if key != "" {
		req.Header.Set("Idempotency-Key", key)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out map[string]any
	_ = json.NewDecoder(resp.Body).Decode(&out)
	return resp.StatusCode, resp.Header, out
}

func (f *suggestionFixture) confirm(t *testing.T, itemID, conceptID int64) (int, http.Header, map[string]any) {
	t.Helper()
	req, _ := http.NewRequest(http.MethodPost, f.srv.URL+"/concept-suggestion-items/"+itoa(itemID)+"/confirm",
		strings.NewReader(fmt.Sprintf(`{"concept_id":%d}`, conceptID)))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out map[string]any
	_ = json.NewDecoder(resp.Body).Decode(&out)
	return resp.StatusCode, resp.Header, out
}

// semanticCounts are every authority table a suggestion must never write.
func (f *suggestionFixture) semanticCounts(t *testing.T) string {
	t.Helper()
	var parts []string
	for _, q := range []string{
		`SELECT COUNT(*) FROM unit_concept_memberships`, `SELECT COUNT(*) FROM unit_concept_links`,
		`SELECT COUNT(*) FROM knowledge_concepts`, `SELECT COUNT(*) FROM unit_resolution_judgments`,
		`SELECT COUNT(*) FROM unit_concept_distinctions`, `SELECT COUNT(*) FROM knowledge_admission_overrides`,
		`SELECT COUNT(*) FROM knowledge_concepts WHERE preferred_unit_id IS NOT NULL`,
		`SELECT COUNT(*) FROM annotation_operations`,
	} {
		var n int
		if err := f.db.QueryRow(q).Scan(&n); err != nil {
			t.Fatal(err)
		}
		parts = append(parts, fmt.Sprint(n))
	}
	return strings.Join(parts, ",")
}

func items(run map[string]any) []map[string]any {
	raw, _ := run["items"].([]any)
	out := make([]map[string]any, 0, len(raw))
	for _, r := range raw {
		out = append(out, r.(map[string]any))
	}
	return out
}

func num(v any) int64 { return int64(v.(float64)) }

const keyA = "6f1c7a0e-2b4d-4c8e-9a1b-0d2e3f4a5b6c"
const keyB = "7a2d8b1f-3c5e-4d9f-8b2c-1e3f4a5b6c7d"

func TestConceptSuggestions_GenerateIsAdvisoryReplayableAndReopenable(t *testing.T) {
	f := newSuggestionFixture(t, 2*time.Second)
	before := f.semanticCounts(t)

	status, hdr, run := f.generate(t, keyA, f.units...)
	if status != http.StatusCreated || run["status"] != "completed" || hdr.Get("Idempotency-Replayed") != "" {
		t.Fatalf("generate %d %v", status, run)
	}
	if f.provider.callCount() != 1 || run["provider_called"] != true || run["candidate_policy"] != domain.ConceptSuggestionCandidatePolicy ||
		run["generator"] != "openai:fake-model:concept_suggestion_v1" {
		t.Fatalf("run provenance %v (calls %d)", run, f.provider.callCount())
	}
	its := items(run)
	if len(its) != 3 {
		t.Fatalf("items %v", its)
	}
	parler, vouloir, xylo := its[0], its[1], its[2]
	cands := parler["candidates"].([]any)
	first := cands[0].(map[string]any)
	if num(first["concept_id"]) != f.c1 || first["source"] != "exact_signature" || len(cands) > domain.SuggestionCandidatesPerUnit {
		t.Fatalf("parler candidates %v", cands)
	}
	if parler["outcome"] != "suggested" || num(parler["suggested_concept_id"]) != f.c1 || parler["state"] != "open" ||
		parler["unit"].(map[string]any)["canonical"] != "parler langue sans article" {
		t.Fatalf("parler item %v", parler)
	}
	if vouloir["outcome"] != "suggested" || num(vouloir["suggested_concept_id"]) != f.c2 {
		t.Fatalf("vouloir item %v", vouloir)
	}
	// No candidate: decided locally, never sent to the provider.
	if xylo["outcome"] != "no_candidates" || xylo["suggested_concept_id"] != nil || xylo["state"] != "no_suggestion" ||
		len(xylo["candidates"].([]any)) != 0 {
		t.Fatalf("xylophone item %v", xylo)
	}
	sent := f.provider.bodies[0]
	if strings.Contains(sent, "xylophone") || !strings.Contains(sent, `"store":false`) || !strings.Contains(sent, `"strict":true`) {
		t.Fatalf("provider request shape: %s", sent)
	}
	// Generation changed no authority.
	if after := f.semanticCounts(t); after != before {
		t.Fatalf("semantic tables changed by generation: %s -> %s", before, after)
	}

	// Same key + same units: replay, no second provider call.
	status, hdr, replay := f.generate(t, keyA, f.units...)
	if status != http.StatusCreated || hdr.Get("Idempotency-Replayed") != "true" || replay["id"] != run["id"] || f.provider.callCount() != 1 {
		t.Fatalf("replay %d %v (calls %d)", status, replay, f.provider.callCount())
	}
	// Same key, different units: conflict.
	if status, _, body := f.generate(t, keyA, f.units[0]); status != http.StatusConflict {
		t.Fatalf("key reuse %d %v", status, body)
	}
	// Lookup by key, and the list.
	if s, byKey := doJSON(t, http.MethodGet, f.srv.URL+"/concept-suggestion-runs/operations/"+keyA, ""); s != 200 || byKey["id"] != run["id"] {
		t.Fatalf("by key %d %v", s, byKey)
	}
	if s, _ := doJSON(t, http.MethodGet, f.srv.URL+"/concept-suggestion-runs/operations/"+keyB, ""); s != http.StatusNotFound {
		t.Fatalf("unknown key %d", s)
	}
	_, list := doJSON(t, http.MethodGet, f.srv.URL+"/concept-suggestion-runs", "")
	if list["enabled"] != true || len(list["runs"].([]any)) != 1 || path(list, "limits", "max_units") != float64(domain.MaxSuggestionUnits) {
		t.Fatalf("list %v", list)
	}

	// Reopen the database with the suggester disabled: the run is still
	// inspectable, and a replay under its key still answers without a provider.
	f.srv.Close()
	f.db.Close()
	srv2, _, _, _ := buildSuggestionServer(t, f.dbPath, nil)
	s, reopened := doJSON(t, http.MethodGet, srv2.URL+"/concept-suggestion-runs/"+itoa(num(run["id"])), "")
	if s != 200 || len(items(reopened)) != 3 || items(reopened)[0]["reason"] == "" {
		t.Fatalf("reopened %d %v", s, reopened)
	}
	f.srv = srv2
	if status, hdr, _ := f.generate(t, keyA, f.units...); status != http.StatusCreated || hdr.Get("Idempotency-Replayed") != "true" {
		t.Fatalf("replay while disabled %d", status)
	}
	if status, _, _ := f.generate(t, keyB, f.units[0]); status != http.StatusServiceUnavailable {
		t.Fatalf("new request while disabled %d", status)
	}
	_, list = doJSON(t, http.MethodGet, srv2.URL+"/concept-suggestion-runs", "")
	if list["enabled"] != false || list["generator"] != nil {
		t.Fatalf("disabled list %v", list)
	}
}

func TestConceptSuggestions_RequestValidation(t *testing.T) {
	f := newSuggestionFixture(t, 2*time.Second)
	if status, _, _ := f.generate(t, "", f.units[0]); status != http.StatusBadRequest {
		t.Fatalf("missing key %d", status)
	}
	if status, _, _ := f.generate(t, "not-a-uuid", f.units[0]); status != http.StatusBadRequest {
		t.Fatalf("invalid key %d", status)
	}
	eleven := make([]int64, domain.MaxSuggestionUnits+1)
	for i := range eleven {
		eleven[i] = int64(1000 + i)
	}
	cases := map[string][]int64{
		"empty":        {},
		"too many":     eleven,
		"duplicate":    {f.units[0], f.units[0]},
		"missing unit": {999999},
		"non-positive": {0},
	}
	for name, ids := range cases {
		if status, _, body := f.generate(t, keyB, ids...); status != http.StatusUnprocessableEntity {
			t.Fatalf("%s: %d %v", name, status, body)
		}
	}
	// A resolved unit is not reviewable: refused, never silently dropped.
	if s, b := doJSON(t, http.MethodPost, f.srv.URL+"/knowledge-units/"+itoa(f.units[0])+"/concept-links/same",
		fmt.Sprintf(`{"concept_id":%d}`, f.c3)); s != http.StatusCreated && s != http.StatusOK {
		t.Fatalf("manual SAME %d %v", s, b)
	}
	if status, _, body := f.generate(t, keyB, f.units[0], f.units[1]); status != http.StatusUnprocessableEntity ||
		!strings.Contains(fmt.Sprint(body["error"]), itoa(f.units[0])) {
		t.Fatalf("resolved unit %d %v", status, body)
	}
	if f.provider.callCount() != 0 {
		t.Fatalf("provider called %d times by refused requests", f.provider.callCount())
	}
	var n int
	f.db.QueryRow(`SELECT COUNT(*) FROM concept_suggestion_runs`).Scan(&n)
	if n != 0 {
		t.Fatalf("refused requests stored %d runs", n)
	}
}

func TestConceptSuggestions_OversizedTextIsRejected(t *testing.T) {
	f := newSuggestionFixture(t, 2*time.Second)
	long := strings.Repeat("parler ", 300)
	if _, err := f.db.Exec(`UPDATE knowledge_units SET statement = ? WHERE id = ?`, long, f.units[0]); err != nil {
		t.Fatal(err)
	}
	if status, _, body := f.generate(t, keyA, f.units[0], f.units[1]); status != http.StatusUnprocessableEntity ||
		!strings.Contains(fmt.Sprint(body["error"]), "characters") {
		t.Fatalf("oversized unit %d %v", status, body)
	}
	if f.provider.callCount() != 0 {
		t.Fatal("provider called for oversized input")
	}
}

func TestConceptSuggestions_ProviderAndOutputFailuresStoreFailedRunOnly(t *testing.T) {
	type answer func(units []fakeSuggestUnit) (int, string)
	reply := func(build func(units []fakeSuggestUnit) []map[string]any) answer {
		return func(units []fakeSuggestUnit) (int, string) {
			b, _ := json.Marshal(map[string]any{"suggestions": build(units)})
			return 200, envelope(string(b))
		}
	}
	one := func(u fakeSuggestUnit, outcome string, concept any) map[string]any {
		return map[string]any{"unit_id": u.UnitID, "outcome": outcome, "concept_id": concept, "reason": "r"}
	}
	cases := []struct {
		name, code string
		status     int
		respond    answer
	}{
		{"http 500", "provider_unavailable", 502, func([]fakeSuggestUnit) (int, string) { return 500, `{"error":"` + suggestionTestKey + `"}` }},
		{"malformed text", "invalid_output", 502, func([]fakeSuggestUnit) (int, string) { return 200, envelope("{not json") }},
		{"missing unit", "invalid_output", 502, reply(func(u []fakeSuggestUnit) []map[string]any {
			return []map[string]any{one(u[0], "uncertain", nil)}
		})},
		{"foreign unit", "invalid_output", 502, reply(func(u []fakeSuggestUnit) []map[string]any {
			return []map[string]any{one(u[0], "uncertain", nil), one(u[1], "uncertain", nil), {"unit_id": 424242, "outcome": "uncertain", "concept_id": nil, "reason": "r"}}
		})},
		{"duplicate unit", "invalid_output", 502, reply(func(u []fakeSuggestUnit) []map[string]any {
			return []map[string]any{one(u[0], "uncertain", nil), one(u[0], "uncertain", nil)}
		})},
		{"foreign concept", "invalid_output", 502, reply(func(u []fakeSuggestUnit) []map[string]any {
			return []map[string]any{one(u[0], "suggested", 987654), one(u[1], "uncertain", nil)}
		})},
		{"concept on uncertain", "invalid_output", 502, reply(func(u []fakeSuggestUnit) []map[string]any {
			return []map[string]any{one(u[0], "uncertain", u[0].Candidates[0].ConceptID), one(u[1], "uncertain", nil)}
		})},
		{"empty reason", "invalid_output", 502, reply(func(u []fakeSuggestUnit) []map[string]any {
			a, b := one(u[0], "uncertain", nil), one(u[1], "uncertain", nil)
			a["reason"] = "  "
			return []map[string]any{a, b}
		})},
		{"oversized body", "invalid_output", 502, func([]fakeSuggestUnit) (int, string) {
			return 200, envelope(strings.Repeat("x", 70<<10))
		}},
		{"timeout", "provider_timeout", 504, answerFirstCandidate},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			f := newSuggestionFixture(t, 300*time.Millisecond)
			f.provider.respond = tc.respond
			if tc.name == "timeout" {
				f.provider.delay = 600 * time.Millisecond
			}
			before := f.semanticCounts(t)
			status, _, body := f.generate(t, keyA, f.units[0], f.units[1])
			run, _ := body["run"].(map[string]any)
			if status != tc.status || run == nil || run["status"] != "failed" || run["failure_code"] != tc.code || len(items(run)) != 0 {
				t.Fatalf("%d %v", status, body)
			}
			raw, _ := json.Marshal(body)
			if strings.Contains(string(raw), suggestionTestKey) || strings.Contains(string(raw), "Bearer") {
				t.Fatalf("secret leaked: %s", raw)
			}
			if after := f.semanticCounts(t); after != before {
				t.Fatalf("semantic writes on failure: %s -> %s", before, after)
			}
			// The failed run is the committed outcome for the key: a replay
			// returns it without another provider call.
			calls := f.provider.callCount()
			if s, hdr, again := f.generate(t, keyA, f.units[0], f.units[1]); s != 201 || hdr.Get("Idempotency-Replayed") != "true" ||
				again["status"] != "failed" || f.provider.callCount() != calls {
				t.Fatalf("failed replay %d %v", s, again)
			}
		})
	}
}

func TestConceptSuggestions_ConfirmRecordsAttributedHumanSameOnce(t *testing.T) {
	f := newSuggestionFixture(t, 2*time.Second)
	_, _, run := f.generate(t, keyA, f.units[0], f.units[1])
	parler, vouloir := items(run)[0], items(run)[1]
	parlerID := num(parler["id"])

	if s, _, b := f.confirm(t, parlerID, f.c2); s != http.StatusUnprocessableEntity {
		t.Fatalf("confirm with another concept %d %v", s, b)
	}
	s, hdr, body := f.confirm(t, parlerID, f.c1)
	if s != http.StatusCreated || hdr.Get("Idempotency-Replayed") != "" {
		t.Fatalf("confirm %d %v", s, body)
	}
	link := body["link"].(map[string]any)
	if link["decision_source"] != "human" || link["relation"] != "same" {
		t.Fatalf("link %v", link)
	}
	var ev map[string]any
	_ = json.Unmarshal([]byte(link["evidence"].(string)), &ev)
	if ev["reason"] != domain.ConceptSuggestionEvidenceReason || num(ev["suggestion_item_id"]) != parlerID ||
		num(ev["suggestion_run_id"]) != num(run["id"]) || ev["generator"] != "openai:fake-model:concept_suggestion_v1" {
		t.Fatalf("evidence %v", ev)
	}
	item := body["item"].(map[string]any)
	if item["state"] != "confirmed" || num(path(item, "confirmation", "link_id")) != num(link["id"]) {
		t.Fatalf("confirmed item %v", item)
	}
	_, m := doJSON(t, http.MethodGet, f.srv.URL+"/knowledge-units/"+itoa(f.units[0])+"/concept-membership", "")
	if num(path(m, "current_membership", "concept_id")) != f.c1 {
		t.Fatalf("membership %v", m)
	}
	// Repeated confirmation: replay of the same event, no second event.
	s, hdr, again := f.confirm(t, parlerID, f.c1)
	if s != http.StatusCreated || hdr.Get("Idempotency-Replayed") != "true" || num(again["link"].(map[string]any)["id"]) != num(link["id"]) {
		t.Fatalf("replayed confirm %d %v", s, again)
	}
	var links, receipts int
	f.db.QueryRow(`SELECT COUNT(*) FROM unit_concept_links WHERE unit_id = ?`, f.units[0]).Scan(&links)
	f.db.QueryRow(`SELECT COUNT(*) FROM concept_suggestion_confirmations`).Scan(&receipts)
	if links != 1 || receipts != 1 {
		t.Fatalf("links %d receipts %d", links, receipts)
	}
	// Concurrent duplicate confirmations of another item: one event.
	vouloirID := num(vouloir["id"])
	var wg sync.WaitGroup
	statuses := make([]int, 4)
	for i := range statuses {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			statuses[i], _, _ = f.confirm(t, vouloirID, f.c2)
		}(i)
	}
	wg.Wait()
	f.db.QueryRow(`SELECT COUNT(*) FROM unit_concept_links WHERE unit_id = ?`, f.units[1]).Scan(&links)
	for _, st := range statuses {
		if st != http.StatusCreated {
			t.Fatalf("concurrent confirm statuses %v", statuses)
		}
	}
	if links != 1 {
		t.Fatalf("concurrent confirmations wrote %d events", links)
	}
	// The stored suggestion itself is unchanged and still inspectable.
	_, reread := doJSON(t, http.MethodGet, f.srv.URL+"/concept-suggestion-runs/"+itoa(num(run["id"])), "")
	if items(reread)[0]["reason"] != parler["reason"] || items(reread)[0]["state"] != "confirmed" {
		t.Fatalf("reread %v", reread)
	}
}

func TestConceptSuggestions_StaleStateBlocksConfirmation(t *testing.T) {
	cases := []struct {
		name   string
		reason string
		change func(t *testing.T, f *suggestionFixture)
	}{
		{"changed membership", "unit_has_current_same", func(t *testing.T, f *suggestionFixture) {
			doJSON(t, http.MethodPost, f.srv.URL+"/knowledge-units/"+itoa(f.units[0])+"/concept-links/same", fmt.Sprintf(`{"concept_id":%d}`, f.c3))
		}},
		{"stale extraction", "unit_not_in_current_extraction", func(t *testing.T, f *suggestionFixture) {
			extractUnits(t, f.srv, f.entryID)
		}},
		{"unit invalid", "unit_invalid", func(t *testing.T, f *suggestionFixture) {
			doJSON(t, http.MethodPost, f.srv.URL+"/knowledge-units/"+itoa(f.units[0])+"/invalid", "")
		}},
		{"target retired", "target_retired", func(t *testing.T, f *suggestionFixture) {
			f.db.Exec(`UPDATE knowledge_concepts SET lifecycle_state = 'retired' WHERE id = ?`, f.c1)
		}},
		{"target identity changed", "target_identity_changed", func(t *testing.T, f *suggestionFixture) {
			f.db.Exec(`UPDATE knowledge_concepts SET signature = 'changed' WHERE id = ?`, f.c1)
		}},
		{"target distinct", "target_distinct_recorded", func(t *testing.T, f *suggestionFixture) {
			doJSON(t, http.MethodPost, f.srv.URL+"/knowledge-units/"+itoa(f.units[0])+"/concept-distinctions", fmt.Sprintf(`{"concept_id":%d}`, f.c1))
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			f := newSuggestionFixture(t, 2*time.Second)
			_, _, run := f.generate(t, keyA, f.units[0])
			itemID := num(items(run)[0]["id"])
			tc.change(t, f)
			var linksBefore int
			f.db.QueryRow(`SELECT COUNT(*) FROM unit_concept_links`).Scan(&linksBefore)
			membershipBefore := f.semanticCounts(t)

			_, reread := doJSON(t, http.MethodGet, f.srv.URL+"/concept-suggestion-runs/"+itoa(num(run["id"])), "")
			it := items(reread)[0]
			if it["state"] != "stale" || !strings.Contains(fmt.Sprint(it["stale_reasons"]), tc.reason) {
				t.Fatalf("derived state %v", it)
			}
			s, _, body := f.confirm(t, itemID, f.c1)
			if s != http.StatusConflict || !strings.Contains(fmt.Sprint(body["stale_reasons"]), tc.reason) {
				t.Fatalf("confirm %d %v", s, body)
			}
			var linksAfter int
			f.db.QueryRow(`SELECT COUNT(*) FROM unit_concept_links`).Scan(&linksAfter)
			if linksAfter != linksBefore || f.semanticCounts(t) != membershipBefore {
				t.Fatal("a refused confirmation wrote a semantic event")
			}
		})
	}
}

func TestConceptSuggestions_DistinctConceptsAreNotCandidates(t *testing.T) {
	f := newSuggestionFixture(t, 2*time.Second)
	doJSON(t, http.MethodPost, f.srv.URL+"/knowledge-units/"+itoa(f.units[0])+"/concept-distinctions", fmt.Sprintf(`{"concept_id":%d}`, f.c1))
	_, _, run := f.generate(t, keyA, f.units[0])
	for _, c := range items(run)[0]["candidates"].([]any) {
		if num(c.(map[string]any)["concept_id"]) == f.c1 {
			t.Fatalf("DISTINCT concept offered as candidate: %v", run)
		}
	}
}

// A suggestion is never human truth; a confirmed one is a human SAME whose
// AI-assisted provenance retrieval evaluation does not classify, so it can
// never become a retrieval sample selected by the candidate policy itself.
func TestConceptSuggestions_EvaluationDoesNotTreatSuggestionsAsTruth(t *testing.T) {
	f := newSuggestionFixture(t, 2*time.Second)
	_, _, run := f.generate(t, keyA, f.units[0])
	type evaluation struct {
		DatasetValid      bool `json:"dataset_valid"`
		EvaluationSamples struct {
			HumanSameRecords int `json:"human_same_records"`
			EligibleSamples  int `json:"eligible_samples"`
			Excluded         struct {
				Unclassified int `json:"unclassified_human_same_provenance"`
			} `json:"excluded"`
		} `json:"evaluation_samples"`
	}
	read := func() evaluation {
		resp, err := http.Get(f.srv.URL + "/retrieval-evaluation/v1")
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		var e evaluation
		json.NewDecoder(resp.Body).Decode(&e)
		return e
	}
	if e := read(); e.EvaluationSamples.HumanSameRecords != 0 {
		t.Fatalf("an unconfirmed suggestion counted as human SAME: %+v", e)
	}
	f.confirm(t, num(items(run)[0]["id"]), f.c1)
	e := read()
	if !e.DatasetValid || e.EvaluationSamples.HumanSameRecords != 1 || e.EvaluationSamples.EligibleSamples != 0 ||
		e.EvaluationSamples.Excluded.Unclassified != 1 {
		t.Fatalf("evaluation after confirmation %+v", e)
	}
}

// A second request under a key that is still being generated is refused
// (409) instead of making a second provider call.
func TestConceptSuggestions_InFlightKeyIsNotDuplicated(t *testing.T) {
	f := newSuggestionFixture(t, 2*time.Second)
	f.provider.delay = 400 * time.Millisecond
	done := make(chan int, 1)
	go func() {
		status, _, _ := f.generate(t, keyA, f.units[0])
		done <- status
	}()
	deadline := time.Now().Add(time.Second)
	for f.provider.callCount() == 0 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if status, _, body := f.generate(t, keyA, f.units[0]); status != http.StatusConflict {
		t.Fatalf("duplicate in flight %d %v", status, body)
	}
	if status := <-done; status != http.StatusCreated {
		t.Fatalf("first request %d", status)
	}
	if f.provider.callCount() != 1 {
		t.Fatalf("provider calls %d", f.provider.callCount())
	}
}

// ---- FLH-097 follow-up regressions ----

// A confirmed item's own SAME is its result, not a staleness reason; the
// confirmation reports that its event is the CURRENT SAME.
func TestConceptSuggestions_ConfirmedItemIsNotStaleBecauseOfItsOwnSame(t *testing.T) {
	f := newSuggestionFixture(t, 2*time.Second)
	_, _, run := f.generate(t, keyA, f.units[0])
	_, _, body := f.confirm(t, num(items(run)[0]["id"]), f.c1)
	it := body["item"].(map[string]any)
	if it["state"] != "confirmed" || len(it["stale_reasons"].([]any)) != 0 || path(it, "confirmation", "still_current") != true {
		t.Fatalf("confirmed item %v", it)
	}
}

// A replay after a later legitimate correction returns the original historical
// event, says it is no longer current, and restores nothing.
func TestConceptSuggestions_ReplayAfterCorrectionIsHistoricalOnly(t *testing.T) {
	f := newSuggestionFixture(t, 2*time.Second)
	_, _, run := f.generate(t, keyA, f.units[0])
	itemID := num(items(run)[0]["id"])
	_, _, first := f.confirm(t, itemID, f.c1)
	original := num(first["link"].(map[string]any)["id"])
	if s, b := doJSON(t, http.MethodPut, f.srv.URL+"/knowledge-units/"+itoa(f.units[0])+"/concept-membership",
		fmt.Sprintf(`{"concept_id":%d}`, f.c3)); s != http.StatusOK && s != http.StatusCreated {
		t.Fatalf("reassign %d %v", s, b)
	}
	s, hdr, again := f.confirm(t, itemID, f.c1)
	it := again["item"].(map[string]any)
	if s != http.StatusCreated || hdr.Get("Idempotency-Replayed") != "true" || num(again["link"].(map[string]any)["id"]) != original ||
		path(it, "confirmation", "still_current") != false || num(it["current_concept_id"]) != f.c3 ||
		!strings.Contains(fmt.Sprint(it["stale_reasons"]), "unit_has_current_same") {
		t.Fatalf("replay after correction %d %v", s, again)
	}
	_, m := doJSON(t, http.MethodGet, f.srv.URL+"/knowledge-units/"+itoa(f.units[0])+"/concept-membership", "")
	var links int
	f.db.QueryRow(`SELECT COUNT(*) FROM unit_concept_links WHERE unit_id = ?`, f.units[0]).Scan(&links)
	if num(path(m, "current_membership", "concept_id")) != f.c3 || links != 2 {
		t.Fatalf("replay changed authority: membership %v, links %d", m, links)
	}
}

// Two suggestions for the same unit (two runs): confirming one resolves the
// unit, and the other is refused as stale instead of reassigning it.
func TestConceptSuggestions_SecondSuggestionForResolvedUnitIsRefused(t *testing.T) {
	f := newSuggestionFixture(t, 2*time.Second)
	_, _, runA := f.generate(t, keyA, f.units[0])
	f.provider.respond = func(units []fakeSuggestUnit) (int, string) {
		u := units[0]
		b, _ := json.Marshal(map[string]any{"suggestions": []any{map[string]any{"unit_id": u.UnitID, "outcome": "suggested",
			"concept_id": u.Candidates[len(u.Candidates)-1].ConceptID, "reason": "Alternative."}}})
		return 200, envelope(string(b))
	}
	_, _, runB := f.generate(t, keyB, f.units[0])
	itemB := items(runB)[0]
	if num(itemB["suggested_concept_id"]) == f.c1 {
		t.Fatalf("fixture needs a different target in run B: %v", itemB)
	}
	if s, _, b := f.confirm(t, num(items(runA)[0]["id"]), f.c1); s != http.StatusCreated {
		t.Fatalf("confirm A %d %v", s, b)
	}
	s, _, body := f.confirm(t, num(itemB["id"]), num(itemB["suggested_concept_id"]))
	if s != http.StatusConflict || !strings.Contains(fmt.Sprint(body["stale_reasons"]), "unit_has_current_same") {
		t.Fatalf("confirm B %d %v", s, body)
	}
	_, m := doJSON(t, http.MethodGet, f.srv.URL+"/knowledge-units/"+itoa(f.units[0])+"/concept-membership", "")
	if num(path(m, "current_membership", "concept_id")) != f.c1 {
		t.Fatalf("membership moved: %v", m)
	}
}

// Traces human_same_ai_suggestion through effective annotation, the dataset,
// the quality report, retrieval evaluation and comparison.
func TestConceptSuggestions_AnnotationAndEvaluationBoundaries(t *testing.T) {
	f := newSuggestionFixture(t, 2*time.Second)
	_, _, run := f.generate(t, keyA, f.units[0])
	unit := itoa(f.units[0])
	record := func() map[string]any {
		_, ds := doJSON(t, http.MethodGet, f.srv.URL+"/annotation-dataset/v1", "")
		for _, r := range ds["records"].([]any) {
			if num(path(r, "unit", "id")) == f.units[0] {
				return r.(map[string]any)
			}
		}
		t.Fatalf("unit missing from dataset %v", ds)
		return nil
	}

	// Generation alone: no label, no effective SAME, nothing counted.
	_, ea := doJSON(t, http.MethodGet, f.srv.URL+"/knowledge-units/"+unit+"/effective-annotation", "")
	if path(ea, "snapshot", "current_same") != nil {
		t.Fatalf("effective annotation after generation %v", ea)
	}
	if path(record(), "human_labels", "same") != nil {
		t.Fatal("suggestion became a human label")
	}
	_, q := doJSON(t, http.MethodGet, f.srv.URL+"/annotation-dataset/v1/quality", "")
	if path(q, "label_inventory", "human_same_records") != float64(0) {
		t.Fatalf("quality after generation %v", q["label_inventory"])
	}

	// Explicit confirmation: a human SAME with suggestion provenance.
	_, _, conf := f.confirm(t, num(items(run)[0]["id"]), f.c1)
	link := num(conf["link"].(map[string]any)["id"])
	_, ea = doJSON(t, http.MethodGet, f.srv.URL+"/knowledge-units/"+unit+"/effective-annotation", "")
	decision := path(ea, "snapshot", "current_same", "decision").(map[string]any)
	var ev map[string]any
	_ = json.Unmarshal([]byte(decision["evidence"].(string)), &ev)
	if path(ea, "snapshot", "status") != "resolved" || decision["decision_source"] != "human" || num(decision["id"]) != link ||
		ev["reason"] != domain.ConceptSuggestionEvidenceReason || num(ev["suggestion_item_id"]) != num(items(run)[0]["id"]) {
		t.Fatalf("effective annotation after confirmation %v", ea)
	}
	if num(path(record(), "human_labels", "same", "event_id")) != link {
		t.Fatal("dataset human SAME label does not name the confirmation's event")
	}
	_, q = doJSON(t, http.MethodGet, f.srv.URL+"/annotation-dataset/v1/quality", "")
	if q["valid"] != true || path(q, "label_inventory", "human_same_records") != float64(1) {
		t.Fatalf("quality after confirmation valid=%v %v", q["valid"], q["label_inventory"])
	}
	_, e := doJSON(t, http.MethodGet, f.srv.URL+"/retrieval-evaluation/v1", "")
	if path(e, "evaluation_samples", "human_same_records") != float64(1) || path(e, "evaluation_samples", "eligible_samples") != float64(0) ||
		path(e, "evaluation_samples", "excluded", "unclassified_human_same_provenance") != float64(1) {
		t.Fatalf("evaluation %v", e["evaluation_samples"])
	}
	_, c := doJSON(t, http.MethodGet, f.srv.URL+"/retrieval-comparison/v1", "")
	if c["dataset_valid"] != true || path(c, "evaluation_samples", "eligible_samples") != float64(0) {
		t.Fatalf("comparison %v", c)
	}
}
