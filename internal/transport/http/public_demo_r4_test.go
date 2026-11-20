package http_test

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	transporthttp "french-learning-app/internal/transport/http"
)

// R4-WB-035: the routes R4 touched through shared code (Review Today's
// grouping and schedule, the notebook's retry save, captures) never write
// through the public demo boundary, whatever the method or prefix: every
// write is refused before any handler, and the private server reads exactly
// the same queue and records afterwards.
func TestPublicDemo_NoWriteOnRoutesTouchedByR4(t *testing.T) {
	f := newNotebookFixture(t)
	_, a := f.save(t, "demo-boundary-a", ref("listening_item", f.ids["listeningExercise"], 1), "a")
	entry := int64(a["entry_id"].(float64))
	if status, _ := doJSON(t, http.MethodPut, fmt.Sprintf("%s/mistake-notebook/items/%d/retry", f.srv.URL, entry), `{"marked":true}`); status != http.StatusOK {
		t.Fatalf("mark: %d", status)
	}
	snapshot := func() string {
		_, today := doJSON(t, http.MethodGet, f.srv.URL+"/review-today", "")
		_, items := doJSON(t, http.MethodGet, f.srv.URL+"/mistake-notebook/items", "")
		delete(today, "generated_at")
		return fmt.Sprint(today["items"], today["history"], items["items"])
	}
	before := snapshot()

	demo := httptest.NewServer(transporthttp.NewPublicDemoBoundary(f.routes, false))
	t.Cleanup(demo.Close)
	routes := []string{
		"/review-today",
		fmt.Sprintf("/mistake-notebook/items/%d/retry", entry),
		"/mistake-notebook/items",
		"/captures",
		fmt.Sprintf("/entries/%d/source", entry),
		"/knowledge-library/concepts",
		"/knowledge-library/demo",
	}
	body := `{"marked":false,"schema_version":"learning_capture_v1","capture_id":"demo-write","source":"manual","original_input":"x"}`
	for _, prefix := range []string{"", "/api"} {
		for _, p := range routes {
			for _, m := range []string{http.MethodPost, http.MethodPut, http.MethodPatch, http.MethodDelete} {
				req, _ := http.NewRequest(m, demo.URL+prefix+p, strings.NewReader(body))
				req.Header.Set("Content-Type", "application/json")
				res, err := http.DefaultClient.Do(req)
				if err != nil {
					t.Fatal(err)
				}
				res.Body.Close()
				if res.StatusCode != http.StatusMethodNotAllowed && res.StatusCode != http.StatusNotFound {
					t.Errorf("%s %s%s through the demo: %d, want 405 or 404", m, prefix, p, res.StatusCode)
				}
			}
		}
		// The private reads are not on the demo allowlist either.
		for _, p := range []string{"/review-today", "/mistake-notebook/items"} {
			if status, _ := doJSON(t, http.MethodGet, demo.URL+prefix+p, ""); status != http.StatusNotFound {
				t.Errorf("GET %s%s through the demo: %d", prefix, p, status)
			}
		}
	}
	if after := snapshot(); after != before {
		t.Fatalf("a demo request changed private state:\nbefore %s\nafter  %s", before, after)
	}
}
