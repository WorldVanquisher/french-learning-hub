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
	"sort"

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
	return buildArtifact(ctx, fixturesPath, outDir, buildMeta{
		generator: "scripts/demo/flh073/prepare build", release: ReleaseBlockedMechanical, notice: MechanicalNotice,
		vectors: func(docs []application.SemanticIndexDocument, presets []presetText) (Vectors, *Provenance, error) {
			identity := VectorIdentity{Source: SourceMechanical, RealModel: false, Generator: MechanicalGenerator, ModelID: MechanicalModelID,
				Dimensions: MechanicalDimensions, DocumentRepresentation: application.ConceptIndexRepresentationV1,
				QueryRepresentation: application.ConceptSearchQueryRepresentationV2}
			vec := Vectors{Schema: VectorsSchema, Identity: identity}
			for _, d := range docs {
				vec.Documents = append(vec.Documents, DocumentVector{ConceptID: d.ConceptID, ContentHash: d.ContentHash, Vector: MechanicalEmbed(d.Text, identity.Dimensions)})
			}
			for _, p := range presets {
				vec.Presets = append(vec.Presets, PresetVector{ID: p.ID, Label: p.Label, Text: p.Text, Envelope: p.Envelope,
					EnvelopeSHA256: sha256Hex(p.Envelope), Vector: MechanicalEmbed(p.Envelope, identity.Dimensions)})
			}
			return vec, nil, nil
		},
	})
}

// presetText is one preset with its exact search-query envelope.
type presetText struct {
	ID, Label, Text, Envelope string
}

type buildMeta struct {
	generator, release, notice string
	vectors                    func(docs []application.SemanticIndexDocument, presets []presetText) (Vectors, *Provenance, error)
}

// derive seeds dbPath from the fixtures and returns the fingerprint, the exact
// Concept documents (in id order) and the exact preset envelopes.
func derive(ctx context.Context, f *Fixtures, dbPath string) (DomainFingerprint, []application.SemanticIndexDocument, []presetText, error) {
	if err := seed(ctx, f, dbPath); err != nil {
		return DomainFingerprint{}, nil, nil, err
	}
	ro, err := OpenReadOnly(dbPath)
	if err != nil {
		return DomainFingerprint{}, nil, nil, err
	}
	defer ro.Close()
	fp, err := ComputeFingerprint(ctx, ro)
	if err != nil {
		return fp, nil, nil, err
	}
	concepts, err := sqlite.NewConceptRepository(ro).ListConcepts(ctx, nil)
	if err != nil {
		return fp, nil, nil, err
	}
	sort.Slice(concepts, func(i, j int) bool { return concepts[i].ID < concepts[j].ID })
	var docs []application.SemanticIndexDocument
	for _, c := range concepts {
		doc, err := application.BuildSemanticIndexDocument(c)
		if err != nil {
			return fp, nil, nil, err
		}
		docs = append(docs, doc)
	}
	var presets []presetText
	for _, p := range f.Presets {
		env, err := application.ConceptSearchQueryEmbeddingText(p.Text)
		if err != nil {
			return fp, nil, nil, fmt.Errorf("preset %s: %w", p.ID, err)
		}
		presets = append(presets, presetText{ID: p.ID, Label: p.Label, Text: p.Text, Envelope: env})
	}
	return fp, docs, presets, nil
}

// buildArtifact writes a complete artifact into a temporary sibling directory,
// validates it with the server's loader, and only then renames it to outDir.
// A failure leaves outDir absent (or as the empty directory it was) and
// removes the partial directory.
func buildArtifact(ctx context.Context, fixturesPath, outDir string, meta buildMeta) (_ *Artifact, err error) {
	f, raw, err := ReadFixtures(fixturesPath)
	if err != nil {
		return nil, err
	}
	outDir, err = filepath.Abs(outDir)
	if err != nil {
		return nil, err
	}
	if entries, err := os.ReadDir(outDir); err == nil && len(entries) > 0 {
		return nil, fmt.Errorf("%s exists and is not empty", outDir)
	}
	if err := os.MkdirAll(filepath.Dir(outDir), 0o755); err != nil {
		return nil, err
	}
	stage, err := os.MkdirTemp(filepath.Dir(outDir), "."+filepath.Base(outDir)+".partial-")
	if err != nil {
		return nil, err
	}
	defer func() {
		if err != nil {
			os.RemoveAll(stage)
		}
	}()
	if err := os.Chmod(stage, 0o755); err != nil {
		return nil, err
	}
	fp, docs, presets, err := derive(ctx, f, filepath.Join(stage, DatabaseFile))
	if err != nil {
		return nil, err
	}
	vec, prov, err := meta.vectors(docs, presets)
	if err != nil {
		return nil, err
	}
	if err := writeJSONFile(filepath.Join(stage, VectorsFile), vec); err != nil {
		return nil, err
	}
	if err := os.WriteFile(filepath.Join(stage, FixturesFile), raw, 0o644); err != nil {
		return nil, err
	}
	names := []string{DatabaseFile, VectorsFile, FixturesFile}
	if prov != nil {
		prov.FixturesSHA256, err = SHA256File(filepath.Join(stage, FixturesFile))
		if err != nil {
			return nil, err
		}
		if err := writeJSONFile(filepath.Join(stage, ProvenanceFile), prov); err != nil {
			return nil, err
		}
		names = append(names, ProvenanceFile)
	}
	files := map[string]string{}
	for _, name := range names {
		if files[name], err = SHA256File(filepath.Join(stage, name)); err != nil {
			return nil, err
		}
	}
	version := sha256.Sum256([]byte(files[FixturesFile] + "\x00" + files[VectorsFile] + "\x00" + fp.SHA256))
	m := Manifest{Schema: ManifestSchema, ArtifactVersion: hex.EncodeToString(version[:])[:16], Generator: meta.generator,
		Files: files, Vectors: vec.Identity, SpacePrefix: DemoSpacePrefix, DomainFingerprint: fp,
		ReleaseStatus: meta.release, Notice: meta.notice}
	if err := writeJSONFile(filepath.Join(stage, ManifestFile), m); err != nil {
		return nil, err
	}
	_, db, err := OpenArtifact(ctx, stage)
	if err != nil {
		return nil, fmt.Errorf("the built artifact does not validate: %w", err)
	}
	db.Close()
	if _, statErr := os.Stat(outDir); statErr == nil {
		if err := os.Remove(outDir); err != nil { // empty, checked above
			return nil, err
		}
	}
	if err := os.Rename(stage, outDir); err != nil {
		return nil, err
	}
	return LoadArtifact(outDir)
}

func writeJSONFile(path string, v any) error {
	b, err := json.MarshalIndent(v, "", " ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(b, '\n'), 0o644)
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
