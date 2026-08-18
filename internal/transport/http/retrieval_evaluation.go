package http

import (
	"context"
	"net/http"

	"french-learning-app/internal/application"
)

// RetrievalEvaluationService is the one read-only operation needed by the
// M12-A transport endpoint.
type RetrievalEvaluationService interface {
	BuildV1(ctx context.Context) (application.ConceptRetrievalEvaluationReport, error)
}

type retrievalEvaluationResponse struct {
	SchemaVersion     string                                     `json:"schema_version"`
	EvaluationPolicy  string                                     `json:"evaluation_policy"`
	Retriever         string                                     `json:"retriever"`
	State             string                                     `json:"state"`
	DatasetValid      bool                                       `json:"dataset_valid"`
	CandidateUniverse retrievalCandidateUniverseResponse         `json:"candidate_universe"`
	EvaluationSamples retrievalEvaluationSampleInventoryResponse `json:"evaluation_samples"`
	Metrics           retrievalEvaluationMetricsResponse         `json:"metrics"`
	Samples           []retrievalEvaluationSampleResponse        `json:"samples"`
}

type retrievalCandidateUniverseResponse struct {
	Concepts int `json:"concepts"`
}

type retrievalEvaluationSampleInventoryResponse struct {
	HumanSameRecords int                                   `json:"human_same_records"`
	EligibleSamples  int                                   `json:"eligible_samples"`
	Excluded         retrievalEvaluationExclusionsResponse `json:"excluded"`
}

type retrievalEvaluationExclusionsResponse struct {
	UnclassifiedHumanSameProvenance int `json:"unclassified_human_same_provenance"`
	SeedNewConcept                  int `json:"seed_new_concept"`
	NonActiveAdmission              int `json:"non_active_admission"`
	RetiredTargetConcept            int `json:"retired_target_concept"`
	TargetMissingFromCurrentCatalog int `json:"target_missing_from_current_catalog"`
}

type retrievalEvaluationMetricsResponse struct {
	RecallAt1 *float64 `json:"recall_at_1"`
	RecallAt3 *float64 `json:"recall_at_3"`
	RecallAt5 *float64 `json:"recall_at_5"`
	MRR       *float64 `json:"mrr"`
}

type retrievalEvaluationSampleResponse struct {
	UnitID           int64                            `json:"unit_id"`
	EntryID          int64                            `json:"entry_id"`
	ExtractionID     int64                            `json:"extraction_id"`
	Query            retrievalQueryResponse           `json:"query"`
	TargetConcept    retrievalConceptDocumentResponse `json:"target_concept"`
	HumanSameEventID int64                            `json:"human_same_event_id"`
	HumanSameReason  string                           `json:"human_same_reason"`
	Retrieved        []retrievalCandidateResponse     `json:"retrieved"`
	TargetRank       *int                             `json:"target_rank"`
	ReciprocalRank   float64                          `json:"reciprocal_rank"`
	HitAt1           bool                             `json:"hit_at_1"`
	HitAt3           bool                             `json:"hit_at_3"`
	HitAt5           bool                             `json:"hit_at_5"`
}

type retrievalQueryResponse struct {
	UnitID            int64              `json:"unit_id"`
	Kind              string             `json:"kind"`
	Canonical         string             `json:"canonical"`
	Statement         string             `json:"statement"`
	Example           *string            `json:"example"`
	CandidateIdentity conceptIdentityDTO `json:"candidate_identity"`
}

type retrievalConceptDocumentResponse struct {
	ID                    int64             `json:"id"`
	IdentitySchemaVersion string            `json:"identity_schema_version"`
	Target                string            `json:"target"`
	PedagogicalIntent     string            `json:"pedagogical_intent"`
	Scope                 string            `json:"scope"`
	IdentityFeatures      map[string]string `json:"identity_features"`
	Signature             string            `json:"signature"`
	Lifecycle             string            `json:"lifecycle_state"`
	Support               string            `json:"support_state"`
	State                 string            `json:"state"`
}

type retrievalCandidateResponse struct {
	ConceptID int64   `json:"concept_id"`
	Rank      int     `json:"rank"`
	Score     float64 `json:"score"`
	Evidence  string  `json:"evidence"`
}

func toRetrievalEvaluationResponse(report application.ConceptRetrievalEvaluationReport) retrievalEvaluationResponse {
	response := retrievalEvaluationResponse{
		SchemaVersion: report.SchemaVersion, EvaluationPolicy: report.EvaluationPolicy,
		Retriever: report.Retriever, State: report.State, DatasetValid: report.DatasetValid,
		CandidateUniverse: retrievalCandidateUniverseResponse{Concepts: report.CandidateUniverse.Concepts},
		EvaluationSamples: retrievalEvaluationSampleInventoryResponse{
			HumanSameRecords: report.EvaluationSamples.HumanSameRecords,
			EligibleSamples:  report.EvaluationSamples.EligibleSamples,
			Excluded: retrievalEvaluationExclusionsResponse{
				UnclassifiedHumanSameProvenance: report.EvaluationSamples.Excluded.UnclassifiedHumanSameProvenance,
				SeedNewConcept:                  report.EvaluationSamples.Excluded.SeedNewConcept,
				NonActiveAdmission:              report.EvaluationSamples.Excluded.NonActiveAdmission,
				RetiredTargetConcept:            report.EvaluationSamples.Excluded.RetiredTargetConcept,
				TargetMissingFromCurrentCatalog: report.EvaluationSamples.Excluded.TargetMissingFromCurrentCatalog,
			},
		},
		Metrics: retrievalEvaluationMetricsResponse{
			RecallAt1: report.Metrics.RecallAt1, RecallAt3: report.Metrics.RecallAt3,
			RecallAt5: report.Metrics.RecallAt5, MRR: report.Metrics.MRR,
		},
		Samples: make([]retrievalEvaluationSampleResponse, 0, len(report.Samples)),
	}
	for _, sample := range report.Samples {
		retrieved := make([]retrievalCandidateResponse, 0, len(sample.Retrieved))
		for _, candidate := range sample.Retrieved {
			retrieved = append(retrieved, retrievalCandidateResponse{
				ConceptID: candidate.ConceptID, Rank: candidate.Rank,
				Score: candidate.Score, Evidence: candidate.Evidence,
			})
		}
		response.Samples = append(response.Samples, retrievalEvaluationSampleResponse{
			UnitID: sample.UnitID, EntryID: sample.EntryID, ExtractionID: sample.ExtractionID,
			Query: retrievalQueryResponse{
				UnitID: sample.Query.UnitID, Kind: string(sample.Query.Kind),
				Canonical: sample.Query.Canonical, Statement: sample.Query.Statement,
				Example: sample.Query.Example, CandidateIdentity: toIdentityDTO(sample.Query.CandidateIdentity),
			},
			TargetConcept:    toRetrievalConceptDocumentResponse(sample.TargetConcept),
			HumanSameEventID: sample.HumanSameEventID, HumanSameReason: sample.HumanSameReason,
			Retrieved: retrieved, TargetRank: sample.TargetRank,
			ReciprocalRank: sample.ReciprocalRank, HitAt1: sample.HitAt1,
			HitAt3: sample.HitAt3, HitAt5: sample.HitAt5,
		})
	}
	return response
}

func toRetrievalConceptDocumentResponse(document application.ConceptRetrievalDocument) retrievalConceptDocumentResponse {
	features := document.IdentityFeatures
	if features == nil {
		features = map[string]string{}
	}
	return retrievalConceptDocumentResponse{
		ID: document.ConceptID, IdentitySchemaVersion: document.IdentitySchemaVersion,
		Target: document.Target, PedagogicalIntent: document.PedagogicalIntent,
		Scope: document.Scope, IdentityFeatures: features, Signature: document.Signature,
		Lifecycle: string(document.Lifecycle), Support: string(document.Support), State: string(document.State),
	}
}

func (h *Handler) handleGetRetrievalEvaluationV1(w http.ResponseWriter, r *http.Request) {
	if h.retrievalEvaluation == nil {
		writeError(w, http.StatusInternalServerError, "could not build concept retrieval evaluation")
		return
	}
	report, err := h.retrievalEvaluation.BuildV1(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not build concept retrieval evaluation")
		return
	}
	writeJSON(w, http.StatusOK, toRetrievalEvaluationResponse(report))
}
