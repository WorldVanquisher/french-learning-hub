// Command server runs the French-learning HTTP API.
package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"french-learning-app/internal/analyzer"
	"french-learning-app/internal/application"
	"french-learning-app/internal/config"
	"french-learning-app/internal/embedding"
	"french-learning-app/internal/extractor"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

func main() {
	if err := run(); err != nil {
		log.Fatalf("server error: %v", err)
	}
}

func run() error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}

	// Ensure the database directory exists.
	if dir := filepath.Dir(cfg.DBPath); dir != "" && dir != "." {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return err
		}
	}

	db, err := sqlite.Open(cfg.DBPath)
	if err != nil {
		return err
	}
	defer db.Close()

	entryRepo := sqlite.NewEntryRepository(db)
	analysisRepo := sqlite.NewAnalysisRepository(db)
	feedbackRepo := sqlite.NewFeedbackRepository(db)
	inventoryRepo := sqlite.NewInventoryRepository(db)
	captureRepo := sqlite.NewCaptureRepository(db)
	knowledgeRepo := sqlite.NewKnowledgeRepository(db)
	admissionRepo := sqlite.NewAdmissionRepository(db)
	conceptRepo := sqlite.NewConceptRepository(db)

	selectedAnalyzer, err := analyzer.New(cfg.AI)
	if err != nil {
		return err
	}

	// The extractor is opt-in and decoupled from the analyzer. A nil extractor
	// (EXTRACTOR_PROVIDER=disabled, the default) is valid: the server runs
	// normally and the extraction endpoints report the feature as unavailable.
	selectedExtractor, err := extractor.New(cfg.Extractor)
	if err != nil {
		return err
	}
	selectedEmbeddingProvider, err := embedding.New(cfg.Embedding)
	if err != nil {
		return err
	}

	entrySvc := application.NewEntryService(entryRepo)
	analysisSvc := application.NewAnalysisService(entryRepo, analysisRepo, selectedAnalyzer)
	feedbackSvc := application.NewFeedbackService(feedbackRepo)
	effectiveSvc := application.NewEffectiveAnalysisService(analysisRepo, feedbackRepo)
	inventorySvc := application.NewInventoryService(inventoryRepo)
	captureSvc := application.NewCaptureService(captureRepo)
	knowledgeSvc := application.NewKnowledgeService(entryRepo, analysisRepo, feedbackRepo, knowledgeRepo, admissionRepo, selectedExtractor)
	conceptSvc := application.NewConceptService(knowledgeRepo, conceptRepo, conceptRepo)
	effectiveAnnotationSvc := application.NewEffectiveAnnotationService(conceptRepo, conceptRepo)
	annotationDatasetSvc := application.NewConceptAnnotationDatasetService(effectiveAnnotationSvc, knowledgeRepo, conceptRepo)
	annotationQualitySvc := application.NewConceptAnnotationDatasetQualityService(annotationDatasetSvc)
	additionalRetrievers := []application.ConceptRetriever{
		application.NewWeightedLexicalConceptRetriever(),
		application.NewBM25ConceptRetriever(),
	}
	if selectedEmbeddingProvider != nil {
		additionalRetrievers = append(additionalRetrievers, application.NewEmbeddingConceptRetriever(selectedEmbeddingProvider))
	}
	retrievalEvaluationSvc := application.NewConceptRetrievalEvaluationServiceWithRegistry(
		annotationDatasetSvc,
		annotationQualitySvc,
		conceptSvc,
		application.NewConceptRetrieverRegistry(
			application.NewExactSignatureConceptRetriever(),
			additionalRetrievers...,
		),
	)
	retrievalComparisonSvc := application.NewConceptRetrievalComparisonService(retrievalEvaluationSvc)

	log.Printf("analyzer provider: %s", cfg.AI.Provider)
	log.Printf("extractor provider: %s", cfg.Extractor.Provider)
	log.Printf("embedding provider: %s", cfg.Embedding.Provider)

	handler := transporthttp.NewHandler(
		entrySvc, analysisSvc, feedbackSvc, effectiveSvc, inventorySvc, captureSvc,
		knowledgeSvc, conceptSvc, effectiveAnnotationSvc, annotationDatasetSvc,
		transporthttp.WithAnnotationDatasetQuality(annotationQualitySvc),
		transporthttp.WithRetrievalEvaluation(retrievalEvaluationSvc),
		transporthttp.WithRetrievalComparison(retrievalComparisonSvc),
	)

	srv := &http.Server{
		Addr:         cfg.Addr,
		Handler:      handler.Routes(),
		ReadTimeout:  cfg.ReadTimeout,
		WriteTimeout: cfg.WriteTimeout,
	}

	// Graceful shutdown on SIGINT/SIGTERM.
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	errCh := make(chan error, 1)
	go func() {
		log.Printf("listening on %s (db=%s)", cfg.Addr, cfg.DBPath)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- err
		}
	}()

	select {
	case err := <-errCh:
		return err
	case <-ctx.Done():
		log.Println("shutting down")
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		return srv.Shutdown(shutdownCtx)
	}
}
