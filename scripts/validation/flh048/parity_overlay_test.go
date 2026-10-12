//go:build flh052parity

package main

import (
	"encoding/json"
	"reflect"
	"testing"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// Built only with -tags flh052parity and the overlay that adds
// testdata/production_bridge.go.txt to internal/application (see
// TestConverterParity_AgainstProductionThroughOverlay).
//
// It compares the runner's mirrored converters with the actual unexported
// production converters, field for field, starting from the raw fixture rather
// than from the runner's own output.
func TestFLH052ConverterParity(t *testing.T) {
	raw := frozenFixture(t)
	in, err := LoadRankingInputs(raw)
	if err != nil {
		t.Fatal(err)
	}
	var f struct {
		Concepts []struct {
			ID       string `json:"id"`
			Identity struct {
				Target            string            `json:"target"`
				PedagogicalIntent string            `json:"pedagogical_intent"`
				Scope             string            `json:"scope"`
				IdentityFeatures  map[string]string `json:"identity_features"`
			} `json:"identity"`
		} `json:"concepts"`
		Queries []struct {
			ID       string `json:"id"`
			Evidence struct {
				Kind      string  `json:"kind"`
				Canonical string  `json:"canonical"`
				Statement string  `json:"statement"`
				Example   *string `json:"example"`
			} `json:"unit_evidence"`
		} `json:"queries"`
	}
	if err := json.Unmarshal(raw, &f); err != nil {
		t.Fatal(err)
	}
	runtimeID := func(ids []string, id string) int64 {
		for i, x := range ids {
			if x == id {
				return int64(i + 1)
			}
		}
		t.Fatalf("unmapped %s", id)
		return 0
	}

	example := "  Je suis ALLÉE  "
	units := []domain.KnowledgeUnit{
		{ID: 901, Kind: "grammar", Canonical: "  Passé   Composé  ", Statement: "x", Example: &example},
		{ID: 902, Kind: "vocabulary", Canonical: "le four", Statement: "", Example: nil},
	}
	for _, q := range f.Queries {
		id := runtimeID(in.QueryFixtureIDs, q.ID)
		u := domain.KnowledgeUnit{ID: id, Kind: domain.KnowledgeKind(q.Evidence.Kind), Canonical: q.Evidence.Canonical,
			Statement: q.Evidence.Statement, Example: q.Evidence.Example}
		units = append(units, u)
		if got, want := in.Queries[id-1], application.FLH052ProductionQuery(u); !reflect.DeepEqual(got, want) {
			t.Fatalf("query %s: loader %+v, production %+v", q.ID, got, want)
		}
	}
	for _, u := range units {
		if got, want := toQuery(u), application.FLH052ProductionQuery(u); !reflect.DeepEqual(got, want) {
			t.Fatalf("query converter drift for unit %d: mirror %+v, production %+v", u.ID, got, want)
		}
	}
	if len(f.Queries) != 56 {
		t.Fatalf("%d queries", len(f.Queries))
	}

	identities := []domain.ConceptIdentity{
		{Target: "  Le PRONOM en ", PedagogicalIntent: "Grammar", Scope: "", IdentityFeatures: nil},
		{Target: "accord", PedagogicalIntent: "grammar", Scope: "avec avoir", IdentityFeatures: map[string]string{"b": "2", "a": "1"}},
	}
	ids := []int64{901, 902}
	for _, c := range f.Concepts {
		identities = append(identities, domain.ConceptIdentity{Target: c.Identity.Target, PedagogicalIntent: c.Identity.PedagogicalIntent,
			Scope: c.Identity.Scope, IdentityFeatures: c.Identity.IdentityFeatures})
		ids = append(ids, runtimeID(in.ConceptFixtureIDs, c.ID))
	}
	for i, identity := range identities {
		mirrored, err := toDocument(ids[i], identity)
		if err != nil {
			t.Fatalf("concept %d: %v", ids[i], err)
		}
		// A persisted Concept as creation stores it: validated identity, its
		// domain signature, and the runner's declared synthetic state.
		stored := identity
		stored.IdentityFeatures = cloneMap(identity.IdentityFeatures)
		if err := stored.Validate(); err != nil {
			t.Fatal(err)
		}
		concept := domain.KnowledgeConcept{ID: ids[i], IdentitySchemaVersion: domain.ConceptIdentitySchemaVersion,
			Target: stored.Target, PedagogicalIntent: stored.PedagogicalIntent, Scope: stored.Scope,
			IdentityFeatures: stored.IdentityFeatures, Signature: stored.Signature(),
			Lifecycle: domain.LifecycleNormal, Support: domain.SupportSupported, State: domain.ConceptActive}
		production := application.FLH052ProductionDocument(concept)
		if !reflect.DeepEqual(mirrored, production) {
			t.Fatalf("document converter drift for concept %d: mirror %+v, production %+v", ids[i], mirrored, production)
		}
		if i >= 2 && !reflect.DeepEqual(in.Documents[ids[i]-1], production) {
			t.Fatalf("loader document %d differs from production", ids[i])
		}
	}
	if len(f.Concepts) != 24 {
		t.Fatalf("%d concepts", len(f.Concepts))
	}
}
