package http_test

import (
	"context"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

// scriptedExtractor returns the next scripted unit list on each call.
type scriptedExtractor struct{ calls [][]domain.ExtractedUnit }

func (s *scriptedExtractor) Name() string { return "stub:library:knowledge_extraction_v1" }
func (s *scriptedExtractor) Extract(context.Context, domain.ExtractionSource) (domain.ExtractionResult, error) {
	next := s.calls[0]
	s.calls = s.calls[1:]
	return domain.ExtractionResult{Units: next}, nil
}

type libraryFixture struct {
	srv  *httptest.Server
	api  *httptest.Server
	db   *sql.DB
	ids  map[string]int64
	path string
	// Write services, used only by tests that change state before reading.
	concepts  *application.ConceptService
	knowledge *application.KnowledgeService
}

// setupLibrary builds a real stack and this scenario:
//
//	entry A v1: uA1 "subjonctif après il faut que" (SAME C1, preferred), uA2 "faire" (SAME C3)
//	entry B v1: uB1 same target as uA1 (SAME C1), uB2 "avoir" (SAME C1 → INVALID)
//	uB1 BROADER → C2 "mode subjonctif"; uB2 SAME C3 first, then reassigned to C1 before INVALID
//	entry A re-extracted to v2 (uA3): uA1 and uA2 become historical, so C3 is orphaned
//	and C1 keeps support only through uB1.
func setupLibrary(t *testing.T) *libraryFixture {
	t.Helper()
	ctx := context.Background()
	dbPath := filepath.Join(t.TempDir(), "library.db")
	db, err := sqlite.Open(dbPath)
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	entryRepo := sqlite.NewEntryRepository(db)
	analysisRepo := sqlite.NewAnalysisRepository(db)
	feedbackRepo := sqlite.NewFeedbackRepository(db)
	knowledgeRepo := sqlite.NewKnowledgeRepository(db)
	admissionRepo := sqlite.NewAdmissionRepository(db)
	conceptRepo := sqlite.NewConceptRepository(db)
	ex := &scriptedExtractor{calls: [][]domain.ExtractedUnit{
		{
			{Kind: domain.KindGrammar, Canonical: "subjonctif après il faut que", Statement: "Après « il faut que », le verbe est au subjonctif.", Confidence: 0.9},
			{Kind: domain.KindVocabulary, Canonical: "faire", Statement: "Faire : verbe irrégulier.", Confidence: 0.9},
		},
		{
			{Kind: domain.KindGrammar, Canonical: "subjonctif après il faut que", Statement: "Le subjonctif exprime ici une nécessité, pas un doute.", Confidence: 0.9},
			{Kind: domain.KindVocabulary, Canonical: "avoir", Statement: "Avoir : auxiliaire.", Confidence: 0.9},
		},
		{
			{Kind: domain.KindUsage, Canonical: "registre familier", Statement: "Forme orale.", Confidence: 0.9},
		},
	}}
	knowledgeSvc := application.NewKnowledgeService(entryRepo, analysisRepo, feedbackRepo, knowledgeRepo, admissionRepo, ex)
	conceptSvc := application.NewConceptService(knowledgeRepo, conceptRepo, conceptRepo)
	effectiveAnnotationSvc := application.NewEffectiveAnnotationService(conceptRepo, conceptRepo)

	newEntry := func(input string) int64 {
		e, err := entryRepo.Create(ctx, domain.NewEntryInput{OriginalInput: input, OriginalContext: "contexte synthétique"})
		if err != nil {
			t.Fatal(err)
		}
		if _, err := analysisRepo.Create(ctx, e.ID, domain.AnalysisResult{Category: "grammar", Explanation: "explication v1", Confidence: 0.8}, "rule-based:test"); err != nil {
			t.Fatal(err)
		}
		return e.ID
	}
	extract := func(entryID int64) []int64 {
		v, err := knowledgeSvc.Extract(ctx, entryID)
		if err != nil {
			t.Fatal(err)
		}
		var ids []int64
		for _, u := range v.Units {
			ids = append(ids, u.Unit.ID)
		}
		return ids
	}
	must := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	ids := map[string]int64{}
	ids["entryA"] = newEntry("Pourquoi « il faut que je fasse » ?")
	a := extract(ids["entryA"])
	ids["uA1"], ids["uA2"] = a[0], a[1]
	ids["entryB"] = newEntry("Il faut que j'aie fini ?")
	// Feedback on B's analysis is in force at extraction: the source interpretation must use it.
	analysesB, _ := analysisRepo.ListByEntry(ctx, ids["entryB"])
	corrected := "explication corrigée"
	fb, err := feedbackRepo.Create(ctx, analysesB[0].ID, domain.NewFeedbackInput{Status: domain.FeedbackCorrected, CorrectedExplanation: &corrected})
	must(err)
	ids["feedbackB"] = fb.ID
	b := extract(ids["entryB"])
	ids["uB1"], ids["uB2"] = b[0], b[1]

	identity := func(target string) domain.ConceptIdentity {
		return domain.ConceptIdentity{Target: target, PedagogicalIntent: "grammar", IdentityFeatures: map[string]string{"mode": "subjonctif"}}
	}
	uA1 := ids["uA1"]
	c1, _, err := conceptSvc.CreateConcept(ctx, identity("subjonctif après il faut que"), &uA1, true)
	must(err)
	ids["C1"] = c1.ID
	_, err = conceptSvc.ResolveSame(ctx, ids["uB1"], c1.ID)
	must(err)
	_, err = conceptSvc.SetPreferredUnit(ctx, c1.ID, ids["uA1"])
	must(err)
	c2, _, err := conceptSvc.CreateConcept(ctx, domain.ConceptIdentity{Target: "mode subjonctif", PedagogicalIntent: "grammar"}, nil, false)
	must(err)
	ids["C2"] = c2.ID
	_, err = conceptSvc.RecordRelation(ctx, ids["uB1"], c2.ID, domain.RelationBroader)
	must(err)
	uA2 := ids["uA2"]
	c3, _, err := conceptSvc.CreateConcept(ctx, domain.ConceptIdentity{Target: "faire", PedagogicalIntent: "vocabulary"}, &uA2, true)
	must(err)
	ids["C3"] = c3.ID
	_, err = conceptSvc.ResolveSame(ctx, ids["uB2"], c3.ID)
	must(err)
	_, err = conceptSvc.ReassignSame(ctx, ids["uB2"], c1.ID)
	must(err)
	_, err = conceptSvc.MarkUnitInvalid(ctx, ids["uB2"])
	must(err)
	extract(ids["entryA"]) // v2: uA1 and uA2 become historical-extraction units

	library := application.NewKnowledgeLibraryService(conceptRepo, knowledgeRepo, entryRepo, analysisRepo, feedbackRepo, effectiveAnnotationSvc)
	handler := transporthttp.NewHandler(nil, nil, nil, nil, nil, nil, nil, conceptSvc, effectiveAnnotationSvc, nil,
		transporthttp.WithKnowledgeLibrary(library))
	srv := httptest.NewServer(handler.Routes())
	t.Cleanup(srv.Close)
	webDir := t.TempDir()
	must(os.WriteFile(filepath.Join(webDir, "index.html"), []byte("<!doctype html>"), 0o600))
	wb, err := transporthttp.NewWorkbenchHandler(handler.Routes(), webDir)
	must(err)
	apiSrv := httptest.NewServer(wb)
	t.Cleanup(apiSrv.Close)
	return &libraryFixture{srv: srv, api: apiSrv, db: db, ids: ids, path: dbPath, concepts: conceptSvc, knowledge: knowledgeSvc}
}

func libraryGet(t *testing.T, url string, want int, v any) {
	t.Helper()
	resp, err := http.Get(url)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != want {
		var body map[string]any
		_ = json.NewDecoder(resp.Body).Decode(&body)
		t.Fatalf("GET %s status = %d, want %d (%v)", url, resp.StatusCode, want, body)
	}
	if v != nil {
		if err := json.NewDecoder(resp.Body).Decode(v); err != nil {
			t.Fatal(err)
		}
	}
}

type libSearch struct {
	Tokens       []string `json:"tokens"`
	TotalMatches int      `json:"total_matches"`
	Truncated    bool     `json:"truncated"`
	Limit        int      `json:"limit"`
	Results      []struct {
		Concept struct {
			ID      int64  `json:"id"`
			Target  string `json:"target"`
			State   string `json:"state"`
			Support string `json:"support_state"`
		} `json:"concept"`
		MatchTier          string   `json:"match_tier"`
		MatchedFields      []string `json:"matched_fields"`
		CurrentMemberCount int      `json:"current_member_count"`
		SupportingCount    int      `json:"supporting_unit_count"`
	} `json:"results"`
}

type libUnit struct {
	UnitID              int64  `json:"unit_id"`
	EntryID             int64  `json:"entry_id"`
	ExtractionVersion   int64  `json:"extraction_version"`
	InCurrentExtraction bool   `json:"in_current_extraction"`
	Admission           string `json:"admission"`
}

type libConcept struct {
	Concept struct {
		ID      int64  `json:"id"`
		State   string `json:"state"`
		Support string `json:"support_state"`
	} `json:"concept"`
	PreferredUnit        *libUnit  `json:"preferred_unit"`
	SupportingUnits      []libUnit `json:"supporting_units"`
	NonSupportingMembers []libUnit `json:"non_supporting_members"`
	CurrentRelations     []struct {
		Relation string  `json:"relation"`
		Unit     libUnit `json:"unit"`
	} `json:"current_relations"`
	HistoricalUnits []struct {
		Unit        libUnit `json:"unit"`
		LatestEvent struct {
			Relation string `json:"relation"`
			Status   string `json:"status"`
		} `json:"latest_event"`
		EffectiveStatus  string `json:"effective_status"`
		CurrentConceptID *int64 `json:"current_concept_id"`
	} `json:"historical_units"`
	HistoryEventCount int `json:"history_event_count"`
}

func unitIDs(units []libUnit) []int64 {
	out := []int64{}
	for _, u := range units {
		out = append(out, u.UnitID)
	}
	return out
}

func TestKnowledgeLibrary_SearchTiersOrderingAndBounds(t *testing.T) {
	f := setupLibrary(t)
	var s libSearch
	// Accent-insensitive prefix match on identity fields: C1 and C2; C3 does not match.
	libraryGet(t, f.srv.URL+"/knowledge-library/concepts?q=SUBJ", 200, &s)
	if s.TotalMatches != 2 || s.Results[0].Concept.ID != f.ids["C1"] || s.Results[1].Concept.ID != f.ids["C2"] {
		t.Fatalf("subj results = %+v", s.Results)
	}
	if s.Results[0].MatchTier != "identity" || s.Results[0].CurrentMemberCount != 2 || s.Results[0].SupportingCount != 1 {
		t.Fatalf("C1 result = %+v", s.Results[0])
	}
	// "nécessité" only occurs in a current member's statement: unit_evidence tier.
	libraryGet(t, f.srv.URL+"/knowledge-library/concepts?q=necessite", 200, &s)
	if s.TotalMatches != 1 || s.Results[0].Concept.ID != f.ids["C1"] || s.Results[0].MatchTier != "unit_evidence" ||
		len(s.Results[0].MatchedFields) != 1 || s.Results[0].MatchedFields[0] != "unit_statement" {
		t.Fatalf("necessite results = %+v", s.Results)
	}
	// "auxiliaire" only occurs in uB2, which is INVALID and no longer a member: no match.
	libraryGet(t, f.srv.URL+"/knowledge-library/concepts?q=auxiliaire", 200, &s)
	if s.TotalMatches != 0 || len(s.Results) != 0 {
		t.Fatalf("historical unit text must not match: %+v", s.Results)
	}
	// Browse: active before orphaned, bounded with truncation.
	libraryGet(t, f.srv.URL+"/knowledge-library/concepts?limit=2", 200, &s)
	if s.TotalMatches != 3 || !s.Truncated || len(s.Results) != 2 || s.Results[0].Concept.State != "active" {
		t.Fatalf("browse = %+v", s)
	}
	libraryGet(t, f.srv.URL+"/knowledge-library/concepts?state=orphaned", 200, &s)
	if len(s.Results) != 2 { // C2 (never supported) and C3 (support lost)
		t.Fatalf("orphaned = %+v", s.Results)
	}
	for _, bad := range []string{"?limit=0", "?limit=51", "?limit=x", "?state=gone", "?q=%21+a"} {
		libraryGet(t, f.srv.URL+"/knowledge-library/concepts"+bad, 400, nil)
	}
}

// The search contract is CURRENT SAME membership, not current extraction or
// support: a member from a historical extraction or with suppressed admission
// still contributes its wording, while a former member contributes nothing to
// the Concept it left.
func TestKnowledgeLibrary_SearchFollowsCurrentSameMembership(t *testing.T) {
	f := setupLibrary(t)
	ctx := context.Background()
	var s libSearch
	// uA2 ("Faire : verbe irrégulier.") is C3's CURRENT SAME member from historical extraction v1.
	libraryGet(t, f.srv.URL+"/knowledge-library/concepts?q=irregulier", 200, &s)
	if s.TotalMatches != 1 || s.Results[0].Concept.ID != f.ids["C3"] || s.Results[0].MatchTier != "unit_evidence" ||
		s.Results[0].Concept.State != "orphaned" || s.Results[0].SupportingCount != 0 || s.Results[0].CurrentMemberCount != 1 {
		t.Fatalf("historical-extraction member: %+v", s.Results)
	}
	// Reassign uA2 to C1: its wording now matches C1 only, never its former Concept C3.
	if _, err := f.concepts.ReassignSame(ctx, f.ids["uA2"], f.ids["C1"]); err != nil {
		t.Fatal(err)
	}
	libraryGet(t, f.srv.URL+"/knowledge-library/concepts?q=irregulier", 200, &s)
	if s.TotalMatches != 1 || s.Results[0].Concept.ID != f.ids["C1"] || s.Results[0].MatchTier != "unit_evidence" {
		t.Fatalf("reassigned member must match only its new concept: %+v", s.Results)
	}
	// Suppress uB1, C1's only supporting unit: C1 loses support but uB1 is still
	// its CURRENT SAME member, so its wording still matches.
	if _, err := f.knowledge.AddOverride(ctx, f.ids["uB1"], domain.NewAdmissionOverrideInput{Decision: domain.HumanAdmitSuppressed, Reason: "ignored"}); err != nil {
		t.Fatal(err)
	}
	libraryGet(t, f.srv.URL+"/knowledge-library/concepts?q=necessite", 200, &s)
	if s.TotalMatches != 1 || s.Results[0].Concept.ID != f.ids["C1"] || s.Results[0].Concept.State != "orphaned" ||
		s.Results[0].SupportingCount != 0 || s.Results[0].MatchedFields[0] != "unit_statement" {
		t.Fatalf("suppressed member: %+v", s.Results)
	}
}

func TestKnowledgeLibrary_ConceptSeparatesCurrentFromHistory(t *testing.T) {
	f := setupLibrary(t)
	var c libConcept
	libraryGet(t, f.srv.URL+"/knowledge-library/concepts/"+itoa(f.ids["C1"]), 200, &c)
	if c.Concept.State != "active" || c.Concept.Support != "supported" {
		t.Fatalf("C1 state = %+v", c.Concept)
	}
	if got := unitIDs(c.SupportingUnits); len(got) != 1 || got[0] != f.ids["uB1"] {
		t.Fatalf("supporting = %v", got)
	}
	// uA1 is still the CURRENT SAME member and preferred unit, but its extraction is historical.
	if got := c.NonSupportingMembers; len(got) != 1 || got[0].UnitID != f.ids["uA1"] || got[0].InCurrentExtraction || got[0].ExtractionVersion != 1 {
		t.Fatalf("non-supporting = %+v", got)
	}
	if c.PreferredUnit == nil || c.PreferredUnit.UnitID != f.ids["uA1"] || c.PreferredUnit.InCurrentExtraction {
		t.Fatalf("preferred = %+v", c.PreferredUnit)
	}
	// uB2 was reassigned here and then marked INVALID: history only, never current.
	if len(c.HistoricalUnits) != 1 || c.HistoricalUnits[0].Unit.UnitID != f.ids["uB2"] ||
		c.HistoricalUnits[0].EffectiveStatus != "invalid" || c.HistoricalUnits[0].CurrentConceptID != nil {
		t.Fatalf("history = %+v", c.HistoricalUnits)
	}
	if len(c.CurrentRelations) != 0 {
		t.Fatalf("C1 relations = %+v", c.CurrentRelations)
	}

	libraryGet(t, f.srv.URL+"/knowledge-library/concepts/"+itoa(f.ids["C2"]), 200, &c)
	if c.Concept.Support != "orphaned" || len(c.CurrentRelations) != 1 || c.CurrentRelations[0].Relation != "broader" ||
		c.CurrentRelations[0].Unit.UnitID != f.ids["uB1"] || !c.CurrentRelations[0].Unit.InCurrentExtraction {
		t.Fatalf("C2 = %+v", c)
	}

	// C3 is orphaned but inspectable: uA2 is a member from a historical extraction,
	// uB2 left (reassigned to C1, then INVALID).
	libraryGet(t, f.srv.URL+"/knowledge-library/concepts/"+itoa(f.ids["C3"]), 200, &c)
	if c.Concept.State != "orphaned" || len(c.SupportingUnits) != 0 || len(c.NonSupportingMembers) != 1 || c.NonSupportingMembers[0].UnitID != f.ids["uA2"] {
		t.Fatalf("C3 = %+v", c)
	}
	if len(c.HistoricalUnits) != 1 || c.HistoricalUnits[0].Unit.UnitID != f.ids["uB2"] || c.HistoricalUnits[0].EffectiveStatus != "invalid" {
		t.Fatalf("C3 history = %+v", c.HistoricalUnits)
	}
	libraryGet(t, f.srv.URL+"/knowledge-library/concepts/999", 404, nil)
	libraryGet(t, f.srv.URL+"/knowledge-library/concepts/x", 400, nil)
}

func TestKnowledgeLibrary_UnitSourceUsesExtractionInterpretation(t *testing.T) {
	f := setupLibrary(t)
	var src struct {
		Unit  libUnit `json:"unit"`
		Entry struct {
			ID            int64  `json:"id"`
			OriginalInput string `json:"original_input"`
		} `json:"entry"`
		Extraction struct {
			Version          int64  `json:"version"`
			SourceFeedbackID *int64 `json:"source_feedback_id"`
		} `json:"extraction"`
		CurrentExtraction struct {
			ExtractionID  *int64 `json:"extraction_id"`
			SelectionMode string `json:"selection_mode"`
		} `json:"current_extraction"`
		SourceInterpretation struct {
			Analysis struct {
				Version int64 `json:"version"`
			} `json:"analysis"`
			Feedback *struct {
				ID int64 `json:"id"`
			} `json:"feedback"`
			Effective struct {
				Resolution string `json:"resolution"`
				Effective  *struct {
					Explanation string `json:"explanation"`
				} `json:"effective"`
			} `json:"effective"`
		} `json:"source_interpretation"`
		LatestAnalysis *struct {
			Version int64 `json:"version"`
		} `json:"latest_analysis"`
		Annotation struct {
			Status           string `json:"status"`
			CurrentConceptID *int64 `json:"current_concept_id"`
		} `json:"annotation"`
	}
	libraryGet(t, f.srv.URL+"/knowledge-library/units/"+itoa(f.ids["uB1"])+"/source", 200, &src)
	if src.Entry.ID != f.ids["entryB"] || src.Entry.OriginalInput != "Il faut que j'aie fini ?" || !src.Unit.InCurrentExtraction {
		t.Fatalf("source = %+v", src)
	}
	if src.SourceInterpretation.Feedback == nil || src.SourceInterpretation.Feedback.ID != f.ids["feedbackB"] ||
		src.SourceInterpretation.Effective.Resolution != "corrected" || src.SourceInterpretation.Effective.Effective.Explanation != "explication corrigée" {
		t.Fatalf("interpretation = %+v", src.SourceInterpretation)
	}
	if src.Annotation.Status != "resolved" || src.Annotation.CurrentConceptID == nil || *src.Annotation.CurrentConceptID != f.ids["C1"] {
		t.Fatalf("annotation = %+v", src.Annotation)
	}
	libraryGet(t, f.srv.URL+"/knowledge-library/units/"+itoa(f.ids["uA1"])+"/source", 200, &src)
	if src.Unit.InCurrentExtraction || src.Extraction.Version != 1 || src.CurrentExtraction.ExtractionID == nil || src.SourceInterpretation.Feedback != nil || src.LatestAnalysis.Version != 1 {
		t.Fatalf("historical source = %+v", src)
	}
	libraryGet(t, f.srv.URL+"/knowledge-library/units/999/source", 404, nil)
}

func TestKnowledgeLibrary_APIPrefixAndReadOnly(t *testing.T) {
	f := setupLibrary(t)
	count := func() map[string]int {
		out := map[string]int{}
		for _, table := range []string{"learning_entries", "entry_analyses", "analysis_feedback", "knowledge_extractions", "knowledge_units",
			"knowledge_concepts", "unit_concept_links", "unit_concept_memberships", "unit_resolution_judgments", "unit_concept_distinctions",
			"entry_current_extractions", "knowledge_admission_overrides", "annotation_operations"} {
			var n int
			if err := f.db.QueryRow("SELECT COUNT(*) FROM " + table).Scan(&n); err != nil {
				t.Fatalf("count %s: %v", table, err)
			}
			out[table] = n
		}
		return out
	}
	before := count()
	var root, prefixed libSearch
	libraryGet(t, f.srv.URL+"/knowledge-library/concepts?q=subjonctif", 200, &root)
	libraryGet(t, f.api.URL+"/api/knowledge-library/concepts?q=subjonctif", 200, &prefixed)
	if root.TotalMatches != prefixed.TotalMatches || root.Results[0].Concept.ID != prefixed.Results[0].Concept.ID {
		t.Fatalf("root %+v vs /api %+v", root, prefixed)
	}
	libraryGet(t, f.api.URL+"/api/knowledge-library/concepts/"+itoa(f.ids["C1"]), 200, nil)
	libraryGet(t, f.api.URL+"/api/knowledge-library/units/"+itoa(f.ids["uA1"])+"/source", 200, nil)
	after := count()
	for table, n := range before {
		if after[table] != n {
			t.Fatalf("%s rows changed by read-only browsing: %d → %d", table, n, after[table])
		}
	}
	resp, err := http.Post(f.srv.URL+"/knowledge-library/concepts", "application/json", nil)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusMethodNotAllowed {
		t.Fatalf("POST status = %d, want 405", resp.StatusCode)
	}
}
