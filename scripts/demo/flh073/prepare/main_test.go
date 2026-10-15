package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"french-learning-app/internal/publicdemo"
)

const testDeployment = "fake-e5-cli@0/flh_e5_role_prefix_v1/float16/singleton_v1/0000000000000000"

func fakeService(t *testing.T) (*httptest.Server, *int) {
	posts := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/readyz":
			w.Write([]byte("{}"))
		case "/manifest":
			json.NewEncoder(w).Encode(map[string]string{"deployment_id": testDeployment, "manifest_sha256": strings.Repeat("cd", 32)})
		case "/v1/embeddings":
			posts++
			var req struct{ Input []string }
			json.NewDecoder(r.Body).Decode(&req)
			var data []map[string]any
			for i, text := range req.Input {
				data = append(data, map[string]any{"index": i, "embedding": publicdemo.MechanicalEmbed(text, 16)})
			}
			json.NewEncoder(w).Encode(map[string]any{"data": data})
		}
	}))
	t.Cleanup(srv.Close)
	return srv, &posts
}

func cli(args ...string) (int, string, string) {
	var out, errb bytes.Buffer
	code := run(args, &out, &errb)
	return code, out.String(), errb.String()
}

func TestCLI_EmbedImportValidateRelease(t *testing.T) {
	fixtures := "../fixtures/catalog.json"
	srv, posts := fakeService(t)
	work := filepath.Join(t.TempDir(), "work")
	args := []string{"embed", "-fixtures", fixtures, "-work", work, "-base-url", srv.URL + "/v1", "-deployment", testDeployment, "-dimensions", "16"}
	if code, _, _ := cli(args...); code != 2 {
		t.Fatal("embed without -allow-live must be refused")
	}
	if *posts != 0 {
		t.Fatal("nothing may be sent without -allow-live")
	}
	if code, _, errs := cli(append(args, "-allow-live", "-max-posts", "2")...); code != 3 || *posts != 0 {
		t.Fatalf("budget refusal: %d %s", code, errs)
	}
	work2 := filepath.Join(t.TempDir(), "work2")
	args[4] = work2
	if code, out, errs := cli(append(args, "-allow-live")...); code != 0 || *posts != 3 || !strings.Contains(out, `"completed": 20`) {
		t.Fatalf("embed: %d %s %s", code, out, errs)
	}
	if code, out, _ := cli("status", "-fixtures", fixtures, "-work", work2); code != 0 || !strings.Contains(out, `"pending": 0`) {
		t.Fatalf("status: %d %s", code, out)
	}
	art := filepath.Join(t.TempDir(), "artifact")
	if code, out, errs := cli("import", "-fixtures", fixtures, "-work", work2, "-out", art); code != 0 || !strings.Contains(out, `"real_model": true`) {
		t.Fatalf("import: %d %s %s", code, out, errs)
	}
	if code, _, errs := cli("validate", "-artifact", art, "-release"); code != 0 {
		t.Fatalf("model artifact release validation: %d %s", code, errs)
	}
	if code, _, _ := cli("import", "-fixtures", fixtures, "-work", work2, "-out", art); code != 1 {
		t.Fatal("import into an existing directory must fail")
	}
	mech := filepath.Join(t.TempDir(), "mech")
	if code, _, _ := cli("build", "-fixtures", fixtures, "-out", mech); code != 0 {
		t.Fatal("build")
	}
	if code, _, errs := cli("validate", "-artifact", mech, "-release"); code != 3 || !strings.Contains(errs, "RELEASE BLOCKED") {
		t.Fatalf("mechanical release validation must be blocked: %d %s", code, errs)
	}
}
