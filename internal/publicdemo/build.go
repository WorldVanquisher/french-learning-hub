package publicdemo

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
)

const (
	FixturesSchema = "flh073_demo_fixtures_v1"

	// MechanicalGenerator is signed feature hashing over normalized tokens. It is
	// deterministic test plumbing with no semantic meaning.
	MechanicalGenerator  = "flh073_mechanical_hash_v1"
	MechanicalModelID    = "flh073-mechanical-hash@1"
	MechanicalDimensions = 64
	DemoSpacePrefix      = "flh073_demo"

	FixtureAnalyzer  = "fixture:flh073:" + domain.TaxonomyVersion
	FixtureExtractor = "fixture:flh073:knowledge_extraction_v1"

	MechanicalNotice = "Mechanical test vectors (feature hashing of words). Semantic and hybrid rankings in this " +
		"artifact show the ranking mechanics only; they say nothing about semantic relevance."
)

// Fixtures is the synthetic catalog the artifact is built from.
type Fixtures struct {
	Schema             string           `json:"schema"`
	DataClassification string           `json:"data_classification"`
	Note               string           `json:"note"`
	Entries            []FixtureEntry   `json:"entries"`
	Concepts           []FixtureConcept `json:"concepts"`
	Presets            []FixturePreset  `json:"presets"`
}

type FixtureEntry struct {
	Key             string          `json:"key"`
	OriginalInput   string          `json:"original_input"`
	OriginalContext string          `json:"original_context"`
	Analysis        FixtureAnalysis `json:"analysis"`
	Units           []FixtureUnit   `json:"units"`
}

type FixtureAnalysis struct {
	Category    string  `json:"category"`
	Explanation string  `json:"explanation"`
	Confidence  float64 `json:"confidence"`
}

type FixtureUnit struct {
	Key       string  `json:"key"`
	Kind      string  `json:"kind"`
	Canonical string  `json:"canonical"`
	Statement string  `json:"statement"`
	Example   *string `json:"example"`
}

type FixtureConcept struct {
	Key               string            `json:"key"`
	Target            string            `json:"target"`
	PedagogicalIntent string            `json:"pedagogical_intent"`
	Scope             string            `json:"scope"`
	IdentityFeatures  map[string]string `json:"identity_features"`
	Members           []string          `json:"members"`
	Preferred         string            `json:"preferred"`
}

type FixturePreset struct {
	ID    string `json:"id"`
	Label string `json:"label"`
	Text  string `json:"text"`
}

// MechanicalEmbed is signed feature hashing of the text's normalized tokens,
// L2-normalized. Same text, same vector; it encodes word overlap only.
func MechanicalEmbed(text string, dims int) []float64 {
	v := make([]float64, dims)
	for _, tok := range application.NormalizeConceptLexicalTokens(text) {
		h := sha256.Sum256([]byte("flh073:" + tok))
		i := binary.BigEndian.Uint32(h[:4]) % uint32(dims)
		if h[4]&1 == 1 {
			v[i]--
		} else {
			v[i]++
		}
	}
	var n float64
	for _, x := range v {
		n += x * x
	}
	if n == 0 {
		v[0] = 1
		return v
	}
	n = math.Sqrt(n)
	for i := range v {
		v[i] /= n
	}
	return v
}

type scriptedExtractor struct {
	byEntry map[int64][]domain.ExtractedUnit
}

func (s scriptedExtractor) Name() string { return FixtureExtractor }
func (s scriptedExtractor) Extract(_ context.Context, src domain.ExtractionSource) (domain.ExtractionResult, error) {
	return domain.ExtractionResult{Units: s.byEntry[src.EntryID]}, nil
}

// ReadFixtures parses and checks a fixture file.
func ReadFixtures(path string) (*Fixtures, []byte, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, nil, err
	}
	var f Fixtures
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&f); err != nil {
		return nil, nil, fmt.Errorf("fixtures: %w", err)
	}
	if f.Schema != FixturesSchema || f.DataClassification != "synthetic" {
		return nil, nil, errors.New("fixtures must be schema " + FixturesSchema + " and marked synthetic")
	}
	if len(f.Presets) == 0 || len(f.Presets) > MaxPresets {
		return nil, nil, fmt.Errorf("fixtures need 1..%d presets", MaxPresets)
	}
	return &f, raw, nil
}

// Build seeds a new database through the real application services, computes
// mechanical vectors, writes the artifact into outDir (which must not exist or
// be empty) and validates it with the server's own loader.
func Build(ctx context.Context, fixturesPath, outDir string) (*Artifact, error) {
	f, raw, err := ReadFixtures(fixturesPath)
	if err != nil {
		return nil, err
	}
	if entries, err := os.ReadDir(outDir); err == nil && len(entries) > 0 {
		return nil, fmt.Errorf("%s exists and is not empty", outDir)
	}
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		return nil, err
	}
	dbPath := filepath.Join(outDir, DatabaseFile)
	if err := seed(ctx, f, dbPath); err != nil {
		return nil, err
	}
	ro, err := OpenReadOnly(dbPath)
	if err != nil {
		return nil, err
	}
	fp, err := ComputeFingerprint(ctx, ro)
	if err != nil {
		ro.Close()
		return nil, err
	}
	concepts, err := sqlite.NewConceptRepository(ro).ListConcepts(ctx, nil)
	ro.Close()
	if err != nil {
		return nil, err
	}

	identity := VectorIdentity{Source: SourceMechanical, RealModel: false, Generator: MechanicalGenerator, ModelID: MechanicalModelID,
		Dimensions: MechanicalDimensions, DocumentRepresentation: application.ConceptIndexRepresentationV1,
		QueryRepresentation: application.ConceptSearchQueryRepresentationV2}
	vec := Vectors{Schema: VectorsSchema, Identity: identity}
	for _, c := range concepts {
		doc, err := application.BuildSemanticIndexDocument(c)
		if err != nil {
			return nil, err
		}
		vec.Documents = append(vec.Documents, DocumentVector{ConceptID: c.ID, ContentHash: doc.ContentHash, Vector: MechanicalEmbed(doc.Text, identity.Dimensions)})
	}
	for _, p := range f.Presets {
		env, err := application.ConceptSearchQueryEmbeddingText(p.Text)
		if err != nil {
			return nil, fmt.Errorf("preset %s: %w", p.ID, err)
		}
		vec.Presets = append(vec.Presets, PresetVector{ID: p.ID, Label: p.Label, Text: p.Text, Envelope: env,
			EnvelopeSHA256: sha256Hex(env), Vector: MechanicalEmbed(env, identity.Dimensions)})
	}
	vecBytes, err := json.MarshalIndent(vec, "", " ")
	if err != nil {
		return nil, err
	}
	if err := os.WriteFile(filepath.Join(outDir, VectorsFile), append(vecBytes, '\n'), 0o644); err != nil {
		return nil, err
	}
	if err := os.WriteFile(filepath.Join(outDir, FixturesFile), raw, 0o644); err != nil {
		return nil, err
	}
	files := map[string]string{}
	for _, name := range []string{DatabaseFile, VectorsFile, FixturesFile} {
		if files[name], err = SHA256File(filepath.Join(outDir, name)); err != nil {
			return nil, err
		}
	}
	version := sha256.Sum256([]byte(files[FixturesFile] + "\x00" + files[VectorsFile] + "\x00" + fp.SHA256))
	m := Manifest{Schema: ManifestSchema, ArtifactVersion: hex.EncodeToString(version[:])[:16], Generator: "scripts/demo/flh073/prepare build",
		Files: files, Vectors: identity, SpacePrefix: DemoSpacePrefix, DomainFingerprint: fp,
		ReleaseStatus: ReleaseBlockedMechanical, Notice: MechanicalNotice}
	mBytes, err := json.MarshalIndent(m, "", " ")
	if err != nil {
		return nil, err
	}
	if err := os.WriteFile(filepath.Join(outDir, ManifestFile), append(mBytes, '\n'), 0o644); err != nil {
		return nil, err
	}
	a, db, err := OpenArtifact(ctx, outDir)
	if err != nil {
		return nil, fmt.Errorf("the built artifact does not validate: %w", err)
	}
	db.Close()
	return a, nil
}

func seed(ctx context.Context, f *Fixtures, dbPath string) error {
	db, err := sqlite.Open(dbPath)
	if err != nil {
		return err
	}
	entryRepo := sqlite.NewEntryRepository(db)
	analysisRepo := sqlite.NewAnalysisRepository(db)
	knowledgeRepo := sqlite.NewKnowledgeRepository(db)
	conceptRepo := sqlite.NewConceptRepository(db)
	extractor := scriptedExtractor{byEntry: map[int64][]domain.ExtractedUnit{}}
	knowledgeSvc := application.NewKnowledgeService(entryRepo, analysisRepo, sqlite.NewFeedbackRepository(db), knowledgeRepo, sqlite.NewAdmissionRepository(db), extractor)
	conceptSvc := application.NewConceptService(knowledgeRepo, conceptRepo, conceptRepo)

	units := map[string]int64{}
	for _, e := range f.Entries {
		entry, err := entryRepo.Create(ctx, domain.NewEntryInput{OriginalInput: e.OriginalInput, OriginalContext: e.OriginalContext})
		if err != nil {
			return fmt.Errorf("entry %s: %w", e.Key, err)
		}
		if _, err := analysisRepo.Create(ctx, entry.ID, domain.AnalysisResult{Category: domain.Category(e.Analysis.Category),
			Explanation: e.Analysis.Explanation, Confidence: e.Analysis.Confidence}, FixtureAnalyzer); err != nil {
			return fmt.Errorf("analysis %s: %w", e.Key, err)
		}
		var extracted []domain.ExtractedUnit
		for _, u := range e.Units {
			extracted = append(extracted, domain.ExtractedUnit{Kind: domain.KnowledgeKind(u.Kind), Canonical: u.Canonical, Statement: u.Statement, Example: u.Example, Confidence: 0.9})
		}
		extractor.byEntry[entry.ID] = extracted
		view, err := knowledgeSvc.Extract(ctx, entry.ID)
		if err != nil {
			return fmt.Errorf("extract %s: %w", e.Key, err)
		}
		if len(view.Units) != len(e.Units) {
			return fmt.Errorf("extract %s: %d units, want %d", e.Key, len(view.Units), len(e.Units))
		}
		for i, u := range e.Units {
			if _, dup := units[u.Key]; dup {
				return fmt.Errorf("duplicate unit key %s", u.Key)
			}
			units[u.Key] = view.Units[i].Unit.ID
		}
	}
	for _, c := range f.Concepts {
		identity := domain.ConceptIdentity{Target: c.Target, PedagogicalIntent: c.PedagogicalIntent, Scope: c.Scope, IdentityFeatures: c.IdentityFeatures}
		var seedUnit *int64
		if len(c.Members) > 0 {
			id, ok := units[c.Members[0]]
			if !ok {
				return fmt.Errorf("concept %s: unknown unit %s", c.Key, c.Members[0])
			}
			seedUnit = &id
		}
		concept, _, err := conceptSvc.CreateConcept(ctx, identity, seedUnit, seedUnit != nil)
		if err != nil {
			return fmt.Errorf("concept %s: %w", c.Key, err)
		}
		for _, m := range c.Members[min(1, len(c.Members)):] {
			id, ok := units[m]
			if !ok {
				return fmt.Errorf("concept %s: unknown unit %s", c.Key, m)
			}
			if _, err := conceptSvc.ResolveSame(ctx, id, concept.ID); err != nil {
				return fmt.Errorf("concept %s member %s: %w", c.Key, m, err)
			}
		}
		if c.Preferred != "" {
			if _, err := conceptSvc.SetPreferredUnit(ctx, concept.ID, units[c.Preferred]); err != nil {
				return fmt.Errorf("concept %s preferred: %w", c.Key, err)
			}
		}
	}
	for _, stmt := range []string{`PRAGMA wal_checkpoint(TRUNCATE)`, `PRAGMA journal_mode=DELETE`} {
		if _, err := db.ExecContext(ctx, stmt); err != nil {
			db.Close()
			return err
		}
	}
	if err := db.Close(); err != nil {
		return err
	}
	for _, suffix := range []string{"-wal", "-shm"} {
		if _, err := os.Stat(dbPath + suffix); err == nil {
			return fmt.Errorf("database left a %s file", suffix)
		}
	}
	return nil
}
