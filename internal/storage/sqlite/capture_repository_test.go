package sqlite

import (
	"context"
	"errors"
	"path/filepath"
	"sync"
	"testing"

	"french-learning-app/internal/domain"
)

func newTestCaptureRepo(t *testing.T) (*CaptureRepository, *sqlDBHandles) {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "capture.db")
	db, err := Open(dbPath)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return NewCaptureRepository(db), &sqlDBHandles{
		entries:   NewEntryRepository(db),
		analyses:  NewAnalysisRepository(db),
		inventory: NewInventoryRepository(db),
		captures:  NewCaptureRepository(db),
	}
}

// sqlDBHandles bundles repositories sharing one database for cross-checks.
type sqlDBHandles struct {
	entries   *EntryRepository
	analyses  *AnalysisRepository
	inventory *InventoryRepository
	captures  *CaptureRepository
}

// preparedCapture builds a valid PreparedLearningCapture (as the service would),
// with an optional analysis.
func preparedCapture(captureID string, withAnalysis bool) domain.PreparedLearningCapture {
	in := domain.NewLearningCaptureInput{
		SchemaVersion:     domain.CaptureSchemaV1,
		CaptureID:         captureID,
		Source:            domain.CaptureSourceChatGPTWeb,
		OriginalInput:     "Je parle japonais ?",
		OriginalContext:   "article after parler",
		DiscussionSummary: "compared parler japonais and apprendre le japonais",
	}
	if withAnalysis {
		in.Analysis = &domain.ImportedAnalysisInput{
			Category:    "grammar",
			Explanation: "no article after parler",
			Confidence:  0.9,
			Uncertainty: "varies by construction",
		}
	}
	// Validate to normalize, then build the prepared form + fingerprint.
	_ = in.Validate()
	p := domain.PreparedLearningCapture{
		CaptureID:         in.CaptureID,
		Source:            in.Source,
		SchemaVersion:     in.SchemaVersion,
		OriginalInput:     in.OriginalInput,
		OriginalContext:   in.OriginalContext,
		DiscussionSummary: in.DiscussionSummary,
	}
	if in.Analysis != nil {
		r := in.Analysis.AsAnalysisResult()
		p.Analysis = &r
		p.AnalyzerProvenance = domain.ImportedAnalysisProvenance(in.Source)
	}
	p.ContentFingerprint = domain.CaptureFingerprint(p)
	return p
}

func countRows(t *testing.T, r *CaptureRepository, table string) int {
	t.Helper()
	var n int
	if err := r.db.QueryRowContext(context.Background(), "SELECT COUNT(*) FROM "+table).Scan(&n); err != nil {
		t.Fatalf("count %s: %v", table, err)
	}
	return n
}

func TestCaptureRepo_CreateWithAnalysis(t *testing.T) {
	repo, h := newTestCaptureRepo(t)
	ctx := context.Background()

	res, err := repo.Create(ctx, preparedCapture("cap-1", true))
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if !res.Created {
		t.Fatal("expected Created=true")
	}
	if res.EntryID == 0 {
		t.Fatal("expected non-zero entry id")
	}
	if res.AnalysisID == nil {
		t.Fatal("expected analysis id for capture with analysis")
	}

	// Entry exists with the original data.
	entry, err := h.entries.GetByID(ctx, res.EntryID)
	if err != nil {
		t.Fatalf("get entry: %v", err)
	}
	if entry.OriginalInput != "Je parle japonais ?" {
		t.Fatalf("entry input wrong: %q", entry.OriginalInput)
	}

	// Analysis is version 1 with imported provenance.
	analyses, err := h.analyses.ListByEntry(ctx, res.EntryID)
	if err != nil {
		t.Fatalf("list analyses: %v", err)
	}
	if len(analyses) != 1 {
		t.Fatalf("expected 1 analysis, got %d", len(analyses))
	}
	if analyses[0].Version != 1 {
		t.Fatalf("analysis version = %d, want 1", analyses[0].Version)
	}
	if analyses[0].Analyzer != "imported:chatgpt-web:learning_capture_v1" {
		t.Fatalf("provenance = %q", analyses[0].Analyzer)
	}
}

func TestCaptureRepo_CreateWithoutAnalysis(t *testing.T) {
	repo, h := newTestCaptureRepo(t)
	ctx := context.Background()

	res, err := repo.Create(ctx, preparedCapture("cap-noan", false))
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if res.AnalysisID != nil {
		t.Fatalf("expected nil analysis id, got %v", *res.AnalysisID)
	}
	analyses, err := h.analyses.ListByEntry(ctx, res.EntryID)
	if err != nil {
		t.Fatalf("list analyses: %v", err)
	}
	if len(analyses) != 0 {
		t.Fatalf("expected no analyses, got %d", len(analyses))
	}
}

func TestCaptureRepo_MetadataPointsToEntry(t *testing.T) {
	repo, _ := newTestCaptureRepo(t)
	ctx := context.Background()

	res, err := repo.Create(ctx, preparedCapture("cap-meta", true))
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	got, err := repo.GetByCaptureID(ctx, "cap-meta")
	if err != nil {
		t.Fatalf("lookup: %v", err)
	}
	if got.EntryID != res.EntryID {
		t.Fatalf("capture entry id = %d, want %d", got.EntryID, res.EntryID)
	}
	if got.AnalysisID == nil || *got.AnalysisID != *res.AnalysisID {
		t.Fatalf("capture analysis id = %v, want %v", got.AnalysisID, res.AnalysisID)
	}
	if got.Source != domain.CaptureSourceChatGPTWeb || got.SchemaVersion != domain.CaptureSchemaV1 {
		t.Fatalf("metadata wrong: %+v", got)
	}
}

func TestCaptureRepo_ExactRepeatNoDuplicate(t *testing.T) {
	repo, _ := newTestCaptureRepo(t)
	ctx := context.Background()

	first, err := repo.Create(ctx, preparedCapture("cap-rep", true))
	if err != nil {
		t.Fatalf("first create: %v", err)
	}
	second, err := repo.Create(ctx, preparedCapture("cap-rep", true))
	if err != nil {
		t.Fatalf("repeat create: %v", err)
	}
	if second.Created {
		t.Fatal("exact repeat should have Created=false")
	}
	if second.EntryID != first.EntryID || *second.AnalysisID != *first.AnalysisID {
		t.Fatalf("repeat returned different ids: %+v vs %+v", second, first)
	}
	if got := countRows(t, repo, "learning_captures"); got != 1 {
		t.Fatalf("expected 1 capture row, got %d", got)
	}
	if got := countRows(t, repo, "learning_entries"); got != 1 {
		t.Fatalf("expected 1 entry row, got %d", got)
	}
	if got := countRows(t, repo, "entry_analyses"); got != 1 {
		t.Fatalf("expected 1 analysis row, got %d", got)
	}
}

func TestCaptureRepo_ConflictingRepeat(t *testing.T) {
	repo, _ := newTestCaptureRepo(t)
	ctx := context.Background()

	if _, err := repo.Create(ctx, preparedCapture("cap-conf", true)); err != nil {
		t.Fatalf("first create: %v", err)
	}

	// Same capture id, different content -> different fingerprint -> conflict.
	changed := preparedCapture("cap-conf", true)
	changed.OriginalInput = "completely different question"
	changed.ContentFingerprint = domain.CaptureFingerprint(changed)

	_, err := repo.Create(ctx, changed)
	if !errors.Is(err, domain.ErrConflict) {
		t.Fatalf("expected ErrConflict, got %v", err)
	}
	// Nothing extra written.
	if got := countRows(t, repo, "learning_captures"); got != 1 {
		t.Fatalf("expected 1 capture row after conflict, got %d", got)
	}
	if got := countRows(t, repo, "learning_entries"); got != 1 {
		t.Fatalf("expected 1 entry row after conflict, got %d", got)
	}
}

func TestCaptureRepo_RollbackOnAnalysisFailure(t *testing.T) {
	repo, _ := newTestCaptureRepo(t)
	ctx := context.Background()

	// Force a genuine mid-transaction failure: after the entry is inserted, the
	// analysis insert targets entry_analyses. Dropping that table makes the insert
	// fail with "no such table" while the fast-path check (which only reads
	// learning_captures) still works. The whole transaction must roll back, so no
	// orphan learning_entries row may survive.
	if _, err := repo.db.ExecContext(ctx, "DROP TABLE entry_analyses"); err != nil {
		t.Fatalf("drop entry_analyses: %v", err)
	}

	_, err := repo.Create(ctx, preparedCapture("cap-analysis-fail", true))
	if err == nil {
		t.Fatal("expected analysis insert to fail")
	}
	if errors.Is(err, domain.ErrConflict) {
		t.Fatalf("expected a storage error, not conflict: %v", err)
	}
	if got := countRows(t, repo, "learning_entries"); got != 0 {
		t.Fatalf("entry not rolled back after analysis failure: %d rows", got)
	}
	if got := countRows(t, repo, "learning_captures"); got != 0 {
		t.Fatalf("receipt not rolled back after analysis failure: %d rows", got)
	}
}

func TestCaptureRepo_RollbackOnReceiptFailure(t *testing.T) {
	repo, _ := newTestCaptureRepo(t)
	ctx := context.Background()

	// Force a genuine mid-transaction failure at the last step: an abort trigger on
	// learning_captures lets the fast-path read succeed and the entry + analysis
	// inserts succeed, then aborts the receipt insert. The whole transaction must
	// roll back, leaving no orphan entry or analysis.
	if _, err := repo.db.ExecContext(ctx,
		`CREATE TRIGGER fail_capture_insert BEFORE INSERT ON learning_captures
		 BEGIN SELECT RAISE(ABORT, 'forced receipt failure'); END;`); err != nil {
		t.Fatalf("create trigger: %v", err)
	}

	_, err := repo.Create(ctx, preparedCapture("cap-receipt-fail", true))
	if err == nil {
		t.Fatal("expected receipt insert to fail")
	}
	if errors.Is(err, domain.ErrConflict) {
		t.Fatalf("expected a storage error, not conflict: %v", err)
	}
	if got := countRows(t, repo, "learning_entries"); got != 0 {
		t.Fatalf("entry not rolled back after receipt failure: %d rows", got)
	}
	if got := countRows(t, repo, "entry_analyses"); got != 0 {
		t.Fatalf("analysis not rolled back after receipt failure: %d rows", got)
	}
}

// TestCaptureRepo_PreM8DataReadable proves the M8 migration is additive: rows
// created before the capture table existed remain readable, and a new capture
// can be imported afterward without disturbing them.
func TestCaptureRepo_PreM8DataReadable(t *testing.T) {
	repo, h := newTestCaptureRepo(t)
	ctx := context.Background()

	// Simulate a pre-M8 entry: an ordinary learning entry with no capture receipt.
	pre, err := h.entries.Create(ctx, domain.NewEntryInput{
		OriginalInput:   "pre-existing question",
		OriginalContext: "created before M8",
	})
	if err != nil {
		t.Fatalf("seed pre-M8 entry: %v", err)
	}

	// The M8 capture flow works alongside it.
	res, err := repo.Create(ctx, preparedCapture("cap-after-migration", true))
	if err != nil {
		t.Fatalf("create capture: %v", err)
	}

	// The pre-M8 entry is still readable and unchanged.
	got, err := h.entries.GetByID(ctx, pre.ID)
	if err != nil {
		t.Fatalf("read pre-M8 entry: %v", err)
	}
	if got.OriginalInput != "pre-existing question" {
		t.Fatalf("pre-M8 entry changed: %q", got.OriginalInput)
	}
	if got.ID == res.EntryID {
		t.Fatal("capture reused the pre-M8 entry instead of creating a new one")
	}
}

func TestCaptureRepo_ConcurrentIdentical(t *testing.T) {
	repo, _ := newTestCaptureRepo(t)
	ctx := context.Background()

	const n = 8
	var wg sync.WaitGroup
	results := make([]domain.LearningCaptureResult, n)
	errs := make([]error, n)
	wg.Add(n)
	for i := 0; i < n; i++ {
		go func(idx int) {
			defer wg.Done()
			results[idx], errs[idx] = repo.Create(ctx, preparedCapture("cap-concurrent", true))
		}(i)
	}
	wg.Wait()

	createdCount := 0
	var entryID int64
	for i := 0; i < n; i++ {
		if errs[i] != nil {
			t.Fatalf("goroutine %d error: %v", i, errs[i])
		}
		if results[i].Created {
			createdCount++
		}
		if entryID == 0 {
			entryID = results[i].EntryID
		} else if results[i].EntryID != entryID {
			t.Fatalf("concurrent submissions returned different entry ids: %d vs %d", results[i].EntryID, entryID)
		}
	}
	if createdCount != 1 {
		t.Fatalf("exactly one submission should create; got %d", createdCount)
	}
	if got := countRows(t, repo, "learning_entries"); got != 1 {
		t.Fatalf("expected 1 entry, got %d", got)
	}
	if got := countRows(t, repo, "learning_captures"); got != 1 {
		t.Fatalf("expected 1 capture, got %d", got)
	}
}

func TestCaptureRepo_ConcurrentConflicting(t *testing.T) {
	repo, _ := newTestCaptureRepo(t)
	ctx := context.Background()

	const n = 8
	var wg sync.WaitGroup
	results := make([]domain.LearningCaptureResult, n)
	errs := make([]error, n)
	wg.Add(n)
	for i := 0; i < n; i++ {
		go func(idx int) {
			defer wg.Done()
			// Each goroutine uses the same capture_id but content that differs by
			// index, so at most one can win and the rest are replay-or-conflict.
			p := preparedCapture("cap-cc", true)
			p.OriginalContext = "variant-" + string(rune('a'+idx))
			p.ContentFingerprint = domain.CaptureFingerprint(p)
			results[idx], errs[idx] = repo.Create(ctx, p)
		}(i)
	}
	wg.Wait()

	createdCount, conflictCount, replayCount := 0, 0, 0
	for i := 0; i < n; i++ {
		switch {
		case errs[i] == nil && results[i].Created:
			createdCount++
		case errs[i] == nil && !results[i].Created:
			replayCount++
		case errors.Is(errs[i], domain.ErrConflict):
			conflictCount++
		default:
			t.Fatalf("goroutine %d unexpected error: %v", i, errs[i])
		}
	}
	if createdCount != 1 {
		t.Fatalf("exactly one create expected, got %d", createdCount)
	}
	// Every other goroutine used different content, so they conflict (none replay).
	if conflictCount != n-1 {
		t.Fatalf("expected %d conflicts, got %d (replays=%d)", n-1, conflictCount, replayCount)
	}
	if got := countRows(t, repo, "learning_entries"); got != 1 {
		t.Fatalf("expected 1 entry after concurrent conflict, got %d", got)
	}
}

func TestCaptureRepo_LookupMissing(t *testing.T) {
	repo, _ := newTestCaptureRepo(t)
	_, err := repo.GetByCaptureID(context.Background(), "does-not-exist")
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

func TestCaptureRepo_CapturedRecordInInventory(t *testing.T) {
	repo, h := newTestCaptureRepo(t)
	ctx := context.Background()

	res, err := repo.Create(ctx, preparedCapture("cap-inv", true))
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	recs, err := h.inventory.ListLearningRecords(ctx, domain.LearningRecordQuery{Limit: 50})
	if err != nil {
		t.Fatalf("inventory list: %v", err)
	}
	var found *domain.LearningRecord
	for _, rec := range recs {
		if rec.EntryID == res.EntryID {
			found = rec
		}
	}
	if found == nil {
		t.Fatal("captured entry not in inventory")
	}
	if found.State != domain.LearningRecordUnreviewed {
		t.Fatalf("state = %q, want unreviewed", found.State)
	}
	if found.Analyzer == nil || *found.Analyzer != "imported:chatgpt-web:learning_capture_v1" {
		t.Fatalf("inventory analyzer = %v", found.Analyzer)
	}
	if found.Effective == nil || found.Effective.Category != "grammar" {
		t.Fatalf("effective should equal imported analysis, got %+v", found.Effective)
	}
	if found.FeedbackID != nil {
		t.Fatalf("feedback id should be nil, got %v", *found.FeedbackID)
	}
}
