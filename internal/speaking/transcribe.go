package speaking

import (
	"bytes"
	"context"
	"encoding/json"
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

// Transcriber is a domain.SpeakingTranscriber backed by the OpenAI
// transcription endpoint (POST {base}/audio/transcriptions, multipart):
// one call per explicit request, audio held in memory only for that call.
// It sends the file (with a filename extension and Content-Type that identify
// its format), the operator's model and response_format=json, and nothing
// else: no language field (its name differs between models) and no prompt,
// so the transcript is not nudged towards the expected answer.
type Transcriber struct {
	apiKey  string
	model   string
	baseURL string
	client  *http.Client
}

var _ domain.SpeakingTranscriber = (*Transcriber)(nil)

// NewTranscriber builds a transcriber. timeout bounds one request (0: context only).
func NewTranscriber(apiKey, model, baseURL string, timeout time.Duration) *Transcriber {
	return &Transcriber{apiKey: apiKey, model: model, baseURL: strings.TrimRight(baseURL, "/"), client: &http.Client{Timeout: timeout}}
}

// Name is the stored transcriber provenance.
func (t *Transcriber) Name() string {
	return fmt.Sprintf("openai:%s:%s", t.model, domain.SpeakingTranscriptionVersion)
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
		return "", err
	}
	// Other documented fields (usage, languages, logprobs) are ignored.
	var parsed struct {
		Text  *string `json:"text"`
		Error *struct {
			Type string `json:"type"`
		} `json:"error"`
	}
	if err := json.Unmarshal(body, &parsed); err != nil {
		return "", fmt.Errorf("%w: transcription response is not JSON", domain.ErrValidation)
	}
	if parsed.Error != nil {
		return "", fmt.Errorf("%w: provider error (%s)", domain.ErrProviderUnavailable, parsed.Error.Type)
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
