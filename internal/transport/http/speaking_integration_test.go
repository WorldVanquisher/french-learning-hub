package http_test

// Speaking v1 end to end: the real handler, SQLite repository, OpenAI
// transcriber and feedback client against local fakes (speakingfake for
// /audio/transcriptions, listeningfake for /responses), with the embedded
// authored prompts, synthetic audio and the authored feedback fixture.

import (
	"bytes"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/listening/listeningfake"
	"french-learning-app/internal/speaking"
	"french-learning-app/internal/speaking/speakingfake"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

const speakingKey = "sk-speaking-integration-secret"

const (
	skeyA = "c1111111-1111-4111-8111-111111111111"
	skeyB = "c2222222-2222-4222-8222-222222222222"
	skeyC = "c3333333-3333-4333-8333-333333333333"
	skeyD = "c4444444-4444-4444-8444-444444444444"
)

type speakingFixture struct {
	stt    *speakingfake.Transcriptions
	model  *listeningfake.Responses
	srv    *httptest.Server
	db     *sql.DB
	dbPath string
	routes http.Handler
}

func speakingExample(t *testing.T) string {
	t.Helper()
	set, err := domain.ParseSpeakingPrompts(speaking.ExamplePrompts())
	if err != nil {
		t.Fatal(err)
	}
	return set.Prompts[0].ExampleTranscript
}

// machine is what the fake transcriber "hears": the example with two
// transcription slips. v1 fixes the first, v2 the second.
func machine(t *testing.T) string {
	return strings.Replace(transcriptV1(t), "ton invitation", "ton imitation", 1)
}
func transcriptV1(t *testing.T) string {
	return strings.Replace(speakingExample(t), "tarte aux pommes", "tarte au pomme", 1)
}
func transcriptV2(t *testing.T) string { return speakingExample(t) }

// synthAudio is a synthetic WAV: a valid header and a distinctive,
// deterministic payload, so the test can prove no window of it is ever stored.
func synthAudio(seed string, n int) []byte {
	out := []byte("RIFF\x24\x08\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80\x3e\x00\x00\x00\x7d\x00\x00\x02\x00\x10\x00data\x00\x08\x00\x00")
	block := sha256.Sum256([]byte(seed))
	for len(out) < n {
		out = append(out, block[:]...)
		block = sha256.Sum256(block[:])
	}
	return out[:n]
}

func digest(b []byte) string {
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:])
}

func speakingFeedbackFixture(t *testing.T) string {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "..", "speaking", "testdata", "invitation_feedback.json"))
	if err != nil {
		t.Fatal(err)
	}
	return string(raw)
}

func newSpeakingFixture(t *testing.T, enabled bool, timeout time.Duration) *speakingFixture {
	t.Helper()
	if timeout == 0 {
		timeout = 2 * time.Second
	}
	f := &speakingFixture{stt: speakingfake.New(t, speakingKey, machine(t)), model: listeningfake.NewResponses(t, speakingKey, speakingFeedbackFixture(t))}
	f.dbPath = filepath.Join(t.TempDir(), "speaking.db")
	f.open(t, enabled, timeout)
	return f
}

// open (re)builds the handler over the same database file: a restart.
func (f *speakingFixture) open(t *testing.T, enabled bool, timeout time.Duration) {
	t.Helper()
	db, err := sqlite.Open(f.dbPath)
	if err != nil {
		t.Fatal(err)
	}
	var tr domain.SpeakingTranscriber
	var gen domain.SpeakingFeedbackGenerator
	if enabled {
		tr = speaking.NewTranscriber(speakingKey, "fake-transcribe", f.stt.URL(), timeout)
		gen = speaking.NewOpenAI(speakingKey, "fake-model", f.model.URL(), timeout)
	}
	svc, err := application.NewSpeakingService(sqlite.NewSpeakingRepository(db), tr, gen, speaking.ExamplePrompts(), application.WithSpeakingDeadline(timeout+30*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	entryRepo := sqlite.NewEntryRepository(db)
	analysisRepo := sqlite.NewAnalysisRepository(db)
	feedbackRepo := sqlite.NewFeedbackRepository(db)
	knowledgeRepo := sqlite.NewKnowledgeRepository(db)
	conceptRepo := sqlite.NewConceptRepository(db)
	annotation := application.NewEffectiveAnnotationService(conceptRepo, conceptRepo)
	handler := transporthttp.NewHandler(
		application.NewEntryService(entryRepo), application.NewAnalysisService(entryRepo, analysisRepo, nil),
		application.NewFeedbackService(feedbackRepo), application.NewEffectiveAnalysisService(analysisRepo, feedbackRepo),
		application.NewInventoryService(sqlite.NewInventoryRepository(db)), application.NewCaptureService(sqlite.NewCaptureRepository(db)),
		application.NewKnowledgeService(entryRepo, analysisRepo, feedbackRepo, knowledgeRepo, sqlite.NewAdmissionRepository(db), nil),
		application.NewConceptService(knowledgeRepo, conceptRepo, conceptRepo), annotation,
		application.NewConceptAnnotationDatasetService(annotation, knowledgeRepo, conceptRepo),
		transporthttp.WithSpeaking(svc),
	)
	if f.srv != nil {
		f.srv.Close()
		_ = f.db.Close()
	}
	f.db, f.routes = db, handler.Routes()
	f.srv = httptest.NewServer(f.routes)
	t.Cleanup(func() { f.srv.Close(); _ = f.db.Close() })
}

func (f *speakingFixture) start(t *testing.T) int64 {
	t.Helper()
	status, out := doJSON(t, http.MethodPost, f.srv.URL+"/speaking/prompts/sp-invitation-reponse", "")
	if status != http.StatusCreated && status != http.StatusOK {
		t.Fatalf("start: %d %v", status, out)
	}
	return int64(path(out, "exercise", "id").(float64))
}

// recordTake stores a take's metadata for audio (nil: a typed take).
func (f *speakingFixture) recordTake(t *testing.T, ex int64, audio []byte) (int64, map[string]any) {
	t.Helper()
	body := map[string]any{"audio_source": "none"}
	if audio != nil {
		body = map[string]any{"audio_source": "recording", "audio_mime": "audio/wav", "audio_bytes": len(audio), "audio_sha256": digest(audio), "duration_ms": 41_400}
	}
	raw, _ := json.Marshal(body)
	status, out := doJSON(t, http.MethodPost, fmt.Sprintf("%s/speaking/exercises/%d/takes", f.srv.URL, ex), string(raw))
	if status != http.StatusCreated {
		t.Fatalf("take: %d %v", status, out)
	}
	takes := out["takes"].([]any)
	return int64(path(takes[len(takes)-1], "id").(float64)), out
}

func (f *speakingFixture) transcribe(t *testing.T, take int64, key string, audio []byte, mime string, confirm bool) (int, map[string]any, http.Header) {
	t.Helper()
	raw, _ := json.Marshal(map[string]any{"audio_base64": base64.StdEncoding.EncodeToString(audio), "audio_mime": mime, "confirm_unknown_retry": confirm})
	status, out, hdr, err := keyed(t, http.DefaultClient, http.MethodPost, fmt.Sprintf("%s/speaking/takes/%d/transcriptions", f.srv.URL, take), key, string(raw))
	if err != nil {
		t.Fatal(err)
	}
	return status, out, hdr
}

func (f *speakingFixture) confirm(t *testing.T, take int64, text string, transcription any) (int, map[string]any) {
	t.Helper()
	raw, _ := json.Marshal(map[string]any{"text": text, "transcription_id": transcription})
	return doJSON(t, http.MethodPost, fmt.Sprintf("%s/speaking/takes/%d/transcripts", f.srv.URL, take), string(raw))
}

func (f *speakingFixture) feedback(t *testing.T, transcript int64, key, body string) (int, map[string]any) {
	t.Helper()
	status, out, _, err := keyed(t, http.DefaultClient, http.MethodPost, fmt.Sprintf("%s/speaking/transcripts/%d/feedback", f.srv.URL, transcript), key, body)
	if err != nil {
		t.Fatal(err)
	}
	return status, out
}

// transcriptID finds a take's version in an exercise view.
func transcriptID(view map[string]any, take int64, version int) int64 {
	for _, s := range view["transcripts"].([]any) {
		if path(s, "take_id") == float64(take) && path(s, "version") == float64(version) {
			return int64(path(s, "id").(float64))
		}
	}
	return 0
}

func improvementsGrounding(fb any) []string {
	out := []string{}
	for _, k := range path(fb, "content", "improvements").([]any) {
		out = append(out, path(k, "grounding").(string))
	}
	return out
}

func (f *speakingFixture) view(t *testing.T, ex int64) map[string]any {
	t.Helper()
	status, out := doJSON(t, http.MethodGet, fmt.Sprintf("%s/speaking/exercises/%d", f.srv.URL, ex), "")
	if status != http.StatusOK {
		t.Fatalf("view: %d %v", status, out)
	}
	return out
}

func TestSpeaking_WholeLoopFromTakeToVersionBoundFeedback(t *testing.T) {
	f := newSpeakingFixture(t, true, 0)
	_, prompts := doJSON(t, http.MethodGet, f.srv.URL+"/speaking/prompts", "")
	if len(prompts["prompts"].([]any)) != 3 || !strings.Contains(prompts["notice"].(string), "cannot judge pronunciation") ||
		path(prompts, "providers", "transcription", "name") != "openai:fake-transcribe:speaking_transcription_v1" ||
		path(prompts, "limits", "max_audio_bytes") != float64(domain.MaxSpeakingAudioBytes) {
		t.Fatalf("prompts = %v", prompts)
	}
	ex := f.start(t)
	if ex2 := f.start(t); ex2 != ex {
		t.Fatalf("starting again: %d vs %d", ex2, ex)
	}
	audio1 := synthAudio("take one", 48_000)
	take1, view := f.recordTake(t, ex, audio1)
	tk := view["takes"].([]any)[0]
	if path(tk, "number") != float64(1) || path(tk, "audio_sha256") != digest(audio1) || path(tk, "duration_ms") != float64(41_400) || f.stt.Calls() != 0 || f.model.Calls() != 0 {
		t.Fatalf("take = %v (calls %d/%d)", tk, f.stt.Calls(), f.model.Calls())
	}
	// One explicit transcription: the audio goes out once, as take.wav.
	status, res, _ := f.transcribe(t, take1, skeyA, audio1, "audio/wav", false)
	tr := res["transcription"]
	if status != http.StatusCreated || path(tr, "text") != machine(t) || path(res, "request", "state") != "completed" || f.stt.Calls() != 1 ||
		f.stt.Received()[0].AudioSHA256 != digest(audio1) || f.stt.Received()[0].Filename != "take.wav" {
		t.Fatalf("transcribe: %d %v", status, res)
	}
	trID := path(tr, "id")
	// The learner corrects the machine transcript and confirms it: version 1.
	status, view = f.confirm(t, take1, transcriptV1(t), trID)
	v1 := transcriptID(view, take1, 1)
	if status != http.StatusCreated || v1 == 0 || path(view["transcripts"].([]any)[0], "origin") != "corrected" {
		t.Fatalf("confirm v1: %d %v", status, view["transcripts"])
	}
	// Feedback on v1, grounded against v1's exact text.
	status, res = f.feedback(t, v1, skeyB, "")
	fb := res["feedback"]
	if status != http.StatusCreated || path(fb, "transcript_id") != float64(v1) || f.model.Calls() != 1 ||
		strings.Join(improvementsGrounding(fb), ",") != "located,located,ambiguous,not_found" || path(fb, "content", "task_fulfilment", "rating") != "partly_met" {
		t.Fatalf("feedback on v1: %d %v", status, res)
	}
	imps := path(fb, "content", "improvements").([]any)
	// Rune offsets in v1, also pinned in web/src/test/speakingFixture.ts.
	if path(imps[0], "start") != float64(100) || path(imps[1], "start") != float64(166) || path(imps[2], "start") != nil {
		t.Fatalf("locations: %v", imps)
	}
	// A further correction is version 2. The report stays on version 1.
	status, view = f.confirm(t, take1, transcriptV2(t), nil)
	v2 := transcriptID(view, take1, 2)
	scripts := view["transcripts"].([]any)
	if status != http.StatusCreated || len(scripts) != 2 || path(scripts[0], "text") != transcriptV1(t) || path(scripts[1], "origin") != "corrected" {
		t.Fatalf("v2: %d %v", status, scripts)
	}
	reports := view["feedback"].([]any)
	if v2 == 0 || len(reports) != 1 || path(reports[0], "transcript_id") != float64(v1) || f.model.Calls() != 1 {
		t.Fatalf("feedback after v2 = %v", reports)
	}
	if status, out := f.confirm(t, take1, transcriptV2(t), nil); status != http.StatusConflict || out["code"] != "unchanged" {
		t.Fatalf("unchanged: %d %v", status, out)
	}
	// A second take: its machine transcript confirmed unchanged.
	f.stt.SetText("Salut Léa, merci pour ton invitation. Oui, je viendrai samedi, j'arriverai vers midi et demi. Je vais apporter une tarte aux pommes.")
	audio2 := synthAudio("take two", 52_000)
	take2, _ := f.recordTake(t, ex, audio2)
	status, res, _ = f.transcribe(t, take2, skeyC, audio2, "audio/x-wav", false)
	if status != http.StatusCreated {
		t.Fatalf("take 2 transcription: %d %v", status, res)
	}
	status, view = f.confirm(t, take2, path(res, "transcription", "text").(string), path(res, "transcription", "id"))
	if status != http.StatusCreated || path(view["transcripts"].([]any)[2], "origin") != "transcription" || f.stt.Calls() != 2 || f.model.Calls() != 1 {
		t.Fatalf("take 2 confirm: %d %v", status, view["transcripts"])
	}
	// Capturing one recurring mistake through the existing path.
	doc, _ := json.Marshal(map[string]string{"schema_version": "learning_capture_v1", "capture_id": fmt.Sprintf("speaking-%d-%d-1-test", ex, v1), "source": "manual",
		"original_input":   "« je suis arrivé vers midi et demi » → « j'arriverai vers midi et demi »",
		"original_context": fmt.Sprintf("Speaking exercise #%d, take 1, transcript version 1", ex)})
	if status, receipt := doJSON(t, http.MethodPost, f.srv.URL+"/captures", string(doc)); status != http.StatusCreated || countRows(t, f.db, "knowledge_concepts") != 0 {
		t.Fatalf("capture: %d %v", status, receipt)
	}
	// Restart: everything reads back the same, with no provider call.
	before, _ := json.Marshal(f.view(t, ex))
	f.open(t, true, 0)
	after, _ := json.Marshal(f.view(t, ex))
	if !bytes.Equal(before, after) || f.stt.Calls() != 2 || f.model.Calls() != 1 {
		t.Fatalf("after restart:\n%s\n%s", before, after)
	}
}

func TestSpeaking_AudioIsCheckedBeforeAnyCallAndNeverStored(t *testing.T) {
	f := newSpeakingFixture(t, true, 0)
	ex := f.start(t)
	audio := synthAudio("the learner's take", 64_000)
	take, _ := f.recordTake(t, ex, audio)
	typed, _ := f.recordTake(t, ex, nil)
	other := synthAudio("someone else's take", 64_000)
	webm := append([]byte{0x1A, 0x45, 0xDF, 0xA3}, other[4:]...)
	for name, tc := range map[string]struct {
		take   int64
		audio  []byte
		mime   string
		status int
	}{
		"other audio":     {take, other, "audio/wav", http.StatusUnprocessableEntity},
		"ogg (one page)":  {take, audio, "audio/ogg", http.StatusUnprocessableEntity},
		"type vs content": {take, audio, "audio/webm", http.StatusUnprocessableEntity},
		"type vs take":    {take, webm, "audio/webm", http.StatusUnprocessableEntity},
		"just over limit": {take, synthAudio("big", domain.MaxSpeakingAudioBytes+1), "audio/wav", http.StatusUnprocessableEntity},
		"body over limit": {take, synthAudio("bigger", domain.MaxSpeakingAudioBytes+(1<<20)), "audio/wav", http.StatusRequestEntityTooLarge},
		"typed take":      {typed, audio, "audio/wav", http.StatusConflict},
		"unknown take":    {9999, audio, "audio/wav", http.StatusNotFound},
		"empty audio":     {take, []byte{}, "audio/wav", http.StatusUnprocessableEntity},
	} {
		if status, out, _ := f.transcribe(t, tc.take, "", tc.audio, tc.mime, false); status != tc.status {
			t.Errorf("%s: %d %v", name, status, out)
		}
	}
	if status, _, _, _ := keyed(t, http.DefaultClient, http.MethodPost, fmt.Sprintf("%s/speaking/takes/%d/transcriptions", f.srv.URL, take), "", `{"audio_base64":"not base64!","audio_mime":"audio/wav"}`); status != http.StatusBadRequest {
		t.Errorf("bad base64: %d", status)
	}
	if f.stt.Calls() != 0 || countRows(t, f.db, "speaking_transcription_requests") != 0 {
		t.Fatalf("refused audio reached the provider: %d calls, %d requests", f.stt.Calls(), countRows(t, f.db, "speaking_transcription_requests"))
	}
	if status, _, _ := f.transcribe(t, take, skeyA, audio, "audio/wav", false); status != http.StatusCreated || f.stt.Calls() != 1 {
		t.Fatalf("good audio: %d", status)
	}
	// No column can hold audio, and no 32-byte window of it is anywhere in the
	// database files (main file and write-ahead log).
	var schema string
	if err := f.db.QueryRow(`SELECT group_concat(sql, ' ') FROM sqlite_master WHERE name LIKE 'speaking_%'`).Scan(&schema); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(strings.ToUpper(schema), "BLOB") {
		t.Fatalf("a speaking table can hold binary data: %s", schema)
	}
	var stored []byte
	for _, suffix := range []string{"", "-wal"} {
		if raw, err := os.ReadFile(f.dbPath + suffix); err == nil {
			stored = append(stored, raw...)
		}
	}
	payload := audio[44:]
	encoded := base64.StdEncoding.EncodeToString(payload)
	for i := 0; i+32 <= len(payload); i += 1024 {
		if bytes.Contains(stored, payload[i:i+32]) || strings.Contains(string(stored), encoded[i:i+32]) {
			t.Fatalf("audio bytes found in the database at window %d", i)
		}
	}
	if !bytes.Contains(stored, []byte(digest(audio))) {
		t.Fatal("expected the audio digest (metadata) to be stored")
	}
}

func TestSpeaking_FailuresUnknownOutcomesAndRetriesAreExplicit(t *testing.T) {
	f := newSpeakingFixture(t, true, 300*time.Millisecond)
	ex := f.start(t)
	audio := synthAudio("take", 4_000)
	take, _ := f.recordTake(t, ex, audio)
	// Transcription: a failed request is stored; a dropped one is unknown.
	f.stt.Set(speakingfake.ModeStatus, http.StatusInternalServerError, 0)
	if status, res, _ := f.transcribe(t, take, "", audio, "audio/wav", false); status != http.StatusBadGateway || path(res, "transcription", "failure_code") != "provider_unavailable" {
		t.Fatalf("transcription 500: %d %v", status, res)
	}
	f.stt.Set(speakingfake.ModeDrop, 0, 0)
	if status, res, _ := f.transcribe(t, take, skeyA, audio, "audio/wav", false); status != http.StatusBadGateway || path(res, "request", "state") != "unknown" {
		t.Fatalf("transcription dropped: %d %v", status, res)
	}
	f.stt.Set(speakingfake.ModeOK, 0, 0)
	if status, res, _ := f.transcribe(t, take, skeyB, audio, "audio/wav", false); status != http.StatusConflict || res["code"] != "outcome_unknown" || f.stt.Calls() != 2 {
		t.Fatalf("unacknowledged: %d %v", status, res)
	}
	status, res, _ := f.transcribe(t, take, skeyB, audio, "audio/wav", true)
	if status != http.StatusCreated || path(res, "request", "after_unknown") != true || f.stt.Calls() != 3 {
		t.Fatalf("acknowledged: %d %v", status, res)
	}
	// The same key with other audio is a different request.
	if status, res, _ := f.transcribe(t, take, skeyB, synthAudio("other", 4_000), "audio/wav", false); status != http.StatusConflict || res["code"] != "key_conflict" || f.stt.Calls() != 3 {
		t.Fatalf("same key, other audio: %d %v", status, res)
	}
	_, view := f.confirm(t, take, transcriptV1(t), path(res, "transcription", "id"))
	v1 := transcriptID(view, take, 1)
	// Feedback: output that judges pronunciation is refused and stored as such.
	f.model.SetOutput(strings.Replace(speakingFeedbackFixture(t), `"comment_en": "The message is short`, `"comment_en": "Your pronunciation is clear and the message is short`, 1))
	if status, res := f.feedback(t, v1, "", ""); status != http.StatusBadGateway || path(res, "feedback", "failure_code") != "invalid_output" {
		t.Fatalf("pronunciation claim: %d %v", status, res)
	}
	f.model.SetOutput(speakingFeedbackFixture(t))
	f.model.Set(listeningfake.ModeHang, 0, time.Second)
	if status, res := f.feedback(t, v1, skeyC, ""); status != http.StatusGatewayTimeout || path(res, "request", "state") != "unknown" {
		t.Fatalf("timeout: %d %v", status, res)
	}
	f.model.Set(listeningfake.ModeOK, 0, 0)
	if status, res := f.feedback(t, v1, "", ""); status != http.StatusConflict || res["code"] != "outcome_unknown" || f.model.Calls() != 2 {
		t.Fatalf("unacknowledged feedback: %d %v", status, res)
	}
	// A new version is new input and is not blocked.
	_, view = f.confirm(t, take, transcriptV2(t), nil)
	v2 := transcriptID(view, take, 2)
	if status, _ := f.feedback(t, v2, "", ""); status != http.StatusCreated || f.model.Calls() != 3 {
		t.Fatalf("v2: %d", status)
	}
	if status, res := f.feedback(t, v1, "", `{"confirm_unknown_retry":true}`); status != http.StatusCreated || path(res, "request", "after_unknown") != true {
		t.Fatalf("acknowledged feedback: %d %v", status, res)
	}
	// A lost response: the client gives up, the call finishes and is found by key.
	f.model.Set(listeningfake.ModeHang, 0, 150*time.Millisecond)
	impatient := &http.Client{Timeout: 50 * time.Millisecond}
	if _, _, _, err := keyed(t, impatient, http.MethodPost, fmt.Sprintf("%s/speaking/transcripts/%d/feedback", f.srv.URL, v2), skeyD, ""); err == nil {
		t.Fatal("expected the client to give up")
	}
	var state any
	for i := 0; i < 50 && state != "completed"; i++ {
		_, got := doJSON(t, http.MethodGet, f.srv.URL+"/speaking/feedback-requests/"+skeyD, "")
		state = path(got, "request", "state")
		time.Sleep(20 * time.Millisecond)
	}
	status, _, hdr, _ := keyed(t, http.DefaultClient, http.MethodPost, fmt.Sprintf("%s/speaking/transcripts/%d/feedback", f.srv.URL, v2), skeyD, "")
	if state != "completed" || status != http.StatusOK || hdr.Get("Idempotency-Replayed") != "true" || f.model.Calls() != 5 {
		t.Fatalf("lost response: %v, resend %d (calls %d)", state, status, f.model.Calls())
	}
	if _, got := doJSON(t, http.MethodGet, f.srv.URL+"/speaking/transcription-requests/"+skeyB, ""); path(got, "request", "state") != "completed" {
		t.Fatalf("transcription lookup = %v", got)
	}
	// Every transcript is intact after every failure.
	scripts := f.view(t, ex)["transcripts"].([]any)
	if len(scripts) != 2 || path(scripts[0], "text") != transcriptV1(t) || path(scripts[1], "text") != transcriptV2(t) {
		t.Fatalf("transcripts after failures = %v", scripts)
	}
}

func TestSpeaking_TypedFlowWorksWithoutProvidersAndIsNotInTheDemo(t *testing.T) {
	f := newSpeakingFixture(t, false, 0)
	ex := f.start(t)
	take, _ := f.recordTake(t, ex, nil)
	status, view := f.confirm(t, take, speakingExample(t), nil)
	v1 := transcriptID(view, take, 1)
	if status != http.StatusCreated || path(view["transcripts"].([]any)[0], "origin") != "typed" || path(view, "providers", "feedback", "enabled") != false {
		t.Fatalf("typed: %d %v", status, view)
	}
	audio := synthAudio("x", 2_000)
	recorded, _ := f.recordTake(t, ex, audio)
	if status, _, _ := f.transcribe(t, recorded, "", audio, "audio/wav", false); status != http.StatusServiceUnavailable {
		t.Fatalf("disabled transcription: %d", status)
	}
	if status, _ := f.feedback(t, v1, "", ""); status != http.StatusServiceUnavailable {
		t.Fatalf("disabled feedback: %d", status)
	}
	if countRows(t, f.db, "speaking_transcription_requests")+countRows(t, f.db, "speaking_feedback_requests") != 0 || f.stt.Calls()+f.model.Calls() != 0 {
		t.Fatal("a disabled provider recorded or sent something")
	}
	for name, body := range map[string]string{
		"empty transcript":  `{"text":"  "}`,
		"oversized":         fmt.Sprintf(`{"text":%q}`, strings.Repeat("a", domain.MaxSpeakingTranscriptRunes+1)),
		"foreign machine":   fmt.Sprintf(`{"text":"x","transcription_id":%d}`, 9999),
		"unknown field":     `{"text":"x","score":3}`,
		"three minute take": `{"audio_source":"recording","audio_mime":"audio/webm","audio_bytes":10,"audio_sha256":"` + strings.Repeat("a", 64) + `","duration_ms":180000}`,
	} {
		url := fmt.Sprintf("%s/speaking/takes/%d/transcripts", f.srv.URL, take)
		if name == "three minute take" {
			url = fmt.Sprintf("%s/speaking/exercises/%d/takes", f.srv.URL, ex)
		}
		if status, out := doJSON(t, http.MethodPost, url, body); status != http.StatusUnprocessableEntity && status != http.StatusBadRequest && status != http.StatusNotFound {
			t.Errorf("%s: %d %v", name, status, out)
		}
	}
	demo := httptest.NewServer(transporthttp.NewPublicDemoBoundary(f.routes, false))
	t.Cleanup(demo.Close)
	for _, prefix := range []string{"", "/api"} {
		for _, p := range []string{"/speaking/prompts", "/speaking/exercises", "/speaking/exercises/1", "/speaking/feedback-requests/" + skeyA, "/speaking/transcription-requests/" + skeyA} {
			if status, _ := doJSON(t, http.MethodGet, demo.URL+prefix+p, ""); status != http.StatusNotFound {
				t.Errorf("GET %s%s in the demo: %d", prefix, p, status)
			}
		}
		for _, p := range []string{"/speaking/prompts/sp-invitation-reponse", "/speaking/exercises/1/takes", "/speaking/takes/1/transcriptions", "/speaking/takes/1/transcripts", "/speaking/transcripts/1/feedback"} {
			if status, _ := doJSON(t, http.MethodPost, demo.URL+prefix+p, "{}"); status != http.StatusMethodNotAllowed {
				t.Errorf("POST %s%s in the demo: %d", prefix, p, status)
			}
		}
	}
}
