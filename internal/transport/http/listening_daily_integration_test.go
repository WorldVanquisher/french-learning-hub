package http_test

// Daily Listening end to end: the real handler, SQLite repository, playlist
// source, exercise generator and Telegram notifier, against three local fakes
// (listeningfake): a YouTube Data API, an OpenAI Responses API and a Telegram
// Bot API. A fake clock drives deadlines and the local day.

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/listening"
	"french-learning-app/internal/listening/listeningfake"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

const (
	dailyModelKey = "sk-daily-integration-secret"
	dailyYTKey    = "yt-daily-integration-secret"
	dailyTGToken  = "424242:tg-daily-integration-secret"
	dailyChat     = "-1004242424242"
	dailyPlaylist = "PLflhDailyIntegration"
)

type fakeClock struct {
	mu sync.Mutex
	t  time.Time
}

func (c *fakeClock) now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.t
}

func (c *fakeClock) set(t time.Time) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.t = t
}

type dailyOpts struct {
	noSource, noPrepare, noNotify bool
	genTimeout                    time.Duration
	notifyBaseURL                 string
}

type dailyFixture struct {
	yt     *listeningfake.YouTube
	model  *listeningfake.Responses
	tg     *listeningfake.Telegram
	clock  *fakeClock
	srv    *httptest.Server
	db     *sql.DB
	routes http.Handler
}

func newDailyFixture(t *testing.T, o dailyOpts) *dailyFixture {
	t.Helper()
	if o.genTimeout == 0 {
		o.genTimeout = 2 * time.Second
	}
	f := &dailyFixture{
		yt:    listeningfake.NewYouTube(t, dailyYTKey),
		model: listeningfake.NewResponses(t, dailyModelKey, listeningExercise),
		tg:    listeningfake.NewTelegram(t, dailyTGToken),
		clock: &fakeClock{t: time.Date(2026, 11, 9, 7, 30, 0, 0, time.UTC)}, // 08:30 in Paris
	}
	db, err := sqlite.Open(filepath.Join(t.TempDir(), "daily.db"))
	if err != nil {
		t.Fatal(err)
	}
	f.db = db
	repo := sqlite.NewListeningRepository(db)
	gen := listening.NewOpenAI(dailyModelKey, "fake-model", f.model.URL(), o.genTimeout)
	lessons := application.NewListeningService(repo, gen,
		application.WithListeningClock(f.clock.now), application.WithPreparationDeadline(o.genTimeout+30*time.Second))
	var source domain.ListeningPlaylistSource
	if !o.noSource {
		source = listening.NewYouTubePlaylist(dailyYTKey, dailyPlaylist, f.yt.URL(), 50, time.Second)
	}
	var notifier domain.ListeningNotifier
	if !o.noNotify {
		base := f.tg.URL()
		if o.notifyBaseURL != "" {
			base = o.notifyBaseURL
		}
		notifier = listening.NewTelegram(dailyTGToken, dailyChat, base, 300*time.Millisecond)
	}
	paris, err := time.LoadLocation("Europe/Paris")
	if err != nil {
		t.Fatal(err)
	}
	daily := application.NewListeningDailyService(lessons, source, notifier, application.ListeningDailySettings{
		AutoPrepare: !o.noPrepare, Location: paris, SourceBudget: time.Second, NotifyDeadline: 30 * time.Second,
	})
	entryRepo := sqlite.NewEntryRepository(db)
	analysisRepo := sqlite.NewAnalysisRepository(db)
	feedbackRepo := sqlite.NewFeedbackRepository(db)
	knowledgeRepo := sqlite.NewKnowledgeRepository(db)
	conceptRepo := sqlite.NewConceptRepository(db)
	conceptSvc := application.NewConceptService(knowledgeRepo, conceptRepo, conceptRepo)
	annotation := application.NewEffectiveAnnotationService(conceptRepo, conceptRepo)
	handler := transporthttp.NewHandler(
		application.NewEntryService(entryRepo), application.NewAnalysisService(entryRepo, analysisRepo, nil),
		application.NewFeedbackService(feedbackRepo), application.NewEffectiveAnalysisService(analysisRepo, feedbackRepo),
		application.NewInventoryService(sqlite.NewInventoryRepository(db)), application.NewCaptureService(sqlite.NewCaptureRepository(db)),
		application.NewKnowledgeService(entryRepo, analysisRepo, feedbackRepo, knowledgeRepo, sqlite.NewAdmissionRepository(db), nil),
		conceptSvc, annotation, application.NewConceptAnnotationDatasetService(annotation, knowledgeRepo, conceptRepo),
		transporthttp.WithListening(lessons), transporthttp.WithListeningDaily(daily),
	)
	f.routes = handler.Routes()
	f.srv = httptest.NewServer(f.routes)
	t.Cleanup(func() { f.srv.Close(); db.Close() })
	return f
}

// keyed sends a request with an optional Idempotency-Key and returns status,
// body and headers.
func keyed(t *testing.T, client *http.Client, method, url, key, body string) (int, map[string]any, http.Header, error) {
	t.Helper()
	req, _ := http.NewRequestWithContext(context.Background(), method, url, strings.NewReader(body))
	if key != "" {
		req.Header.Set("Idempotency-Key", key)
	}
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := client.Do(req)
	if err != nil {
		return 0, nil, nil, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	var out map[string]any
	_ = json.Unmarshal(raw, &out)
	return resp.StatusCode, out, resp.Header, nil
}

func (f *dailyFixture) pull(t *testing.T, key string) (int, map[string]any) {
	t.Helper()
	status, out, _, err := keyed(t, http.DefaultClient, http.MethodPost, f.srv.URL+"/listening/pull", key, "")
	if err != nil {
		t.Fatal(err)
	}
	return status, out
}

func (f *dailyFixture) addMaterial(t *testing.T, videoID, title, transcript string) int64 {
	t.Helper()
	body, _ := json.Marshal(map[string]string{"source_url": "https://youtu.be/" + videoID, "title": title, "transcript": transcript})
	status, out := doJSON(t, http.MethodPost, f.srv.URL+"/listening/materials", string(body))
	if status != http.StatusCreated {
		t.Fatalf("add material: %d %v", status, out)
	}
	return int64(path(out, "material", "id").(float64))
}

func (f *dailyFixture) addTranscript(t *testing.T, id int64, transcript string) {
	t.Helper()
	body, _ := json.Marshal(map[string]string{"transcript": transcript})
	if status, out := doJSON(t, http.MethodPost, fmt.Sprintf("%s/listening/materials/%d/transcripts", f.srv.URL, id), string(body)); status != http.StatusCreated {
		t.Fatalf("add transcript: %d %v", status, out)
	}
}

func (f *dailyFixture) lesson(t *testing.T, id int64) map[string]any {
	t.Helper()
	_, out := doJSON(t, http.MethodGet, fmt.Sprintf("%s/listening/materials/%d", f.srv.URL, id), "")
	return out
}

// materialsByVideo maps video ID to list row.
func (f *dailyFixture) materialsByVideo(t *testing.T) map[string]map[string]any {
	t.Helper()
	_, list := doJSON(t, http.MethodGet, f.srv.URL+"/listening/materials", "")
	out := map[string]map[string]any{}
	for _, r := range list["materials"].([]any) {
		row := r.(map[string]any)
		vid := path(row, "material", "video_id").(string)
		if _, dup := out[vid]; dup {
			t.Fatalf("video %s is stored twice", vid)
		}
		out[vid] = row
	}
	return out
}

func idOf(row map[string]any) int64 { return int64(path(row, "material", "id").(float64)) }

func stepOutcomes(run map[string]any) string {
	return fmt.Sprintf("%v/%v/%v", path(run, "source", "outcome"), path(run, "preparation", "outcome"), path(run, "notification", "outcome"))
}

const (
	dkeyA = "11111111-1111-4111-8111-111111111111"
	dkeyB = "22222222-2222-4222-8222-222222222222"
	dkeyC = "33333333-3333-4333-8333-333333333333"
	dkeyD = "44444444-4444-4444-8444-444444444444"
	dkeyE = "55555555-5555-4555-8555-555555555555"
	dkeyF = "66666666-6666-4666-8666-666666666666"
	dkeyG = "77777777-7777-4777-8777-777777777777"
)

func TestDailyListening_PullDedupesAndWaitsForTranscript(t *testing.T) {
	f := newDailyFixture(t, dailyOpts{})
	// The learner saved one of the playlist's videos by hand earlier, without a transcript.
	manual := f.addMaterial(t, "FLHdailyB01", "Saved by hand", "")
	f.yt.SetVideos(
		listeningfake.Video{ID: "FLHdailyA01", Title: "Le marché du samedi", PublishedAt: "2026-11-08T07:00:00Z"},
		listeningfake.Video{ID: "FLHdailyB01", Title: "La bibliothèque", Privacy: "unlisted"},
		listeningfake.Video{ID: "FLHdailyP01", Title: "Private video", Privacy: "private"},
	)
	status, run := f.pull(t, dkeyA)
	if status != http.StatusCreated || run["status"] != "finished" || run["trigger"] != "manual" ||
		stepOutcomes(run) != "ok/nothing_to_prepare/nothing_ready" ||
		path(run, "items", "created") != 1.0 || path(run, "items", "known") != 1.0 || path(run, "items", "skipped") != 1.0 {
		t.Fatalf("first pull: %d %v", status, run)
	}
	rows := f.materialsByVideo(t)
	a, b := rows["FLHdailyA01"], rows["FLHdailyB01"]
	if len(rows) != 2 || a == nil || b == nil || idOf(b) != manual || rows["FLHdailyP01"] != nil {
		t.Fatalf("materials = %v", rows)
	}
	if a["state"] != "waiting_for_transcript" || a["in_playlist"] != true || path(a, "material", "title") != "Le marché du samedi" ||
		path(a, "material", "source_url") != "https://www.youtube.com/watch?v=FLHdailyA01" || b["in_playlist"] != true || b["state"] != "waiting_for_transcript" {
		t.Fatalf("rows a=%v b=%v", a, b)
	}
	// A second pull (the timer, say) records nothing twice.
	status, run = f.pull(t, dkeyB)
	if status != http.StatusCreated || path(run, "items", "created") != 0.0 || path(run, "items", "known") != 2.0 {
		t.Fatalf("second pull: %d %v", status, run)
	}
	if n := countRows(t, f.db, "listening_materials"); n != 2 {
		t.Fatalf("materials after two pulls = %d", n)
	}
	// Waiting material never reaches the model or the notifier.
	if f.model.Calls() != 0 || f.tg.Calls() != 0 {
		t.Fatalf("model %d, telegram %d calls for material without a transcript", f.model.Calls(), f.tg.Calls())
	}
	// The same key replays the stored run; nothing is read again.
	calls := f.yt.Calls()
	status, replay, hdr, _ := keyed(t, http.DefaultClient, http.MethodPost, f.srv.URL+"/listening/pull", dkeyA, "")
	if status != http.StatusOK || hdr.Get("Idempotency-Replayed") != "true" || replay["id"] != 1.0 || f.yt.Calls() != calls {
		t.Fatalf("replay: %d %v", status, replay)
	}
	if status, got := doJSON(t, http.MethodGet, f.srv.URL+"/listening/pull-runs/"+dkeyA, ""); status != http.StatusOK || got["id"] != 1.0 {
		t.Fatalf("lookup: %d %v", status, got)
	}
	_, st := doJSON(t, http.MethodGet, f.srv.URL+"/listening/daily", "")
	if path(st, "last_run", "id") != 2.0 || path(st, "preparation", "timezone") != "Europe/Paris" || path(st, "preparation", "daily_cap") != 1.0 ||
		path(st, "notification", "channel") != "telegram" || st["pull_enabled"] != true {
		t.Fatalf("status = %v", st)
	}
	// Official metadata only, the key in a header, never in the URL.
	if f.yt.KeyInURL() || f.yt.Queries()[0].Get("part") != "snippet,contentDetails,status" {
		t.Fatalf("youtube queries = %v", f.yt.Queries())
	}
}

func TestDailyListening_PreparesOneLessonPerLocalDayAndNotifies(t *testing.T) {
	f := newDailyFixture(t, dailyOpts{})
	transcript := authoredTranscript(t)
	f.yt.SetVideos(listeningfake.Video{ID: "FLHdailyA01", Title: "La minute du quartier"}, listeningfake.Video{ID: "FLHdailyB01", Title: "Le marché"})
	f.pull(t, dkeyA)
	rows := f.materialsByVideo(t)
	a, b := idOf(rows["FLHdailyA01"]), idOf(rows["FLHdailyB01"])
	f.addTranscript(t, a, transcript)
	f.addTranscript(t, b, transcript)

	// 23:30 in Paris: the first pull of the day prepares the oldest, then announces it.
	f.clock.set(time.Date(2026, 11, 9, 22, 30, 0, 0, time.UTC))
	status, run := f.pull(t, dkeyB)
	if status != http.StatusCreated || stepOutcomes(run) != "ok/completed/sent" || path(run, "preparation", "attempt", "material_id") != float64(a) ||
		path(run, "preparation", "attempt", "trigger") != "pull" || f.model.Calls() != 1 || f.tg.Calls() != 1 {
		t.Fatalf("first daily pull: %d %v (model %d, telegram %d)", status, run, f.model.Calls(), f.tg.Calls())
	}
	msg := f.tg.Messages()[0]
	if msg.ChatID != dailyChat || !strings.Contains(msg.Text, "«La minute du quartier»") {
		t.Fatalf("message = %+v", msg)
	}
	for _, leak := range []string{"bibliothèque", "justificatif", "youtube", dailyTGToken, dailyModelKey, dailyYTKey} {
		if strings.Contains(strings.Join(f.tg.Bodies(), "\n"), leak) {
			t.Fatalf("the notification carries %q", leak)
		}
	}
	// Same local day, button or timer: the cap is reached; nothing is called.
	status, run = f.pull(t, dkeyC)
	if status != http.StatusCreated || stepOutcomes(run) != "ok/daily_cap_reached/nothing_ready" || f.model.Calls() != 1 || f.tg.Calls() != 1 {
		t.Fatalf("same-day pull: %d %v", status, run)
	}
	_, st := doJSON(t, http.MethodGet, f.srv.URL+"/listening/daily", "")
	if path(st, "preparation", "today") != "2026-11-09" || path(st, "preparation", "used_today") != 1.0 {
		t.Fatalf("status = %v", st)
	}
	// 00:05 in Paris is a new local day although UTC is still the 9th.
	f.clock.set(time.Date(2026, 11, 9, 23, 5, 0, 0, time.UTC))
	status, run = f.pull(t, dkeyD)
	if status != http.StatusCreated || stepOutcomes(run) != "ok/completed/sent" || path(run, "preparation", "attempt", "material_id") != float64(b) ||
		f.model.Calls() != 2 || f.tg.Calls() != 2 {
		t.Fatalf("next-day pull: %d %v", status, run)
	}
	// Nothing is left to prepare; prepared lessons are never prepared again.
	f.clock.set(time.Date(2026, 11, 11, 7, 0, 0, 0, time.UTC))
	if _, run = f.pull(t, dkeyE); stepOutcomes(run) != "ok/nothing_to_prepare/nothing_ready" || f.model.Calls() != 2 {
		t.Fatalf("later pull: %v", run)
	}
	lesson := f.lesson(t, a)
	if lesson["state"] != "prepared" || len(lesson["preparations"].([]any)) != 1 || len(lesson["notifications"].([]any)) != 1 ||
		path(lesson["notifications"].([]any)[0], "state") != "sent" || path(lesson, "notification", "enabled") != true {
		t.Fatalf("lesson = %v", lesson)
	}
}

func TestDailyListening_UnknownGenerationOutcomesNeedAnExplicitRetry(t *testing.T) {
	f := newDailyFixture(t, dailyOpts{genTimeout: 300 * time.Millisecond})
	f.yt.SetVideos(listeningfake.Video{ID: "FLHdailyA01", Title: "La minute du quartier"})
	f.pull(t, dkeyA)
	id := idOf(f.materialsByVideo(t)["FLHdailyA01"])
	f.addTranscript(t, id, authoredTranscript(t))

	// The model does not answer in time: the outcome is unknown, and nothing is announced.
	f.model.Set(listeningfake.ModeHang, 0, 2*time.Second)
	_, run := f.pull(t, dkeyB)
	if stepOutcomes(run) != "ok/unknown/nothing_ready" || f.model.Calls() != 1 || f.tg.Calls() != 0 {
		t.Fatalf("timed-out pull: %v", run)
	}
	lesson := f.lesson(t, id)
	if lesson["state"] != "outcome_unknown" || path(lesson["preparations"].([]any)[0], "state") != "unknown" {
		t.Fatalf("lesson = %v", lesson)
	}
	// Later pulls never retry it, and it does not block other lessons: a newer
	// playlist video with a transcript is prepared instead the next day.
	f.model.Set(listeningfake.ModeOK, 0, 0)
	f.yt.SetVideos(listeningfake.Video{ID: "FLHdailyA01", Title: "La minute du quartier"}, listeningfake.Video{ID: "FLHdailyB01", Title: "Le marché"})
	if _, run = f.pull(t, dkeyC); stepOutcomes(run) != "ok/daily_cap_reached/nothing_ready" || f.model.Calls() != 1 {
		t.Fatalf("same-day pull: %v", run)
	}
	other := idOf(f.materialsByVideo(t)["FLHdailyB01"])
	f.addTranscript(t, other, authoredTranscript(t))
	// A new transcript version for the first video does not clear its unknown attempt.
	f.addTranscript(t, id, authoredTranscript(t))
	f.clock.set(time.Date(2026, 11, 10, 7, 30, 0, 0, time.UTC))
	if _, run = f.pull(t, dkeyD); stepOutcomes(run) != "ok/completed/sent" || path(run, "preparation", "attempt", "material_id") != float64(other) || f.model.Calls() != 2 {
		t.Fatalf("next-day pull: %v", run)
	}
	if f.lesson(t, id)["state"] != "outcome_unknown" {
		t.Fatal("the unknown attempt must stay visible until the learner acts")
	}
	// An explicit Prepare must acknowledge the unknown outcome first.
	url := fmt.Sprintf("%s/listening/materials/%d/exercises", f.srv.URL, id)
	status, out, _, _ := keyed(t, http.DefaultClient, http.MethodPost, url, dkeyG, "")
	if status != http.StatusConflict || out["code"] != "outcome_unknown" || path(out, "preparation", "state") != "unknown" || f.model.Calls() != 2 {
		t.Fatalf("unacknowledged retry: %d %v", status, out)
	}
	status, out, _, _ = keyed(t, http.DefaultClient, http.MethodPost, url, dkeyG, `{"confirm_unknown_retry":true}`)
	if status != http.StatusCreated || path(out, "preparation", "state") != "completed" || path(out, "preparation", "after_unknown") != true || f.model.Calls() != 3 {
		t.Fatalf("acknowledged retry: %d %v", status, out)
	}
	if f.lesson(t, id)["state"] != "prepared" {
		t.Fatal("lesson is not prepared after the explicit retry")
	}

	// A connection dropped after the request was sent is unknown too, never "failed".
	f.model.Set(listeningfake.ModeDrop, 0, 0)
	status, out, _, _ = keyed(t, http.DefaultClient, http.MethodPost, url, dkeyE, "")
	if status != http.StatusBadGateway || path(out, "preparation", "state") != "unknown" || path(out, "exercise", "status") != "failed" ||
		!strings.Contains(out["error"].(string), "outcome is unknown") {
		t.Fatalf("dropped response: %d %v", status, out)
	}
}

func TestDailyListening_LostResponsesAreCheckedByKeyBeforeAnyRetry(t *testing.T) {
	f := newDailyFixture(t, dailyOpts{})
	id := f.addMaterial(t, "FLHmanual01", "La minute du quartier", authoredTranscript(t))
	impatient := &http.Client{Timeout: 100 * time.Millisecond}
	url := fmt.Sprintf("%s/listening/materials/%d/exercises", f.srv.URL, id)

	// The browser gives up while the model is still working: the response is lost.
	f.model.Set(listeningfake.ModeHang, 0, 500*time.Millisecond)
	if _, _, _, err := keyed(t, impatient, http.MethodPost, url, dkeyA, ""); err == nil {
		t.Fatal("expected the client to give up")
	}
	// A second click with a new key while the first call is still running is
	// refused without a call.
	status, busy, _, _ := keyed(t, http.DefaultClient, http.MethodPost, url, dkeyB, "")
	if status != http.StatusConflict || busy["code"] != "preparation_in_progress" || path(busy, "preparation", "operation_id") != dkeyA || f.model.Calls() != 1 {
		t.Fatalf("second click: %d %v", status, busy)
	}
	// Checking the stored result: in progress, then completed. The call was not canceled.
	var state any
	for i := 0; i < 50; i++ {
		_, got := doJSON(t, http.MethodGet, f.srv.URL+"/listening/preparations/"+dkeyA, "")
		if state = path(got, "preparation", "state"); state != "in_progress" {
			if state != "completed" || path(got, "exercise", "status") != "completed" {
				t.Fatalf("stored result: %v", got)
			}
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	if state != "completed" || f.model.Calls() != 1 {
		t.Fatalf("state %v after %d calls", state, f.model.Calls())
	}
	// Resending the same key returns the stored attempt without a second call.
	status, out, hdr, _ := keyed(t, http.DefaultClient, http.MethodPost, url, dkeyA, "")
	if status != http.StatusOK || hdr.Get("Idempotency-Replayed") != "true" || path(out, "exercise", "status") != "completed" || f.model.Calls() != 1 {
		t.Fatalf("same-key resend: %d %v (calls %d)", status, out, f.model.Calls())
	}
	if status, _ := doJSON(t, http.MethodGet, f.srv.URL+"/listening/preparations/"+dkeyB, ""); status != http.StatusNotFound {
		t.Fatalf("unknown key: %d", status)
	}

	// The same for "Pull now": a lost response, then the stored run by key.
	f.yt.SetVideos(listeningfake.Video{ID: "FLHdailyA01", Title: "Nouvelle vidéo"})
	f.yt.Set(listeningfake.ModeHang, 0, 400*time.Millisecond)
	if _, _, _, err := keyed(t, impatient, http.MethodPost, f.srv.URL+"/listening/pull", dkeyC, ""); err == nil {
		t.Fatal("expected the client to give up on the pull")
	}
	for i := 0; i < 50; i++ {
		_, got := doJSON(t, http.MethodGet, f.srv.URL+"/listening/pull-runs/"+dkeyC, "")
		if got["status"] == "finished" {
			if path(got, "items", "created") != 1.0 {
				t.Fatalf("stored run: %v", got)
			}
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	status, out, hdr, _ = keyed(t, http.DefaultClient, http.MethodPost, f.srv.URL+"/listening/pull", dkeyC, "")
	if status != http.StatusOK || hdr.Get("Idempotency-Replayed") != "true" || out["status"] != "finished" || f.yt.Calls() != 1 {
		t.Fatalf("pull resend: %d %v (youtube calls %d)", status, out, f.yt.Calls())
	}
}

func TestDailyListening_AmbiguousTelegramSendsNeedAnExplicitRetry(t *testing.T) {
	f := newDailyFixture(t, dailyOpts{})
	f.yt.SetVideos(listeningfake.Video{ID: "FLHdailyA01", Title: "La minute du quartier"})
	f.pull(t, dkeyA)
	id := idOf(f.materialsByVideo(t)["FLHdailyA01"])
	f.addTranscript(t, id, authoredTranscript(t))

	// Telegram reads the message, then the connection drops: delivery is unknown.
	f.tg.Set(listeningfake.ModeDrop, 0, 0)
	_, run := f.pull(t, dkeyB)
	if stepOutcomes(run) != "ok/completed/unknown" || path(run, "notification", "attempt", "failure_code") != "no_response" || f.tg.Calls() != 1 {
		t.Fatalf("pull: %v", run)
	}
	exerciseID := int64(path(run, "preparation", "attempt", "exercise_id").(float64))
	// A later pull never sends it again.
	f.tg.Set(listeningfake.ModeOK, 0, 0)
	if _, run = f.pull(t, dkeyC); f.tg.Calls() != 1 || path(run, "notification", "outcome") != "nothing_ready" {
		t.Fatalf("later pull resent: %v", run)
	}
	url := fmt.Sprintf("%s/listening/exercises/%d/notifications", f.srv.URL, exerciseID)
	status, out, _, _ := keyed(t, http.DefaultClient, http.MethodPost, url, dkeyD, "")
	if status != http.StatusConflict || out["code"] != "outcome_unknown" || f.tg.Calls() != 1 {
		t.Fatalf("unacknowledged resend: %d %v", status, out)
	}
	status, out, _, _ = keyed(t, http.DefaultClient, http.MethodPost, url, dkeyD, `{"confirm_unknown_retry":true}`)
	if status != http.StatusCreated || out["state"] != "sent" || out["after_unknown"] != true || out["trigger"] != "explicit" || f.tg.Calls() != 2 {
		t.Fatalf("acknowledged resend: %d %v", status, out)
	}
	status, out, hdr, _ := keyed(t, http.DefaultClient, http.MethodPost, url, dkeyD, `{"confirm_unknown_retry":true}`)
	if status != http.StatusOK || hdr.Get("Idempotency-Replayed") != "true" || f.tg.Calls() != 2 {
		t.Fatalf("same-key resend: %d %v", status, out)
	}
	if status, out, _, _ = keyed(t, http.DefaultClient, http.MethodPost, url, dkeyE, ""); status != http.StatusConflict || out["code"] != "not_retryable" || f.tg.Calls() != 2 {
		t.Fatalf("resend after sent: %d %v", status, out)
	}
	if status, got := doJSON(t, http.MethodGet, f.srv.URL+"/listening/notifications/"+dkeyD, ""); status != http.StatusOK || got["state"] != "sent" {
		t.Fatalf("lookup: %d %v", status, got)
	}
	lesson := f.lesson(t, id)
	ns := lesson["notifications"].([]any)
	if len(ns) != 2 || path(ns[0], "state") != "sent" || path(ns[1], "state") != "unknown" {
		t.Fatalf("notifications = %v", ns)
	}
}

func TestDailyListening_RefusedAndUnsentNotificationsAreFailuresWithoutRetry(t *testing.T) {
	closed := httptest.NewServer(http.NotFoundHandler())
	deadURL := closed.URL
	closed.Close()
	for name, setup := range map[string]struct {
		opts dailyOpts
		mode string
		code string
	}{
		"refused":  {dailyOpts{}, listeningfake.ModeStatus, "refused"},
		"not sent": {dailyOpts{notifyBaseURL: deadURL}, listeningfake.ModeOK, "not_sent"},
	} {
		t.Run(name, func(t *testing.T) {
			f := newDailyFixture(t, setup.opts)
			f.tg.Set(setup.mode, http.StatusBadRequest, 0)
			f.yt.SetVideos(listeningfake.Video{ID: "FLHdailyA01", Title: "La minute du quartier"})
			f.pull(t, dkeyA)
			f.addTranscript(t, idOf(f.materialsByVideo(t)["FLHdailyA01"]), authoredTranscript(t))
			_, run := f.pull(t, dkeyB)
			if stepOutcomes(run) != "ok/completed/failed" || path(run, "notification", "attempt", "failure_code") != setup.code {
				t.Fatalf("pull: %v", run)
			}
			calls := f.tg.Calls()
			f.clock.set(time.Date(2026, 11, 10, 7, 30, 0, 0, time.UTC))
			if _, run = f.pull(t, dkeyC); f.tg.Calls() != calls {
				t.Fatalf("a later pull resent a failed notification: %v", run)
			}
		})
	}
}

func TestDailyListening_RunsNeverOverlapAndInterruptedRunsAreReported(t *testing.T) {
	f := newDailyFixture(t, dailyOpts{})
	f.yt.SetVideos(listeningfake.Video{ID: "FLHdailyA01", Title: "Une"})
	f.yt.Set(listeningfake.ModeHang, 0, 600*time.Millisecond)
	done := make(chan int, 1)
	go func() {
		status, _, _, _ := keyed(t, http.DefaultClient, http.MethodPost, f.srv.URL+"/listening/pull", dkeyA, "")
		done <- status
	}()
	<-f.yt.Arrived // the first pull is reading the playlist
	status, out := f.pull(t, dkeyB)
	if status != http.StatusConflict || out["code"] != "busy" || path(out, "run", "operation_id") != dkeyA || f.yt.Calls() != 1 {
		t.Fatalf("overlapping pull: %d %v", status, out)
	}
	if status, _ := doJSON(t, http.MethodGet, f.srv.URL+"/listening/pull-runs/"+dkeyB, ""); status != http.StatusNotFound {
		t.Fatalf("a refused pull must record nothing: %d", status)
	}
	if status := <-done; status != http.StatusCreated {
		t.Fatalf("first pull: %d", status)
	}
	f.yt.Set(listeningfake.ModeOK, 0, 0)

	// A process that died mid-run leaves a running row and a pending attempt.
	id := idOf(f.materialsByVideo(t)["FLHdailyA01"])
	f.addTranscript(t, id, authoredTranscript(t))
	past := f.clock.now().Add(-time.Hour).Format(time.RFC3339Nano)
	if _, err := f.db.Exec(`INSERT INTO listening_pull_runs (operation_id, trigger, status, started_at, lease_expires_at) VALUES (?, 'scheduled', 'running', ?, ?)`,
		dkeyC, past, past); err != nil {
		t.Fatal(err)
	}
	var transcriptID int64
	_ = f.db.QueryRow(`SELECT id FROM listening_transcripts WHERE material_id = ?`, id).Scan(&transcriptID)
	if _, err := f.db.Exec(`INSERT INTO listening_preparations (operation_id, material_id, transcript_id, trigger, pull_run_id, pull_day, after_unknown, started_at, deadline_at)
		VALUES ('crashed', ?, ?, 'pull', (SELECT id FROM listening_pull_runs WHERE operation_id = ?), '2026-11-08', 0, ?, ?)`, id, transcriptID, dkeyC, past, past); err != nil {
		t.Fatal(err)
	}
	if _, got := doJSON(t, http.MethodGet, f.srv.URL+"/listening/pull-runs/"+dkeyC, ""); got["status"] != "interrupted" {
		t.Fatalf("a running run past its lease reads as interrupted: %v", got)
	}
	status, run := f.pull(t, dkeyD)
	if status != http.StatusCreated || stepOutcomes(run) != "ok/nothing_to_prepare/nothing_ready" || f.model.Calls() != 0 {
		t.Fatalf("pull after a crash: %d %v (model %d)", status, run, f.model.Calls())
	}
	var stored string
	_ = f.db.QueryRow(`SELECT status FROM listening_pull_runs WHERE operation_id = ?`, dkeyC).Scan(&stored)
	if stored != "interrupted" || f.lesson(t, id)["state"] != "outcome_unknown" {
		t.Fatalf("crashed run %q, lesson %v", stored, f.lesson(t, id)["state"])
	}
}

func TestDailyListening_SourceFailureIsRecordedAndPreparationStillRuns(t *testing.T) {
	f := newDailyFixture(t, dailyOpts{})
	f.yt.SetVideos(listeningfake.Video{ID: "FLHdailyA01", Title: "La minute du quartier"})
	f.pull(t, dkeyA)
	f.addTranscript(t, idOf(f.materialsByVideo(t)["FLHdailyA01"]), authoredTranscript(t))
	f.yt.Set(listeningfake.ModeStatus, http.StatusForbidden, 0)
	status, run := f.pull(t, dkeyB)
	if status != http.StatusCreated || stepOutcomes(run) != "failed/completed/sent" || path(run, "source", "failure") != "source_refused" {
		t.Fatalf("pull with a refusing source: %d %v", status, run)
	}
	raw, _ := json.Marshal(run)
	if strings.Contains(string(raw), dailyYTKey) || strings.Contains(string(raw), f.yt.URL()) {
		t.Fatalf("run leaks the key or URL: %s", raw)
	}
}

func TestDailyListening_DisabledAndDemo(t *testing.T) {
	f := newDailyFixture(t, dailyOpts{noSource: true, noPrepare: true, noNotify: true})
	if status, _ := f.pull(t, dkeyA); status != http.StatusServiceUnavailable {
		t.Fatalf("pull with nothing configured: %d", status)
	}
	if _, st := doJSON(t, http.MethodGet, f.srv.URL+"/listening/daily", ""); st["pull_enabled"] != false || path(st, "notification", "enabled") != false {
		t.Fatalf("status = %v", st)
	}
	if n := countRows(t, f.db, "listening_pull_runs"); n != 0 || f.yt.Calls()+f.model.Calls()+f.tg.Calls() != 0 {
		t.Fatalf("disabled pull recorded %d runs", n)
	}

	demo := httptest.NewServer(transporthttp.NewPublicDemoBoundary(f.routes, false))
	t.Cleanup(demo.Close)
	for _, prefix := range []string{"", "/api"} {
		for _, p := range []string{"/listening/daily", "/listening/pull-runs/" + dkeyA, "/listening/preparations/" + dkeyA, "/listening/notifications/" + dkeyA} {
			if status, _ := doJSON(t, http.MethodGet, demo.URL+prefix+p, ""); status != http.StatusNotFound {
				t.Errorf("GET %s%s in the demo: %d", prefix, p, status)
			}
		}
		for _, p := range []string{"/listening/pull", "/listening/exercises/1/notifications"} {
			if status, _ := doJSON(t, http.MethodPost, demo.URL+prefix+p, ""); status != http.StatusMethodNotAllowed {
				t.Errorf("POST %s%s in the demo: %d", prefix, p, status)
			}
		}
	}
}

func TestDailyListening_RequestValidation(t *testing.T) {
	f := newDailyFixture(t, dailyOpts{})
	id := f.addMaterial(t, "FLHmanual01", "Titre", authoredTranscript(t))
	cases := []struct {
		name, method, url, key, body string
		want                         int
	}{
		{"pull without key", http.MethodPost, "/listening/pull", "", "", http.StatusBadRequest},
		{"pull with a non-UUID key", http.MethodPost, "/listening/pull", "pull-1", "", http.StatusBadRequest},
		{"pull with a body", http.MethodPost, "/listening/pull", dkeyA, `{"trigger":"scheduled"}`, http.StatusBadRequest},
		{"prepare with a bad key", http.MethodPost, fmt.Sprintf("/listening/materials/%d/exercises", id), "nope", "", http.StatusBadRequest},
		{"prepare with an unknown field", http.MethodPost, fmt.Sprintf("/listening/materials/%d/exercises", id), dkeyB, `{"retry":true}`, http.StatusBadRequest},
		{"notify without key", http.MethodPost, "/listening/exercises/1/notifications", "", "", http.StatusBadRequest},
		{"notify unknown exercise", http.MethodPost, "/listening/exercises/999/notifications", dkeyC, "", http.StatusNotFound},
		{"lookup with a bad key", http.MethodGet, "/listening/pull-runs/not-a-key", "", "", http.StatusBadRequest},
	}
	for _, c := range cases {
		if status, out, _, _ := keyed(t, http.DefaultClient, c.method, f.srv.URL+c.url, c.key, c.body); status != c.want {
			t.Errorf("%s: %d %v", c.name, status, out)
		}
	}
	if f.yt.Calls()+f.model.Calls()+f.tg.Calls() != 0 || countRows(t, f.db, "listening_pull_runs") != 0 || countRows(t, f.db, "listening_preparations") != 0 {
		t.Fatal("refused requests reached a service or stored something")
	}
	// A key reused for another material conflicts instead of replaying.
	other := f.addMaterial(t, "FLHmanual02", "Autre", authoredTranscript(t))
	if status, _, _, _ := keyed(t, http.DefaultClient, http.MethodPost, fmt.Sprintf("%s/listening/materials/%d/exercises", f.srv.URL, id), dkeyF, ""); status != http.StatusCreated {
		t.Fatalf("prepare: %d", status)
	}
	if status, out, _, _ := keyed(t, http.DefaultClient, http.MethodPost, fmt.Sprintf("%s/listening/materials/%d/exercises", f.srv.URL, other), dkeyF, ""); status != http.StatusConflict || out["code"] != "key_conflict" || f.model.Calls() != 1 {
		t.Fatalf("key reuse: %d %v", status, out)
	}
}
