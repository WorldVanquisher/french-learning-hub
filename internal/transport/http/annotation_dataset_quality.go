package http

import (
	"context"
	"net/http"

	"french-learning-app/internal/application"
)

// AnnotationDatasetQualityService is the narrow read-only application behavior
// needed by the quality-report endpoint.
type AnnotationDatasetQualityService interface {
	BuildV1(ctx context.Context) (application.ConceptAnnotationQualityReport, error)
}

type annotationDatasetQualityResponse struct {
	SchemaVersion        string                                     `json:"schema_version"`
	DatasetSchemaVersion string                                     `json:"dataset_schema_version"`
	Valid                bool                                       `json:"valid"`
	ErrorCount           int                                        `json:"error_count"`
	WarningCount         int                                        `json:"warning_count"`
	Summary              annotationDatasetQualitySummaryResponse    `json:"summary"`
	LabelInventory       annotationDatasetQualityLabelsResponse     `json:"label_inventory"`
	Provenance           annotationDatasetQualityProvenanceResponse `json:"provenance"`
	LeakageRisk          annotationDatasetQualityLeakageResponse    `json:"leakage_risk"`
	Issues               []annotationDatasetQualityIssueResponse    `json:"issues"`
}

type annotationDatasetQualitySummaryResponse struct {
	TotalRecords            int                                       `json:"total_records"`
	TotalEntries            int                                       `json:"total_entries"`
	TotalExtractions        int                                       `json:"total_extractions"`
	TotalReferencedConcepts int                                       `json:"total_referenced_concepts"`
	EffectiveStatus         annotationDatasetQualityStatusResponse    `json:"effective_status"`
	AdmissionEffective      annotationDatasetQualityAdmissionResponse `json:"admission_effective"`
	Authority               annotationDatasetQualityAuthorityResponse `json:"authority"`
}

type annotationDatasetQualityStatusResponse struct {
	Resolved   int `json:"resolved"`
	Unresolved int `json:"unresolved"`
	Invalid    int `json:"invalid"`
}

type annotationDatasetQualityAdmissionResponse struct {
	Active      int `json:"active"`
	Suppressed  int `json:"suppressed"`
	NeedsReview int `json:"needs_review"`
}

type annotationDatasetQualityAuthorityResponse struct {
	ResolvedHumanSame     int `json:"resolved_human_same"`
	ResolvedAutomaticSame int `json:"resolved_automatic_same"`
}

type annotationDatasetQualityLabelsResponse struct {
	RecordsWithAnyHumanLabel   int                                       `json:"records_with_any_human_label"`
	RecordsWithoutHumanLabel   int                                       `json:"records_without_human_label"`
	HumanSameRecords           int                                       `json:"human_same_records"`
	HumanDistinctPairs         int                                       `json:"human_distinct_pairs"`
	HumanRelations             annotationDatasetQualityRelationsResponse `json:"human_relations"`
	HumanInvalidRecords        int                                       `json:"human_invalid_records"`
	UnlabeledUnresolvedRecords int                                       `json:"unlabeled_unresolved_records"`
	AutomaticSameOnlyRecords   int                                       `json:"automatic_same_only_records"`
}

type annotationDatasetQualityRelationsResponse struct {
	Broader  int `json:"broader"`
	Narrower int `json:"narrower"`
	Related  int `json:"related"`
}

type annotationDatasetQualityProvenanceResponse struct {
	Extractors                    []annotationDatasetQualityDistributionResponse `json:"extractors"`
	ConceptIdentitySchemaVersions []annotationDatasetQualityDistributionResponse `json:"concept_identity_schema_versions"`
	HumanLabelResolverVersions    []annotationDatasetQualityDistributionResponse `json:"human_label_resolver_versions"`
}

type annotationDatasetQualityDistributionResponse struct {
	Value string `json:"value"`
	Count int    `json:"count"`
}

type annotationDatasetQualityLeakageResponse struct {
	EntriesWithMultipleRecords               int `json:"entries_with_multiple_records"`
	MaxRecordsPerEntry                       int `json:"max_records_per_entry"`
	HumanSameConcepts                        int `json:"human_same_concepts"`
	HumanSameConceptsWithMultipleUnits       int `json:"human_same_concepts_with_multiple_units"`
	HumanSameConceptsSpanningMultipleEntries int `json:"human_same_concepts_spanning_multiple_entries"`
	MaxUnitsPerHumanSameConcept              int `json:"max_units_per_human_same_concept"`
}

type annotationDatasetQualityIssueResponse struct {
	Severity  string `json:"severity"`
	Code      string `json:"code"`
	EntryID   int64  `json:"entry_id"`
	UnitID    int64  `json:"unit_id"`
	ConceptID *int64 `json:"concept_id"`
	Message   string `json:"message"`
}

func toAnnotationDatasetQualityResponse(report application.ConceptAnnotationQualityReport) annotationDatasetQualityResponse {
	response := annotationDatasetQualityResponse{
		SchemaVersion:        report.SchemaVersion,
		DatasetSchemaVersion: report.DatasetSchemaVersion,
		Valid:                report.Valid,
		ErrorCount:           report.ErrorCount,
		WarningCount:         report.WarningCount,
		Summary: annotationDatasetQualitySummaryResponse{
			TotalRecords: report.Summary.TotalRecords, TotalEntries: report.Summary.TotalEntries,
			TotalExtractions: report.Summary.TotalExtractions, TotalReferencedConcepts: report.Summary.TotalReferencedConcepts,
			EffectiveStatus: annotationDatasetQualityStatusResponse{
				Resolved: report.Summary.EffectiveStatus.Resolved, Unresolved: report.Summary.EffectiveStatus.Unresolved, Invalid: report.Summary.EffectiveStatus.Invalid,
			},
			AdmissionEffective: annotationDatasetQualityAdmissionResponse{
				Active: report.Summary.AdmissionEffective.Active, Suppressed: report.Summary.AdmissionEffective.Suppressed, NeedsReview: report.Summary.AdmissionEffective.NeedsReview,
			},
			Authority: annotationDatasetQualityAuthorityResponse{
				ResolvedHumanSame: report.Summary.Authority.ResolvedHumanSame, ResolvedAutomaticSame: report.Summary.Authority.ResolvedAutomaticSame,
			},
		},
		LabelInventory: annotationDatasetQualityLabelsResponse{
			RecordsWithAnyHumanLabel: report.LabelInventory.RecordsWithAnyHumanLabel,
			RecordsWithoutHumanLabel: report.LabelInventory.RecordsWithoutHumanLabel,
			HumanSameRecords:         report.LabelInventory.HumanSameRecords, HumanDistinctPairs: report.LabelInventory.HumanDistinctPairs,
			HumanRelations: annotationDatasetQualityRelationsResponse{
				Broader: report.LabelInventory.HumanRelations.Broader, Narrower: report.LabelInventory.HumanRelations.Narrower, Related: report.LabelInventory.HumanRelations.Related,
			},
			HumanInvalidRecords:        report.LabelInventory.HumanInvalidRecords,
			UnlabeledUnresolvedRecords: report.LabelInventory.UnlabeledUnresolvedRecords,
			AutomaticSameOnlyRecords:   report.LabelInventory.AutomaticSameOnlyRecords,
		},
		Provenance: annotationDatasetQualityProvenanceResponse{
			Extractors:                    make([]annotationDatasetQualityDistributionResponse, 0, len(report.Provenance.Extractors)),
			ConceptIdentitySchemaVersions: make([]annotationDatasetQualityDistributionResponse, 0, len(report.Provenance.ConceptIdentitySchemaVersions)),
			HumanLabelResolverVersions:    make([]annotationDatasetQualityDistributionResponse, 0, len(report.Provenance.HumanLabelResolverVersions)),
		},
		LeakageRisk: annotationDatasetQualityLeakageResponse{
			EntriesWithMultipleRecords:               report.LeakageRisk.EntriesWithMultipleRecords,
			MaxRecordsPerEntry:                       report.LeakageRisk.MaxRecordsPerEntry,
			HumanSameConcepts:                        report.LeakageRisk.HumanSameConcepts,
			HumanSameConceptsWithMultipleUnits:       report.LeakageRisk.HumanSameConceptsWithMultipleUnits,
			HumanSameConceptsSpanningMultipleEntries: report.LeakageRisk.HumanSameConceptsSpanningMultipleEntries,
			MaxUnitsPerHumanSameConcept:              report.LeakageRisk.MaxUnitsPerHumanSameConcept,
		},
		Issues: make([]annotationDatasetQualityIssueResponse, 0, len(report.Issues)),
	}
	for _, bucket := range report.Provenance.Extractors {
		response.Provenance.Extractors = append(response.Provenance.Extractors, toQualityDistributionResponse(bucket))
	}
	for _, bucket := range report.Provenance.ConceptIdentitySchemaVersions {
		response.Provenance.ConceptIdentitySchemaVersions = append(response.Provenance.ConceptIdentitySchemaVersions, toQualityDistributionResponse(bucket))
	}
	for _, bucket := range report.Provenance.HumanLabelResolverVersions {
		response.Provenance.HumanLabelResolverVersions = append(response.Provenance.HumanLabelResolverVersions, toQualityDistributionResponse(bucket))
	}
	for _, issue := range report.Issues {
		response.Issues = append(response.Issues, annotationDatasetQualityIssueResponse{
			Severity: issue.Severity, Code: issue.Code, EntryID: issue.EntryID,
			UnitID: issue.UnitID, ConceptID: issue.ConceptID, Message: issue.Message,
		})
	}
	return response
}

func toQualityDistributionResponse(bucket application.ConceptAnnotationQualityDistributionCount) annotationDatasetQualityDistributionResponse {
	return annotationDatasetQualityDistributionResponse{Value: bucket.Value, Count: bucket.Count}
}

func (h *Handler) handleGetAnnotationDatasetQualityV1(w http.ResponseWriter, r *http.Request) {
	if h.annotationQuality == nil {
		writeError(w, http.StatusInternalServerError, "could not build concept annotation quality report")
		return
	}
	report, err := h.annotationQuality.BuildV1(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not build concept annotation quality report")
		return
	}
	writeJSON(w, http.StatusOK, toAnnotationDatasetQualityResponse(report))
}
