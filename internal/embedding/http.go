package embedding

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"strings"
	"time"

	"french-learning-app/internal/application"
)

const maxEmbeddingResponseBytes = 16 << 20 // 16 MiB

// HTTPProvider calls an OpenAI-compatible batch embeddings endpoint. The base
// URL may refer to a hosted API, rented compute, or a service on another local
// machine; the semantic retriever is unaware of that deployment choice.
type HTTPProvider struct {
	apiKey  string
	model   string
	baseURL string
	client  *http.Client
}

var _ application.EmbeddingProvider = (*HTTPProvider)(nil)

func NewHTTPProvider(apiKey, model, baseURL string, timeout time.Duration) *HTTPProvider {
	return &HTTPProvider{
		apiKey: apiKey, model: model, baseURL: strings.TrimRight(baseURL, "/"),
		client: &http.Client{Timeout: timeout},
	}
}

func NewHTTPProviderWithClient(apiKey, model, baseURL string, client *http.Client) *HTTPProvider {
	return &HTTPProvider{
		apiKey: apiKey, model: model, baseURL: strings.TrimRight(baseURL, "/"), client: client,
	}
}

func (p *HTTPProvider) Name() string {
	return fmt.Sprintf("http:%s", p.model)
}

type embeddingRequest struct {
	Model string   `json:"model"`
	Input []string `json:"input"`
}

type embeddingResponse struct {
	Data  []embeddingResponseItem `json:"data"`
	Error *struct {
		Type string `json:"type"`
	} `json:"error"`
}

type embeddingResponseItem struct {
	Index     int       `json:"index"`
	Embedding []float64 `json:"embedding"`
}

func (p *HTTPProvider) Embed(ctx context.Context, texts []string) ([][]float64, error) {
	if len(texts) == 0 {
		return make([][]float64, 0), nil
	}
	raw, err := json.Marshal(embeddingRequest{Model: p.model, Input: texts})
	if err != nil {
		return nil, fmt.Errorf("%w: encode request", application.ErrEmbeddingProviderUnavailable)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, p.baseURL+"/embeddings", bytes.NewReader(raw))
	if err != nil {
		return nil, fmt.Errorf("%w: build request", application.ErrEmbeddingProviderUnavailable)
	}
	req.Header.Set("Content-Type", "application/json")
	if strings.TrimSpace(p.apiKey) != "" {
		req.Header.Set("Authorization", "Bearer "+p.apiKey)
	}

	response, err := p.client.Do(req)
	if err != nil {
		if errors.Is(err, context.DeadlineExceeded) || errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return nil, fmt.Errorf("%w: request deadline exceeded", application.ErrEmbeddingProviderTimeout)
		}
		if errors.Is(ctx.Err(), context.Canceled) {
			return nil, fmt.Errorf("%w: request canceled", application.ErrEmbeddingProviderUnavailable)
		}
		return nil, fmt.Errorf("%w: request failed", application.ErrEmbeddingProviderUnavailable)
	}
	defer response.Body.Close()

	body, err := io.ReadAll(io.LimitReader(response.Body, maxEmbeddingResponseBytes+1))
	if err != nil {
		if errors.Is(err, context.DeadlineExceeded) || errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return nil, fmt.Errorf("%w: reading response timed out", application.ErrEmbeddingProviderTimeout)
		}
		return nil, fmt.Errorf("%w: reading response body", application.ErrEmbeddingProviderUnavailable)
	}
	if len(body) > maxEmbeddingResponseBytes {
		return nil, fmt.Errorf("%w: response exceeded size limit", application.ErrEmbeddingProviderUnavailable)
	}
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("%w: provider returned HTTP %d", application.ErrEmbeddingProviderUnavailable, response.StatusCode)
	}

	var parsed embeddingResponse
	if err := json.Unmarshal(body, &parsed); err != nil {
		return nil, fmt.Errorf("%w: malformed response JSON", application.ErrEmbeddingProviderUnavailable)
	}
	if parsed.Error != nil {
		return nil, fmt.Errorf("%w: provider error (%s)", application.ErrEmbeddingProviderUnavailable, parsed.Error.Type)
	}
	if len(parsed.Data) != len(texts) {
		return nil, fmt.Errorf("%w: provider returned %d vectors for %d texts", application.ErrEmbeddingProviderUnavailable, len(parsed.Data), len(texts))
	}

	vectors := make([][]float64, len(texts))
	seen := make([]bool, len(texts))
	dimensions := -1
	for _, item := range parsed.Data {
		if item.Index < 0 || item.Index >= len(texts) || seen[item.Index] {
			return nil, fmt.Errorf("%w: provider returned invalid vector index", application.ErrEmbeddingProviderUnavailable)
		}
		if len(item.Embedding) == 0 {
			return nil, fmt.Errorf("%w: provider returned an empty vector", application.ErrEmbeddingProviderUnavailable)
		}
		if dimensions == -1 {
			dimensions = len(item.Embedding)
		} else if len(item.Embedding) != dimensions {
			return nil, fmt.Errorf("%w: provider returned inconsistent vector dimensions", application.ErrEmbeddingProviderUnavailable)
		}
		for _, value := range item.Embedding {
			if math.IsNaN(value) || math.IsInf(value, 0) {
				return nil, fmt.Errorf("%w: provider returned a non-finite vector", application.ErrEmbeddingProviderUnavailable)
			}
		}
		seen[item.Index] = true
		vectors[item.Index] = append([]float64(nil), item.Embedding...)
	}
	return vectors, nil
}
