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

	selectedAnalyzer, err := analyzer.New(cfg.AI)
	if err != nil {
		return err
	}

	entrySvc := application.NewEntryService(entryRepo)
	analysisSvc := application.NewAnalysisService(entryRepo, analysisRepo, selectedAnalyzer)
	feedbackSvc := application.NewFeedbackService(feedbackRepo)

	log.Printf("analyzer provider: %s", cfg.AI.Provider)

	handler := transporthttp.NewHandler(entrySvc, analysisSvc, feedbackSvc)

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
