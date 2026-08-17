package http

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"french-learning-app/internal/application"
)

// AnnotationDatasetService is the narrow read-only application behavior needed
// by both v1 dataset representations.
type AnnotationDatasetService interface {
	ListV1(ctx context.Context) ([]application.ConceptAnnotationDatasetRecord, error)
}

type annotationDatasetResponse struct {
	SchemaVersion string                            `json:"schema_version"`
	Records       []annotationDatasetRecordResponse `json:"records"`
}

type annotationDatasetRecordResponse struct {
	SchemaVersion       string                                       `json:"schema_version"`
	Unit                effectiveAnnotationUnitResponse              `json:"unit"`
	Source              annotationDatasetSourceResponse              `json:"source"`
	Admission           admissionResponse                            `json:"admission"`
	EffectiveAnnotation annotationDatasetEffectiveAnnotationResponse `json:"effective_annotation"`
	HumanLabels         annotationDatasetHumanLabelsResponse         `json:"human_labels"`
}

type annotationDatasetSourceResponse struct {
	EntryID             int64  `json:"entry_id"`
	ExtractionID        int64  `json:"extraction_id"`
	ExtractionVersion   int64  `json:"extraction_version"`
	SourceAnalysisID    int64  `json:"source_analysis_id"`
	SourceFeedbackID    *int64 `json:"source_feedback_id"`
	Extractor           string `json:"extractor"`
	ExtractionCreatedAt string `json:"extraction_created_at"`
}

type annotationDatasetSameResponse struct {
	Concept    conceptResponse           `json:"concept"`
	Membership currentMembershipResponse `json:"membership"`
	Decision   unitConceptLinkResponse   `json:"decision"`
}

type annotationDatasetDistinctionResponse struct {
	Concept     conceptResponse         `json:"concept"`
	Distinction unitDistinctionResponse `json:"distinction"`
}

type annotationDatasetRelationResponse struct {
	Concept  conceptResponse         `json:"concept"`
	Decision unitConceptLinkResponse `json:"decision"`
}

type annotationDatasetEffectiveAnnotationResponse struct {
	UnitID             int64                                  `json:"unit_id"`
	Status             string                                 `json:"status"`
	LatestUnitJudgment *unitJudgmentResponse                  `json:"latest_unit_judgment"`
	CurrentSame        *annotationDatasetSameResponse         `json:"current_same"`
	Distinctions       []annotationDatasetDistinctionResponse `json:"distinctions"`
	Relations          []annotationDatasetRelationResponse    `json:"relations"`
}

type annotationDatasetHumanSameResponse struct {
	ConceptID       int64  `json:"concept_id"`
	EventID         int64  `json:"event_id"`
	ResolverVersion string `json:"resolver_version"`
	CreatedAt       string `json:"created_at"`
}

type annotationDatasetHumanDistinctResponse struct {
	ConceptID          int64  `json:"concept_id"`
	DistinctionEventID int64  `json:"distinction_event_id"`
	ResolverVersion    string `json:"resolver_version"`
	CreatedAt          string `json:"created_at"`
}

type annotationDatasetHumanRelationResponse struct {
	ConceptID       int64  `json:"concept_id"`
	Relation        string `json:"relation"`
	EventID         int64  `json:"event_id"`
	ResolverVersion string `json:"resolver_version"`
	CreatedAt       string `json:"created_at"`
}

type annotationDatasetHumanInvalidResponse struct {
	JudgmentID int64  `json:"judgment_id"`
	CreatedAt  string `json:"created_at"`
	Note       string `json:"note"`
	Evidence   string `json:"evidence"`
}

type annotationDatasetHumanLabelsResponse struct {
	Same         *annotationDatasetHumanSameResponse      `json:"same"`
	Distinctions []annotationDatasetHumanDistinctResponse `json:"distinctions"`
	Relations    []annotationDatasetHumanRelationResponse `json:"relations"`
	Invalid      *annotationDatasetHumanInvalidResponse   `json:"invalid"`
}

func toAnnotationDatasetRecordResponse(record application.ConceptAnnotationDatasetRecord) annotationDatasetRecordResponse {
	effective := annotationDatasetEffectiveAnnotationResponse{
		UnitID:       record.EffectiveAnnotation.UnitID,
		Status:       string(record.EffectiveAnnotation.Status),
		Distinctions: make([]annotationDatasetDistinctionResponse, 0, len(record.EffectiveAnnotation.Distinctions)),
		Relations:    make([]annotationDatasetRelationResponse, 0, len(record.EffectiveAnnotation.Relations)),
	}
	if record.EffectiveAnnotation.LatestUnitJudgment != nil {
		judgment := toUnitJudgmentResponse(*record.EffectiveAnnotation.LatestUnitJudgment)
		effective.LatestUnitJudgment = &judgment
	}
	if record.EffectiveAnnotation.CurrentSame != nil {
		same := record.EffectiveAnnotation.CurrentSame
		membership := toCurrentMembershipResponse(&same.Membership)
		effective.CurrentSame = &annotationDatasetSameResponse{
			Concept:    toConceptResponse(same.Concept),
			Membership: *membership,
			Decision:   toLinkResponse(same.Decision),
		}
	}
	for _, distinction := range record.EffectiveAnnotation.Distinctions {
		effective.Distinctions = append(effective.Distinctions, annotationDatasetDistinctionResponse{
			Concept:     toConceptResponse(distinction.Concept),
			Distinction: toUnitDistinctionResponse(distinction.Distinction),
		})
	}
	for _, relation := range record.EffectiveAnnotation.Relations {
		effective.Relations = append(effective.Relations, annotationDatasetRelationResponse{
			Concept:  toConceptResponse(relation.Concept),
			Decision: toLinkResponse(relation.Decision),
		})
	}

	human := annotationDatasetHumanLabelsResponse{
		Distinctions: make([]annotationDatasetHumanDistinctResponse, 0, len(record.HumanLabels.Distinctions)),
		Relations:    make([]annotationDatasetHumanRelationResponse, 0, len(record.HumanLabels.Relations)),
	}
	if record.HumanLabels.Same != nil {
		same := record.HumanLabels.Same
		human.Same = &annotationDatasetHumanSameResponse{
			ConceptID: same.ConceptID, EventID: same.EventID,
			ResolverVersion: same.ResolverVersion, CreatedAt: formatDatasetTime(same.CreatedAt),
		}
	}
	for _, distinction := range record.HumanLabels.Distinctions {
		human.Distinctions = append(human.Distinctions, annotationDatasetHumanDistinctResponse{
			ConceptID: distinction.ConceptID, DistinctionEventID: distinction.DistinctionEventID,
			ResolverVersion: distinction.ResolverVersion, CreatedAt: formatDatasetTime(distinction.CreatedAt),
		})
	}
	for _, relation := range record.HumanLabels.Relations {
		human.Relations = append(human.Relations, annotationDatasetHumanRelationResponse{
			ConceptID: relation.ConceptID, Relation: string(relation.Relation), EventID: relation.EventID,
			ResolverVersion: relation.ResolverVersion, CreatedAt: formatDatasetTime(relation.CreatedAt),
		})
	}
	if record.HumanLabels.Invalid != nil {
		invalid := record.HumanLabels.Invalid
		human.Invalid = &annotationDatasetHumanInvalidResponse{
			JudgmentID: invalid.JudgmentID, CreatedAt: formatDatasetTime(invalid.CreatedAt),
			Note: invalid.Note, Evidence: invalid.Evidence,
		}
	}

	return annotationDatasetRecordResponse{
		SchemaVersion: record.SchemaVersion,
		Unit:          toEffectiveAnnotationUnitResponse(record.Unit),
		Source: annotationDatasetSourceResponse{
			EntryID: record.Source.EntryID, ExtractionID: record.Source.ExtractionID,
			ExtractionVersion:   record.Source.ExtractionVersion,
			SourceAnalysisID:    record.Source.SourceAnalysisID,
			SourceFeedbackID:    record.Source.SourceFeedbackID,
			Extractor:           record.Source.Extractor,
			ExtractionCreatedAt: formatDatasetTime(record.Source.ExtractionCreatedAt),
		},
		Admission:           toAdmissionResponse(record.Admission),
		EffectiveAnnotation: effective,
		HumanLabels:         human,
	}
}

func toAnnotationDatasetRecordResponses(records []application.ConceptAnnotationDatasetRecord) []annotationDatasetRecordResponse {
	responses := make([]annotationDatasetRecordResponse, 0, len(records))
	for _, record := range records {
		responses = append(responses, toAnnotationDatasetRecordResponse(record))
	}
	return responses
}

func formatDatasetTime(value time.Time) string {
	return value.Format(time.RFC3339Nano)
}

// handleGetAnnotationDatasetV1 returns the stable JSON dataset envelope.
func (h *Handler) handleGetAnnotationDatasetV1(w http.ResponseWriter, r *http.Request) {
	records, err := h.annotationDataset.ListV1(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not build concept annotation dataset")
		return
	}
	writeJSON(w, http.StatusOK, annotationDatasetResponse{
		SchemaVersion: application.ConceptAnnotationDatasetV1SchemaVersion,
		Records:       toAnnotationDatasetRecordResponses(records),
	})
}

// handleExportAnnotationDatasetV1 returns the same application records as
// newline-delimited JSON, one versioned record per line.
func (h *Handler) handleExportAnnotationDatasetV1(w http.ResponseWriter, r *http.Request) {
	records, err := h.annotationDataset.ListV1(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not build concept annotation dataset")
		return
	}

	w.Header().Set("Content-Type", "application/x-ndjson; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	encoder := json.NewEncoder(w)
	for _, record := range records {
		if err := encoder.Encode(toAnnotationDatasetRecordResponse(record)); err != nil {
			return
		}
	}
}
