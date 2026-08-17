package application

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"time"

	"french-learning-app/internal/domain"
)

// ConceptAnnotationDatasetV1SchemaVersion is the stable wire and application
// schema identifier for the first current-snapshot annotation dataset.
const ConceptAnnotationDatasetV1SchemaVersion = "concept_annotation_dataset_v1"

// ErrConceptAnnotationDatasetCorrupt reports broken internal references while
// composing the dataset. Callers must fail closed rather than emit incomplete
// machine-consumed records.
var ErrConceptAnnotationDatasetCorrupt = errors.New("corrupt concept annotation dataset state")

// EffectiveAnnotationDatasetReader supplies the already-resolved M11-A current
// snapshot. Dataset code must not reconstruct annotation authority from history.
type EffectiveAnnotationDatasetReader interface {
	ListEffectiveAnnotations(ctx context.Context) ([]EffectiveAnnotationItem, error)
}

// AnnotationDatasetExtractionReader supplies immutable extraction provenance
// and each unit's current admission read model.
type AnnotationDatasetExtractionReader interface {
	GetByID(ctx context.Context, extractionID int64) (*domain.ExtractionView, error)
}

// AnnotationDatasetConceptReader resolves durable Concept identity snapshots.
type AnnotationDatasetConceptReader interface {
	GetConcept(ctx context.Context, conceptID int64) (*domain.ConceptView, error)
}

// ConceptAnnotationDatasetSource preserves interaction and extraction provenance
// needed for later grouping, splitting, and leakage analysis.
type ConceptAnnotationDatasetSource struct {
	EntryID             int64
	ExtractionID        int64
	ExtractionVersion   int64
	SourceAnalysisID    int64
	SourceFeedbackID    *int64
	Extractor           string
	ExtractionCreatedAt time.Time
}

// ConceptAnnotationDatasetSame is M11-A's CURRENT SAME plus the referenced
// durable Concept snapshot. Membership remains the sole current authority.
type ConceptAnnotationDatasetSame struct {
	Concept    domain.KnowledgeConcept
	Membership domain.CurrentConceptMembership
	Decision   domain.UnitConceptLink
}

// ConceptAnnotationDatasetDistinction is one already-effective M11-A DISTINCT
// event plus its referenced durable Concept snapshot.
type ConceptAnnotationDatasetDistinction struct {
	Concept     domain.KnowledgeConcept
	Distinction domain.UnitConceptDistinction
}

// ConceptAnnotationDatasetRelation is one already-effective M11-A relation plus
// its referenced durable Concept snapshot.
type ConceptAnnotationDatasetRelation struct {
	Concept  domain.KnowledgeConcept
	Decision domain.UnitConceptLink
}

// ConceptAnnotationDatasetEffectiveAnnotation decorates the unchanged M11-A
// effective results with resolved Concept identities. No history is scanned and
// no SAME, INVALID, DISTINCT, or relation authority is recalculated here.
type ConceptAnnotationDatasetEffectiveAnnotation struct {
	UnitID             int64
	Status             domain.EffectiveAnnotationStatus
	LatestUnitJudgment *domain.UnitResolutionJudgment
	CurrentSame        *ConceptAnnotationDatasetSame
	Distinctions       []ConceptAnnotationDatasetDistinction
	Relations          []ConceptAnnotationDatasetRelation
}

// HumanSameLabel is an explicit human CURRENT SAME suitable for later dataset
// validation. An automatic SAME never produces this label.
type HumanSameLabel struct {
	ConceptID       int64
	EventID         int64
	ResolverVersion string
	CreatedAt       time.Time
}

// HumanDistinctLabel is an explicit effective human negative identity pair.
type HumanDistinctLabel struct {
	ConceptID          int64
	DistinctionEventID int64
	ResolverVersion    string
	CreatedAt          time.Time
}

// HumanRelationLabel preserves an explicit effective human non-SAME relation.
type HumanRelationLabel struct {
	ConceptID       int64
	Relation        domain.ConceptRelation
	EventID         int64
	ResolverVersion string
	CreatedAt       time.Time
}

// HumanInvalidLabel is explicit human unit-level exclusion evidence.
type HumanInvalidLabel struct {
	JudgmentID int64
	CreatedAt  time.Time
	Note       string
	Evidence   string
}

// ConceptAnnotationHumanLabels exposes explicit human decisions without
// asserting whole-record gold eligibility. Arrays preserve M11-A order.
type ConceptAnnotationHumanLabels struct {
	Same         *HumanSameLabel
	Distinctions []HumanDistinctLabel
	Relations    []HumanRelationLabel
	Invalid      *HumanInvalidLabel
}

// ConceptAnnotationDatasetRecord is one stable v1 current-snapshot record.
type ConceptAnnotationDatasetRecord struct {
	SchemaVersion       string
	Unit                domain.KnowledgeUnit
	Source              ConceptAnnotationDatasetSource
	Admission           domain.AdmissionState
	EffectiveAnnotation ConceptAnnotationDatasetEffectiveAnnotation
	HumanLabels         ConceptAnnotationHumanLabels
}

// ProjectHumanAnnotationLabels conservatively projects explicit human labels
// from an already-effective M11-A snapshot. It never examines raw history.
func ProjectHumanAnnotationLabels(snapshot domain.EffectiveAnnotationSnapshot) ConceptAnnotationHumanLabels {
	labels := ConceptAnnotationHumanLabels{
		Distinctions: make([]HumanDistinctLabel, 0),
		Relations:    make([]HumanRelationLabel, 0),
	}

	// INVALID is unit-level and dominant in M11-A. Do not allow malformed input
	// to resurrect pair-level labels in this consumer projection.
	if snapshot.Status == domain.EffectiveAnnotationInvalid {
		if snapshot.LatestUnitJudgment != nil && snapshot.LatestUnitJudgment.DecisionSource == domain.SourceHuman {
			labels.Invalid = &HumanInvalidLabel{
				JudgmentID: snapshot.LatestUnitJudgment.ID,
				CreatedAt:  snapshot.LatestUnitJudgment.CreatedAt,
				Note:       snapshot.LatestUnitJudgment.Note,
				Evidence:   snapshot.LatestUnitJudgment.Evidence,
			}
		}
		return labels
	}

	if snapshot.CurrentSame != nil && snapshot.CurrentSame.Decision.DecisionSource == domain.SourceHuman {
		decision := snapshot.CurrentSame.Decision
		labels.Same = &HumanSameLabel{
			ConceptID:       decision.ConceptID,
			EventID:         decision.ID,
			ResolverVersion: decision.ResolverVersion,
			CreatedAt:       decision.CreatedAt,
		}
	}
	for _, distinction := range snapshot.Distinctions {
		if distinction.DecisionSource != domain.SourceHuman {
			continue
		}
		labels.Distinctions = append(labels.Distinctions, HumanDistinctLabel{
			ConceptID:          distinction.ConceptID,
			DistinctionEventID: distinction.ID,
			ResolverVersion:    distinction.ResolverVersion,
			CreatedAt:          distinction.CreatedAt,
		})
	}
	for _, relation := range snapshot.Relations {
		if relation.DecisionSource != domain.SourceHuman {
			continue
		}
		labels.Relations = append(labels.Relations, HumanRelationLabel{
			ConceptID:       relation.ConceptID,
			Relation:        relation.Relation,
			EventID:         relation.ID,
			ResolverVersion: relation.ResolverVersion,
			CreatedAt:       relation.CreatedAt,
		})
	}
	return labels
}

// ConceptAnnotationDatasetService composes the read-only v1 dataset from the
// M11-A projection, extraction/admission provenance, and durable Concepts.
type ConceptAnnotationDatasetService struct {
	effective   EffectiveAnnotationDatasetReader
	extractions AnnotationDatasetExtractionReader
	concepts    AnnotationDatasetConceptReader
}

// NewConceptAnnotationDatasetService wires the three read-only data sources.
func NewConceptAnnotationDatasetService(
	effective EffectiveAnnotationDatasetReader,
	extractions AnnotationDatasetExtractionReader,
	concepts AnnotationDatasetConceptReader,
) *ConceptAnnotationDatasetService {
	return &ConceptAnnotationDatasetService{
		effective: effective, extractions: extractions, concepts: concepts,
	}
}

// ListV1 returns a deterministic current-extraction-only dataset. Extraction
// and Concept reads are cached for the duration of one build.
func (s *ConceptAnnotationDatasetService) ListV1(ctx context.Context) ([]ConceptAnnotationDatasetRecord, error) {
	items, err := s.effective.ListEffectiveAnnotations(ctx)
	if err != nil {
		return nil, fmt.Errorf("list effective annotations: %w", err)
	}

	records := make([]ConceptAnnotationDatasetRecord, 0, len(items))
	extractionCache := make(map[int64]*domain.ExtractionView)
	conceptCache := make(map[int64]domain.KnowledgeConcept)

	for _, item := range items {
		if item.Snapshot.UnitID != item.Unit.ID {
			return nil, datasetCorrupt("effective snapshot unit %d does not match unit %d", item.Snapshot.UnitID, item.Unit.ID)
		}

		extraction, ok := extractionCache[item.Unit.ExtractionID]
		if !ok {
			extraction, err = s.extractions.GetByID(ctx, item.Unit.ExtractionID)
			if errors.Is(err, domain.ErrNotFound) {
				return nil, datasetCorrupt("referenced extraction %d is missing", item.Unit.ExtractionID)
			}
			if err != nil {
				return nil, fmt.Errorf("read extraction %d: %w", item.Unit.ExtractionID, err)
			}
			if extraction == nil || extraction.Extraction.ID != item.Unit.ExtractionID {
				return nil, datasetCorrupt("extraction metadata does not match extraction %d", item.Unit.ExtractionID)
			}
			extractionCache[item.Unit.ExtractionID] = extraction
		}

		admission, ok := admissionForUnit(extraction, item.Unit.ID)
		if !ok {
			return nil, datasetCorrupt("unit %d is absent from extraction %d", item.Unit.ID, item.Unit.ExtractionID)
		}

		effective, err := s.resolveEffectiveConcepts(ctx, item.Snapshot, conceptCache)
		if err != nil {
			return nil, err
		}
		ext := extraction.Extraction
		records = append(records, ConceptAnnotationDatasetRecord{
			SchemaVersion: ConceptAnnotationDatasetV1SchemaVersion,
			Unit:          item.Unit,
			Source: ConceptAnnotationDatasetSource{
				EntryID:             ext.EntryID,
				ExtractionID:        ext.ID,
				ExtractionVersion:   ext.Version,
				SourceAnalysisID:    ext.SourceAnalysisID,
				SourceFeedbackID:    ext.SourceFeedbackID,
				Extractor:           ext.Extractor,
				ExtractionCreatedAt: ext.CreatedAt,
			},
			Admission:           admission,
			EffectiveAnnotation: effective,
			HumanLabels:         ProjectHumanAnnotationLabels(item.Snapshot),
		})
	}

	sort.Slice(records, func(i, j int) bool {
		left, right := records[i], records[j]
		if left.Source.EntryID != right.Source.EntryID {
			return left.Source.EntryID < right.Source.EntryID
		}
		if left.Source.ExtractionVersion != right.Source.ExtractionVersion {
			return left.Source.ExtractionVersion < right.Source.ExtractionVersion
		}
		if left.Unit.Ordinal != right.Unit.Ordinal {
			return left.Unit.Ordinal < right.Unit.Ordinal
		}
		return left.Unit.ID < right.Unit.ID
	})
	return records, nil
}

func admissionForUnit(extraction *domain.ExtractionView, unitID int64) (domain.AdmissionState, bool) {
	for _, unit := range extraction.Units {
		if unit.Unit.ID == unitID {
			return unit.Admission, true
		}
	}
	return domain.AdmissionState{}, false
}

func (s *ConceptAnnotationDatasetService) resolveEffectiveConcepts(
	ctx context.Context,
	snapshot domain.EffectiveAnnotationSnapshot,
	cache map[int64]domain.KnowledgeConcept,
) (ConceptAnnotationDatasetEffectiveAnnotation, error) {
	out := ConceptAnnotationDatasetEffectiveAnnotation{
		UnitID:             snapshot.UnitID,
		Status:             snapshot.Status,
		LatestUnitJudgment: snapshot.LatestUnitJudgment,
		Distinctions:       make([]ConceptAnnotationDatasetDistinction, 0, len(snapshot.Distinctions)),
		Relations:          make([]ConceptAnnotationDatasetRelation, 0, len(snapshot.Relations)),
	}
	if snapshot.CurrentSame != nil {
		concept, err := s.conceptByID(ctx, snapshot.CurrentSame.Membership.ConceptID, cache)
		if err != nil {
			return out, err
		}
		out.CurrentSame = &ConceptAnnotationDatasetSame{
			Concept: concept, Membership: snapshot.CurrentSame.Membership, Decision: snapshot.CurrentSame.Decision,
		}
	}
	for _, distinction := range snapshot.Distinctions {
		concept, err := s.conceptByID(ctx, distinction.ConceptID, cache)
		if err != nil {
			return out, err
		}
		out.Distinctions = append(out.Distinctions, ConceptAnnotationDatasetDistinction{
			Concept: concept, Distinction: distinction,
		})
	}
	for _, relation := range snapshot.Relations {
		concept, err := s.conceptByID(ctx, relation.ConceptID, cache)
		if err != nil {
			return out, err
		}
		out.Relations = append(out.Relations, ConceptAnnotationDatasetRelation{
			Concept: concept, Decision: relation,
		})
	}
	return out, nil
}

func (s *ConceptAnnotationDatasetService) conceptByID(
	ctx context.Context,
	conceptID int64,
	cache map[int64]domain.KnowledgeConcept,
) (domain.KnowledgeConcept, error) {
	if concept, ok := cache[conceptID]; ok {
		return concept, nil
	}
	view, err := s.concepts.GetConcept(ctx, conceptID)
	if errors.Is(err, domain.ErrNotFound) {
		return domain.KnowledgeConcept{}, datasetCorrupt("referenced concept %d is missing", conceptID)
	}
	if err != nil {
		return domain.KnowledgeConcept{}, fmt.Errorf("read concept %d: %w", conceptID, err)
	}
	if view == nil || view.Concept.ID != conceptID {
		return domain.KnowledgeConcept{}, datasetCorrupt("concept metadata does not match concept %d", conceptID)
	}
	cache[conceptID] = view.Concept
	return view.Concept, nil
}

func datasetCorrupt(format string, args ...any) error {
	return fmt.Errorf("%w: %s", ErrConceptAnnotationDatasetCorrupt, fmt.Sprintf(format, args...))
}
