package http_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"french-learning-app/internal/domain"
)

// Revision studio (ARCHITECTURE.md §4.3): history, block comparison of any two
// stored revisions, and a previewed restore that appends a revision. Every
// case runs on its own disposable database with fixture packs built from the
// embedded one; nothing calls a provider.

// secondU05 is a third content for ls-wb1-u05: the same uncited line as in
// earlierU05, with another ending.
func secondU05(t *testing.T) domain.ListeningScriptPack {
	t.Helper()
	pack := embeddedScripts(t)
	sc := &pack.Scripts[u05]
	sc.Lines[uncitedLine(t, *sc)].Text += " Bon, à demain !"
	if err := domain.ValidateListeningScript(sc); err != nil {
		t.Fatalf("second fixture is invalid: %v", err)
	}
	return pack
}

func restoreBody(from, revision any, fingerprint any) string {
	raw, _ := json.Marshal(map[string]any{"from_revision": from, "revision": revision, "fingerprint": fingerprint})
	return string(raw)
}

func postRestore(t *testing.T, url, id, body string) (int, map[string]any, string) {
	t.Helper()
	req, _ := http.NewRequest(http.MethodPost, url+"/listening/materials/"+id+"/restore", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out map[string]any
	_ = json.NewDecoder(resp.Body).Decode(&out)
	return resp.StatusCode, out, resp.Header.Get("Idempotency-Replayed")
}

func revisionsOf(t *testing.T, url, id string) []map[string]any {
	t.Helper()
	status, body := doJSON(t, http.MethodGet, url+"/listening/materials/"+id+"/revisions", "")
	if status != http.StatusOK {
		t.Fatalf("revisions: %d %v", status, body)
	}
	var out []map[string]any
	for _, r := range body["revisions"].([]any) {
		out = append(out, r.(map[string]any))
	}
	return out
}

func wordSides(block map[string]any) (before, after string) {
	for _, w := range block["words"].([]any) {
		e := w.(map[string]any)
		if e["op"] != domain.WordInserted {
			before += e["text"].(string)
		}
		if e["op"] != domain.WordRemoved {
			after += e["text"].(string)
		}
	}
	return
}

// History, comparison and restore on one database: three revisions from
// three packs, notebook records on revision 1, a restore that appends
// revision 4, a resend that replays, and a second editor whose preview went
// stale and is refused with a fresh one.
func TestRevisionStudio_HistoryCompareRestoreAndTwoEditors(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "studio.db")
	earlier, changedLine := earlierU05(t)

	// Revision 1 under the earlier pack, with two saved mistakes (one marked).
	s1, db := buildRevisionServer(t, dbPath, earlier)
	_, lesson, _ := postScript(t, s1, "ls-wb1-u05")
	id := materialOf(t, lesson)
	ex1 := lesson["current_exercise_id"].(float64)
	_, saved := saveMistake(t, s1, "studio-l04", ex1, 4, "Parce qu'il est moins cher")
	saveMistake(t, s1, "studio-l02", ex1, 2, "")
	marked := notebookItem(t, s1, "studio-l04")["entry_id"].(float64)
	if status, _ := doJSON(t, http.MethodPut, s1.URL+"/mistake-notebook/items/"+itoa(int64(marked))+"/retry", `{"marked":true}`); status != http.StatusOK {
		t.Fatalf("mark: %d", status)
	}
	_ = saved
	s1.Close()

	// Revision 2 under a second pack, revision 3 under the current one.
	confirm := func(s *httptest.Server) {
		_, preview := doJSON(t, http.MethodGet, s.URL+"/listening/materials/"+id+"/script-update", "")
		if status, body, _ := postUpdate(t, s, id, confirmBody(preview["current_revision"], preview["pack_fingerprint"])); status != http.StatusCreated {
			t.Fatalf("update: %d %v", status, body)
		}
	}
	s2, _ := buildRevisionServer(t, dbPath, secondU05(t))
	confirm(s2)
	s2.Close()
	srv, _ := buildRevisionServer(t, dbPath, embeddedScripts(t))
	confirm(srv)

	// History: what belongs to each revision.
	revs := revisionsOf(t, srv.URL, id)
	if len(revs) != 3 || revs[2]["current"] != true || revs[0]["current"] != false {
		t.Fatalf("history: %v", revs)
	}
	for _, r := range revs {
		if r["audio"] != "none" || r["generator"] != domain.ListeningAuthoredGenerator || r["lines"].(float64) < 5 || r["questions"].(float64) < 4 {
			t.Fatalf("revision metadata: %v", r)
		}
	}
	if revs[0]["exercise_id"] != ex1 || revs[0]["exercise_id"] == revs[2]["exercise_id"] {
		t.Fatalf("exercises: %v %v", revs[0]["exercise_id"], revs[2]["exercise_id"])
	}
	linked := revs[0]["linked_records"].([]any)
	if len(linked) != 2 || len(revs[2]["linked_records"].([]any)) != 0 {
		t.Fatalf("linked records: %v / %v", linked, revs[2]["linked_records"])
	}
	inToday := 0
	for _, l := range linked {
		if l.(map[string]any)["in_review_today"] == true {
			inToday++
		}
	}
	if inToday != 1 {
		t.Fatalf("records in Review Today: %v", linked)
	}

	// Compare 1 → 3: every line in order; the one changed line's words rebuild both sides.
	status, cmp := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id+"/revision-compare?from=1&to=3", "")
	if status != http.StatusOK || path(cmp, "from", "revision") != 1.0 || path(cmp, "to", "revision") != 3.0 {
		t.Fatalf("compare: %d %v", status, cmp)
	}
	blocks := cmp["blocks"].([]any)
	if len(blocks) != int(revs[2]["lines"].(float64)) {
		t.Fatalf("blocks %d for %v lines", len(blocks), revs[2]["lines"])
	}
	changed := 0
	for _, b := range blocks {
		blk := b.(map[string]any)
		if blk["kind"] == domain.BlockChanged {
			changed++
			before, after := wordSides(blk)
			if blk["after_line"] != changedLine || before != path(blk, "before", "text") || after != path(blk, "after", "text") || !strings.HasSuffix(before, " Voilà.") {
				t.Fatalf("changed block: %v (%q / %q)", blk, before, after)
			}
		} else if blk["kind"] != domain.BlockSame {
			t.Fatalf("unexpected block: %v", blk)
		}
	}
	if changed != 1 || len(path(cmp, "changes", "questions").([]any)) != 2 {
		t.Fatalf("changes: %d lines, questions %v", changed, path(cmp, "changes", "questions"))
	}
	if status, _ := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id+"/revision-compare?from=1&to=9", ""); status != http.StatusNotFound {
		t.Fatalf("unknown revision: %d", status)
	}
	if status, _ := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id+"/revision-compare?from=0&to=1", ""); status != http.StatusBadRequest {
		t.Fatalf("bad revision: %d", status)
	}

	// Restore previews: the current revision offers nothing; revision 1 would be 4.
	_, cur := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id+"/restore?revision=3", "")
	if cur["blocked"] != "is_current" || cur["next_revision"] != nil {
		t.Fatalf("current: %v", cur)
	}
	before := listeningCounts(t, db)
	_, editorA := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id+"/restore?revision=1", "")
	_, editorB := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id+"/restore?revision=2", "")
	if editorA["next_revision"] != 4.0 || editorA["blocked"] != nil || editorA["current_exercise_id"] != revs[2]["exercise_id"] ||
		len(editorA["records_on_current"].([]any)) != 0 || path(editorA, "from", "revision") != 3.0 || path(editorA, "to", "revision") != 1.0 {
		t.Fatalf("restore preview: %v", editorA)
	}
	if after := listeningCounts(t, db); after != before {
		t.Fatalf("previews wrote: %s → %s", before, after)
	}

	// Editor A restores revision 1: revision 4 has its content; a resend replays.
	status, res, replayed := postRestore(t, srv.URL, id, restoreBody(3, 1, editorA["target_fingerprint"]))
	if status != http.StatusCreated || res["revision"] != 4.0 || res["restored_from"] != 1.0 || replayed != "" ||
		path(res, "lesson", "script_revision", "revision") != 4.0 || path(res, "lesson", "script_revision", "pack_status") != domain.ListeningScriptUpdateAvailable {
		t.Fatalf("restore: %d %v", status, res)
	}
	revs = revisionsOf(t, srv.URL, id)
	if len(revs) != 4 || revs[3]["fingerprint"] != revs[0]["fingerprint"] || revs[3]["exercise_id"] == revs[0]["exercise_id"] {
		t.Fatalf("after restore: %v", revs)
	}
	if status, _, replayed := postRestore(t, srv.URL, id, restoreBody(3, 1, editorA["target_fingerprint"])); status != http.StatusOK || replayed != "true" {
		t.Fatalf("resend: %d %q", status, replayed)
	}
	if n := len(revisionsOf(t, srv.URL, id)); n != 4 {
		t.Fatalf("resend added a revision: %d", n)
	}

	// Editor B's preview (restore revision 2 from 3) went stale: refused, nothing written, fresh preview.
	counts := listeningCounts(t, db)
	status, conflict, _ := postRestore(t, srv.URL, id, restoreBody(3, 2, editorB["target_fingerprint"]))
	if status != http.StatusConflict || conflict["code"] != "stale_preview" || path(conflict, "preview", "from", "revision") != 4.0 ||
		path(conflict, "preview", "next_revision") != 5.0 {
		t.Fatalf("stale editor: %d %v", status, conflict)
	}
	if after := listeningCounts(t, db); after != counts {
		t.Fatalf("stale confirmation wrote: %s → %s", counts, after)
	}
	// A wrong fingerprint for the target is refused the same way.
	if status, body, _ := postRestore(t, srv.URL, id, restoreBody(4, 2, editorA["target_fingerprint"])); status != http.StatusConflict || body["code"] != "stale_preview" {
		t.Fatalf("wrong fingerprint: %d %v", status, body)
	}
	// Confirming the fresh preview works.
	if status, res, _ := postRestore(t, srv.URL, id, restoreBody(4, 2, path(conflict, "preview", "target_fingerprint"))); status != http.StatusCreated || res["revision"] != 5.0 {
		t.Fatalf("fresh confirm: %d %v", status, res)
	}

	// The records saved from revision 1 still resolve to revision 1's words.
	item := notebookItem(t, srv, "studio-l04")
	if item["source_status"] != "resolved" || path(item, "link", "listening_exercise_id") != ex1 ||
		item["explanation_en"] != "Work ends before the 18:30 class." || item["latest_version"] != 5.0 {
		t.Fatalf("notebook record after restores: %v", item)
	}
	// Malformed confirmations.
	for _, body := range []string{restoreBody(0, 1, editorA["target_fingerprint"]), restoreBody(5, 1, "sha256:short"), restoreBody(5, 5, path(conflict, "preview", "target_fingerprint"))} {
		if status, _, _ := postRestore(t, srv.URL, id, body); status != http.StatusUnprocessableEntity && status != http.StatusConflict {
			t.Fatalf("malformed %s: %d", body, status)
		}
	}
}

// An older record next to a current one: revision 1 as an older build stored
// it (an extra key, no evidence on its questions) compares with the current
// revision without error, and the difference names exactly what differs.
func TestRevisionStudio_OlderStoredRevisionComparesWithCurrent(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "older.db")
	earlier, _ := earlierU05(t)
	s1, db := buildRevisionServer(t, dbPath, earlier)
	_, lesson, _ := postScript(t, s1, "ls-wb1-u05")
	id := materialOf(t, lesson)
	exID := int64(lesson["current_exercise_id"].(float64))
	s1.Close()
	var raw string
	if err := db.QueryRow(`SELECT content FROM listening_exercises WHERE id = ?`, exID).Scan(&raw); err != nil {
		t.Fatal(err)
	}
	var content map[string]any
	if err := json.Unmarshal([]byte(raw), &content); err != nil {
		t.Fatal(err)
	}
	content["older_build_note"] = "kept by an older build"
	for _, it := range content["items"].([]any) {
		delete(it.(map[string]any), "evidence")
	}
	edited, _ := json.Marshal(content)
	if _, err := db.Exec(`UPDATE listening_exercises SET content = ? WHERE id = ?`, string(edited), exID); err != nil {
		t.Fatal(err)
	}
	srv, _ := buildRevisionServer(t, dbPath, embeddedScripts(t))
	_, preview := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id+"/script-update", "")
	if status, body, _ := postUpdate(t, srv, id, confirmBody(1, preview["pack_fingerprint"])); status != http.StatusCreated {
		t.Fatalf("update: %d %v", status, body)
	}
	status, cmp := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id+"/revision-compare?from=1&to=2", "")
	if status != http.StatusOK {
		t.Fatalf("compare: %d %v", status, cmp)
	}
	for _, q := range path(cmp, "changes", "questions").([]any) {
		fields := q.(map[string]any)["fields"].([]any)
		hasEvidence := false
		for _, f := range fields {
			hasEvidence = hasEvidence || f == "evidence"
		}
		if !hasEvidence {
			t.Fatalf("an older question without evidence must show evidence as changed: %v", q)
		}
	}
	revs := revisionsOf(t, srv.URL, id)
	if len(revs) != 2 || revs[0]["fingerprint"] == revs[1]["fingerprint"] {
		t.Fatalf("history: %v", revs)
	}
	// Restore of the older revision is previewed like any other.
	_, rp := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id+"/restore?revision=1", "")
	if rp["next_revision"] != 3.0 || rp["blocked"] != nil {
		t.Fatalf("restore preview of the older revision: %v", rp)
	}
}

// A YouTube lesson has no script revisions: 409 not_authored_script.
func TestRevisionStudio_NotAScript(t *testing.T) {
	srv, _ := buildRevisionServer(t, filepath.Join(t.TempDir(), "yt.db"), embeddedScripts(t))
	status, body := doJSON(t, http.MethodPost, srv.URL+"/listening/materials", `{"source_url":"https://youtu.be/dQw4w9WgXcQ","title":"Vidéo","transcript":"Bonjour."}`)
	if status != http.StatusCreated {
		t.Fatalf("create: %d %v", status, body)
	}
	id := materialOf(t, body)
	for _, u := range []string{"/revisions", "/revision-compare?from=1&to=1", "/restore?revision=1"} {
		if status, body := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id+u, ""); status != http.StatusConflict || body["code"] != "not_authored_script" {
			t.Fatalf("%s: %d %v", u, status, body)
		}
	}
	if status, _ := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/999/revisions", ""); status != http.StatusNotFound {
		t.Fatalf("unknown lesson: %d", status)
	}
}
