// Command extraction-render is an offline tool for the knowledge-extraction
// dataset (tools/extraction). It never contacts a provider and never opens a
// database: it drives the unchanged production extractor
// (internal/extractor.OpenAI, knowledge_extraction_v2) against an in-process
// HTTP server, so prompts and validation are exactly the production ones.
//
//	extraction-render render   -in candidates.jsonl -out prompts.jsonl
//	    the exact developer instruction, user payload and output schema the
//	    production extractor sends for each candidate's input
//	extraction-render validate -in outputs.jsonl    -out results.jsonl
//	    each {"id", "input", "output_text"} line parsed and validated by the
//	    production code path; output_text is a raw model answer (the JSON text)
//	extraction-render expected -in candidates.jsonl -out results.jsonl
//	    the candidates' own expected outputs, validated the same way
//	extraction-render run -in candidates.jsonl -out results.jsonl -max-requests N -confirm-paid-calls
//	    the CONFIGURED production extractor (EXTRACTOR_PROVIDER, OPENAI_*):
//	    one request per input, sequential, no retry; a provider error is a
//	    recorded result. Refused without both flags or above N inputs.
//
// Lines are processed one at a time; the tool exits non-zero on a malformed
// input line (not on an invalid output, which is a result).
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"sync"

	"french-learning-app/internal/config"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/extractor"
)

// Input mirrors domain.ExtractionSource's model-visible fields.
type Input struct {
	EntryID              int64  `json:"entry_id"`
	OriginalInput        string `json:"original_input"`
	OriginalContext      string `json:"original_context"`
	EffectiveCategory    string `json:"effective_category"`
	EffectiveExplanation string `json:"effective_explanation"`
	Resolution           string `json:"resolution"`
}

func (in Input) source() domain.ExtractionSource {
	return domain.ExtractionSource{
		EntryID: in.EntryID, OriginalInput: in.OriginalInput, OriginalContext: in.OriginalContext,
		EffectiveCategory: in.EffectiveCategory, EffectiveExplanation: in.EffectiveExplanation,
		Resolution: domain.Resolution(in.Resolution),
	}
}

// fakeResponses is the in-process stand-in for the Responses API: it records
// the request body and answers with the queued structured-output text.
type fakeResponses struct {
	mu      sync.Mutex
	answer  string
	request []byte
}

func (f *fakeResponses) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	body, _ := io.ReadAll(r.Body)
	f.mu.Lock()
	f.request = body
	text := f.answer
	f.mu.Unlock()
	resp := map[string]any{"status": "completed", "output": []any{map[string]any{
		"type": "message", "content": []any{map[string]any{"type": "output_text", "text": text}},
	}}}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}

type tool struct {
	fake *fakeResponses
	ex   *extractor.OpenAI
	srv  *httptest.Server
}

// RenderModel is the model name recorded in rendered prompts; it is not a
// provider model and is never sent anywhere outside this process.
const RenderModel = "offline-render"

func newTool() *tool {
	f := &fakeResponses{}
	srv := httptest.NewServer(f)
	return &tool{fake: f, srv: srv, ex: extractor.NewOpenAIWithClient("offline-placeholder-key", RenderModel, srv.URL, srv.Client())}
}

func (t *tool) close() { t.srv.Close() }

// Rendered is the exact request content for one input.
type Rendered struct {
	ID         string          `json:"id"`
	Developer  string          `json:"developer"`
	User       string          `json:"user"`
	Schema     json.RawMessage `json:"schema"`
	Provenance string          `json:"extractor_provenance"`
}

func (t *tool) render(id string, in Input) (Rendered, error) {
	t.fake.mu.Lock()
	t.fake.answer = `{"units":[]}`
	t.fake.mu.Unlock()
	if _, err := t.ex.Extract(context.Background(), in.source()); err != nil {
		return Rendered{}, fmt.Errorf("render %s: %w", id, err)
	}
	t.fake.mu.Lock()
	raw := t.fake.request
	t.fake.mu.Unlock()
	var req struct {
		Input []struct {
			Role    string `json:"role"`
			Content []struct {
				Text string `json:"text"`
			} `json:"content"`
		} `json:"input"`
		Text struct {
			Format struct {
				Schema json.RawMessage `json:"schema"`
			} `json:"format"`
		} `json:"text"`
	}
	if err := json.Unmarshal(raw, &req); err != nil || len(req.Input) != 2 {
		return Rendered{}, fmt.Errorf("render %s: unexpected request shape", id)
	}
	return Rendered{ID: id, Developer: req.Input[0].Content[0].Text, User: req.Input[1].Content[0].Text,
		Schema: req.Text.Format.Schema, Provenance: t.ex.Name()}, nil
}

// Unit is one validated unit in the production payload shape.
type Unit struct {
	Kind        string  `json:"kind"`
	Canonical   string  `json:"canonical"`
	Statement   string  `json:"statement"`
	StatementZH string  `json:"statement_zh"`
	Example     *string `json:"example"`
	Confidence  float64 `json:"confidence"`
}

// Result is the production verdict on one output text.
type Result struct {
	ID         string `json:"id"`
	Valid      bool   `json:"valid"`
	ErrorClass string `json:"error_class,omitempty"` // invalid_output | unparseable_output
	Error      string `json:"error,omitempty"`
	Units      []Unit `json:"units"`
}

func (t *tool) validate(id string, in Input, outputText string) Result {
	t.fake.mu.Lock()
	t.fake.answer = outputText
	t.fake.mu.Unlock()
	res, err := t.ex.Extract(context.Background(), in.source())
	out := Result{ID: id, Units: []Unit{}}
	switch {
	case err == nil:
		out.Valid = true
		for _, u := range res.Units {
			zh := ""
			if u.Statements.ZH != nil {
				zh = *u.Statements.ZH
			}
			out.Units = append(out.Units, Unit{Kind: string(u.Kind), Canonical: u.Canonical, Statement: u.Statement,
				StatementZH: zh, Example: u.Example, Confidence: u.Confidence})
		}
	case errors.Is(err, domain.ErrValidation):
		out.ErrorClass, out.Error = "invalid_output", err.Error()
	default:
		out.ErrorClass, out.Error = "unparseable_output", err.Error()
	}
	return out
}

type line struct {
	ID         string          `json:"id"`
	Input      *Input          `json:"input"`
	OutputText *string         `json:"output_text"`
	Expected   json.RawMessage `json:"expected"`
}

// runConfigured drives the configured extractor (the paid baseline). It
// never retries and never stores anything; errors are results.
func runConfigured(ex domain.Extractor, id string, in Input) Result {
	res, err := ex.Extract(context.Background(), in.source())
	out := Result{ID: id, Units: []Unit{}}
	switch {
	case err == nil:
		out.Valid = true
		for _, u := range res.Units {
			zh := ""
			if u.Statements.ZH != nil {
				zh = *u.Statements.ZH
			}
			out.Units = append(out.Units, Unit{Kind: string(u.Kind), Canonical: u.Canonical, Statement: u.Statement,
				StatementZH: zh, Example: u.Example, Confidence: u.Confidence})
		}
	case errors.Is(err, domain.ErrValidation):
		out.ErrorClass, out.Error = "invalid_output", "the provider output failed production validation"
	case errors.Is(err, domain.ErrProviderTimeout):
		out.ErrorClass, out.Error = "provider_timeout", "provider timeout"
	default:
		out.ErrorClass, out.Error = "provider_unavailable", "provider unavailable or unparseable output"
	}
	return out
}

func run(mode, inPath, outPath string) error {
	return runWith(mode, inPath, outPath, nil, 0)
}

func runWith(mode, inPath, outPath string, configured domain.Extractor, maxRequests int) error {
	in, err := os.Open(inPath)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(outPath)
	if err != nil {
		return err
	}
	defer out.Close()
	w := bufio.NewWriter(out)
	defer w.Flush()
	t := newTool()
	defer t.close()
	sc := bufio.NewScanner(in)
	sc.Buffer(make([]byte, 0, 1<<20), 8<<20)
	n := 0
	for sc.Scan() {
		n++
		if len(sc.Bytes()) == 0 {
			continue
		}
		var l line
		if err := json.Unmarshal(sc.Bytes(), &l); err != nil || l.ID == "" || l.Input == nil {
			return fmt.Errorf("%s line %d: need a JSON object with id and input", inPath, n)
		}
		var v any
		switch mode {
		case "render":
			r, err := t.render(l.ID, *l.Input)
			if err != nil {
				return err
			}
			v = r
		case "validate":
			if l.OutputText == nil {
				return fmt.Errorf("%s line %d: validate needs output_text", inPath, n)
			}
			v = t.validate(l.ID, *l.Input, *l.OutputText)
		case "run":
			if maxRequests > 0 && n > maxRequests {
				return fmt.Errorf("more than -max-requests %d inputs; nothing beyond line %d was sent", maxRequests, n-1)
			}
			v = runConfigured(configured, l.ID, *l.Input)
		case "expected":
			if len(l.Expected) == 0 {
				return fmt.Errorf("%s line %d: expected is missing", inPath, n)
			}
			v = t.validate(l.ID, *l.Input, string(l.Expected))
		}
		raw, err := json.Marshal(v)
		if err != nil {
			return err
		}
		if _, err := w.Write(append(raw, '\n')); err != nil {
			return err
		}
	}
	return sc.Err()
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: extraction-render render|validate|expected -in FILE -out FILE")
		os.Exit(2)
	}
	mode := os.Args[1]
	fs := flag.NewFlagSet(mode, flag.ExitOnError)
	inPath := fs.String("in", "", "input JSONL")
	outPath := fs.String("out", "", "output JSONL")
	maxRequests := fs.Int("max-requests", 0, "run: refuse more inputs than this")
	confirm := fs.Bool("confirm-paid-calls", false, "run: acknowledge that each input is one provider request")
	_ = fs.Parse(os.Args[2:])
	if (mode != "render" && mode != "validate" && mode != "expected" && mode != "run") || *inPath == "" || *outPath == "" {
		fmt.Fprintln(os.Stderr, "usage: extraction-render render|validate|expected|run -in FILE -out FILE")
		os.Exit(2)
	}
	var configured domain.Extractor
	if mode == "run" {
		if !*confirm || *maxRequests < 1 {
			fmt.Fprintln(os.Stderr, "extraction-render: run sends one provider request per input; pass -max-requests N and -confirm-paid-calls")
			os.Exit(2)
		}
		cfg, err := config.Load()
		if err != nil {
			fmt.Fprintln(os.Stderr, "extraction-render:", err)
			os.Exit(2)
		}
		configured, err = extractor.New(cfg.Extractor)
		if err != nil || configured == nil {
			fmt.Fprintln(os.Stderr, "extraction-render: EXTRACTOR_PROVIDER is disabled or invalid")
			os.Exit(2)
		}
	}
	if err := runWith(mode, *inPath, *outPath, configured, *maxRequests); err != nil {
		fmt.Fprintln(os.Stderr, "extraction-render:", err)
		os.Exit(1)
	}
}
