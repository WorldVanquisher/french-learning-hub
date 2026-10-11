package vectorindex

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/application"
)

func TestQdrant_RequestShapesAndAPIKey(t *testing.T) {
	var seen []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("api-key") != "secret-key" {
			t.Errorf("missing api-key header on %s", r.URL.Path)
		}
		body, _ := io.ReadAll(r.Body)
		seen = append(seen, r.Method+" "+r.URL.RequestURI()+" "+string(body))
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/collections/c1":
			io.WriteString(w, `{"result":{"config":{"params":{"vectors":{"size":3,"distance":"Cosine"}}}},"status":"ok"}`)
		case strings.HasSuffix(r.URL.Path, "/points/count"):
			io.WriteString(w, `{"result":{"count":2},"status":"ok"}`)
		case strings.HasSuffix(r.URL.Path, "/points/query"):
			io.WriteString(w, `{"result":{"points":[{"id":7,"score":0.9,"payload":{"concept_id":7,"content_hash":"h","representation":"r","model_id":"m","dimensions":3}},{"id":8,"score":0.1,"payload":{"concept_id":9}}]},"status":"ok"}`)
		default:
			io.WriteString(w, `{"result":true,"status":"ok"}`)
		}
	}))
	defer srv.Close()
	q := NewQdrant(srv.URL, "secret-key", time.Second)
	ctx := context.Background()

	info, err := q.CollectionInfo(ctx, "c1")
	if err != nil || !info.Exists || info.Dimensions != 3 || info.Distance != "Cosine" || info.PointCount != 2 {
		t.Fatalf("info = %+v, %v", info, err)
	}
	space := application.SemanticIndexSpace{Collection: "c1", Representation: "r", ModelID: "m", Dimensions: 3}
	if err := q.Upsert(ctx, space, []application.VectorPoint{{ConceptID: 7, ContentHash: "h", Vector: []float32{1, 0, 0}}}); err != nil {
		t.Fatal(err)
	}
	hits, err := q.Query(ctx, "c1", []float32{1, 0, 0}, 5)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 2 || hits[0].ConceptID != 7 || hits[0].ContentHash != "h" || hits[0].ModelID != "m" {
		t.Fatalf("hits = %+v", hits)
	}
	if hits[1].ModelID != "" || hits[1].ContentHash != "" {
		t.Fatalf("a point whose id disagrees with its payload must come back without payload: %+v", hits[1])
	}
	if err := q.CreateCollection(ctx, "c2", 3); err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(seen, "\n")
	for _, want := range []string{
		`PUT /collections/c1/points?wait=true {"points":[{"id":7,"vector":[1,0,0],"payload":{"concept_id":7,"content_hash":"h","representation":"r","model_id":"m","dimensions":3}}]}`,
		`POST /collections/c1/points/query {"limit":5,"query":[1,0,0],"with_payload":true}`,
		`PUT /collections/c2 {"vectors":{"distance":"Cosine","size":3}}`,
	} {
		if !strings.Contains(joined, want) {
			t.Fatalf("missing request %s in:\n%s", want, joined)
		}
	}
}

func TestQdrant_MissingCollectionAndErrorCategories(t *testing.T) {
	mode := "404"
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch mode {
		case "404":
			w.WriteHeader(http.StatusNotFound)
			io.WriteString(w, `{"status":{"error":"Not found"}}`)
		case "500":
			w.WriteHeader(http.StatusInternalServerError)
			io.WriteString(w, `{"status":{"error":"secret detail"}}`)
		case "slow":
			time.Sleep(200 * time.Millisecond)
		case "garbage":
			io.WriteString(w, `not json`)
		}
	}))
	defer srv.Close()
	ctx := context.Background()
	q := NewQdrant(srv.URL, "", 50*time.Millisecond)

	info, err := q.CollectionInfo(ctx, "absent")
	if err != nil || info.Exists {
		t.Fatalf("absent collection: %+v %v", info, err)
	}
	if err := q.DeleteCollection(ctx, "absent"); err != nil {
		t.Fatalf("deleting an absent collection is not an error: %v", err)
	}
	if _, err := q.Query(ctx, "absent", []float32{1}, 1); !errors.Is(err, application.ErrSemanticIndexNotBuilt) {
		t.Fatalf("query on absent collection: %v", err)
	}

	mode = "500"
	_, err = q.CollectionInfo(ctx, "c")
	if !errors.Is(err, application.ErrVectorIndexUnavailable) || strings.Contains(err.Error(), "secret detail") {
		t.Fatalf("500: %v", err)
	}
	mode = "slow"
	if _, err := q.CollectionInfo(ctx, "c"); !errors.Is(err, application.ErrVectorIndexTimeout) {
		t.Fatalf("timeout: %v", err)
	}
	mode = "garbage"
	if _, err := q.CollectionInfo(ctx, "c"); !errors.Is(err, application.ErrVectorIndexUnavailable) {
		t.Fatalf("garbage: %v", err)
	}
	cctx, cancel := context.WithCancel(ctx)
	cancel()
	if _, err := q.CollectionInfo(cctx, "c"); !errors.Is(err, context.Canceled) {
		t.Fatalf("canceled context must be visible: %v", err)
	}

	srv.Close()
	if _, err := q.CollectionInfo(ctx, "c"); !errors.Is(err, application.ErrVectorIndexUnavailable) {
		t.Fatalf("unreachable: %v", err)
	}
}

func TestQdrant_RejectsNonPositivePointIDs(t *testing.T) {
	q := NewQdrant("http://127.0.0.1:1", "", time.Second)
	err := q.Upsert(context.Background(), application.SemanticIndexSpace{Collection: "c"}, []application.VectorPoint{{ConceptID: 0, Vector: []float32{1}}})
	if !errors.Is(err, application.ErrVectorIndexUnavailable) {
		t.Fatalf("err = %v", err)
	}
}
