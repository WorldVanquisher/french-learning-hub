package publicdemo_test

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"french-learning-app/internal/application"
	"french-learning-app/internal/publicdemo"
	"french-learning-app/internal/storage/sqlite"
)

const fixturePath = "../../scripts/demo/flh073/fixtures/catalog.json"

func buildArtifact(t *testing.T) string {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "artifact")
	if _, err := publicdemo.Build(context.Background(), fixturePath, dir); err != nil {
		t.Fatal(err)
	}
	return dir
}

func copyDir(t *testing.T, src string) string {
	t.Helper()
	dst := filepath.Join(t.TempDir(), "copy")
	if err := os.MkdirAll(dst, 0o755); err != nil {
		t.Fatal(err)
	}
	entries, err := os.ReadDir(src)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		b, err := os.ReadFile(filepath.Join(src, e.Name()))
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dst, e.Name()), b, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return dst
}

func readJSON(t *testing.T, path string, v any) {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(b, v); err != nil {
		t.Fatal(err)
	}
}

func writeJSON(t *testing.T, path string, v any) {
	t.Helper()
	b, err := json.MarshalIndent(v, "", " ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, append(b, '\n'), 0o644); err != nil {
		t.Fatal(err)
	}
}

// rehash records a file's current SHA-256 in the manifest, simulating a
// consistent edit of both, so only the deeper checks can catch it.
func rehash(t *testing.T, dir, name string) {
	t.Helper()
	var m publicdemo.Manifest
	readJSON(t, filepath.Join(dir, publicdemo.ManifestFile), &m)
	sum, err := publicdemo.SHA256File(filepath.Join(dir, name))
	if err != nil {
		t.Fatal(err)
	}
	m.Files[name] = sum
	writeJSON(t, filepath.Join(dir, publicdemo.ManifestFile), m)
}

func TestBuild_ArtifactValidatesAndIsLabelledMechanical(t *testing.T) {
	dir := buildArtifact(t)
	a, db, err := publicdemo.OpenArtifact(context.Background(), dir)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	m := a.Manifest
	if !a.Mechanical() || m.Vectors.RealModel || m.ReleaseStatus != publicdemo.ReleaseBlockedMechanical ||
		!strings.Contains(m.Notice, "say nothing about semantic relevance") {
		t.Fatalf("manifest must label mechanical vectors: %+v", m)
	}
	if m.Vectors.QueryRepresentation != application.ConceptSearchQueryRepresentationV2 || m.Vectors.Dimensions != 64 || len(a.Presets) != 8 {
		t.Fatalf("identity/presets: %+v %d", m.Vectors, len(a.Presets))
	}
	if m.DomainFingerprint.Counts["knowledge_concepts"] != 12 || m.DomainFingerprint.Counts["learning_entries"] != 8 ||
		m.DomainFingerprint.Counts["unit_concept_memberships"] != 11 {
		t.Fatalf("counts = %v", m.DomainFingerprint.Counts)
	}
	for _, suffix := range []string{"-wal", "-shm"} {
		if _, err := os.Stat(a.DatabasePath() + suffix); err == nil {
			t.Fatalf("artifact has a %s file", suffix)
		}
	}
	// The database refuses writes.
	if _, err := db.Exec(`UPDATE knowledge_concepts SET target = 'x'`); err == nil || !strings.Contains(err.Error(), "readonly") {
		t.Fatalf("write must fail: %v", err)
	}
}

func TestBuild_VectorsAndFingerprintAreReproducible(t *testing.T) {
	a1, err := publicdemo.LoadArtifact(buildArtifact(t))
	if err != nil {
		t.Fatal(err)
	}
	a2, err := publicdemo.LoadArtifact(buildArtifact(t))
	if err != nil {
		t.Fatal(err)
	}
	m1, m2 := a1.Manifest, a2.Manifest
	if m1.Files[publicdemo.VectorsFile] != m2.Files[publicdemo.VectorsFile] || m1.DomainFingerprint.SHA256 != m2.DomainFingerprint.SHA256 ||
		m1.ArtifactVersion != m2.ArtifactVersion || m1.Files[publicdemo.FixturesFile] != m2.Files[publicdemo.FixturesFile] {
		t.Fatalf("not reproducible:\n%+v\n%+v", m1, m2)
	}
}

func TestBuild_RefusesNonEmptyOutputAndNonSyntheticFixtures(t *testing.T) {
	dir := buildArtifact(t)
	if _, err := publicdemo.Build(context.Background(), fixturePath, dir); err == nil {
		t.Fatal("a non-empty output directory must be refused")
	}
	var f map[string]any
	readJSON(t, fixturePath, &f)
	f["data_classification"] = "personal"
	bad := filepath.Join(t.TempDir(), "f.json")
	writeJSON(t, bad, f)
	if _, err := publicdemo.Build(context.Background(), bad, filepath.Join(t.TempDir(), "out")); err == nil {
		t.Fatal("non-synthetic fixtures must be refused")
	}
}

func TestOpenArtifact_RejectsMissingOrAlteredArtifacts(t *testing.T) {
	good := buildArtifact(t)
	cases := map[string]func(t *testing.T, dir string){
		"missing manifest": func(t *testing.T, dir string) { os.Remove(filepath.Join(dir, publicdemo.ManifestFile)) },
		"missing database": func(t *testing.T, dir string) { os.Remove(filepath.Join(dir, publicdemo.DatabaseFile)) },
		"missing vectors":  func(t *testing.T, dir string) { os.Remove(filepath.Join(dir, publicdemo.VectorsFile)) },
		"database bytes changed": func(t *testing.T, dir string) {
			f, _ := os.OpenFile(filepath.Join(dir, publicdemo.DatabaseFile), os.O_APPEND|os.O_WRONLY, 0)
			f.Write([]byte{0})
			f.Close()
		},
		"vector value changed (manifest stale)": func(t *testing.T, dir string) {
			var v publicdemo.Vectors
			readJSON(t, filepath.Join(dir, publicdemo.VectorsFile), &v)
			v.Documents[0].Vector[0] += 0.5
			writeJSON(t, filepath.Join(dir, publicdemo.VectorsFile), v)
		},
		"preset text changed, envelope kept": func(t *testing.T, dir string) {
			var v publicdemo.Vectors
			readJSON(t, filepath.Join(dir, publicdemo.VectorsFile), &v)
			v.Presets[0].Text = "how to tell a colleague I miss them"
			writeJSON(t, filepath.Join(dir, publicdemo.VectorsFile), v)
			rehash(t, dir, publicdemo.VectorsFile)
		},
		"preset envelope hash changed": func(t *testing.T, dir string) {
			var v publicdemo.Vectors
			readJSON(t, filepath.Join(dir, publicdemo.VectorsFile), &v)
			v.Presets[1].EnvelopeSHA256 = strings.Repeat("0", 64)
			writeJSON(t, filepath.Join(dir, publicdemo.VectorsFile), v)
			rehash(t, dir, publicdemo.VectorsFile)
		},
		"preset vector wrong dimension": func(t *testing.T, dir string) {
			var v publicdemo.Vectors
			readJSON(t, filepath.Join(dir, publicdemo.VectorsFile), &v)
			v.Presets[2].Vector = v.Presets[2].Vector[:10]
			writeJSON(t, filepath.Join(dir, publicdemo.VectorsFile), v)
			rehash(t, dir, publicdemo.VectorsFile)
		},
		"zero document vector": func(t *testing.T, dir string) {
			var v publicdemo.Vectors
			readJSON(t, filepath.Join(dir, publicdemo.VectorsFile), &v)
			v.Documents[3].Vector = make([]float64, 64)
			writeJSON(t, filepath.Join(dir, publicdemo.VectorsFile), v)
			rehash(t, dir, publicdemo.VectorsFile)
		},
		"document content hash changed": func(t *testing.T, dir string) {
			var v publicdemo.Vectors
			readJSON(t, filepath.Join(dir, publicdemo.VectorsFile), &v)
			v.Documents[0].ContentHash = strings.Repeat("a", 64)
			writeJSON(t, filepath.Join(dir, publicdemo.VectorsFile), v)
			rehash(t, dir, publicdemo.VectorsFile)
		},
		"concept without a vector": func(t *testing.T, dir string) {
			var v publicdemo.Vectors
			readJSON(t, filepath.Join(dir, publicdemo.VectorsFile), &v)
			v.Documents = v.Documents[1:]
			writeJSON(t, filepath.Join(dir, publicdemo.VectorsFile), v)
			rehash(t, dir, publicdemo.VectorsFile)
		},
		"duplicate preset": func(t *testing.T, dir string) {
			var v publicdemo.Vectors
			readJSON(t, filepath.Join(dir, publicdemo.VectorsFile), &v)
			v.Presets = append(v.Presets, v.Presets[0])
			writeJSON(t, filepath.Join(dir, publicdemo.VectorsFile), v)
			rehash(t, dir, publicdemo.VectorsFile)
		},
		"model identity changed in the manifest only": func(t *testing.T, dir string) {
			var m publicdemo.Manifest
			readJSON(t, filepath.Join(dir, publicdemo.ManifestFile), &m)
			m.Vectors.ModelID = "multilingual-e5-base@real"
			writeJSON(t, filepath.Join(dir, publicdemo.ManifestFile), m)
		},
		"mechanical vectors relabelled as a real model": func(t *testing.T, dir string) {
			var m publicdemo.Manifest
			readJSON(t, filepath.Join(dir, publicdemo.ManifestFile), &m)
			m.Vectors.Source, m.Vectors.RealModel = publicdemo.SourceModel, true
			m.ReleaseStatus = publicdemo.ReleaseModelVectors
			writeJSON(t, filepath.Join(dir, publicdemo.ManifestFile), m)
		},
		"query representation changed": func(t *testing.T, dir string) {
			var m publicdemo.Manifest
			readJSON(t, filepath.Join(dir, publicdemo.ManifestFile), &m)
			m.Vectors.QueryRepresentation = "concept_search_query_v1"
			writeJSON(t, filepath.Join(dir, publicdemo.ManifestFile), m)
		},
		"fingerprint changed": func(t *testing.T, dir string) {
			var m publicdemo.Manifest
			readJSON(t, filepath.Join(dir, publicdemo.ManifestFile), &m)
			m.DomainFingerprint.SHA256 = strings.Repeat("b", 64)
			writeJSON(t, filepath.Join(dir, publicdemo.ManifestFile), m)
		},
		"unknown manifest field": func(t *testing.T, dir string) {
			b, _ := os.ReadFile(filepath.Join(dir, publicdemo.ManifestFile))
			b = []byte(strings.Replace(string(b), "{", `{"extra": 1,`, 1))
			os.WriteFile(filepath.Join(dir, publicdemo.ManifestFile), b, 0o644)
		},
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			dir := copyDir(t, good)
			mutate(t, dir)
			a, db, err := publicdemo.OpenArtifact(context.Background(), dir)
			if !errors.Is(err, publicdemo.ErrArtifact) {
				if db != nil {
					db.Close()
				}
				t.Fatalf("want ErrArtifact, got %v (%v)", err, a)
			}
		})
	}
	// The unaltered artifact still opens.
	_, db, err := publicdemo.OpenArtifact(context.Background(), copyDir(t, good))
	if err != nil {
		t.Fatal(err)
	}
	db.Close()
}

func TestOpenReadOnly_RefusesOtherMigrationLedgers(t *testing.T) {
	dir := buildArtifact(t)
	// A normal (writable) open of a copy, then a ledger row is removed.
	copyPath := filepath.Join(t.TempDir(), "x.db")
	b, _ := os.ReadFile(filepath.Join(dir, publicdemo.DatabaseFile))
	os.WriteFile(copyPath, b, 0o644)
	db, err := sqlite.Open(copyPath)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`DELETE FROM schema_migrations WHERE name = (SELECT max(name) FROM schema_migrations)`); err != nil {
		t.Fatal(err)
	}
	db.Exec(`PRAGMA wal_checkpoint(TRUNCATE)`)
	db.Close()
	if _, err := publicdemo.OpenReadOnly(copyPath); !errors.Is(err, publicdemo.ErrArtifact) {
		t.Fatalf("ledger mismatch: %v", err)
	}
	if _, err := publicdemo.OpenReadOnly(filepath.Join(t.TempDir(), "missing.db")); err == nil {
		t.Fatal("a missing database must not be created")
	}
}

func TestPresetProviderAndIndexAreReadOnlyAndRefuseOtherText(t *testing.T) {
	a, err := publicdemo.LoadArtifact(buildArtifact(t))
	if err != nil {
		t.Fatal(err)
	}
	p := publicdemo.NewPresetQueryVectors(a)
	env, _ := application.ConceptSearchQueryEmbeddingText(a.Presets[0].Text)
	if v, err := p.Embed(context.Background(), []string{env}); err != nil || len(v) != 1 || len(v[0]) != 64 {
		t.Fatalf("preset lookup: %v", err)
	}
	for _, text := range []string{a.Presets[0].Text, `{"representation":"concept_search_query_v2","type":"query","text":"anything"}`, ""} {
		if _, err := p.Embed(context.Background(), []string{text}); !errors.Is(err, application.ErrEmbeddingProviderUnavailable) {
			t.Fatalf("%q must be refused: %v", text, err)
		}
	}
	if lookups, refused := p.Counters(); lookups != 1 || refused != 3 {
		t.Fatalf("counters = %d %d", lookups, refused)
	}
	idx := publicdemo.NewIndex(a)
	ctx := context.Background()
	if err := idx.CreateCollection(ctx, "x", 64); !errors.Is(err, publicdemo.ErrReadOnlyIndex) {
		t.Fatal("index must be read-only")
	}
	if err := idx.Upsert(ctx, a.Collection, a.Space, nil); !errors.Is(err, publicdemo.ErrReadOnlyIndex) {
		t.Fatal("index must be read-only")
	}
	if info, _ := idx.CollectionInfo(ctx, "other"); info.Exists {
		t.Fatal("only the artifact collection exists")
	}
	vec, _ := application.ValidateEmbedding(publicdemo.MechanicalEmbed(env, 64), 64)
	hits, err := idx.Query(ctx, a.Collection, vec, 5)
	if err != nil || len(hits) != 5 {
		t.Fatalf("query: %v %d", err, len(hits))
	}
	for i := 1; i < len(hits); i++ {
		if hits[i].Score > hits[i-1].Score {
			t.Fatal("hits not ordered")
		}
	}
	if st, _ := publicdemo.NewPublication(a).SpaceState(ctx, a.Space.Collection); st == nil || st.PublishedCollection != a.Collection {
		t.Fatalf("publication = %+v", st)
	}
}
