package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"strings"

	"french-learning-app/internal/application"
	"french-learning-app/internal/config"
	"french-learning-app/internal/publicdemo"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

// checkPublicDemoConfig refuses any configuration that would enable a live or
// paid provider. The demo constructs no analyzer, extractor or provider client
// at all; this makes a misconfigured environment fail loudly instead.
func checkPublicDemoConfig(cfg config.Config) error {
	var bad []string
	if cfg.AI.Provider != config.ProviderRuleBased {
		bad = append(bad, fmt.Sprintf("AI_PROVIDER=%s (must be %s)", cfg.AI.Provider, config.ProviderRuleBased))
	}
	if cfg.Extractor.Provider != config.ExtractorDisabled {
		bad = append(bad, fmt.Sprintf("EXTRACTOR_PROVIDER=%s (must be %s)", cfg.Extractor.Provider, config.ExtractorDisabled))
	}
	if cfg.Embedding.Provider != config.EmbeddingDisabled {
		bad = append(bad, fmt.Sprintf("EMBEDDING_PROVIDER=%s (must be %s)", cfg.Embedding.Provider, config.EmbeddingDisabled))
	}
	if cfg.Semantic.Mode != config.SemanticDisabled {
		bad = append(bad, fmt.Sprintf("SEMANTIC_SEARCH=%s (must be %s; the demo reads vectors from its artifact)", cfg.Semantic.Mode, config.SemanticDisabled))
	}
	if len(bad) > 0 {
		return fmt.Errorf("public demo refuses live providers: %s", strings.Join(bad, "; "))
	}
	return nil
}

// buildPublicDemo opens the artifact read-only and wires the existing library,
// semantic and hybrid services over the artifact's read-only index, fixed
// publication and preset-only query vectors, behind the demo allowlist.
func buildPublicDemo(cfg config.Config, artifactDir string, allowMechanical bool, webDir string) (_ *demoServer, err error) {
	if err := checkPublicDemoConfig(cfg); err != nil {
		return nil, err
	}
	a, db, err := publicdemo.OpenArtifact(context.Background(), artifactDir)
	if err != nil {
		return nil, err
	}
	defer func() {
		if err != nil {
			db.Close()
		}
	}()
	if a.Mechanical() && !allowMechanical {
		return nil, fmt.Errorf("artifact vectors are mechanical test fixtures (release_status %s); pass -public-demo-allow-mechanical for a local smoke only", a.Manifest.ReleaseStatus)
	}
	conceptRepo := sqlite.NewConceptRepository(db)
	library := application.NewKnowledgeLibraryService(conceptRepo, sqlite.NewKnowledgeRepository(db), sqlite.NewEntryRepository(db),
		sqlite.NewAnalysisRepository(db), sqlite.NewFeedbackRepository(db), application.NewEffectiveAnnotationService(conceptRepo, conceptRepo))
	vectors := publicdemo.NewPresetQueryVectors(a)
	semantic := application.NewSemanticSearchService(conceptRepo, library, publicdemo.NewPublication(a), publicdemo.NewIndex(a), vectors, a.Space)
	hybrid := application.NewHybridSearchService(library, semantic, conceptRepo, library)
	handler := transporthttp.NewHandler(nil, nil, nil, nil, nil, nil, nil, nil, nil, nil,
		transporthttp.WithKnowledgeLibrary(library),
		transporthttp.WithSemanticSearch(semantic),
		transporthttp.WithHybridSearch(hybrid),
		transporthttp.WithReadiness(db.PingContext),
		transporthttp.WithPublicDemo(a, vectors),
	)
	routes := handler.Routes()
	if webDir != "" {
		if routes, err = transporthttp.NewWorkbenchHandler(routes, webDir); err != nil {
			return nil, err
		}
	}
	routes = transporthttp.NewPublicDemoBoundary(routes, webDir != "")
	if routes, err = transporthttp.NewBrowserBoundary(routes, cfg.HTTPBoundary); err != nil {
		return nil, err
	}
	return &demoServer{routes: routes, artifact: a, close: db.Close}, nil
}

type demoServer struct {
	routes   http.Handler
	artifact *publicdemo.Artifact
	close    func() error
}

// runPublicDemo serves the read-only demo. DB_PATH is never opened.
func runPublicDemo(cfg config.Config, artifactDir string, allowMechanical bool, webDir string) error {
	d, err := buildPublicDemo(cfg, artifactDir, allowMechanical, webDir)
	if err != nil {
		return err
	}
	defer d.close()
	m := d.artifact.Manifest
	log.Printf("PUBLIC DEMO (read-only): artifact %s version %s, manifest sha256 %s", d.artifact.Dir, m.ArtifactVersion, d.artifact.ManifestSHA256)
	log.Printf("PUBLIC DEMO vectors: source=%s real_model=%v model=%s dims=%d release_status=%s", m.Vectors.Source, m.Vectors.RealModel, m.Vectors.ModelID, m.Vectors.Dimensions, m.ReleaseStatus)
	if d.artifact.Mechanical() {
		log.Printf("PUBLIC DEMO WARNING: mechanical test vectors; semantic and hybrid rankings are not semantic. Not for public release.")
	}
	return serve(cfg, d.routes, "public demo, database read-only; DB_PATH not opened")
}
