package publicdemo_test

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"french-learning-app/internal/application"
	"french-learning-app/internal/publicdemo"
)

const fakeDeployment = "fake-e5-test@0/flh_e5_role_prefix_v1/float16/singleton_v1/0000000000000000"

// fakeE5 mimics the E5 service's HTTP contract and role checks, deterministically.
// It is test plumbing: its vectors encode word overlap, not meaning.
type fakeE5 struct {
	mu         sync.Mutex
	dims       int
	notReady   bool
	deployment string
	failPost   int // fail this POST number (1-based) with HTTP 500 after receiving it
	badDims    bool
	posts      int
	readyz     int
	manifests  int
	inputs     map[string]int // text -> times received
}

func newFakeE5(dims int) *fakeE5 {
	return &fakeE5{dims: dims, deployment: fakeDeployment, inputs: map[string]int{}}
}

func (f *fakeE5) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/readyz":
		f.readyz++
		if f.notReady {
			w.WriteHeader(503)
			return
		}
		w.Write([]byte(`{"state":"ready"}`))
	case r.Method == http.MethodGet && r.URL.Path == "/manifest":
		f.manifests++
		json.NewEncoder(w).Encode(map[string]string{"deployment_id": f.deployment, "manifest_sha256": strings.Repeat("ab", 32)})
	case r.Method == http.MethodPost && r.URL.Path == "/v1/embeddings":
		f.posts++
		var req struct {
			Model string   `json:"model"`
			Input []string `json:"input"`
		}
		if json.NewDecoder(r.Body).Decode(&req) != nil || req.Model != f.deployment || len(req.Input) < 1 || len(req.Input) > 32 {
			w.WriteHeader(400)
			return
		}
		var out []map[string]any
		for i, text := range req.Input {
			f.inputs[text]++
			var doc struct {
				Representation string `json:"representation"`
				Type           string `json:"type"`
			}
			if json.Unmarshal([]byte(text), &doc) != nil {
				w.WriteHeader(422)
				return
			}
			prefix := ""
			switch {
			case doc.Representation == "concept_embedding_text_v1" && doc.Type == "concept":
				prefix = "passage: "
			case doc.Representation == "concept_search_query_v2" && doc.Type == "query":
				prefix = "query: "
			default:
				w.WriteHeader(422)
				return
			}
			dims := f.dims
			if f.badDims {
				dims--
			}
			out = append(out, map[string]any{"object": "embedding", "index": i, "embedding": publicdemo.MechanicalEmbed(prefix+text, dims)})
		}
		if f.posts == f.failPost {
			w.WriteHeader(500)
			return
		}
		json.NewEncoder(w).Encode(map[string]any{"object": "list", "model": f.deployment, "data": out})
	default:
		w.WriteHeader(404)
	}
}

func (f *fakeE5) counts() (posts, readyz, positions int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	for _, n := range f.inputs {
		positions += n
	}
	return f.posts, f.readyz, positions
}

func startFake(t *testing.T, f *fakeE5) string {
	t.Helper()
	srv := httptest.NewServer(f)
	t.Cleanup(srv.Close)
	return srv.URL + "/v1"
}

func embedOpts(base string) publicdemo.EmbedOptions {
	return publicdemo.EmbedOptions{BaseURL: base, DeploymentID: fakeDeployment, Dimensions: 32}
}

func TestPlan_ExactProductionTextsAndRoles(t *testing.T) {
	plan, err := publicdemo.PlanFromFixtures(context.Background(), fixturePath)
	if err != nil {
		t.Fatal(err)
	}
	if len(plan.Positions) != 20 {
		t.Fatalf("positions = %d", len(plan.Positions))
	}
	docs, presets := 0, 0
	for _, p := range plan.Positions {
		var probe struct {
			Representation string `json:"representation"`
			Type           string `json:"type"`
			Text           string `json:"text"`
		}
		if err := json.Unmarshal([]byte(p.Text), &probe); err != nil {
			t.Fatal(err)
		}
		switch p.Kind {
		case "document":
			docs++
			if p.Role != "passage" || probe.Representation != application.ConceptIndexRepresentationV1 || probe.Type != "concept" {
				t.Fatalf("document %s: %+v", p.Key, probe)
			}
		case "preset":
			presets++
			want, _ := application.ConceptSearchQueryEmbeddingText(probe.Text)
			if p.Role != "query" || p.Text != want || probe.Representation != application.ConceptSearchQueryRepresentationV2 {
				t.Fatalf("preset %s: %q", p.Key, p.Text)
			}
		}
	}
	if docs != 12 || presets != 8 {
		t.Fatalf("docs %d presets %d", docs, presets)
	}
	again, _ := publicdemo.PlanFromFixtures(context.Background(), fixturePath)
	if again.SHA256 != plan.SHA256 {
		t.Fatal("plan is not reproducible")
	}
}

func TestEmbedImport_FullPipelineProducesAValidModelArtifact(t *testing.T) {
	fake := newFakeE5(32)
	base := startFake(t, fake)
	work := filepath.Join(t.TempDir(), "work")
	r, err := publicdemo.Embed(context.Background(), fixturePath, work, embedOpts(base))
	if err != nil {
		t.Fatal(err)
	}
	posts, readyz, positions := fake.counts()
	if r.Completed != 20 || r.Pending != 0 || r.SentPosts != 3 || posts != 3 || readyz != 1 || positions != 20 ||
		r.Accounting.UsedPosts != 3 || r.Accounting.UsedPositions != 20 || r.Accounting.UsedProbes != 1 {
		t.Fatalf("report %+v; fake posts %d readyz %d positions %d", r, posts, readyz, positions)
	}
	// A repeat sends nothing and does not even probe.
	if r, err := publicdemo.Embed(context.Background(), fixturePath, work, embedOpts(base)); err != nil || r.SentPosts != 0 || r.Probed {
		t.Fatalf("repeat: %+v %v", r, err)
	}
	if p, z, _ := fake.counts(); p != 3 || z != 1 {
		t.Fatal("a complete work directory must not contact the service")
	}
	out := filepath.Join(t.TempDir(), "artifact")
	a, err := publicdemo.Import(context.Background(), fixturePath, work, out)
	if err != nil {
		t.Fatal(err)
	}
	m := a.Manifest
	if a.Mechanical() || !m.Vectors.RealModel || m.Vectors.Source != "model" || m.Vectors.ModelID != fakeDeployment ||
		m.Vectors.Generator != publicdemo.ModelGenerator || m.ReleaseStatus != publicdemo.ReleaseModelVectors || len(m.Files) != 4 {
		t.Fatalf("manifest = %+v", m)
	}
	_, db, err := publicdemo.OpenArtifact(context.Background(), out)
	if err != nil {
		t.Fatal(err)
	}
	db.Close()
	// The model artifact serves preset vectors with no network capability at all.
	pv := publicdemo.NewPresetQueryVectors(a)
	env, _ := application.ConceptSearchQueryEmbeddingText(a.Presets[0].Text)
	if v, err := pv.Embed(context.Background(), []string{env}); err != nil || len(v[0]) != 32 {
		t.Fatalf("preset lookup: %v", err)
	}
	if _, err := pv.Embed(context.Background(), []string{`{"representation":"concept_search_query_v2","type":"query","text":"free"}`}); err == nil {
		t.Fatal("free text must be refused")
	}
	if p, _, _ := fake.counts(); p != 3 {
		t.Fatal("serving must not call the service")
	}
	// Same fixtures, same domain: the fingerprint equals the mechanical artifact's.
	mech, err := publicdemo.LoadArtifact(buildArtifact(t))
	if err != nil {
		t.Fatal(err)
	}
	if mech.Manifest.DomainFingerprint.SHA256 != m.DomainFingerprint.SHA256 {
		t.Fatal("model and mechanical artifacts must share the domain fingerprint")
	}
	if _, err := os.Stat(out + ".partial"); err == nil {
		t.Fatal("partial directory left behind")
	}
	entries, _ := os.ReadDir(filepath.Dir(out))
	for _, e := range entries {
		if strings.Contains(e.Name(), ".partial-") {
			t.Fatalf("partial directory left behind: %s", e.Name())
		}
	}
}

func TestEmbed_FailureStopsAndResumeNeverResendsCompletedPositions(t *testing.T) {
	fake := newFakeE5(32)
	fake.failPost = 2
	base := startFake(t, fake)
	work := filepath.Join(t.TempDir(), "work")
	r, err := publicdemo.Embed(context.Background(), fixturePath, work, embedOpts(base))
	if err == nil || r.Completed != 8 || r.SentPosts != 2 {
		t.Fatalf("first run: %+v %v", r, err)
	}
	plan, _ := publicdemo.PlanFromFixtures(context.Background(), fixturePath)
	firstBatch := plan.Positions[:8]
	fake.failPost = 0
	r, err = publicdemo.Embed(context.Background(), fixturePath, work, embedOpts(base))
	if err != nil || r.Completed != 20 || r.SentPositions != 12 || r.SentPosts != 2 {
		t.Fatalf("resume: %+v %v", r, err)
	}
	for _, p := range firstBatch {
		if fake.inputs[p.Text] != 1 {
			t.Fatalf("%s was sent %d times; completed receipts must not be resent", p.Key, fake.inputs[p.Text])
		}
	}
	// Accounting: 4 POSTs charged (1 ok, 1 failed, 2 ok), 28 positions, 2 probes.
	status, st, err := publicdemo.WorkStatus(context.Background(), fixturePath, work)
	if err != nil {
		t.Fatal(err)
	}
	if status.Accounting.UsedPosts != 4 || status.Accounting.UsedPositions != 28 || status.Accounting.UsedProbes != 2 {
		t.Fatalf("accounting = %+v", status.Accounting)
	}
	if st.Posts[1].Outcome != "failed" || !strings.Contains(st.Posts[1].Error, "HTTP 500") {
		t.Fatalf("failed post record = %+v", st.Posts[1])
	}
	out := filepath.Join(t.TempDir(), "artifact")
	if _, err := publicdemo.Import(context.Background(), fixturePath, work, out); err != nil {
		t.Fatal(err)
	}
}

func TestEmbed_BudgetAndProbeRefusalsSendNothing(t *testing.T) {
	ctx := context.Background()
	// 20 positions at batch 8 need 3 POSTs: a 2-POST limit is refused up front.
	fake := newFakeE5(32)
	base := startFake(t, fake)
	opts := embedOpts(base)
	opts.MaxPosts = 2
	if _, err := publicdemo.Embed(ctx, fixturePath, filepath.Join(t.TempDir(), "w1"), opts); !errors.Is(err, publicdemo.ErrBudget) {
		t.Fatalf("posts budget: %v", err)
	}
	opts = embedOpts(base)
	opts.MaxPositions = 19
	if _, err := publicdemo.Embed(ctx, fixturePath, filepath.Join(t.TempDir(), "w2"), opts); !errors.Is(err, publicdemo.ErrBudget) {
		t.Fatalf("positions budget: %v", err)
	}
	if p, z, n := fake.counts(); p != 0 || z != 0 || n != 0 {
		t.Fatalf("budget refusals must contact nothing: %d %d %d", p, z, n)
	}
	for _, bad := range []publicdemo.EmbedOptions{
		{BaseURL: base, DeploymentID: fakeDeployment, Dimensions: 32, MaxPositions: 65},
		{BaseURL: base, DeploymentID: fakeDeployment, Dimensions: 32, MaxPosts: 17},
		{BaseURL: base, DeploymentID: fakeDeployment, Dimensions: 32, Batch: 9},
		{BaseURL: strings.TrimSuffix(base, "/v1"), DeploymentID: fakeDeployment, Dimensions: 32},
		{BaseURL: base, Dimensions: 32},
	} {
		if _, err := publicdemo.Embed(ctx, fixturePath, filepath.Join(t.TempDir(), "w"), bad); err == nil {
			t.Fatalf("options must be refused: %+v", bad)
		}
	}
	// Not ready: one probe is charged, no POST. Wrong deployment: same.
	fake.notReady = true
	work := filepath.Join(t.TempDir(), "w3")
	if _, err := publicdemo.Embed(ctx, fixturePath, work, embedOpts(base)); err == nil {
		t.Fatal("not ready must fail")
	}
	fake.notReady = false
	fake.deployment = "another-deployment"
	if _, err := publicdemo.Embed(ctx, fixturePath, work, embedOpts(base)); err == nil || !strings.Contains(err.Error(), "deployment_mismatch") {
		t.Fatalf("deployment mismatch: %v", err)
	}
	// Probe budget (2) is now used up: a third run is refused before any request.
	fake.deployment = fakeDeployment
	_, readyBefore, _ := fake.counts()
	if _, err := publicdemo.Embed(ctx, fixturePath, work, embedOpts(base)); !errors.Is(err, publicdemo.ErrBudget) {
		t.Fatalf("probe budget: %v", err)
	}
	if p, z, _ := fake.counts(); p != 0 || z != readyBefore {
		t.Fatalf("no POST and no further probe expected: posts %d readyz %d", p, z)
	}
	// Changing the deployment or dimensions of a started work directory is refused.
	other := embedOpts(base)
	other.Dimensions = 16
	if _, err := publicdemo.Embed(ctx, fixturePath, work, other); !errors.Is(err, publicdemo.ErrWorkState) {
		t.Fatalf("changed dimensions: %v", err)
	}
}

func TestEmbed_InvalidVectorsAreNeverRecorded(t *testing.T) {
	fake := newFakeE5(32)
	fake.badDims = true
	base := startFake(t, fake)
	work := filepath.Join(t.TempDir(), "work")
	r, err := publicdemo.Embed(context.Background(), fixturePath, work, embedOpts(base))
	if err == nil || r.Completed != 0 || r.SentPosts != 1 {
		t.Fatalf("bad dims: %+v %v", r, err)
	}
	_, st, _ := publicdemo.WorkStatus(context.Background(), fixturePath, work)
	if len(st.Receipts) != 0 || st.Posts[0].Outcome != "failed" {
		t.Fatalf("no receipt may be written: %+v", st)
	}
	if _, err := publicdemo.Import(context.Background(), fixturePath, work, filepath.Join(t.TempDir(), "a")); err == nil {
		t.Fatal("an incomplete work directory must not import")
	}
}

func completeWork(t *testing.T) string {
	t.Helper()
	work := filepath.Join(t.TempDir(), "work")
	if _, err := publicdemo.Embed(context.Background(), fixturePath, work, embedOpts(startFake(t, newFakeE5(32)))); err != nil {
		t.Fatal(err)
	}
	return work
}

func TestImport_RefusesIncompleteMismatchedOrCorruptedInputs(t *testing.T) {
	ctx := context.Background()
	editState := func(t *testing.T, work string, edit func(st map[string]any)) {
		var st map[string]any
		readJSON(t, filepath.Join(work, publicdemo.WorkStateFile), &st)
		edit(st)
		writeJSON(t, filepath.Join(work, publicdemo.WorkStateFile), st)
	}
	receipts := func(st map[string]any) map[string]any { return st["receipts"].(map[string]any) }
	cases := map[string]func(t *testing.T, work string){
		"missing receipt": func(t *testing.T, work string) {
			editState(t, work, func(st map[string]any) { delete(receipts(st), "preset:although") })
		},
		"vector changed, hash kept": func(t *testing.T, work string) {
			editState(t, work, func(st map[string]any) {
				r := receipts(st)["concept:1"].(map[string]any)
				r["vector"].([]any)[0] = 0.5
			})
		},
		"receipt for another text": func(t *testing.T, work string) {
			editState(t, work, func(st map[string]any) {
				receipts(st)["concept:2"].(map[string]any)["text_sha256"] = strings.Repeat("0", 64)
			})
		},
		"receipt from another deployment": func(t *testing.T, work string) {
			editState(t, work, func(st map[string]any) { receipts(st)["concept:3"].(map[string]any)["deployment_id"] = "other" })
		},
		"extra receipt": func(t *testing.T, work string) {
			editState(t, work, func(st map[string]any) { receipts(st)["preset:extra"] = receipts(st)["preset:although"] })
		},
		"post marked failed": func(t *testing.T, work string) {
			editState(t, work, func(st map[string]any) { st["posts"].([]any)[0].(map[string]any)["outcome"] = "failed" })
		},
		"plan from other fixtures": func(t *testing.T, work string) {
			var p map[string]any
			readJSON(t, filepath.Join(work, publicdemo.PlanFile), &p)
			p["sha256"] = strings.Repeat("1", 64)
			writeJSON(t, filepath.Join(work, publicdemo.PlanFile), p)
		},
		"corrupt state": func(t *testing.T, work string) {
			os.WriteFile(filepath.Join(work, publicdemo.WorkStateFile), []byte("{"), 0o644)
		},
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			work := completeWork(t)
			mutate(t, work)
			out := filepath.Join(t.TempDir(), "artifact")
			if _, err := publicdemo.Import(ctx, fixturePath, work, out); err == nil {
				t.Fatal("import must be refused")
			}
			if _, err := os.Stat(out); err == nil {
				t.Fatal("no artifact directory may be published")
			}
		})
	}
	// An existing output directory is never reused, even if empty.
	work := completeWork(t)
	existing := t.TempDir()
	if _, err := publicdemo.Import(ctx, fixturePath, work, existing); err == nil {
		t.Fatal("import must build a new directory")
	}
}

func TestModelArtifact_ProvenanceMustBindEveryVector(t *testing.T) {
	work := completeWork(t)
	good := filepath.Join(t.TempDir(), "artifact")
	if _, err := publicdemo.Import(context.Background(), fixturePath, work, good); err != nil {
		t.Fatal(err)
	}
	mutateProvenance := func(t *testing.T, dir string, edit func(p map[string]any)) {
		var p map[string]any
		readJSON(t, filepath.Join(dir, publicdemo.ProvenanceFile), &p)
		edit(p)
		writeJSON(t, filepath.Join(dir, publicdemo.ProvenanceFile), p)
		rehash(t, dir, publicdemo.ProvenanceFile)
	}
	positions := func(p map[string]any) []any { return p["positions"].([]any) }
	cases := map[string]func(t *testing.T, dir string){
		"provenance missing": func(t *testing.T, dir string) {
			os.Remove(filepath.Join(dir, publicdemo.ProvenanceFile))
		},
		"vector hash mismatch": func(t *testing.T, dir string) {
			mutateProvenance(t, dir, func(p map[string]any) { positions(p)[0].(map[string]any)["vector_sha256"] = strings.Repeat("0", 64) })
		},
		"role swapped": func(t *testing.T, dir string) {
			mutateProvenance(t, dir, func(p map[string]any) { positions(p)[0].(map[string]any)["role"] = "query" })
		},
		"position dropped": func(t *testing.T, dir string) {
			mutateProvenance(t, dir, func(p map[string]any) { p["positions"] = positions(p)[1:] })
		},
		"other deployment": func(t *testing.T, dir string) {
			mutateProvenance(t, dir, func(p map[string]any) { p["deployment_id"] = "other" })
		},
		"no successful probe": func(t *testing.T, dir string) {
			mutateProvenance(t, dir, func(p map[string]any) { p["probes"].([]any)[0].(map[string]any)["outcome"] = "not_ready" })
		},
		"budget exceeded": func(t *testing.T, dir string) {
			mutateProvenance(t, dir, func(p map[string]any) { p["accounting"].(map[string]any)["max_posts"] = 40 })
		},
		"vector changed with matching vectors.json hash": func(t *testing.T, dir string) {
			var v publicdemo.Vectors
			readJSON(t, filepath.Join(dir, publicdemo.VectorsFile), &v)
			v.Documents[0].Vector[0] = -v.Documents[0].Vector[0]
			writeJSON(t, filepath.Join(dir, publicdemo.VectorsFile), v)
			rehash(t, dir, publicdemo.VectorsFile)
		},
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			dir := copyDir(t, good)
			mutate(t, dir)
			if _, err := publicdemo.LoadArtifact(dir); !errors.Is(err, publicdemo.ErrArtifact) {
				t.Fatalf("want ErrArtifact, got %v", err)
			}
		})
	}
	// Relabelling a mechanical artifact, even with a fabricated provenance file, fails.
	mech := copyDir(t, buildArtifact(t))
	var m publicdemo.Manifest
	readJSON(t, filepath.Join(mech, publicdemo.ManifestFile), &m)
	m.Vectors.Source, m.Vectors.RealModel, m.Vectors.Generator = "model", true, publicdemo.ModelGenerator
	m.ReleaseStatus = publicdemo.ReleaseModelVectors
	b, _ := os.ReadFile(filepath.Join(good, publicdemo.ProvenanceFile))
	os.WriteFile(filepath.Join(mech, publicdemo.ProvenanceFile), b, 0o644)
	sum, _ := publicdemo.SHA256File(filepath.Join(mech, publicdemo.ProvenanceFile))
	m.Files[publicdemo.ProvenanceFile] = sum
	writeJSON(t, filepath.Join(mech, publicdemo.ManifestFile), m)
	var v publicdemo.Vectors
	readJSON(t, filepath.Join(mech, publicdemo.VectorsFile), &v)
	v.Identity = m.Vectors
	writeJSON(t, filepath.Join(mech, publicdemo.VectorsFile), v)
	rehash(t, mech, publicdemo.VectorsFile)
	if _, err := publicdemo.LoadArtifact(mech); !errors.Is(err, publicdemo.ErrArtifact) {
		t.Fatalf("relabelled mechanical artifact: %v", err)
	}
}
