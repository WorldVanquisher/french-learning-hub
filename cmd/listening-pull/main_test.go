package main

import (
	"bytes"
	"context"
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/config"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/listening"
	"french-learning-app/internal/listening/listeningfake"
	"french-learning-app/internal/storage/sqlite"
)

const (
	cliModelKey = "sk-cli-test-secret"
	cliYTKey    = "yt-cli-test-secret"
	cliTGToken  = "777777:tg-cli-test-secret"
	cliChat     = "-1007777777777"
)

// The exercise the fake model returns; it fits the transcript below.
const cliExercise = `{"items":[
 {"kind":"main_idea","question":"De quoi parle-t-on ?","expected_answer":"D'une bibliothèque qui ouvre.","rationale_en":"Segment 1 says so.","rationale_zh":"第1段说明了。","segments":[1]},
 {"kind":"detail","question":"Quand ?","expected_answer":"Samedi.","rationale_en":"Segment 2 gives the day.","rationale_zh":"第2段给出了日期。","segments":[2]}],
 "annotations":[{"kind":"vocabulary","segment":2,"excerpt":"samedi","note_en":"Saturday","note_zh":"星期六"}]}`

const cliTranscript = "Une bibliothèque ouvre dans le quartier.\nElle ouvre samedi matin."

type cliEnv struct {
	yt     *listeningfake.YouTube
	model  *listeningfake.Responses
	tg     *listeningfake.Telegram
	dbPath string
}

func setup(t *testing.T) cliEnv {
	t.Helper()
	t.Chdir(t.TempDir()) // no .env
	e := cliEnv{
		yt:     listeningfake.NewYouTube(t, cliYTKey, listeningfake.Video{ID: "FLHcliVid01", Title: "La bibliothèque"}),
		model:  listeningfake.NewResponses(t, cliModelKey, cliExercise),
		tg:     listeningfake.NewTelegram(t, cliTGToken),
		dbPath: filepath.Join(t.TempDir(), "app.db"),
	}
	for k, v := range map[string]string{
		"DB_PATH": e.dbPath, "AI_PROVIDER": "rule-based", "EXTRACTOR_PROVIDER": "disabled", "SUGGESTION_PROVIDER": "disabled",
		"EMBEDDING_PROVIDER": "disabled", "SEMANTIC_SEARCH": "disabled",
		"LISTENING_PROVIDER": "openai", "OPENAI_API_KEY": cliModelKey, "OPENAI_MODEL": "fake-model",
		"OPENAI_BASE_URL": e.model.URL(), "OPENAI_TIMEOUT": "5",
		"LISTENING_PLAYLIST_SOURCE": "youtube", "LISTENING_PLAYLIST_ID": "PLflhCliTest", "YOUTUBE_API_KEY": cliYTKey,
		"YOUTUBE_API_BASE_URL": e.yt.URL(), "YOUTUBE_TIMEOUT": "2",
		"LISTENING_AUTO_PREPARE": "daily", "LISTENING_TIMEZONE": "Europe/Paris",
		"LISTENING_NOTIFY": "telegram", "TELEGRAM_BOT_TOKEN": cliTGToken, "TELEGRAM_CHAT_ID": cliChat,
		"TELEGRAM_API_BASE_URL": e.tg.URL(), "TELEGRAM_TIMEOUT": "2",
	} {
		t.Setenv(k, v)
	}
	return e
}

type result struct {
	code   int
	stdout string
	stderr string
	run    map[string]any
}

func invoke(t *testing.T, args ...string) result {
	t.Helper()
	var out, errOut bytes.Buffer
	code := run(context.Background(), args, &out, &errOut)
	r := result{code: code, stdout: out.String(), stderr: errOut.String()}
	for _, secret := range []string{cliModelKey, cliYTKey, cliTGToken, cliChat} {
		if strings.Contains(r.stdout+r.stderr, secret) {
			t.Fatalf("output leaks a secret: %s%s", r.stdout, r.stderr)
		}
	}
	if strings.Contains(strings.Join(args, " "), "-json") && code != exitUsage && out.Len() > 0 {
		_ = json.Unmarshal(out.Bytes(), &r.run)
	}
	return r
}

func TestListeningPull_SharesThePullWithTheButtonAndNeverOverlaps(t *testing.T) {
	e := setup(t)
	// The timer's run: a new video waits for its transcript; nothing is prepared or sent.
	r := invoke(t, "-json", "-trigger", "scheduled")
	if r.code != exitOK || r.run["trigger"] != "scheduled" || r.run["materials_created"] != 1.0 ||
		r.run["prepare_outcome"] != "nothing_to_prepare" || r.run["notify_outcome"] != "nothing_ready" || e.model.Calls()+e.tg.Calls() != 0 {
		t.Fatalf("first run: %+v", r)
	}

	// The server process, on its own connection to the same database file: the
	// learner adds the transcript and presses "Pull now".
	cfg, err := config.Load()
	if err != nil {
		t.Fatal(err)
	}
	db, err := sqlite.Open(e.dbPath)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })
	lessons, daily, err := listening.NewServices(cfg, sqlite.NewListeningRepository(db))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := lessons.AddTranscript(context.Background(), 1, cliTranscript); err != nil {
		t.Fatal(err)
	}
	dayBefore := domain.ListeningDay(time.Now(), cfg.ListeningDaily.Location)
	button, _, err := daily.Pull(context.Background(), "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", domain.ListeningPullManual)
	if err != nil || button.PrepareOutcome != "completed" || button.NotifyOutcome != "sent" || e.model.Calls() != 1 || e.tg.Calls() != 1 {
		t.Fatalf("button pull: %+v %v", button, err)
	}

	// The command's next run the same local day shares the button's cap.
	if _, err := lessons.CreateMaterial(context.Background(), "https://youtu.be/FLHcliVid02", "Deuxième", cliTranscript); err != nil {
		t.Fatal(err)
	}
	e.yt.SetVideos(listeningfake.Video{ID: "FLHcliVid01", Title: "La bibliothèque"}, listeningfake.Video{ID: "FLHcliVid02", Title: "Deuxième"})
	r = invoke(t, "-json", "-trigger", "scheduled")
	if dayBefore == domain.ListeningDay(time.Now(), cfg.ListeningDaily.Location) &&
		(r.code != exitOK || r.run["prepare_outcome"] != "daily_cap_reached" || r.run["items_known"] != 2.0 || e.model.Calls() != 1 || e.tg.Calls() != 1) {
		t.Fatalf("same-day command run: %+v", r)
	}

	// While another pull holds its lease (the button, say), the command starts nothing.
	future := time.Now().Add(time.Hour).UTC().Format(time.RFC3339Nano)
	if _, err := db.Exec(`INSERT INTO listening_pull_runs (operation_id, trigger, status, started_at, lease_expires_at) VALUES ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'manual', 'running', ?, ?)`,
		future, future); err != nil {
		t.Fatal(err)
	}
	calls := e.yt.Calls()
	r = invoke(t, "-trigger", "scheduled")
	if r.code != exitBusy || !strings.Contains(r.stderr, "another pull is running") || e.yt.Calls() != calls {
		t.Fatalf("overlapping run: %+v", r)
	}
	var runs int
	_ = db.QueryRow(`SELECT COUNT(*) FROM listening_pull_runs`).Scan(&runs)
	if runs != 4 {
		t.Fatalf("pull runs = %d, want 4 (the refused one records nothing)", runs)
	}
	if _, err := db.Exec(`UPDATE listening_pull_runs SET status = 'interrupted', finished_at = ? WHERE status = 'running'`, future); err != nil {
		t.Fatal(err)
	}

	// A failed step needs attention: exit 3, and it is the last outcome shown.
	e.yt.Set(listeningfake.ModeStatus, 500, 0)
	if r = invoke(t, "-trigger", "scheduled"); r.code != exitAttention || !strings.Contains(r.stdout, "playlist:     failed (source_unavailable)") {
		t.Fatalf("failing source: %+v", r)
	}
	if r = invoke(t, "status"); r.code != exitOK || !strings.Contains(r.stdout, "Europe/Paris") ||
		!strings.Contains(r.stdout, "last pull:    pull run 5 (scheduled) finished") || !strings.Contains(r.stdout, "notification: telegram") {
		t.Fatalf("status: %+v", r)
	}
	if r = invoke(t, "-json", "status"); r.code != exitOK || r.run["used_today"] == nil || r.run["timezone"] != "Europe/Paris" {
		t.Fatalf("json status: %+v", r)
	}
}

func TestListeningPull_RefusesWhenNotConfiguredAndOnBadUsage(t *testing.T) {
	setup(t)
	if r := invoke(t, "-trigger", "hourly"); r.code != exitUsage {
		t.Fatalf("bad trigger: %+v", r)
	}
	if r := invoke(t, "now"); r.code != exitUsage {
		t.Fatalf("bad argument: %+v", r)
	}
	t.Setenv("LISTENING_PLAYLIST_SOURCE", "disabled")
	t.Setenv("LISTENING_NOTIFY", "disabled")
	t.Setenv("LISTENING_AUTO_PREPARE", "disabled")
	if r := invoke(t); r.code != exitNotEnabled || !strings.Contains(r.stderr, "not configured") {
		t.Fatalf("not configured: %+v", r)
	}
	t.Setenv("LISTENING_NOTIFY", "telegram") // notify without automatic preparation
	if r := invoke(t); r.code != exitError || !strings.Contains(r.stderr, "configuration") {
		t.Fatalf("invalid configuration: %+v", r)
	}
}
