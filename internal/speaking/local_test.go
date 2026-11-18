package speaking_test

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/config"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/listening/listeningfake"
	"french-learning-app/internal/speaking"
	"french-learning-app/internal/speaking/speakingfake"
)

const deployment = "whisper-base@e37978b90ca9/flh_speaking_transcribe_v1/cpu-fp32/0123456789abcdef"

func transcribeWAV(t *testing.T, tr domain.SpeakingTranscriber) (string, error) {
	t.Helper()
	return tr.Transcribe(context.Background(), domain.SpeakingTranscriptionInput{Audio: synthWAV(), Format: wavFormat(t)})
}

func TestLocalTranscriberSendsNoKeyAndNamesTheLocalModel(t *testing.T) {
	fake := speakingfake.NewLocal(t, deployment, "Bonjour.")
	tr := speaking.NewLocalTranscriber(deployment, fake.URL()+"/", time.Second)
	if tr.Name() != "local:"+deployment+":"+domain.SpeakingTranscriptionVersion {
		t.Fatalf("name = %q", tr.Name())
	}
	got, err := transcribeWAV(t, tr)
	r := fake.Received()
	if err != nil || got != "Bonjour." || len(r) != 1 || r[0].Auth != "" || len(r[0].Fields) != 2 ||
		r[0].Fields["model"] != deployment || r[0].Fields["response_format"] != "json" || r[0].Filename != "take.wav" {
		t.Fatalf("text %q err %v received %+v", got, err, r)
	}
	if speaking.NewTranscriber(key, "m", fake.URL(), time.Second).Name() != "openai:m:"+domain.SpeakingTranscriptionVersion {
		t.Fatal("openai provenance changed")
	}
}

// The stored provenance names the configured deployment, so an answer from any
// other deployment (or from a server that names none) is refused, never stored.
func TestLocalTranscriberRefusesAnAnswerFromAnotherDeployment(t *testing.T) {
	fake := speakingfake.NewLocal(t, deployment, "Bonjour.")
	fake.SetDeployment("whisper-small@973afd24965f/flh_speaking_transcribe_v1/cpu-fp32/fedcba9876543210")
	_, err := transcribeWAV(t, speaking.NewLocalTranscriber(deployment, fake.URL(), time.Second))
	if !errors.Is(err, domain.ErrProviderUnavailable) || errors.Is(err, domain.ErrOutcomeUnknown) {
		t.Fatalf("other deployment: %v", err)
	}
	plain := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		_, _ = io.WriteString(w, `{"text":"Bonjour."}`)
	}))
	t.Cleanup(plain.Close)
	_, err = transcribeWAV(t, speaking.NewLocalTranscriber(deployment, plain.URL, time.Second))
	if !errors.Is(err, domain.ErrProviderUnavailable) {
		t.Fatalf("no flh block: %v", err)
	}
	// The OpenAI transcriber never asks for the block.
	if text, err := transcribeWAV(t, speaking.NewTranscriber(key, "m", plain.URL, time.Second)); err != nil || text != "Bonjour." {
		t.Fatalf("openai: %q %v", text, err)
	}
}

// Each service answer maps to one stored failure code (provider_timeout,
// provider_unavailable, invalid_output) and one outcome: definite, or unknown when the
// audio was sent and no answer came back.
func TestLocalTranscriberFailureStates(t *testing.T) {
	for name, tc := range map[string]struct {
		mode    string
		status  int
		delay   time.Duration
		is      error
		code    string
		unknown bool
	}{
		"413 audio too large":   {speakingfake.ModeStatus, http.StatusRequestEntityTooLarge, 0, domain.ErrValidation, "invalid_output", false},
		"415 unsupported audio": {speakingfake.ModeStatus, http.StatusUnsupportedMediaType, 0, domain.ErrValidation, "invalid_output", false},
		"422 undecodable/long":  {speakingfake.ModeStatus, http.StatusUnprocessableEntity, 0, domain.ErrValidation, "invalid_output", false},
		"400 unknown model":     {speakingfake.ModeStatus, http.StatusBadRequest, 0, domain.ErrProviderUnavailable, "provider_unavailable", false},
		"429 busy":              {speakingfake.ModeStatus, http.StatusTooManyRequests, 0, domain.ErrProviderUnavailable, "provider_unavailable", false},
		"503 loading":           {speakingfake.ModeStatus, http.StatusServiceUnavailable, 0, domain.ErrProviderUnavailable, "provider_unavailable", false},
		"504 service deadline":  {speakingfake.ModeStatus, http.StatusGatewayTimeout, 0, domain.ErrProviderUnavailable, "provider_unavailable", false},
		"no speech (empty)":     {speakingfake.ModeEmpty, 0, 0, domain.ErrValidation, "invalid_output", false},
		"malformed":             {speakingfake.ModeMalformed, 0, 0, domain.ErrValidation, "invalid_output", false},
		"slow: client timeout":  {speakingfake.ModeHang, 0, time.Second, domain.ErrProviderTimeout, "provider_timeout", true},
		// Nothing is billed or kept by the local service, so a lost answer is definite.
		"dropped after sending": {speakingfake.ModeDrop, 0, 0, domain.ErrProviderUnavailable, "provider_unavailable", false},
	} {
		t.Run(name, func(t *testing.T) {
			fake := speakingfake.NewLocal(t, deployment, "texte")
			fake.Set(tc.mode, tc.status, tc.delay)
			_, err := transcribeWAV(t, speaking.NewLocalTranscriber(deployment, fake.URL(), 200*time.Millisecond))
			unknown := domain.PreparationOutcome(err) == domain.ListeningOutcomeUnknown
			if !errors.Is(err, tc.is) || domain.SpeakingFailureCode(err) != tc.code || unknown != tc.unknown || strings.Contains(err.Error(), "fake failure") {
				t.Fatalf("err = %v (code %s, unknown %v)", err, domain.SpeakingFailureCode(err), unknown)
			}
		})
	}
	// Not started (connection refused): never sent, a definite failure.
	dead := httptest.NewServer(http.NotFoundHandler())
	url := dead.URL
	dead.Close()
	_, err := transcribeWAV(t, speaking.NewLocalTranscriber(deployment, url, time.Second))
	if !errors.Is(err, domain.ErrProviderUnavailable) || domain.PreparationOutcome(err) != domain.ListeningOutcomeFailed {
		t.Fatalf("connection refused: %v", err)
	}
	// The OpenAI transcriber keeps its mapping: a lost answer stays unknown
	// (it may have been billed), and a 422 there stays unavailable.
	drop := speakingfake.New(t, key, "texte")
	drop.Set(speakingfake.ModeDrop, 0, 0)
	if _, err := transcribeWAV(t, speaking.NewTranscriber(key, "m", drop.URL(), time.Second)); !errors.Is(err, domain.ErrOutcomeUnknown) {
		t.Fatalf("openai drop: %v", err)
	}
	fake := speakingfake.New(t, key, "texte")
	fake.Set(speakingfake.ModeStatus, http.StatusUnprocessableEntity, 0)
	if _, err := transcribeWAV(t, speaking.NewTranscriber(key, "m", fake.URL(), time.Second)); !errors.Is(err, domain.ErrProviderUnavailable) {
		t.Fatalf("openai 422: %v", err)
	}
}

// Local transcription and OpenAI feedback run in one process: each uses its
// own base URL, credentials and timeout from the same configuration.
func TestNewWiresLocalTranscriptionBesideOpenAIFeedback(t *testing.T) {
	stt := speakingfake.NewLocal(t, deployment, "Salut Léa.")
	model := listeningfake.NewResponses(t, key, fixture(t))
	cfg := config.SpeakingConfig{
		Feedback: config.SpeakingOpenAI, Transcription: config.SpeakingLocal, TranscriptionModel: deployment,
		TranscriptionBaseURL: stt.URL() + "/v1", TranscriptionTimeout: 300 * time.Millisecond,
		OpenAIAPIKey: key, OpenAIModel: "gpt-test", OpenAIBaseURL: model.URL(), OpenAITimeout: 5 * time.Second,
	}
	// The fake serves /audio/transcriptions; route /v1/... to it like the real service.
	mux := http.NewServeMux()
	mux.Handle("/v1/", http.StripPrefix("/v1", stt.Server.Config.Handler))
	front := httptest.NewServer(mux)
	t.Cleanup(front.Close)
	cfg.TranscriptionBaseURL = front.URL + "/v1"
	tr, gen, err := speaking.New(cfg)
	if err != nil || tr == nil || gen == nil {
		t.Fatalf("new: %v %v %v", tr, gen, err)
	}
	if tr.Name() != "local:"+deployment+":speaking_transcription_v1" || gen.Name() != "openai:gpt-test:speaking_feedback_v1" {
		t.Fatalf("names %s / %s", tr.Name(), gen.Name())
	}
	if text, err := transcribeWAV(t, tr); err != nil || text != "Salut Léa." || stt.Received()[0].Auth != "" || model.Calls() != 0 {
		t.Fatalf("transcribe: %q %v %+v", text, err, stt.Received())
	}
	if _, err := gen.Generate(context.Background(), domain.SpeakingFeedbackInput{Transcript: example(t)}); err != nil || model.Calls() != 1 || stt.Calls() != 1 {
		t.Fatalf("feedback: %v (calls %d/%d)", err, model.Calls(), stt.Calls())
	}
	// SPEAKING_TRANSCRIPTION_TIMEOUT, not OPENAI_TIMEOUT, bounds the local call.
	stt.Set(speakingfake.ModeHang, 0, 3*time.Second)
	start := time.Now()
	if _, err := transcribeWAV(t, tr); !errors.Is(err, domain.ErrProviderTimeout) || time.Since(start) > 2*time.Second {
		t.Fatalf("timeout: %v after %v", err, time.Since(start))
	}
	// Local transcription alone needs no OpenAI key at all.
	tr, gen, err = speaking.New(config.SpeakingConfig{Transcription: config.SpeakingLocal, TranscriptionModel: deployment, TranscriptionBaseURL: front.URL + "/v1", TranscriptionTimeout: time.Second, Feedback: config.SpeakingDisabled})
	if err != nil || tr == nil || gen != nil {
		t.Fatalf("local only: %v %v %v", tr, gen, err)
	}
}
