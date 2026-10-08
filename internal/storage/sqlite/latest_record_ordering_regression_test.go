package sqlite

import (
	"context"
	"database/sql"
	"path/filepath"
	"slices"
	"testing"
	"time"

	"french-learning-app/internal/domain"
)

// FLH-004: assert chronological created_at ordering, with ID only for equal
// instants. Variable-width cases cover historical timestamp text.
// Equal-time and wall-clock rollback cases are independent controls.
// Existing helpers create migrated databases exclusively in t.TempDir().
func TestLatestRecordOrderingRegression(t *testing.T) {
	base := time.Date(2026, 10, 7, 12, 0, 0, 0, time.UTC)
	cases := []struct {
		name          string
		first, second time.Time
	}{
		{"whole_second_then_fraction", base, base.Add(100 * time.Millisecond)},
		{"fraction_prefix", base.Add(100 * time.Millisecond), base.Add(110 * time.Millisecond)},
		{"nanosecond_prefix", base.Add(100 * time.Millisecond), base.Add(100*time.Millisecond + time.Nanosecond)},
		{"equal_instant_offset", base, base.In(time.FixedZone("plus_one", 3600))},
		{"equal_timestamp", base.Add(123 * time.Millisecond), base.Add(123 * time.Millisecond)},
		// A later insertion with an earlier wall time is NOT chronologically latest.
		// Switching to ID-only ordering would change this existing contract.
		{"wall_clock_rollback", base.Add(2 * time.Second), base.Add(time.Second)},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Run("feedback", func(t *testing.T) {
				ctx := context.Background()
				entries, analyses, repo := newTestFeedbackRepos(t)
				analysis := seedAnalysis(t, entries, analyses)
				repo.now = func() time.Time { return tc.first }
				first, err := repo.Create(ctx, analysis.ID, domain.NewFeedbackInput{Status: domain.FeedbackRejected})
				if err != nil {
					t.Fatal(err)
				}
				repo.now = func() time.Time { return tc.second }
				second, err := repo.Create(ctx, analysis.ID, domain.NewFeedbackInput{Status: domain.FeedbackAccepted})
				if err != nil {
					t.Fatal(err)
				}
				latest, err := repo.GetLatestByAnalysis(ctx, analysis.ID)
				if err != nil {
					t.Fatal(err)
				}
				if latest == nil {
					t.Fatal("missing latest feedback")
				}
				wantID := flh004ChronologicalLatest(t, repo.db, "analysis_feedback", first.ID, second.ID)
				want := first
				if wantID == second.ID {
					want = second
				}
				flh004AssertLatest(t, latest.ID, wantID)
				gotEffective := domain.ResolveEffective(analysis, latest)
				wantEffective := domain.ResolveEffective(analysis, want)
				if gotEffective.Resolution != wantEffective.Resolution {
					t.Errorf("effective analysis = %s, chronological resolution = %s", gotEffective.Resolution, wantEffective.Resolution)
				}
				inventory := NewInventoryRepository(repo.db)
				state := domain.StateFromResolution(wantEffective.Resolution)
				records, err := inventory.ListLearningRecords(ctx, domain.LearningRecordQuery{State: &state, Limit: 10})
				if err != nil {
					t.Fatal(err)
				}
				if len(records) != 1 || records[0].FeedbackID == nil || *records[0].FeedbackID != wantID || records[0].State != state {
					t.Errorf("filtered inventory must select chronological feedback %d, state %s: %+v", wantID, state, records)
				}
				summary, err := inventory.SummarizeLearningRecords(ctx)
				if err != nil {
					t.Fatal(err)
				}
				if summary.ByState[state] != 1 {
					t.Errorf("inventory summary = %+v; want one %s", summary.ByState, state)
				}

			})
			t.Run("admission_override", func(t *testing.T) {
				ctx := context.Background()
				entries, knowledge, repo, concepts := newConceptTestRepos(t)
				view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("FLH-004 synthetic unit")})
				unitID := view.Units[0].Unit.ID
				repo.now = func() time.Time { return tc.first }
				first, err := repo.Create(ctx, unitID, domain.NewAdmissionOverrideInput{Decision: domain.HumanAdmitSuppressed, Reason: domain.HumanReasonOther})
				if err != nil {
					t.Fatal(err)
				}
				repo.now = func() time.Time { return tc.second }
				second, err := repo.Create(ctx, unitID, domain.NewAdmissionOverrideInput{Decision: domain.HumanAdmitActive})
				if err != nil {
					t.Fatal(err)
				}
				got, err := repo.GetAdmission(ctx, unitID)
				if err != nil {
					t.Fatal(err)
				}
				if got.LatestOverride == nil {
					t.Fatal("missing latest override")
				}
				wantID := flh004ChronologicalLatest(t, repo.db, "knowledge_admission_overrides", first.ID, second.ID)
				want := first
				if wantID == second.ID {
					want = second
				}
				flh004AssertLatest(t, got.LatestOverride.ID, wantID)
				wantEffective := domain.ResolveAdmission(got.Recommendation, want).Effective
				if got.Effective != wantEffective {
					t.Errorf("admission = %s, chronological admission = %s", got.Effective, wantEffective)
				}
				// Concept support has another SQL latest-override query; check agreement
				// against the same chronological oracle without changing membership.
				supportAdmission, err := effectiveAdmissionState(ctx, concepts.db, unitID)
				if err != nil {
					t.Fatal(err)
				}
				if supportAdmission != wantEffective {
					t.Errorf("concept support admission = %s, chronological admission = %s", supportAdmission, wantEffective)
				}
				concept := mustConcept(t, concepts, domain.DeriveCandidateIdentity(view.Units[0].Unit))
				if _, err := concepts.LinkSame(ctx, unitID, concept.ID, domain.SourceHuman, nil, ""); err != nil {
					t.Fatal(err)
				}
				support, err := concepts.ActiveSupportUnitIDs(ctx, concept.ID)
				if err != nil {
					t.Fatal(err)
				}
				wantSupport := 0
				if wantEffective == domain.AdmissionActive {
					wantSupport = 1
				}
				if len(support) != wantSupport {
					t.Errorf("support units = %v; want count %d", support, wantSupport)
				}
				history, err := repo.ListByUnit(ctx, unitID)
				if err != nil {
					t.Fatal(err)
				}
				if len(history) != 2 || history[1].ID != wantID {
					t.Errorf("admission history must end with chronological latest %d: %+v", wantID, history)
				}

			})
			t.Run("invalid_restore", func(t *testing.T) {
				ctx := context.Background()
				entries, knowledge, _, repo := newConceptTestRepos(t)
				view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("FLH-004 synthetic unit")})
				unitID := view.Units[0].Unit.ID
				repo.now = func() time.Time { return tc.first }
				first, err := repo.MarkUnitInvalid(ctx, unitID, domain.SourceHuman, "", "")
				if err != nil {
					t.Fatal(err)
				}
				repo.now = func() time.Time { return tc.second }
				second, err := repo.RestoreUnit(ctx, unitID, domain.SourceHuman, "", "")
				if err != nil {
					t.Fatal(err)
				}
				if first == nil || second == nil {
					t.Fatal("expected both INVALID and restored events")
				}
				latest, err := repo.LatestUnitJudgment(ctx, unitID)
				if err != nil {
					t.Fatal(err)
				}
				if latest == nil {
					t.Fatal("missing latest judgment")
				}
				wantID := flh004ChronologicalLatest(t, repo.db, "unit_resolution_judgments", first.ID, second.ID)
				want := first
				if wantID == second.ID {
					want = second
				}
				flh004AssertLatest(t, latest.ID, wantID)
				// The Go resolver consumes the supplied latest judgment; it does not
				// reselect from history or repair incorrect SQL ordering.
				gotSnapshot, err := domain.ResolveEffectiveAnnotation(unitID, latest, nil, nil, nil)
				if err != nil {
					t.Fatal(err)
				}
				wantSnapshot, err := domain.ResolveEffectiveAnnotation(unitID, want, nil, nil, nil)
				if err != nil {
					t.Fatal(err)
				}
				if gotSnapshot.Status != wantSnapshot.Status {
					t.Errorf("annotation = %s, chronological annotation = %s", gotSnapshot.Status, wantSnapshot.Status)
				}
				queue, err := repo.ListReviewableUnits(ctx, nil)
				if err != nil {
					t.Fatal(err)
				}
				wantCount := 1
				if domain.EffectiveUnitInvalid(want) {
					wantCount = 0
				}
				if len(queue) != wantCount {
					t.Errorf("review queue count = %d, want %d", len(queue), wantCount)
				}
				history, err := repo.ListUnitJudgments(ctx, unitID)
				if err != nil {
					t.Fatal(err)
				}
				if len(history) != 2 || history[0].ID != wantID {
					t.Errorf("judgment history must start with chronological latest %d: %+v", wantID, history)
				}

			})
		})
	}
}

// Read the actual persisted text and compare parsed instants, not string order.
// Table names are fixed test literals; IDs are parameterized. This oracle never
// changes stored records and preserves nanosecond precision and the ID tie-break.
func flh004ChronologicalLatest(t *testing.T, db *sql.DB, table string, firstID, secondID int64) int64 {
	t.Helper()
	rows, err := db.Query(`SELECT id, created_at FROM `+table+` WHERE id IN (?, ?) ORDER BY id`, firstID, secondID)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var wantID int64
	var latestTime time.Time
	count := 0
	for rows.Next() {
		var id int64
		var raw string
		if err := rows.Scan(&id, &raw); err != nil {
			t.Fatal(err)
		}
		parsed, err := time.Parse(time.RFC3339Nano, raw)
		if err != nil {
			t.Fatal(err)
		}
		t.Logf("%s id=%d stored=%q", table, id, raw)
		if count == 0 || parsed.After(latestTime) || (parsed.Equal(latestTime) && id > wantID) {
			wantID, latestTime = id, parsed
		}
		count++
	}
	if err := rows.Err(); err != nil {
		t.Fatal(err)
	}
	if count != 2 {
		t.Fatalf("persisted rows = %d, want 2", count)
	}
	return wantID
}

func flh004AssertLatest(t *testing.T, gotID, wantID int64) {
	t.Helper()
	if gotID != wantID {
		t.Errorf("SQL selected id=%d; parsed chronological ordering (created_at, then id) selects id=%d", gotID, wantID)
	}
}

// Existing timestamps remain unchanged across reads/reopen. This also exercises
// registration on a new connection, historical fixed-width fractions, offsets,
// and differences smaller than SQLite date functions' millisecond precision.
func TestTimestampOrderingHistoricalRows(t *testing.T) {
	path := filepath.Join(t.TempDir(), "historical.db")
	db, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })
	if _, err := db.Exec(`CREATE TABLE ordering_evidence (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL)`); err != nil {
		t.Fatal(err)
	}
	timestamps := []string{
		"2026-10-07T12:00:00.100000001Z",
		"2026-10-07T12:00:00.1Z",
		"2026-10-07T13:00:00.100000000+01:00",
		"2026-10-07T12:00:00Z",
	}
	for i, raw := range timestamps {
		if _, err := db.Exec(`INSERT INTO ordering_evidence VALUES (?, ?)`, i+1, raw); err != nil {
			t.Fatal(err)
		}
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	db, err = Open(path)
	if err != nil {
		t.Fatal(err)
	}
	rows, err := db.Query(`SELECT id, created_at FROM ordering_evidence ORDER BY created_at COLLATE flh_timestamp_v1 DESC, id DESC`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var ids []int
	for rows.Next() {
		var id int
		var raw string
		if err := rows.Scan(&id, &raw); err != nil {
			t.Fatal(err)
		}
		ids = append(ids, id)
		if raw != timestamps[id-1] {
			t.Errorf("timestamp rewritten: %q, want %q", raw, timestamps[id-1])
		}
	}
	if err := rows.Err(); err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(ids, []int{1, 3, 2, 4}) {
		t.Errorf("historical order = %v, want [1 3 2 4]", ids)
	}
}

func TestTimestampOrderingInvalidLatestFailsRead(t *testing.T) {
	entries, analyses, repo := newTestFeedbackRepos(t)
	analysis := seedAnalysis(t, entries, analyses)
	ctx := context.Background()
	bad, err := repo.Create(ctx, analysis.ID, domain.NewFeedbackInput{Status: domain.FeedbackRejected})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := repo.Create(ctx, analysis.ID, domain.NewFeedbackInput{Status: domain.FeedbackAccepted}); err != nil {
		t.Fatal(err)
	}
	// Corrupt only this isolated fixture; the collation must not hide the malformed
	// timestamp by preferring a valid row and silently returning effective state.
	if _, err := repo.db.Exec(`UPDATE analysis_feedback SET created_at = ? WHERE id = ?`, "!invalid", bad.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := repo.GetLatestByAnalysis(ctx, analysis.ID); err == nil {
		t.Fatal("expected timestamp parse error")
	}
}
