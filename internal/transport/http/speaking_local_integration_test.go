package http_test

// Speaking v1 with SPEAKING_TRANSCRIPTION_PROVIDER=local, end to end through
// the normal Speaking API: config → speaking.New → service → handler, against
// a stand-in for the local transcription service (speakingfake.NewLocal) on a
// listener the test can stop and restart at the same address, and OpenAI
// feedback (listeningfake) configured in the same process. Real inference
// against the pretrained Whisper service is recorded separately
// (docs/validation/SPEAKING-LOCAL-PROVIDER/real-inference/).

import (
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/config"
	"french-learning-app/internal/listening/listeningfake"
	"french-learning-app/internal/speaking"
	"french-learning-app/internal/speaking/speakingfake"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

const localDeployment = "whisper-base@e37978b90ca9/flh_speaking_transcribe_v1/cpu-fp32/0123456789abcdef"

// restartable serves a handler on one loopback address that can be stopped
// (connection refused) and started again at the same address.
type restartable struct {
	addr string
	h    http.Handler
	srv  *http.Server
}

func newRestartable(t *testing.T, h http.Handler) *restartable {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	r := &restartable{addr: l.Addr().String(), h: h}
	r.serve(l)
	t.Cleanup(func() { _ = r.srv.Close() })
	return r
}

func (r *restartable) serve(l net.Listener) {
	r.srv = &http.Server{Handler: r.h, ReadHeaderTimeout: 5 * time.Second}
	go func() { _ = r.srv.Serve(l) }()
}

func (r *restartable) stop() { _ = r.srv.Close() }

func (r *restartable) start(t *testing.T) {
	t.Helper()
	var l net.Listener
	var err error
	for i := 0; i < 100; i++ {
		if l, err = net.Listen("tcp", r.addr); err == nil {
			r.serve(l)
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("restart on %s: %v", r.addr, err)
}

// newLocalSpeakingFixture wires Speaking from configuration, as cmd/server does.
func newLocalSpeakingFixture(t *testing.T, timeout time.Duration) (*speakingFixture, *restartable) {
	t.Helper()
	f := &speakingFixture{stt: speakingfake.NewLocal(t, localDeployment, machine(t)), model: listeningfake.NewResponses(t, speakingKey, speakingFeedbackFixture(t))}
	mux := http.NewServeMux()
	mux.Handle("/v1/", http.StripPrefix("/v1", f.stt.Server.Config.Handler))
	svcFront := newRestartable(t, mux)
	cfg := config.SpeakingConfig{
		Transcription: config.SpeakingLocal, TranscriptionModel: localDeployment,
		TranscriptionBaseURL: "http://" + svcFront.addr + "/v1", TranscriptionTimeout: timeout,
		Feedback: config.SpeakingOpenAI, OpenAIAPIKey: speakingKey, OpenAIModel: "fake-model", OpenAIBaseURL: f.model.URL(), OpenAITimeout: 2 * time.Second,
	}
	tr, gen, err := speaking.New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	f.dbPath = filepath.Join(t.TempDir(), "speaking-local.db")
	db, err := sqlite.Open(f.dbPath)
	if err != nil {
		t.Fatal(err)
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
	f.db, f.routes = db, handler.Routes()
	f.srv = httptest.NewServer(f.routes)
	t.Cleanup(func() { f.srv.Close(); _ = f.db.Close() })
	return f, svcFront
}

func TestSpeakingLocal_TranscriptionThroughTheNormalAPIBesideOpenAIFeedback(t *testing.T) {
	f, _ := newLocalSpeakingFixture(t, 2*time.Second)
	_, prompts := doJSON(t, http.MethodGet, f.srv.URL+"/speaking/prompts", "")
	if path(prompts, "providers", "transcription", "name") != "local:"+localDeployment+":speaking_transcription_v1" ||
		path(prompts, "providers", "feedback", "name") != "openai:fake-model:speaking_feedback_v1" {
		t.Fatalf("providers = %v", prompts["providers"])
	}
	ex := f.start(t)
	audio := synthAudio("local take", 48_000)
	take, _ := f.recordTake(t, ex, audio)
	status, res, hdr := f.transcribe(t, take, skeyA, audio, "audio/wav", false)
	tr := res["transcription"]
	if status != http.StatusCreated || path(tr, "transcriber") != "local:"+localDeployment+":speaking_transcription_v1" || path(tr, "text") != machine(t) ||
		hdr.Get("Idempotency-Key") != skeyA || f.stt.Calls() != 1 || f.stt.Received()[0].Auth != "" || f.stt.Received()[0].Fields["model"] != localDeployment {
		t.Fatalf("transcribe: %d %v %+v", status, res, f.stt.Received())
	}
	// The same key replays the stored result; the service is not called again.
	status, again, hdr := f.transcribe(t, take, skeyA, audio, "audio/wav", false)
	if status != http.StatusOK || hdr.Get("Idempotency-Replayed") != "true" || path(again, "transcription", "id") != path(tr, "id") || f.stt.Calls() != 1 {
		t.Fatalf("replay: %d %v (calls %d)", status, again, f.stt.Calls())
	}
	// A machine transcript is not a transcript until the learner confirms it.
	view := f.view(t, ex)
	if len(view["transcripts"].([]any)) != 0 {
		t.Fatalf("transcripts before confirmation: %v", view["transcripts"])
	}
	status, view = f.confirm(t, take, machine(t), path(tr, "id"))
	v1 := view["transcripts"].([]any)[0]
	if status != http.StatusCreated || path(v1, "origin") != "transcription" || path(v1, "transcription_id") != path(tr, "id") {
		t.Fatalf("confirm unchanged: %d %v", status, view["transcripts"])
	}
	status, view = f.confirm(t, take, transcriptV2(t), path(tr, "id"))
	v2 := transcriptID(view, take, 2)
	if status != http.StatusCreated || v2 == 0 || path(view["transcripts"].([]any)[1], "origin") != "corrected" {
		t.Fatalf("confirm corrected: %d %v", status, view["transcripts"])
	}
	// The saved result keeps the local provenance; feedback goes to OpenAI with
	// its own key while transcription never carried one.
	if trs := view["transcriptions"].([]any); len(trs) != 1 || path(trs[0], "transcriber") != "local:"+localDeployment+":speaking_transcription_v1" {
		t.Fatalf("stored transcriptions = %v", trs)
	}
	status, fb := f.feedback(t, v2, skeyB, "")
	if status != http.StatusCreated || path(fb, "feedback", "generator") != "openai:fake-model:speaking_feedback_v1" || f.model.Calls() != 1 || f.stt.Calls() != 1 {
		t.Fatalf("feedback: %d %v", status, fb)
	}
}

func TestSpeakingLocal_ServiceStopsRestartsAndRecovers(t *testing.T) {
	f, svc := newLocalSpeakingFixture(t, 500*time.Millisecond)
	ex := f.start(t)
	audio := synthAudio("restart take", 32_000)
	take, _ := f.recordTake(t, ex, audio)
	failed := func(key string, confirm bool, want int, code string) map[string]any {
		t.Helper()
		status, res, _ := f.transcribe(t, take, key, audio, "audio/wav", confirm)
		if status != want || (code != "" && path(res, "transcription", "failure_code") != code) {
			t.Fatalf("%s: %d %v", key, status, res)
		}
		return res
	}
	// Stopped: nothing is sent, a definite failure, and a new click is allowed at once.
	svc.stop()
	res := failed(skeyA, false, http.StatusBadGateway, "provider_unavailable")
	if path(res, "request", "state") != "failed" || f.stt.Calls() != 0 {
		t.Fatalf("stopped: %v", res)
	}
	// Restarted but still loading the model (503 not_ready).
	svc.start(t)
	f.stt.Set(speakingfake.ModeStatus, http.StatusServiceUnavailable, 0)
	failed(skeyB, false, http.StatusBadGateway, "provider_unavailable")
	// Ready: the next explicit request succeeds with no acknowledgement needed.
	f.stt.Set(speakingfake.ModeOK, 0, 0)
	status, res, _ := f.transcribe(t, take, skeyC, audio, "audio/wav", false)
	if status != http.StatusCreated || path(res, "transcription", "status") != "completed" {
		t.Fatalf("after restart: %d %v", status, res)
	}
	// Restarted with other weights: the answer names another deployment and is refused.
	f.stt.SetDeployment("whisper-small@973afd24965f/flh_speaking_transcribe_v1/cpu-fp32/fedcba9876543210")
	res = failed(skeyD, false, http.StatusBadGateway, "provider_unavailable")
	if path(res, "transcription", "text") != nil {
		t.Fatalf("a foreign deployment's text was stored: %v", res)
	}
	f.stt.SetDeployment(localDeployment)
	// A restarting container behind a published port accepts, then drops the
	// connection: a definite failure for the local provider, so the next click
	// needs no acknowledgement (nothing was billed or kept).
	f.stt.Set(speakingfake.ModeDrop, 0, 0)
	res = failed("c8888888-8888-4888-8888-888888888888", false, http.StatusBadGateway, "provider_unavailable")
	if path(res, "request", "state") != "failed" {
		t.Fatalf("dropped: %v", res)
	}
	f.stt.Set(speakingfake.ModeOK, 0, 0)
	if status, res, _ := f.transcribe(t, take, "c9999999-9999-4999-8999-999999999999", audio, "audio/wav", false); status != http.StatusCreated {
		t.Fatalf("after a dropped answer: %d %v", status, res)
	}
	// Slow inference past SPEAKING_TRANSCRIPTION_TIMEOUT: the audio was sent, so the
	// outcome is unknown and a new request needs the learner's acknowledgement.
	f.stt.Set(speakingfake.ModeHang, 0, 2*time.Second)
	keyE, keyF, keyG := "c5555555-5555-4555-8555-555555555555", "c6666666-6666-4666-8666-666666666666", "c7777777-7777-4777-8777-777777777777"
	res = failed(keyE, false, http.StatusGatewayTimeout, "provider_timeout")
	if path(res, "request", "state") != "unknown" {
		t.Fatalf("timeout state: %v", res)
	}
	f.stt.Set(speakingfake.ModeOK, 0, 0)
	calls := f.stt.Calls()
	if status, res, _ := f.transcribe(t, take, keyF, audio, "audio/wav", false); status != http.StatusConflict || res["code"] != "outcome_unknown" || f.stt.Calls() != calls {
		t.Fatalf("retry without acknowledgement: %d %v", status, res)
	}
	if status, res, _ := f.transcribe(t, take, keyG, audio, "audio/wav", true); status != http.StatusCreated || path(res, "request", "after_unknown") != true {
		t.Fatalf("acknowledged retry: %d %v", status, res)
	}
}

func TestSpeakingLocal_DuplicateSubmissionWhileInferenceRuns(t *testing.T) {
	f, _ := newLocalSpeakingFixture(t, 3*time.Second)
	ex := f.start(t)
	audio := synthAudio("slow take", 32_000)
	take, _ := f.recordTake(t, ex, audio)
	f.stt.Set(speakingfake.ModeHang, 0, 700*time.Millisecond)
	type result struct {
		status int
		res    map[string]any
	}
	first := make(chan result, 1)
	go func() {
		raw, _ := json.Marshal(map[string]any{"audio_base64": audio, "audio_mime": "audio/wav"})
		status, res, _, _ := keyed(t, http.DefaultClient, http.MethodPost, fmt.Sprintf("%s/speaking/takes/%d/transcriptions", f.srv.URL, take), skeyA, string(raw))
		first <- result{status, res}
	}()
	<-f.stt.Arrived
	// A second click with another key while the first runs: refused, not sent.
	status, res, _ := f.transcribe(t, take, skeyB, audio, "audio/wav", false)
	if status != http.StatusConflict || res["code"] != "request_in_progress" || f.stt.Calls() != 1 {
		t.Fatalf("second click: %d %v", status, res)
	}
	// The same key while it runs is the same request: replayed as in progress, not sent again.
	status, res, hdr := f.transcribe(t, take, skeyA, audio, "audio/wav", false)
	if status != http.StatusOK || hdr.Get("Idempotency-Replayed") != "true" || path(res, "request", "state") != "in_progress" || res["transcription"] != nil || f.stt.Calls() != 1 {
		t.Fatalf("same key while running: %d %v", status, res)
	}
	got := <-first
	if got.status != http.StatusCreated || f.stt.Calls() != 1 {
		t.Fatalf("first: %d %v", got.status, got.res)
	}
	status, res, hdr = f.transcribe(t, take, skeyA, audio, "audio/wav", false)
	if status != http.StatusOK || hdr.Get("Idempotency-Replayed") != "true" || path(res, "transcription", "status") != "completed" || f.stt.Calls() != 1 {
		t.Fatalf("replay after completion: %d %v", status, res)
	}
}
