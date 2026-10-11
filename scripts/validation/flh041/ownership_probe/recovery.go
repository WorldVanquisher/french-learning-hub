// FLH-047 independent recovery probes. Every vector operation delegates to Qdrant.
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net/http/httptest"
	"os"
	"reflect"
	"strings"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/embedding"
	"french-learning-app/internal/storage/sqlite"
	transport "french-learning-app/internal/transport/http"
	"french-learning-app/internal/vectorindex"
)

type countedProvider struct {
	application.EmbeddingProvider
	Calls, Texts int
}

func (p *countedProvider) Embed(ctx context.Context, texts []string) ([][]float64, error) {
	p.Calls++
	p.Texts += len(texts)
	return p.EmbeddingProvider.Embed(ctx, texts)
}

type recoveryAdapter struct {
	application.VectorIndex
	before                func(string, string)
	InfoCalls, QueryCalls int
	Deletes               []string
}

func (a *recoveryAdapter) CollectionInfo(ctx context.Context, collection string) (application.VectorCollectionInfo, error) {
	a.InfoCalls++
	if a.before != nil {
		a.before("info", collection)
	}
	return a.VectorIndex.CollectionInfo(ctx, collection)
}
func (a *recoveryAdapter) Query(ctx context.Context, collection string, vector []float32, limit int) ([]application.VectorHit, error) {
	a.QueryCalls++
	if a.before != nil {
		a.before("query", collection)
	}
	return a.VectorIndex.Query(ctx, collection, vector, limit)
}
func (a *recoveryAdapter) DeleteCollection(ctx context.Context, collection string) error {
	a.Deletes = append(a.Deletes, collection)
	return a.VectorIndex.DeleteCollection(ctx, collection)
}

type observedSearch struct {
	service *application.SemanticSearchService
	result  *application.SemanticSearchReport
	err     error
}

func (s *observedSearch) Search(ctx context.Context, q application.LibrarySearchQuery) (*application.SemanticSearchReport, error) {
	s.result, s.err = s.service.Search(ctx, q)
	return s.result, s.err
}
func httpSearch(ctx context.Context, observed *observedSearch) (int, any) {
	h := transport.NewHandler(nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, transport.WithSemanticSearch(observed))
	request := httptest.NewRequest("GET", "/knowledge-library/semantic-search?q=flh043%20query&limit=20", nil).WithContext(ctx)
	reply := httptest.NewRecorder()
	h.Routes().ServeHTTP(reply, request)
	var body any
	must(json.Unmarshal(reply.Body.Bytes(), &body))
	return reply.Code, body
}
func publicationEqual(a, b publication) bool {
	return a.State.PublishedCollection == b.State.PublishedCollection &&
		a.State.PublishedRunID == b.State.PublishedRunID &&
		reflect.DeepEqual(a.State.PublishedAt, b.State.PublishedAt) &&
		reflect.DeepEqual(a.Manifest, b.Manifest) && reflect.DeepEqual(a.Points, b.Points)
}

func recovery(db *sql.DB, mode string) {
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
	defer cancel()
	store := sqlite.NewSemanticIndexRepository(db)
	space, err := application.NewSemanticIndexSpace(os.Getenv("QDRANT_COLLECTION_PREFIX"), os.Getenv("EMBEDDING_MODEL_ID"), 8)
	must(err)
	q := vectorindex.NewQdrant(os.Getenv("QDRANT_URL"), "", 5*time.Second)
	provider := embedding.NewHTTPProvider("", "fixture", os.Getenv("EMBEDDING_BASE_URL"), 5*time.Second)
	reader := sqlite.NewConceptRepository(db)
	service := func(index application.VectorIndex) *application.SemanticIndexService {
		return application.NewSemanticIndexService(reader, store, index, provider, space, 2)
	}
	if mode == "recovery-cleanup-lease-loss" {
		physical, err := store.PhysicalCollections(ctx, space.Collection)
		must(err)
		eligible := []string{}
		manifests := map[string]map[int64]string{}
		for _, c := range physical {
			manifests[c.Collection], err = store.Manifest(ctx, c.Collection)
			must(err)
			if c.Status == application.PhysicalRetired || c.Status == application.PhysicalAbandoned {
				eligible = append(eligible, c.Collection)
			}
		}
		require(len(eligible) == 2, "lease-loss setup requires exactly two terminal leftovers")
		for _, name := range eligible {
			info, e := q.CollectionInfo(ctx, name)
			must(e)
			require(info.Exists, "terminal fixture collection absent")
		}
		adapter := &recoveryAdapter{VectorIndex: q}
		gates := 0
		var newer publication
		rep, err := service(adapter).WithGateHook(func(step string) {
			if step != "delete-collection" {
				return
			}
			gates++
			require(gates == 1, "old cleanup passed a second ownership gate")
			now := time.Now()
			run := fmt.Sprintf("f047newer%016x", now.UnixNano())
			must(store.AcquireLease(ctx, space, run, "sync", now, now.Add(time.Minute), true))
			// A verified no-op owner completes through real fenced repository APIs.
			health, e := service(q).Status(ctx)
			must(e)
			require(health.VerifiedHealthy, "new owner's publication unhealthy")
			must(store.CompleteRun(ctx, space.Collection, run, "sync", application.SemanticRunOutcome{Outcome: application.RunOutcomeVerifiedUnchanged, StartedAt: now, FinishedAt: time.Now()}))
			newer = capture(ctx, store, q, space)
		}).Sync(ctx, application.SemanticRunOptions{})
		require(errors.Is(err, application.ErrSemanticIndexOwnershipLost) && rep.OwnershipLost, "old cleanup did not return ownership lost")
		after := capture(ctx, store, q, space)
		require(reflect.DeepEqual(newer, after), "old cleanup changed newer state/manifest/points")
		retained, e := store.PhysicalCollections(ctx, space.Collection)
		must(e)
		require(reflect.DeepEqual(physical, retained), "old cleanup forgot or changed fenced physical records")
		for name, before := range manifests {
			now, e := store.Manifest(ctx, name)
			must(e)
			require(reflect.DeepEqual(before, now), "old cleanup changed a manifest")
		}
		require(len(adapter.Deletes) == 1 && gates == 1, "lease loss did not stop subsequent deletion")
		existence := map[string]bool{}
		for _, name := range eligible {
			info, e := q.CollectionInfo(ctx, name)
			must(e)
			existence[name] = info.Exists
			require(info.Exists == (name != adapter.Deletes[0]), "unexpected terminal deletion")
		}
		output(map[string]any{"pass": true, "report": rep, "error": err.Error(), "gates": gates, "deletions": adapter.Deletes, "eligible": eligible, "existence_after": existence, "physical_before": physical, "physical_after": retained, "manifests": manifests, "newer_before_release": newer, "newer_after_release": after})
		return
	}
	if mode == "recovery-cleanup-writing" {
		before := capture(ctx, store, q, space)
		now := time.Now()
		run := fmt.Sprintf("f047writer%016x", now.UnixNano())
		name := space.PhysicalCollectionName(run)
		must(store.AcquireLease(ctx, space, run, "rebuild", now, now.Add(time.Minute), false))
		must(store.RegisterCollection(ctx, space.Collection, run, name, now))
		must(q.CreateCollection(ctx, name, 8))
		point := before.Points[0]
		must(q.Upsert(ctx, name, space, []application.VectorPoint{{ConceptID: point.ConceptID, ContentHash: point.ContentHash, Vector: point.Vector}}))
		must(store.RecordManifest(ctx, space.Collection, run, name, map[int64]string{point.ConceptID: point.ContentHash}))
		privateBefore, _, e := q.Scroll(ctx, name, nil, 2)
		must(e)
		adapter := &recoveryAdapter{VectorIndex: q}
		rep, e := service(adapter).Sync(ctx, application.SemanticRunOptions{Takeover: true})
		must(e)
		after := capture(ctx, store, q, space)
		privateAfter, _, e := q.Scroll(ctx, name, nil, 2)
		must(e)
		records, e := store.PhysicalCollections(ctx, space.Collection)
		must(e)
		manifest, e := store.Manifest(ctx, name)
		must(e)
		require(rep.VerifiedUnchanged && !rep.Published, "writing test sync republished")
		require(publicationEqual(before, after), "healthy sync changed publication contents")
		require(reflect.DeepEqual(privateBefore, privateAfter) && manifest[point.ConceptID] == point.ContentHash, "healthy sync touched another writer's points/manifest")
		found := false
		for _, c := range records {
			if c.Collection == name {
				found = c.Status == application.PhysicalWriting && c.RunID == run
			}
		}
		require(found, "healthy sync forgot writing collection")
		require(len(adapter.Deletes) == 0, "healthy sync deleted a writing collection")
		require(len(rep.CleanupPending) == 1 && rep.CleanupPending[0] == name, "writing collection not reported pending")
		output(map[string]any{"pass": true, "writing_collection": name, "report": rep, "publication_before": before, "publication_after": after, "private_before": privateBefore, "private_after": privateAfter, "manifest": manifest, "records": records, "deletions": adapter.Deletes})
		return
	}
	suffix := strings.TrimPrefix(mode, "recovery-search-")
	loss := strings.HasPrefix(suffix, "loss-")
	suffix = strings.TrimPrefix(suffix, "loss-")
	windows := strings.Split(suffix, "-")
	require(len(windows) <= 2, "probe only supports the one-retry boundary")
	for _, window := range windows {
		require(window == "info" || window == "query", "unknown search window")
	}
	prior := capture(ctx, store, q, space)
	adapter := &recoveryAdapter{VectorIndex: q}
	replacements := []*application.SemanticIndexReport{}
	changed := 0
	adapter.before = func(step, old string) {
		if changed >= len(windows) || windows[changed] != step {
			return
		}
		changed++
		if loss {
			must(q.DeleteCollection(ctx, old))
			return
		}
		rep, e := service(q).Rebuild(ctx, application.SemanticRunOptions{})
		must(e)
		require(rep.Published && rep.Replaced == old, "replacement did not replace the selected publication")
		info, e := q.CollectionInfo(ctx, old)
		must(e)
		require(!info.Exists, "replaced collection was not actually deleted")
		replacements = append(replacements, rep)
	}
	counted := &countedProvider{EmbeddingProvider: provider}
	search := &observedSearch{service: application.NewSemanticSearchService(reader, counts{}, store, adapter, counted, space)}
	code, body := httpSearch(ctx, search)
	wantEmbeddings, wantQueries, wantInfo := 1, 1, 2
	wantStatus := 200
	if len(windows) == 1 && windows[0] == "query" {
		wantQueries = 2
	}
	if len(windows) == 2 {
		wantStatus = 500
		if windows[0] == "info" && windows[1] == "info" {
			wantEmbeddings, wantQueries = 0, 0
		}
		if windows[0] == "query" && windows[1] == "query" {
			wantQueries = 2
		}
		require(errors.Is(search.err, application.ErrSemanticPublicationChanged) && !errors.Is(search.err, application.ErrSemanticIndexNotBuilt), "repeated replacement returned dishonest error or exceeded retry budget")
	}
	if loss {
		wantStatus, wantInfo = 409, 1
		if windows[0] == "info" {
			wantEmbeddings, wantQueries = 0, 0
		} else {
			wantQueries = 1
		}
		require(errors.Is(search.err, application.ErrSemanticIndexNotBuilt), "unchanged-pointer loss was hidden")
		state, e := store.SpaceState(ctx, space.Collection)
		must(e)
		require(reflect.DeepEqual(prior.State, state), "search mutated bookkeeping during true loss")
	}
	require(changed == len(windows), "not all requested replacement windows executed")
	require(code == wantStatus, "unexpected production HTTP error mapping")
	require(counted.Calls == wantEmbeddings && counted.Texts == wantEmbeddings && adapter.QueryCalls == wantQueries && adapter.InfoCalls == wantInfo, "unexpected search request/embedding counts")
	if wantStatus == 200 {
		require(search.err == nil, "successful replacement returned error")
	}
	detail := ""
	if search.err != nil {
		detail = search.err.Error()
	}
	firstCounters := map[string]int{"embeddings": counted.Calls, "input_texts": counted.Texts, "collection_info": adapter.InfoCalls, "queries": adapter.QueryCalls}
	var repair *application.SemanticIndexReport
	if loss {
		repair, err = service(q).Sync(ctx, application.SemanticRunOptions{})
		must(err)
		require(repair.EmbeddedTexts == 0 && repair.Published, "true-loss repair did not reuse cache")
	}
	current := capture(ctx, store, q, space)
	require(reflect.DeepEqual(prior.Manifest, current.Manifest) && reflect.DeepEqual(prior.Points, current.Points), "replacement/repair changed cached document payloads or vectors")
	if wantStatus == 200 {
		require(search.result.Collection == current.State.PublishedCollection, "retry did not query the current collection")
	}
	// Next independent request succeeds after churn ends; it gets its own one embedding.
	follow := &observedSearch{service: application.NewSemanticSearchService(reader, counts{}, store, q, counted, space)}
	followCode, followBody := httpSearch(ctx, follow)
	require(followCode == 200 && counted.Calls == wantEmbeddings+1 && counted.Texts == wantEmbeddings+1, "subsequent request did not independently recover")
	output(map[string]any{"pass": true, "mode": mode, "windows": windows, "actual_error": detail, "http_status": code, "http_body": body, "http_evidence": "actual production handler via httptest; real provider and Qdrant", "first_counters": firstCounters, "total_embedding_calls": counted.Calls, "replacements": replacements, "prior": prior, "current": current, "repair": repair, "followup_status": followCode, "followup_body": followBody})
}
