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
		statement = "On n'emploie pas d'article défini devant un nom de langue après un verbe comme parler."
	}
	return domain.ExtractionResult{Units: []domain.ExtractedUnit{{
		Kind: domain.KindGrammar, Canonical: canonical, Statement: statement, Confidence: 0.9,
	}}}, nil
}

type retrievalEvaluationEmbeddingProvider struct {
	calls   int
	batches [][]string
}

func (*retrievalEvaluationEmbeddingProvider) Name() string {
	return "frozen:retrieval-integration-v1"
}

func (p *retrievalEvaluationEmbeddingProvider) Embed(_ context.Context, texts []string) ([][]float64, error) {
	p.calls++
	p.batches = append(p.batches, append([]string(nil), texts...))
	vectors := make([][]float64, len(texts))
	for index := range texts {
		vectors[index] = []float64{1, 0}
	}
	return vectors, nil
}

func setupRetrievalEvaluationServer(t *testing.T) (*httptest.Server, *sqlite.EntryRepository, *sqlite.AnalysisRepository, *retrievalEvaluationEmbeddingProvider) {
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
	embeddingProvider := &retrievalEvaluationEmbeddingProvider{}
	evaluationSvc := application.NewConceptRetrievalEvaluationServiceWithRegistry(
		datasetSvc,
		qualitySvc,
		conceptSvc,
		application.NewConceptRetrieverRegistry(
			application.NewExactSignatureConceptRetriever(),
			application.NewWeightedLexicalConceptRetriever(),
			application.NewBM25ConceptRetriever(),
			application.NewEmbeddingConceptRetriever(embeddingProvider),
		),
	)
	comparisonSvc := application.NewConceptRetrievalComparisonService(evaluationSvc)

	handler := transporthttp.NewHandler(
		entrySvc, analysisSvc, feedbackSvc, effectiveSvc, inventorySvc, captureSvc,
		knowledgeSvc, conceptSvc, effectiveAnnotationSvc, datasetSvc,
		transporthttp.WithAnnotationDatasetQuality(qualitySvc),
		transporthttp.WithRetrievalEvaluation(evaluationSvc),
		transporthttp.WithRetrievalComparison(comparisonSvc),
	)
	server := httptest.NewServer(handler.Routes())
	t.Cleanup(server.Close)
	return server, entryRepo, analysisRepo, embeddingProvider
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

type retrievalEvaluationIntegrationReport struct {
	Retriever         string `json:"retriever"`
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
		UnitID          int64  `json:"unit_id"`
		HumanSameReason string `json:"human_same_reason"`
		TargetConcept   struct {
			ID int64 `json:"id"`
		} `json:"target_concept"`
		Retrieved []struct {
			ConceptID int64 `json:"concept_id"`
			Rank      int   `json:"rank"`
		} `json:"retrieved"`
		TargetRank *int `json:"target_rank"`
	} `json:"samples"`
}

type retrievalComparisonIntegrationReport struct {
	SchemaVersion     string `json:"schema_version"`
	State             string `json:"state"`
	DatasetValid      bool   `json:"dataset_valid"`
	CandidateUniverse struct {
		Concepts int `json:"concepts"`
	} `json:"candidate_universe"`
	EvaluationSamples struct {
		EligibleSamples int `json:"eligible_samples"`
	} `json:"evaluation_samples"`
	Retrievers []struct {
		Retriever string `json:"retriever"`
		State     string `json:"state"`
		Metrics   struct {
			RecallAt1 *float64 `json:"recall_at_1"`
			RecallAt3 *float64 `json:"recall_at_3"`
			RecallAt5 *float64 `json:"recall_at_5"`
			MRR       *float64 `json:"mrr"`
		} `json:"metrics"`
	} `json:"retrievers"`
}

func getRetrievalEvaluationIntegrationReport(t *testing.T, url string) retrievalEvaluationIntegrationReport {
	t.Helper()
	response, err := http.Get(url)
	if err != nil {
		t.Fatalf("GET retrieval evaluation: %v", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("evaluation status = %d", response.StatusCode)
	}
	var report retrievalEvaluationIntegrationReport
	if err := json.NewDecoder(response.Body).Decode(&report); err != nil {
		t.Fatalf("decode evaluation: %v", err)
	}
	return report
}

func getRetrievalComparisonIntegrationReport(t *testing.T, url string) retrievalComparisonIntegrationReport {
	t.Helper()
	response, err := http.Get(url)
	if err != nil {
		t.Fatalf("GET retrieval comparison: %v", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("comparison status = %d", response.StatusCode)
	}
	var report retrievalComparisonIntegrationReport
	if err := json.NewDecoder(response.Body).Decode(&report); err != nil {
		t.Fatalf("decode comparison: %v", err)
	}
	return report
}

func TestIntegration_RetrievalEvaluationComparesConfiguredRetrievers(t *testing.T) {
	server, entries, analyses, embeddingProvider := setupRetrievalEvaluationServer(t)

	seedEntryID := createRetrievalEvaluationEntry(t, entries, analyses, "seed concept query")
	seedUnitID := extractUnits(t, server, seedEntryID)[0]
	createBody := `{
		"identity":{"target":"parler + nom de langue — pas d'article","pedagogical_intent":"usage"},
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

	exact := getRetrievalEvaluationIntegrationReport(t, server.URL+"/retrieval-evaluation/v1")
	weighted := getRetrievalEvaluationIntegrationReport(t, server.URL+"/retrieval-evaluation/v1?retriever="+application.WeightedLexicalRetrieverV1Name)
	bm25 := getRetrievalEvaluationIntegrationReport(t, server.URL+"/retrieval-evaluation/v1?retriever="+application.BM25RetrieverV1Name)
	embedding := getRetrievalEvaluationIntegrationReport(t, server.URL+"/retrieval-evaluation/v1?retriever="+application.EmbeddingRetrieverV1Name)
	comparison := getRetrievalComparisonIntegrationReport(t, server.URL+"/retrieval-comparison/v1")

	if exact.Retriever != application.ExactSignatureRetrieverV1Name || weighted.Retriever != application.WeightedLexicalRetrieverV1Name || bm25.Retriever != application.BM25RetrieverV1Name || embedding.Retriever != application.EmbeddingRetrieverV1Name {
		t.Fatalf("retrievers = %q, %q, %q, %q", exact.Retriever, weighted.Retriever, bm25.Retriever, embedding.Retriever)
	}
	for name, report := range map[string]retrievalEvaluationIntegrationReport{"exact": exact, "weighted": weighted, "bm25": bm25, "embedding": embedding} {
		if report.State != application.ConceptRetrievalEvaluationStateEvaluated || !report.DatasetValid || report.CandidateUniverse.Concepts != 1 {
			t.Fatalf("%s evaluation state/universe = %+v", name, report)
		}
		if report.EvaluationSamples.HumanSameRecords != 2 || report.EvaluationSamples.EligibleSamples != 1 || report.EvaluationSamples.Excluded.SeedNewConcept != 1 {
			t.Fatalf("%s evaluation sample inventory = %+v", name, report.EvaluationSamples)
		}
		if len(report.Samples) != 1 || report.Samples[0].UnitID != laterUnitID || report.Samples[0].HumanSameReason != "human_same" || report.Samples[0].TargetConcept.ID != created.Concept.ID {
			t.Fatalf("%s later sample identity = %+v", name, report.Samples)
		}
	}
	if len(exact.Samples[0].Retrieved) != 0 || exact.Samples[0].TargetRank != nil {
		t.Fatalf("exact later sample audit = %+v", exact.Samples)
	}
	if exact.Metrics.RecallAt1 == nil || exact.Metrics.RecallAt3 == nil || exact.Metrics.RecallAt5 == nil || exact.Metrics.MRR == nil || *exact.Metrics.RecallAt1 != 0 || *exact.Metrics.RecallAt3 != 0 || *exact.Metrics.RecallAt5 != 0 || *exact.Metrics.MRR != 0 {
		t.Fatalf("exact-signature miss metrics = %+v", exact.Metrics)
	}
	if len(weighted.Samples[0].Retrieved) == 0 || weighted.Samples[0].Retrieved[0].ConceptID != created.Concept.ID || weighted.Samples[0].Retrieved[0].Rank != 1 || weighted.Samples[0].TargetRank == nil || *weighted.Samples[0].TargetRank != 1 {
		t.Fatalf("weighted later sample audit = %+v", weighted.Samples)
	}
	if weighted.Metrics.RecallAt1 == nil || weighted.Metrics.RecallAt3 == nil || weighted.Metrics.RecallAt5 == nil || weighted.Metrics.MRR == nil || *weighted.Metrics.RecallAt1 != 1 || *weighted.Metrics.RecallAt3 != 1 || *weighted.Metrics.RecallAt5 != 1 || *weighted.Metrics.MRR != 1 {
		t.Fatalf("weighted lexical hit metrics = %+v", weighted.Metrics)
	}
	if len(bm25.Samples[0].Retrieved) == 0 || bm25.Samples[0].Retrieved[0].ConceptID != created.Concept.ID || bm25.Samples[0].Retrieved[0].Rank != 1 || bm25.Samples[0].TargetRank == nil || *bm25.Samples[0].TargetRank != 1 {
		t.Fatalf("BM25 later sample audit = %+v", bm25.Samples)
	}
	if bm25.Metrics.RecallAt1 == nil || bm25.Metrics.RecallAt3 == nil || bm25.Metrics.RecallAt5 == nil || bm25.Metrics.MRR == nil || *bm25.Metrics.RecallAt1 != 1 || *bm25.Metrics.RecallAt3 != 1 || *bm25.Metrics.RecallAt5 != 1 || *bm25.Metrics.MRR != 1 {
		t.Fatalf("BM25 lexical hit metrics = %+v", bm25.Metrics)
	}
	if len(embedding.Samples[0].Retrieved) == 0 || embedding.Samples[0].Retrieved[0].ConceptID != created.Concept.ID || embedding.Samples[0].Retrieved[0].Rank != 1 || embedding.Samples[0].TargetRank == nil || *embedding.Samples[0].TargetRank != 1 {
		t.Fatalf("embedding later sample audit = %+v", embedding.Samples)
	}
	if embedding.Metrics.RecallAt1 == nil || embedding.Metrics.RecallAt3 == nil || embedding.Metrics.RecallAt5 == nil || embedding.Metrics.MRR == nil || *embedding.Metrics.RecallAt1 != 1 || *embedding.Metrics.RecallAt3 != 1 || *embedding.Metrics.RecallAt5 != 1 || *embedding.Metrics.MRR != 1 {
		t.Fatalf("embedding hit metrics = %+v", embedding.Metrics)
	}
	if comparison.SchemaVersion != application.ConceptRetrievalComparisonV1SchemaVersion || comparison.State != application.ConceptRetrievalEvaluationStateEvaluated || !comparison.DatasetValid || comparison.CandidateUniverse.Concepts != 1 || comparison.EvaluationSamples.EligibleSamples != 1 || len(comparison.Retrievers) != 4 {
		t.Fatalf("comparison identity/population = %+v", comparison)
	}
	wantComparisonOrder := []string{application.ExactSignatureRetrieverV1Name, application.WeightedLexicalRetrieverV1Name, application.BM25RetrieverV1Name, application.EmbeddingRetrieverV1Name}
	for index, name := range wantComparisonOrder {
		row := comparison.Retrievers[index]
		if row.Retriever != name || row.State != application.ConceptRetrievalEvaluationStateEvaluated || row.Metrics.RecallAt1 == nil || row.Metrics.RecallAt3 == nil || row.Metrics.RecallAt5 == nil || row.Metrics.MRR == nil {
			t.Fatalf("comparison row[%d] = %+v", index, row)
		}
	}
	if *comparison.Retrievers[0].Metrics.RecallAt1 != 0 || *comparison.Retrievers[1].Metrics.RecallAt1 != 1 || *comparison.Retrievers[2].Metrics.RecallAt1 != 1 || *comparison.Retrievers[3].Metrics.RecallAt1 != 1 {
		t.Fatalf("comparison Recall@1 rows = %+v", comparison.Retrievers)
	}
	if embeddingProvider.calls != 2 || len(embeddingProvider.batches) != 2 || len(embeddingProvider.batches[0]) != 2 || len(embeddingProvider.batches[1]) != 2 {
		t.Fatalf("embedding provider calls/batches = %d, %#v", embeddingProvider.calls, embeddingProvider.batches)
	}
}
