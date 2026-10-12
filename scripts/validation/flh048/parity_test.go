package main

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// TestConverterParity_AgainstProductionThroughOverlay runs the build-tagged
// TestFLH052ConverterParity in a child `go test` whose -overlay adds a virtual
// bridge (testdata/production_bridge.go.txt) to internal/application. The
// bridge calls the actual unexported toConceptRetrievalQuery and
// toConceptRetrievalDocument, so a drift between them and the runner's mirrors
// fails this ordinary test. Nothing is written outside a temporary directory.
func TestConverterParity_AgainstProductionThroughOverlay(t *testing.T) {
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	root, err := findRepoRoot(cwd)
	if err != nil {
		t.Fatal(err)
	}
	bridge, err := filepath.Abs(filepath.Join("testdata", "production_bridge.go.txt"))
	if err != nil {
		t.Fatal(err)
	}
	virtual := filepath.Join(root, "internal", "application", "flh052_parity_bridge.go")
	if _, err := os.Stat(virtual); err == nil {
		t.Fatalf("%s exists on disk; the bridge must stay virtual", virtual)
	}
	overlay := filepath.Join(t.TempDir(), "overlay.json")
	raw, _ := json.Marshal(map[string]any{"Replace": map[string]string{virtual: bridge}})
	if err := os.WriteFile(overlay, raw, 0o600); err != nil {
		t.Fatal(err)
	}
	// The toolchain that built this test, not whatever `go` is first on PATH.
	goBin := filepath.Join(runtime.GOROOT(), "bin", "go")
	if _, err := os.Stat(goBin); err != nil {
		if goBin, err = exec.LookPath("go"); err != nil {
			t.Fatal("go toolchain not found")
		}
	}
	cmd := exec.Command(goBin, "test", "-tags", "flh052parity", "-overlay", overlay, "-count=1", "-v",
		"-run", "^TestFLH052ConverterParity$", ".")
	cmd.Dir = cwd
	out, err := cmd.CombinedOutput()
	if err != nil || !strings.Contains(string(out), "--- PASS: TestFLH052ConverterParity") {
		t.Fatalf("converter parity against production failed (%v):\n%s", err, out)
	}
	if _, err := os.Stat(virtual); err == nil {
		t.Fatalf("%s was written to disk", virtual)
	}
}
