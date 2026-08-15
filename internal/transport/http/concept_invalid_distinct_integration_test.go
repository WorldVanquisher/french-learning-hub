package http_test

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"french-learning-app/internal/domain"
)

// mkConceptIT creates a concept over HTTP and returns its id.
func mkConceptIT(t *testing.T, srv *httptest.Server, target string) int64 {
	t.Helper()
	body := `{"identity":{"target":"` + target + `","pedagogical_intent":"grammar"}}`
	resp, err := http.Post(srv.URL+"/concepts", "application/json", bytes.NewReader([]byte(body)))
	if err != nil {
		t.Fatalf("POST concept: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("concept status = %d, want 201", resp.StatusCode)
	}
	var created struct {
		Concept struct {
			ID int64 `json:"id"`
		} `json:"concept"`
	}
	json.NewDecoder(resp.Body).Decode(&created)
	return created.Concept.ID
}

// reviewableUnitIDs returns the entry's reviewable unit ids over HTTP.
func reviewableUnitIDs(t *testing.T, srv *httptest.Server, entryID int64) []int64 {
	t.Helper()
	resp, err := http.Get(srv.URL + "/reviewable-units?entry_id=" + itoa(entryID))
	if err != nil {
		t.Fatalf("GET reviewable: %v", err)
	}
	defer resp.Body.Close()
	var body struct {
		Units []struct {
			UnitID int64 `json:"unit_id"`
		} `json:"reviewable_units"`
	}
	json.NewDecoder(resp.Body).Decode(&body)
	ids := make([]int64, 0, len(body.Units))
	for _, u := range body.Units {
		ids = append(ids, u.UnitID)
	}
	return ids
}

func containsID(ids []int64, id int64) bool {
	for _, x := range ids {
		if x == id {
			return true
		}
	}
	return false
}

// TestIntegration_MarkUnitInvalidUnresolved drives POST /knowledge-units/{id}/invalid
// for a freshly extracted, never-resolved unit (the gap the membership-reject
// endpoint could not cover): the unit must be markable INVALID, the response and the
// GET /invalid read model must report the effective invalid state, and the unit must
// leave the review queue. Restore returns it to the queue. A missing unit is 404.
func TestIntegration_MarkUnitInvalidUnresolved(t *testing.T) {
	srv, entryID := setupConceptServer(t, []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "garbage", Statement: "s", Confidence: 0.9},
	})
	unitID := extractUnits(t, srv, entryID)[0]

	// Precondition: an unresolved unit is reviewable.
	if !containsID(reviewableUnitIDs(t, srv, entryID), unitID) {
		t.Fatal("precondition: unresolved unit must be reviewable")
	}

	// Mark INVALID (no membership exists — this is the new capability).
	iResp, err := http.Post(srv.URL+"/knowledge-units/"+itoa(unitID)+"/invalid", "application/json", nil)
	if err != nil {
		t.Fatalf("POST invalid: %v", err)
	}
	if iResp.StatusCode != http.StatusOK {
		t.Fatalf("invalid status = %d, want 200", iResp.StatusCode)
	}
	var markResp struct {
		UnitID            int64 `json:"unit_id"`
		Invalid           bool  `json:"invalid"`
		CurrentMembership *struct {
			ConceptID int64 `json:"concept_id"`
		} `json:"current_membership"`
		Judgment *struct {
			UnitID         int64  `json:"unit_id"`
			Judgment       string `json:"judgment"`
			DecisionSource string `json:"decision_source"`
		} `json:"judgment"`
	}
	json.NewDecoder(iResp.Body).Decode(&markResp)
	iResp.Body.Close()
	if !markResp.Invalid {
		t.Fatal("response must report the unit is now invalid")
	}
	if markResp.CurrentMembership != nil {
		t.Fatalf("an unresolved unit has no membership to clear, got %+v", markResp.CurrentMembership)
	}
	if markResp.Judgment == nil || markResp.Judgment.Judgment != "invalid" || markResp.Judgment.UnitID != unitID {
		t.Fatalf("response must carry the recorded invalid judgment, got %+v", markResp.Judgment)
	}
	if markResp.Judgment.DecisionSource != "human" {
		t.Fatalf("judgment must be human-sourced, got %q", markResp.Judgment.DecisionSource)
	}

	// GET /invalid read model reports effective invalid + history.
	gResp, err := http.Get(srv.URL + "/knowledge-units/" + itoa(unitID) + "/invalid")
	if err != nil {
		t.Fatalf("GET invalid: %v", err)
	}
	var getResp struct {
		UnitID  int64 `json:"unit_id"`
		Invalid bool  `json:"invalid"`
		History []struct {
			Judgment string `json:"judgment"`
		} `json:"history"`
	}
	json.NewDecoder(gResp.Body).Decode(&getResp)
	gResp.Body.Close()
	if !getResp.Invalid {
		t.Fatal("GET /invalid must report the unit is invalid")
	}
	if len(getResp.History) != 1 || getResp.History[0].Judgment != "invalid" {
		t.Fatalf("GET /invalid history must have the one invalid judgment, got %+v", getResp.History)
	}

	// The unit leaves the review queue.
	if containsID(reviewableUnitIDs(t, srv, entryID), unitID) {
		t.Fatal("an INVALID unit must not be reviewable")
	}

	// Restore returns it to the queue.
	rResp, err := http.Post(srv.URL+"/knowledge-units/"+itoa(unitID)+"/invalid/restore", "application/json", nil)
	if err != nil {
		t.Fatalf("POST restore: %v", err)
	}
	if rResp.StatusCode != http.StatusOK {
		t.Fatalf("restore status = %d, want 200", rResp.StatusCode)
	}
	var restoreResp struct {
		Invalid  bool `json:"invalid"`
		Judgment *struct {
			Judgment string `json:"judgment"`
		} `json:"judgment"`
	}
	json.NewDecoder(rResp.Body).Decode(&restoreResp)
	rResp.Body.Close()
	if restoreResp.Invalid {
		t.Fatal("restore response must report the unit is no longer invalid")
	}
	if restoreResp.Judgment == nil || restoreResp.Judgment.Judgment != "restored" {
		t.Fatalf("restore must return a 'restored' judgment, got %+v", restoreResp.Judgment)
	}
	if !containsID(reviewableUnitIDs(t, srv, entryID), unitID) {
		t.Fatal("a restored unit must be reviewable again")
	}

	// GET /invalid now shows both events, newest-first, and invalid=false.
	gResp2, err := http.Get(srv.URL + "/knowledge-units/" + itoa(unitID) + "/invalid")
	if err != nil {
		t.Fatalf("GET invalid 2: %v", err)
	}
	var getResp2 struct {
		Invalid bool `json:"invalid"`
		History []struct {
			Judgment string `json:"judgment"`
		} `json:"history"`
	}
	json.NewDecoder(gResp2.Body).Decode(&getResp2)
	gResp2.Body.Close()
	if getResp2.Invalid {
		t.Fatal("restored unit must read invalid=false")
	}
	if len(getResp2.History) != 2 || getResp2.History[0].Judgment != "restored" || getResp2.History[1].Judgment != "invalid" {
		t.Fatalf("history must be [restored, invalid] newest-first, got %+v", getResp2.History)
	}

	// Missing unit -> 404 on both write and read endpoints.
	miss, err := http.Post(srv.URL+"/knowledge-units/999999/invalid", "application/json", nil)
	if err != nil {
		t.Fatalf("POST invalid missing: %v", err)
	}
	miss.Body.Close()
	if miss.StatusCode != http.StatusNotFound {
		t.Fatalf("missing unit invalid status = %d, want 404", miss.StatusCode)
	}
	missGet, err := http.Get(srv.URL + "/knowledge-units/999999/invalid")
	if err != nil {
		t.Fatalf("GET invalid missing: %v", err)
	}
	missGet.Body.Close()
	if missGet.StatusCode != http.StatusNotFound {
		t.Fatalf("missing unit GET invalid status = %d, want 404", missGet.StatusCode)
	}
}

// TestIntegration_MarkUnitInvalidClearsSame drives POST
// /knowledge-units/{id}/invalid for a unit that currently has a SAME membership:
// the atomic rule (option A) must clear that membership so the unit is never both
// SAME and INVALID. The response reports invalid=true with a null current membership,
// and the membership read model confirms the clear.
func TestIntegration_MarkUnitInvalidClearsSame(t *testing.T) {
	srv, entryID := setupConceptServer(t, []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "x", Statement: "s", Confidence: 0.9},
	})
	unitID := extractUnits(t, srv, entryID)[0]
	conceptA := mkConceptIT(t, srv, "alpha")

	// Resolve SAME to A.
	sResp, err := http.Post(srv.URL+"/knowledge-units/"+itoa(unitID)+"/concept-links/same", "application/json",
		bytes.NewReader([]byte(`{"concept_id":`+itoa(conceptA)+`}`)))
	if err != nil {
		t.Fatalf("POST same: %v", err)
	}
	sResp.Body.Close()
	if sResp.StatusCode != http.StatusCreated {
		t.Fatalf("same status = %d, want 201", sResp.StatusCode)
	}

	// Mark INVALID: must clear the SAME membership atomically.
	iResp, err := http.Post(srv.URL+"/knowledge-units/"+itoa(unitID)+"/invalid", "application/json", nil)
	if err != nil {
		t.Fatalf("POST invalid: %v", err)
	}
	var markResp struct {
		Invalid           bool `json:"invalid"`
		CurrentMembership *struct {
			ConceptID int64 `json:"concept_id"`
		} `json:"current_membership"`
	}
	json.NewDecoder(iResp.Body).Decode(&markResp)
	iResp.Body.Close()
	if !markResp.Invalid || markResp.CurrentMembership != nil {
		t.Fatalf("INVALID must report invalid with a cleared membership, got %+v", markResp)
	}

	// The membership read model confirms null.
	mResp, err := http.Get(srv.URL + "/knowledge-units/" + itoa(unitID) + "/concept-membership")
	if err != nil {
		t.Fatalf("GET membership: %v", err)
	}
	var membership struct {
		CurrentMembership *struct {
			ConceptID int64 `json:"concept_id"`
		} `json:"current_membership"`
	}
	json.NewDecoder(mResp.Body).Decode(&membership)
	mResp.Body.Close()
	if membership.CurrentMembership != nil {
		t.Fatalf("membership must be null after INVALID cleared SAME, got %+v", membership.CurrentMembership)
	}

	// A drops to orphaned; the unit is not reviewable (it is invalid, not merely
	// unresolved).
	gResp, err := http.Get(srv.URL + "/concepts/" + itoa(conceptA))
	if err != nil {
		t.Fatalf("GET concept A: %v", err)
	}
	var aView struct {
		Concept struct {
			State string `json:"state"`
		} `json:"concept"`
	}
	json.NewDecoder(gResp.Body).Decode(&aView)
	gResp.Body.Close()
	if aView.Concept.State != "orphaned" {
		t.Fatalf("A should be orphaned after its member was invalidated, got %q", aView.Concept.State)
	}
	if containsID(reviewableUnitIDs(t, srv, entryID), unitID) {
		t.Fatal("an INVALID unit must not be reviewable (distinct from a plain reject)")
	}
}

// TestIntegration_RecordDistinctionAndNewConcept drives POST
// /knowledge-units/{id}/concept-distinctions end to end. Recording DISTINCT(U, A)
// must create no membership and keep the unit reviewable; the reviewer can then
// create a NEW concept B and resolve SAME to it. The negative pair (U, A) persists
// alongside the positive membership (U, B), and both are queryable. Errors: a missing
// unit or concept is 404.
func TestIntegration_RecordDistinctionAndNewConcept(t *testing.T) {
	srv, entryID := setupConceptServer(t, []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "x", Statement: "s", Confidence: 0.9},
	})
	unitID := extractUnits(t, srv, entryID)[0]
	conceptA := mkConceptIT(t, srv, "alpha")

	// Record DISTINCT(U, A).
	dResp, err := http.Post(srv.URL+"/knowledge-units/"+itoa(unitID)+"/concept-distinctions", "application/json",
		bytes.NewReader([]byte(`{"concept_id":`+itoa(conceptA)+`}`)))
	if err != nil {
		t.Fatalf("POST distinction: %v", err)
	}
	if dResp.StatusCode != http.StatusCreated {
		t.Fatalf("distinction status = %d, want 201", dResp.StatusCode)
	}
	var dist struct {
		UnitID    int64  `json:"unit_id"`
		ConceptID int64  `json:"concept_id"`
		Source    string `json:"decision_source"`
	}
	json.NewDecoder(dResp.Body).Decode(&dist)
	dResp.Body.Close()
	if dist.UnitID != unitID || dist.ConceptID != conceptA {
		t.Fatalf("distinction must reference U and A, got %+v", dist)
	}
	if dist.Source != "human" {
		t.Fatalf("distinction must be human-sourced, got %q", dist.Source)
	}

	// No membership was created; the unit stays reviewable.
	mResp, err := http.Get(srv.URL + "/knowledge-units/" + itoa(unitID) + "/concept-membership")
	if err != nil {
		t.Fatalf("GET membership: %v", err)
	}
	var membership struct {
		CurrentMembership *struct {
			ConceptID int64 `json:"concept_id"`
		} `json:"current_membership"`
	}
	json.NewDecoder(mResp.Body).Decode(&membership)
	mResp.Body.Close()
	if membership.CurrentMembership != nil {
		t.Fatalf("DISTINCT must not create a membership, got %+v", membership.CurrentMembership)
	}
	if !containsID(reviewableUnitIDs(t, srv, entryID), unitID) {
		t.Fatal("a unit with only a DISTINCT must remain reviewable")
	}

	// Reviewer creates a NEW concept B and resolves SAME to it.
	conceptB := mkConceptIT(t, srv, "beta")
	sResp, err := http.Post(srv.URL+"/knowledge-units/"+itoa(unitID)+"/concept-links/same", "application/json",
		bytes.NewReader([]byte(`{"concept_id":`+itoa(conceptB)+`}`)))
	if err != nil {
		t.Fatalf("POST same to B: %v", err)
	}
	sResp.Body.Close()
	if sResp.StatusCode != http.StatusCreated {
		t.Fatalf("same-to-B status = %d, want 201", sResp.StatusCode)
	}

	// Positive membership is B.
	mResp2, err := http.Get(srv.URL + "/knowledge-units/" + itoa(unitID) + "/concept-membership")
	if err != nil {
		t.Fatalf("GET membership 2: %v", err)
	}
	var membership2 struct {
		CurrentMembership *struct {
			ConceptID int64 `json:"concept_id"`
		} `json:"current_membership"`
	}
	json.NewDecoder(mResp2.Body).Decode(&membership2)
	mResp2.Body.Close()
	if membership2.CurrentMembership == nil || membership2.CurrentMembership.ConceptID != conceptB {
		t.Fatalf("unit must belong SAME to B, got %+v", membership2.CurrentMembership)
	}

	// The negative pair (U, A) persists and is queryable, still referencing A (not B).
	lResp, err := http.Get(srv.URL + "/knowledge-units/" + itoa(unitID) + "/concept-distinctions")
	if err != nil {
		t.Fatalf("GET distinctions: %v", err)
	}
	var list struct {
		Distinctions []struct {
			ConceptID int64 `json:"concept_id"`
		} `json:"distinctions"`
	}
	json.NewDecoder(lResp.Body).Decode(&list)
	lResp.Body.Close()
	if len(list.Distinctions) != 1 || list.Distinctions[0].ConceptID != conceptA {
		t.Fatalf("the (U, A) negative pair must persist independently of the B membership, got %+v", list.Distinctions)
	}

	// Missing concept -> 404; missing unit -> 404.
	missConcept, err := http.Post(srv.URL+"/knowledge-units/"+itoa(unitID)+"/concept-distinctions", "application/json",
		bytes.NewReader([]byte(`{"concept_id":999999}`)))
	if err != nil {
		t.Fatalf("POST distinction missing concept: %v", err)
	}
	missConcept.Body.Close()
	if missConcept.StatusCode != http.StatusNotFound {
		t.Fatalf("missing concept distinction status = %d, want 404", missConcept.StatusCode)
	}
	missUnit, err := http.Post(srv.URL+"/knowledge-units/999999/concept-distinctions", "application/json",
		bytes.NewReader([]byte(`{"concept_id":`+itoa(conceptA)+`}`)))
	if err != nil {
		t.Fatalf("POST distinction missing unit: %v", err)
	}
	missUnit.Body.Close()
	if missUnit.StatusCode != http.StatusNotFound {
		t.Fatalf("missing unit distinction status = %d, want 404", missUnit.StatusCode)
	}
}
