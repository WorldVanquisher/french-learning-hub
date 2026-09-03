package http

import (
	"context"
	"errors"
	"net/http"

	"french-learning-app/internal/application"
)

// RetrievalComparisonService is the single read-only operation needed by the
// compact M13-A0 comparison endpoint.
type RetrievalComparisonService interface {
	BuildV1(ctx context.Context) (application.ConceptRetrievalComparisonReport, error)
}

type retrievalComparisonResponse struct {
	SchemaVersion     string                                     `json:"schema_version"`
	State             string                                     `json:"state"`
	DatasetValid      bool                                       `json:"dataset_valid"`
	CandidateUniverse retrievalCandidateUniverseResponse         `json:"candidate_universe"`
	EvaluationSamples retrievalComparisonSampleInventoryResponse `json:"evaluation_samples"`
	Retrievers        []retrievalComparisonRetrieverResponse     `json:"retrievers"`
}

type retrievalComparisonSampleInventoryResponse struct {
	EligibleSamples int `json:"eligible_samples"`
}

type retrievalComparisonRetrieverResponse struct {
	Retriever string                             `json:"retriever"`
	State     string                             `json:"state"`
	Metrics   retrievalEvaluationMetricsResponse `json:"metrics"`
}

func toRetrievalComparisonResponse(report application.ConceptRetrievalComparisonReport) retrievalComparisonResponse {
	response := retrievalComparisonResponse{
		SchemaVersion:     report.SchemaVersion,
		State:             report.State,
		DatasetValid:      report.DatasetValid,
		CandidateUniverse: retrievalCandidateUniverseResponse{Concepts: report.CandidateUniverse.Concepts},
		EvaluationSamples: retrievalComparisonSampleInventoryResponse{EligibleSamples: report.EvaluationSamples.EligibleSamples},
		Retrievers:        make([]retrievalComparisonRetrieverResponse, 0, len(report.Retrievers)),
	}
	for _, row := range report.Retrievers {
		response.Retrievers = append(response.Retrievers, retrievalComparisonRetrieverResponse{
			Retriever: row.Retriever,
			State:     row.State,
			Metrics: retrievalEvaluationMetricsResponse{
				RecallAt1: row.Metrics.RecallAt1,
				RecallAt3: row.Metrics.RecallAt3,
				RecallAt5: row.Metrics.RecallAt5,
				MRR:       row.Metrics.MRR,
			},
		})
	}
	return response
}

func (h *Handler) handleGetRetrievalComparisonV1(w http.ResponseWriter, r *http.Request) {
	if h.retrievalComparison == nil {
		writeError(w, http.StatusInternalServerError, "could not build concept retrieval comparison")
		return
	}
	report, err := h.retrievalComparison.BuildV1(r.Context())
	if errors.Is(err, application.ErrEmbeddingProviderTimeout) {
		writeError(w, http.StatusGatewayTimeout, "embedding provider timed out")
		return
	}
	if errors.Is(err, application.ErrEmbeddingProviderUnavailable) {
		writeError(w, http.StatusBadGateway, "embedding provider unavailable")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not build concept retrieval comparison")
		return
	}
	writeJSON(w, http.StatusOK, toRetrievalComparisonResponse(report))
}
