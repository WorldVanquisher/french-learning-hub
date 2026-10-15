// Command prepare builds and validates the FLH-073 public demo artifact.
//
//	go run ./scripts/demo/flh073/prepare build    -out DIR [-fixtures FILE]
//	go run ./scripts/demo/flh073/prepare validate -artifact DIR [-release]
//	go run ./scripts/demo/flh073/prepare plan     [-fixtures FILE]
//	go run ./scripts/demo/flh073/prepare embed    -work DIR -base-url URL -deployment ID -dimensions N -allow-live
//	go run ./scripts/demo/flh073/prepare status   -work DIR
//	go run ./scripts/demo/flh073/prepare import   -work DIR -out NEW_DIR
//
// plan/embed/status/import (FLH-076) prepare real-model vectors: embed sends
// the exact production texts to an existing E5 service within a persistent,
// bounded budget (at most 64 positions, 16 POSTs, 2 readiness probes per work
// directory) and never resends completed positions; import builds a model
// artifact atomically after full validation.
//
// build seeds a new synthetic database through the real application services
// and computes MECHANICAL test vectors (no model, no network). validate runs
// the server's own loader; -release additionally requires real-model vectors
// and exits 3 with BLOCKED otherwise. Exit codes: 0 ok, 1 failure, 2 usage, 3
// release blocked.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"french-learning-app/internal/publicdemo"
)

const defaultFixtures = "scripts/demo/flh073/fixtures/catalog.json"

func main() { os.Exit(run(os.Args[1:], os.Stdout, os.Stderr)) }

func run(args []string, stdout, stderr io.Writer) int {
	if len(args) == 0 {
		fmt.Fprintln(stderr, "usage: prepare build|validate|plan|embed|status|import (see the package comment)")
		return 2
	}
	switch args[0] {
	case "plan":
		fs := flag.NewFlagSet("plan", flag.ContinueOnError)
		fs.SetOutput(stderr)
		fixtures := fs.String("fixtures", defaultFixtures, "synthetic fixture catalog")
		batch := fs.Int("batch", publicdemo.MaxBatch, "inputs per POST")
		if fs.Parse(args[1:]) != nil || *batch < 1 || *batch > publicdemo.MaxBatch {
			return 2
		}
		plan, err := publicdemo.PlanFromFixtures(context.Background(), *fixtures)
		if err != nil {
			fmt.Fprintln(stderr, "plan failed:", err)
			return 1
		}
		kinds := map[string]int{}
		for _, p := range plan.Positions {
			kinds[p.Kind+"/"+p.Representation+"/"+p.Role]++
		}
		return printJSON(stdout, map[string]any{"plan_sha256": plan.SHA256, "fixtures_sha256": plan.FixturesSHA256,
			"positions": len(plan.Positions), "by_kind": kinds, "posts_at_batch": (len(plan.Positions) + *batch - 1) / *batch,
			"batch": *batch, "limits": map[string]int{"positions": publicdemo.HardMaxPositions, "posts": publicdemo.HardMaxPosts, "probes": publicdemo.HardMaxProbes}})
	case "embed":
		fs := flag.NewFlagSet("embed", flag.ContinueOnError)
		fs.SetOutput(stderr)
		fixtures := fs.String("fixtures", defaultFixtures, "synthetic fixture catalog")
		work := fs.String("work", "", "work directory outside the repository (created, or resumed)")
		base := fs.String("base-url", "", "the E5 service's /v1 base URL")
		deployment := fs.String("deployment", "", "the exact deployment_id the service must report on /manifest")
		dims := fs.Int("dimensions", 0, "vector dimensions")
		batch := fs.Int("batch", publicdemo.MaxBatch, "inputs per POST (1..8)")
		maxPositions := fs.Int("max-positions", publicdemo.HardMaxPositions, "position budget (<= 64)")
		maxPosts := fs.Int("max-posts", publicdemo.HardMaxPosts, "POST budget (<= 16)")
		live := fs.Bool("allow-live", false, "required: this sends synthetic texts to the embedding service")
		if fs.Parse(args[1:]) != nil || *work == "" {
			return 2
		}
		if !*live {
			fmt.Fprintln(stderr, "refused: embed contacts the embedding service; pass -allow-live")
			return 2
		}
		if err := outsideRepository(*work); err != nil {
			fmt.Fprintln(stderr, "refused:", err)
			return 2
		}
		r, err := publicdemo.Embed(context.Background(), *fixtures, *work, publicdemo.EmbedOptions{BaseURL: *base, DeploymentID: *deployment,
			Dimensions: *dims, Batch: *batch, MaxPositions: *maxPositions, MaxPosts: *maxPosts})
		if r != nil {
			printJSON(stdout, r)
		}
		if err != nil {
			fmt.Fprintln(stderr, "embed stopped:", err)
			if errors.Is(err, publicdemo.ErrBudget) {
				return 3
			}
			return 1
		}
		return 0
	case "status":
		fs := flag.NewFlagSet("status", flag.ContinueOnError)
		fs.SetOutput(stderr)
		fixtures := fs.String("fixtures", defaultFixtures, "synthetic fixture catalog")
		work := fs.String("work", "", "work directory")
		if fs.Parse(args[1:]) != nil || *work == "" {
			return 2
		}
		r, st, err := publicdemo.WorkStatus(context.Background(), *fixtures, *work)
		if err != nil {
			fmt.Fprintln(stderr, "invalid:", err)
			return 1
		}
		return printJSON(stdout, map[string]any{"report": r, "deployment_id": st.DeploymentID, "dimensions": st.Dimensions,
			"base_url": st.BaseURL, "probes": st.Probes, "posts": st.Posts})
	case "import":
		fs := flag.NewFlagSet("import", flag.ContinueOnError)
		fs.SetOutput(stderr)
		fixtures := fs.String("fixtures", defaultFixtures, "synthetic fixture catalog")
		work := fs.String("work", "", "complete work directory")
		out := fs.String("out", "", "new artifact directory outside the repository (must not exist)")
		if fs.Parse(args[1:]) != nil || *work == "" || *out == "" {
			return 2
		}
		if err := outsideRepository(*out); err != nil {
			fmt.Fprintln(stderr, "refused:", err)
			return 2
		}
		a, err := publicdemo.Import(context.Background(), *fixtures, *work, *out)
		if err != nil {
			fmt.Fprintln(stderr, "import failed:", err)
			return 1
		}
		return report(stdout, a, true)
	case "build":
		fs := flag.NewFlagSet("build", flag.ContinueOnError)
		fs.SetOutput(stderr)
		out := fs.String("out", "", "new or empty artifact directory outside the repository")
		fixtures := fs.String("fixtures", defaultFixtures, "synthetic fixture catalog")
		if fs.Parse(args[1:]) != nil || *out == "" {
			return 2
		}
		if err := outsideRepository(*out); err != nil {
			fmt.Fprintln(stderr, "refused:", err)
			return 2
		}
		a, err := publicdemo.Build(context.Background(), *fixtures, *out)
		if err != nil {
			fmt.Fprintln(stderr, "build failed:", err)
			return 1
		}
		return report(stdout, a, false)
	case "validate":
		fs := flag.NewFlagSet("validate", flag.ContinueOnError)
		fs.SetOutput(stderr)
		dir := fs.String("artifact", "", "artifact directory")
		release := fs.Bool("release", false, "require real-model vectors (public release)")
		if fs.Parse(args[1:]) != nil || *dir == "" {
			return 2
		}
		a, db, err := publicdemo.OpenArtifact(context.Background(), *dir)
		if err != nil {
			fmt.Fprintln(stderr, "invalid:", err)
			return 1
		}
		db.Close()
		if code := report(stdout, a, *release); code != 0 {
			fmt.Fprintln(stderr, "RELEASE BLOCKED: the artifact's vectors are mechanical test fixtures, not a real model. "+
				"A public release needs vectors produced by a separately authorized real-model run (vectors.json with source \"model\").")
			return code
		}
		return 0
	default:
		fmt.Fprintln(stderr, "unknown command", args[0])
		return 2
	}
}

func printJSON(w io.Writer, v any) int {
	b, _ := json.MarshalIndent(v, "", "  ")
	fmt.Fprintln(w, string(b))
	return 0
}

func report(w io.Writer, a *publicdemo.Artifact, release bool) int {
	m := a.Manifest
	status := "valid (local smoke only: mechanical vectors)"
	code := 0
	if !a.Mechanical() {
		status = "valid (real-model vectors)"
	} else if release {
		status, code = "BLOCKED", 3
	}
	out := map[string]any{
		"status": status, "artifact": a.Dir, "artifact_version": m.ArtifactVersion, "manifest_sha256": a.ManifestSHA256,
		"vector_source": m.Vectors.Source, "real_model": m.Vectors.RealModel, "model_id": m.Vectors.ModelID,
		"dimensions": m.Vectors.Dimensions, "release_status": m.ReleaseStatus, "presets": len(a.Presets),
		"domain_fingerprint": m.DomainFingerprint, "files": m.Files, "notice": m.Notice,
	}
	b, _ := json.MarshalIndent(out, "", "  ")
	fmt.Fprintln(w, string(b))
	return code
}

// outsideRepository refuses output inside this repository, so a database or
// artifact cannot be committed by accident.
func outsideRepository(out string) error {
	abs, err := filepath.Abs(out)
	if err != nil {
		return err
	}
	for dir := filepath.Dir(abs); ; dir = filepath.Dir(dir) {
		if b, err := os.ReadFile(filepath.Join(dir, "go.mod")); err == nil && strings.Contains(string(b), "module french-learning-app") {
			return errors.New("artifact output must be outside the repository (" + dir + ")")
		}
		if dir == filepath.Dir(dir) {
			return nil
		}
	}
}
