// Command prepare builds and validates the FLH-073 public demo artifact.
//
//	go run ./scripts/demo/flh073/prepare build    -out DIR [-fixtures FILE]
//	go run ./scripts/demo/flh073/prepare validate -artifact DIR [-release]
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
		fmt.Fprintln(stderr, "usage: prepare build -out DIR [-fixtures FILE] | validate -artifact DIR [-release]")
		return 2
	}
	switch args[0] {
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
