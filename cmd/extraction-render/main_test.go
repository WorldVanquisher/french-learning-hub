package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"french-learning-app/internal/extractor"
)

func sample() Input {
	return Input{EntryID: 7, OriginalInput: "Pourquoi « je suis allé » et pas « j'ai allé » ?", OriginalContext: "message à un ami",
		EffectiveCategory: "grammar", EffectiveExplanation: "Aller forms the passé composé with être.", Resolution: "accepted"}
}

func TestRenderIsTheProductionRequest(t *testing.T) {
	tl := newTool()
	defer tl.close()
	r, err := tl.render("c1", sample())
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(r.Developer, "Schema version: fr_l2_knowledge_v1") || strings.Contains(r.Developer, "j'ai allé") {
		t.Fatalf("developer instruction must be the trusted production text without learner data")
	}
	var user map[string]any
	if err := json.Unmarshal([]byte(r.User), &user); err != nil {
		t.Fatal(err)
	}
	if user["original_input"] != sample().OriginalInput || user["effective_explanation"] != sample().EffectiveExplanation || user["resolution"] != "accepted" || user["entry_id"] != float64(7) {
		t.Fatalf("user payload = %v", user)
	}
	if r.Provenance != "openai:offline-render:knowledge_extraction_v2" || !strings.Contains(string(r.Schema), `"statement_zh"`) {
		t.Fatalf("provenance %q schema %s", r.Provenance, r.Schema)
	}
}

func TestValidateUsesTheProductionRules(t *testing.T) {
	tl := newTool()
	defer tl.close()
	ok := `{"units":[{"kind":"grammar","canonical":"aller — passé composé avec être","statement":"« Aller » forms the passé composé with « être ».","statement_zh":"« aller » 用 « être » 构成复合过去时。","example":"Je suis allé au marché.","confidence":0.9}]}`
	cases := map[string]struct {
		text  string
		valid bool
		class string
	}{
		"valid":           {ok, true, ""},
		"zero units":      {`{"units":[]}`, true, ""},
		"no zh":           {`{"units":[{"kind":"grammar","canonical":"c","statement":"s","example":null,"confidence":0.9}]}`, false, "invalid_output"},
		"bad kind":        {strings.Replace(ok, `"grammar"`, `"tense"`, 1), false, "invalid_output"},
		"confidence":      {strings.Replace(ok, `0.9`, `1.5`, 1), false, "invalid_output"},
		"duplicate":       {`{"units":[` + ok[10:len(ok)-2] + `,` + ok[10:len(ok)-2] + `]}`, false, "invalid_output"},
		"not json":        {`Voici les unités : …`, false, "unparseable_output"},
		"blank canonical": {strings.Replace(ok, `"aller — passé composé avec être"`, `"  "`, 1), false, "invalid_output"},
	}
	for name, c := range cases {
		r := tl.validate(name, sample(), c.text)
		if r.Valid != c.valid || r.ErrorClass != c.class {
			t.Errorf("%s: valid=%v class=%q err=%q", name, r.Valid, r.ErrorClass, r.Error)
		}
	}
	if r := tl.validate("v", sample(), ok); len(r.Units) != 1 || r.Units[0].StatementZH == "" || *r.Units[0].Example != "Je suis allé au marché." {
		t.Fatalf("normalized units = %+v", r.Units)
	}
}

func TestRunModes(t *testing.T) {
	dir := t.TempDir()
	in := filepath.Join(dir, "c.jsonl")
	raw, _ := json.Marshal(map[string]any{"id": "c1", "input": sample(), "expected": map[string]any{"units": []any{}}})
	if err := os.WriteFile(in, append(raw, '\n'), 0o600); err != nil {
		t.Fatal(err)
	}
	for _, mode := range []string{"render", "expected"} {
		out := filepath.Join(dir, mode+".jsonl")
		if err := run(mode, in, out); err != nil {
			t.Fatalf("%s: %v", mode, err)
		}
		b, _ := os.ReadFile(out)
		if !strings.Contains(string(b), `"id":"c1"`) {
			t.Fatalf("%s output %s", mode, b)
		}
	}
	bad := filepath.Join(dir, "bad.jsonl")
	_ = os.WriteFile(bad, []byte("{\"id\":\"x\"}\n"), 0o600)
	if err := run("render", bad, filepath.Join(dir, "o.jsonl")); err == nil {
		t.Fatal("a line without input must be refused")
	}
}

func TestRunModeUsesTheConfiguredExtractorAndCapsRequests(t *testing.T) {
	calls := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		_, _ = w.Write([]byte(`{"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"{\"units\":[]}"}]}]}`))
	}))
	defer srv.Close()
	ex := extractor.NewOpenAIWithClient("k", "fake", srv.URL, srv.Client())
	dir := t.TempDir()
	in := filepath.Join(dir, "c.jsonl")
	var lines []byte
	for _, id := range []string{"a", "b", "c"} {
		raw, _ := json.Marshal(map[string]any{"id": id, "input": sample()})
		lines = append(lines, append(raw, '\n')...)
	}
	_ = os.WriteFile(in, lines, 0o600)
	out := filepath.Join(dir, "o.jsonl")
	if err := runWith("run", in, out, ex, 3); err != nil || calls != 3 {
		t.Fatalf("err=%v calls=%d", err, calls)
	}
	calls = 0
	if err := runWith("run", in, out, ex, 2); err == nil || calls != 2 {
		t.Fatalf("the cap must stop before the third request: err=%v calls=%d", err, calls)
	}
}
