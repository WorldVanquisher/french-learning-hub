package sqlite

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"french-learning-app/internal/domain"
)

// invRepos bundles the writer repositories used to seed inventory fixtures
// alongside the read-only inventory repository under test.
type invRepos struct {
	entries   *EntryRepository
	analyses  *AnalysisRepository
	feedback  *FeedbackRepository
	inventory *InventoryRepository
}

func newTestInventoryRepos(t *testing.T) *invRepos {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "inventory.db")
	db, err := Open(dbPath)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return &invRepos{
		entries:   NewEntryRepository(db),
		analyses:  NewAnalysisRepository(db),
		feedback:  NewFeedbackRepository(db),
		inventory: NewInventoryRepository(db),
	}
}

// setClock pins the create timestamp used by the analysis and feedback repos so
// tie-breaks and ordering are deterministic. The entry repo timestamp does not
// affect inventory selection (entries are ordered by id), so it is left alone.
func (r *invRepos) setClock(ts time.Time) {
	r.analyses.now = func() time.Time { return ts }
	r.feedback.now = func() time.Time { return ts }
}

func (r *invRepos) newEntry(t *testing.T, input, context string) *domain.Entry {
	t.Helper()
	e, err := r.entries.Create(context2(), domain.NewEntryInput{OriginalInput: input, OriginalContext: context})
	if err != nil {
		t.Fatalf("create entry: %v", err)
	}
	return e
}

func (r *invRepos) newAnalysis(t *testing.T, entryID int64, category, explanation, analyzer string) *domain.Analysis {
	t.Helper()
	a, err := r.analyses.Create(context2(), entryID, domain.AnalysisResult{
		Category:    category,
		Explanation: explanation,
		Confidence:  0.5,
	}, analyzer)
	if err != nil {
		t.Fatalf("create analysis: %v", err)
	}
	return a
}

func (r *invRepos) newFeedback(t *testing.T, analysisID int64, in domain.NewFeedbackInput) *domain.Feedback {
	t.Helper()
	f, err := r.feedback.Create(context2(), analysisID, in)
	if err != nil {
		t.Fatalf("create feedback: %v", err)
	}
	return f
}

// context2 is a tiny helper so seed calls read cleanly.
func context2() context.Context { return context.Background() }

// findRecord returns the single record for entryID, or fails.
func findRecord(t *testing.T, recs []*domain.LearningRecord, entryID int64) *domain.LearningRecord {
	t.Helper()
	var found *domain.LearningRecord
	for _, r := range recs {
		if r.EntryID == entryID {
			if found != nil {
				t.Fatalf("duplicate record for entry %d", entryID)
			}
			found = r
		}
	}
	if found == nil {
		t.Fatalf("no record for entry %d", entryID)
	}
	return found
}

// listAll lists with a generous, already-normalized query.
func (r *invRepos) listAll(t *testing.T) []*domain.LearningRecord {
	t.Helper()
	recs, err := r.inventory.ListLearningRecords(context2(), domain.LearningRecordQuery{Limit: 200})
	if err != nil {
		t.Fatalf("list records: %v", err)
	}
	return recs
}

func TestInventory_UnanalyzedEntry(t *testing.T) {
	r := newTestInventoryRepos(t)
	e := r.newEntry(t, "bonjour", "greeting")

	rec := findRecord(t, r.listAll(t), e.ID)
	if rec.State != domain.LearningRecordUnanalyzed {
		t.Fatalf("state = %q, want unanalyzed", rec.State)
	}
	if rec.AnalysisID != nil || rec.AnalysisVersion != nil || rec.Analyzer != nil ||
		rec.Confidence != nil || rec.Uncertainty != nil || rec.AnalysisCreatedAt != nil {
		t.Fatalf("unanalyzed record must have nil analysis fields: %+v", rec)
	}
	if rec.Original != nil || rec.Effective != nil || rec.FeedbackID != nil {
		t.Fatalf("unanalyzed record must have nil original/effective/feedback: %+v", rec)
	}
	if rec.OriginalInput != "bonjour" || rec.OriginalContext != "greeting" {
		t.Fatalf("entry fields wrong: %+v", rec)
	}
}

func TestInventory_LatestVersionSelected_NoDuplicateRows(t *testing.T) {
	r := newTestInventoryRepos(t)
	e := r.newEntry(t, "je mange", "lunch")

	// Three analyses on the same entry; only the latest version should surface,
	// as exactly one row.
	r.newAnalysis(t, e.ID, "vocabulary", "v1", "rule-based:v1:fr_l2_taxonomy_v1")
	r.newAnalysis(t, e.ID, "grammar", "v2", "rule-based:v2:fr_l2_taxonomy_v1")
	latest := r.newAnalysis(t, e.ID, "morphology", "v3", "openai:gpt-x:fr_l2_taxonomy_v1")

	recs := r.listAll(t)
	// Exactly one row for the entry.
	count := 0
	for _, rec := range recs {
		if rec.EntryID == e.ID {
			count++
		}
	}
	if count != 1 {
		t.Fatalf("expected exactly 1 row for entry, got %d", count)
	}

	rec := findRecord(t, recs, e.ID)
	if rec.AnalysisID == nil || *rec.AnalysisID != latest.ID {
		t.Fatalf("latest analysis id = %v, want %d", rec.AnalysisID, latest.ID)
	}
	if rec.AnalysisVersion == nil || *rec.AnalysisVersion != 3 {
		t.Fatalf("version = %v, want 3", rec.AnalysisVersion)
	}
	if rec.Analyzer == nil || *rec.Analyzer != "openai:gpt-x:fr_l2_taxonomy_v1" {
		t.Fatalf("analyzer = %v, want latest provenance", rec.Analyzer)
	}
	if rec.Original == nil || rec.Original.Category != "morphology" {
		t.Fatalf("original should be latest analysis, got %+v", rec.Original)
	}
	// No feedback yet: unreviewed, effective == original.
	if rec.State != domain.LearningRecordUnreviewed {
		t.Fatalf("state = %q, want unreviewed", rec.State)
	}
	if rec.Effective == nil || rec.Effective.Category != "morphology" {
		t.Fatalf("unreviewed effective should equal original, got %+v", rec.Effective)
	}
	if rec.FeedbackID != nil {
		t.Fatalf("unreviewed feedback id should be nil, got %v", rec.FeedbackID)
	}
}

func TestInventory_LatestFeedbackDeterminesState(t *testing.T) {
	r := newTestInventoryRepos(t)
	base := timeMustParse(t, "2026-07-01T10:00:00Z")

	e := r.newEntry(t, "je mange", "lunch")
	r.setClock(base)
	a := r.newAnalysis(t, e.ID, "grammar", "present tense", "rule-based:v2:fr_l2_taxonomy_v1")

	// Accepted, then corrected, then rejected — increasing timestamps so the last
	// one wins.
	r.setClock(base.Add(1 * time.Minute))
	r.newFeedback(t, a.ID, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})
	r.setClock(base.Add(2 * time.Minute))
	r.newFeedback(t, a.ID, domain.NewFeedbackInput{Status: domain.FeedbackCorrected, CorrectedCategory: sptr("morphology")})
	r.setClock(base.Add(3 * time.Minute))
	rejected := r.newFeedback(t, a.ID, domain.NewFeedbackInput{Status: domain.FeedbackRejected})

	rec := findRecord(t, r.listAll(t), e.ID)
	if rec.State != domain.LearningRecordRejected {
		t.Fatalf("state = %q, want rejected (latest wins)", rec.State)
	}
	if rec.Effective != nil {
		t.Fatalf("rejected effective must be nil, got %+v", rec.Effective)
	}
	if rec.FeedbackID == nil || *rec.FeedbackID != rejected.ID {
		t.Fatalf("feedback id = %v, want %d", rec.FeedbackID, rejected.ID)
	}
}

func TestInventory_IdenticalFeedbackTimestampsTieByID(t *testing.T) {
	r := newTestInventoryRepos(t)
	fixed := timeMustParse(t, "2026-07-02T09:00:00Z")

	e := r.newEntry(t, "je mange", "lunch")
	r.setClock(fixed)
	a := r.newAnalysis(t, e.ID, "grammar", "present tense", "rule-based:v2:fr_l2_taxonomy_v1")

	// All feedback share created_at; the highest id (last inserted) must win.
	r.newFeedback(t, a.ID, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})
	r.newFeedback(t, a.ID, domain.NewFeedbackInput{Status: domain.FeedbackCorrected, CorrectedCategory: sptr("morphology")})
	last := r.newFeedback(t, a.ID, domain.NewFeedbackInput{Status: domain.FeedbackRejected})

	rec := findRecord(t, r.listAll(t), e.ID)
	if rec.State != domain.LearningRecordRejected {
		t.Fatalf("tie-break should pick highest id (rejected), got state %q", rec.State)
	}
	if rec.FeedbackID == nil || *rec.FeedbackID != last.ID {
		t.Fatalf("feedback id = %v, want highest id %d", rec.FeedbackID, last.ID)
	}
}

func TestInventory_AcceptedPreservesOriginal(t *testing.T) {
	r := newTestInventoryRepos(t)
	e := r.newEntry(t, "je mange", "lunch")
	a := r.newAnalysis(t, e.ID, "grammar", "present tense", "rule-based:v2:fr_l2_taxonomy_v1")
	fb := r.newFeedback(t, a.ID, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})

	rec := findRecord(t, r.listAll(t), e.ID)
	if rec.State != domain.LearningRecordAccepted {
		t.Fatalf("state = %q, want accepted", rec.State)
	}
	if rec.Original == nil || rec.Original.Category != "grammar" || rec.Original.Explanation != "present tense" {
		t.Fatalf("original not preserved: %+v", rec.Original)
	}
	if rec.Effective == nil || rec.Effective.Category != "grammar" || rec.Effective.Explanation != "present tense" {
		t.Fatalf("accepted effective should equal original: %+v", rec.Effective)
	}
	if rec.FeedbackID == nil || *rec.FeedbackID != fb.ID {
		t.Fatalf("feedback id = %v, want %d", rec.FeedbackID, fb.ID)
	}
}

func TestInventory_Corrected(t *testing.T) {
	cases := []struct {
		name     string
		in       domain.NewFeedbackInput
		wantCat  string
		wantExpl string
	}{
		{
			"category only",
			domain.NewFeedbackInput{Status: domain.FeedbackCorrected, CorrectedCategory: sptr("morphology")},
			"morphology", "present tense", // explanation retains original
		},
		{
			"explanation only",
			domain.NewFeedbackInput{Status: domain.FeedbackCorrected, CorrectedExplanation: sptr("conjugation of manger")},
			"grammar", "conjugation of manger", // category retains original
		},
		{
			"both",
			domain.NewFeedbackInput{Status: domain.FeedbackCorrected, CorrectedCategory: sptr("morphology"), CorrectedExplanation: sptr("conjugation of manger")},
			"morphology", "conjugation of manger",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			r := newTestInventoryRepos(t)
			e := r.newEntry(t, "je mange", "lunch")
			a := r.newAnalysis(t, e.ID, "grammar", "present tense", "rule-based:v2:fr_l2_taxonomy_v1")
			r.newFeedback(t, a.ID, tc.in)

			rec := findRecord(t, r.listAll(t), e.ID)
			if rec.State != domain.LearningRecordCorrected {
				t.Fatalf("state = %q, want corrected", rec.State)
			}
			// Original always unchanged.
			if rec.Original == nil || rec.Original.Category != "grammar" || rec.Original.Explanation != "present tense" {
				t.Fatalf("original mutated: %+v", rec.Original)
			}
			if rec.Effective == nil || rec.Effective.Category != tc.wantCat || rec.Effective.Explanation != tc.wantExpl {
				t.Fatalf("effective = %+v, want cat=%q expl=%q", rec.Effective, tc.wantCat, tc.wantExpl)
			}
		})
	}
}

func TestInventory_RejectedHasNoEffective(t *testing.T) {
	r := newTestInventoryRepos(t)
	e := r.newEntry(t, "je mange", "lunch")
	a := r.newAnalysis(t, e.ID, "grammar", "present tense", "rule-based:v2:fr_l2_taxonomy_v1")
	r.newFeedback(t, a.ID, domain.NewFeedbackInput{Status: domain.FeedbackRejected})

	rec := findRecord(t, r.listAll(t), e.ID)
	if rec.State != domain.LearningRecordRejected {
		t.Fatalf("state = %q, want rejected", rec.State)
	}
	if rec.Effective != nil {
		t.Fatalf("rejected effective must be nil, got %+v", rec.Effective)
	}
	// Original is still reported for reference.
	if rec.Original == nil || rec.Original.Category != "grammar" {
		t.Fatalf("original should be preserved for rejected: %+v", rec.Original)
	}
}

func TestInventory_StateFilter(t *testing.T) {
	r := newTestInventoryRepos(t)
	// One entry per state.
	unan := r.newEntry(t, "unanalyzed one", "")

	unrev := r.newEntry(t, "unreviewed one", "")
	r.newAnalysis(t, unrev.ID, "grammar", "x", "rule-based:v2:fr_l2_taxonomy_v1")

	acc := r.newEntry(t, "accepted one", "")
	aAcc := r.newAnalysis(t, acc.ID, "grammar", "x", "rule-based:v2:fr_l2_taxonomy_v1")
	r.newFeedback(t, aAcc.ID, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})

	corr := r.newEntry(t, "corrected one", "")
	aCorr := r.newAnalysis(t, corr.ID, "grammar", "x", "rule-based:v2:fr_l2_taxonomy_v1")
	r.newFeedback(t, aCorr.ID, domain.NewFeedbackInput{Status: domain.FeedbackCorrected, CorrectedCategory: sptr("morphology")})

	rej := r.newEntry(t, "rejected one", "")
	aRej := r.newAnalysis(t, rej.ID, "grammar", "x", "rule-based:v2:fr_l2_taxonomy_v1")
	r.newFeedback(t, aRej.ID, domain.NewFeedbackInput{Status: domain.FeedbackRejected})

	cases := []struct {
		state  domain.LearningRecordState
		wantID int64
	}{
		{domain.LearningRecordUnanalyzed, unan.ID},
		{domain.LearningRecordUnreviewed, unrev.ID},
		{domain.LearningRecordAccepted, acc.ID},
		{domain.LearningRecordCorrected, corr.ID},
		{domain.LearningRecordRejected, rej.ID},
	}
	for _, tc := range cases {
		t.Run(string(tc.state), func(t *testing.T) {
			st := tc.state
			recs, err := r.inventory.ListLearningRecords(context2(), domain.LearningRecordQuery{State: &st, Limit: 200})
			if err != nil {
				t.Fatalf("list: %v", err)
			}
			if len(recs) != 1 {
				t.Fatalf("expected 1 record for state %q, got %d", tc.state, len(recs))
			}
			if recs[0].EntryID != tc.wantID {
				t.Fatalf("state %q returned entry %d, want %d", tc.state, recs[0].EntryID, tc.wantID)
			}
		})
	}
}

func TestInventory_CategoryFilterUsesEffective(t *testing.T) {
	r := newTestInventoryRepos(t)

	// Corrected to morphology: matches morphology, not the original grammar.
	corr := r.newEntry(t, "corrected", "")
	aCorr := r.newAnalysis(t, corr.ID, "grammar", "x", "rule-based:v2:fr_l2_taxonomy_v1")
	r.newFeedback(t, aCorr.ID, domain.NewFeedbackInput{Status: domain.FeedbackCorrected, CorrectedCategory: sptr("morphology")})

	// Plain unreviewed grammar entry.
	gram := r.newEntry(t, "grammar", "")
	r.newAnalysis(t, gram.ID, "grammar", "x", "rule-based:v2:fr_l2_taxonomy_v1")

	morph := domain.Category("morphology")
	recs, err := r.inventory.ListLearningRecords(context2(), domain.LearningRecordQuery{Category: &morph, Limit: 200})
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(recs) != 1 || recs[0].EntryID != corr.ID {
		t.Fatalf("morphology filter should return only the corrected entry, got %+v", recs)
	}

	// The original grammar category should no longer match the corrected entry.
	gramCat := domain.Category("grammar")
	recs, err = r.inventory.ListLearningRecords(context2(), domain.LearningRecordQuery{Category: &gramCat, Limit: 200})
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(recs) != 1 || recs[0].EntryID != gram.ID {
		t.Fatalf("grammar filter should return only the uncorrected grammar entry, got %+v", recs)
	}
}

func TestInventory_CategoryFilterExcludesRejectedAndUnanalyzed(t *testing.T) {
	r := newTestInventoryRepos(t)

	// Rejected grammar analysis: no effective category, so grammar filter skips it.
	rej := r.newEntry(t, "rejected grammar", "")
	aRej := r.newAnalysis(t, rej.ID, "grammar", "x", "rule-based:v2:fr_l2_taxonomy_v1")
	r.newFeedback(t, aRej.ID, domain.NewFeedbackInput{Status: domain.FeedbackRejected})

	// Unanalyzed entry: no effective category at all.
	r.newEntry(t, "unanalyzed", "")

	// One legitimate grammar entry to prove the filter still returns real matches.
	ok := r.newEntry(t, "real grammar", "")
	r.newAnalysis(t, ok.ID, "grammar", "x", "rule-based:v2:fr_l2_taxonomy_v1")

	gramCat := domain.Category("grammar")
	recs, err := r.inventory.ListLearningRecords(context2(), domain.LearningRecordQuery{Category: &gramCat, Limit: 200})
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(recs) != 1 || recs[0].EntryID != ok.ID {
		t.Fatalf("grammar filter should exclude rejected+unanalyzed, got %+v", recs)
	}
}

func TestInventory_AnalyzerFilterUsesLatestProvenanceExactMatch(t *testing.T) {
	r := newTestInventoryRepos(t)

	// Entry whose latest analysis is openai (older is rule-based) — the latest
	// provenance must be what the filter sees.
	e := r.newEntry(t, "je mange", "")
	r.newAnalysis(t, e.ID, "grammar", "v1", "rule-based:v2:fr_l2_taxonomy_v1")
	r.newAnalysis(t, e.ID, "grammar", "v2", "openai:gpt-x:fr_l2_taxonomy_v1")

	// A second entry that stays rule-based.
	other := r.newEntry(t, "bonjour", "")
	r.newAnalysis(t, other.ID, "vocabulary", "hi", "rule-based:v2:fr_l2_taxonomy_v1")

	openai := "openai:gpt-x:fr_l2_taxonomy_v1"
	recs, err := r.inventory.ListLearningRecords(context2(), domain.LearningRecordQuery{Analyzer: &openai, Limit: 200})
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(recs) != 1 || recs[0].EntryID != e.ID {
		t.Fatalf("analyzer filter should match latest provenance only, got %+v", recs)
	}

	// Exact match, not substring: "openai" alone must not match.
	partial := "openai"
	recs, err = r.inventory.ListLearningRecords(context2(), domain.LearningRecordQuery{Analyzer: &partial, Limit: 200})
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(recs) != 0 {
		t.Fatalf("analyzer filter must be exact, substring should match nothing, got %+v", recs)
	}
}

func TestInventory_DescendingOrderAndStablePagination(t *testing.T) {
	r := newTestInventoryRepos(t)
	var ids []int64
	for i := 0; i < 5; i++ {
		e := r.newEntry(t, "entry", "")
		ids = append(ids, e.ID)
	}
	// ids are ascending in creation order; descending order should reverse them.

	// First page of 2.
	page1, err := r.inventory.ListLearningRecords(context2(), domain.LearningRecordQuery{Limit: 2})
	if err != nil {
		t.Fatalf("page1: %v", err)
	}
	if len(page1) != 2 {
		t.Fatalf("page1 len = %d, want 2", len(page1))
	}
	if page1[0].EntryID != ids[4] || page1[1].EntryID != ids[3] {
		t.Fatalf("page1 not in descending id order: %d, %d", page1[0].EntryID, page1[1].EntryID)
	}

	// Second page using before_entry_id cursor = last id of page1.
	cursor := page1[1].EntryID
	page2, err := r.inventory.ListLearningRecords(context2(), domain.LearningRecordQuery{Limit: 2, BeforeEntryID: &cursor})
	if err != nil {
		t.Fatalf("page2: %v", err)
	}
	if len(page2) != 2 {
		t.Fatalf("page2 len = %d, want 2", len(page2))
	}
	if page2[0].EntryID != ids[2] || page2[1].EntryID != ids[1] {
		t.Fatalf("page2 wrong: %d, %d", page2[0].EntryID, page2[1].EntryID)
	}

	// Third page returns the final record.
	cursor = page2[1].EntryID
	page3, err := r.inventory.ListLearningRecords(context2(), domain.LearningRecordQuery{Limit: 2, BeforeEntryID: &cursor})
	if err != nil {
		t.Fatalf("page3: %v", err)
	}
	if len(page3) != 1 || page3[0].EntryID != ids[0] {
		t.Fatalf("page3 wrong: %+v", page3)
	}
}

func TestInventory_Summarize(t *testing.T) {
	r := newTestInventoryRepos(t)

	// 2 unanalyzed.
	r.newEntry(t, "u1", "")
	r.newEntry(t, "u2", "")

	// 1 unreviewed (rule-based, grammar).
	unrev := r.newEntry(t, "unrev", "")
	r.newAnalysis(t, unrev.ID, "grammar", "x", "rule-based:v2:fr_l2_taxonomy_v1")

	// 1 accepted (rule-based, vocabulary).
	acc := r.newEntry(t, "acc", "")
	aAcc := r.newAnalysis(t, acc.ID, "vocabulary", "x", "rule-based:v2:fr_l2_taxonomy_v1")
	r.newFeedback(t, aAcc.ID, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})

	// 1 corrected grammar->morphology (openai).
	corr := r.newEntry(t, "corr", "")
	aCorr := r.newAnalysis(t, corr.ID, "grammar", "x", "openai:gpt-x:fr_l2_taxonomy_v1")
	r.newFeedback(t, aCorr.ID, domain.NewFeedbackInput{Status: domain.FeedbackCorrected, CorrectedCategory: sptr("morphology")})

	// 1 rejected (openai, grammar) — contributes no effective category.
	rej := r.newEntry(t, "rej", "")
	aRej := r.newAnalysis(t, rej.ID, "grammar", "x", "openai:gpt-x:fr_l2_taxonomy_v1")
	r.newFeedback(t, aRej.ID, domain.NewFeedbackInput{Status: domain.FeedbackRejected})

	s, err := r.inventory.SummarizeLearningRecords(context2())
	if err != nil {
		t.Fatalf("summarize: %v", err)
	}

	if s.TotalEntries != 6 {
		t.Fatalf("total = %d, want 6", s.TotalEntries)
	}
	if s.UnanalyzedEntries != 2 {
		t.Fatalf("unanalyzed = %d, want 2", s.UnanalyzedEntries)
	}
	if s.AnalyzedEntries != 4 {
		t.Fatalf("analyzed = %d, want 4", s.AnalyzedEntries)
	}
	if s.AnalyzedEntries+s.UnanalyzedEntries != s.TotalEntries {
		t.Fatalf("analyzed+unanalyzed != total")
	}

	// State counts must sum to total, and every state key is present.
	var stateSum int64
	for _, st := range domain.LearningRecordStates() {
		if _, ok := s.ByState[st]; !ok {
			t.Fatalf("state key %q missing from summary", st)
		}
		stateSum += s.ByState[st]
	}
	if stateSum != s.TotalEntries {
		t.Fatalf("state counts sum = %d, want %d", stateSum, s.TotalEntries)
	}
	wantStates := map[domain.LearningRecordState]int64{
		domain.LearningRecordUnanalyzed: 2,
		domain.LearningRecordUnreviewed: 1,
		domain.LearningRecordAccepted:   1,
		domain.LearningRecordCorrected:  1,
		domain.LearningRecordRejected:   1,
	}
	for st, want := range wantStates {
		if s.ByState[st] != want {
			t.Fatalf("by_state[%q] = %d, want %d", st, s.ByState[st], want)
		}
	}

	// by_effective_category: unreviewed grammar (1), accepted vocabulary (1),
	// corrected morphology (1). Rejected + unanalyzed contribute nothing.
	wantCats := map[domain.Category]int64{
		"grammar":    1,
		"vocabulary": 1,
		"morphology": 1,
	}
	if len(s.ByEffectiveCategory) != len(wantCats) {
		t.Fatalf("by_effective_category = %+v, want %+v", s.ByEffectiveCategory, wantCats)
	}
	for c, want := range wantCats {
		if s.ByEffectiveCategory[c] != want {
			t.Fatalf("by_effective_category[%q] = %d, want %d", c, s.ByEffectiveCategory[c], want)
		}
	}

	// by_analyzer: latest provenance per analyzed entry. rule-based on unrev+acc
	// (2), openai on corr+rej (2).
	if s.ByAnalyzer["rule-based:v2:fr_l2_taxonomy_v1"] != 2 {
		t.Fatalf("by_analyzer rule-based = %d, want 2", s.ByAnalyzer["rule-based:v2:fr_l2_taxonomy_v1"])
	}
	if s.ByAnalyzer["openai:gpt-x:fr_l2_taxonomy_v1"] != 2 {
		t.Fatalf("by_analyzer openai = %d, want 2", s.ByAnalyzer["openai:gpt-x:fr_l2_taxonomy_v1"])
	}
}

func TestInventory_Summarize_Empty(t *testing.T) {
	r := newTestInventoryRepos(t)
	s, err := r.inventory.SummarizeLearningRecords(context2())
	if err != nil {
		t.Fatalf("summarize: %v", err)
	}
	if s.TotalEntries != 0 || s.AnalyzedEntries != 0 || s.UnanalyzedEntries != 0 {
		t.Fatalf("empty summary should be all zero, got %+v", s)
	}
	// Every state key still present at zero.
	for _, st := range domain.LearningRecordStates() {
		if v, ok := s.ByState[st]; !ok || v != 0 {
			t.Fatalf("state %q should be present at 0, got %d ok=%v", st, v, ok)
		}
	}
	if len(s.ByEffectiveCategory) != 0 || len(s.ByAnalyzer) != 0 {
		t.Fatalf("category/analyzer maps should be empty, got %+v %+v", s.ByEffectiveCategory, s.ByAnalyzer)
	}
}
