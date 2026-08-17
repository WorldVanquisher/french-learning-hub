package application

import (
	"context"
	"errors"
	"testing"
	"time"

	"french-learning-app/internal/domain"
)

type fakeDatasetEffectiveReader struct {
	items []EffectiveAnnotationItem
	err   error
}

func (f *fakeDatasetEffectiveReader) ListEffectiveAnnotations(context.Context) ([]EffectiveAnnotationItem, error) {
	return f.items, f.err
}

type fakeDatasetExtractionReader struct {
	views map[int64]*domain.ExtractionView
	calls map[int64]int
	err   error
}

func (f *fakeDatasetExtractionReader) GetByID(_ context.Context, extractionID int64) (*domain.ExtractionView, error) {
	if f.calls == nil {
		f.calls = make(map[int64]int)
	}
	f.calls[extractionID]++
	if f.err != nil {
		return nil, f.err
	}
	view, ok := f.views[extractionID]
	if !ok {
		return nil, domain.ErrNotFound
	}
	return view, nil
}

type fakeDatasetConceptReader struct {
	views map[int64]*domain.ConceptView
	calls map[int64]int
	err   error
}

func (f *fakeDatasetConceptReader) GetConcept(_ context.Context, conceptID int64) (*domain.ConceptView, error) {
	if f.calls == nil {
		f.calls = make(map[int64]int)
	}
	f.calls[conceptID]++
	if f.err != nil {
		return nil, f.err
	}
	view, ok := f.views[conceptID]
	if !ok {
		return nil, domain.ErrNotFound
	}
	return view, nil
}

func datasetTestTime(minute int) time.Time {
	return time.Date(2026, time.January, 2, 3, minute, 0, 0, time.UTC)
}

func datasetSame(unitID, conceptID, eventID int64, source domain.DecisionSource) *domain.EffectiveSame {
	createdAt := datasetTestTime(int(eventID))
	return &domain.EffectiveSame{
		Membership: domain.CurrentConceptMembership{
			UnitID: unitID, ConceptID: conceptID, LinkID: eventID, UpdatedAt: createdAt,
		},
		Decision: domain.UnitConceptLink{
			ID: eventID, UnitID: unitID, ConceptID: conceptID, Relation: domain.RelationSame,
			Status: domain.LinkAccepted, DecisionSource: source,
			ResolverVersion: domain.ConceptResolverVersion, CreatedAt: createdAt,
		},
	}
}

func TestProjectHumanAnnotationLabels_HumanCurrentSameIsTheOnlySameLabel(t *testing.T) {
	snapshot := domain.EffectiveAnnotationSnapshot{
		UnitID: 7, Status: domain.EffectiveAnnotationResolved,
		CurrentSame: datasetSame(7, 42, 11, domain.SourceHuman),
	}
	labels := ProjectHumanAnnotationLabels(snapshot)
	if labels.Same == nil || labels.Same.ConceptID != 42 || labels.Same.EventID != 11 {
		t.Fatalf("human SAME label = %+v", labels.Same)
	}
	if labels.Invalid != nil || len(labels.Distinctions) != 0 || len(labels.Relations) != 0 {
		t.Fatalf("unexpected extra labels: %+v", labels)
	}
	// A human create-and-seed action needs no separate NEW label: its effective
	// human SAME is represented by the same projection above.
}

func TestProjectHumanAnnotationLabels_AutomaticResolvedSameIsNotHumanGold(t *testing.T) {
	snapshot := domain.EffectiveAnnotationSnapshot{
		UnitID: 7, Status: domain.EffectiveAnnotationResolved,
		CurrentSame: datasetSame(7, 42, 11, domain.SourceResolverAutomatic),
	}
	labels := ProjectHumanAnnotationLabels(snapshot)
	if labels.Same != nil {
		t.Fatalf("automatic SAME promoted to human label: %+v", labels.Same)
	}
}

func TestProjectHumanAnnotationLabels_DistinctRequiresExplicitEffectiveHumanSource(t *testing.T) {
	snapshot := domain.EffectiveAnnotationSnapshot{
		UnitID: 7, Status: domain.EffectiveAnnotationUnresolved,
		Distinctions: []domain.UnitConceptDistinction{
			{ID: 21, UnitID: 7, ConceptID: 50, DecisionSource: domain.SourceHuman, ResolverVersion: "v1", CreatedAt: datasetTestTime(21)},
			{ID: 22, UnitID: 7, ConceptID: 51, DecisionSource: domain.SourceResolverAutomatic, ResolverVersion: "v1", CreatedAt: datasetTestTime(22)},
		},
	}
	labels := ProjectHumanAnnotationLabels(snapshot)
	if len(labels.Distinctions) != 1 || labels.Distinctions[0].ConceptID != 50 || labels.Distinctions[0].DistinctionEventID != 21 {
		t.Fatalf("DISTINCT labels = %+v", labels.Distinctions)
	}
	if labels.Same != nil || labels.Invalid != nil {
		t.Fatalf("DISTINCT manufactured another label: %+v", labels)
	}
}

func TestProjectHumanAnnotationLabels_PreservesEachHumanRelationWithoutDistinct(t *testing.T) {
	relations := []domain.UnitConceptLink{
		{ID: 31, UnitID: 7, ConceptID: 61, Relation: domain.RelationBroader, DecisionSource: domain.SourceHuman},
		{ID: 32, UnitID: 7, ConceptID: 62, Relation: domain.RelationNarrower, DecisionSource: domain.SourceHuman},
		{ID: 33, UnitID: 7, ConceptID: 63, Relation: domain.RelationRelated, DecisionSource: domain.SourceHuman},
		{ID: 34, UnitID: 7, ConceptID: 64, Relation: domain.RelationRelated, DecisionSource: domain.SourceResolverAutomatic},
	}
	labels := ProjectHumanAnnotationLabels(domain.EffectiveAnnotationSnapshot{
		UnitID: 7, Status: domain.EffectiveAnnotationUnresolved, Relations: relations,
	})
	if len(labels.Relations) != 3 {
		t.Fatalf("relation labels = %+v", labels.Relations)
	}
	want := []domain.ConceptRelation{domain.RelationBroader, domain.RelationNarrower, domain.RelationRelated}
	for i, relation := range want {
		if labels.Relations[i].Relation != relation {
			t.Fatalf("relations[%d] = %q, want %q", i, labels.Relations[i].Relation, relation)
		}
	}
	if len(labels.Distinctions) != 0 {
		t.Fatalf("relations became DISTINCT: %+v", labels.Distinctions)
	}
}

func TestProjectHumanAnnotationLabels_HumanInvalidSuppressesAllPairLabels(t *testing.T) {
	judgment := &domain.UnitResolutionJudgment{
		ID: 41, UnitID: 7, Judgment: domain.UnitInvalid, DecisionSource: domain.SourceHuman,
		Note: "not a learning unit", Evidence: `{"reason":"fragment"}`, CreatedAt: datasetTestTime(41),
	}
	snapshot := domain.EffectiveAnnotationSnapshot{
		UnitID: 7, Status: domain.EffectiveAnnotationInvalid, LatestUnitJudgment: judgment,
		// These pair fields deliberately make the test fail if projection code can
		// resurrect pair labels for an invalid record.
		CurrentSame:  datasetSame(7, 42, 11, domain.SourceHuman),
		Distinctions: []domain.UnitConceptDistinction{{ID: 21, UnitID: 7, ConceptID: 50, DecisionSource: domain.SourceHuman}},
		Relations:    []domain.UnitConceptLink{{ID: 31, UnitID: 7, ConceptID: 61, Relation: domain.RelationBroader, DecisionSource: domain.SourceHuman}},
	}
	labels := ProjectHumanAnnotationLabels(snapshot)
	if labels.Invalid == nil || labels.Invalid.JudgmentID != 41 || labels.Invalid.Note != "not a learning unit" {
		t.Fatalf("invalid label = %+v", labels.Invalid)
	}
	if labels.Same != nil || len(labels.Distinctions) != 0 || len(labels.Relations) != 0 {
		t.Fatalf("invalid record resurrected pair labels: %+v", labels)
	}
}

func TestProjectHumanAnnotationLabels_RestoredUnresolvedAndRejectSameStayUnlabeled(t *testing.T) {
	restored := &domain.UnitResolutionJudgment{
		ID: 51, UnitID: 7, Judgment: domain.UnitRestored, DecisionSource: domain.SourceHuman,
	}
	for _, tc := range []struct {
		name     string
		snapshot domain.EffectiveAnnotationSnapshot
	}{
		{name: "restored", snapshot: domain.EffectiveAnnotationSnapshot{UnitID: 7, Status: domain.EffectiveAnnotationUnresolved, LatestUnitJudgment: restored}},
		{name: "unresolved", snapshot: domain.EffectiveAnnotationSnapshot{UnitID: 7, Status: domain.EffectiveAnnotationUnresolved}},
		// RejectSame is history and therefore absent from an effective snapshot; it
		// must not be transformed into DISTINCT by this consumer.
		{name: "reject_same_history", snapshot: domain.EffectiveAnnotationSnapshot{UnitID: 7, Status: domain.EffectiveAnnotationUnresolved}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			labels := ProjectHumanAnnotationLabels(tc.snapshot)
			if labels.Same != nil || labels.Invalid != nil || len(labels.Distinctions) != 0 || len(labels.Relations) != 0 {
				t.Fatalf("unexpected labels: %+v", labels)
			}
		})
	}
}

func TestConceptAnnotationDatasetService_ComposesCachesAndSortsDeterministically(t *testing.T) {
	admission := domain.ResolveAdmission(domain.AdmissionRecommendation{
		Ruleset: domain.AdmissionRulesetName, State: domain.AdmissionActive, Reason: domain.ReasonDefaultActive,
	}, nil)
	unit1 := domain.KnowledgeUnit{ID: 1, ExtractionID: 10, Ordinal: 1, Kind: domain.KindGrammar, Canonical: "one"}
	unit3 := domain.KnowledgeUnit{ID: 3, ExtractionID: 20, Ordinal: 1, Kind: domain.KindVocabulary, Canonical: "three"}
	unit4 := domain.KnowledgeUnit{ID: 4, ExtractionID: 20, Ordinal: 2, Kind: domain.KindVocabulary, Canonical: "four"}

	effective := &fakeDatasetEffectiveReader{items: []EffectiveAnnotationItem{
		{Unit: unit1, Snapshot: domain.EffectiveAnnotationSnapshot{
			UnitID: 1, Status: domain.EffectiveAnnotationResolved,
			CurrentSame:  datasetSame(1, 100, 13, domain.SourceHuman),
			Distinctions: []domain.UnitConceptDistinction{{ID: 21, UnitID: 1, ConceptID: 102, DecisionSource: domain.SourceHuman}},
		}},
		{Unit: unit4, Snapshot: domain.EffectiveAnnotationSnapshot{
			UnitID: 4, Status: domain.EffectiveAnnotationResolved,
			CurrentSame: datasetSame(4, 100, 14, domain.SourceHuman),
		}},
		{Unit: unit3, Snapshot: domain.EffectiveAnnotationSnapshot{
			UnitID: 3, Status: domain.EffectiveAnnotationUnresolved,
			Relations: []domain.UnitConceptLink{{ID: 31, UnitID: 3, ConceptID: 101, Relation: domain.RelationRelated, DecisionSource: domain.SourceHuman}},
		}},
	}}
	extractions := &fakeDatasetExtractionReader{views: map[int64]*domain.ExtractionView{
		10: {
			Extraction: domain.KnowledgeExtraction{ID: 10, EntryID: 2, Version: 1, SourceAnalysisID: 201, Extractor: "extractor:v1", CreatedAt: datasetTestTime(1)},
			Units:      []domain.KnowledgeUnitView{{Unit: unit1, Admission: admission}},
		},
		20: {
			Extraction: domain.KnowledgeExtraction{ID: 20, EntryID: 1, Version: 2, SourceAnalysisID: 202, Extractor: "extractor:v1", CreatedAt: datasetTestTime(2)},
			Units: []domain.KnowledgeUnitView{
				{Unit: unit3, Admission: admission}, {Unit: unit4, Admission: admission},
			},
		},
	}}
	concepts := &fakeDatasetConceptReader{views: map[int64]*domain.ConceptView{
		100: {Concept: domain.KnowledgeConcept{ID: 100, Target: "shared concept", PedagogicalIntent: "grammar"}},
		101: {Concept: domain.KnowledgeConcept{ID: 101, Target: "related concept", PedagogicalIntent: "vocabulary"}},
		102: {Concept: domain.KnowledgeConcept{ID: 102, Target: "distinct concept", PedagogicalIntent: "grammar"}},
	}}

	records, err := NewConceptAnnotationDatasetService(effective, extractions, concepts).ListV1(context.Background())
	if err != nil {
		t.Fatalf("ListV1: %v", err)
	}
	if len(records) != 3 || records[0].Unit.ID != 3 || records[1].Unit.ID != 4 || records[2].Unit.ID != 1 {
		t.Fatalf("record order = %+v", []int64{records[0].Unit.ID, records[1].Unit.ID, records[2].Unit.ID})
	}
	if records[0].SchemaVersion != ConceptAnnotationDatasetV1SchemaVersion || records[0].Source.EntryID != 1 || records[0].Source.ExtractionVersion != 2 {
		t.Fatalf("schema/source provenance missing: %+v", records[0])
	}
	if records[0].Admission.Effective != domain.AdmissionActive {
		t.Fatalf("admission missing: %+v", records[0].Admission)
	}
	if records[1].EffectiveAnnotation.CurrentSame == nil || records[1].EffectiveAnnotation.CurrentSame.Concept.Target != "shared concept" {
		t.Fatalf("SAME Concept metadata missing: %+v", records[1].EffectiveAnnotation.CurrentSame)
	}
	if records[2].EffectiveAnnotation.CurrentSame == nil || records[2].EffectiveAnnotation.CurrentSame.Concept.ID != 100 {
		t.Fatalf("different unit evidence did not trust CURRENT SAME: %+v", records[2])
	}
	if records[2].EffectiveAnnotation.Distinctions[0].Concept.Target != "distinct concept" || records[0].EffectiveAnnotation.Relations[0].Concept.Target != "related concept" {
		t.Fatalf("DISTINCT/relation Concept metadata missing: %+v %+v", records[2], records[0])
	}
	if extractions.calls[20] != 1 || extractions.calls[10] != 1 {
		t.Fatalf("extraction cache calls = %+v", extractions.calls)
	}
	if concepts.calls[100] != 1 || concepts.calls[101] != 1 || concepts.calls[102] != 1 {
		t.Fatalf("Concept cache calls = %+v", concepts.calls)
	}
}

func TestConceptAnnotationDatasetService_MissingReferencedConceptFailsClosed(t *testing.T) {
	unit := domain.KnowledgeUnit{ID: 7, ExtractionID: 9, Ordinal: 1}
	effective := &fakeDatasetEffectiveReader{items: []EffectiveAnnotationItem{{
		Unit: unit,
		Snapshot: domain.EffectiveAnnotationSnapshot{
			UnitID: 7, Status: domain.EffectiveAnnotationResolved,
			CurrentSame: datasetSame(7, 404, 11, domain.SourceHuman),
		},
	}}}
	extractions := &fakeDatasetExtractionReader{views: map[int64]*domain.ExtractionView{
		9: {Extraction: domain.KnowledgeExtraction{ID: 9}, Units: []domain.KnowledgeUnitView{{Unit: unit}}},
	}}
	_, err := NewConceptAnnotationDatasetService(effective, extractions, &fakeDatasetConceptReader{}).ListV1(context.Background())
	if !errors.Is(err, ErrConceptAnnotationDatasetCorrupt) {
		t.Fatalf("error = %v, want dataset corruption", err)
	}
}

func TestConceptAnnotationDatasetService_PropagatesM11ACorruption(t *testing.T) {
	effective := &fakeDatasetEffectiveReader{err: domain.ErrEffectiveAnnotationCorrupt}
	_, err := NewConceptAnnotationDatasetService(effective, &fakeDatasetExtractionReader{}, &fakeDatasetConceptReader{}).ListV1(context.Background())
	if !errors.Is(err, domain.ErrEffectiveAnnotationCorrupt) {
		t.Fatalf("error = %v, want M11-A corruption", err)
	}
}

func TestConceptAnnotationDatasetService_BrokenExtractionProvenanceFailsClosed(t *testing.T) {
	unit := domain.KnowledgeUnit{ID: 7, ExtractionID: 9}
	effective := &fakeDatasetEffectiveReader{items: []EffectiveAnnotationItem{{
		Unit: unit, Snapshot: domain.EffectiveAnnotationSnapshot{UnitID: 7, Status: domain.EffectiveAnnotationUnresolved},
	}}}
	extractions := &fakeDatasetExtractionReader{views: map[int64]*domain.ExtractionView{
		9: {Extraction: domain.KnowledgeExtraction{ID: 9}, Units: nil},
	}}
	_, err := NewConceptAnnotationDatasetService(effective, extractions, &fakeDatasetConceptReader{}).ListV1(context.Background())
	if !errors.Is(err, ErrConceptAnnotationDatasetCorrupt) {
		t.Fatalf("error = %v, want dataset corruption", err)
	}
}
