// Package vectorindex contains the disposable vector-store adapter used by the
// semantic index (FLH-040). It speaks Qdrant's REST API with the standard
// library only, owns no Concept authority, and maps every failure to an
// application error category without exposing response bodies or keys.
package vectorindex

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"french-learning-app/internal/application"
)

const maxResponseBytes = 32 << 20

// Qdrant is a single-instance Qdrant client.
type Qdrant struct {
	baseURL string
	apiKey  string
	client  *http.Client
}

var _ application.VectorIndex = (*Qdrant)(nil)

func NewQdrant(baseURL, apiKey string, timeout time.Duration) *Qdrant {
	return NewQdrantWithClient(baseURL, apiKey, &http.Client{Timeout: timeout})
}

func NewQdrantWithClient(baseURL, apiKey string, client *http.Client) *Qdrant {
	return &Qdrant{baseURL: strings.TrimRight(baseURL, "/"), apiKey: apiKey, client: client}
}

type qdrantEnvelope struct {
	Result json.RawMessage `json:"result"`
	Status json.RawMessage `json:"status"`
}

// do sends one request and returns the HTTP status and the "result" field.
func (q *Qdrant) do(ctx context.Context, method, path string, body any) (int, json.RawMessage, error) {
	var reader io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			return 0, nil, fmt.Errorf("%w: encode request", application.ErrVectorIndexUnavailable)
		}
		reader = bytes.NewReader(raw)
	}
	req, err := http.NewRequestWithContext(ctx, method, q.baseURL+path, reader)
	if err != nil {
		return 0, nil, fmt.Errorf("%w: build request", application.ErrVectorIndexUnavailable)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if q.apiKey != "" {
		req.Header.Set("api-key", q.apiKey)
	}
	resp, err := q.client.Do(req)
	if err != nil {
		return 0, nil, classify(ctx, err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, maxResponseBytes+1))
	if err != nil {
		return 0, nil, classify(ctx, err)
	}
	if len(raw) > maxResponseBytes {
		return 0, nil, fmt.Errorf("%w: response exceeded size limit", application.ErrVectorIndexUnavailable)
	}
	if resp.StatusCode == http.StatusNotFound {
		return resp.StatusCode, nil, nil
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return resp.StatusCode, nil, fmt.Errorf("%w: qdrant returned HTTP %d", application.ErrVectorIndexUnavailable, resp.StatusCode)
	}
	var env qdrantEnvelope
	if err := json.Unmarshal(raw, &env); err != nil {
		return resp.StatusCode, nil, fmt.Errorf("%w: malformed response", application.ErrVectorIndexUnavailable)
	}
	return resp.StatusCode, env.Result, nil
}

func classify(ctx context.Context, err error) error {
	if ctx.Err() != nil {
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return fmt.Errorf("%w: %w", application.ErrVectorIndexTimeout, ctx.Err())
		}
		return fmt.Errorf("%w: %w", application.ErrVectorIndexUnavailable, ctx.Err())
	}
	var timeout interface{ Timeout() bool }
	if errors.As(err, &timeout) && timeout.Timeout() {
		return fmt.Errorf("%w: request timed out", application.ErrVectorIndexTimeout)
	}
	return fmt.Errorf("%w: request failed", application.ErrVectorIndexUnavailable)
}

func collectionPath(collection string) string {
	return "/collections/" + url.PathEscape(collection)
}

func (q *Qdrant) CollectionInfo(ctx context.Context, collection string) (application.VectorCollectionInfo, error) {
	status, result, err := q.do(ctx, http.MethodGet, collectionPath(collection), nil)
	if err != nil {
		return application.VectorCollectionInfo{}, err
	}
	if status == http.StatusNotFound {
		return application.VectorCollectionInfo{Exists: false}, nil
	}
	var info struct {
		Config struct {
			Params struct {
				Vectors json.RawMessage `json:"vectors"`
			} `json:"params"`
		} `json:"config"`
	}
	if err := json.Unmarshal(result, &info); err != nil {
		return application.VectorCollectionInfo{}, fmt.Errorf("%w: malformed collection info", application.ErrVectorIndexUnavailable)
	}
	var vectors struct {
		Size     int    `json:"size"`
		Distance string `json:"distance"`
	}
	// A collection created by this adapter has one unnamed vector. Named
	// vectors (an object of objects) decode with Size 0 and are reported as
	// incompatible by the caller.
	_ = json.Unmarshal(info.Config.Params.Vectors, &vectors)
	count, err := q.count(ctx, collection)
	if err != nil {
		return application.VectorCollectionInfo{}, err
	}
	return application.VectorCollectionInfo{Exists: true, Dimensions: vectors.Size, Distance: vectors.Distance, PointCount: count}, nil
}

func (q *Qdrant) count(ctx context.Context, collection string) (int64, error) {
	status, result, err := q.do(ctx, http.MethodPost, collectionPath(collection)+"/points/count", map[string]any{"exact": true})
	if err != nil {
		return 0, err
	}
	if status == http.StatusNotFound {
		return 0, nil
	}
	var c struct {
		Count int64 `json:"count"`
	}
	if err := json.Unmarshal(result, &c); err != nil {
		return 0, fmt.Errorf("%w: malformed count", application.ErrVectorIndexUnavailable)
	}
	return c.Count, nil
}

func (q *Qdrant) CreateCollection(ctx context.Context, collection string, dimensions int) error {
	_, _, err := q.do(ctx, http.MethodPut, collectionPath(collection), map[string]any{
		"vectors": map[string]any{"size": dimensions, "distance": "Cosine"},
	})
	return err
}

func (q *Qdrant) DeleteCollection(ctx context.Context, collection string) error {
	_, _, err := q.do(ctx, http.MethodDelete, collectionPath(collection), nil)
	return err // 404 (already absent) is not an error
}

type qdrantPayload struct {
	ConceptID      int64  `json:"concept_id"`
	ContentHash    string `json:"content_hash"`
	Representation string `json:"representation"`
	ModelID        string `json:"model_id"`
	Dimensions     int    `json:"dimensions"`
}

func (q *Qdrant) Upsert(ctx context.Context, collection string, space application.SemanticIndexSpace, points []application.VectorPoint) error {
	type point struct {
		ID      int64         `json:"id"`
		Vector  []float32     `json:"vector"`
		Payload qdrantPayload `json:"payload"`
	}
	body := struct {
		Points []point `json:"points"`
	}{Points: make([]point, 0, len(points))}
	for _, p := range points {
		if p.ConceptID <= 0 {
			return fmt.Errorf("%w: point id must be positive", application.ErrVectorIndexUnavailable)
		}
		body.Points = append(body.Points, point{ID: p.ConceptID, Vector: p.Vector, Payload: qdrantPayload{
			ConceptID: p.ConceptID, ContentHash: p.ContentHash, Representation: space.Representation,
			ModelID: space.ModelID, Dimensions: space.Dimensions,
		}})
	}
	status, _, err := q.do(ctx, http.MethodPut, collectionPath(collection)+"/points?wait=true", body)
	if err == nil && status == http.StatusNotFound {
		return fmt.Errorf("%w: collection %s does not exist", application.ErrSemanticIndexNotBuilt, collection)
	}
	return err
}

func (q *Qdrant) Delete(ctx context.Context, collection string, conceptIDs []int64) error {
	status, _, err := q.do(ctx, http.MethodPost, collectionPath(collection)+"/points/delete?wait=true", map[string]any{"points": conceptIDs})
	if err == nil && status == http.StatusNotFound {
		return nil
	}
	return err
}

func (q *Qdrant) Query(ctx context.Context, collection string, vector []float32, limit int) ([]application.VectorHit, error) {
	status, result, err := q.do(ctx, http.MethodPost, collectionPath(collection)+"/points/query", map[string]any{
		"query": vector, "limit": limit, "with_payload": true,
	})
	if err != nil {
		return nil, err
	}
	if status == http.StatusNotFound {
		return nil, fmt.Errorf("%w: collection %s does not exist", application.ErrSemanticIndexNotBuilt, collection)
	}
	var parsed struct {
		Points []struct {
			ID      json.RawMessage `json:"id"`
			Score   float64         `json:"score"`
			Payload qdrantPayload   `json:"payload"`
		} `json:"points"`
	}
	if err := json.Unmarshal(result, &parsed); err != nil {
		return nil, fmt.Errorf("%w: malformed query response", application.ErrVectorIndexUnavailable)
	}
	hits := make([]application.VectorHit, 0, len(parsed.Points))
	for _, p := range parsed.Points {
		var id int64
		if err := json.Unmarshal(p.ID, &id); err != nil || id <= 0 || id != p.Payload.ConceptID {
			// A point this adapter did not write (or a corrupted payload) is
			// returned as an incompatible hit so the caller can count and drop it.
			hits = append(hits, application.VectorHit{ConceptID: id, Score: p.Score})
			continue
		}
		hits = append(hits, application.VectorHit{
			ConceptID: id, Score: p.Score, ContentHash: p.Payload.ContentHash,
			Representation: p.Payload.Representation, ModelID: p.Payload.ModelID, Dimensions: p.Payload.Dimensions,
		})
	}
	return hits, nil
}

// ListCollections returns every collection name in the Qdrant instance.
func (q *Qdrant) ListCollections(ctx context.Context) ([]string, error) {
	_, result, err := q.do(ctx, http.MethodGet, "/collections", nil)
	if err != nil {
		return nil, err
	}
	var parsed struct {
		Collections []struct {
			Name string `json:"name"`
		} `json:"collections"`
	}
	if err := json.Unmarshal(result, &parsed); err != nil {
		return nil, fmt.Errorf("%w: malformed collection list", application.ErrVectorIndexUnavailable)
	}
	names := make([]string, 0, len(parsed.Collections))
	for _, c := range parsed.Collections {
		names = append(names, c.Name)
	}
	return names, nil
}

// Scroll returns one page of points with payloads and vectors, ordered by id.
func (q *Qdrant) Scroll(ctx context.Context, collection string, offset *int64, limit int) ([]application.StoredPoint, *int64, error) {
	body := map[string]any{"limit": limit, "with_payload": true, "with_vector": true}
	if offset != nil {
		body["offset"] = *offset
	}
	status, result, err := q.do(ctx, http.MethodPost, collectionPath(collection)+"/points/scroll", body)
	if err != nil {
		return nil, nil, err
	}
	if status == http.StatusNotFound {
		return nil, nil, fmt.Errorf("%w: collection %s does not exist", application.ErrSemanticIndexNotBuilt, collection)
	}
	var parsed struct {
		Points []struct {
			ID      json.RawMessage `json:"id"`
			Payload json.RawMessage `json:"payload"`
			Vector  []float32       `json:"vector"`
		} `json:"points"`
		Next json.RawMessage `json:"next_page_offset"`
	}
	if err := json.Unmarshal(result, &parsed); err != nil {
		return nil, nil, fmt.Errorf("%w: malformed scroll response", application.ErrVectorIndexUnavailable)
	}
	points := make([]application.StoredPoint, 0, len(parsed.Points))
	for _, p := range parsed.Points {
		var id int64
		idErr := json.Unmarshal(p.ID, &id)
		var payload qdrantPayload
		payloadErr := json.Unmarshal(p.Payload, &payload)
		valid := idErr == nil && payloadErr == nil && id > 0 && payload.ConceptID == id
		points = append(points, application.StoredPoint{
			ConceptID: id, PayloadValid: valid, ContentHash: payload.ContentHash, Representation: payload.Representation,
			ModelID: payload.ModelID, Dimensions: payload.Dimensions, Vector: p.Vector,
		})
	}
	var next *int64
	if len(parsed.Next) > 0 && string(parsed.Next) != "null" {
		var n int64
		if err := json.Unmarshal(parsed.Next, &n); err != nil {
			return nil, nil, fmt.Errorf("%w: malformed scroll offset", application.ErrVectorIndexUnavailable)
		}
		next = &n
	}
	return points, next, nil
}
