package application

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"french-learning-app/internal/domain"
)

// ConceptAnnotationQualityReportV1SchemaVersion is the stable schema identifier
// for the first validation and quality report over Dataset v1.
const ConceptAnnotationQualityReportV1SchemaVersion = "concept_annotation_quality_report_v1"

// AnnotationDatasetV1Reader is the sole data boundary for the quality report.
// Implementations provide the already-composed M11-C current snapshot.
type AnnotationDatasetV1Reader interface {
	ListV1(ctx context.Context) ([]ConceptAnnotationDatasetRecord, error)
}

// ConceptAnnotationQualityIssue is one deterministic structural error or
// conservative quality warning. ConceptID is nil for record-wide findings.
type ConceptAnnotationQualityIssue struct {
	Severity  string
	Code      string
	EntryID   int64
	UnitID    int64
	ConceptID *int64
	Message   string
}

// ConceptAnnotationQualityDistributionCount is one sorted provenance bucket.
type ConceptAnnotationQualityDistributionCount struct {
	Value string
	Count int
}

type ConceptAnnotationQualityStatusSummary struct {
	Resolved   int
	Unresolved int
	Invalid    int
}

type ConceptAnnotationQualityAdmissionSummary struct {
	Active      int
	Suppressed  int
	NeedsReview int
}

type ConceptAnnotationQualityAuthoritySummary struct {
	ResolvedHumanSame     int
	ResolvedAutomaticSame int
}

type ConceptAnnotationQualitySummary struct {
	TotalRecords            int
	TotalEntries            int
	TotalExtractions        int
	TotalReferencedConcepts int
	EffectiveStatus         ConceptAnnotationQualityStatusSummary
	AdmissionEffective      ConceptAnnotationQualityAdmissionSummary
	Authority               ConceptAnnotationQualityAuthoritySummary
}

type ConceptAnnotationQualityHumanRelations struct {
	Broader  int
	Narrower int
	Related  int
}

type ConceptAnnotationQualityLabelInventory struct {
	RecordsWithAnyHumanLabel   int
	RecordsWithoutHumanLabel   int
	HumanSameRecords           int
	HumanDistinctPairs         int
	HumanRelations             ConceptAnnotationQualityHumanRelations
	HumanInvalidRecords        int
	UnlabeledUnresolvedRecords int
	AutomaticSameOnlyRecords   int
}

type ConceptAnnotationQualityProvenance struct {
	Extractors                    []ConceptAnnotationQualityDistributionCount
	ConceptIdentitySchemaVersions []ConceptAnnotationQualityDistributionCount
	HumanLabelResolverVersions    []ConceptAnnotationQualityDistributionCount
}

type ConceptAnnotationQualityLeakageRisk struct {
	EntriesWithMultipleRecords               int
	MaxRecordsPerEntry                       int
	HumanSameConcepts                        int
	HumanSameConceptsWithMultipleUnits       int
	HumanSameConceptsSpanningMultipleEntries int
	MaxUnitsPerHumanSameConcept              int
}

// ConceptAnnotationQualityReport is a deterministic, descriptive view over one
// M11-C dataset build. Valid means only that no structural error was found;
// warnings never make the report invalid.
type ConceptAnnotationQualityReport struct {
	SchemaVersion        string
	DatasetSchemaVersion string
	Valid                bool
	ErrorCount           int
	WarningCount         int
	Summary              ConceptAnnotationQualitySummary
	LabelInventory       ConceptAnnotationQualityLabelInventory
	Provenance           ConceptAnnotationQualityProvenance
	LeakageRisk          ConceptAnnotationQualityLeakageRisk
	Issues               []ConceptAnnotationQualityIssue
}

// ConceptAnnotationDatasetQualityService validates and describes Dataset v1.
// It never reads storage or annotation history and creates no annotation
// authority.
type ConceptAnnotationDatasetQualityService struct {
	dataset AnnotationDatasetV1Reader
}

func NewConceptAnnotationDatasetQualityService(dataset AnnotationDatasetV1Reader) *ConceptAnnotationDatasetQualityService {
	return &ConceptAnnotationDatasetQualityService{dataset: dataset}
}

// BuildV1 obtains Dataset v1 once, validates its application representation,
// and returns deterministic counts and findings.
func (s *ConceptAnnotationDatasetQualityService) BuildV1(ctx context.Context) (ConceptAnnotationQualityReport, error) {
	records, err := s.dataset.ListV1(ctx)
	if err != nil {
		return ConceptAnnotationQualityReport{}, fmt.Errorf("list concept annotation dataset v1: %w", err)
	}
	return buildConceptAnnotationQualityReportV1(records), nil
}

type qualityExtractionSnapshot struct {
	id      int64
	version int64
}

type qualityHumanSameGroup struct {
	units   map[int64]struct{}
	entries map[int64]struct{}
}

type qualityDistinctKey struct {
	conceptID       int64
	eventID         int64
	resolverVersion string
}

type qualityRelationKey struct {
	conceptID       int64
	eventID         int64
	relation        domain.ConceptRelation
	resolverVersion string
}

func buildConceptAnnotationQualityReportV1(records []ConceptAnnotationDatasetRecord) ConceptAnnotationQualityReport {
	report := ConceptAnnotationQualityReport{
		SchemaVersion:        ConceptAnnotationQualityReportV1SchemaVersion,
		DatasetSchemaVersion: ConceptAnnotationDatasetV1SchemaVersion,
		Provenance: ConceptAnnotationQualityProvenance{
			Extractors:                    make([]ConceptAnnotationQualityDistributionCount, 0),
			ConceptIdentitySchemaVersions: make([]ConceptAnnotationQualityDistributionCount, 0),
			HumanLabelResolverVersions:    make([]ConceptAnnotationQualityDistributionCount, 0),
		},
		Issues: make([]ConceptAnnotationQualityIssue, 0),
	}
	report.Summary.TotalRecords = len(records)

	entries := make(map[int64]struct{})
	extractions := make(map[int64]struct{})
	referencedConcepts := make(map[int64]domain.KnowledgeConcept)
	entryRecordCounts := make(map[int64]int)
	entryExtractions := make(map[int64]qualityExtractionSnapshot)
	unitIDs := make(map[int64]struct{})
	ordinals := make(map[[2]int64]struct{})
	extractorCounts := make(map[string]int)
	resolverCounts := make(map[string]int)
	humanSameGroups := make(map[int64]*qualityHumanSameGroup)

	for _, record := range records {
		entryID, unitID := record.Source.EntryID, record.Unit.ID
		entries[entryID] = struct{}{}
		extractions[record.Source.ExtractionID] = struct{}{}
		entryRecordCounts[entryID]++
		extractorCounts[record.Source.Extractor]++

		if record.SchemaVersion != ConceptAnnotationDatasetV1SchemaVersion {
			addQualityIssue(&report, "error", "record_schema_mismatch", entryID, unitID, nil, "record schema_version is not concept_annotation_dataset_v1")
		}
		validateQualityRecordIdentifiers(&report, record)

		if _, exists := unitIDs[unitID]; exists {
			addQualityIssue(&report, "error", "duplicate_unit_id", entryID, unitID, nil, "unit appears more than once in the current dataset")
		} else {
			unitIDs[unitID] = struct{}{}
		}

		snapshot := qualityExtractionSnapshot{id: record.Source.ExtractionID, version: record.Source.ExtractionVersion}
		if prior, exists := entryExtractions[entryID]; exists && prior != snapshot {
			addQualityIssue(&report, "error", "multiple_current_extractions", entryID, unitID, nil, "entry records refer to more than one extraction snapshot")
		} else if !exists {
			entryExtractions[entryID] = snapshot
		}

		ordinalKey := [2]int64{record.Source.ExtractionID, int64(record.Unit.Ordinal)}
		if record.Unit.Ordinal <= 0 {
			addQualityIssue(&report, "error", "invalid_unit_ordinal", entryID, unitID, nil, "unit ordinal must be positive")
		} else if _, exists := ordinals[ordinalKey]; exists {
			addQualityIssue(&report, "error", "duplicate_extraction_ordinal", entryID, unitID, nil, "unit ordinal appears more than once in the extraction")
		} else {
			ordinals[ordinalKey] = struct{}{}
		}

		countQualityStatusAndAdmission(&report, record)
		hasHumanLabel := qualityRecordHasHumanLabel(record)
		countQualityHumanLabels(&report, record, hasHumanLabel, resolverCounts, humanSameGroups)
		validateQualityEffectiveAnnotation(&report, record)
		validateQualityHumanProjections(&report, record)
		validateQualityContradictions(&report, record)

		concepts := qualityRecordConcepts(record)
		for _, concept := range concepts {
			if _, exists := referencedConcepts[concept.ID]; !exists {
				referencedConcepts[concept.ID] = concept
			}
			validateQualityConceptSnapshot(&report, entryID, unitID, concept)
		}

		if hasHumanLabel && record.Admission.Effective != domain.AdmissionActive {
			addQualityIssue(&report, "warning", "human_label_non_active_admission", entryID, unitID, nil, "record has an explicit human label but effective admission is not active")
		}
		if same := record.EffectiveAnnotation.CurrentSame; same != nil && same.Decision.DecisionSource == domain.SourceHuman && same.Concept.Lifecycle == domain.LifecycleRetired {
			addQualityIssue(&report, "warning", "human_same_retired_concept", entryID, unitID, qualityConceptID(same.Concept.ID), "current human SAME points to a retired concept")
		}
	}

	report.Summary.TotalEntries = len(entries)
	report.Summary.TotalExtractions = len(extractions)
	report.Summary.TotalReferencedConcepts = len(referencedConcepts)
	for _, count := range entryRecordCounts {
		if count > 1 {
			report.LeakageRisk.EntriesWithMultipleRecords++
		}
		if count > report.LeakageRisk.MaxRecordsPerEntry {
			report.LeakageRisk.MaxRecordsPerEntry = count
		}
	}
	report.LeakageRisk.HumanSameConcepts = len(humanSameGroups)
	for _, group := range humanSameGroups {
		unitCount := len(group.units)
		if unitCount > 1 {
			report.LeakageRisk.HumanSameConceptsWithMultipleUnits++
		}
		if len(group.entries) > 1 {
			report.LeakageRisk.HumanSameConceptsSpanningMultipleEntries++
		}
		if unitCount > report.LeakageRisk.MaxUnitsPerHumanSameConcept {
			report.LeakageRisk.MaxUnitsPerHumanSameConcept = unitCount
		}
	}

	identitySchemaCounts := make(map[string]int)
	for _, concept := range referencedConcepts {
		identitySchemaCounts[concept.IdentitySchemaVersion]++
	}
	report.Provenance.Extractors = sortedQualityDistribution(extractorCounts)
	report.Provenance.ConceptIdentitySchemaVersions = sortedQualityDistribution(identitySchemaCounts)
	report.Provenance.HumanLabelResolverVersions = sortedQualityDistribution(resolverCounts)

	sort.SliceStable(report.Issues, func(i, j int) bool {
		left, right := report.Issues[i], report.Issues[j]
		if qualitySeverityRank(left.Severity) != qualitySeverityRank(right.Severity) {
			return qualitySeverityRank(left.Severity) < qualitySeverityRank(right.Severity)
		}
		if left.Code != right.Code {
			return left.Code < right.Code
		}
		if left.EntryID != right.EntryID {
			return left.EntryID < right.EntryID
		}
		if left.UnitID != right.UnitID {
			return left.UnitID < right.UnitID
		}
		return qualityIssueConceptID(left.ConceptID) < qualityIssueConceptID(right.ConceptID)
	})
	for _, issue := range report.Issues {
		if issue.Severity == "error" {
			report.ErrorCount++
		} else if issue.Severity == "warning" {
			report.WarningCount++
		}
	}
	report.Valid = report.ErrorCount == 0
	return report
}

func validateQualityRecordIdentifiers(report *ConceptAnnotationQualityReport, record ConceptAnnotationDatasetRecord) {
	entryID, unitID := record.Source.EntryID, record.Unit.ID
	checks := []struct {
		invalid bool
		code    string
		message string
	}{
		{unitID <= 0, "invalid_unit_id", "unit id must be positive"},
		{entryID <= 0, "invalid_entry_id", "source entry_id must be positive"},
		{record.Source.ExtractionID <= 0, "invalid_extraction_id", "source extraction_id must be positive"},
		{record.Source.ExtractionVersion <= 0, "invalid_extraction_version", "source extraction_version must be positive"},
		{record.Source.SourceAnalysisID <= 0, "invalid_source_analysis_id", "source analysis_id must be positive"},
	}
	for _, check := range checks {
		if check.invalid {
			addQualityIssue(report, "error", check.code, entryID, unitID, nil, check.message)
		}
	}
	if record.Unit.ExtractionID != record.Source.ExtractionID {
		addQualityIssue(report, "error", "unit_source_extraction_mismatch", entryID, unitID, nil, "unit extraction_id does not match source extraction_id")
	}
	if record.EffectiveAnnotation.UnitID != unitID {
		addQualityIssue(report, "error", "effective_unit_mismatch", entryID, unitID, nil, "effective annotation unit_id does not match unit id")
	}
}

func countQualityStatusAndAdmission(report *ConceptAnnotationQualityReport, record ConceptAnnotationDatasetRecord) {
	switch record.EffectiveAnnotation.Status {
	case domain.EffectiveAnnotationResolved:
		report.Summary.EffectiveStatus.Resolved++
	case domain.EffectiveAnnotationUnresolved:
		report.Summary.EffectiveStatus.Unresolved++
	case domain.EffectiveAnnotationInvalid:
		report.Summary.EffectiveStatus.Invalid++
	default:
		addQualityIssue(report, "error", "invalid_effective_status", record.Source.EntryID, record.Unit.ID, nil, "effective annotation status is not recognized")
	}
	switch record.Admission.Effective {
	case domain.AdmissionActive:
		report.Summary.AdmissionEffective.Active++
	case domain.AdmissionSuppressed:
		report.Summary.AdmissionEffective.Suppressed++
	case domain.AdmissionNeedsReview:
		report.Summary.AdmissionEffective.NeedsReview++
	default:
		addQualityIssue(report, "error", "invalid_admission_state", record.Source.EntryID, record.Unit.ID, nil, "effective admission state is not recognized")
	}
	if same := record.EffectiveAnnotation.CurrentSame; record.EffectiveAnnotation.Status == domain.EffectiveAnnotationResolved && same != nil {
		switch same.Decision.DecisionSource {
		case domain.SourceHuman:
			report.Summary.Authority.ResolvedHumanSame++
		case domain.SourceResolverAutomatic:
			report.Summary.Authority.ResolvedAutomaticSame++
		}
	}
}

func countQualityHumanLabels(report *ConceptAnnotationQualityReport, record ConceptAnnotationDatasetRecord, hasHumanLabel bool, resolverCounts map[string]int, humanSameGroups map[int64]*qualityHumanSameGroup) {
	labels := record.HumanLabels
	if hasHumanLabel {
		report.LabelInventory.RecordsWithAnyHumanLabel++
	} else {
		report.LabelInventory.RecordsWithoutHumanLabel++
	}
	if labels.Same != nil {
		report.LabelInventory.HumanSameRecords++
		resolverCounts[labels.Same.ResolverVersion]++
		group := humanSameGroups[labels.Same.ConceptID]
		if group == nil {
			group = &qualityHumanSameGroup{units: make(map[int64]struct{}), entries: make(map[int64]struct{})}
			humanSameGroups[labels.Same.ConceptID] = group
		}
		group.units[record.Unit.ID] = struct{}{}
		group.entries[record.Source.EntryID] = struct{}{}
	}
	report.LabelInventory.HumanDistinctPairs += len(labels.Distinctions)
	for _, label := range labels.Distinctions {
		resolverCounts[label.ResolverVersion]++
	}
	for _, label := range labels.Relations {
		resolverCounts[label.ResolverVersion]++
		switch label.Relation {
		case domain.RelationBroader:
			report.LabelInventory.HumanRelations.Broader++
		case domain.RelationNarrower:
			report.LabelInventory.HumanRelations.Narrower++
		case domain.RelationRelated:
			report.LabelInventory.HumanRelations.Related++
		}
	}
	if labels.Invalid != nil {
		report.LabelInventory.HumanInvalidRecords++
	}
	if record.EffectiveAnnotation.Status == domain.EffectiveAnnotationUnresolved && !hasHumanLabel {
		report.LabelInventory.UnlabeledUnresolvedRecords++
	}
	if record.EffectiveAnnotation.Status == domain.EffectiveAnnotationResolved && record.EffectiveAnnotation.CurrentSame != nil && record.EffectiveAnnotation.CurrentSame.Decision.DecisionSource == domain.SourceResolverAutomatic && !hasHumanLabel {
		report.LabelInventory.AutomaticSameOnlyRecords++
	}
}

func validateQualityEffectiveAnnotation(report *ConceptAnnotationQualityReport, record ConceptAnnotationDatasetRecord) {
	effective := record.EffectiveAnnotation
	entryID, unitID := record.Source.EntryID, record.Unit.ID
	if effective.Status == domain.EffectiveAnnotationResolved && effective.CurrentSame == nil {
		addQualityIssue(report, "error", "resolved_without_current_same", entryID, unitID, nil, "resolved record has no current SAME")
	}
	if (effective.Status == domain.EffectiveAnnotationUnresolved || effective.Status == domain.EffectiveAnnotationInvalid) && effective.CurrentSame != nil {
		addQualityIssue(report, "error", "non_resolved_with_current_same", entryID, unitID, qualityConceptID(effective.CurrentSame.Concept.ID), "unresolved or invalid record has a current SAME")
	}
	if same := effective.CurrentSame; same != nil {
		conceptID := same.Concept.ID
		if conceptID != same.Membership.ConceptID || conceptID != same.Decision.ConceptID {
			addQualityIssue(report, "error", "current_same_concept_mismatch", entryID, unitID, qualityConceptID(conceptID), "current SAME concept, membership, and decision concept ids do not match")
		}
		if same.Decision.UnitID != unitID || same.Membership.UnitID != unitID {
			addQualityIssue(report, "error", "current_same_unit_mismatch", entryID, unitID, qualityConceptID(conceptID), "current SAME membership or decision unit id does not match the record")
		}
		if same.Decision.Relation != domain.RelationSame || same.Decision.Status != domain.LinkAccepted {
			addQualityIssue(report, "error", "invalid_current_same_decision", entryID, unitID, qualityConceptID(conceptID), "current SAME decision must be an accepted SAME relation")
		}
		if same.Membership.LinkID != same.Decision.ID {
			addQualityIssue(report, "error", "current_same_link_mismatch", entryID, unitID, qualityConceptID(conceptID), "current SAME membership link_id does not match the decision id")
		}
		if record.Admission.Effective == domain.AdmissionActive && same.Concept.Support != domain.SupportSupported {
			addQualityIssue(report, "error", "active_same_unsupported_concept", entryID, unitID, qualityConceptID(conceptID), "active unit's current SAME concept is not supported")
		}
	}
	if effective.Status == domain.EffectiveAnnotationInvalid {
		if effective.LatestUnitJudgment == nil || effective.LatestUnitJudgment.Judgment != domain.UnitInvalid || effective.LatestUnitJudgment.UnitID != unitID {
			addQualityIssue(report, "error", "invalid_status_judgment_mismatch", entryID, unitID, nil, "invalid record does not have a latest INVALID judgment")
		}
		if effective.CurrentSame != nil || len(effective.Distinctions) != 0 || len(effective.Relations) != 0 || record.HumanLabels.Same != nil || len(record.HumanLabels.Distinctions) != 0 || len(record.HumanLabels.Relations) != 0 {
			addQualityIssue(report, "error", "invalid_pair_output", entryID, unitID, nil, "invalid record exposes pair-level annotation output")
		}
	}
}

func validateQualityHumanProjections(report *ConceptAnnotationQualityReport, record ConceptAnnotationDatasetRecord) {
	entryID, unitID := record.Source.EntryID, record.Unit.ID
	effective, labels := record.EffectiveAnnotation, record.HumanLabels
	if labels.Same != nil {
		label := labels.Same
		if effective.CurrentSame == nil {
			addQualityIssue(report, "error", "human_same_without_effective_same", entryID, unitID, qualityConceptID(label.ConceptID), "human SAME label has no effective current SAME")
		} else {
			decision := effective.CurrentSame.Decision
			if decision.DecisionSource == domain.SourceResolverAutomatic {
				addQualityIssue(report, "error", "automatic_same_has_human_label", entryID, unitID, qualityConceptID(label.ConceptID), "automatic current SAME must not expose a human SAME label")
			} else if decision.DecisionSource != domain.SourceHuman || label.ConceptID != effective.CurrentSame.Concept.ID || label.EventID != decision.ID || label.ResolverVersion != decision.ResolverVersion {
				addQualityIssue(report, "error", "human_same_projection_mismatch", entryID, unitID, qualityConceptID(label.ConceptID), "human SAME label does not exactly match the effective human current SAME")
			}
		}
	}
	if effective.CurrentSame != nil && effective.CurrentSame.Decision.DecisionSource == domain.SourceHuman && labels.Same == nil {
		addQualityIssue(report, "error", "missing_human_same_projection", entryID, unitID, qualityConceptID(effective.CurrentSame.Concept.ID), "effective human current SAME is missing from human labels")
	}

	effectiveDistinct := make(map[qualityDistinctKey]int)
	for _, distinction := range effective.Distinctions {
		if distinction.Concept.ID != distinction.Distinction.ConceptID || distinction.Distinction.UnitID != unitID {
			addQualityIssue(report, "error", "effective_distinction_reference_mismatch", entryID, unitID, qualityConceptID(distinction.Concept.ID), "effective distinction Concept or Unit reference does not match its event")
		}
		if distinction.Distinction.DecisionSource == domain.SourceHuman {
			key := qualityDistinctKey{distinction.Distinction.ConceptID, distinction.Distinction.ID, distinction.Distinction.ResolverVersion}
			effectiveDistinct[key]++
		}
	}
	humanDistinct := make(map[qualityDistinctKey]int)
	for _, label := range labels.Distinctions {
		humanDistinct[qualityDistinctKey{label.ConceptID, label.DistinctionEventID, label.ResolverVersion}]++
	}
	compareQualityProjectionCounts(report, entryID, unitID, effectiveDistinct, humanDistinct, "missing_human_distinct_projection", "human_distinct_projection_mismatch")

	effectiveRelations := make(map[qualityRelationKey]int)
	for _, relation := range effective.Relations {
		if relation.Concept.ID != relation.Decision.ConceptID || relation.Decision.UnitID != unitID {
			addQualityIssue(report, "error", "effective_relation_reference_mismatch", entryID, unitID, qualityConceptID(relation.Concept.ID), "effective relation Concept or Unit reference does not match its decision")
		}
		if relation.Decision.DecisionSource != domain.SourceHuman {
			continue
		}
		if relation.Decision.Relation != domain.RelationBroader && relation.Decision.Relation != domain.RelationNarrower && relation.Decision.Relation != domain.RelationRelated {
			addQualityIssue(report, "error", "invalid_effective_relation", entryID, unitID, qualityConceptID(relation.Concept.ID), "effective human relation is not broader, narrower, or related")
			continue
		}
		key := qualityRelationKey{relation.Decision.ConceptID, relation.Decision.ID, relation.Decision.Relation, relation.Decision.ResolverVersion}
		effectiveRelations[key]++
	}
	humanRelations := make(map[qualityRelationKey]int)
	for _, label := range labels.Relations {
		humanRelations[qualityRelationKey{label.ConceptID, label.EventID, label.Relation, label.ResolverVersion}]++
	}
	compareQualityProjectionCounts(report, entryID, unitID, effectiveRelations, humanRelations, "missing_human_relation_projection", "human_relation_projection_mismatch")

	if effective.Status == domain.EffectiveAnnotationInvalid {
		judgment := effective.LatestUnitJudgment
		if judgment != nil && judgment.Judgment == domain.UnitInvalid && judgment.DecisionSource == domain.SourceHuman {
			if labels.Invalid == nil || labels.Invalid.JudgmentID != judgment.ID || !labels.Invalid.CreatedAt.Equal(judgment.CreatedAt) || labels.Invalid.Note != judgment.Note || labels.Invalid.Evidence != judgment.Evidence {
				addQualityIssue(report, "error", "human_invalid_projection_mismatch", entryID, unitID, nil, "human INVALID label does not exactly match the latest human INVALID judgment")
			}
		} else if labels.Invalid != nil {
			addQualityIssue(report, "error", "non_human_invalid_has_human_label", entryID, unitID, nil, "non-human INVALID state exposes a human INVALID label")
		}
	} else if labels.Invalid != nil {
		addQualityIssue(report, "error", "human_invalid_on_non_invalid", entryID, unitID, nil, "human INVALID label exists on a non-invalid record")
	}
}

func compareQualityProjectionCounts[K comparable](report *ConceptAnnotationQualityReport, entryID, unitID int64, effective, human map[K]int, missingCode, mismatchCode string) {
	for key, count := range effective {
		if human[key] < count {
			for range count - human[key] {
				addQualityIssue(report, "error", missingCode, entryID, unitID, qualityProjectionConceptID(key), "effective human annotation is missing from human labels")
			}
		}
	}
	for key, count := range human {
		if effective[key] < count {
			for range count - effective[key] {
				addQualityIssue(report, "error", mismatchCode, entryID, unitID, qualityProjectionConceptID(key), "human label does not exactly match an effective human annotation")
			}
		}
	}
}

func qualityProjectionConceptID[K comparable](key K) *int64 {
	switch typed := any(key).(type) {
	case qualityDistinctKey:
		return qualityConceptID(typed.conceptID)
	case qualityRelationKey:
		return qualityConceptID(typed.conceptID)
	default:
		return nil
	}
}

func validateQualityContradictions(report *ConceptAnnotationQualityReport, record ConceptAnnotationDatasetRecord) {
	same := record.EffectiveAnnotation.CurrentSame
	if same == nil {
		return
	}
	entryID, unitID, conceptID := record.Source.EntryID, record.Unit.ID, same.Concept.ID
	if same.Decision.DecisionSource == domain.SourceHuman {
		for _, distinction := range record.EffectiveAnnotation.Distinctions {
			if distinction.Distinction.DecisionSource == domain.SourceHuman && distinction.Distinction.ConceptID == conceptID {
				addQualityIssue(report, "error", "human_same_distinct_contradiction", entryID, unitID, qualityConceptID(conceptID), "effective human SAME and DISTINCT reference the same concept")
			}
		}
	}
	for _, relation := range record.EffectiveAnnotation.Relations {
		if relation.Decision.ConceptID == conceptID {
			addQualityIssue(report, "error", "same_relation_contradiction", entryID, unitID, qualityConceptID(conceptID), "current SAME and effective relation reference the same concept")
		}
	}
}

func validateQualityConceptSnapshot(report *ConceptAnnotationQualityReport, entryID, unitID int64, concept domain.KnowledgeConcept) {
	if concept.ID <= 0 || strings.TrimSpace(concept.IdentitySchemaVersion) == "" || strings.TrimSpace(concept.Target) == "" || strings.TrimSpace(concept.PedagogicalIntent) == "" || strings.TrimSpace(concept.Signature) == "" {
		addQualityIssue(report, "error", "invalid_concept_snapshot", entryID, unitID, qualityConceptID(concept.ID), "referenced concept is missing required identity data")
	}
}

func qualityRecordConcepts(record ConceptAnnotationDatasetRecord) []domain.KnowledgeConcept {
	concepts := make([]domain.KnowledgeConcept, 0, 1+len(record.EffectiveAnnotation.Distinctions)+len(record.EffectiveAnnotation.Relations))
	if record.EffectiveAnnotation.CurrentSame != nil {
		concepts = append(concepts, record.EffectiveAnnotation.CurrentSame.Concept)
	}
	for _, distinction := range record.EffectiveAnnotation.Distinctions {
		concepts = append(concepts, distinction.Concept)
	}
	for _, relation := range record.EffectiveAnnotation.Relations {
		concepts = append(concepts, relation.Concept)
	}
	return concepts
}

func qualityRecordHasHumanLabel(record ConceptAnnotationDatasetRecord) bool {
	labels := record.HumanLabels
	return labels.Same != nil || len(labels.Distinctions) != 0 || len(labels.Relations) != 0 || labels.Invalid != nil
}

func sortedQualityDistribution(counts map[string]int) []ConceptAnnotationQualityDistributionCount {
	result := make([]ConceptAnnotationQualityDistributionCount, 0, len(counts))
	for value, count := range counts {
		result = append(result, ConceptAnnotationQualityDistributionCount{Value: value, Count: count})
	}
	sort.Slice(result, func(i, j int) bool { return result[i].Value < result[j].Value })
	return result
}

func addQualityIssue(report *ConceptAnnotationQualityReport, severity, code string, entryID, unitID int64, conceptID *int64, message string) {
	report.Issues = append(report.Issues, ConceptAnnotationQualityIssue{
		Severity: severity, Code: code, EntryID: entryID, UnitID: unitID, ConceptID: conceptID, Message: message,
	})
}

func qualityConceptID(id int64) *int64 {
	return &id
}

func qualityIssueConceptID(id *int64) int64 {
	if id == nil {
		return -1
	}
	return *id
}

func qualitySeverityRank(severity string) int {
	if severity == "error" {
		return 0
	}
	return 1
}
