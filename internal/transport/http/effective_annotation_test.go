package http

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

type fakeEffectiveAnnotationInspector struct {
	getItem   *application.EffectiveAnnotationItem
	getErr    error
	listItems []application.EffectiveAnnotationItem
	listErr   error
}

func (f *fakeEffectiveAnnotationInspector) GetEffectiveAnnotation(context.Context, int64) (*application.EffectiveAnnotationItem, error) {
	return f.getItem, f.getErr
}

func (f *fakeEffectiveAnnotationInspector) ListEffectiveAnnotations(context.Context) ([]application.EffectiveAnnotationItem, error) {
	return f.listItems, f.listErr
}

func effectiveAnnotationServer(svc EffectiveAnnotationInspectorService) http.Handler {
	return NewHandler(&fakeService{}, nil, nil, nil, nil, nil, nil, nil, svc).Routes()
}

func effectiveAnnotationTestItem(status domain.EffectiveAnnotationStatus) application.EffectiveAnnotationItem {
	createdAt := time.Date(2026, time.January, 1, 2, 3, 4, 0, time.UTC)
	return application.EffectiveAnnotationItem{
		Unit: domain.KnowledgeUnit{
			ID: 101, ExtractionID: 9, Ordinal: 1, Kind: domain.KindGrammar,
			Canonical: "conditionnel présent", Statement: "Used for polite requests.",
			Confidence: 0.91, CreatedAt: createdAt,
		},
		Snapshot: domain.EffectiveAnnotationSnapshot{
			UnitID: 101, Status: status,
			Distinctions: []domain.UnitConceptDistinction{},
			Relations:    []domain.UnitConceptLink{},
		},
	}
}

func TestHandleGetEffectiveAnnotationSerializesResolvedProvenance(t *testing.T) {
	item := effectiveAnnotationTestItem(domain.EffectiveAnnotationResolved)
	createdAt := item.Unit.CreatedAt
	membership := domain.CurrentConceptMembership{UnitID: 101, ConceptID: 20, LinkID: 501, UpdatedAt: createdAt}
	decision := domain.UnitConceptLink{
		ID: 501, UnitID: 101, ConceptID: 20, Relation: domain.RelationSame,
		Status: domain.LinkAccepted, DecisionSource: domain.SourceResolverAutomatic,
		ResolverVersion: domain.ConceptResolverVersion, Evidence: `{"reason":"exact"}`, CreatedAt: createdAt,
	}
	item.Snapshot.CurrentSame = &domain.EffectiveSame{Membership: membership, Decision: decision}
	srv := effectiveAnnotationServer(&fakeEffectiveAnnotationInspector{getItem: &item})

	req := httptest.NewRequest(http.MethodGet, "/knowledge-units/101/effective-annotation", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body=%s", rec.Code, rec.Body.String())
	}
	var body effectiveAnnotationItemResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body.Unit.ID != 101 || body.Unit.Canonical != "conditionnel présent" {
		t.Fatalf("unit not serialized: %+v", body.Unit)
	}
	if body.Snapshot.Status != "resolved" || body.Snapshot.CurrentSame == nil {
		t.Fatalf("resolved snapshot not serialized: %+v", body.Snapshot)
	}
	if body.Snapshot.CurrentSame.Decision.ID != 501 || body.Snapshot.CurrentSame.Decision.DecisionSource != "resolver:automatic" {
		t.Fatalf("SAME provenance not serialized: %+v", body.Snapshot.CurrentSame)
	}
}

func TestHandleGetEffectiveAnnotationUnknownUnit(t *testing.T) {
	srv := effectiveAnnotationServer(&fakeEffectiveAnnotationInspector{getErr: domain.ErrNotFound})
	req := httptest.NewRequest(http.MethodGet, "/knowledge-units/999/effective-annotation", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}

func TestHandleListEffectiveAnnotationsSerializesAllStatusesAndEvidence(t *testing.T) {
	createdAt := time.Date(2026, time.January, 1, 2, 3, 4, 0, time.UTC)
	unresolved := effectiveAnnotationTestItem(domain.EffectiveAnnotationUnresolved)
	unresolved.Snapshot.Distinctions = []domain.UnitConceptDistinction{{
		ID: 601, UnitID: 101, ConceptID: 30, DecisionSource: domain.SourceHuman,
		ResolverVersion: domain.ConceptResolverVersion, Evidence: `{"reason":"distinct"}`, CreatedAt: createdAt,
	}}
	unresolved.Snapshot.Relations = []domain.UnitConceptLink{{
		ID: 701, UnitID: 101, ConceptID: 40, Relation: domain.RelationRelated,
		Status: domain.LinkAccepted, DecisionSource: domain.SourceHuman,
		ResolverVersion: domain.ConceptResolverVersion, Evidence: `{"reason":"relation"}`, CreatedAt: createdAt,
	}}
	invalid := effectiveAnnotationTestItem(domain.EffectiveAnnotationInvalid)
	invalid.Unit.ID = 102
	invalid.Snapshot.UnitID = 102
	invalid.Snapshot.LatestUnitJudgment = &domain.UnitResolutionJudgment{
		ID: 801, UnitID: 102, Judgment: domain.UnitInvalid, DecisionSource: domain.SourceHuman,
		Note: "bad extraction", Evidence: "{}", CreatedAt: createdAt,
	}

	srv := effectiveAnnotationServer(&fakeEffectiveAnnotationInspector{listItems: []application.EffectiveAnnotationItem{unresolved, invalid}})
	req := httptest.NewRequest(http.MethodGet, "/effective-annotations", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body=%s", rec.Code, rec.Body.String())
	}
	var body struct {
		Items []effectiveAnnotationItemResponse `json:"effective_annotations"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(body.Items) != 2 || body.Items[0].Snapshot.Status != "unresolved" || body.Items[1].Snapshot.Status != "invalid" {
		t.Fatalf("statuses not serialized: %+v", body.Items)
	}
	if len(body.Items[0].Snapshot.Distinctions) != 1 || len(body.Items[0].Snapshot.Relations) != 1 {
		t.Fatalf("DISTINCT/relation evidence missing: %+v", body.Items[0].Snapshot)
	}
	if body.Items[1].Snapshot.LatestUnitJudgment == nil || body.Items[1].Snapshot.LatestUnitJudgment.Note != "bad extraction" {
		t.Fatalf("INVALID provenance missing: %+v", body.Items[1].Snapshot)
	}
}

func TestEffectiveAnnotationProjectionErrorsSurfaceAsServerErrors(t *testing.T) {
	for _, path := range []string{"/knowledge-units/101/effective-annotation", "/effective-annotations"} {
		t.Run(path, func(t *testing.T) {
			svc := &fakeEffectiveAnnotationInspector{
				getErr:  domain.ErrEffectiveAnnotationCorrupt,
				listErr: domain.ErrEffectiveAnnotationCorrupt,
			}
			srv := effectiveAnnotationServer(svc)
			req := httptest.NewRequest(http.MethodGet, path, nil)
			rec := httptest.NewRecorder()
			srv.ServeHTTP(rec, req)
			if rec.Code != http.StatusInternalServerError || !strings.Contains(rec.Body.String(), "internally inconsistent") {
				t.Fatalf("status/body = %d %q", rec.Code, rec.Body.String())
			}
		})
	}
}

func TestEffectiveAnnotationGenericErrorsRemainServerErrors(t *testing.T) {
	srv := effectiveAnnotationServer(&fakeEffectiveAnnotationInspector{listErr: errors.New("storage unavailable")})
	req := httptest.NewRequest(http.MethodGet, "/effective-annotations", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want 500", rec.Code)
	}
}
