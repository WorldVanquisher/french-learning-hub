package main

import (
	"context"
	"fmt"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

type batch struct {
	Name   string   `json:"name"`
	Inputs []string `json:"inputs"`
}

const english = "How do I describe a completed action in French?"
const french = "Comment décrire une action terminée en français ?"

type captureProvider struct{ texts []string }

func (*captureProvider) Name() string { return "flh053-render-capture-only" }
func (p *captureProvider) Embed(_ context.Context, texts []string) ([][]float64, error) {
	p.texts = append([]string(nil), texts...)
	out := make([][]float64, len(texts))
	for i := range out {
		out[i] = []float64{1, 0}
	}
	return out, nil
}

// Synthetic identities only. Rendering is performed by current production code.
func fixtures(mode string) ([]batch, error) {
	if mode == "plain" {
		return []batch{{"english-french-repeat", []string{english, french, english}}, {"permuted-repeat", []string{french, english, french}}}, nil
	}
	if mode != "rendered" {
		return nil, fmt.Errorf("payload must be plain or rendered")
	}
	docs := []application.ConceptRetrievalDocument{}
	indexTexts := []string{}
	for i, target := range []string{"completed past action", "action passée achevée"} {
		identity := domain.ConceptIdentity{Target: target, PedagogicalIntent: "grammar", Scope: "synthetic example", IdentityFeatures: map[string]string{"aspect": "bounded"}}
		if err := identity.Validate(); err != nil {
			return nil, err
		}
		concept := domain.KnowledgeConcept{ID: int64(i + 1), IdentitySchemaVersion: domain.ConceptIdentitySchemaVersion, Target: identity.Target, PedagogicalIntent: identity.PedagogicalIntent, Scope: identity.Scope, IdentityFeatures: identity.IdentityFeatures, Signature: identity.Signature(), Lifecycle: domain.LifecycleNormal, Support: domain.SupportSupported, State: domain.ConceptActive}
		indexed, err := application.BuildSemanticIndexDocument(concept)
		if err != nil {
			return nil, err
		}
		indexTexts = append(indexTexts, indexed.Text)
		docs = append(docs, application.ConceptRetrievalDocument{ConceptID: concept.ID, IdentitySchemaVersion: concept.IdentitySchemaVersion, Target: concept.Target, PedagogicalIntent: concept.PedagogicalIntent, Scope: concept.Scope, IdentityFeatures: concept.IdentityFeatures, Signature: concept.Signature, Lifecycle: concept.Lifecycle, Support: concept.Support, State: concept.State})
	}
	example := "Le train est arrivé."
	unit := domain.KnowledgeUnit{ID: 1, Kind: domain.KindGrammar, Canonical: "Une action terminée", Statement: french, Example: &example}
	query := application.ConceptRetrievalQuery{UnitID: unit.ID, Kind: unit.Kind, Canonical: unit.Canonical, Statement: unit.Statement, Example: unit.Example, CandidateIdentity: domain.DeriveCandidateIdentity(unit)}
	p := &captureProvider{}
	if _, err := application.NewEmbeddingConceptRetriever(p).Retrieve(context.Background(), query, docs, 5); err != nil {
		return nil, err
	}
	if len(p.texts) != 3 || p.texts[1] != indexTexts[0] || p.texts[2] != indexTexts[1] {
		return nil, fmt.Errorf("production document rendering differs by path")
	}
	return []batch{{"unit-to-concept", p.texts}, {"document-only-permuted", []string{indexTexts[1], indexTexts[0], indexTexts[1]}}, {"raw-search-en", []string{english}}, {"raw-search-fr", []string{french}}, {"mixed-repeat", p.texts}}, nil
}
