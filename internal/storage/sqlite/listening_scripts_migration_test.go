package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"io/fs"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/domain"
	"french-learning-app/migrations"
)

// applyBefore021 builds a database exactly as the runner would have left it
// before 021: every earlier embedded migration (in the private stack too,
// 018-020) applied once and recorded in the ledger.
func applyBefore021(t *testing.T, path string) *sql.DB {
	t.Helper()
	db, err := sql.Open("sqlite", fmt.Sprintf("file:%s?_pragma=busy_timeout(5000)&_pragma=journal_mode(WAL)&_pragma=foreign_keys(ON)", path))
	if err != nil {
		t.Fatalf("open raw db: %v", err)
	}
	db.SetMaxOpenConns(1)
	if _, err := db.Exec(`CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))`); err != nil {
		t.Fatal(err)
	}
	entries, err := fs.ReadDir(migrations.Files, ".")
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".sql") && e.Name() < "021" {
			names = append(names, e.Name())
		}
	}
	sort.Strings(names)
	for _, name := range names {
		b, _ := migrations.Files.ReadFile(name)
		if _, err := db.Exec(string(b)); err != nil {
			t.Fatalf("exec %s: %v", name, err)
		}
		if _, err := db.Exec(`INSERT INTO schema_migrations (name) VALUES (?)`, name); err != nil {
			t.Fatal(err)
		}
	}
	return db
}

// TestMigration021_KeepsEveryListeningRowAndForeignKey upgrades a populated
// pre-021 database: YouTube materials referenced by transcripts, exercises,
// a playlist item, a preparation and a notification, with an AUTOINCREMENT
// high-water mark above the largest ID. The rebuild must keep every row, every
// ID, the counter and the foreign keys, and must make a link-less YouTube row
// or a linked authored script impossible.
func TestMigration021_KeepsEveryListeningRowAndForeignKey(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "pre021.db")
	raw := applyBefore021(t, path)
	ts := time.Date(2026, 11, 1, 9, 0, 0, 0, time.UTC).Format(rfc3339)
	content := `{"items":[{"kind":"main_idea","question":"Q","expected_answer":"A","rationale_en":"r","rationale_zh":"r","segments":[1]},` +
		`{"kind":"detail","question":"Q2","expected_answer":"A2","rationale_en":"r","rationale_zh":"r","segments":[1]}],` +
		`"annotations":[{"kind":"vocabulary","segment":1,"excerpt":"Bonjour","note_en":"hello","note_zh":"你好"}]}`
	for _, stmt := range []string{
		`INSERT INTO listening_materials (id, video_id, source_url, title, created_at) VALUES
			(1, 'aBcDeFgHiJk', 'https://www.youtube.com/watch?v=aBcDeFgHiJk', 'Annonce en gare', '` + ts + `'),
			(2, 'pLaYlIsT001', 'https://www.youtube.com/watch?v=pLaYlIsT001', 'Vidéo de la playlist', '` + ts + `'),
			(4, 'nOtRaNsCr1p', 'https://www.youtube.com/watch?v=nOtRaNsCr1p', 'Sans transcription', '` + ts + `')`,
		`UPDATE sqlite_sequence SET seq = 10 WHERE name = 'listening_materials'`,
		`INSERT INTO listening_transcripts (id, material_id, version, segments, has_timestamps, created_at) VALUES
			(1, 1, 1, '[{"index":1,"start_seconds":5,"text":"Bonjour à tous."}]', 1, '` + ts + `'),
			(2, 2, 1, '[{"index":1,"start_seconds":null,"text":"Bonjour."}]', 0, '` + ts + `')`,
		`INSERT INTO listening_exercises (id, material_id, transcript_id, status, failure_code, generator, content, created_at) VALUES
			(1, 1, 1, 'completed', NULL, 'openai:fake:listening_exercise_v1', '` + content + `', '` + ts + `')`,
		`INSERT INTO listening_pull_runs (id, operation_id, trigger, status, started_at, lease_expires_at, finished_at, source_outcome, prepare_outcome, notify_outcome)
			VALUES (1, 'op-pull-1', 'manual', 'finished', '` + ts + `', '` + ts + `', '` + ts + `', 'ok', 'nothing_to_prepare', 'disabled')`,
		`INSERT INTO listening_playlist_items (video_id, material_id, playlist_id, material_created, source_title, published_at, pull_run_id, created_at)
			VALUES ('pLaYlIsT001', 2, 'PLtest', 1, 'Vidéo de la playlist', NULL, 1, '` + ts + `')`,
		`INSERT INTO listening_preparations (id, operation_id, material_id, transcript_id, trigger, after_unknown, started_at, deadline_at, finished_at, outcome, exercise_id)
			VALUES (1, 'op-prep-1', 1, 1, 'explicit', 0, '` + ts + `', '` + ts + `', '` + ts + `', 'completed', 1)`,
		`INSERT INTO listening_notifications (id, operation_id, exercise_id, channel, trigger, after_unknown, started_at, deadline_at, finished_at, outcome)
			VALUES (1, 'op-note-1', 1, 'telegram', 'explicit', 0, '` + ts + `', '` + ts + `', '` + ts + `', 'sent')`,
	} {
		if _, err := raw.Exec(stmt); err != nil {
			t.Fatalf("seed: %v\n%s", err, stmt)
		}
	}
	raw.Close()

	db, err := Open(path) // applies 021 only
	if err != nil {
		t.Fatalf("open with 021: %v", err)
	}
	defer db.Close()

	var applied int
	if err := db.QueryRow(`SELECT COUNT(*) FROM schema_migrations WHERE name = '021_listening_authored_scripts.sql'`).Scan(&applied); err != nil || applied != 1 {
		t.Fatalf("021 recorded %d times: %v", applied, err)
	}
	rows, err := db.Query(`SELECT id, source_kind, video_id, source_url, pack_script_id IS NULL, title, created_at FROM listening_materials ORDER BY id`)
	if err != nil {
		t.Fatal(err)
	}
	var got []string
	for rows.Next() {
		var id int64
		var kind, video, url, title, created string
		var noPack bool
		if err := rows.Scan(&id, &kind, &video, &url, &noPack, &title, &created); err != nil {
			t.Fatal(err)
		}
		got = append(got, fmt.Sprintf("%d|%s|%s|%s|%v|%s|%v", id, kind, video, url, noPack, title, created == ts))
	}
	rows.Close()
	want := []string{
		"1|youtube|aBcDeFgHiJk|https://www.youtube.com/watch?v=aBcDeFgHiJk|true|Annonce en gare|true",
		"2|youtube|pLaYlIsT001|https://www.youtube.com/watch?v=pLaYlIsT001|true|Vidéo de la playlist|true",
		"4|youtube|nOtRaNsCr1p|https://www.youtube.com/watch?v=nOtRaNsCr1p|true|Sans transcription|true",
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("materials after 021:\n%s\nwant:\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
	for table, n := range map[string]int{"listening_transcripts": 2, "listening_exercises": 1, "listening_playlist_items": 1,
		"listening_preparations": 1, "listening_notifications": 1, "listening_pull_runs": 1} {
		var c int
		if err := db.QueryRow(`SELECT COUNT(*) FROM ` + table).Scan(&c); err != nil || c != n {
			t.Errorf("%s: %d rows (%v), want %d", table, c, err, n)
		}
	}
	fk, err := db.Query(`PRAGMA foreign_key_check`)
	if err != nil {
		t.Fatal(err)
	}
	if fk.Next() {
		t.Error("foreign_key_check reports a violation after 021")
	}
	fk.Close()
	var leftovers int
	if err := db.QueryRow(`SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'listening_materials_021%'`).Scan(&leftovers); err != nil || leftovers != 0 {
		t.Errorf("021 left %d helper tables (%v)", leftovers, err)
	}
	var seq int
	if err := db.QueryRow(`SELECT seq FROM sqlite_sequence WHERE name = 'listening_materials'`).Scan(&seq); err != nil || seq != 10 {
		t.Errorf("AUTOINCREMENT high-water mark = %d (%v), want 10", seq, err)
	}
	for _, child := range []string{"listening_transcripts", "listening_exercises", "listening_playlist_items", "listening_preparations"} {
		var schema string
		if err := db.QueryRow(`SELECT sql FROM sqlite_master WHERE name = ?`, child).Scan(&schema); err != nil ||
			!strings.Contains(schema, "REFERENCES listening_materials(id)") {
			t.Errorf("%s no longer references listening_materials: %v %s", child, err, schema)
		}
	}

	// The constraints after 021.
	for name, stmt := range map[string]string{
		"orphan transcript":         `INSERT INTO listening_transcripts (material_id, version, segments, has_timestamps, created_at) VALUES (999, 1, '[]', 0, 'x')`,
		"youtube without a link":    `INSERT INTO listening_materials (source_kind, video_id, source_url, title, created_at) VALUES ('youtube', NULL, NULL, 't', 'x')`,
		"youtube with a pack id":    `INSERT INTO listening_materials (source_kind, video_id, source_url, pack_script_id, title, created_at) VALUES ('youtube', 'zZzZzZzZzZz', 'u', 'p/x', 't', 'x')`,
		"script with a link":        `INSERT INTO listening_materials (source_kind, source_url, pack_script_id, title, created_at) VALUES ('authored_script', 'https://youtu.be/zZzZzZzZzZz', 'p/x', 't', 'x')`,
		"script with a video id":    `INSERT INTO listening_materials (source_kind, video_id, pack_script_id, title, created_at) VALUES ('authored_script', 'zZzZzZzZzZz', 'p/x', 't', 'x')`,
		"script without a pack id":  `INSERT INTO listening_materials (source_kind, title, created_at) VALUES ('authored_script', 't', 'x')`,
		"unknown source kind":       `INSERT INTO listening_materials (source_kind, video_id, source_url, title, created_at) VALUES ('podcast', 'zZzZzZzZzZz', 'u', 't', 'x')`,
		"no source kind":            `INSERT INTO listening_materials (video_id, source_url, title, created_at) VALUES ('zZzZzZzZzZz', 'u', 't', 'x')`,
		"malformed video id stored": `INSERT INTO listening_materials (source_kind, video_id, source_url, title, created_at) VALUES ('youtube', 'short', 'u', 't', 'x')`,
	} {
		if _, err := db.Exec(stmt); err == nil {
			t.Errorf("%s was accepted", name)
		}
	}

	// The repository on the upgraded database: old rows read back, a new
	// material continues above the kept high-water mark, an authored script
	// imports with no link, and pulls still match and create YouTube material only.
	repo := NewListeningRepository(db)
	m1, err := repo.GetMaterial(ctx, 1)
	if err != nil || m1.SourceKind != domain.ListeningSourceYouTube || m1.VideoID != "aBcDeFgHiJk" || m1.PackScriptID != "" {
		t.Fatalf("material 1 = %+v, %v", m1, err)
	}
	m, _, err := repo.CreateMaterial(ctx, domain.ListeningMaterial{SourceKind: domain.ListeningSourceYouTube, VideoID: "nEwViDeO001",
		SourceURL: "https://www.youtube.com/watch?v=nEwViDeO001", Title: "Nouveau"}, nil, false)
	if err != nil || m.ID != 11 {
		t.Fatalf("new material id = %d (%v), want 11", m.ID, err)
	}
	segs := []domain.TranscriptSegment{{Index: 1, Speaker: "Agent", Text: "Bonjour."}, {Index: 2, Speaker: "Mei", Text: "Bonjour, je voudrais m'inscrire."}}
	authored := domain.ListeningExerciseContent{Items: []domain.ListeningItem{
		{ID: "x-1", Kind: domain.ListeningMainIdea, Question: "Q", ExpectedAnswer: "A", RationaleEN: "r", RationaleZH: "r", Segments: []int{2},
			Evidence: []domain.ListeningEvidence{{Segment: 2, Excerpt: "m'inscrire"}}},
		{ID: "x-2", Kind: domain.ListeningDetail, Question: "Q2", ExpectedAnswer: "B", RationaleEN: "r", RationaleZH: "r", Segments: []int{1},
			Evidence: []domain.ListeningEvidence{{Segment: 1, Excerpt: "Bonjour"}}},
	}, Annotations: []domain.ListeningAnnotation{}}
	script := domain.ListeningMaterial{SourceKind: domain.ListeningSourceAuthoredScript, PackScriptID: "flh_listening_script_pack_v1/ls-test", Title: "Script"}
	s, replay, err := repo.ImportAuthoredScript(ctx, script, segs, authored, time.Now())
	if err != nil || replay || s.VideoID != "" || s.SourceURL != "" || !s.IsAuthoredScript() {
		t.Fatalf("import = %+v replay=%v err=%v", s, replay, err)
	}
	again, replay, err := repo.ImportAuthoredScript(ctx, script, segs, authored, time.Now())
	if err != nil || !replay || again.ID != s.ID {
		t.Fatalf("replay = %+v replay=%v err=%v", again, replay, err)
	}
	changed := authored
	changed.Items = append([]domain.ListeningItem{}, authored.Items...)
	changed.Items[1].ExpectedAnswer = "C"
	if _, _, err := repo.ImportAuthoredScript(ctx, script, segs, changed, time.Now()); !errors.Is(err, domain.ErrListeningScriptConflict) {
		t.Fatalf("changed content: %v", err)
	}
	if _, _, err := repo.ImportAuthoredScript(ctx, domain.ListeningMaterial{SourceKind: domain.ListeningSourceAuthoredScript,
		PackScriptID: "p/y", SourceURL: "https://youtu.be/zZzZzZzZzZz", Title: "x"}, segs, authored, time.Now()); !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("a script with a link: %v", err)
	}
	// Material 2 is the playlist video with a transcript and no exercise: the
	// pull's candidate before and after the import. The script is never one.
	if cand, err := repo.NextPullCandidate(ctx); err != nil || cand == nil || *cand != 2 {
		t.Fatalf("pull candidate = %v (%v), want material 2", cand, err)
	}
	run, _, err := repo.StartPullRun(ctx, "op-pull-2", domain.ListeningPullManual, time.Now(), time.Now().Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if rec, err := repo.RecordPlaylistItem(ctx, run.ID, "PLtest", domain.PlaylistItem{VideoID: "aBcDeFgHiJk", Title: "Annonce"}, time.Now()); err != nil || rec.Created || rec.MaterialID != 1 {
		t.Fatalf("known video: %+v %v", rec, err)
	}
	rec, err := repo.RecordPlaylistItem(ctx, run.ID, "PLtest", domain.PlaylistItem{VideoID: "pUlLeDvId01", Title: "Nouvelle vidéo"}, time.Now())
	if err != nil || !rec.Created {
		t.Fatalf("new video: %+v %v", rec, err)
	}
	if pulled, err := repo.GetMaterial(ctx, rec.MaterialID); err != nil || pulled.SourceKind != domain.ListeningSourceYouTube || pulled.SourceURL == "" {
		t.Fatalf("pulled material = %+v %v", pulled, err)
	}
}
