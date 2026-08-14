package sqlite

import (
	"context"
	"database/sql"
	"fmt"
	"io/fs"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/domain"
	"french-learning-app/migrations"
)

// migrationNames returns every embedded *.sql migration filename in lexical order,
// so the ledger tests assert against the real migration set rather than a
// hard-coded count.
func migrationNames(t *testing.T) []string {
	t.Helper()
	entries, err := fs.ReadDir(migrations.Files, ".")
	if err != nil {
		t.Fatalf("read migrations dir: %v", err)
	}
	var names []string
	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), ".sql") {
			names = append(names, e.Name())
		}
	}
	sort.Strings(names)
	return names
}

// appliedLedger reads the schema_migrations ledger from an open database.
func appliedLedger(t *testing.T, db *sql.DB) []string {
	t.Helper()
	rows, err := db.Query(`SELECT name FROM schema_migrations ORDER BY name`)
	if err != nil {
		t.Fatalf("read schema_migrations: %v", err)
	}
	defer rows.Close()
	var names []string
	for rows.Next() {
		var n string
		if err := rows.Scan(&n); err != nil {
			t.Fatalf("scan ledger row: %v", err)
		}
		names = append(names, n)
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("ledger rows: %v", err)
	}
	return names
}

// applyRaw applies the named migrations to a raw database connection WITHOUT the
// ledger, simulating an on-disk schema produced by an earlier version of the app
// that ran every migration on each Open.
func applyRaw(t *testing.T, path string, names []string) {
	t.Helper()
	dsn := fmt.Sprintf("file:%s?_pragma=busy_timeout(5000)&_pragma=journal_mode(WAL)&_pragma=foreign_keys(ON)", path)
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		t.Fatalf("open raw db: %v", err)
	}
	defer db.Close()
	db.SetMaxOpenConns(1)
	for _, name := range names {
		b, err := migrations.Files.ReadFile(name)
		if err != nil {
			t.Fatalf("read %s: %v", name, err)
		}
		if _, err := db.Exec(string(b)); err != nil {
			t.Fatalf("exec %s: %v", name, err)
		}
	}
}

// TestMigrationLedger_ReopenDoesNotReapply proves the ledger applies each migration
// exactly once: a fresh database migrates 001..007, and reopening it neither
// re-runs migration 007's non-idempotent ALTER statements (which would fail on the
// already-dropped `state` column) nor duplicates ledger rows. Existing data
// survives the reopen.
func TestMigrationLedger_ReopenDoesNotReapply(t *testing.T) {
	ctx := context.Background()
	dbPath := filepath.Join(t.TempDir(), "ledger.db")

	db, err := Open(dbPath)
	if err != nil {
		t.Fatalf("first open: %v", err)
	}

	// Seed a concept so we can prove data survives the reopen.
	concepts := NewConceptRepository(db)
	created := mustConcept(t, concepts, domain.ConceptIdentity{Target: "vouloir", PedagogicalIntent: "grammar"})

	all := migrationNames(t)
	ledger := appliedLedger(t, db)
	if len(ledger) != len(all) {
		t.Fatalf("ledger after first open = %v, want one row per migration %v", ledger, all)
	}
	for i, name := range all {
		if ledger[i] != name {
			t.Fatalf("ledger[%d] = %q, want %q", i, ledger[i], name)
		}
	}
	db.Close()

	// Reopen: this must succeed. If migration 007 re-ran, its `ALTER TABLE ... DROP
	// COLUMN state` would error because the column is already gone — so a clean
	// reopen is itself proof the non-idempotent migration was not re-executed.
	db2, err := Open(dbPath)
	if err != nil {
		t.Fatalf("reopen must not re-apply non-idempotent migrations: %v", err)
	}
	defer db2.Close()

	// The ledger still has exactly one row per migration (no duplicates).
	ledger2 := appliedLedger(t, db2)
	if len(ledger2) != len(all) {
		t.Fatalf("ledger after reopen = %v, want %v (no duplicates)", ledger2, all)
	}

	// The seeded concept survives.
	got, err := NewConceptRepository(db2).GetConcept(ctx, created.ID)
	if err != nil {
		t.Fatalf("seeded concept lost after reopen: %v", err)
	}
	if got.Concept.Signature != created.Signature {
		t.Fatalf("concept changed across reopen: %q vs %q", got.Concept.Signature, created.Signature)
	}
}

// TestMigrationLedger_UpgradeFromMigration006 exercises the real upgrade path: a
// database whose on-disk schema is post-006 / pre-007 and has no schema_migrations
// table (an older app version that ran every migration on each Open). Opening it
// through the current migration system must create the ledger, apply 007 exactly
// once, preserve the M10.5 concept/unit/SAME data, backfill
// unit_concept_memberships from the existing accepted SAME, populate lifecycle_state
// (including carrying a 'retired' state across), and remove the stale `state`
// column.
func TestMigrationLedger_UpgradeFromMigration006(t *testing.T) {
	ctx := context.Background()
	dbPath := filepath.Join(t.TempDir(), "upgrade006.db")

	// 1. Build a post-006 / pre-007 schema (no ledger), applying only 001..006.
	all := migrationNames(t)
	var upTo006 []string
	for _, n := range all {
		upTo006 = append(upTo006, n)
		if strings.HasPrefix(n, "006_") {
			break
		}
	}
	applyRaw(t, dbPath, upTo006)

	// 2. Seed M10.5 data directly in the 006 schema (which has knowledge_concepts.state
	//    and unit_concept_links WITHOUT supersedes_link_id, and no memberships table).
	seed := func() (unitID, normalConceptID, retiredConceptID, sameLinkID int64) {
		dsn := fmt.Sprintf("file:%s?_pragma=foreign_keys(ON)", dbPath)
		raw, err := sql.Open("sqlite", dsn)
		if err != nil {
			t.Fatalf("open seed db: %v", err)
		}
		raw.SetMaxOpenConns(1)
		defer raw.Close()
		ts := time.Now().UTC().Format(rfc3339)

		exec := func(q string, args ...any) sql.Result {
			res, err := raw.ExecContext(ctx, q, args...)
			if err != nil {
				t.Fatalf("seed exec %q: %v", q, err)
			}
			return res
		}

		entryRes := exec(`INSERT INTO learning_entries (original_input, original_context, created_at, updated_at) VALUES (?, ?, ?, ?)`,
			"q", "c", ts, ts)
		entryID, _ := entryRes.LastInsertId()
		anRes := exec(`INSERT INTO entry_analyses (entry_id, version, category, explanation, confidence, uncertainty, analyzer, created_at) VALUES (?, 1, 'grammar', 'e', 0.8, '', 'rule-based:test', ?)`,
			entryID, ts)
		analysisID, _ := anRes.LastInsertId()
		exRes := exec(`INSERT INTO knowledge_extractions (entry_id, version, source_analysis_id, source_feedback_id, extractor, created_at) VALUES (?, 1, ?, NULL, 'openai:test', ?)`,
			entryID, analysisID, ts)
		extractionID, _ := exRes.LastInsertId()
		uRes := exec(`INSERT INTO knowledge_units (extraction_id, ordinal, kind, canonical, statement, example, confidence, created_at) VALUES (?, 0, 'grammar', 'vouloir + inf', 's', NULL, 0.9, ?)`,
			extractionID, ts)
		unitID, _ = uRes.LastInsertId()
		// Machine recommendation so effective admission resolves to active.
		exec(`INSERT INTO knowledge_admission_recommendations (unit_id, ruleset, state, reason, created_at) VALUES (?, 'knowledge_admission_v1', 'active', 'default_active', ?)`,
			unitID, ts)

		// A 'normal' concept (state='active' in 006) with the unit linked SAME/accepted.
		nRes := exec(`INSERT INTO knowledge_concepts (identity_schema_version, target, pedagogical_intent, scope, identity_features, signature, preferred_unit_id, state, created_at, updated_at) VALUES (?, 'vouloir + infinitive', 'grammar', '', '{}', 'sig-normal', NULL, 'active', ?, ?)`,
			domain.ConceptIdentitySchemaVersion, ts, ts)
		normalConceptID, _ = nRes.LastInsertId()
		lRes := exec(`INSERT INTO unit_concept_links (unit_id, concept_id, relation, status, decision_source, resolver_version, score, evidence, created_at) VALUES (?, ?, 'same', 'accepted', 'human', 'concept_resolver_v1', NULL, '{}', ?)`,
			unitID, normalConceptID, ts)
		sameLinkID, _ = lRes.LastInsertId()

		// A 'retired' concept, to prove the lifecycle backfill carries it across.
		rRes := exec(`INSERT INTO knowledge_concepts (identity_schema_version, target, pedagogical_intent, scope, identity_features, signature, preferred_unit_id, state, created_at, updated_at) VALUES (?, 'old', 'grammar', '', '{}', 'sig-retired', NULL, 'retired', ?, ?)`,
			domain.ConceptIdentitySchemaVersion, ts, ts)
		retiredConceptID, _ = rRes.LastInsertId()
		return unitID, normalConceptID, retiredConceptID, sameLinkID
	}
	unitID, normalConceptID, retiredConceptID, sameLinkID := seed()

	// 3. Open through the current migration system: this creates the ledger and
	//    applies 007 exactly once.
	db, err := Open(dbPath)
	if err != nil {
		t.Fatalf("open (upgrade to 007): %v", err)
	}
	defer db.Close()

	// The ledger now records every migration once.
	ledger := appliedLedger(t, db)
	if len(ledger) != len(all) {
		t.Fatalf("ledger after upgrade = %v, want %v", ledger, all)
	}

	// The stale `state` column is gone.
	if _, err := db.ExecContext(ctx, `SELECT state FROM knowledge_concepts LIMIT 1`); err == nil {
		t.Fatal("expected knowledge_concepts.state to be removed by 007")
	}

	// lifecycle_state is populated: the active concept is 'normal', the retired one
	// carried across to 'retired'.
	lifecycleOf := func(id int64) string {
		var lc string
		if err := db.QueryRowContext(ctx, `SELECT lifecycle_state FROM knowledge_concepts WHERE id = ?`, id).Scan(&lc); err != nil {
			t.Fatalf("read lifecycle_state for %d: %v", id, err)
		}
		return lc
	}
	if got := lifecycleOf(normalConceptID); got != "normal" {
		t.Fatalf("normal concept lifecycle_state = %q, want normal", got)
	}
	if got := lifecycleOf(retiredConceptID); got != "retired" {
		t.Fatalf("retired concept lifecycle_state = %q, want retired", got)
	}

	// unit_concept_memberships was backfilled from the existing accepted SAME link.
	concepts := NewConceptRepository(db)
	m, err := concepts.GetCurrentMembership(ctx, unitID)
	if err != nil {
		t.Fatalf("get current membership after upgrade: %v", err)
	}
	if m == nil || m.ConceptID != normalConceptID || m.LinkID != sameLinkID {
		t.Fatalf("membership must be backfilled to the accepted SAME link, got %+v", m)
	}

	// The concept data survived and support is derived: the unit belongs to the
	// current extraction, is admission-active, and holds the current SAME → active.
	view, err := concepts.GetConcept(ctx, normalConceptID)
	if err != nil {
		t.Fatalf("get concept after upgrade: %v", err)
	}
	if view.Concept.Signature != "sig-normal" {
		t.Fatalf("concept signature changed: %q", view.Concept.Signature)
	}
	if view.Concept.State != domain.ConceptActive {
		t.Fatalf("upgraded concept should derive active support, got %q", view.Concept.State)
	}

	// Reopening again is a no-op (ledger prevents 007 from re-running).
	db.Close()
	db2, err := Open(dbPath)
	if err != nil {
		t.Fatalf("second reopen after upgrade: %v", err)
	}
	defer db2.Close()
	if l2 := appliedLedger(t, db2); len(l2) != len(all) {
		t.Fatalf("ledger after second reopen = %v, want %v", l2, all)
	}
}
