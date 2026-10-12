// FLH-053 probes existing HTTPProvider plumbing. Default is a local fake;
// supplied endpoints require explicit opt-in. It never adds E5 prefixes.
package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/embedding"
)

type wireCall struct {
	Method       string   `json:"method"`
	Path         string   `json:"path"`
	Model        string   `json:"model"`
	InputHashes  []string `json:"input_sha256"`
	Status       int      `json:"http_status"`
	ResponseHash string   `json:"response_sha256"`
	body         []byte
}
type tape struct {
	inner                            http.RoundTripper
	maxRequests, maxInputs, maxBytes int
	positions                        int
	calls                            []*wireCall
}
type captureBody struct {
	io.ReadCloser
	call *wireCall
}

func (b *captureBody) Read(p []byte) (int, error) {
	n, err := b.ReadCloser.Read(p)
	if len(b.call.body) < (16<<20)+1 {
		b.call.body = append(b.call.body, p[:min(n, (16<<20)+1-len(b.call.body))]...)
	}
	return n, err
}
func (t *tape) RoundTrip(req *http.Request) (*http.Response, error) {
	if req.GetBody == nil {
		return nil, errors.New("request body unavailable to observer")
	}
	r, err := req.GetBody()
	if err != nil {
		return nil, err
	}
	defer r.Close()
	var body struct {
		Model string   `json:"model"`
		Input []string `json:"input"`
	}
	if err := json.NewDecoder(io.LimitReader(r, 64<<10)).Decode(&body); err != nil {
		return nil, err
	}
	if len(t.calls) >= t.maxRequests || t.positions+len(body.Input) > t.maxInputs {
		return nil, errors.New("probe request/input limit")
	}
	for _, text := range body.Input {
		if len(text) > t.maxBytes {
			return nil, errors.New("probe input byte limit")
		}
	}
	w := &wireCall{Method: req.Method, Path: req.URL.Path, Model: body.Model, InputHashes: []string{}}
	for _, text := range body.Input {
		w.InputHashes = append(w.InputHashes, digest([]byte(text)))
	}
	t.calls = append(t.calls, w)
	t.positions += len(body.Input)
	response, err := t.inner.RoundTrip(req)
	if err != nil {
		return nil, err
	}
	w.Status = response.StatusCode
	response.Body = &captureBody{ReadCloser: response.Body, call: w}
	return response, nil
}

type settings struct {
	Dimensions        int     `json:"expected_dimensions"`
	AbsTolerance      float64 `json:"absolute_tolerance"`
	RelTolerance      float64 `json:"relative_tolerance"`
	RequireUnitNorm   bool    `json:"require_unit_norm"`
	UnitNormTolerance float64 `json:"unit_norm_tolerance"`
}
type batchResult struct {
	Name    string      `json:"name"`
	State   string      `json:"state"`
	Error   string      `json:"error_category,omitempty"`
	Vectors [][]float64 `json:"ordered_vectors,omitempty"`
	Norms   []float64   `json:"l2_norms,omitempty"`
}
type result struct {
	Schema    string        `json:"schema"`
	Scope     string        `json:"scope"`
	Mode      string        `json:"mode"`
	State     string        `json:"state"`
	Model     string        `json:"wire_model"`
	Settings  settings      `json:"checks"`
	Inputs    []batch       `json:"synthetic_inputs"`
	Batches   []batchResult `json:"batches"`
	Wire      []*wireCall   `json:"wire_calls"`
	Positions int           `json:"submitted_input_positions"`
}

func digest(b []byte) string { s := sha256.Sum256(b); return hex.EncodeToString(s[:]) }
func category(err error) string {
	if errors.Is(err, application.ErrEmbeddingProviderTimeout) {
		return "provider_timeout"
	}
	if errors.Is(err, application.ErrEmbeddingProviderUnavailable) {
		return "provider_unavailable"
	}
	return "probe_failure"
}
func responseHasIndices(raw []byte) bool {
	var body struct {
		Data []map[string]json.RawMessage `json:"data"`
	}
	if json.Unmarshal(raw, &body) != nil {
		return false
	}
	for _, item := range body.Data {
		raw, ok := item["index"]
		if !ok || bytes.Equal(bytes.TrimSpace(raw), []byte("null")) {
			return false
		}
	}
	return true
}
func norm(vector []float64) float64 {
	var n float64
	for _, v := range vector {
		n = math.Hypot(n, v)
	}
	return n
}
func closeVector(a, b []float64, s settings) bool {
	if len(a) != len(b) {
		return false
	}
	for i, x := range a {
		if math.Abs(x-b[i]) > s.AbsTolerance+s.RelTolerance*math.Max(math.Abs(x), math.Abs(b[i])) {
			return false
		}
	}
	return true
}
func exercise(ctx context.Context, p application.EmbeddingProvider, t *tape, inputs []batch, s settings) result {
	out := result{Schema: "flh053_embedding_contract_probe_v1", Scope: "connectivity/vector plumbing only; no semantic-quality, role-adapter or GPU acceptance", State: "passed", Settings: s, Inputs: inputs, Batches: []batchResult{}}
	seen := map[string][]float64{}
	for _, b := range inputs {
		row := batchResult{Name: b.Name, State: "passed"}
		vectors, err := p.Embed(ctx, b.Inputs)
		if err != nil {
			row.State = "provider_rejected"
			row.Error = category(err)
		} else {
			row.Vectors = vectors
			row.Norms = []float64{}
			if len(vectors) != len(b.Inputs) {
				row.Error = "vector_count"
			}
			if len(t.calls) == 0 || !responseHasIndices(t.calls[len(t.calls)-1].body) {
				row.Error = "missing_explicit_index"
			}
			for i, v := range vectors {
				n := norm(v)
				row.Norms = append(row.Norms, n)
				stored, err := application.ValidateEmbedding(v, s.Dimensions)
				storedNonzero := false
				for _, component := range stored {
					storedNonzero = storedNonzero || component != 0
				}
				if err != nil || !storedNonzero || n == 0 || math.IsInf(n, 0) || math.IsNaN(n) {
					row.Error = "dimensions_finite_nonzero_float32"
					break
				}
				if s.RequireUnitNorm && math.Abs(n-1) > s.UnitNormTolerance {
					row.Error = "unit_norm"
					break
				}
				key := b.Inputs[i]
				if old, ok := seen[key]; ok && !closeVector(old, v, s) {
					row.Error = "repeated_input_inconsistent"
					break
				}
				seen[key] = append([]float64(nil), v...)
			}
			if row.Error != "" {
				row.State = "probe_rejected"
			}
		}
		out.Batches = append(out.Batches, row)
		if row.State != "passed" {
			out.State = "failed"
			break
		} // no retry/fallback or quality metrics
	}
	for _, w := range t.calls {
		w.ResponseHash = digest(w.body)
	}
	out.Wire = t.calls
	out.Positions = t.positions
	return out
}

func fakeVector(text string, dimensions int) []float64 {
	sum := sha256.Sum256([]byte(text))
	v := make([]float64, dimensions)
	for i := range v {
		v[i] = 1 + float64(sum[i%len(sum)])/255
	}
	n := norm(v)
	for i := range v {
		v[i] /= n
	}
	return v
}
func fakeServer(dimensions int) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Model string   `json:"model"`
			Input []string `json:"input"`
		}
		if r.Method != http.MethodPost || r.URL.Path != "/v1/embeddings" || json.NewDecoder(io.LimitReader(r.Body, 64<<10)).Decode(&body) != nil {
			http.Error(w, "bad synthetic request", 400)
			return
		}
		items := []map[string]any{}
		for i := len(body.Input) - 1; i >= 0; i-- {
			items = append(items, map[string]any{"index": i, "embedding": fakeVector(body.Input[i], dimensions)})
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"data": items})
	}))
}
func newProvider(base, model string, timeout time.Duration, maxRequests, maxInputs, maxBytes int) (*embedding.HTTPProvider, *tape) {
	transport := &http.Transport{Proxy: nil, DisableKeepAlives: true}
	t := &tape{inner: transport, maxRequests: maxRequests, maxInputs: maxInputs, maxBytes: maxBytes}
	client := &http.Client{Timeout: timeout, Transport: t, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	return embedding.NewHTTPProviderWithClient("", model, base, client), t
}
func validateURL(base string) error {
	u, err := url.Parse(base)
	if err != nil || u == nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return errors.New("base URL needs http(s), no credentials/query/fragment")
	}
	ip := net.ParseIP(u.Hostname())
	if ip == nil || (!ip.IsPrivate() && !ip.IsLoopback()) {
		return errors.New("use a private-network or loopback IP literal")
	}
	return nil
}
func outputDir(path string) (string, error) {
	if path == "" {
		return os.MkdirTemp("", "flh053-probe-")
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}
	// Only task output under /tmp: no source/daily-data output destinations.
	if !strings.HasPrefix(abs, filepath.Join(os.TempDir(), "flh053")) {
		return "", errors.New("output must be a new /tmp/flh053... path")
	}
	parent := filepath.Dir(abs)
	resolved, err := filepath.EvalSymlinks(parent)
	if err != nil {
		return "", err
	}
	if resolved != parent {
		return "", errors.New("output symlink ancestors refused")
	}
	if err := os.Mkdir(abs, 0700); err != nil {
		return "", errors.New("output must not exist")
	}
	return abs, nil
}
func writeNew(path string, data []byte) error {
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = f.Write(data)
	return err
}
func run(args []string, stdout, stderr io.Writer) int {
	f := flag.NewFlagSet("flh053", flag.ContinueOnError)
	f.SetOutput(stderr)
	real := f.Bool("allow-real-endpoint", false, "explicitly contact the supplied private endpoint (plumbing only)")
	base := f.String("base-url", "", "base URL, not the /embeddings URL")
	model := f.String("model", "", "exact wire model/deployment identifier")
	dimensions := f.Int("dimensions", 8, "required expected vector size; candidate e5-base is 768")
	payload := f.String("payload", "plain", "plain or current production rendered synthetic payloads; no prefix adaptation")
	maxRequests := f.Int("max-requests", 5, "HTTP request limit (1..8)")
	maxInputs := f.Int("max-inputs", 16, "input-position limit (1..24)")
	maxBytes := f.Int("max-input-bytes", 2048, "UTF-8 bytes per input (1..4096)")
	timeout := f.Duration("request-timeout", 5*time.Second, "per-request timeout (100ms..30s)")
	overall := f.Duration("timeout", 30*time.Second, "overall timeout (100ms..120s)")
	atol := f.Float64("atol", 1e-5, "coordinate absolute tolerance")
	rtol := f.Float64("rtol", 1e-4, "coordinate relative tolerance")
	unit := f.Bool("require-unit-norm", false, "require L2 norm within norm-tolerance of one")
	normTolerance := f.Float64("norm-tolerance", 1e-3, "absolute unit-norm tolerance")
	outPath := f.String("out", "", "new /tmp/flh053... directory; default creates one")
	if f.Parse(args) != nil || f.NArg() != 0 {
		return 2
	}
	if *maxRequests < 1 || *maxRequests > 8 || *maxInputs < 1 || *maxInputs > 24 || *maxBytes < 1 || *maxBytes > 4096 || *dimensions < 1 || *dimensions > 8192 || *timeout < 100*time.Millisecond || *timeout > 30*time.Second || *overall < 100*time.Millisecond || *overall > 120*time.Second {
		fmt.Fprintln(stderr, "invalid bounded limits/dimensions/timeouts")
		return 2
	}
	for _, v := range []float64{*atol, *rtol, *normTolerance} {
		if math.IsNaN(v) || math.IsInf(v, 0) || v < 0 || v > 0.01 {
			fmt.Fprintln(stderr, "tolerances must be finite in [0,.01]")
			return 2
		}
	}
	inputs, err := fixtures(*payload)
	if err != nil {
		fmt.Fprintln(stderr, "invalid payload")
		return 2
	}
	positions := 0
	for _, b := range inputs {
		positions += len(b.Inputs)
		for _, text := range b.Inputs {
			if len(text) > *maxBytes {
				fmt.Fprintln(stderr, "fixture exceeds input-byte limit")
				return 2
			}
		}
	}
	if len(inputs) > *maxRequests || positions > *maxInputs {
		fmt.Fprintln(stderr, "limits below fixed probe inventory")
		return 2
	}
	if !*real && (*base != "" || *model != "") {
		fmt.Fprintln(stderr, "supplied endpoint/model requires -allow-real-endpoint")
		return 2
	}
	if *real {
		explicit := map[string]bool{}
		f.Visit(func(option *flag.Flag) { explicit[option.Name] = true })
		if validateURL(*base) != nil || strings.TrimSpace(*model) == "" || !explicit["dimensions"] || !explicit["max-requests"] || !explicit["max-inputs"] {
			fmt.Fprintln(stderr, "explicit private base URL, model, dimensions and request/input limits required")
			return 2
		}
	}
	dir, err := outputDir(*outPath)
	if err != nil {
		fmt.Fprintln(stderr, "output rejected")
		return 2
	}
	mode := "offline_local_fake"
	if !*real {
		server := fakeServer(*dimensions)
		defer server.Close()
		*base = server.URL + "/v1/"
		*model = "flh053-sha256-fake-v1"
	} else {
		mode = "explicit_endpoint_plumbing_only"
	}
	p, t := newProvider(*base, *model, *timeout, *maxRequests, *maxInputs, *maxBytes)
	ctx, cancel := context.WithTimeout(context.Background(), *overall)
	defer cancel()
	r := exercise(ctx, p, t, inputs, settings{*dimensions, *atol, *rtol, *unit, *normTolerance})
	r.Mode = mode
	r.Model = *model
	data, err := json.MarshalIndent(r, "", "  ")
	if err != nil {
		fmt.Fprintln(stderr, "cannot encode probe evidence")
		return 2
	}
	data = append(data, '\n')
	if writeNew(filepath.Join(dir, "report.json"), data) != nil {
		fmt.Fprintln(stderr, "cannot save probe evidence")
		return 2
	}
	hashes, _ := json.MarshalIndent(map[string]string{"report.json": digest(data)}, "", "  ")
	if writeNew(filepath.Join(dir, "sha256.json"), append(hashes, '\n')) != nil {
		return 2
	}
	fmt.Fprintf(stdout, "%s: %s; %d request(s), %d positions; plumbing only; report %s\n", mode, r.State, len(t.calls), t.positions, filepath.Join(dir, "report.json"))
	if r.State != "passed" {
		return 1
	}
	return 0
}
func main() { os.Exit(run(os.Args[1:], os.Stdout, os.Stderr)) }
