package http_test

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"french-learning-app/internal/analyzer"
	"french-learning-app/internal/extractor"
)

// FLH-095 wire contract: bilingual explanations through HTTP -> service ->
// provider adapter -> storage, with fake providers only.

func doJSON(t *testing.T, method, url, body string) (int, map[string]any) {
	t.Helper()
	req, _ := http.NewRequestWithContext(context.Background(), method, url, strings.NewReader(body))
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("%s %s: %v", method, url, err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	var out map[string]any
	_ = json.Unmarshal(raw, &out)
	return resp.StatusCode, out
}

func path(v any, keys ...string) any {
	for _, k := range keys {
		m, ok := v.(map[string]any)
		if !ok {
			return nil
		}
		v = m[k]
	}
	return v
}

func TestIntegration_BilingualAnalysisFeedbackAndEffective(t *testing.T) {
	provider := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, fakeProviderResponse(t, "grammar", "Ne … pas surrounds the verb.", 0.8))
	}))
	t.Cleanup(provider.Close)
	srv := setupServerWithAnalyzer(t, analyzer.NewOpenAIWithClient("sk-test", "gpt-test", provider.URL, provider.Client()))
	ctx := context.Background()

	entryID := createEntry(t, ctx, srv.URL, `{"original_input":"Je ne mange pas.","original_context":""}`)
	status, a := doJSON(t, http.MethodPost, srv.URL+"/entries/"+itoa(entryID)+"/analysis", "")
	if status != http.StatusCreated || path(a, "explanations", "en") != "Ne … pas surrounds the verb." ||
		path(a, "explanations", "zh") != "测试用中文解释。" || a["explanation"] != "Ne … pas surrounds the verb." {
		t.Fatalf("analysis %d %v", status, a)
	}
	analysisID := int64(a["id"].(float64))
	base := srv.URL + "/analyses/" + itoa(analysisID)

	_, eff := doJSON(t, http.MethodGet, base+"/effective", "")
	if path(eff, "effective_explanations", "zh", "basis") != "unreviewed" || path(eff, "original_explanations", "zh") != "测试用中文解释。" {
		t.Fatalf("unreviewed effective %v", eff)
	}

	for _, bad := range []string{
		`{"status":"accepted","reviewed_explanation_languages":["fr"]}`,
		`{"status":"accepted","reviewed_explanation_languages":["en","en"]}`,
		`{"status":"corrected","corrected_explanation":"x","corrected_explanation_zh":"y"}`,
		`{"status":"accepted","corrected_explanation_en":"x"}`,
	} {
		if s, body := doJSON(t, http.MethodPost, base+"/feedback", bad); s != http.StatusUnprocessableEntity {
			t.Fatalf("%s -> %d %v, want 422", bad, s, body)
		}
	}

	// Accepted while only English was shown: Chinese is not approved.
	s, fb := doJSON(t, http.MethodPost, base+"/feedback", `{"status":"accepted","reviewed_explanation_languages":["en"]}`)
	if s != http.StatusCreated || len(fb["reviewed_explanation_languages"].([]any)) != 1 {
		t.Fatalf("accept %d %v", s, fb)
	}
	_, eff = doJSON(t, http.MethodGet, base+"/effective", "")
	if path(eff, "effective_explanations", "en", "basis") != "reviewed" || path(eff, "effective_explanations", "zh", "basis") != "not_reviewed" {
		t.Fatalf("accepted (en shown) effective %v", eff)
	}

	// A later Chinese-only correction: zh corrected, en outdated, and the
	// language-independent effective explanation is the correction.
	s, fb = doJSON(t, http.MethodPost, base+"/feedback",
		`{"status":"corrected","corrected_explanation_zh":"「ne … pas」包围变位动词。","reviewed_explanation_languages":["zh","en"]}`)
	if s != http.StatusCreated || fb["corrected_explanation_zh"] != "「ne … pas」包围变位动词。" ||
		strings.Join([]string{fb["reviewed_explanation_languages"].([]any)[0].(string), fb["reviewed_explanation_languages"].([]any)[1].(string)}, ",") != "en,zh" {
		t.Fatalf("correct %d %v", s, fb)
	}
	_, eff = doJSON(t, http.MethodGet, base+"/effective", "")
	if path(eff, "effective_explanations", "zh", "basis") != "corrected" || path(eff, "effective_explanations", "en", "basis") != "outdated" ||
		path(eff, "effective", "explanation") != "「ne … pas」包围变位动词。" || path(eff, "original", "explanation") != "Ne … pas surrounds the verb." {
		t.Fatalf("corrected effective %v", eff)
	}
	// History keeps both decisions; the analysis itself is unchanged.
	_, list := doJSON(t, http.MethodGet, base+"/feedback", "")
	if n := len(list["feedback"].([]any)); n != 2 {
		t.Fatalf("feedback history has %d records, want 2", n)
	}
	_, entry := doJSON(t, http.MethodGet, srv.URL+"/entries/"+itoa(entryID), "")
	if entry["original_input"] != "Je ne mange pas." {
		t.Fatalf("entry changed: %v", entry)
	}
}

func TestIntegration_CaptureImportHasNoRecordedLanguage(t *testing.T) {
	srv := setupServer(t)
	status, imp := doJSON(t, http.MethodPost, srv.URL+"/captures", `{"schema_version":"learning_capture_v1","capture_id":"flh095-legacy",
		"source":"chatgpt-web","original_input":"Je parle japonais ?","original_context":"",
		"analysis":{"category":"grammar","explanation":"Pas d'article après parler.","confidence":0.9,"uncertainty":""}}`)
	if status != http.StatusCreated {
		t.Fatalf("import %d %v", status, imp)
	}
	_, list := doJSON(t, http.MethodGet, srv.URL+"/entries/"+itoa(int64(imp["entry_id"].(float64)))+"/analyses", "")
	a := list["analyses"].([]any)[0]
	if path(a, "explanations", "en") != nil || path(a, "explanations", "zh") != nil || path(a, "explanation") != "Pas d'article après parler." {
		t.Fatalf("imported analysis %v", a)
	}
	id := itoa(int64(path(a, "id").(float64)))
	// No language was recorded, so none can be claimed as reviewed.
	if s, _ := doJSON(t, http.MethodPost, srv.URL+"/analyses/"+id+"/feedback", `{"status":"accepted","reviewed_explanation_languages":["en"]}`); s != http.StatusUnprocessableEntity {
		t.Fatalf("reviewed en on an imported analysis -> %d, want 422", s)
	}
	_, eff := doJSON(t, http.MethodGet, srv.URL+"/analyses/"+id+"/effective", "")
	if path(eff, "effective_explanations", "en", "basis") != "unavailable" || path(eff, "effective", "explanation") != "Pas d'article après parler." {
		t.Fatalf("imported effective %v", eff)
	}
	// No per-language correction either: the original's language is unknown, so
	// a correction cannot be filed under one. Nothing is stored.
	for _, bad := range []string{
		`{"status":"corrected","corrected_explanation_en":"No article after parler."}`,
		`{"status":"corrected","corrected_explanation_zh":"parler 后不加冠词。"}`,
		`{"status":"corrected","corrected_category":"grammar","corrected_explanation_en":"x","corrected_explanation_zh":"y"}`,
	} {
		if s, body := doJSON(t, http.MethodPost, srv.URL+"/analyses/"+id+"/feedback", bad); s != http.StatusUnprocessableEntity {
			t.Fatalf("%s on an imported analysis -> %d %v, want 422", bad, s, body)
		}
	}
	if _, fl := doJSON(t, http.MethodGet, srv.URL+"/analyses/"+id+"/feedback", ""); len(fl["feedback"].([]any)) != 0 {
		t.Fatalf("refused feedback was stored: %v", fl)
	}
	// The language-unspecified correction still works.
	s, fb := doJSON(t, http.MethodPost, srv.URL+"/analyses/"+id+"/feedback",
		`{"status":"corrected","corrected_explanation":"Pas d'article après parler une langue."}`)
	if s != http.StatusCreated || fb["corrected_explanation_en"] != nil || fb["corrected_explanation_zh"] != nil {
		t.Fatalf("legacy correction %d %v", s, fb)
	}
	_, eff = doJSON(t, http.MethodGet, srv.URL+"/analyses/"+id+"/effective", "")
	if path(eff, "effective", "explanation") != "Pas d'article après parler une langue." ||
		path(eff, "effective_explanations", "en", "basis") != "unavailable" || path(eff, "effective_explanations", "zh", "basis") != "unavailable" {
		t.Fatalf("legacy corrected effective %v", eff)
	}
}

func TestIntegration_BilingualExtractionStatements(t *testing.T) {
	provider := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		inner := `{"units":[{"kind":"grammar","canonical":"ne … pas","statement":"Ne … pas surrounds the conjugated verb.",` +
			`"statement_zh":"「ne … pas」包围变位动词。","example":"Je ne mange pas.","confidence":0.9}]}`
		out, _ := json.Marshal(map[string]any{"status": "completed", "output": []any{map[string]any{
			"type": "message", "content": []any{map[string]any{"type": "output_text", "text": inner}}}}})
		w.Write(out)
	}))
	t.Cleanup(provider.Close)
	srv, entries, analyses, _ := setupKnowledgeServer(t, extractor.NewOpenAIWithClient("sk-test", "gpt-test", provider.URL, provider.Client()))
	entryID := seedAnalyzedEntry(t, entries, analyses)

	status, ext := doJSON(t, http.MethodPost, srv.URL+"/entries/"+itoa(entryID)+"/extractions", "")
	unit := path(ext, "units").([]any)[0]
	if status != http.StatusCreated || ext["extractor"] != "openai:gpt-test:knowledge_extraction_v2" ||
		path(unit, "statement") != "Ne … pas surrounds the conjugated verb." || path(unit, "statements", "zh") != "「ne … pas」包围变位动词。" ||
		path(unit, "example") != "Je ne mange pas." {
		t.Fatalf("extraction %d %v", status, ext)
	}
	_, listed := doJSON(t, http.MethodGet, srv.URL+"/entries/"+itoa(entryID)+"/extractions", "")
	stored := path(listed, "extractions").([]any)[0]
	if path(path(stored, "units").([]any)[0], "statements", "en") != "Ne … pas surrounds the conjugated verb." {
		t.Fatalf("stored unit %v", stored)
	}
}
