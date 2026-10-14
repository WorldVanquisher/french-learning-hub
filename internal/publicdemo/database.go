package publicdemo

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io/fs"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/storage/sqlite"
	"french-learning-app/migrations"

	_ "modernc.org/sqlite"
)

// OpenReadOnly opens an existing database read-only and immutable: SQLite
// refuses every write, takes no lock and creates no -wal/-shm file. The
// migration ledger must equal the embedded migrations exactly; nothing is
// migrated.
func OpenReadOnly(path string) (*sql.DB, error) {
	u := url.URL{Scheme: "file", Path: path, RawQuery: "mode=ro&immutable=1&_pragma=foreign_keys(ON)"}
	db, err := sql.Open("sqlite", u.String())
	if err != nil {
		return nil, fail("open database: %v", err)
	}
	if err := db.Ping(); err != nil {
		db.Close()
		return nil, fail("open database: %v", err)
	}
	if err := checkMigrations(db); err != nil {
		db.Close()
		return nil, err
	}
	return db, nil
}

func checkMigrations(db *sql.DB) error {
	entries, err := fs.ReadDir(migrations.Files, ".")
	if err != nil {
		return err
	}
	var want []string
	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), ".sql") {
			want = append(want, e.Name())
		}
	}
	rows, err := db.Query(`SELECT name FROM schema_migrations ORDER BY name`)
	if err != nil {
		return fail("database has no migration ledger: %v", err)
	}
	defer rows.Close()
	var got []string
	for rows.Next() {
		var n string
		if err := rows.Scan(&n); err != nil {
			return err
		}
		got = append(got, n)
	}
	if err := rows.Err(); err != nil {
		return err
	}
	sort.Strings(want)
	if strings.Join(got, ",") != strings.Join(want, ",") {
		return fail("database migrations %v differ from this server's %v", got, want)
	}
	return nil
}

// FingerprintVersion names the domain-fingerprint contract. v1 (FLH-073,
// manifests without a version) omitted admission recommendations, the
// current-extraction selection and the order of latest-wins records, so a
// change to them could keep a valid fingerprint; v1 artifacts are refused.
const FingerprintVersion = "flh075_domain_fingerprint_v2"

// fingerprintContent lists, for every table that public-library reads depend
// on, the columns that carry domain meaning. Absolute timestamps are excluded
// (they only label records); where "latest wins" reads order rows by
// created_at, the row's position in that order is included instead (order_rank,
// computed across all ordered tables because effective annotation compares
// SAME, DISTINCT and relation events with each other).
var fingerprintContent = []struct{ table, query string }{
	{"learning_entries", `SELECT id, original_input, original_context FROM learning_entries ORDER BY id`},
	{"entry_analyses", `SELECT id, entry_id, version, category, explanation, confidence, uncertainty, analyzer FROM entry_analyses ORDER BY id`},
	{"analysis_feedback", `SELECT id, analysis_id, status, corrected_category, corrected_explanation, user_note FROM analysis_feedback ORDER BY id`},
	{"knowledge_extractions", `SELECT id, entry_id, version, source_analysis_id, source_feedback_id, extractor FROM knowledge_extractions ORDER BY id`},
	{"entry_current_extractions", `SELECT entry_id, extraction_id FROM entry_current_extractions ORDER BY entry_id`},
	{"knowledge_units", `SELECT id, extraction_id, ordinal, kind, canonical, statement, example, confidence FROM knowledge_units ORDER BY id`},
	{"knowledge_admission_recommendations", `SELECT id, unit_id, ruleset, state, reason FROM knowledge_admission_recommendations ORDER BY id`},
	{"knowledge_admission_overrides", `SELECT id, unit_id, decision, reason, note FROM knowledge_admission_overrides ORDER BY id`},
	{"knowledge_concepts", `SELECT id, identity_schema_version, target, pedagogical_intent, scope, identity_features, signature, preferred_unit_id, lifecycle_state FROM knowledge_concepts ORDER BY id`},
	{"unit_concept_links", `SELECT id, unit_id, concept_id, relation, status, decision_source, resolver_version, score, evidence, supersedes_link_id FROM unit_concept_links ORDER BY id`},
	{"unit_concept_memberships", `SELECT unit_id, concept_id, link_id FROM unit_concept_memberships ORDER BY unit_id`},
	{"unit_concept_distinctions", `SELECT id, unit_id, concept_id, decision_source, resolver_version, evidence FROM unit_concept_distinctions ORDER BY id`},
	{"unit_resolution_judgments", `SELECT id, unit_id, judgment, decision_source, note, evidence FROM unit_resolution_judgments ORDER BY id`},
	{"learning_captures", `SELECT id, capture_id, entry_id, analysis_id, source, schema_version, discussion_summary, content_fingerprint FROM learning_captures ORDER BY id`},
}

// orderedTables are read "latest by created_at, then id". Their rows get a
// global order rank.
var orderedTables = []string{"analysis_feedback", "knowledge_admission_recommendations", "knowledge_admission_overrides",
	"unit_concept_links", "unit_concept_distinctions", "unit_resolution_judgments"}

// emptyTables must hold no rows in a demo artifact: semantic index state is
// replaced by the artifact's own vectors, and the demo records no operations.
var emptyTables = []string{"annotation_operations", "semantic_embedding_cache", "semantic_index_collections",
	"semantic_index_manifest", "semantic_index_physical_collections", "semantic_index_points", "semantic_index_spaces"}

// unfingerprintedTables are bookkeeping, checked elsewhere or not data.
var unfingerprintedTables = map[string]string{
	"schema_migrations": "checked exactly against the embedded migrations",
	"sqlite_sequence":   "autoincrement counters, not domain data",
}

// FingerprintTables reports every table the fingerprint covers, by kind.
func FingerprintTables() (content, empty []string, skipped map[string]string) {
	for _, c := range fingerprintContent {
		content = append(content, c.table)
	}
	return content, append([]string{}, emptyTables...), unfingerprintedTables
}

type orderKey struct {
	table string
	id    int64
}

// orderRanks ranks every row of the ordered tables by its created_at instant
// (parsed as RFC 3339; equal instants share a rank). Unparseable timestamps
// rank after all valid ones and their raw text is digested, so corruption is
// visible.
func orderRanks(ctx context.Context, db *sql.DB) (map[orderKey]string, error) {
	type row struct {
		key   orderKey
		at    time.Time
		raw   string
		valid bool
	}
	var rows []row
	for _, t := range orderedTables {
		rs, err := db.QueryContext(ctx, `SELECT id, created_at FROM `+t)
		if err != nil {
			return nil, fmt.Errorf("order %s: %w", t, err)
		}
		for rs.Next() {
			var r row
			r.key.table = t
			if err := rs.Scan(&r.key.id, &r.raw); err != nil {
				rs.Close()
				return nil, err
			}
			at, err := time.Parse(time.RFC3339Nano, r.raw)
			r.at, r.valid = at, err == nil
			rows = append(rows, r)
		}
		if err := rs.Err(); err != nil {
			rs.Close()
			return nil, err
		}
		rs.Close()
	}
	sort.SliceStable(rows, func(i, j int) bool {
		a, b := rows[i], rows[j]
		if a.valid != b.valid {
			return a.valid
		}
		if a.valid && !a.at.Equal(b.at) {
			return a.at.Before(b.at)
		}
		if !a.valid && a.raw != b.raw {
			return a.raw < b.raw
		}
		if a.key.table != b.key.table {
			return a.key.table < b.key.table
		}
		return a.key.id < b.key.id
	})
	ranks := map[orderKey]string{}
	rank := 0
	for i, r := range rows {
		if i == 0 || !(r.valid == rows[i-1].valid && (r.valid && r.at.Equal(rows[i-1].at) || !r.valid && r.raw == rows[i-1].raw)) {
			rank++
		}
		if r.valid {
			ranks[r.key] = strconv.Itoa(rank)
		} else {
			ranks[r.key] = "invalid:" + r.raw
		}
	}
	return ranks, nil
}

// ComputeFingerprint digests the database's domain content (FingerprintVersion).
func ComputeFingerprint(ctx context.Context, db *sql.DB) (DomainFingerprint, error) {
	fp := DomainFingerprint{Version: FingerprintVersion, Counts: map[string]int{}}
	ranks, err := orderRanks(ctx, db)
	if err != nil {
		return fp, err
	}
	ordered := map[string]bool{}
	for _, t := range orderedTables {
		ordered[t] = true
	}
	h := sha256.New()
	fmt.Fprintf(h, "%s\n", FingerprintVersion)
	for _, q := range fingerprintContent {
		rows, err := db.QueryContext(ctx, q.query)
		if err != nil {
			return fp, fmt.Errorf("fingerprint %s: %w", q.table, err)
		}
		cols, _ := rows.Columns()
		n := 0
		fmt.Fprintf(h, "%s\n", q.table)
		for rows.Next() {
			vals := make([]any, len(cols))
			ptrs := make([]any, len(cols))
			for i := range vals {
				ptrs[i] = &vals[i]
			}
			if err := rows.Scan(ptrs...); err != nil {
				rows.Close()
				return fp, err
			}
			for i, v := range vals {
				if b, ok := v.([]byte); ok {
					vals[i] = string(b)
				}
			}
			if ordered[q.table] {
				id, _ := vals[0].(int64)
				vals = append(vals, ranks[orderKey{q.table, id}])
			}
			line, _ := json.Marshal(vals)
			h.Write(line)
			h.Write([]byte("\n"))
			n++
		}
		if err := rows.Err(); err != nil {
			rows.Close()
			return fp, err
		}
		rows.Close()
		fp.Counts[q.table] = n
	}
	for _, t := range emptyTables {
		var n int
		if err := db.QueryRowContext(ctx, `SELECT count(*) FROM `+t).Scan(&n); err != nil {
			return fp, fmt.Errorf("fingerprint %s: %w", t, err)
		}
		fmt.Fprintf(h, "%s %d\n", t, n)
		fp.Counts[t] = n
	}
	fp.SHA256 = hex.EncodeToString(h.Sum(nil))
	return fp, nil
}

// OpenArtifact loads the artifact, opens its database read-only, and checks
// the database fingerprint and that every current Concept has exactly the
// recorded document vector (same content hash), with no vector left over.
func OpenArtifact(ctx context.Context, dir string) (*Artifact, *sql.DB, error) {
	a, err := LoadArtifact(dir)
	if err != nil {
		return nil, nil, err
	}
	db, err := OpenReadOnly(a.DatabasePath())
	if err != nil {
		return nil, nil, err
	}
	if err := a.verifyDatabase(ctx, db); err != nil {
		db.Close()
		return nil, nil, err
	}
	return a, db, nil
}

func equalCounts(a, b map[string]int) bool {
	if len(a) != len(b) {
		return false
	}
	for k, v := range a {
		if b[k] != v {
			return false
		}
	}
	return true
}

func (a *Artifact) verifyDatabase(ctx context.Context, db *sql.DB) error {
	fp, err := ComputeFingerprint(ctx, db)
	if err != nil {
		return fail("fingerprint: %v", err)
	}
	if fp.SHA256 != a.Manifest.DomainFingerprint.SHA256 || !equalCounts(fp.Counts, a.Manifest.DomainFingerprint.Counts) {
		return fail("database fingerprint differs from the manifest")
	}
	for _, t := range emptyTables {
		if fp.Counts[t] != 0 {
			return fail("demo database must not carry %s rows", t)
		}
	}
	concepts, err := sqlite.NewConceptRepository(db).ListConcepts(ctx, nil)
	if err != nil {
		return fail("list concepts: %v", err)
	}
	if len(concepts) != len(a.documents) {
		return fail("%d concepts but %d document vectors", len(concepts), len(a.documents))
	}
	for _, c := range concepts {
		d, ok := a.documents[c.ID]
		if !ok {
			return fail("concept %d has no document vector", c.ID)
		}
		doc, err := application.BuildSemanticIndexDocument(c)
		if err != nil {
			return fail("concept %d document: %v", c.ID, err)
		}
		if doc.ContentHash != d.hash {
			return fail("concept %d document hash differs from its vector's", c.ID)
		}
	}
	return nil
}
