package application

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"

	"french-learning-app/internal/domain"
)

const (
	ConceptRetrievalEvaluationV1SchemaVersion = "concept_retrieval_evaluation_v1"
	ConceptRetrievalEvaluationPolicyV1        = "concept_retrieval_eval_policy_v1"
	ConceptRetrievalEvaluationMaxK            = 5

	ConceptRetrievalEvaluationStateEvaluated             = "evaluated"
	ConceptRetrievalEvaluationStateBlockedInvalidDataset = "blocked_invalid_dataset"
)

// AnnotationDatasetQualityReader is the M11-D quality gate used before any
// retrieval metric is calculated.
type AnnotationDatasetQualityReader interface {
	BuildV1(ctx context.Context) (ConceptAnnotationQualityReport, error)
}

// RetrievalConceptCatalogReader supplies the current durable Concept catalog.
// Annotation truth never comes from this interface.
type RetrievalConceptCatalogReader interface {
	ListConcepts(ctx context.Context, state *domain.ConceptState) ([]domain.KnowledgeConcept, error)
}

type ConceptRetrievalCandidateUniverse struct {
	Concepts int
}

type ConceptRetrievalEvaluationExclusions struct {
	UnclassifiedHumanSameProvenance int
	SeedNewConcept                  int
	NonActiveAdmission              int
	RetiredTargetConcept            int
	TargetMissingFromCurrentCatalog int
}

type ConceptRetrievalEvaluationSampleInventory struct {
	HumanSameRecords int
	EligibleSamples  int
	Excluded         ConceptRetrievalEvaluationExclusions
}

type ConceptRetrievalEvaluationMetrics struct {
	RecallAt1 *float64
	RecallAt3 *float64
	RecallAt5 *float64
	MRR       *float64
}

// ConceptRetrievalEvaluationSample is an auditable result for one eligible
// current human SAME. Retrieved candidates are retrieval output only.
type ConceptRetrievalEvaluationSample struct {
	UnitID           int64
	EntryID          int64
	ExtractionID     int64
	Query            ConceptRetrievalQuery
	TargetConcept    ConceptRetrievalDocument
	HumanSameEventID int64
	HumanSameReason  string
	Retrieved        []ConceptRetrievalCandidate
	TargetRank       *int
	ReciprocalRank   float64
	HitAt1           bool
	HitAt3           bool
	HitAt5           bool
}

type ConceptRetrievalEvaluationReport struct {
	SchemaVersion     string
	EvaluationPolicy  string
	Retriever         string
	State             string
	DatasetValid      bool
	CandidateUniverse ConceptRetrievalCandidateUniverse
	EvaluationSamples ConceptRetrievalEvaluationSampleInventory
	Metrics           ConceptRetrievalEvaluationMetrics
	Samples           []ConceptRetrievalEvaluationSample
}

// ConceptRetrievalEvaluationService builds a current-catalog retrieval audit
// using M11-C human truth, gated by M11-D validity.
type ConceptRetrievalEvaluationService struct {
	dataset    AnnotationDatasetV1Reader
	quality    AnnotationDatasetQualityReader
	catalog    RetrievalConceptCatalogReader
	retrievers *ConceptRetrieverRegistry
}

func NewConceptRetrievalEvaluationService(dataset AnnotationDatasetV1Reader, quality AnnotationDatasetQualityReader, catalog RetrievalConceptCatalogReader, retriever ConceptRetriever) *ConceptRetrievalEvaluationService {
	return NewConceptRetrievalEvaluationServiceWithRegistry(dataset, quality, catalog, NewConceptRetrieverRegistry(retriever))
}

func NewConceptRetrievalEvaluationServiceWithRegistry(dataset AnnotationDatasetV1Reader, quality AnnotationDatasetQualityReader, catalog RetrievalConceptCatalogReader, retrievers *ConceptRetrieverRegistry) *ConceptRetrievalEvaluationService {
	return &ConceptRetrievalEvaluationService{dataset: dataset, quality: quality, catalog: catalog, retrievers: retrievers}
}

// BuildV1 evaluates eligible explicit human SAME labels against the current
// non-retired Concept catalog. It never records retrieval output or annotation
// authority.
func (s *ConceptRetrievalEvaluationService) BuildV1(ctx context.Context) (ConceptRetrievalEvaluationReport, error) {
	return s.BuildV1WithRetriever(ctx, "")
}

// BuildV1WithRetriever runs the unchanged evaluation policy with the selected
// retrieval strategy. Empty selection preserves the exact-signature default.
func (s *ConceptRetrievalEvaluationService) BuildV1WithRetriever(ctx context.Context, name string) (ConceptRetrievalEvaluationReport, error) {
	retriever, err := s.retrievers.Select(name)
	if err != nil {
		return ConceptRetrievalEvaluationReport{}, err
	}
	report := ConceptRetrievalEvaluationReport{
		SchemaVersion:    ConceptRetrievalEvaluationV1SchemaVersion,
		EvaluationPolicy: ConceptRetrievalEvaluationPolicyV1,
		Retriever:        retriever.Name(),
		State:            ConceptRetrievalEvaluationStateEvaluated,
		DatasetValid:     true,
		Samples:          make([]ConceptRetrievalEvaluationSample, 0),
	}

	quality, err := s.quality.BuildV1(ctx)
	if err != nil {
		return ConceptRetrievalEvaluationReport{}, fmt.Errorf("build concept annotation quality report: %w", err)
	}
	if !quality.Valid {
		report.State = ConceptRetrievalEvaluationStateBlockedInvalidDataset
		report.DatasetValid = false
		return report, nil
	}

	records, err := s.dataset.ListV1(ctx)
	if err != nil {
		return ConceptRetrievalEvaluationReport{}, fmt.Errorf("list concept annotation dataset v1: %w", err)
	}
	concepts, err := s.catalog.ListConcepts(ctx, nil)
	if err != nil {
		return ConceptRetrievalEvaluationReport{}, fmt.Errorf("list current concept catalog: %w", err)
	}

	allConceptsByID := make(map[int64]domain.KnowledgeConcept, len(concepts))
	documents := make([]ConceptRetrievalDocument, 0, len(concepts))
	for _, concept := range concepts {
		allConceptsByID[concept.ID] = concept
		if concept.Lifecycle == domain.LifecycleRetired {
			continue
		}
		documents = append(documents, toConceptRetrievalDocument(concept))
	}
	sort.Slice(documents, func(i, j int) bool { return documents[i].ConceptID < documents[j].ConceptID })
	documentsByID := make(map[int64]ConceptRetrievalDocument, len(documents))
	for _, document := range documents {
		documentsByID[document.ConceptID] = document
	}
	report.CandidateUniverse.Concepts = len(documents)

	eligible := make([]eligibleConceptRetrievalRecord, 0)
	for _, record := range records {
		same, label, isHumanSame, err := evaluationHumanSame(record)
		if err != nil {
			return ConceptRetrievalEvaluationReport{}, err
		}
		if !isHumanSame {
			continue
		}
		report.EvaluationSamples.HumanSameRecords++

		reason, classified := classifyHumanSameEvidence(same.Decision.Evidence)
		if !classified {
			report.EvaluationSamples.Excluded.UnclassifiedHumanSameProvenance++
			continue
		}
		if reason == "seed_unit_same" {
			report.EvaluationSamples.Excluded.SeedNewConcept++
			continue
		}
		if record.Admission.Effective != domain.AdmissionActive {
			report.EvaluationSamples.Excluded.NonActiveAdmission++
			continue
		}
		catalogConcept, catalogFound := allConceptsByID[same.Concept.ID]
		if same.Concept.Lifecycle == domain.LifecycleRetired || (catalogFound && catalogConcept.Lifecycle == domain.LifecycleRetired) {
			report.EvaluationSamples.Excluded.RetiredTargetConcept++
			continue
		}
		target, inUniverse := documentsByID[same.Concept.ID]
		if !inUniverse {
			report.EvaluationSamples.Excluded.TargetMissingFromCurrentCatalog++
			continue
		}
		eligible = append(eligible, eligibleConceptRetrievalRecord{
			record: record, target: target, eventID: label.EventID, reason: reason,
		})
	}

	sort.Slice(eligible, func(i, j int) bool {
		if eligible[i].record.Source.EntryID != eligible[j].record.Source.EntryID {
			return eligible[i].record.Source.EntryID < eligible[j].record.Source.EntryID
		}
		return eligible[i].record.Unit.ID < eligible[j].record.Unit.ID
	})
	report.EvaluationSamples.EligibleSamples = len(eligible)

	for _, item := range eligible {
		query := toConceptRetrievalQuery(item.record.Unit)
		candidates, err := retriever.Retrieve(ctx, query, documents, ConceptRetrievalEvaluationMaxK)
		if err != nil {
			return ConceptRetrievalEvaluationReport{}, fmt.Errorf("retrieve candidates for unit %d: %w", item.record.Unit.ID, err)
		}
		if candidates == nil {
			candidates = make([]ConceptRetrievalCandidate, 0)
		}
		if err := validateConceptRetrievalCandidates(candidates, documentsByID); err != nil {
			return ConceptRetrievalEvaluationReport{}, fmt.Errorf("invalid retrieval result for unit %d: %w", item.record.Unit.ID, err)
		}

		sample := ConceptRetrievalEvaluationSample{
			UnitID: item.record.Unit.ID, EntryID: item.record.Source.EntryID,
			ExtractionID: item.record.Source.ExtractionID, Query: query,
			TargetConcept: item.target, HumanSameEventID: item.eventID,
			HumanSameReason: item.reason, Retrieved: candidates,
		}
		for _, candidate := range candidates {
			if candidate.ConceptID != item.target.ConceptID {
				continue
			}
			rank := candidate.Rank
			sample.TargetRank = &rank
			sample.ReciprocalRank = 1 / float64(rank)
			sample.HitAt1 = rank <= 1
			sample.HitAt3 = rank <= 3
			sample.HitAt5 = rank <= 5
			break
		}
		report.Samples = append(report.Samples, sample)
	}
	report.Metrics = calculateConceptRetrievalMetrics(report.Samples)
	return report, nil
}

type eligibleConceptRetrievalRecord struct {
	record  ConceptAnnotationDatasetRecord
	target  ConceptRetrievalDocument
	eventID int64
	reason  string
}

func evaluationHumanSame(record ConceptAnnotationDatasetRecord) (*ConceptAnnotationDatasetSame, *HumanSameLabel, bool, error) {
	same := record.EffectiveAnnotation.CurrentSame
	label := record.HumanLabels.Same
	hasHumanAuthority := same != nil && same.Decision.DecisionSource == domain.SourceHuman
	if !hasHumanAuthority && label == nil {
		return nil, nil, false, nil
	}
	if record.EffectiveAnnotation.Status != domain.EffectiveAnnotationResolved || same == nil || label == nil || same.Decision.DecisionSource != domain.SourceHuman || label.ConceptID != same.Concept.ID || label.EventID != same.Decision.ID || label.ResolverVersion != same.Decision.ResolverVersion {
		return nil, nil, false, fmt.Errorf("dataset quality gate reported valid but unit %d has inconsistent human SAME projection", record.Unit.ID)
	}
	return same, label, true, nil
}

func classifyHumanSameEvidence(evidence string) (string, bool) {
	var value struct {
		Reason string `json:"reason"`
	}
	if err := json.Unmarshal([]byte(evidence), &value); err != nil {
		return "", false
	}
	switch value.Reason {
	case "seed_unit_same", "human_same", "human_same_correction":
		return value.Reason, true
	default:
		return "", false
	}
}

func toConceptRetrievalQuery(unit domain.KnowledgeUnit) ConceptRetrievalQuery {
	return ConceptRetrievalQuery{
		UnitID: unit.ID, Kind: unit.Kind, Canonical: unit.Canonical,
		Statement: unit.Statement, Example: unit.Example,
		CandidateIdentity: domain.DeriveCandidateIdentity(unit),
	}
}

func toConceptRetrievalDocument(concept domain.KnowledgeConcept) ConceptRetrievalDocument {
	features := make(map[string]string, len(concept.IdentityFeatures))
	for key, value := range concept.IdentityFeatures {
		features[key] = value
	}
	return ConceptRetrievalDocument{
		ConceptID: concept.ID, IdentitySchemaVersion: concept.IdentitySchemaVersion,
		Target: concept.Target, PedagogicalIntent: concept.PedagogicalIntent,
		Scope: concept.Scope, IdentityFeatures: features, Signature: concept.Signature,
		Lifecycle: concept.Lifecycle, Support: concept.Support, State: concept.State,
	}
}

func validateConceptRetrievalCandidates(candidates []ConceptRetrievalCandidate, universe map[int64]ConceptRetrievalDocument) error {
	if len(candidates) > ConceptRetrievalEvaluationMaxK {
		return fmt.Errorf("retriever returned more than %d candidates", ConceptRetrievalEvaluationMaxK)
	}
	seen := make(map[int64]struct{}, len(candidates))
	for index, candidate := range candidates {
		if candidate.Rank != index+1 {
			return fmt.Errorf("candidate rank %d does not match position %d", candidate.Rank, index+1)
		}
		if _, exists := universe[candidate.ConceptID]; !exists {
			return fmt.Errorf("candidate concept %d is outside the current universe", candidate.ConceptID)
		}
		if _, duplicate := seen[candidate.ConceptID]; duplicate {
			return fmt.Errorf("candidate concept %d appears more than once", candidate.ConceptID)
		}
		seen[candidate.ConceptID] = struct{}{}
	}
	return nil
}

func calculateConceptRetrievalMetrics(samples []ConceptRetrievalEvaluationSample) ConceptRetrievalEvaluationMetrics {
	if len(samples) == 0 {
		return ConceptRetrievalEvaluationMetrics{}
	}
	var hit1, hit3, hit5 int
	var reciprocalRank float64
	for _, sample := range samples {
		if sample.HitAt1 {
			hit1++
		}
		if sample.HitAt3 {
			hit3++
		}
		if sample.HitAt5 {
			hit5++
		}
		reciprocalRank += sample.ReciprocalRank
	}
	count := float64(len(samples))
	recallAt1 := float64(hit1) / count
	recallAt3 := float64(hit3) / count
	recallAt5 := float64(hit5) / count
	mrr := reciprocalRank / count
	return ConceptRetrievalEvaluationMetrics{
		RecallAt1: &recallAt1, RecallAt3: &recallAt3, RecallAt5: &recallAt5, MRR: &mrr,
	}
}
