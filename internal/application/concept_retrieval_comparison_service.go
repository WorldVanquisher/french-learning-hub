package application

import (
	"context"
	"errors"
	"fmt"
	"reflect"
)

const (
	// ConceptRetrievalComparisonV1SchemaVersion identifies the compact M13-A0
	// report comparing the existing M12 retrieval baselines.
	ConceptRetrievalComparisonV1SchemaVersion = "concept_retrieval_comparison_v1"

	// ConceptRetrievalComparisonRetrieverStateUnavailable is emitted only for
	// the optional embedding baseline when it is not registered in production.
	ConceptRetrievalComparisonRetrieverStateUnavailable = "unavailable"
)

var (
	// ErrConceptRetrievalComparisonInconsistent prevents a compact report from
	// presenting metrics produced from different experiment populations.
	ErrConceptRetrievalComparisonInconsistent = errors.New("inconsistent concept retrieval comparison population")

	conceptRetrievalComparisonRetrieversV1 = []string{
		ExactSignatureRetrieverV1Name,
		WeightedLexicalRetrieverV1Name,
		BM25RetrieverV1Name,
		EmbeddingRetrieverV1Name,
	}
)

// ConceptRetrievalEvaluationBuilder is the sole comparison dependency. The
// existing M12 service continues to own quality gating, population, retrieval,
// metrics, and per-sample audit construction.
type ConceptRetrievalEvaluationBuilder interface {
	BuildV1WithRetriever(ctx context.Context, name string) (ConceptRetrievalEvaluationReport, error)
}

type ConceptRetrievalComparisonSampleInventory struct {
	EligibleSamples int
}

type ConceptRetrievalComparisonRetriever struct {
	Retriever string
	State     string
	Metrics   ConceptRetrievalEvaluationMetrics
}

// ConceptRetrievalComparisonReport is a compact, read-only projection over the
// existing detailed evaluation reports. It intentionally omits per-sample audit
// output while retaining shared population metadata and top-level metrics.
type ConceptRetrievalComparisonReport struct {
	SchemaVersion     string
	State             string
	DatasetValid      bool
	CandidateUniverse ConceptRetrievalCandidateUniverse
	EvaluationSamples ConceptRetrievalComparisonSampleInventory
	Retrievers        []ConceptRetrievalComparisonRetriever
}

// ConceptRetrievalComparisonService orchestrates the fixed M12 baseline set.
// It implements no ranking, truth, population, exclusion, or metric logic.
type ConceptRetrievalComparisonService struct {
	evaluation ConceptRetrievalEvaluationBuilder
}

func NewConceptRetrievalComparisonService(evaluation ConceptRetrievalEvaluationBuilder) *ConceptRetrievalComparisonService {
	return &ConceptRetrievalComparisonService{evaluation: evaluation}
}

// BuildV1 evaluates each fixed baseline under the existing M12 contract, checks
// that all evaluated reports describe the same experiment population, then
// copies their metrics into the compact comparison response. An unregistered
// optional embedding retriever becomes an explicit unavailable row; configured
// provider failures propagate and never fall back.
func (s *ConceptRetrievalComparisonService) BuildV1(ctx context.Context) (ConceptRetrievalComparisonReport, error) {
	report := ConceptRetrievalComparisonReport{
		SchemaVersion: ConceptRetrievalComparisonV1SchemaVersion,
		Retrievers:    make([]ConceptRetrievalComparisonRetriever, 0, len(conceptRetrievalComparisonRetrieversV1)),
	}
	if s == nil || s.evaluation == nil {
		return ConceptRetrievalComparisonReport{}, errors.New("concept retrieval evaluation service is not configured")
	}

	var reference *ConceptRetrievalEvaluationReport
	for _, retrieverName := range conceptRetrievalComparisonRetrieversV1 {
		evaluation, err := s.evaluation.BuildV1WithRetriever(ctx, retrieverName)
		if err != nil {
			if retrieverName == EmbeddingRetrieverV1Name && errors.Is(err, ErrUnknownConceptRetriever) {
				report.Retrievers = append(report.Retrievers, ConceptRetrievalComparisonRetriever{
					Retriever: retrieverName,
					State:     ConceptRetrievalComparisonRetrieverStateUnavailable,
				})
				continue
			}
			return ConceptRetrievalComparisonReport{}, fmt.Errorf("build %s evaluation for comparison: %w", retrieverName, err)
		}
		if evaluation.Retriever != retrieverName {
			return ConceptRetrievalComparisonReport{}, fmt.Errorf(
				"%w: requested %s but evaluation reported %s",
				ErrConceptRetrievalComparisonInconsistent, retrieverName, evaluation.Retriever,
			)
		}

		if reference == nil {
			copyOfEvaluation := evaluation
			reference = &copyOfEvaluation
			report.State = evaluation.State
			report.DatasetValid = evaluation.DatasetValid
			report.CandidateUniverse = evaluation.CandidateUniverse
			report.EvaluationSamples.EligibleSamples = evaluation.EvaluationSamples.EligibleSamples
		} else if err := validateConceptRetrievalComparisonPopulation(*reference, evaluation); err != nil {
			return ConceptRetrievalComparisonReport{}, err
		}

		report.Retrievers = append(report.Retrievers, ConceptRetrievalComparisonRetriever{
			Retriever: evaluation.Retriever,
			State:     evaluation.State,
			Metrics:   evaluation.Metrics,
		})
	}

	if reference == nil {
		return ConceptRetrievalComparisonReport{}, errors.New("concept retrieval comparison has no evaluated baseline")
	}
	return report, nil
}

func validateConceptRetrievalComparisonPopulation(reference, selected ConceptRetrievalEvaluationReport) error {
	if reference.SchemaVersion != selected.SchemaVersion ||
		reference.EvaluationPolicy != selected.EvaluationPolicy ||
		reference.State != selected.State ||
		reference.DatasetValid != selected.DatasetValid ||
		reference.CandidateUniverse != selected.CandidateUniverse ||
		reference.EvaluationSamples != selected.EvaluationSamples {
		return fmt.Errorf(
			"%w: %s shared evaluation metadata differs from %s",
			ErrConceptRetrievalComparisonInconsistent, selected.Retriever, reference.Retriever,
		)
	}
	if len(reference.Samples) != len(selected.Samples) {
		return fmt.Errorf(
			"%w: %s sample count differs from %s",
			ErrConceptRetrievalComparisonInconsistent, selected.Retriever, reference.Retriever,
		)
	}
	for index := range reference.Samples {
		if !sameConceptRetrievalComparisonSample(reference.Samples[index], selected.Samples[index]) {
			return fmt.Errorf(
				"%w: %s sample population differs from %s at index %d",
				ErrConceptRetrievalComparisonInconsistent, selected.Retriever, reference.Retriever, index,
			)
		}
	}
	return nil
}

func sameConceptRetrievalComparisonSample(left, right ConceptRetrievalEvaluationSample) bool {
	return left.UnitID == right.UnitID &&
		left.EntryID == right.EntryID &&
		left.ExtractionID == right.ExtractionID &&
		left.HumanSameEventID == right.HumanSameEventID &&
		left.HumanSameReason == right.HumanSameReason &&
		reflect.DeepEqual(left.Query, right.Query) &&
		reflect.DeepEqual(left.TargetConcept, right.TargetConcept)
}
