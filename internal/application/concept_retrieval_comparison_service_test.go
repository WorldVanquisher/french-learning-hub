package application

import (
	"context"
	"errors"
	"reflect"
	"testing"
)

type fakeConceptRetrievalEvaluationBuilder struct {
	reports map[string]ConceptRetrievalEvaluationReport
	errs    map[string]error
	calls   []string
}

func (f *fakeConceptRetrievalEvaluationBuilder) BuildV1WithRetriever(_ context.Context, name string) (ConceptRetrievalEvaluationReport, error) {
	f.calls = append(f.calls, name)
	if err := f.errs[name]; err != nil {
		return ConceptRetrievalEvaluationReport{}, err
	}
	return f.reports[name], nil
}

func comparisonMetric(value float64) *float64 { return &value }

func comparisonEvaluationReport(name string, metric float64) ConceptRetrievalEvaluationReport {
	return ConceptRetrievalEvaluationReport{
		SchemaVersion:    ConceptRetrievalEvaluationV1SchemaVersion,
		EvaluationPolicy: ConceptRetrievalEvaluationPolicyV1,
		Retriever:        name,
		State:            ConceptRetrievalEvaluationStateEvaluated,
		DatasetValid:     true,
		CandidateUniverse: ConceptRetrievalCandidateUniverse{
			Concepts: 7,
		},
		EvaluationSamples: ConceptRetrievalEvaluationSampleInventory{
			HumanSameRecords: 4,
			EligibleSamples:  2,
			Excluded: ConceptRetrievalEvaluationExclusions{
				SeedNewConcept: 2,
			},
		},
		Metrics: ConceptRetrievalEvaluationMetrics{
			RecallAt1: comparisonMetric(metric),
			RecallAt3: comparisonMetric(metric + 0.1),
			RecallAt5: comparisonMetric(metric + 0.2),
			MRR:       comparisonMetric(metric + 0.05),
		},
		Samples: []ConceptRetrievalEvaluationSample{
			{
				UnitID: 10, EntryID: 1, ExtractionID: 100,
				Query:            ConceptRetrievalQuery{UnitID: 10, Canonical: "partir demain"},
				TargetConcept:    ConceptRetrievalDocument{ConceptID: 20, Target: "futur proche"},
				HumanSameEventID: 30, HumanSameReason: "human_same",
			},
			{
				UnitID: 11, EntryID: 2, ExtractionID: 101,
				Query:            ConceptRetrievalQuery{UnitID: 11, Canonical: "article partitif"},
				TargetConcept:    ConceptRetrievalDocument{ConceptID: 21, Target: "article partitif"},
				HumanSameEventID: 31, HumanSameReason: "human_same_correction",
			},
		},
	}
}

func configuredComparisonEvaluationBuilder() *fakeConceptRetrievalEvaluationBuilder {
	return &fakeConceptRetrievalEvaluationBuilder{reports: map[string]ConceptRetrievalEvaluationReport{
		ExactSignatureRetrieverV1Name:  comparisonEvaluationReport(ExactSignatureRetrieverV1Name, 0.1),
		WeightedLexicalRetrieverV1Name: comparisonEvaluationReport(WeightedLexicalRetrieverV1Name, 0.2),
		BM25RetrieverV1Name:            comparisonEvaluationReport(BM25RetrieverV1Name, 0.3),
		EmbeddingRetrieverV1Name:       comparisonEvaluationReport(EmbeddingRetrieverV1Name, 0.4),
	}}
}

func TestConceptRetrievalComparisonService_ConfiguredBaselinesCopyMetricsInStableOrder(t *testing.T) {
	evaluation := configuredComparisonEvaluationBuilder()
	report, err := NewConceptRetrievalComparisonService(evaluation).BuildV1(context.Background())
	if err != nil {
		t.Fatalf("BuildV1: %v", err)
	}
	if report.SchemaVersion != ConceptRetrievalComparisonV1SchemaVersion || report.State != ConceptRetrievalEvaluationStateEvaluated || !report.DatasetValid || report.CandidateUniverse.Concepts != 7 || report.EvaluationSamples.EligibleSamples != 2 {
		t.Fatalf("comparison identity/population = %+v", report)
	}
	wantOrder := []string{ExactSignatureRetrieverV1Name, WeightedLexicalRetrieverV1Name, BM25RetrieverV1Name, EmbeddingRetrieverV1Name}
	if !reflect.DeepEqual(evaluation.calls, wantOrder) {
		t.Fatalf("evaluation calls = %v, want %v", evaluation.calls, wantOrder)
	}
	if len(report.Retrievers) != len(wantOrder) {
		t.Fatalf("retriever rows = %+v", report.Retrievers)
	}
	for index, name := range wantOrder {
		row := report.Retrievers[index]
		source := evaluation.reports[name]
		if row.Retriever != name || row.State != ConceptRetrievalEvaluationStateEvaluated {
			t.Fatalf("row[%d] = %+v", index, row)
		}
		if row.Metrics.RecallAt1 != source.Metrics.RecallAt1 || row.Metrics.RecallAt3 != source.Metrics.RecallAt3 || row.Metrics.RecallAt5 != source.Metrics.RecallAt5 || row.Metrics.MRR != source.Metrics.MRR {
			t.Fatalf("row[%d] metrics were not copied directly: row=%+v source=%+v", index, row.Metrics, source.Metrics)
		}
	}
}

func TestConceptRetrievalComparisonService_UnregisteredEmbeddingIsExplicitlyUnavailable(t *testing.T) {
	evaluation := configuredComparisonEvaluationBuilder()
	delete(evaluation.reports, EmbeddingRetrieverV1Name)
	evaluation.errs = map[string]error{EmbeddingRetrieverV1Name: ErrUnknownConceptRetriever}

	report, err := NewConceptRetrievalComparisonService(evaluation).BuildV1(context.Background())
	if err != nil {
		t.Fatalf("BuildV1: %v", err)
	}
	if len(report.Retrievers) != 4 {
		t.Fatalf("rows = %+v", report.Retrievers)
	}
	embedding := report.Retrievers[3]
	if embedding.Retriever != EmbeddingRetrieverV1Name || embedding.State != ConceptRetrievalComparisonRetrieverStateUnavailable || embedding.Metrics.RecallAt1 != nil || embedding.Metrics.RecallAt3 != nil || embedding.Metrics.RecallAt5 != nil || embedding.Metrics.MRR != nil {
		t.Fatalf("embedding row = %+v", embedding)
	}
}

func TestConceptRetrievalComparisonService_InvalidDatasetUsesExistingBlockedReportsWithoutRetrieval(t *testing.T) {
	dataset := &fakeAnnotationDatasetV1Reader{}
	quality := &fakeRetrievalQualityReader{report: ConceptAnnotationQualityReport{Valid: false, ErrorCount: 1}}
	catalog := &fakeRetrievalConceptCatalog{}
	embeddingProvider := &frozenEmbeddingProvider{name: "frozen:comparison-blocked", output: [][]float64{{1}}}
	evaluation := NewConceptRetrievalEvaluationServiceWithRegistry(
		dataset, quality, catalog,
		NewConceptRetrieverRegistry(
			NewExactSignatureConceptRetriever(),
			NewWeightedLexicalConceptRetriever(),
			NewBM25ConceptRetriever(),
			NewEmbeddingConceptRetriever(embeddingProvider),
		),
	)

	report, err := NewConceptRetrievalComparisonService(evaluation).BuildV1(context.Background())
	if err != nil {
		t.Fatalf("BuildV1: %v", err)
	}
	if report.State != ConceptRetrievalEvaluationStateBlockedInvalidDataset || report.DatasetValid || report.EvaluationSamples.EligibleSamples != 0 || len(report.Retrievers) != 4 {
		t.Fatalf("blocked comparison = %+v", report)
	}
	for _, row := range report.Retrievers {
		if row.State != ConceptRetrievalEvaluationStateBlockedInvalidDataset || row.Metrics.RecallAt1 != nil || row.Metrics.RecallAt3 != nil || row.Metrics.RecallAt5 != nil || row.Metrics.MRR != nil {
			t.Fatalf("blocked row = %+v", row)
		}
	}
	if quality.calls != 4 || dataset.calls != 0 || catalog.calls != 0 || embeddingProvider.calls != 0 {
		t.Fatalf("blocked dependency calls: quality=%d dataset=%d catalog=%d embedding=%d", quality.calls, dataset.calls, catalog.calls, embeddingProvider.calls)
	}
}

func TestConceptRetrievalComparisonService_DetectsInconsistentExperimentPopulation(t *testing.T) {
	for _, tc := range []struct {
		name   string
		change func(*ConceptRetrievalEvaluationReport)
	}{
		{name: "candidate universe", change: func(report *ConceptRetrievalEvaluationReport) { report.CandidateUniverse.Concepts++ }},
		{name: "eligible sample count", change: func(report *ConceptRetrievalEvaluationReport) { report.EvaluationSamples.EligibleSamples++ }},
		{name: "exclusion inventory", change: func(report *ConceptRetrievalEvaluationReport) { report.EvaluationSamples.Excluded.SeedNewConcept++ }},
		{name: "dataset validity", change: func(report *ConceptRetrievalEvaluationReport) { report.DatasetValid = false }},
		{name: "sample identity", change: func(report *ConceptRetrievalEvaluationReport) { report.Samples[0].UnitID++ }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			evaluation := configuredComparisonEvaluationBuilder()
			changed := evaluation.reports[WeightedLexicalRetrieverV1Name]
			tc.change(&changed)
			evaluation.reports[WeightedLexicalRetrieverV1Name] = changed
			_, err := NewConceptRetrievalComparisonService(evaluation).BuildV1(context.Background())
			if !errors.Is(err, ErrConceptRetrievalComparisonInconsistent) {
				t.Fatalf("error = %v", err)
			}
			if !reflect.DeepEqual(evaluation.calls, []string{ExactSignatureRetrieverV1Name, WeightedLexicalRetrieverV1Name}) {
				t.Fatalf("calls after mismatch = %v", evaluation.calls)
			}
		})
	}
}

func TestConceptRetrievalComparisonService_EmbeddingProviderFailuresPropagateWithoutFallback(t *testing.T) {
	for _, providerErr := range []error{ErrEmbeddingProviderTimeout, ErrEmbeddingProviderUnavailable} {
		evaluation := configuredComparisonEvaluationBuilder()
		evaluation.errs = map[string]error{EmbeddingRetrieverV1Name: providerErr}
		_, err := NewConceptRetrievalComparisonService(evaluation).BuildV1(context.Background())
		if !errors.Is(err, providerErr) {
			t.Fatalf("provider error %v propagated as %v", providerErr, err)
		}
		if !reflect.DeepEqual(evaluation.calls, conceptRetrievalComparisonRetrieversV1) {
			t.Fatalf("calls = %v", evaluation.calls)
		}
	}
}

func TestConceptRetrievalComparisonService_RequiredBaselineFailureIsNotUnavailable(t *testing.T) {
	evaluation := configuredComparisonEvaluationBuilder()
	evaluation.errs = map[string]error{BM25RetrieverV1Name: ErrUnknownConceptRetriever}
	_, err := NewConceptRetrievalComparisonService(evaluation).BuildV1(context.Background())
	if !errors.Is(err, ErrUnknownConceptRetriever) {
		t.Fatalf("error = %v", err)
	}
}
