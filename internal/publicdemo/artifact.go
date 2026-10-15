// Package publicdemo implements the FLH-073 read-only public demo: an
// integrity-checked artifact (synthetic database, Concept-document vectors and
// a bounded catalog of preset queries with cached query vectors), a read-only
// database opener, and read-only stand-ins for the vector index, publication
// record and embedding provider that let the existing semantic and hybrid
// search services run with no Qdrant, no provider and no network.
package publicdemo

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"

	"french-learning-app/internal/application"
)

const (
	ManifestSchema = "flh073_public_demo_artifact_v1"
	VectorsSchema  = "flh073_demo_vectors_v1"

	ManifestFile = "manifest.json"
	DatabaseFile = "demo.db"
	VectorsFile  = "vectors.json"
	FixturesFile = "fixtures.json"
	// ProvenanceFile is required for, and only for, model-vector artifacts.
	ProvenanceFile   = "provenance.json"
	ProvenanceSchema = "flh076_vector_provenance_v1"
	// ModelGenerator is the FLH-076 E5 HTTP preparation pipeline.
	ModelGenerator = "flh076_e5_http_v1"

	RoleDocument = "passage"
	RoleQuery    = "query"

	// SourceMechanical marks deterministic test vectors with no semantic meaning.
	SourceMechanical = "mechanical-test"
	// SourceModel marks vectors produced by a real embedding model.
	SourceModel = "model"

	ReleaseBlockedMechanical = "blocked_mechanical_vectors"
	ReleaseModelVectors      = "model_vectors"

	// MaxPresets bounds the preset catalog.
	MaxPresets = 12
)

// ErrArtifact reports a missing, altered or inconsistent artifact. The demo
// refuses to start on it; nothing is substituted.
var ErrArtifact = errors.New("public demo artifact rejected")

var (
	presetIDPattern = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{0,39}$`)
	hexSHA256       = regexp.MustCompile(`^[0-9a-f]{64}$`)
	versionPattern  = regexp.MustCompile(`^[0-9a-f]{16}$`)
)

// VectorIdentity names exactly what produced the vectors.
type VectorIdentity struct {
	Source                 string `json:"source"`
	RealModel              bool   `json:"real_model"`
	Generator              string `json:"generator"`
	ModelID                string `json:"model_id"`
	Dimensions             int    `json:"dimensions"`
	DocumentRepresentation string `json:"document_representation"`
	QueryRepresentation    string `json:"query_representation"`
}

// DomainFingerprint is a timestamp-free digest of the synthetic database content.
type DomainFingerprint struct {
	// Version is FingerprintVersion; FLH-073 (v1) manifests have none.
	Version string         `json:"version"`
	SHA256  string         `json:"sha256"`
	Counts  map[string]int `json:"counts"`
}

// Manifest is manifest.json.
type Manifest struct {
	Schema            string            `json:"schema"`
	ArtifactVersion   string            `json:"artifact_version"`
	Generator         string            `json:"generator"`
	Files             map[string]string `json:"files"`
	Vectors           VectorIdentity    `json:"vectors"`
	SpacePrefix       string            `json:"space_prefix"`
	DomainFingerprint DomainFingerprint `json:"domain_fingerprint"`
	ReleaseStatus     string            `json:"release_status"`
	Notice            string            `json:"notice"`
}

// DocumentVector is one Concept document's vector, bound to its content hash.
type DocumentVector struct {
	ConceptID   int64     `json:"concept_id"`
	ContentHash string    `json:"content_hash"`
	Vector      []float64 `json:"vector"`
}

// PresetVector is one preset query with its exact text, embedding envelope and vector.
type PresetVector struct {
	ID             string    `json:"id"`
	Label          string    `json:"label"`
	Text           string    `json:"text"`
	Envelope       string    `json:"envelope"`
	EnvelopeSHA256 string    `json:"envelope_sha256"`
	Vector         []float64 `json:"vector"`
}

// Vectors is vectors.json.
type Vectors struct {
	Schema    string           `json:"schema"`
	Identity  VectorIdentity   `json:"identity"`
	Documents []DocumentVector `json:"documents"`
	Presets   []PresetVector   `json:"presets"`
}

// Preset is a validated preset query.
type Preset struct {
	ID     string
	Label  string
	Text   string
	vector []float32
}

// ProvenancePosition binds one embedded text to its vector.
type ProvenancePosition struct {
	Key            string `json:"key"`
	Kind           string `json:"kind"` // "document" or "preset"
	Representation string `json:"representation"`
	Role           string `json:"role"`
	TextSHA256     string `json:"text_sha256"`
	VectorSHA256   string `json:"vector_sha256"`
	PostSeq        int    `json:"post_seq"`
	ReceivedUTC    string `json:"received_utc"`
}

// ProvenancePost is one embedding POST as recorded by the ledger.
type ProvenancePost struct {
	Seq         int    `json:"seq"`
	Positions   int    `json:"positions"`
	Outcome     string `json:"outcome"` // ok, failed, attempted
	ReservedUTC string `json:"reserved_utc"`
	FinishedUTC string `json:"finished_utc"`
	Error       string `json:"error"`
}

// ProvenanceProbe is one readiness probe (GET /readyz and GET /manifest).
type ProvenanceProbe struct {
	UTC                  string `json:"utc"`
	ReadyStatus          int    `json:"ready_status"`
	ManifestDeploymentID string `json:"manifest_deployment_id"`
	ManifestSHA256       string `json:"manifest_sha256"`
	Outcome              string `json:"outcome"`
}

// Accounting is the persistent preparation budget and its use.
type Accounting struct {
	MaxPositions  int `json:"max_positions"`
	MaxPosts      int `json:"max_posts"`
	MaxProbes     int `json:"max_probes"`
	UsedPositions int `json:"used_positions"`
	UsedPosts     int `json:"used_posts"`
	UsedProbes    int `json:"used_probes"`
}

// Provenance is provenance.json: what the preparation recorded about every vector.
type Provenance struct {
	Schema         string               `json:"schema"`
	Generator      string               `json:"generator"`
	DeploymentID   string               `json:"deployment_id"`
	Dimensions     int                  `json:"dimensions"`
	BaseURL        string               `json:"base_url"`
	PlanSHA256     string               `json:"plan_sha256"`
	FixturesSHA256 string               `json:"fixtures_sha256"`
	Probes         []ProvenanceProbe    `json:"probes"`
	Posts          []ProvenancePost     `json:"posts"`
	Accounting     Accounting           `json:"accounting"`
	Positions      []ProvenancePosition `json:"positions"`
	Note           string               `json:"note"`
}

// VectorSHA256 is the SHA-256 of a vector's canonical JSON encoding.
func VectorSHA256(v []float64) string {
	b, _ := json.Marshal(v)
	return sha256Hex(string(b))
}

// Artifact is a loaded, validated artifact (database not yet opened).
type Artifact struct {
	Dir            string
	Manifest       Manifest
	ManifestSHA256 string
	Space          application.SemanticIndexSpace
	Collection     string
	Presets        []Preset
	documents      map[int64]artifactDocument
	byEnvelope     map[string]int
}

type artifactDocument struct {
	hash   string
	vector []float32
}

// DatabasePath is the artifact's database file.
func (a *Artifact) DatabasePath() string { return filepath.Join(a.Dir, DatabaseFile) }

// Mechanical reports whether the vectors are mechanical test fixtures.
func (a *Artifact) Mechanical() bool { return a.Manifest.Vectors.Source == SourceMechanical }

// PresetByID returns the preset with this id.
func (a *Artifact) PresetByID(id string) (Preset, bool) {
	for _, p := range a.Presets {
		if p.ID == id {
			return p, true
		}
	}
	return Preset{}, false
}

func fail(format string, args ...any) error {
	return fmt.Errorf("%w: %s", ErrArtifact, fmt.Sprintf(format, args...))
}

// SHA256File returns the hex SHA-256 of a file.
func SHA256File(path string) (string, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:]), nil
}

func sha256Hex(s string) string {
	sum := sha256.Sum256([]byte(s))
	return hex.EncodeToString(sum[:])
}

func readStrictJSON(path string, v any) error {
	b, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.DisallowUnknownFields()
	if err := dec.Decode(v); err != nil {
		return err
	}
	if dec.More() {
		return errors.New("trailing data")
	}
	return nil
}

// LoadArtifact reads and validates manifest.json, the file hashes and
// vectors.json. It does not open the database; OpenArtifact does both.
func LoadArtifact(dir string) (*Artifact, error) {
	abs, err := filepath.Abs(dir)
	if err != nil {
		return nil, fail("artifact directory: %v", err)
	}
	var m Manifest
	if err := readStrictJSON(filepath.Join(abs, ManifestFile), &m); err != nil {
		return nil, fail("%s: %v", ManifestFile, err)
	}
	manifestSHA, err := SHA256File(filepath.Join(abs, ManifestFile))
	if err != nil {
		return nil, fail("%s: %v", ManifestFile, err)
	}
	if m.Schema != ManifestSchema {
		return nil, fail("unknown manifest schema %q", m.Schema)
	}
	if !versionPattern.MatchString(m.ArtifactVersion) {
		return nil, fail("artifact_version must be 16 hex digits")
	}
	if m.SpacePrefix == "" || m.Generator == "" {
		return nil, fail("space_prefix and generator are required")
	}
	want := []string{DatabaseFile, VectorsFile, FixturesFile}
	if m.Vectors.Source == SourceModel {
		want = append(want, ProvenanceFile)
	}
	if len(m.Files) != len(want) {
		return nil, fail("manifest must list exactly %v", want)
	}
	for _, name := range want {
		recorded, ok := m.Files[name]
		if !ok || !hexSHA256.MatchString(recorded) {
			return nil, fail("manifest has no valid SHA-256 for %s", name)
		}
		got, err := SHA256File(filepath.Join(abs, name))
		if err != nil {
			return nil, fail("%s is missing or unreadable", name)
		}
		if got != recorded {
			return nil, fail("%s SHA-256 %s differs from the manifest", name, got[:12])
		}
	}
	if err := checkIdentity(m.Vectors); err != nil {
		return nil, err
	}
	switch {
	case m.Vectors.Source == SourceMechanical && m.ReleaseStatus != ReleaseBlockedMechanical,
		m.Vectors.Source == SourceModel && m.ReleaseStatus != ReleaseModelVectors:
		return nil, fail("release_status %q does not match vector source %q", m.ReleaseStatus, m.Vectors.Source)
	}
	if m.DomainFingerprint.Version != FingerprintVersion {
		v := m.DomainFingerprint.Version
		if v == "" {
			v = "v1 (FLH-073, no version)"
		}
		return nil, fail("domain fingerprint contract %s is not %s: v1 does not cover admission recommendations, the "+
			"current-extraction selection or record order, and v2 depends on clock ticks. Rebuild the artifact into a new "+
			"directory: go run ./scripts/demo/flh073/prepare build -out NEW_DIR (model vectors: prepare import from the "+
			"same work directory)", v, FingerprintVersion)
	}
	if !hexSHA256.MatchString(m.DomainFingerprint.SHA256) {
		return nil, fail("domain fingerprint is missing")
	}

	var v Vectors
	if err := readStrictJSON(filepath.Join(abs, VectorsFile), &v); err != nil {
		return nil, fail("%s: %v", VectorsFile, err)
	}
	if v.Schema != VectorsSchema {
		return nil, fail("unknown vectors schema %q", v.Schema)
	}
	if v.Identity != m.Vectors {
		return nil, fail("vector identity in %s differs from the manifest", VectorsFile)
	}
	space, err := application.NewSemanticIndexSpace(m.SpacePrefix, m.Vectors.ModelID, m.Vectors.Dimensions)
	if err != nil {
		return nil, fail("vector space: %v", err)
	}
	a := &Artifact{Dir: abs, Manifest: m, ManifestSHA256: manifestSHA, Space: space,
		Collection: space.PhysicalCollectionName(m.ArtifactVersion),
		documents:  map[int64]artifactDocument{}, byEnvelope: map[string]int{}}
	if len(v.Documents) == 0 {
		return nil, fail("no Concept-document vectors")
	}
	for _, d := range v.Documents {
		if d.ConceptID <= 0 || !hexSHA256.MatchString(d.ContentHash) {
			return nil, fail("document vector has an invalid concept id or content hash")
		}
		if _, dup := a.documents[d.ConceptID]; dup {
			return nil, fail("duplicate vector for concept %d", d.ConceptID)
		}
		vec, err := application.ValidateEmbedding(d.Vector, m.Vectors.Dimensions)
		if err != nil {
			return nil, fail("concept %d vector: %v", d.ConceptID, err)
		}
		a.documents[d.ConceptID] = artifactDocument{hash: d.ContentHash, vector: vec}
	}
	if len(v.Presets) == 0 || len(v.Presets) > MaxPresets {
		return nil, fail("preset catalog must have 1..%d entries", MaxPresets)
	}
	for i, p := range v.Presets {
		if !presetIDPattern.MatchString(p.ID) {
			return nil, fail("preset id %q is invalid", p.ID)
		}
		if _, dup := a.PresetByID(p.ID); dup {
			return nil, fail("duplicate preset id %q", p.ID)
		}
		if p.Label == "" || len(p.Label) > 80 {
			return nil, fail("preset %s label must be 1..80 bytes", p.ID)
		}
		if _, err := application.ParseHybridSearchQuery(p.Text, "", nil, nil); err != nil || p.Text != trimmed(p.Text) {
			return nil, fail("preset %s text is not a valid search query", p.ID)
		}
		envelope, err := application.ConceptSearchQueryEmbeddingText(p.Text)
		if err != nil || envelope != p.Envelope {
			return nil, fail("preset %s envelope is not exactly the %s envelope of its text", p.ID, application.ConceptSearchQueryRepresentationV2)
		}
		if sha256Hex(p.Envelope) != p.EnvelopeSHA256 {
			return nil, fail("preset %s envelope SHA-256 differs", p.ID)
		}
		if _, dup := a.byEnvelope[p.Envelope]; dup {
			return nil, fail("preset %s duplicates another preset's text", p.ID)
		}
		vec, err := application.ValidateEmbedding(p.Vector, m.Vectors.Dimensions)
		if err != nil {
			return nil, fail("preset %s vector: %v", p.ID, err)
		}
		a.Presets = append(a.Presets, Preset{ID: p.ID, Label: p.Label, Text: p.Text, vector: vec})
		a.byEnvelope[p.Envelope] = i
	}
	if m.Vectors.Source == SourceModel {
		if err := checkProvenance(abs, m, &v); err != nil {
			return nil, err
		}
	}
	return a, nil
}

// checkProvenance requires provenance.json to bind every vector in
// vectors.json: the same text hash (document content hash, preset envelope
// hash), the same vector hash, the right representation and role, and the
// vector identity's deployment and dimensions. A mechanical artifact
// relabelled as a model therefore fails here.
func checkProvenance(dir string, m Manifest, v *Vectors) error {
	var p Provenance
	if err := readStrictJSON(filepath.Join(dir, ProvenanceFile), &p); err != nil {
		return fail("%s: %v", ProvenanceFile, err)
	}
	if p.Schema != ProvenanceSchema || p.Generator != m.Vectors.Generator || m.Vectors.Generator != ModelGenerator {
		return fail("model vectors need %s provenance from %s", ProvenanceSchema, ModelGenerator)
	}
	if p.DeploymentID != m.Vectors.ModelID || p.Dimensions != m.Vectors.Dimensions {
		return fail("provenance deployment/dimensions differ from the vector identity")
	}
	if !hexSHA256.MatchString(p.PlanSHA256) || p.FixturesSHA256 != m.Files[FixturesFile] {
		return fail("provenance is not bound to this artifact's fixtures and plan")
	}
	acc := p.Accounting
	if acc.MaxPositions < 1 || acc.MaxPositions > 64 || acc.MaxPosts < 1 || acc.MaxPosts > 16 || acc.MaxProbes < 1 || acc.MaxProbes > 2 ||
		acc.UsedPositions > acc.MaxPositions || acc.UsedPosts > acc.MaxPosts || acc.UsedProbes > acc.MaxProbes ||
		acc.UsedPosts != len(p.Posts) || acc.UsedProbes != len(p.Probes) {
		return fail("provenance accounting exceeds the bounded preparation limits")
	}
	okProbe := false
	for _, pr := range p.Probes {
		if pr.Outcome == "ready" && pr.ReadyStatus == 200 && pr.ManifestDeploymentID == p.DeploymentID {
			okProbe = true
		}
	}
	if !okProbe {
		return fail("provenance has no successful readiness probe of %s", p.DeploymentID)
	}
	type want struct{ kind, rep, role, text, vec string }
	expected := map[string]want{}
	for _, d := range v.Documents {
		expected[fmt.Sprintf("concept:%d", d.ConceptID)] = want{"document", application.ConceptIndexRepresentationV1, RoleDocument, d.ContentHash, VectorSHA256(d.Vector)}
	}
	for _, pr := range v.Presets {
		expected["preset:"+pr.ID] = want{"preset", application.ConceptSearchQueryRepresentationV2, RoleQuery, pr.EnvelopeSHA256, VectorSHA256(pr.Vector)}
	}
	if len(p.Positions) != len(expected) {
		return fail("provenance has %d positions for %d vectors", len(p.Positions), len(expected))
	}
	posts := map[int]string{}
	for _, post := range p.Posts {
		posts[post.Seq] = post.Outcome
	}
	seen := map[string]bool{}
	for _, pos := range p.Positions {
		w, ok := expected[pos.Key]
		if !ok || seen[pos.Key] {
			return fail("provenance position %q is unknown or duplicated", pos.Key)
		}
		seen[pos.Key] = true
		if pos.Kind != w.kind || pos.Representation != w.rep || pos.Role != w.role || pos.TextSHA256 != w.text || pos.VectorSHA256 != w.vec {
			return fail("provenance position %s does not match its vector, text, representation or role", pos.Key)
		}
		if posts[pos.PostSeq] != "ok" {
			return fail("provenance position %s is not from a completed POST", pos.Key)
		}
	}
	return nil
}

func trimmed(s string) string {
	q, err := application.ParseLibrarySearchQuery(s, "", nil)
	if err != nil {
		return ""
	}
	return q.Text
}

func checkIdentity(id VectorIdentity) error {
	switch id.Source {
	case SourceMechanical:
		if id.RealModel {
			return fail("mechanical vectors cannot be marked real_model")
		}
	case SourceModel:
		if !id.RealModel {
			return fail("model vectors must be marked real_model")
		}
	default:
		return fail("unknown vector source %q", id.Source)
	}
	if id.Generator == "" || id.ModelID == "" {
		return fail("vector generator and model_id are required")
	}
	if id.Dimensions < 1 || id.Dimensions > application.SemanticIndexMaxDimensions {
		return fail("vector dimensions %d out of range", id.Dimensions)
	}
	if id.DocumentRepresentation != application.ConceptIndexRepresentationV1 {
		return fail("document representation must be %s", application.ConceptIndexRepresentationV1)
	}
	if id.QueryRepresentation != application.ConceptSearchQueryRepresentationV2 {
		return fail("query representation must be %s", application.ConceptSearchQueryRepresentationV2)
	}
	return nil
}
