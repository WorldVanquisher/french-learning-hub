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
	"strings"

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

// fingerprintQueries select content columns only (no timestamps), so the same
// fixture always produces the same fingerprint.
var fingerprintQueries = []struct{ name, query string }{
	{"learning_entries", `SELECT id, original_input, original_context FROM learning_entries ORDER BY id`},
	{"entry_analyses", `SELECT id, entry_id, version, category, explanation, confidence, uncertainty, analyzer FROM entry_analyses ORDER BY id`},
	{"analysis_feedback", `SELECT id, analysis_id, status, corrected_category, corrected_explanation, user_note FROM analysis_feedback ORDER BY id`},
	{"knowledge_extractions", `SELECT id, entry_id, version, source_analysis_id, source_feedback_id, extractor FROM knowledge_extractions ORDER BY id`},
	{"knowledge_units", `SELECT id, extraction_id, ordinal, kind, canonical, statement, example, confidence FROM knowledge_units ORDER BY id`},
	{"knowledge_admission_overrides", `SELECT id, unit_id, decision, reason, note FROM knowledge_admission_overrides ORDER BY id`},
	{"knowledge_concepts", `SELECT id, identity_schema_version, target, pedagogical_intent, scope, identity_features, signature, preferred_unit_id, lifecycle_state FROM knowledge_concepts ORDER BY id`},
	{"unit_concept_links", `SELECT id, unit_id, concept_id, relation, status, decision_source, resolver_version, supersedes_link_id FROM unit_concept_links ORDER BY id`},
	{"unit_concept_memberships", `SELECT unit_id, concept_id, link_id FROM unit_concept_memberships ORDER BY unit_id`},
	{"unit_concept_distinctions", `SELECT id, unit_id, concept_id, decision_source FROM unit_concept_distinctions ORDER BY id`},
	{"unit_resolution_judgments", `SELECT id, unit_id, judgment, decision_source, note FROM unit_resolution_judgments ORDER BY id`},
	{"learning_captures", `SELECT id, capture_id, entry_id FROM learning_captures ORDER BY id`},
	{"semantic_embedding_cache", `SELECT content_hash FROM semantic_embedding_cache ORDER BY content_hash`},
	{"semantic_index_spaces", `SELECT space FROM semantic_index_spaces ORDER BY space`},
}

// ComputeFingerprint digests the database content.
func ComputeFingerprint(ctx context.Context, db *sql.DB) (DomainFingerprint, error) {
	h := sha256.New()
	fp := DomainFingerprint{Counts: map[string]int{}}
	for _, q := range fingerprintQueries {
		rows, err := db.QueryContext(ctx, q.query)
		if err != nil {
			return fp, fmt.Errorf("fingerprint %s: %w", q.name, err)
		}
		cols, _ := rows.Columns()
		n := 0
		fmt.Fprintf(h, "%s\n", q.name)
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
		fp.Counts[q.name] = n
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

func (a *Artifact) verifyDatabase(ctx context.Context, db *sql.DB) error {
	fp, err := ComputeFingerprint(ctx, db)
	if err != nil {
		return fail("fingerprint: %v", err)
	}
	if fp.SHA256 != a.Manifest.DomainFingerprint.SHA256 {
		return fail("database fingerprint differs from the manifest")
	}
	if fp.Counts["semantic_embedding_cache"] != 0 || fp.Counts["semantic_index_spaces"] != 0 {
		return fail("demo database must not carry semantic index state")
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
