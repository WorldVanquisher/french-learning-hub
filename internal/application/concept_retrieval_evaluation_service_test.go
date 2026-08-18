package application

import (
	"context"
	"errors"
	"math"
	"reflect"
	"testing"

	"french-learning-app/internal/domain"
)

type fakeRetrievalQualityReader struct {
	report ConceptAnnotationQualityReport
	err    error
	calls  int
}

func (f *fakeRetrievalQualityReader) BuildV1(context.Context) (ConceptAnnotationQualityReport, error) {
	f.calls++
	return f.report, f.err
}

type fakeRetrievalConceptCatalog struct {
	concepts []domain.KnowledgeConcept
	err      error
	calls    int
}

func (f *fakeRetrievalConceptCatalog) ListConcepts(context.Context, *domain.ConceptState) ([]domain.KnowledgeConcept, error) {
	f.calls++
	return f.concepts, f.err
}

type fakeConceptRetriever struct {
	candidates map[int64][]ConceptRetrievalCandidate
	err        error
	calls      int
	limits     []int
	documents  [][]ConceptRetrievalDocument
}

func (*fakeConceptRetriever) Name() string { return "fake_retriever_v1" }

func (f *fakeConceptRetriever) Retrieve(_ context.Context, query ConceptRetrievalQuery, concepts []ConceptRetrievalDocument, limit int) ([]ConceptRetrievalCandidate, error) {
	f.calls++
	f.limits = append(f.limits, limit)
	copyOfDocuments := append([]ConceptRetrievalDocument(nil), concepts...)
	f.documents = append(f.documents, copyOfDocuments)
	if f.err != nil {
		return nil, f.err
	}
	return f.candidates[query.UnitID], nil
}

func retrievalHumanSameRecord(entryID, extractionID, unitID int64, concept domain.KnowledgeConcept, eventID int64, reason string) ConceptAnnotationDatasetRecord {
	record := qualityWithSame(qualityTestRecord(entryID, extractionID, unitID, 1), concept, eventID, domain.SourceHuman)
	record.EffectiveAnnotation.CurrentSame.Decision.Evidence = `{"reason":"` + reason + `"}`
	return record
}

func buildRetrievalEvaluationForTest(t *testing.T, records []ConceptAnnotationDatasetRecord, concepts []domain.KnowledgeConcept, quality ConceptAnnotationQualityReport, retriever *fakeConceptRetriever) (ConceptRetrievalEvaluationReport, *fakeAnnotationDatasetV1Reader, *fakeRetrievalQualityReader, *fakeRetrievalConceptCatalog) {
	t.Helper()
	dataset := &fakeAnnotationDatasetV1Reader{records: records}
	qualityReader := &fakeRetrievalQualityReader{report: quality}
	catalog := &fakeRetrievalConceptCatalog{concepts: concepts}
	report, err := NewConceptRetrievalEvaluationService(dataset, qualityReader, catalog, retriever).BuildV1(context.Background())
	if err != nil {
		t.Fatalf("BuildV1: %v", err)
	}
	return report, dataset, qualityReader, catalog
}

func TestConceptRetrievalEvaluationService_EligibilityExclusionsCatalogAndAudit(t *testing.T) {
	supported1 := qualityTestConcept(1)
	supported2 := qualityTestConcept(2)
	orphaned := qualityTestConcept(3)
	orphaned.Support = domain.SupportOrphaned
	orphaned.State = domain.ConceptOrphaned
	retired := qualityTestConcept(4)
	retired.Lifecycle = domain.LifecycleRetired
	retired.State = domain.ConceptRetired
	missing := qualityTestConcept(99)

	recordHuman := retrievalHumanSameRecord(2, 20, 20, supported1, 120, "human_same")
	recordHuman.Unit.Statement = "ordinary SAME statement"
	example := "ordinary example"
	recordHuman.Unit.Example = &example
	recordCorrection := retrievalHumanSameRecord(1, 10, 11, supported2, 111, "human_same_correction")
	recordSeed := retrievalHumanSameRecord(3, 30, 30, supported1, 130, "seed_unit_same")
	recordMalformed := retrievalHumanSameRecord(4, 40, 40, supported1, 140, "human_same")
	recordMalformed.EffectiveAnnotation.CurrentSame.Decision.Evidence = "not-json"
	recordUnknown := retrievalHumanSameRecord(5, 50, 50, supported1, 150, "unknown")
	recordAutomatic := qualityWithSame(qualityTestRecord(6, 60, 60, 1), supported1, 160, domain.SourceResolverAutomatic)
	recordSuppressed := retrievalHumanSameRecord(7, 70, 70, supported1, 170, "human_same")
	recordSuppressed.Admission.Effective = domain.AdmissionSuppressed
	recordRetired := retrievalHumanSameRecord(8, 80, 80, retired, 180, "human_same")
	recordMissing := retrievalHumanSameRecord(9, 90, 90, missing, 190, "human_same")
	recordOrphaned := retrievalHumanSameRecord(1, 10, 10, orphaned, 110, "human_same")

	retriever := &fakeConceptRetriever{candidates: map[int64][]ConceptRetrievalCandidate{
		10: {
			{ConceptID: 1, Rank: 1, Score: 0.8, Evidence: "test competitor"},
			{ConceptID: 3, Rank: 2, Score: 0.7, Evidence: "test target"},
		},
		11: {{ConceptID: 2, Rank: 1, Score: 0.9, Evidence: "test target"}},
	}}
	report, dataset, quality, catalog := buildRetrievalEvaluationForTest(t, []ConceptAnnotationDatasetRecord{
		recordMissing, recordSuppressed, recordHuman, recordAutomatic, recordSeed,
		recordRetired, recordMalformed, recordOrphaned, recordUnknown, recordCorrection,
	}, []domain.KnowledgeConcept{retired, orphaned, supported2, supported1}, ConceptAnnotationQualityReport{Valid: true, WarningCount: 2}, retriever)

	if report.State != ConceptRetrievalEvaluationStateEvaluated || !report.DatasetValid || report.SchemaVersion != ConceptRetrievalEvaluationV1SchemaVersion || report.EvaluationPolicy != ConceptRetrievalEvaluationPolicyV1 || report.Retriever != "fake_retriever_v1" {
		t.Fatalf("report identity/state = %+v", report)
	}
	if report.CandidateUniverse.Concepts != 3 {
		t.Fatalf("candidate universe = %+v", report.CandidateUniverse)
	}
	wantInventory := ConceptRetrievalEvaluationSampleInventory{
		HumanSameRecords: 9, EligibleSamples: 3,
		Excluded: ConceptRetrievalEvaluationExclusions{
			UnclassifiedHumanSameProvenance: 2, SeedNewConcept: 1,
			NonActiveAdmission: 1, RetiredTargetConcept: 1,
			TargetMissingFromCurrentCatalog: 1,
		},
	}
	if !reflect.DeepEqual(report.EvaluationSamples, wantInventory) {
		t.Fatalf("sample inventory = %+v, want %+v", report.EvaluationSamples, wantInventory)
	}
	if dataset.calls != 1 || quality.calls != 1 || catalog.calls != 1 || retriever.calls != 3 {
		t.Fatalf("calls: dataset=%d quality=%d catalog=%d retriever=%d", dataset.calls, quality.calls, catalog.calls, retriever.calls)
	}
	for index, documents := range retriever.documents {
		if got := []int64{documents[0].ConceptID, documents[1].ConceptID, documents[2].ConceptID}; !reflect.DeepEqual(got, []int64{1, 2, 3}) {
			t.Fatalf("documents[%d] ids = %v", index, got)
		}
		if retriever.limits[index] != ConceptRetrievalEvaluationMaxK {
			t.Fatalf("limit[%d] = %d", index, retriever.limits[index])
		}
	}
	if got := []int64{report.Samples[0].UnitID, report.Samples[1].UnitID, report.Samples[2].UnitID}; !reflect.DeepEqual(got, []int64{10, 11, 20}) {
		t.Fatalf("sample order = %v", got)
	}
	firstAudit := report.Samples[0]
	if len(firstAudit.Retrieved) != 2 || firstAudit.Retrieved[0].ConceptID != 1 || firstAudit.Retrieved[1].ConceptID != 3 || firstAudit.TargetRank == nil || *firstAudit.TargetRank != 2 {
		t.Fatalf("ranked audit output = %+v", firstAudit)
	}
	audit := report.Samples[2]
	if audit.EntryID != 2 || audit.ExtractionID != 20 || audit.Query.UnitID != 20 || audit.Query.Statement != "ordinary SAME statement" || audit.Query.Example == nil || *audit.Query.Example != example {
		t.Fatalf("query provenance = %+v", audit)
	}
	if audit.HumanSameEventID != 120 || audit.HumanSameReason != "human_same" || audit.TargetConcept.ConceptID != supported1.ID || audit.TargetConcept.Target != supported1.Target || audit.Retrieved == nil || audit.TargetRank != nil || audit.ReciprocalRank != 0 {
		t.Fatalf("audit output = %+v", audit)
	}
	assertRetrievalMetrics(t, report.Metrics, 1.0/3, 2.0/3, 2.0/3, 0.5)
}

func TestConceptRetrievalEvaluationService_ExclusionPrecedenceCountsOnce(t *testing.T) {
	concept := qualityTestConcept(1)
	malformed := retrievalHumanSameRecord(1, 10, 1, concept, 11, "seed_unit_same")
	malformed.EffectiveAnnotation.CurrentSame.Decision.Evidence = "bad"
	malformed.Admission.Effective = domain.AdmissionSuppressed
	seed := retrievalHumanSameRecord(2, 20, 2, concept, 12, "seed_unit_same")
	seed.Admission.Effective = domain.AdmissionSuppressed
	report, _, _, _ := buildRetrievalEvaluationForTest(t, []ConceptAnnotationDatasetRecord{seed, malformed}, []domain.KnowledgeConcept{concept}, ConceptAnnotationQualityReport{Valid: true}, &fakeConceptRetriever{})
	excluded := report.EvaluationSamples.Excluded
	if report.EvaluationSamples.HumanSameRecords != 2 || report.EvaluationSamples.EligibleSamples != 0 || excluded.UnclassifiedHumanSameProvenance != 1 || excluded.SeedNewConcept != 1 || excluded.NonActiveAdmission != 0 {
		t.Fatalf("precedence inventory = %+v", report.EvaluationSamples)
	}
	if report.State != ConceptRetrievalEvaluationStateEvaluated || report.Metrics.RecallAt1 != nil || report.Metrics.RecallAt3 != nil || report.Metrics.RecallAt5 != nil || report.Metrics.MRR != nil {
		t.Fatalf("zero-sample evaluated metrics = %+v", report)
	}
}

func TestConceptRetrievalEvaluationService_QualityGateAndFailures(t *testing.T) {
	t.Run("invalid blocks before dataset catalog and retrieval", func(t *testing.T) {
		dataset := &fakeAnnotationDatasetV1Reader{}
		quality := &fakeRetrievalQualityReader{report: ConceptAnnotationQualityReport{Valid: false, ErrorCount: 1}}
		catalog := &fakeRetrievalConceptCatalog{}
		retriever := &fakeConceptRetriever{}
		report, err := NewConceptRetrievalEvaluationService(dataset, quality, catalog, retriever).BuildV1(context.Background())
		if err != nil {
			t.Fatalf("BuildV1: %v", err)
		}
		if report.State != ConceptRetrievalEvaluationStateBlockedInvalidDataset || report.DatasetValid || report.Metrics.RecallAt1 != nil || report.Metrics.RecallAt3 != nil || report.Metrics.RecallAt5 != nil || report.Metrics.MRR != nil || report.Samples == nil || len(report.Samples) != 0 {
			t.Fatalf("blocked report = %+v", report)
		}
		if dataset.calls != 0 || catalog.calls != 0 || retriever.calls != 0 || quality.calls != 1 {
			t.Fatalf("blocked calls: dataset=%d catalog=%d retriever=%d quality=%d", dataset.calls, catalog.calls, retriever.calls, quality.calls)
		}
	})

	t.Run("quality failure propagates", func(t *testing.T) {
		sentinel := errors.New("quality failed")
		_, err := NewConceptRetrievalEvaluationService(&fakeAnnotationDatasetV1Reader{}, &fakeRetrievalQualityReader{err: sentinel}, &fakeRetrievalConceptCatalog{}, &fakeConceptRetriever{}).BuildV1(context.Background())
		if !errors.Is(err, sentinel) {
			t.Fatalf("error = %v", err)
		}
	})
}

func TestConceptRetrievalEvaluationService_DatasetCatalogAndRetrieverFailuresPropagate(t *testing.T) {
	sentinel := errors.New("dependency failed")
	validQuality := &fakeRetrievalQualityReader{report: ConceptAnnotationQualityReport{Valid: true}}
	concept := qualityTestConcept(1)
	record := retrievalHumanSameRecord(1, 10, 1, concept, 11, "human_same")

	for _, tc := range []struct {
		name      string
		dataset   *fakeAnnotationDatasetV1Reader
		catalog   *fakeRetrievalConceptCatalog
		retriever *fakeConceptRetriever
	}{
		{name: "dataset", dataset: &fakeAnnotationDatasetV1Reader{err: sentinel}, catalog: &fakeRetrievalConceptCatalog{}, retriever: &fakeConceptRetriever{}},
		{name: "catalog", dataset: &fakeAnnotationDatasetV1Reader{records: []ConceptAnnotationDatasetRecord{record}}, catalog: &fakeRetrievalConceptCatalog{err: sentinel}, retriever: &fakeConceptRetriever{}},
		{name: "retriever", dataset: &fakeAnnotationDatasetV1Reader{records: []ConceptAnnotationDatasetRecord{record}}, catalog: &fakeRetrievalConceptCatalog{concepts: []domain.KnowledgeConcept{concept}}, retriever: &fakeConceptRetriever{err: sentinel}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, err := NewConceptRetrievalEvaluationService(tc.dataset, validQuality, tc.catalog, tc.retriever).BuildV1(context.Background())
			if !errors.Is(err, sentinel) {
				t.Fatalf("error = %v", err)
			}
		})
	}
}

func TestCalculateConceptRetrievalMetrics_RanksMissAggregateAndEmpty(t *testing.T) {
	for _, tc := range []struct {
		name          string
		rank          int
		want1, want3  float64
		want5, wantRR float64
	}{
		{name: "rank1", rank: 1, want1: 1, want3: 1, want5: 1, wantRR: 1},
		{name: "rank3", rank: 3, want1: 0, want3: 1, want5: 1, wantRR: 1.0 / 3},
		{name: "rank5", rank: 5, want1: 0, want3: 0, want5: 1, wantRR: 0.2},
	} {
		t.Run(tc.name, func(t *testing.T) {
			sample := retrievalMetricSample(tc.rank)
			metrics := calculateConceptRetrievalMetrics([]ConceptRetrievalEvaluationSample{sample})
			assertRetrievalMetrics(t, metrics, tc.want1, tc.want3, tc.want5, tc.wantRR)
		})
	}

	miss := ConceptRetrievalEvaluationSample{}
	assertRetrievalMetrics(t, calculateConceptRetrievalMetrics([]ConceptRetrievalEvaluationSample{miss}), 0, 0, 0, 0)
	aggregate := calculateConceptRetrievalMetrics([]ConceptRetrievalEvaluationSample{
		retrievalMetricSample(1), retrievalMetricSample(3), retrievalMetricSample(5), miss,
	})
	assertRetrievalMetrics(t, aggregate, 0.25, 0.5, 0.75, (1+1.0/3+0.2)/4)
	empty := calculateConceptRetrievalMetrics(nil)
	if empty.RecallAt1 != nil || empty.RecallAt3 != nil || empty.RecallAt5 != nil || empty.MRR != nil {
		t.Fatalf("empty metrics = %+v", empty)
	}
}

func retrievalMetricSample(rank int) ConceptRetrievalEvaluationSample {
	return ConceptRetrievalEvaluationSample{
		TargetRank: &rank, ReciprocalRank: 1 / float64(rank),
		HitAt1: rank <= 1, HitAt3: rank <= 3, HitAt5: rank <= 5,
	}
}

func assertRetrievalMetrics(t *testing.T, metrics ConceptRetrievalEvaluationMetrics, want1, want3, want5, wantMRR float64) {
	t.Helper()
	if metrics.RecallAt1 == nil || metrics.RecallAt3 == nil || metrics.RecallAt5 == nil || metrics.MRR == nil {
		t.Fatalf("metrics contain nil: %+v", metrics)
	}
	if math.Abs(*metrics.RecallAt1-want1) > 1e-12 || math.Abs(*metrics.RecallAt3-want3) > 1e-12 || math.Abs(*metrics.RecallAt5-want5) > 1e-12 || math.Abs(*metrics.MRR-wantMRR) > 1e-12 {
		t.Fatalf("metrics = %+v, want %v/%v/%v/%v", metrics, want1, want3, want5, wantMRR)
	}
}
