package http_test

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

type retrievalEvaluationExtractor struct{}

func (*retrievalEvaluationExtractor) Name() string {
	return "stub:test:retrieval_evaluation_v1"
}

func (*retrievalEvaluationExtractor) Extract(_ context.Context, source domain.ExtractionSource) (domain.ExtractionResult, error) {
	canonical := "parler + nom de langue — pas d'article"
	statement := "Seed representation for the durable Concept."
	if source.OriginalInput == "later retrieval query" {
		canonical = "nom de langue — omission d'article après parler"
		statement = "Later wording that a human maps to the existing Concept."
	}
	return domain.ExtractionResult{Units: []domain.ExtractedUnit{{
		Kind: domain.KindGrammar, Canonical: canonical, Statement: statement, Confidence: 0.9,
	}}}, nil
}

func setupRetrievalEvaluationServer(t *testing.T) (*httptest.Server, *sqlite.EntryRepository, *sqlite.AnalysisRepository) {
	t.Helper()
	db, err := sqlite.Open(filepath.Join(t.TempDir(), "retrieval_evaluation_it.db"))
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	t.Cleanup(func() { db.Close() })

	entryRepo := sqlite.NewEntryRepository(db)
	analysisRepo := sqlite.NewAnalysisRepository(db)
	feedbackRepo := sqlite.NewFeedbackRepository(db)
	inventoryRepo := sqlite.NewInventoryRepository(db)
	captureRepo := sqlite.NewCaptureRepository(db)
	knowledgeRepo := sqlite.NewKnowledgeRepository(db)
	admissionRepo := sqlite.NewAdmissionRepository(db)
	conceptRepo := sqlite.NewConceptRepository(db)

	entrySvc := application.NewEntryService(entryRepo)
	analysisSvc := application.NewAnalysisService(entryRepo, analysisRepo, nil)
	feedbackSvc := application.NewFeedbackService(feedbackRepo)
	effectiveSvc := application.NewEffectiveAnalysisService(analysisRepo, feedbackRepo)
	inventorySvc := application.NewInventoryService(inventoryRepo)
	captureSvc := application.NewCaptureService(captureRepo)
	knowledgeSvc := application.NewKnowledgeService(entryRepo, analysisRepo, feedbackRepo, knowledgeRepo, admissionRepo, &retrievalEvaluationExtractor{})
	conceptSvc := application.NewConceptService(knowledgeRepo, conceptRepo, conceptRepo)
	effectiveAnnotationSvc := application.NewEffectiveAnnotationService(conceptRepo, conceptRepo)
	datasetSvc := application.NewConceptAnnotationDatasetService(effectiveAnnotationSvc, knowledgeRepo, conceptRepo)
	qualitySvc := application.NewConceptAnnotationDatasetQualityService(datasetSvc)
	evaluationSvc := application.NewConceptRetrievalEvaluationService(datasetSvc, qualitySvc, conceptSvc, application.NewExactSignatureConceptRetriever())

	handler := transporthttp.NewHandler(
		entrySvc, analysisSvc, feedbackSvc, effectiveSvc, inventorySvc, captureSvc,
		knowledgeSvc, conceptSvc, effectiveAnnotationSvc, datasetSvc,
		transporthttp.WithAnnotationDatasetQuality(qualitySvc),
		transporthttp.WithRetrievalEvaluation(evaluationSvc),
	)
	server := httptest.NewServer(handler.Routes())
	t.Cleanup(server.Close)
	return server, entryRepo, analysisRepo
}

func createRetrievalEvaluationEntry(t *testing.T, entries *sqlite.EntryRepository, analyses *sqlite.AnalysisRepository, originalInput string) int64 {
	t.Helper()
	ctx := context.Background()
	entry, err := entries.Create(ctx, domain.NewEntryInput{OriginalInput: originalInput, OriginalContext: "retrieval evaluation integration"})
	if err != nil {
		t.Fatalf("create entry: %v", err)
	}
	if _, err := analyses.Create(ctx, entry.ID, domain.AnalysisResult{
		Category: "grammar", Explanation: "language names after parler", Confidence: 0.9,
	}, "rule-based:test"); err != nil {
		t.Fatalf("create analysis: %v", err)
	}
	return entry.ID
}

func TestIntegration_RetrievalEvaluationExcludesSeedAndAuditsLaterExactMiss(t *testing.T) {
	server, entries, analyses := setupRetrievalEvaluationServer(t)

	seedEntryID := createRetrievalEvaluationEntry(t, entries, analyses, "seed concept query")
	seedUnitID := extractUnits(t, server, seedEntryID)[0]
	createBody := `{
		"identity":{"target":"parler + nom de langue — pas d'article","pedagogical_intent":"grammar"},
		"seed_unit_id":` + itoa(seedUnitID) + `,
		"link_seed_as_same":true
	}`
	createResponse, err := http.Post(server.URL+"/concepts", "application/json", bytes.NewBufferString(createBody))
	if err != nil {
		t.Fatalf("create seed Concept: %v", err)
	}
	if createResponse.StatusCode != http.StatusCreated {
		defer createResponse.Body.Close()
		t.Fatalf("create Concept status = %d", createResponse.StatusCode)
	}
	var created struct {
		Concept struct {
			ID int64 `json:"id"`
		} `json:"concept"`
	}
	if err := json.NewDecoder(createResponse.Body).Decode(&created); err != nil {
		createResponse.Body.Close()
		t.Fatalf("decode created Concept: %v", err)
	}
	createResponse.Body.Close()

	laterEntryID := createRetrievalEvaluationEntry(t, entries, analyses, "later retrieval query")
	laterUnitID := extractUnits(t, server, laterEntryID)[0]
	sameBody := `{"concept_id":` + itoa(created.Concept.ID) + `}`
	sameResponse, err := http.Post(server.URL+"/knowledge-units/"+itoa(laterUnitID)+"/concept-links/same", "application/json", bytes.NewBufferString(sameBody))
	if err != nil {
		t.Fatalf("record later human SAME: %v", err)
	}
	if sameResponse.StatusCode != http.StatusCreated {
		defer sameResponse.Body.Close()
		t.Fatalf("human SAME status = %d", sameResponse.StatusCode)
	}
	sameResponse.Body.Close()

	response, err := http.Get(server.URL + "/retrieval-evaluation/v1")
	if err != nil {
		t.Fatalf("GET retrieval evaluation: %v", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("evaluation status = %d", response.StatusCode)
	}
	var report struct {
		State             string `json:"state"`
		DatasetValid      bool   `json:"dataset_valid"`
		CandidateUniverse struct {
			Concepts int `json:"concepts"`
		} `json:"candidate_universe"`
		EvaluationSamples struct {
			HumanSameRecords int `json:"human_same_records"`
			EligibleSamples  int `json:"eligible_samples"`
			Excluded         struct {
				SeedNewConcept int `json:"seed_new_concept"`
			} `json:"excluded"`
		} `json:"evaluation_samples"`
		Metrics struct {
			RecallAt1 *float64 `json:"recall_at_1"`
			RecallAt3 *float64 `json:"recall_at_3"`
			RecallAt5 *float64 `json:"recall_at_5"`
			MRR       *float64 `json:"mrr"`
		} `json:"metrics"`
		Samples []struct {
			UnitID          int64             `json:"unit_id"`
			HumanSameReason string            `json:"human_same_reason"`
			Retrieved       []json.RawMessage `json:"retrieved"`
			TargetRank      *int              `json:"target_rank"`
		} `json:"samples"`
	}
	if err := json.NewDecoder(response.Body).Decode(&report); err != nil {
		t.Fatalf("decode evaluation: %v", err)
	}
	if report.State != application.ConceptRetrievalEvaluationStateEvaluated || !report.DatasetValid || report.CandidateUniverse.Concepts != 1 {
		t.Fatalf("evaluation state/universe = %+v", report)
	}
	if report.EvaluationSamples.HumanSameRecords != 2 || report.EvaluationSamples.EligibleSamples != 1 || report.EvaluationSamples.Excluded.SeedNewConcept != 1 {
		t.Fatalf("evaluation sample inventory = %+v", report.EvaluationSamples)
	}
	if len(report.Samples) != 1 || report.Samples[0].UnitID != laterUnitID || report.Samples[0].HumanSameReason != "human_same" || len(report.Samples[0].Retrieved) != 0 || report.Samples[0].TargetRank != nil {
		t.Fatalf("later sample audit = %+v", report.Samples)
	}
	if report.Metrics.RecallAt1 == nil || report.Metrics.RecallAt3 == nil || report.Metrics.RecallAt5 == nil || report.Metrics.MRR == nil || *report.Metrics.RecallAt1 != 0 || *report.Metrics.RecallAt3 != 0 || *report.Metrics.RecallAt5 != 0 || *report.Metrics.MRR != 0 {
		t.Fatalf("exact-signature miss metrics = %+v", report.Metrics)
	}
}
