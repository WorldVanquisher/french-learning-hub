// FLH-043: active FLH-042 API diagnostics with real SQLite and real Qdrant.
// The historical FLH-041 migration-010 evidence is preserved in its report.
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"reflect"
	"sort"
	"strings"
	"sync"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/embedding"
	"french-learning-app/internal/storage/sqlite"
	"french-learning-app/internal/vectorindex"
)

func must(err error) {
	if err != nil {
		panic(err)
	}
}
func require(ok bool, message string) {
	if !ok {
		panic(message)
	}
}
func output(v any) { must(json.NewEncoder(os.Stdout).Encode(v)) }

func seed(db *sql.DB) {
	var count int
	must(db.QueryRow("SELECT count(*) FROM knowledge_concepts").Scan(&count))
	if count != 0 {
		return
	}
	// Direct isolated synthetic fixture, not a learner-facing concept creation workflow.
	for i, target := range []string{"flh043 alpha", "flh043 beta", "flh043 gamma", "flh043 alpha"} {
		lifecycle := "normal"
		if i == 3 {
			lifecycle = "retired"
		}
		identity := domain.ConceptIdentity{Target: target, PedagogicalIntent: "grammar", Scope: "synthetic", IdentityFeatures: map[string]string{"fixture": "flh043"}}
		_, err := db.Exec(`INSERT INTO knowledge_concepts (id,identity_schema_version,target,pedagogical_intent,scope,identity_features,signature,lifecycle_state,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)`, i+1, "fr_l2_concept_identity_v1", target, "grammar", "synthetic", `{"fixture":"flh043"}`, identity.Signature(), lifecycle, "2026-10-11T12:00:00Z", "2026-10-11T12:00:00Z")
		must(err)
	}
}

func documents(db *sql.DB) []application.SemanticIndexDocument {
	concepts, err := sqlite.NewConceptRepository(db).ListConcepts(context.Background(), nil)
	must(err)
	docs := []application.SemanticIndexDocument{}
	for _, c := range concepts {
		d, err := application.BuildSemanticIndexDocument(c)
		must(err)
		docs = append(docs, d)
	}
	sort.Slice(docs, func(i, j int) bool { return docs[i].ConceptID < docs[j].ConceptID })
	return docs
}

func repository(db *sql.DB, path string) {
	ctx := context.Background()
	other, err := sqlite.Open(path)
	must(err)
	defer other.Close()
	a, b := sqlite.NewSemanticIndexRepository(db), sqlite.NewSemanticIndexRepository(other)
	space, err := application.NewSemanticIndexSpace("flh043_repository", "fixture/repository", 8)
	must(err)
	now := time.Date(2026, 10, 11, 12, 0, 0, 0, time.UTC)
	old, newer := "aaaaaaaaaaaa00000000000000000000", "bbbbbbbbbbbb00000000000000000000"
	must(a.AcquireLease(ctx, space, old, "rebuild", now, now.Add(time.Minute), false))
	busy := b.AcquireLease(ctx, space, newer, "sync", now, now.Add(time.Minute), false)
	require(errors.Is(busy, application.ErrSemanticIndexBusy), "busy lease was not refused")
	oldCol, newCol := space.PhysicalCollectionName(old), space.PhysicalCollectionName(newer)
	must(a.RegisterCollection(ctx, space.Collection, old, oldCol, now))
	must(a.RecordManifest(ctx, space.Collection, old, oldCol, map[int64]string{1: "old"}))
	must(b.AcquireLease(ctx, space, newer, "rebuild", now, now.Add(time.Minute), true))
	must(b.RegisterCollection(ctx, space.Collection, newer, newCol, now))
	must(b.RecordManifest(ctx, space.Collection, newer, newCol, map[int64]string{1: "new"}))
	_, err = b.Publish(ctx, space.Collection, newer, newCol, now)
	must(err)
	before, err := b.SpaceState(ctx, space.Collection)
	must(err)
	manifest, err := b.Manifest(ctx, newCol)
	must(err)
	failures := map[string]bool{}
	attempts := map[string]func() error{
		"renew": func() error { return a.RenewLease(ctx, space.Collection, old, now.Add(time.Minute)) },
		"record-own": func() error {
			return a.RecordManifest(ctx, space.Collection, old, oldCol, map[int64]string{1: "wrong"})
		},
		"record-newer": func() error {
			return a.RecordManifest(ctx, space.Collection, old, newCol, map[int64]string{1: "wrong"})
		},
		"remove":  func() error { return a.RemoveManifest(ctx, space.Collection, old, newCol, []int64{1}) },
		"publish": func() error { _, e := a.Publish(ctx, space.Collection, old, oldCol, now); return e },
		"mark": func() error {
			return a.MarkCollection(ctx, space.Collection, old, newCol, application.PhysicalAbandoned, now)
		},
		"forget":   func() error { return a.ForgetCollection(ctx, space.Collection, old, newCol) },
		"register": func() error { return a.RegisterCollection(ctx, space.Collection, old, "foreign", now) },
		"complete": func() error {
			return a.CompleteRun(ctx, space.Collection, old, "rebuild", application.SemanticRunOutcome{Outcome: application.RunOutcomePublished, StartedAt: now, FinishedAt: now})
		},
	}
	for name, attempt := range attempts {
		failures[name] = errors.Is(attempt(), application.ErrSemanticIndexOwnershipLost)
		require(failures[name], "superseded write succeeded: "+name)
	}
	after, err := b.SpaceState(ctx, space.Collection)
	must(err)
	afterManifest, err := b.Manifest(ctx, newCol)
	must(err)
	require(reflect.DeepEqual(before, after) && reflect.DeepEqual(manifest, afterManifest), "superseded writes changed active records")
	must(b.AcquireLease(ctx, space, old, "sync", now.Add(2*time.Minute), now.Add(3*time.Minute), false))
	// Expiration used the API's supplied clock; no wall-clock sleep or production clock edit.
	must(a.CompleteRun(ctx, space.Collection, old, "sync", application.SemanticRunOutcome{Outcome: application.RunOutcomeVerifiedUnchanged, StartedAt: now, FinishedAt: now}))
	output(map[string]any{"busy_refused": true, "expired_acquired": true, "takeover_acquired": true, "fenced_refusals": failures, "active_before": before, "active_after": after, "manifest": afterManifest, "api": "FLH-042 migration 011; no legacy methods"})
}

type publication struct {
	State    *application.SemanticIndexSpaceState `json:"state"`
	Manifest map[int64]string                     `json:"manifest"`
	Points   []application.StoredPoint            `json:"points"`
}

func capture(ctx context.Context, store *sqlite.SemanticIndexRepository, q application.VectorIndex, space application.SemanticIndexSpace) publication {
	st, err := store.SpaceState(ctx, space.Collection)
	must(err)
	p := publication{State: st, Points: []application.StoredPoint{}}
	if st == nil || st.PublishedCollection == "" {
		return p
	}
	p.Manifest, err = store.Manifest(ctx, st.PublishedCollection)
	must(err)
	var offset *int64
	for {
		points, next, err := q.Scroll(ctx, st.PublishedCollection, offset, 2)
		must(err)
		p.Points = append(p.Points, points...)
		if next == nil {
			break
		}
		offset = next
	}
	return p
}

type counts struct{}

func (counts) ConceptCounts(context.Context, int64) (int, int, error) { return 0, 0, nil }

// Gate the actual adapter calls; every ungated operation delegates to Qdrant.
type queryGate struct {
	application.VectorIndex
	step             string
	reached, release chan struct{}
	once             sync.Once
}

func (g *queryGate) pause() {
	g.once.Do(func() {
		close(g.reached)
		select {
		case <-g.release:
		case <-time.After(20 * time.Second):
			panic("query gate timeout")
		}
	})
}
func (g *queryGate) Query(ctx context.Context, c string, v []float32, l int) ([]application.VectorHit, error) {
	if g.step == "query" {
		g.pause()
	}
	return g.VectorIndex.Query(ctx, c, v, l)
}
func (g *queryGate) CollectionInfo(ctx context.Context, c string) (application.VectorCollectionInfo, error) {
	if g.step == "info" {
		g.pause()
	}
	return g.VectorIndex.CollectionInfo(ctx, c)
}

func integrated(db *sql.DB, mode string) {
	if strings.HasPrefix(mode, "recovery-") {
		recovery(db, mode)
		return
	}
	ctx := context.Background()
	store := sqlite.NewSemanticIndexRepository(db)
	space, err := application.NewSemanticIndexSpace(os.Getenv("QDRANT_COLLECTION_PREFIX"), os.Getenv("EMBEDDING_MODEL_ID"), 8)
	must(err)
	q := vectorindex.NewQdrant(os.Getenv("QDRANT_URL"), "", 5*time.Second)
	provider := embedding.NewHTTPProvider("", "fixture", os.Getenv("EMBEDDING_BASE_URL"), 5*time.Second)
	reader := sqlite.NewConceptRepository(db)
	svc := func() *application.SemanticIndexService {
		return application.NewSemanticIndexService(reader, store, q, provider, space, 2)
	}
	if mode == "inventory" {
		output(capture(ctx, store, q, space))
		return
	}
	if mode == "source-change" {
		var once sync.Once
		rep, err := svc().WithGateHook(func(step string) {
			if step == "upsert" {
				once.Do(func() { _, e := db.Exec(`UPDATE knowledge_concepts SET target='flh043 delta' WHERE id=2`); must(e) })
			}
		}).Rebuild(ctx, application.SemanticRunOptions{})
		must(err)
		require(rep.CatchUpChanges == 1 && rep.Published, "source change did not catch up")
		output(map[string]any{"report": rep, "publication": capture(ctx, store, q, space), "documents": documents(db)})
		return
	}
	if mode == "search-query-race" || mode == "search-info-race" {
		step := "query"
		if mode == "search-info-race" {
			step = "info"
		}
		gate := &queryGate{VectorIndex: q, step: step, reached: make(chan struct{}), release: make(chan struct{})}
		search := application.NewSemanticSearchService(reader, counts{}, store, gate, provider, space)
		done := make(chan struct{})
		var result *application.SemanticSearchReport
		var searchErr error
		go func() {
			defer close(done)
			result, searchErr = search.Search(ctx, application.LibrarySearchQuery{Text: "flh043 query", Limit: 20})
		}()
		select {
		case <-gate.reached:
		case <-time.After(10 * time.Second):
			panic("search did not reach gate")
		}
		newer, newErr := svc().Rebuild(ctx, application.SemanticRunOptions{})
		close(gate.release)
		<-done
		must(newErr)
		active := capture(ctx, store, q, space)
		success := searchErr == nil && result.Collection == active.State.PublishedCollection
		detail := ""
		if searchErr != nil {
			detail = searchErr.Error()
		}
		output(map[string]any{"expected": "retry once on current publication", "actual_error": detail, "pass": success, "newer": newer, "result": result, "publication": active})
		return
	}
	reached, release, done := make(chan struct{}), make(chan struct{}), make(chan struct{})
	step := mode
	noop := mode == "publish-noop"
	if noop {
		step = "publish"
	}
	var oldRep *application.SemanticIndexReport
	var oldErr error
	var once sync.Once
	go func() {
		defer close(done)
		oldRep, oldErr = svc().WithGateHook(func(at string) {
			if at == step {
				once.Do(func() {
					close(reached)
					select {
					case <-release:
					case <-time.After(20 * time.Second):
						panic("index gate timeout")
					}
				})
			}
		}).Rebuild(ctx, application.SemanticRunOptions{})
	}()
	select {
	case <-reached:
	case <-time.After(10 * time.Second):
		panic("index did not reach gate")
	}
	var newer *application.SemanticIndexReport
	var newErr error
	if noop {
		newer, newErr = svc().Sync(ctx, application.SemanticRunOptions{Takeover: true})
	} else {
		newer, newErr = svc().Rebuild(ctx, application.SemanticRunOptions{Takeover: true})
	}
	before := capture(ctx, store, q, space)
	close(release)
	<-done
	must(newErr)
	after := capture(ctx, store, q, space)
	require(errors.Is(oldErr, application.ErrSemanticIndexOwnershipLost) && !oldRep.Published, "old run was not fenced")
	require(reflect.DeepEqual(before, after), "old work mutated newer publication/state/manifest/points")
	if noop {
		require(newer.VerifiedUnchanged, "takeover sync was not a verified no-op")
	}
	physical, err := store.PhysicalCollections(ctx, space.Collection)
	must(err)
	names, err := q.ListCollections(ctx)
	must(err)
	output(map[string]any{"pass": true, "gate": mode, "old": oldRep, "old_error": oldErr.Error(), "newer": newer, "before_release": before, "after_release": after, "physical_records": physical, "qdrant_collections": names})
}
func main() {
	require(len(os.Args) == 3, "usage: ownership-probe mode task-owned-db")
	db, err := sqlite.Open(os.Args[2])
	must(err)
	defer db.Close()
	switch os.Args[1] {
	case "seed":
		seed(db)
		output(documents(db))
	case "documents":
		output(documents(db))
	case "repository":
		repository(db, os.Args[2])
	default:
		integrated(db, os.Args[1])
	}
	fmt.Fprintln(os.Stderr, "FLH-043 active API diagnostic finished")
}
