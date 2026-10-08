package http_test

import (
	"context"
	"database/sql"
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

// hookExtractor is a controllable fake provider. Its hook runs while the
// "provider call" is in flight, i.e. after the service has read the source and
// before it persists the result, so a test can deterministically change the
// entry's effective interpretation in that window.
type hookExtractor struct {
	units []domain.ExtractedUnit
	hook  func(t *testing.T)
	t     *testing.T
	calls int
}

func (h *hookExtractor) Name() string { return "hook:test:knowledge_extraction_v1" }
func (h *hookExtractor) Extract(context.Context, domain.ExtractionSource) (domain.ExtractionResult, error) {
	h.calls++
	if h.hook != nil {
		// With MaxOpenConns(1), these writes would block if the service still
		// held a database connection or transaction across the provider call.
		h.hook(h.t)
	}
	return domain.ExtractionResult{Units: h.units}, nil
}

type raceFixture struct {
	srv       *httptest.Server
	db        *sql.DB
	entries   *sqlite.EntryRepository
	analyses  *sqlite.AnalysisRepository
	feedback  *sqlite.FeedbackRepository
	knowledge *sqlite.KnowledgeRepository
	concepts  *sqlite.ConceptRepository
	ex        *hookExtractor
}

func setupRaceFixture(t *testing.T) *raceFixture {
	t.Helper()
	db, err := sqlite.Open(filepath.Join(t.TempDir(), "race.db"))
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	t.Cleanup(func() { db.Close() })

	f := &raceFixture{
		db:        db,
		entries:   sqlite.NewEntryRepository(db),
		analyses:  sqlite.NewAnalysisRepository(db),
		feedback:  sqlite.NewFeedbackRepository(db),
		knowledge: sqlite.NewKnowledgeRepository(db),
		concepts:  sqlite.NewConceptRepository(db),
		ex: &hookExtractor{t: t, units: []domain.ExtractedUnit{
			{Kind: domain.KindGrammar, Canonical: "vouloir + inf", Statement: "vouloir takes a bare infinitive", Confidence: 0.9},
		}},
	}
	knowledgeSvc := application.NewKnowledgeService(f.entries, f.analyses, f.feedback, f.knowledge, sqlite.NewAdmissionRepository(db), f.ex)
	handler := transporthttp.NewHandler(
		application.NewEntryService(f.entries),
		application.NewAnalysisService(f.entries, f.analyses, nil),
		application.NewFeedbackService(f.feedback),
		application.NewEffectiveAnalysisService(f.analyses, f.feedback),
		application.NewInventoryService(sqlite.NewInventoryRepository(db)),
		application.NewCaptureService(sqlite.NewCaptureRepository(db)),
		knowledgeSvc, nil, nil, nil)
	f.srv = httptest.NewServer(handler.Routes())
	t.Cleanup(f.srv.Close)
	return f
}

func (f *raceFixture) seedEntry(t *testing.T) (entryID, analysisID int64) {
	t.Helper()
	ctx := context.Background()
	e, err := f.entries.Create(ctx, domain.NewEntryInput{OriginalInput: "Je veux aller au marché"})
	if err != nil {
		t.Fatalf("create entry: %v", err)
	}
	a := f.addAnalysis(t, e.ID)
	return e.ID, a
}

func (f *raceFixture) addAnalysis(t *testing.T, entryID int64) int64 {
	t.Helper()
	a, err := f.analyses.Create(context.Background(), entryID, domain.AnalysisResult{
		Category: "grammar", Explanation: "vouloir + infinitive", Confidence: 0.8,
	}, "rule-based:test")
	if err != nil {
		t.Fatalf("create analysis: %v", err)
	}
	return a.ID
}

func (f *raceFixture) addFeedback(t *testing.T, analysisID int64, in domain.NewFeedbackInput) int64 {
	t.Helper()
	fb, err := f.feedback.Create(context.Background(), analysisID, in)
	if err != nil {
		t.Fatalf("create feedback: %v", err)
	}
	return fb.ID
}

func (f *raceFixture) postExtraction(t *testing.T, entryID int64) (int, map[string]any) {
	t.Helper()
	resp, err := http.Post(f.srv.URL+"/entries/"+itoa(entryID)+"/extractions", "application/json", nil)
	if err != nil {
		t.Fatalf("POST: %v", err)
	}
	defer resp.Body.Close()
	var body map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	return resp.StatusCode, body
}

type tableCounts struct{ extractions, units, recommendations int }

func (f *raceFixture) counts(t *testing.T) tableCounts {
	t.Helper()
	var c tableCounts
	for _, q := range []struct {
		table string
		dst   *int
	}{
		{"knowledge_extractions", &c.extractions},
		{"knowledge_units", &c.units},
		{"knowledge_admission_recommendations", &c.recommendations},
	} {
		if err := f.db.QueryRow(`SELECT COUNT(*) FROM ` + q.table).Scan(q.dst); err != nil {
			t.Fatalf("count %s: %v", q.table, err)
		}
	}
	return c
}

func (f *raceFixture) currentExtraction(t *testing.T, entryID int64) *int64 {
	t.Helper()
	id, err := f.concepts.GetCurrentExtractionID(context.Background(), entryID)
	if err != nil {
		t.Fatalf("current extraction: %v", err)
	}
	return id
}

// TestExtractionSourceChangedDuringProvider covers every way the effective
// interpretation can move while the provider runs. Each stale case must answer
// 409, write nothing, and leave the previously current extraction current.
func TestExtractionSourceChangedDuringProvider(t *testing.T) {
	cases := []struct {
		name string
		// setup prepares the entry before the first (baseline) extraction and
		// returns the analysis that will be current when the stale run starts.
		setup func(t *testing.T, f *raceFixture, entryID, analysisID int64) int64
		// change mutates the source during the provider call.
		change func(t *testing.T, f *raceFixture, entryID, analysisID int64)
	}{
		{
			name:  "new analysis arrives",
			setup: func(_ *testing.T, _ *raceFixture, _, a int64) int64 { return a },
			change: func(t *testing.T, f *raceFixture, entryID, _ int64) {
				f.addAnalysis(t, entryID)
			},
		},
		{
			name: "feedback rejects current analysis",
			setup: func(t *testing.T, f *raceFixture, _, a int64) int64 {
				f.addFeedback(t, a, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})
				return a
			},
			change: func(t *testing.T, f *raceFixture, _, a int64) {
				f.addFeedback(t, a, domain.NewFeedbackInput{Status: domain.FeedbackRejected})
			},
		},
		{
			name: "feedback corrects current analysis",
			setup: func(t *testing.T, f *raceFixture, _, a int64) int64 {
				f.addFeedback(t, a, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})
				return a
			},
			change: func(t *testing.T, f *raceFixture, _, a int64) {
				expl := "vouloir + infinitif (corrigé)"
				f.addFeedback(t, a, domain.NewFeedbackInput{Status: domain.FeedbackCorrected, CorrectedExplanation: &expl})
			},
		},
		{
			name:  "absent feedback becomes present",
			setup: func(_ *testing.T, _ *raceFixture, _, a int64) int64 { return a },
			change: func(t *testing.T, f *raceFixture, _, a int64) {
				f.addFeedback(t, a, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})
			},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			f := setupRaceFixture(t)
			entryID, analysisID := f.seedEntry(t)
			analysisID = tc.setup(t, f, entryID, analysisID)

			// Baseline: an unchanged run succeeds and becomes current.
			status, body := f.postExtraction(t, entryID)
			if status != http.StatusCreated {
				t.Fatalf("baseline status = %d, body %v", status, body)
			}
			baselineID := int64(body["id"].(float64))
			before := f.counts(t)

			f.ex.hook = func(t *testing.T) { tc.change(t, f, entryID, analysisID) }
			status, body = f.postExtraction(t, entryID)
			if status != http.StatusConflict {
				t.Fatalf("stale status = %d, want 409; body %v", status, body)
			}
			if msg, _ := body["error"].(string); msg == "" {
				t.Fatalf("stale conflict carries no error message: %v", body)
			}
			if f.ex.calls != 2 {
				t.Fatalf("provider calls = %d, want 2", f.ex.calls)
			}

			if after := f.counts(t); after != before {
				t.Fatalf("stale result persisted rows: before %+v, after %+v", before, after)
			}
			cur := f.currentExtraction(t, entryID)
			if cur == nil || *cur != baselineID {
				t.Fatalf("current extraction = %v, want baseline %d", cur, baselineID)
			}
			if _, err := f.knowledge.GetByID(context.Background(), baselineID); err != nil {
				t.Fatalf("baseline extraction no longer readable: %v", err)
			}
		})
	}
}

// TestExtractionUnchangedSourceSucceeds proves the currency check does not reject
// a run whose source stays the same, including when the hook writes something
// unrelated to this entry during the provider call.
func TestExtractionUnchangedSourceSucceeds(t *testing.T) {
	f := setupRaceFixture(t)
	entryID, analysisID := f.seedEntry(t)
	fbID := f.addFeedback(t, analysisID, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})
	otherEntry, otherAnalysis := f.seedEntry(t)

	f.ex.hook = func(t *testing.T) {
		// Activity on a different entry must not make this entry's run stale.
		f.addAnalysis(t, otherEntry)
		f.addFeedback(t, otherAnalysis, domain.NewFeedbackInput{Status: domain.FeedbackRejected})
	}
	status, body := f.postExtraction(t, entryID)
	if status != http.StatusCreated {
		t.Fatalf("status = %d, want 201; body %v", status, body)
	}
	if got := int64(body["source_analysis_id"].(float64)); got != analysisID {
		t.Fatalf("source_analysis_id = %d, want %d", got, analysisID)
	}
	if got, _ := body["source_feedback_id"].(float64); int64(got) != fbID {
		t.Fatalf("source_feedback_id = %v, want %d", body["source_feedback_id"], fbID)
	}
	if c := f.counts(t); c.extractions != 1 || c.units != 1 || c.recommendations != 1 {
		t.Fatalf("counts = %+v, want one of each", c)
	}
	cur := f.currentExtraction(t, entryID)
	if cur == nil || *cur != int64(body["id"].(float64)) {
		t.Fatalf("current extraction = %v, want new extraction", cur)
	}
}
