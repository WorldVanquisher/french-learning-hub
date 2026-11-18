package speaking

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"strings"
	"time"

	"french-learning-app/internal/domain"
)

// maxTranscriptRunes bounds a machine transcript accepted from the provider.
// It equals the confirmed-transcript bound, so a machine transcript can always
// be confirmed unchanged.
const maxTranscriptRunes = domain.MaxSpeakingTranscriptRunes

// Transcriber is a domain.SpeakingTranscriber backed by an OpenAI-style
// transcription endpoint (POST {base}/audio/transcriptions, multipart): OpenAI's,
// or the local transcription service (NewLocalTranscriber). It makes
// one call per explicit request, audio held in memory only for that call.
// It sends the file (with a filename extension and Content-Type that identify
// its format), the operator's model and response_format=json, and nothing
// else: no language field (its name differs between models) and no prompt,
// so the transcript is not nudged towards the expected answer.
type Transcriber struct {
	provider string // provenance prefix: "openai" or "local"
	apiKey   string
	model    string
	baseURL  string
	client   *http.Client
}

var _ domain.SpeakingTranscriber = (*Transcriber)(nil)

// NewTranscriber builds a transcriber. timeout bounds one request (0: context only).
func NewTranscriber(apiKey, model, baseURL string, timeout time.Duration) *Transcriber {
	return &Transcriber{provider: "openai", apiKey: apiKey, model: model, baseURL: strings.TrimRight(baseURL, "/"), client: &http.Client{Timeout: timeout}}
}

// NewLocalTranscriber builds a transcriber for the local transcription service
// (tools/speaking, flh_speaking_transcription_v1), which speaks the same
// protocol. It sends no API key; model is the service's deployment_id, so the
// stored provenance names the exact local model, and a response must name that
// same deployment_id. Audio the service refuses (HTTP 413, 415 or 422) is
// unusable output, not an unavailable service: sending it again cannot help.
// A connection closed without an answer is a definite failure here, not an
// unknown outcome: the service bills nothing and keeps nothing, so a new
// request is safe (a container restarting behind a published port resets
// connections it has accepted). A timeout stays unknown: the service may still
// be working on the abandoned request.
func NewLocalTranscriber(deploymentID, baseURL string, timeout time.Duration) *Transcriber {
	return &Transcriber{provider: "local", model: deploymentID, baseURL: strings.TrimRight(baseURL, "/"), client: &http.Client{Timeout: timeout}}
}

// Name is the stored transcriber provenance.
func (t *Transcriber) Name() string {
	return fmt.Sprintf("%s:%s:%s", t.provider, t.model, domain.SpeakingTranscriptionVersion)
}

// Transcribe sends one take's audio and returns the machine transcript. An
// empty or oversized transcript is unusable output (ErrValidation).
func (t *Transcriber) Transcribe(ctx context.Context, in domain.SpeakingTranscriptionInput) (string, error) {
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	part, err := mw.CreatePart(textproto.MIMEHeader{
		"Content-Disposition": {fmt.Sprintf(`form-data; name="file"; filename="take.%s"`, in.Format.Extension)},
		"Content-Type":        {in.Format.MIME},
	})
	if err != nil {
		return "", fmt.Errorf("%w: encode audio", domain.ErrProviderUnavailable)
	}
	if _, err := part.Write(in.Audio); err != nil {
		return "", fmt.Errorf("%w: encode audio", domain.ErrProviderUnavailable)
	}
	for _, f := range [][2]string{{"model", t.model}, {"response_format", "json"}} {
		if err := mw.WriteField(f[0], f[1]); err != nil {
			return "", fmt.Errorf("%w: encode request", domain.ErrProviderUnavailable)
		}
	}
	if err := mw.Close(); err != nil {
		return "", fmt.Errorf("%w: encode request", domain.ErrProviderUnavailable)
	}
	body, err := send(ctx, t.client, t.baseURL+"/audio/transcriptions", mw.FormDataContentType(), t.apiKey, buf.Bytes())
	if err != nil {
		var se *statusError
		if t.provider == "local" && errors.As(err, &se) && (se.code == http.StatusRequestEntityTooLarge || se.code == http.StatusUnsupportedMediaType || se.code == http.StatusUnprocessableEntity) {
			return "", fmt.Errorf("%w: the transcription service refused this audio (HTTP %d)", domain.ErrValidation, se.code)
		}
		if t.provider == "local" && errors.Is(err, domain.ErrOutcomeUnknown) && !errors.Is(err, domain.ErrProviderTimeout) {
			return "", fmt.Errorf("%w: the transcription service closed the connection without an answer", domain.ErrProviderUnavailable)
		}
		return "", err
	}
	// Other documented fields (usage, languages, logprobs) are ignored.
	var parsed struct {
		Text  *string `json:"text"`
		Error *struct {
			Type string `json:"type"`
		} `json:"error"`
		FLH *struct {
			DeploymentID string `json:"deployment_id"`
		} `json:"flh"`
	}
	if err := json.Unmarshal(body, &parsed); err != nil {
		return "", fmt.Errorf("%w: transcription response is not JSON", domain.ErrValidation)
	}
	if parsed.Error != nil {
		return "", fmt.Errorf("%w: provider error (%s)", domain.ErrProviderUnavailable, parsed.Error.Type)
	}
	if t.provider == "local" && (parsed.FLH == nil || parsed.FLH.DeploymentID != t.model) {
		// The stored provenance would name a model that did not answer.
		return "", fmt.Errorf("%w: the transcription service did not answer as the configured deployment", domain.ErrProviderUnavailable)
	}
	if parsed.Text == nil {
		return "", fmt.Errorf("%w: transcription response has no text", domain.ErrValidation)
	}
	text, _, err := domain.NormalizeSpeakingTranscript(*parsed.Text)
	if err != nil {
		return "", fmt.Errorf("%w: no usable transcript (empty, oversized or with control characters)", domain.ErrValidation)
	}
	return text, nil
}
