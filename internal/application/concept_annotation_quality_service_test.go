package application

import (
	"context"
	"errors"
	"reflect"
	"testing"
	"time"

	"french-learning-app/internal/domain"
)

type fakeAnnotationDatasetV1Reader struct {
	records []ConceptAnnotationDatasetRecord
	err     error
	calls   int
}

func (f *fakeAnnotationDatasetV1Reader) ListV1(context.Context) ([]ConceptAnnotationDatasetRecord, error) {
	f.calls++
	return f.records, f.err
}

func qualityTestConcept(id int64) domain.KnowledgeConcept {
	return domain.KnowledgeConcept{
		ID: id, IdentitySchemaVersion: "concept_identity_v1", Target: "target",
		PedagogicalIntent: "intent", Scope: "scope", IdentityFeatures: map[string]string{},
		Signature: "signature", Lifecycle: domain.LifecycleNormal, Support: domain.SupportSupported,
		State: domain.ConceptActive, CreatedAt: datasetTestTime(1), UpdatedAt: datasetTestTime(1),
	}
}

func qualityTestRecord(entryID, extractionID, unitID int64, ordinal int) ConceptAnnotationDatasetRecord {
	return ConceptAnnotationDatasetRecord{
		SchemaVersion: ConceptAnnotationDatasetV1SchemaVersion,
		Unit: domain.KnowledgeUnit{
			ID: unitID, ExtractionID: extractionID, Ordinal: ordinal,
			Kind: domain.KindGrammar, Canonical: "canonical", Statement: "statement",
		},
		Source: ConceptAnnotationDatasetSource{
			EntryID: entryID, ExtractionID: extractionID, ExtractionVersion: 1,
			SourceAnalysisID: entryID + 100, Extractor: "extractor:z", ExtractionCreatedAt: datasetTestTime(1),
		},
		Admission: domain.AdmissionState{Effective: domain.AdmissionActive},
		EffectiveAnnotation: ConceptAnnotationDatasetEffectiveAnnotation{
			UnitID: unitID, Status: domain.EffectiveAnnotationUnresolved,
			Distinctions: make([]ConceptAnnotationDatasetDistinction, 0),
			Relations:    make([]ConceptAnnotationDatasetRelation, 0),
		},
		HumanLabels: ConceptAnnotationHumanLabels{
			Distinctions: make([]HumanDistinctLabel, 0), Relations: make([]HumanRelationLabel, 0),
		},
	}
}

func qualityWithSame(record ConceptAnnotationDatasetRecord, concept domain.KnowledgeConcept, eventID int64, source domain.DecisionSource) ConceptAnnotationDatasetRecord {
	createdAt := datasetTestTime(int(eventID % 60))
	record.EffectiveAnnotation.Status = domain.EffectiveAnnotationResolved
	record.EffectiveAnnotation.CurrentSame = &ConceptAnnotationDatasetSame{
		Concept: concept,
		Membership: domain.CurrentConceptMembership{
			UnitID: record.Unit.ID, ConceptID: concept.ID, LinkID: eventID, UpdatedAt: createdAt,
		},
		Decision: domain.UnitConceptLink{
			ID: eventID, UnitID: record.Unit.ID, ConceptID: concept.ID,
			Relation: domain.RelationSame, Status: domain.LinkAccepted,
			DecisionSource: source, ResolverVersion: "resolver:v1", CreatedAt: createdAt,
		},
	}
	if source == domain.SourceHuman {
		record.HumanLabels.Same = &HumanSameLabel{
			ConceptID: concept.ID, EventID: eventID, ResolverVersion: "resolver:v1", CreatedAt: createdAt,
		}
	}
	return record
}

func qualityHumanDistinct(record ConceptAnnotationDatasetRecord, concept domain.KnowledgeConcept, eventID int64) ConceptAnnotationDatasetRecord {
	createdAt := datasetTestTime(int(eventID % 60))
	record.EffectiveAnnotation.Distinctions = append(record.EffectiveAnnotation.Distinctions, ConceptAnnotationDatasetDistinction{
		Concept: concept,
		Distinction: domain.UnitConceptDistinction{
			ID: eventID, UnitID: record.Unit.ID, ConceptID: concept.ID,
			DecisionSource: domain.SourceHuman, ResolverVersion: "resolver:v1", CreatedAt: createdAt,
		},
	})
	record.HumanLabels.Distinctions = append(record.HumanLabels.Distinctions, HumanDistinctLabel{
		ConceptID: concept.ID, DistinctionEventID: eventID, ResolverVersion: "resolver:v1", CreatedAt: createdAt,
	})
	return record
}

func qualityHumanRelation(record ConceptAnnotationDatasetRecord, concept domain.KnowledgeConcept, eventID int64, relation domain.ConceptRelation) ConceptAnnotationDatasetRecord {
	createdAt := datasetTestTime(int(eventID % 60))
	record.EffectiveAnnotation.Relations = append(record.EffectiveAnnotation.Relations, ConceptAnnotationDatasetRelation{
		Concept: concept,
		Decision: domain.UnitConceptLink{
			ID: eventID, UnitID: record.Unit.ID, ConceptID: concept.ID, Relation: relation,
			Status: domain.LinkAccepted, DecisionSource: domain.SourceHuman,
			ResolverVersion: "resolver:v2", CreatedAt: createdAt,
		},
	})
	record.HumanLabels.Relations = append(record.HumanLabels.Relations, HumanRelationLabel{
		ConceptID: concept.ID, Relation: relation, EventID: eventID,
		ResolverVersion: "resolver:v2", CreatedAt: createdAt,
	})
	return record
}

func qualityHumanInvalid(record ConceptAnnotationDatasetRecord, judgmentID int64) ConceptAnnotationDatasetRecord {
	createdAt := datasetTestTime(int(judgmentID % 60))
	judgment := &domain.UnitResolutionJudgment{
		ID: judgmentID, UnitID: record.Unit.ID, Judgment: domain.UnitInvalid,
		DecisionSource: domain.SourceHuman, Note: "invalid fragment", Evidence: `{"reason":"fragment"}`, CreatedAt: createdAt,
	}
	record.EffectiveAnnotation.Status = domain.EffectiveAnnotationInvalid
	record.EffectiveAnnotation.LatestUnitJudgment = judgment
	record.HumanLabels.Invalid = &HumanInvalidLabel{
		JudgmentID: judgmentID, CreatedAt: createdAt, Note: judgment.Note, Evidence: judgment.Evidence,
	}
	return record
}

func buildQualityReportForTest(t *testing.T, records ...ConceptAnnotationDatasetRecord) ConceptAnnotationQualityReport {
	t.Helper()
	reader := &fakeAnnotationDatasetV1Reader{records: records}
	report, err := NewConceptAnnotationDatasetQualityService(reader).BuildV1(context.Background())
	if err != nil {
		t.Fatalf("BuildV1: %v", err)
	}
	if reader.calls != 1 {
		t.Fatalf("dataset calls = %d, want 1", reader.calls)
	}
	return report
}

func qualityIssueCodes(report ConceptAnnotationQualityReport) []string {
	codes := make([]string, 0, len(report.Issues))
	for _, issue := range report.Issues {
		codes = append(codes, issue.Code)
	}
	return codes
}

func qualityHasIssue(report ConceptAnnotationQualityReport, code string) bool {
	for _, issue := range report.Issues {
		if issue.Code == code {
			return true
		}
	}
	return false
}

func TestConceptAnnotationDatasetQualityService_EmptyDataset(t *testing.T) {
	report := buildQualityReportForTest(t)
	if !report.Valid || report.ErrorCount != 0 || report.WarningCount != 0 || report.Summary.TotalRecords != 0 {
		t.Fatalf("empty report = %+v", report)
	}
	if report.SchemaVersion != ConceptAnnotationQualityReportV1SchemaVersion || report.DatasetSchemaVersion != ConceptAnnotationDatasetV1SchemaVersion {
		t.Fatalf("schema versions = %q, %q", report.SchemaVersion, report.DatasetSchemaVersion)
	}
	if report.Issues == nil || report.Provenance.Extractors == nil || report.Provenance.ConceptIdentitySchemaVersions == nil || report.Provenance.HumanLabelResolverVersions == nil {
		t.Fatal("empty report contains a nil collection")
	}
}

func TestConceptAnnotationDatasetQualityService_InventoryProvenanceAndLeakage(t *testing.T) {
	concept1 := qualityTestConcept(1)
	record1 := qualityWithSame(qualityTestRecord(1, 10, 1, 1), concept1, 11, domain.SourceHuman)
	record2 := qualityWithSame(qualityTestRecord(1, 10, 2, 2), qualityTestConcept(2), 12, domain.SourceResolverAutomatic)
	record2.Source.Extractor = "extractor:a"
	record3 := qualityWithSame(qualityTestRecord(2, 20, 3, 1), concept1, 13, domain.SourceHuman)
	record3.Unit.Kind = domain.KindVocabulary
	record3.Unit.Canonical = "different representation"
	record4 := qualityHumanDistinct(qualityTestRecord(2, 20, 4, 2), qualityTestConcept(3), 21)
	record4 = qualityHumanRelation(record4, qualityTestConcept(4), 31, domain.RelationBroader)
	record4 = qualityHumanRelation(record4, qualityTestConcept(5), 32, domain.RelationNarrower)
	record4 = qualityHumanRelation(record4, qualityTestConcept(6), 33, domain.RelationRelated)
	record5 := qualityHumanInvalid(qualityTestRecord(3, 30, 5, 1), 41)
	record6 := qualityTestRecord(4, 40, 6, 1)

	report := buildQualityReportForTest(t, record6, record4, record2, record5, record3, record1)
	if !report.Valid {
		t.Fatalf("valid dataset issues = %+v", report.Issues)
	}
	if got, want := report.Summary, (ConceptAnnotationQualitySummary{
		TotalRecords: 6, TotalEntries: 4, TotalExtractions: 4, TotalReferencedConcepts: 6,
		EffectiveStatus:    ConceptAnnotationQualityStatusSummary{Resolved: 3, Unresolved: 2, Invalid: 1},
		AdmissionEffective: ConceptAnnotationQualityAdmissionSummary{Active: 6},
		Authority:          ConceptAnnotationQualityAuthoritySummary{ResolvedHumanSame: 2, ResolvedAutomaticSame: 1},
	}); !reflect.DeepEqual(got, want) {
		t.Fatalf("summary = %+v, want %+v", got, want)
	}
	labels := report.LabelInventory
	if labels.RecordsWithAnyHumanLabel != 4 || labels.RecordsWithoutHumanLabel != 2 || labels.HumanSameRecords != 2 || labels.HumanDistinctPairs != 1 || labels.HumanRelations.Broader != 1 || labels.HumanRelations.Narrower != 1 || labels.HumanRelations.Related != 1 || labels.HumanInvalidRecords != 1 || labels.UnlabeledUnresolvedRecords != 1 || labels.AutomaticSameOnlyRecords != 1 {
		t.Fatalf("label inventory = %+v", labels)
	}
	wantLeakage := ConceptAnnotationQualityLeakageRisk{
		EntriesWithMultipleRecords: 2, MaxRecordsPerEntry: 2, HumanSameConcepts: 1,
		HumanSameConceptsWithMultipleUnits: 1, HumanSameConceptsSpanningMultipleEntries: 1, MaxUnitsPerHumanSameConcept: 2,
	}
	if !reflect.DeepEqual(report.LeakageRisk, wantLeakage) {
		t.Fatalf("leakage = %+v, want %+v", report.LeakageRisk, wantLeakage)
	}
	if got := report.Provenance.Extractors; !reflect.DeepEqual(got, []ConceptAnnotationQualityDistributionCount{{Value: "extractor:a", Count: 1}, {Value: "extractor:z", Count: 5}}) {
		t.Fatalf("extractors = %+v", got)
	}
	if got := report.Provenance.HumanLabelResolverVersions; !reflect.DeepEqual(got, []ConceptAnnotationQualityDistributionCount{{Value: "resolver:v1", Count: 3}, {Value: "resolver:v2", Count: 3}}) {
		t.Fatalf("resolver versions = %+v", got)
	}
}

func TestConceptAnnotationDatasetQualityService_WarningsRemainValid(t *testing.T) {
	for _, state := range []domain.MachineAdmissionState{domain.AdmissionSuppressed, domain.AdmissionNeedsReview} {
		t.Run(string(state), func(t *testing.T) {
			record := qualityWithSame(qualityTestRecord(1, 10, 1, 1), qualityTestConcept(1), 11, domain.SourceHuman)
			record.Admission.Effective = state
			report := buildQualityReportForTest(t, record)
			if !report.Valid || report.ErrorCount != 0 || report.WarningCount != 1 || !qualityHasIssue(report, "human_label_non_active_admission") {
				t.Fatalf("report = %+v", report)
			}
		})
	}

	record := qualityWithSame(qualityTestRecord(1, 10, 1, 1), qualityTestConcept(1), 11, domain.SourceHuman)
	record.EffectiveAnnotation.CurrentSame.Concept.Lifecycle = domain.LifecycleRetired
	record.EffectiveAnnotation.CurrentSame.Concept.State = domain.ConceptRetired
	report := buildQualityReportForTest(t, record)
	if !report.Valid || !qualityHasIssue(report, "human_same_retired_concept") {
		t.Fatalf("retired SAME report = %+v", report)
	}
}

func TestConceptAnnotationDatasetQualityService_StructuralErrors(t *testing.T) {
	tests := []struct {
		name    string
		code    string
		records func() []ConceptAnnotationDatasetRecord
	}{
		{"duplicate unit", "duplicate_unit_id", func() []ConceptAnnotationDatasetRecord {
			return []ConceptAnnotationDatasetRecord{qualityTestRecord(1, 10, 1, 1), qualityTestRecord(1, 10, 1, 2)}
		}},
		{"multiple extraction snapshots", "multiple_current_extractions", func() []ConceptAnnotationDatasetRecord {
			return []ConceptAnnotationDatasetRecord{qualityTestRecord(1, 10, 1, 1), qualityTestRecord(1, 11, 2, 1)}
		}},
		{"duplicate ordinal", "duplicate_extraction_ordinal", func() []ConceptAnnotationDatasetRecord {
			return []ConceptAnnotationDatasetRecord{qualityTestRecord(1, 10, 1, 1), qualityTestRecord(1, 10, 2, 1)}
		}},
		{"resolved without same", "resolved_without_current_same", func() []ConceptAnnotationDatasetRecord {
			r := qualityTestRecord(1, 10, 1, 1)
			r.EffectiveAnnotation.Status = domain.EffectiveAnnotationResolved
			return []ConceptAnnotationDatasetRecord{r}
		}},
		{"unresolved with same", "non_resolved_with_current_same", func() []ConceptAnnotationDatasetRecord {
			r := qualityWithSame(qualityTestRecord(1, 10, 1, 1), qualityTestConcept(1), 11, domain.SourceHuman)
			r.EffectiveAnnotation.Status = domain.EffectiveAnnotationUnresolved
			return []ConceptAnnotationDatasetRecord{r}
		}},
		{"invalid pair output", "invalid_pair_output", func() []ConceptAnnotationDatasetRecord {
			r := qualityHumanInvalid(qualityTestRecord(1, 10, 1, 1), 41)
			r = qualityHumanDistinct(r, qualityTestConcept(2), 21)
			return []ConceptAnnotationDatasetRecord{r}
		}},
		{"human same mismatch", "human_same_projection_mismatch", func() []ConceptAnnotationDatasetRecord {
			r := qualityWithSame(qualityTestRecord(1, 10, 1, 1), qualityTestConcept(1), 11, domain.SourceHuman)
			r.HumanLabels.Same.EventID = 99
			return []ConceptAnnotationDatasetRecord{r}
		}},
		{"automatic same human label", "automatic_same_has_human_label", func() []ConceptAnnotationDatasetRecord {
			r := qualityWithSame(qualityTestRecord(1, 10, 1, 1), qualityTestConcept(1), 11, domain.SourceResolverAutomatic)
			r.HumanLabels.Same = &HumanSameLabel{ConceptID: 1, EventID: 11, ResolverVersion: "resolver:v1"}
			return []ConceptAnnotationDatasetRecord{r}
		}},
		{"missing human distinct", "missing_human_distinct_projection", func() []ConceptAnnotationDatasetRecord {
			r := qualityHumanDistinct(qualityTestRecord(1, 10, 1, 1), qualityTestConcept(2), 21)
			r.HumanLabels.Distinctions = nil
			return []ConceptAnnotationDatasetRecord{r}
		}},
		{"mismatched relation", "human_relation_projection_mismatch", func() []ConceptAnnotationDatasetRecord {
			r := qualityHumanRelation(qualityTestRecord(1, 10, 1, 1), qualityTestConcept(2), 31, domain.RelationBroader)
			r.HumanLabels.Relations[0].ResolverVersion = "wrong"
			return []ConceptAnnotationDatasetRecord{r}
		}},
		{"invalid label on unresolved", "human_invalid_on_non_invalid", func() []ConceptAnnotationDatasetRecord {
			r := qualityTestRecord(1, 10, 1, 1)
			r.HumanLabels.Invalid = &HumanInvalidLabel{JudgmentID: 1, CreatedAt: time.Unix(1, 0)}
			return []ConceptAnnotationDatasetRecord{r}
		}},
		{"same distinct contradiction", "human_same_distinct_contradiction", func() []ConceptAnnotationDatasetRecord {
			r := qualityWithSame(qualityTestRecord(1, 10, 1, 1), qualityTestConcept(1), 11, domain.SourceHuman)
			r = qualityHumanDistinct(r, qualityTestConcept(1), 21)
			return []ConceptAnnotationDatasetRecord{r}
		}},
		{"same relation contradiction", "same_relation_contradiction", func() []ConceptAnnotationDatasetRecord {
			r := qualityWithSame(qualityTestRecord(1, 10, 1, 1), qualityTestConcept(1), 11, domain.SourceHuman)
			r = qualityHumanRelation(r, qualityTestConcept(1), 31, domain.RelationRelated)
			return []ConceptAnnotationDatasetRecord{r}
		}},
		{"invalid concept", "invalid_concept_snapshot", func() []ConceptAnnotationDatasetRecord {
			concept := qualityTestConcept(1)
			concept.Signature = ""
			return []ConceptAnnotationDatasetRecord{qualityWithSame(qualityTestRecord(1, 10, 1, 1), concept, 11, domain.SourceHuman)}
		}},
		{"unsupported active same", "active_same_unsupported_concept", func() []ConceptAnnotationDatasetRecord {
			concept := qualityTestConcept(1)
			concept.Support = domain.SupportOrphaned
			concept.State = domain.ConceptOrphaned
			return []ConceptAnnotationDatasetRecord{qualityWithSame(qualityTestRecord(1, 10, 1, 1), concept, 11, domain.SourceHuman)}
		}},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			report := buildQualityReportForTest(t, tc.records()...)
			if report.Valid || report.ErrorCount == 0 || !qualityHasIssue(report, tc.code) {
				t.Fatalf("wanted error %q; report issues = %+v", tc.code, report.Issues)
			}
		})
	}
}

func TestConceptAnnotationDatasetQualityService_DeterministicIssueOrdering(t *testing.T) {
	record1 := qualityTestRecord(2, 20, 2, 0)
	record1.Admission.Effective = domain.AdmissionSuppressed
	record1.HumanLabels.Invalid = &HumanInvalidLabel{JudgmentID: 1}
	record2 := qualityTestRecord(1, 10, 1, 0)
	report := buildQualityReportForTest(t, record1, record2)
	want := []string{"human_invalid_on_non_invalid", "invalid_unit_ordinal", "invalid_unit_ordinal", "human_label_non_active_admission"}
	if got := qualityIssueCodes(report); !reflect.DeepEqual(got, want) {
		t.Fatalf("issue codes = %v, want %v", got, want)
	}
}

func TestConceptAnnotationDatasetQualityService_PropagatesDatasetFailure(t *testing.T) {
	sentinel := errors.New("private storage detail")
	reader := &fakeAnnotationDatasetV1Reader{err: sentinel}
	_, err := NewConceptAnnotationDatasetQualityService(reader).BuildV1(context.Background())
	if !errors.Is(err, sentinel) || reader.calls != 1 {
		t.Fatalf("BuildV1 error = %v, calls = %d", err, reader.calls)
	}
}
