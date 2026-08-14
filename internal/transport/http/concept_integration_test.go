package http_test

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

// setupConceptServer wires a full stack (real repositories, real services) with a
// deterministic in-memory extractor so the HTTP -> service -> resolver -> storage
// path is exercised end to end.
func setupConceptServer(t *testing.T, units []domain.ExtractedUnit) (*httptest.Server, int64) {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "concept_it.db")
	db, err := sqlite.Open(dbPath)
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	t.Cleanup(func() { db.Close() })

	entryRepo := sqlite.NewEntryRepository(db)
	analysisRepo := sqlite.NewAnalysisRepository(db)
	feedbackRepo := sqlite.NewFeedbackRepository(db)
	inventoryRepo := sqlite.NewInventoryRepository(db)
	captureRepo := sqlite.NewCaptureRepository(db)
	knowledgeRepo := sqlite.NewKnowledgeRepository(db)
	admissionRepo := sqlite.NewAdmissionRepository(db)
	conceptRepo := sqlite.NewConceptRepository(db)

	ex := &stubExtractor{units: units}

	entrySvc := application.NewEntryService(entryRepo)
	analysisSvc := application.NewAnalysisService(entryRepo, analysisRepo, nil)
	feedbackSvc := application.NewFeedbackService(feedbackRepo)
	effectiveSvc := application.NewEffectiveAnalysisService(analysisRepo, feedbackRepo)
	inventorySvc := application.NewInventoryService(inventoryRepo)
	captureSvc := application.NewCaptureService(captureRepo)
	knowledgeSvc := application.NewKnowledgeService(entryRepo, analysisRepo, feedbackRepo, knowledgeRepo, admissionRepo, ex)
	conceptSvc := application.NewConceptService(knowledgeRepo, conceptRepo, conceptRepo)

	handler := transporthttp.NewHandler(entrySvc, analysisSvc, feedbackSvc, effectiveSvc, inventorySvc, captureSvc, knowledgeSvc, conceptSvc)
	srv := httptest.NewServer(handler.Routes())
	t.Cleanup(srv.Close)

	// Seed an eligible entry with an accepted analysis.
	ctx := context.Background()
	entry, err := entryRepo.Create(ctx, domain.NewEntryInput{OriginalInput: "Je veux aller au marché"})
	if err != nil {
		t.Fatalf("create entry: %v", err)
	}
	if _, err := analysisRepo.Create(ctx, entry.ID, domain.AnalysisResult{
		Category: "grammar", Explanation: "vouloir + infinitive", Confidence: 0.8,
	}, "rule-based:test"); err != nil {
		t.Fatalf("create analysis: %v", err)
	}
	return srv, entry.ID
}

// extractUnits POSTs an extraction and returns the created unit ids in order.
func extractUnits(t *testing.T, srv *httptest.Server, entryID int64) []int64 {
	t.Helper()
	resp, err := http.Post(srv.URL+"/entries/"+itoa(entryID)+"/extractions", "application/json", nil)
	if err != nil {
		t.Fatalf("POST extractions: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("extraction status = %d, want 201", resp.StatusCode)
	}
	var extraction struct {
		Units []struct {
			ID int64 `json:"id"`
		} `json:"units"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&extraction); err != nil {
		t.Fatalf("decode extraction: %v", err)
	}
	ids := make([]int64, 0, len(extraction.Units))
	for _, u := range extraction.Units {
		ids = append(ids, u.ID)
	}
	return ids
}

func TestIntegration_ConceptCreateResolveSameAndPreferred(t *testing.T) {
	srv, entryID := setupConceptServer(t, []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "vouloir + inf", Statement: "wording A", Confidence: 0.9},
	})
	units := extractUnits(t, srv, entryID)
	unitID := units[0]

	// The unit is reviewable (no SAME membership yet).
	revResp, err := http.Get(srv.URL + "/reviewable-units?entry_id=" + itoa(entryID))
	if err != nil {
		t.Fatalf("GET reviewable: %v", err)
	}
	var reviewable struct {
		Units []struct {
			UnitID    int64  `json:"unit_id"`
			Signature string `json:"signature"`
		} `json:"reviewable_units"`
	}
	json.NewDecoder(revResp.Body).Decode(&reviewable)
	revResp.Body.Close()
	if len(reviewable.Units) != 1 || reviewable.Units[0].UnitID != unitID {
		t.Fatalf("expected unit %d reviewable, got %+v", unitID, reviewable.Units)
	}

	// Create a concept from an explicit identity.
	createBody := `{"identity":{"target":"vouloir + infinitive","pedagogical_intent":"grammar"}}`
	cResp, err := http.Post(srv.URL+"/concepts", "application/json", bytes.NewReader([]byte(createBody)))
	if err != nil {
		t.Fatalf("POST concept: %v", err)
	}
	if cResp.StatusCode != http.StatusCreated {
		t.Fatalf("concept status = %d, want 201", cResp.StatusCode)
	}
	var created struct {
		Concept struct {
			ID    int64  `json:"id"`
			State string `json:"state"`
		} `json:"concept"`
	}
	json.NewDecoder(cResp.Body).Decode(&created)
	cResp.Body.Close()
	conceptID := created.Concept.ID

	// Resolve the unit SAME to the concept.
	sameBody := `{"concept_id":` + itoa(conceptID) + `}`
	sResp, err := http.Post(srv.URL+"/knowledge-units/"+itoa(unitID)+"/concept-links/same", "application/json", bytes.NewReader([]byte(sameBody)))
	if err != nil {
		t.Fatalf("POST same: %v", err)
	}
	if sResp.StatusCode != http.StatusCreated {
		t.Fatalf("same status = %d, want 201", sResp.StatusCode)
	}
	sResp.Body.Close()

	// The concept must NOT have a preferred unit just because of the SAME link.
	gResp, err := http.Get(srv.URL + "/concepts/" + itoa(conceptID))
	if err != nil {
		t.Fatalf("GET concept: %v", err)
	}
	var view struct {
		Concept struct {
			PreferredUnitID *int64 `json:"preferred_unit_id"`
		} `json:"concept"`
		Links []struct {
			Relation string `json:"relation"`
			Status   string `json:"status"`
		} `json:"links"`
	}
	json.NewDecoder(gResp.Body).Decode(&view)
	gResp.Body.Close()
	if view.Concept.PreferredUnitID != nil {
		t.Fatalf("SAME must not auto-set preferred unit")
	}
	if len(view.Links) != 1 || view.Links[0].Relation != "same" || view.Links[0].Status != "accepted" {
		t.Fatalf("expected one accepted SAME link, got %+v", view.Links)
	}

	// Now explicitly set the preferred unit.
	pfBody := `{"unit_id":` + itoa(unitID) + `}`
	pResp, err := http.Post(srv.URL+"/concepts/"+itoa(conceptID)+"/preferred-unit", "application/json", bytes.NewReader([]byte(pfBody)))
	if err != nil {
		t.Fatalf("POST preferred: %v", err)
	}
	if pResp.StatusCode != http.StatusOK {
		t.Fatalf("preferred status = %d, want 200", pResp.StatusCode)
	}
	var pref struct {
		PreferredUnitID *int64 `json:"preferred_unit_id"`
	}
	json.NewDecoder(pResp.Body).Decode(&pref)
	pResp.Body.Close()
	if pref.PreferredUnitID == nil || *pref.PreferredUnitID != unitID {
		t.Fatalf("preferred unit not set, got %v", pref.PreferredUnitID)
	}
}

func TestIntegration_ConceptSecondSameConflicts(t *testing.T) {
	srv, entryID := setupConceptServer(t, []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "x", Statement: "s", Confidence: 0.9},
	})
	unitID := extractUnits(t, srv, entryID)[0]

	mkConcept := func(target string) int64 {
		body := `{"identity":{"target":"` + target + `","pedagogical_intent":"grammar"}}`
		resp, err := http.Post(srv.URL+"/concepts", "application/json", bytes.NewReader([]byte(body)))
		if err != nil {
			t.Fatalf("POST concept: %v", err)
		}
		defer resp.Body.Close()
		var created struct {
			Concept struct {
				ID int64 `json:"id"`
			} `json:"concept"`
		}
		json.NewDecoder(resp.Body).Decode(&created)
		return created.Concept.ID
	}
	c1 := mkConcept("alpha")
	c2 := mkConcept("beta")

	same := func(conceptID int64) int {
		body := `{"concept_id":` + itoa(conceptID) + `}`
		resp, err := http.Post(srv.URL+"/knowledge-units/"+itoa(unitID)+"/concept-links/same", "application/json", bytes.NewReader([]byte(body)))
		if err != nil {
			t.Fatalf("POST same: %v", err)
		}
		defer resp.Body.Close()
		return resp.StatusCode
	}

	if code := same(c1); code != http.StatusCreated {
		t.Fatalf("first SAME status = %d, want 201", code)
	}
	if code := same(c2); code != http.StatusConflict {
		t.Fatalf("second SAME to another concept status = %d, want 409", code)
	}
}

// TestIntegration_ReassignSameCorrectsMembership drives the human-correction
// endpoint end to end: a unit wrongly resolved SAME to concept A is moved to
// concept B via PUT /knowledge-units/{id}/concept-membership. The move must
// succeed (not 409) even though a prior SAME exists, the new link must supersede
// the old one, B must gain support, and A must lose it while keeping the original
// decision as queryable history.
func TestIntegration_ReassignSameCorrectsMembership(t *testing.T) {
	srv, entryID := setupConceptServer(t, []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "x", Statement: "s", Confidence: 0.9},
	})
	unitID := extractUnits(t, srv, entryID)[0]

	mkConcept := func(target string) int64 {
		body := `{"identity":{"target":"` + target + `","pedagogical_intent":"grammar"}}`
		resp, err := http.Post(srv.URL+"/concepts", "application/json", bytes.NewReader([]byte(body)))
		if err != nil {
			t.Fatalf("POST concept: %v", err)
		}
		defer resp.Body.Close()
		var created struct {
			Concept struct {
				ID int64 `json:"id"`
			} `json:"concept"`
		}
		json.NewDecoder(resp.Body).Decode(&created)
		return created.Concept.ID
	}
	conceptA := mkConcept("alpha")
	conceptB := mkConcept("beta")

	// Wrongly resolve the unit SAME to A.
	sameBody := `{"concept_id":` + itoa(conceptA) + `}`
	sResp, err := http.Post(srv.URL+"/knowledge-units/"+itoa(unitID)+"/concept-links/same", "application/json", bytes.NewReader([]byte(sameBody)))
	if err != nil {
		t.Fatalf("POST same: %v", err)
	}
	if sResp.StatusCode != http.StatusCreated {
		t.Fatalf("same status = %d, want 201", sResp.StatusCode)
	}
	var firstLink struct {
		ID int64 `json:"id"`
	}
	json.NewDecoder(sResp.Body).Decode(&firstLink)
	sResp.Body.Close()

	// Human correction: move the membership to B. This must succeed with 200 even
	// though a prior SAME exists.
	body := `{"concept_id":` + itoa(conceptB) + `}`
	req, _ := http.NewRequest(http.MethodPut, srv.URL+"/knowledge-units/"+itoa(unitID)+"/concept-membership", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("PUT concept-membership: %v", err)
	}
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("reassign status = %d, want 200", resp.StatusCode)
	}
	var moved struct {
		ConceptID        int64  `json:"concept_id"`
		Relation         string `json:"relation"`
		Status           string `json:"status"`
		SupersedesLinkID *int64 `json:"supersedes_link_id"`
	}
	json.NewDecoder(resp.Body).Decode(&moved)
	resp.Body.Close()
	if moved.ConceptID != conceptB || moved.Relation != "same" || moved.Status != "accepted" {
		t.Fatalf("moved link should be an accepted SAME to B, got %+v", moved)
	}
	if moved.SupersedesLinkID == nil || *moved.SupersedesLinkID != firstLink.ID {
		t.Fatalf("moved link must supersede the original link %d, got %v", firstLink.ID, moved.SupersedesLinkID)
	}

	// B is now the current membership; A retains the original decision as history.
	assertConceptState := func(conceptID int64, wantState string, wantLinks int) {
		gResp, err := http.Get(srv.URL + "/concepts/" + itoa(conceptID))
		if err != nil {
			t.Fatalf("GET concept %d: %v", conceptID, err)
		}
		defer gResp.Body.Close()
		var view struct {
			Concept struct {
				State string `json:"state"`
			} `json:"concept"`
			Links []struct {
				Status string `json:"status"`
			} `json:"links"`
		}
		json.NewDecoder(gResp.Body).Decode(&view)
		if view.Concept.State != wantState {
			t.Fatalf("concept %d state = %q, want %q", conceptID, view.Concept.State, wantState)
		}
		if len(view.Links) != wantLinks {
			t.Fatalf("concept %d links = %d, want %d", conceptID, len(view.Links), wantLinks)
		}
	}
	// B is supported (active) with its accepted SAME event; A is orphaned but keeps
	// the historical decision queryable.
	assertConceptState(conceptB, "active", 1)
	assertConceptState(conceptA, "orphaned", 1)
}

func TestIntegration_ConceptDuplicateActiveIdentityConflicts(t *testing.T) {
	srv, _ := setupConceptServer(t, nil)
	body := `{"identity":{"target":"vouloir","pedagogical_intent":"grammar"}}`

	first, err := http.Post(srv.URL+"/concepts", "application/json", bytes.NewReader([]byte(body)))
	if err != nil {
		t.Fatalf("first: %v", err)
	}
	if first.StatusCode != http.StatusCreated {
		t.Fatalf("first status = %d, want 201", first.StatusCode)
	}
	first.Body.Close()

	second, err := http.Post(srv.URL+"/concepts", "application/json", bytes.NewReader([]byte(body)))
	if err != nil {
		t.Fatalf("second: %v", err)
	}
	defer second.Body.Close()
	if second.StatusCode != http.StatusConflict {
		t.Fatalf("duplicate active identity status = %d, want 409", second.StatusCode)
	}
}

func TestIntegration_ConceptResolveEndpointDeterministic(t *testing.T) {
	srv, entryID := setupConceptServer(t, []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "aller au futur", Statement: "s", Confidence: 0.9},
	})
	unitID := extractUnits(t, srv, entryID)[0]

	// With no concepts, the resolver reports no_match and records nothing.
	resp, err := http.Get(srv.URL + "/knowledge-units/" + itoa(unitID) + "/concept-resolution")
	if err != nil {
		t.Fatalf("GET resolution: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("resolution status = %d, want 200", resp.StatusCode)
	}
	var outcome struct {
		Decision string `json:"decision"`
		Matches  []any  `json:"matches"`
	}
	json.NewDecoder(resp.Body).Decode(&outcome)
	if outcome.Decision != "no_match" {
		t.Fatalf("decision = %q, want no_match", outcome.Decision)
	}
	if len(outcome.Matches) != 0 {
		t.Fatalf("expected no matches, got %d", len(outcome.Matches))
	}
}

func TestIntegration_CurrentExtractionRollback(t *testing.T) {
	srv, entryID := setupConceptServer(t, []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "v", Statement: "s", Confidence: 0.9},
	})
	// First extraction.
	extractUnits(t, srv, entryID)
	firstCurrent := getCurrentExtraction(t, srv, entryID)

	// Second extraction becomes current.
	extractUnits(t, srv, entryID)
	secondCurrent := getCurrentExtraction(t, srv, entryID)
	if secondCurrent == firstCurrent {
		t.Fatalf("second extraction should have become current")
	}

	// Roll back to the first extraction.
	body := `{"extraction_id":` + itoa(firstCurrent) + `}`
	req, _ := http.NewRequest(http.MethodPut, srv.URL+"/entries/"+itoa(entryID)+"/current-extraction", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("PUT current: %v", err)
	}
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("rollback status = %d, want 200", resp.StatusCode)
	}
	resp.Body.Close()

	if got := getCurrentExtraction(t, srv, entryID); got != firstCurrent {
		t.Fatalf("after rollback current = %d, want %d", got, firstCurrent)
	}
}

func getCurrentExtraction(t *testing.T, srv *httptest.Server, entryID int64) int64 {
	t.Helper()
	resp, err := http.Get(srv.URL + "/entries/" + itoa(entryID) + "/current-extraction")
	if err != nil {
		t.Fatalf("GET current: %v", err)
	}
	defer resp.Body.Close()
	var body struct {
		CurrentExtractionID *int64 `json:"current_extraction_id"`
	}
	json.NewDecoder(resp.Body).Decode(&body)
	if body.CurrentExtractionID == nil {
		t.Fatalf("expected a current extraction id")
	}
	return *body.CurrentExtractionID
}
