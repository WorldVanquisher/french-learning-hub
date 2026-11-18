package http_test

// A second workbook revision (1 → 2 → 3): every mistake saved on an earlier
// revision keeps its own words, its link and its revision's evidence, and each
// earlier revision still reads in full. Disposable database, fixture packs
// built from the embedded one, no provider.

import (
	"net/http"
	"path/filepath"
	"strings"
	"testing"

	"french-learning-app/internal/domain"
)

func TestListeningScriptRevisions_SecondUpdateKeepsEarlierMistakesAndEvidence(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "rev3.db")
	middle, _ := earlierU05(t) // one correction behind the embedded pack
	oldest, _ := earlierU05(t) // two corrections behind: question 1 read differently too
	oldest.Scripts[u05].Questions[0].Question += " (première formulation)"
	if err := domain.ValidateListeningScript(&oldest.Scripts[u05]); err != nil {
		t.Fatalf("oldest fixture is invalid: %v", err)
	}
	current := embeddedScripts(t)
	const earlierExcerpt = "Je finis le travail à 17 h 30"

	// update previews and confirms the next revision under the server's pack.
	update := func(srv string, id string, from float64) float64 {
		t.Helper()
		status, preview := doJSON(t, http.MethodGet, srv+"/listening/materials/"+id+"/script-update", "")
		if status != http.StatusOK || preview["current_revision"] != from || preview["next_revision"] != from+1 {
			t.Fatalf("preview from %v: %d %v", from, status, preview)
		}
		status, body := doJSON(t, http.MethodPost, srv+"/listening/materials/"+id+"/script-update", confirmBody(from, preview["pack_fingerprint"]))
		if status != http.StatusCreated || body["revision"] != from+1 {
			t.Fatalf("update from %v: %d %v", from, status, body)
		}
		return path(body, "lesson", "current_exercise_id").(float64)
	}

	// Revision 1 under the oldest pack; two mistakes saved on it.
	srv1, db := buildRevisionServer(t, dbPath, oldest)
	status, lesson, _ := postScript(t, srv1, "ls-wb1-u05")
	if status != http.StatusCreated {
		t.Fatalf("import: %d", status)
	}
	id := materialOf(t, lesson)
	ex1 := lesson["current_exercise_id"].(float64)
	for capture, item := range map[string]int{"r1-l01": 1, "r1-l04": 4} {
		if status, body := saveMistake(t, srv1, capture, ex1, item, "Parce qu'il est moins cher"); status != http.StatusCreated {
			t.Fatalf("save %s: %d %v", capture, status, body)
		}
	}
	saved := map[string]map[string]any{"r1-l01": notebookItem(t, srv1, "r1-l01"), "r1-l04": notebookItem(t, srv1, "r1-l04")}
	srv1.Close()

	// Revision 2 under the middle pack, and a mistake on it.
	srv2, _ := buildRevisionServer(t, dbPath, middle)
	ex2 := update(srv2.URL, id, 1)
	if status, body := saveMistake(t, srv2, "r2-l04", ex2, 4, ""); status != http.StatusCreated {
		t.Fatalf("save on revision 2: %d %v", status, body)
	}
	saved["r2-l04"] = notebookItem(t, srv2, "r2-l04")
	srv2.Close()

	// Revision 3 under the current pack.
	srv, _ := buildRevisionServer(t, dbPath, current)
	ex3 := update(srv.URL, id, 2)
	if ex1 == ex2 || ex2 == ex3 {
		t.Fatalf("each revision has its own exercise: %v %v %v", ex1, ex2, ex3)
	}
	if got := listeningCounts(t, db); !strings.Contains(got, "listening_transcripts=3") || !strings.Contains(got, "listening_exercises=3") ||
		!strings.Contains(got, "listening_materials=1") {
		t.Fatalf("three revisions, nothing rewritten: %s", got)
	}

	// Every earlier mistake: the same words, its own revision, flagged with revision 3.
	links := map[string][2]float64{"r1-l01": {ex1, 1}, "r1-l04": {ex1, 1}, "r2-l04": {ex2, 2}}
	for capture, link := range links {
		got := notebookItem(t, srv, capture)
		want := saved[capture]
		if got["prompt"] != want["prompt"] || got["reference"] != want["reference"] || got["explanation_en"] != want["explanation_en"] ||
			path(got, "link", "listening_exercise_id") != link[0] || path(got, "link", "listening_transcript_version") != link[1] ||
			got["latest_version"] != 3.0 || got["source_status"] != "resolved" {
			t.Fatalf("%s after the second update: %v (saved %v)", capture, got, want)
		}
	}
	if !strings.HasSuffix(saved["r1-l01"]["prompt"].(string), " (première formulation)") ||
		saved["r1-l04"]["explanation_en"] != "Work ends before the 18:30 class." ||
		saved["r2-l04"]["explanation_en"] != "Work ends before the 18:30 class." {
		t.Fatalf("fixture: the saved items are not the earlier wordings: %v", saved)
	}

	// Each earlier revision still reads in full, with its own evidence.
	for rev, ex := range map[string]float64{"1": ex1, "2": ex2} {
		status, read := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id+"/revisions/"+rev, "")
		items := path(read, "exercise", "content", "items").([]any)
		evidence := path(items[3], "evidence").([]any)
		if status != http.StatusOK || read["current_revision"] != 3.0 || path(read, "exercise", "id") != ex ||
			len(evidence) != 1 || path(evidence[0], "excerpt") != earlierExcerpt {
			t.Fatalf("revision %s: %d %v", rev, status, read)
		}
		first := path(items[0], "question").(string)
		if wantOld := rev == "1"; strings.HasSuffix(first, " (première formulation)") != wantOld {
			t.Fatalf("revision %s, question 1: %q", rev, first)
		}
	}
	// The lesson reads revision 3 with the current evidence.
	_, lesson = doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id, "")
	if lesson["current_exercise_id"] != ex3 || path(lesson, "transcript", "version") != 3.0 ||
		currentItem(t, lesson, 4)["rationale_en"] != current.Scripts[u05].Questions[3].RationaleEN {
		t.Fatalf("lesson on revision 3: %v %v", lesson["current_exercise_id"], path(lesson, "transcript", "version"))
	}
	// The same question on revision 3 is a new source; revisions 1 and 2 keep theirs.
	if status, body := saveMistake(t, srv, "r3-l04", ex3, 4, ""); status != http.StatusCreated {
		t.Fatalf("save on revision 3: %d %v", status, body)
	}
	if status, body := saveMistake(t, srv, "r2-l04-again", ex2, 4, ""); status != http.StatusConflict || body["code"] != "source_already_saved" {
		t.Fatalf("revision 2's item again: %d %v", status, body)
	}
}
