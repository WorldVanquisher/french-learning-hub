package http_test

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"testing"

	"french-learning-app/internal/domain"
)

// FLH-090: learning-record text search and the opt-in paged review queue.

func getRaw(t *testing.T, u string) (int, map[string]json.RawMessage) {
	t.Helper()
	resp, err := http.Get(u)
	if err != nil {
		t.Fatalf("GET %s: %v", u, err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	var out map[string]json.RawMessage
	if err := json.Unmarshal(body, &out); err != nil {
		t.Fatalf("GET %s: decode %q: %v", u, body, err)
	}
	return resp.StatusCode, out
}

func keys(m map[string]json.RawMessage) []string {
	var out []string
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func TestIntegration_LearningRecordsTextSearch(t *testing.T) {
	srv := setupServer(t)
	post := func(input, context string) int64 {
		body, _ := json.Marshal(map[string]string{"original_input": input, "original_context": context})
		resp, err := http.Post(srv.URL+"/entries", "application/json", bytes.NewReader(body))
		if err != nil {
			t.Fatal(err)
		}
		var e struct {
			ID int64 `json:"id"`
		}
		decodeBody(t, resp, &e)
		return e.ID
	}
	a := post("Bien que + subjonctif ?", "")
	post("autre chose", "")
	c := post("question", "Contexte : SUBJONCTIF imparfait à 50%")
	ids := func(q string) []int64 {
		status, body := getRaw(t, srv.URL+"/learning-records?"+q)
		if status != http.StatusOK {
			t.Fatalf("%s: status %d", q, status)
		}
		var recs []struct {
			EntryID int64 `json:"entry_id"`
		}
		json.Unmarshal(body["records"], &recs)
		var out []int64
		for _, r := range recs {
			out = append(out, r.EntryID)
		}
		return out
	}
	if got := ids("q=" + url.QueryEscape("subjonctif")); len(got) != 2 || got[0] != c || got[1] != a {
		t.Fatalf("q=subjonctif: %v, want [%d %d]", got, c, a)
	}
	if got := ids("q=" + url.QueryEscape("50%")); len(got) != 1 || got[0] != c {
		t.Fatalf("q=50%%: %v", got)
	}
	if got := ids("q=" + url.QueryEscape("%")); len(got) != 1 {
		t.Fatalf("q=%%: %v, want only the record containing %%", got)
	}
	if got := ids("q=" + url.QueryEscape("   ")); len(got) != 3 {
		t.Fatalf("blank q must not filter: %v", got)
	}
	if got := ids("q=subjonctif&limit=1"); len(got) != 1 || got[0] != c {
		t.Fatalf("q with limit: %v", got)
	}
	status, body := getRaw(t, srv.URL+"/learning-records?q="+strings.Repeat("a", 201))
	if status != http.StatusBadRequest || !strings.Contains(string(body["error"]), "200 characters") {
		t.Fatalf("201-character q: %d %s", status, body["error"])
	}
	if status, _ := getRaw(t, srv.URL+"/learning-records?q="+strings.Repeat("é", 200)); status != http.StatusOK {
		t.Fatalf("200-character q: %d", status)
	}
}

func TestIntegration_ReviewableUnitsPagedContract(t *testing.T) {
	srv, entryID := setupConceptServer(t, []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "a", Statement: "A", Confidence: 0.9},
		{Kind: domain.KindGrammar, Canonical: "b", Statement: "B", Confidence: 0.9},
		{Kind: domain.KindGrammar, Canonical: "c", Statement: "C", Confidence: 0.9},
	})
	units := extractUnits(t, srv, entryID)

	// Legacy request: byte-compatible shape, one key, no entry_id on items.
	status, legacy := getRaw(t, srv.URL+"/reviewable-units")
	if status != http.StatusOK || strings.Join(keys(legacy), ",") != "reviewable_units" {
		t.Fatalf("legacy shape: %d %v", status, keys(legacy))
	}
	var legacyItems []map[string]json.RawMessage
	json.Unmarshal(legacy["reviewable_units"], &legacyItems)
	if len(legacyItems) != 3 || legacyItems[0]["entry_id"] != nil {
		t.Fatalf("legacy items: %d, entry_id present=%v", len(legacyItems), legacyItems[0]["entry_id"] != nil)
	}

	type item struct {
		UnitID  int64 `json:"unit_id"`
		EntryID int64 `json:"entry_id"`
	}
	page := func(q string) (int, []item, *string, int) {
		status, body := getRaw(t, srv.URL+"/reviewable-units?"+q)
		var items []item
		var next *string
		var limit int
		json.Unmarshal(body["reviewable_units"], &items)
		json.Unmarshal(body["next_cursor"], &next)
		json.Unmarshal(body["limit"], &limit)
		return status, items, next, limit
	}
	status, p1, next, limit := page("limit=2")
	if status != 200 || len(p1) != 2 || p1[0].UnitID != units[0] || p1[1].UnitID != units[1] || p1[0].EntryID != entryID || next == nil || limit != 2 {
		t.Fatalf("page 1: %d %+v next=%v limit=%d", status, p1, next, limit)
	}
	status, p2, next2, _ := page("limit=2&after=" + url.QueryEscape(*next))
	if status != 200 || len(p2) != 1 || p2[0].UnitID != units[2] || next2 != nil {
		t.Fatalf("page 2: %d %+v next=%v", status, p2, next2)
	}
	// Entry-scoped paging and the from_unit_id locator.
	status, scoped, _, _ := page("entry_id=" + itoa(entryID) + "&from_unit_id=" + itoa(units[1]))
	if status != 200 || len(scoped) != 2 || scoped[0].UnitID != units[1] {
		t.Fatalf("scoped from: %d %+v", status, scoped)
	}
	// Limit bounds: default and clamp.
	if _, _, _, l := page("limit=0"); l != 50 {
		t.Fatalf("limit=0 applied %d, want default 50", l)
	}
	if _, _, _, l := page("limit=100000"); l != 200 {
		t.Fatalf("limit clamp applied %d, want 200", l)
	}
	for q, want := range map[string]int{
		"limit=abc":                  http.StatusBadRequest,
		"after=1.2":                  http.StatusBadRequest,
		"after=a.b.c":                http.StatusBadRequest,
		"after=1.0.0":                http.StatusBadRequest,
		"after=1.0.1&from_unit_id=1": http.StatusBadRequest,
		"from_unit_id=0":             http.StatusBadRequest,
		"from_unit_id=999999":        http.StatusNotFound,
		"entry_id=999999&limit=5":    http.StatusNotFound,
		"entry_id=" + itoa(entryID+1000) + "&from_unit_id=" + itoa(units[0]): http.StatusNotFound,
	} {
		if status, _, _, _ := page(q); status != want {
			t.Errorf("%s: status %d, want %d", q, status, want)
		}
	}
}
