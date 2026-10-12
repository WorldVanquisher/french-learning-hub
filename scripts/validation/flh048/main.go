// Command flh048 runs an EXPLORATORY retrieval comparison over the frozen
// FLH-045 synthetic fixture by calling the existing Go ConceptRetriever
// implementations. It is not the production concept_retrieval_eval_policy_v1
// report and the fixture's judgments are author proposals, not human ground
// truth.
//
//	go run ./scripts/validation/flh048 -out "$TMPDIR/flh048-run"
//
// Ranking inputs (Concept identities and Unit evidence) and evaluator data
// (proposed targets, alternatives, splits, languages, buckets) are decoded into
// separate structures; only the former reaches a retriever or provider.
//
// The embedding retriever is unavailable unless -embedding=http is given with
// a caller-supplied OpenAI-compatible endpoint, a model name and an explicit
// input-position cap. No .env file is read; an API key is taken only from the
// environment variable named by -embedding-api-key-env and never logged.
//
// The runner is frozen-fixture-only: the fixture's SHA-256 must equal the
// FLH-045 constant compiled into this runner. -expect-fixture-sha256 is only an
// extra equality assertion and can never redefine which fixture is frozen.
//
// -timeout bounds the run: it is checked before and after every Retrieve, and
// a retriever that misses it fails without metrics. A synchronous Retrieve that
// ignores its context cannot be interrupted by that check (see RunRetriever).
//
// Exit status: 0 report written and every enabled retriever completed;
// 1 report written but an enabled retriever failed (including the overall
// timeout); 2 usage or configuration; 3 input or output error.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/embedding"
)

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr, nil))
}

// EmbeddingConfig is the validated, deliberately enabled HTTP endpoint.
type EmbeddingConfig struct {
	Enabled    bool          `json:"enabled"`
	BaseURL    string        `json:"base_url,omitempty"`
	Model      string        `json:"model,omitempty"`
	APIKeyEnv  string        `json:"api_key_env,omitempty"`
	APIKeySet  bool          `json:"api_key_set"`
	Timeout    time.Duration `json:"timeout_ns,omitempty"`
	MaxInputs  int           `json:"max_input_positions,omitempty"`
	Dimensions int           `json:"expected_dimensions,omitempty"`
	apiKey     string
}

// ValidateEmbeddingConfig checks an explicit opt-in. getenv is injected for tests.
func ValidateEmbeddingConfig(mode, baseURL, model, keyEnv string, timeout time.Duration, maxInputs, dims, planned int, getenv func(string) string) (EmbeddingConfig, error) {
	switch mode {
	case "", "disabled":
		if baseURL != "" || model != "" || keyEnv != "" || maxInputs != 0 || dims != 0 {
			return EmbeddingConfig{}, errors.New("embedding flags given but -embedding is not http; refusing to guess")
		}
		return EmbeddingConfig{}, nil
	case "http":
	default:
		return EmbeddingConfig{}, fmt.Errorf("-embedding must be disabled or http, got %q", mode)
	}
	u, err := url.Parse(baseURL)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
		return EmbeddingConfig{}, errors.New("-embedding-base-url must be an absolute http(s) URL")
	}
	if u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return EmbeddingConfig{}, errors.New("-embedding-base-url must not contain credentials, a query string or a fragment; use -embedding-api-key-env")
	}
	if strings.TrimSpace(model) == "" {
		return EmbeddingConfig{}, errors.New("-embedding-model is required")
	}
	if timeout < time.Second || timeout > 5*time.Minute {
		return EmbeddingConfig{}, errors.New("-embedding-timeout must be between 1s and 5m")
	}
	if maxInputs <= 0 {
		return EmbeddingConfig{}, fmt.Errorf("-embedding-max-inputs is required; this run submits %d input positions", planned)
	}
	if maxInputs < planned {
		return EmbeddingConfig{}, fmt.Errorf("-embedding-max-inputs %d is below the %d input positions this run submits; refusing to start", maxInputs, planned)
	}
	if dims < 0 {
		return EmbeddingConfig{}, errors.New("-embedding-dimensions must be positive when given")
	}
	cfg := EmbeddingConfig{Enabled: true, BaseURL: u.Scheme + "://" + u.Host + u.Path, Model: model, APIKeyEnv: keyEnv,
		Timeout: timeout, MaxInputs: maxInputs, Dimensions: dims}
	if keyEnv != "" {
		cfg.apiKey = getenv(keyEnv)
		if cfg.apiKey == "" {
			return EmbeddingConfig{}, fmt.Errorf("environment variable %s named by -embedding-api-key-env is empty", keyEnv)
		}
		cfg.APIKeySet = true
	}
	return cfg, nil
}

// findRepoRoot walks up from dir to the directory holding go.mod.
func findRepoRoot(dir string) (string, error) {
	for {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", errors.New("go.mod not found; run from the repository")
		}
		dir = parent
	}
}

// run is main without process exit. providerOverride lets tests substitute a
// provider for the HTTP one (it is still wrapped by the counter).
func run(args []string, stdout, stderr io.Writer, providerOverride application.EmbeddingProvider) int {
	fs := flag.NewFlagSet("flh048", flag.ContinueOnError)
	fs.SetOutput(stderr)
	fixture := fs.String("fixture", "", "fixture path (default: <repo>/scripts/validation/flh045/fixture.json)")
	out := fs.String("out", "", "new or empty output directory outside the repository (required)")
	expect := fs.String("expect-fixture-sha256", "", "optional extra assertion; must equal the frozen FLH-045 SHA-256 compiled into this runner")
	mode := fs.String("embedding", "disabled", "disabled (default) or http")
	baseURL := fs.String("embedding-base-url", "", "OpenAI-compatible base URL (POST <url>/embeddings)")
	model := fs.String("embedding-model", "", "model name sent to the endpoint")
	keyEnv := fs.String("embedding-api-key-env", "", "name of an environment variable holding the API key (optional)")
	timeout := fs.Duration("embedding-timeout", 30*time.Second, "per-request timeout (1s..5m)")
	maxInputs := fs.Int("embedding-max-inputs", 0, "cap on submitted input positions (required with -embedding=http)")
	dims := fs.Int("embedding-dimensions", 0, "expected vector dimensions (optional check)")
	overall := fs.Duration("timeout", 10*time.Minute, "overall run timeout (must be positive)")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if fs.NArg() != 0 {
		fmt.Fprintln(stderr, "unexpected arguments:", fs.Args())
		return 2
	}
	if *overall <= 0 {
		fmt.Fprintf(stderr, "-timeout must be positive, got %s\n", *overall)
		return 2
	}
	if *expect != "" && *expect != flh045FixtureSHA256 {
		fmt.Fprintf(stderr, "-expect-fixture-sha256 %s is not the frozen FLH-045 SHA-256 %s; this runner accepts only the frozen fixture\n", *expect, flh045FixtureSHA256)
		return 2
	}
	cwd, _ := os.Getwd()
	root, err := findRepoRoot(cwd)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 3
	}
	if *fixture == "" {
		*fixture = filepath.Join(root, "scripts", "validation", "flh045", "fixture.json")
	}
	raw, err := os.ReadFile(*fixture)
	if err != nil {
		fmt.Fprintln(stderr, "read fixture:", err)
		return 3
	}
	in, err := LoadRankingInputs(raw)
	if err != nil {
		fmt.Fprintln(stderr, "ranking inputs:", err)
		return 3
	}
	ev, err := LoadEvaluation(raw, in)
	if err != nil {
		fmt.Fprintln(stderr, "evaluator view:", err)
		return 3
	}
	digests, err := Digests(raw, in)
	if err != nil {
		fmt.Fprintln(stderr, "digests:", err)
		return 3
	}
	if !digests.FixtureMatchesFrozen {
		fmt.Fprintf(stderr, "fixture sha256 %s is not the frozen FLH-045 %s; refusing to run on a modified fixture\n", digests.FixtureSHA256, flh045FixtureSHA256)
		return 3
	}
	digests.CallerAssertedSHA256 = *expect
	planned := plannedEmbeddingPositions(in)
	emb, err := ValidateEmbeddingConfig(*mode, *baseURL, *model, *keyEnv, *timeout, *maxInputs, *dims, planned, os.Getenv)
	if err != nil {
		fmt.Fprintln(stderr, "embedding configuration:", err)
		return 2
	}
	outDir, err := PrepareOutputDir(*out, root, *fixture)
	if err != nil {
		fmt.Fprintln(stderr, "output:", err)
		return 3
	}

	ctx, cancel := context.WithTimeout(context.Background(), *overall)
	defer cancel()
	started := time.Now().UTC()

	baselines := []application.ConceptRetriever{
		application.NewExactSignatureConceptRetriever(),
		application.NewWeightedLexicalConceptRetriever(),
		application.NewBM25ConceptRetriever(),
	}
	report := &Report{Schema: reportSchema, Labels: Labels, Inputs: digests,
		FixtureStatus: map[string]string{"path": *fixture, "schema_version": ev.SchemaVersion, "label_status": ev.LabelStatus},
		Sources:       hashSources(root), Denominators: CountDenominators(ev, len(in.Documents)),
		ConceptIDs: idMap(in.ConceptFixtureIDs), QueryIDs: idMap(in.QueryFixtureIDs)}
	for _, r := range baselines {
		rr := buildRetrieverReport(RunRetriever(ctx, r, in), ev)
		if r.Name() == application.ExactSignatureRetrieverV1Name {
			rr.Structure = ExactStructure(in)
		}
		report.Baselines = append(report.Baselines, rr)
	}

	var counter *ProviderCounter
	if emb.Enabled {
		var provider application.EmbeddingProvider = embedding.NewHTTPProvider(emb.apiKey, emb.Model, emb.BaseURL, emb.Timeout)
		if providerOverride != nil {
			provider = providerOverride
		}
		counter = NewProviderCounter(provider, emb.MaxInputs, emb.Dimensions)
		er := RunRetriever(ctx, application.NewEmbeddingConceptRetriever(counter), in)
		er.Provider = counter
		er.Note = "Caller-supplied endpoint. Results describe that endpoint only; a stub or fake endpoint tests plumbing, not quality."
		report.Embedding = buildRetrieverReport(er, ev)
	} else {
		report.Embedding = buildRetrieverReport(RetrieverRun{Name: application.EmbeddingRetrieverV1Name, State: stateUnavailable,
			Note: "Not enabled (default); no provider was constructed or contacted and nothing was substituted.", Queries: []QueryRun{}}, ev)
	}

	deadline := "not reached"
	if err := ctx.Err(); err != nil {
		deadline = deadlineError("during the run; affected retrievers failed without metrics", err)
	}
	report.Run = map[string]any{
		"timeout_ns": overall.Nanoseconds(), "timeout": overall.String(), "deadline": deadline,
		"timeout_limit": "checked before and after each Retrieve; a synchronous Retrieve that ignores its context is not interrupted",
		"started_at":    started.Format(time.RFC3339Nano), "finished_at": time.Now().UTC().Format(time.RFC3339Nano),
		"go_version": runtime.Version(), "goos": runtime.GOOS, "goarch": runtime.GOARCH,
		"command": "go run ./scripts/validation/flh048 " + strings.Join(args, " "),
	}
	report.Configuration = map[string]any{
		"limit_k": retrievalLimit, "catalog": "all fixture Concepts for every query (no split filtering)",
		"retriever_order":                   []string{application.ExactSignatureRetrieverV1Name, application.WeightedLexicalRetrieverV1Name, application.BM25RetrieverV1Name, application.EmbeddingRetrieverV1Name},
		"parameters":                        "existing implementations as compiled; no tuning (see source_sha256)",
		"query_mapping":                     "unit_evidence -> KnowledgeUnit -> domain.DeriveCandidateIdentity (mirrors application.toConceptRetrievalQuery)",
		"document_mapping":                  "identity -> ConceptIdentity.Validate/Signature; lifecycle normal, support supported, state active (mirrors application.toConceptRetrievalDocument)",
		"id_mapping":                        "runtime IDs 1..n in ascending fixture-ID order; ties break by ascending runtime ID",
		"planned_embedding_input_positions": planned,
		"embedding":                         emb,
	}

	data, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		fmt.Fprintln(stderr, "encode report:", err)
		return 3
	}
	summary := Summary(report)
	if err := writeNew(filepath.Join(outDir, "report.json"), append(data, '\n')); err != nil {
		fmt.Fprintln(stderr, "write report:", err)
		return 3
	}
	if err := writeNew(filepath.Join(outDir, "summary.md"), []byte(summary)); err != nil {
		fmt.Fprintln(stderr, "write summary:", err)
		return 3
	}
	fmt.Fprint(stdout, summary)
	fmt.Fprintf(stdout, "\nWrote %s and %s\n", filepath.Join(outDir, "report.json"), filepath.Join(outDir, "summary.md"))
	for _, rr := range append(append([]RetrieverReport(nil), report.Baselines...), report.Embedding) {
		if rr.State == stateFailed {
			return 1
		}
	}
	return 0
}

func hashSources(root string) map[string]string {
	out := map[string]string{}
	for _, rel := range sourceFiles {
		b, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(rel)))
		if err != nil {
			out[rel] = "unreadable: " + err.Error()
			continue
		}
		out[rel] = sha256Hex(b)
	}
	return out
}
