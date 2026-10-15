package publicdemo

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/embedding"
)

// FLH-076 real-vector preparation: plan the exact production texts, embed them
// through the existing E5 HTTP service within a persistent, bounded budget,
// and import the receipts into a model artifact.

const (
	PlanSchema      = "flh076_embedding_plan_v1"
	WorkStateSchema = "flh076_embedding_work_state_v1"

	PlanFile      = "plan.json"
	WorkStateFile = "state.json"

	// Task-authorized hard ceilings; options may only lower them.
	HardMaxPositions = 64
	HardMaxPosts     = 16
	HardMaxProbes    = 2
	MaxBatch         = 8
	// unitNormTolerance matches the E5 service's own normalization check.
	unitNormTolerance = 1e-3
)

var (
	// ErrBudget means the preparation would exceed its limits; nothing was sent.
	ErrBudget = errors.New("embedding preparation budget exceeded; nothing sent")
	// ErrWorkState means the work directory does not match this preparation.
	ErrWorkState = errors.New("embedding work directory rejected")
)

// PlanPosition is one exact text to embed.
type PlanPosition struct {
	Key            string `json:"key"`
	Kind           string `json:"kind"`
	Representation string `json:"representation"`
	Role           string `json:"role"`
	Text           string `json:"text"`
	TextSHA256     string `json:"text_sha256"`
}

// Plan is every position the artifact needs, in a fixed order.
type Plan struct {
	Schema         string         `json:"schema"`
	FixturesSHA256 string         `json:"fixtures_sha256"`
	Positions      []PlanPosition `json:"positions"`
	SHA256         string         `json:"sha256"`
}

func planSHA(positions []PlanPosition) string {
	b, _ := json.Marshal(positions)
	return sha256Hex(string(b))
}

// PlanFromFixtures seeds a throwaway database exactly as build/import do and
// lists the Concept documents and preset envelopes the artifact will embed.
func PlanFromFixtures(ctx context.Context, fixturesPath string) (*Plan, error) {
	f, raw, err := ReadFixtures(fixturesPath)
	if err != nil {
		return nil, err
	}
	tmp, err := os.MkdirTemp("", "flh076-plan-")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(tmp)
	_, docs, presets, err := derive(ctx, f, filepath.Join(tmp, DatabaseFile))
	if err != nil {
		return nil, err
	}
	p := &Plan{Schema: PlanSchema, FixturesSHA256: sha256Hex(string(raw))}
	for _, d := range docs {
		p.Positions = append(p.Positions, PlanPosition{Key: fmt.Sprintf("concept:%d", d.ConceptID), Kind: "document",
			Representation: application.ConceptIndexRepresentationV1, Role: RoleDocument, Text: d.Text, TextSHA256: d.ContentHash})
	}
	for _, pr := range presets {
		p.Positions = append(p.Positions, PlanPosition{Key: "preset:" + pr.ID, Kind: "preset",
			Representation: application.ConceptSearchQueryRepresentationV2, Role: RoleQuery, Text: pr.Envelope, TextSHA256: sha256Hex(pr.Envelope)})
	}
	p.SHA256 = planSHA(p.Positions)
	return p, nil
}

// Receipt is one received, validated vector.
type Receipt struct {
	TextSHA256   string    `json:"text_sha256"`
	DeploymentID string    `json:"deployment_id"`
	Dimensions   int       `json:"dimensions"`
	Vector       []float64 `json:"vector"`
	VectorSHA256 string    `json:"vector_sha256"`
	PostSeq      int       `json:"post_seq"`
	ReceivedUTC  string    `json:"received_utc"`
}

// WorkState is the single, atomically rewritten record of a preparation:
// budget, probes, POSTs and receipts move together.
type WorkState struct {
	Schema       string             `json:"schema"`
	PlanSHA256   string             `json:"plan_sha256"`
	DeploymentID string             `json:"deployment_id"`
	Dimensions   int                `json:"dimensions"`
	BaseURL      string             `json:"base_url"`
	Accounting   Accounting         `json:"accounting"`
	Probes       []ProvenanceProbe  `json:"probes"`
	Posts        []ProvenancePost   `json:"posts"`
	Receipts     map[string]Receipt `json:"receipts"`
}

// EmbedOptions configure one embed run. Zero limits mean the hard ceilings.
type EmbedOptions struct {
	BaseURL      string // the service's OpenAI-compatible base, ending in /v1
	DeploymentID string
	Dimensions   int
	Batch        int
	MaxPositions int
	MaxPosts     int
	Client       *http.Client
	ProbeTimeout time.Duration
}

// EmbedReport summarizes one run.
type EmbedReport struct {
	PlanPositions int        `json:"plan_positions"`
	Completed     int        `json:"completed"`
	Pending       int        `json:"pending"`
	SentPositions int        `json:"sent_positions"`
	SentPosts     int        `json:"sent_posts"`
	Probed        bool       `json:"probed"`
	Accounting    Accounting `json:"accounting"`
}

func nowUTC() string { return time.Now().UTC().Format(time.RFC3339Nano) }

func writeAtomic(path string, v any) error {
	b, err := json.MarshalIndent(v, "", " ")
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	if _, err := f.Write(append(b, '\n')); err != nil {
		f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// openWork loads (or, with create, initializes) a work directory for this plan.
func openWork(workDir string, plan *Plan, opts *EmbedOptions, create bool) (*WorkState, error) {
	var stored Plan
	err := readStrictJSON(filepath.Join(workDir, PlanFile), &stored)
	switch {
	case err == nil:
		if stored.SHA256 != plan.SHA256 || planSHA(stored.Positions) != stored.SHA256 || stored.FixturesSHA256 != plan.FixturesSHA256 {
			return nil, fmt.Errorf("%w: its plan differs from these fixtures; use a new work directory", ErrWorkState)
		}
	case errors.Is(err, os.ErrNotExist) && create:
		if err := os.MkdirAll(workDir, 0o755); err != nil {
			return nil, err
		}
		if entries, _ := os.ReadDir(workDir); len(entries) > 0 {
			return nil, fmt.Errorf("%w: %s is not empty and has no plan", ErrWorkState, workDir)
		}
		if err := writeAtomic(filepath.Join(workDir, PlanFile), plan); err != nil {
			return nil, err
		}
	default:
		return nil, fmt.Errorf("%w: %v", ErrWorkState, err)
	}
	var st WorkState
	err = readStrictJSON(filepath.Join(workDir, WorkStateFile), &st)
	switch {
	case err == nil:
		if st.Schema != WorkStateSchema || st.PlanSHA256 != plan.SHA256 {
			return nil, fmt.Errorf("%w: state does not belong to this plan", ErrWorkState)
		}
		if opts != nil && (st.DeploymentID != opts.DeploymentID || st.Dimensions != opts.Dimensions || st.BaseURL != opts.BaseURL) {
			return nil, fmt.Errorf("%w: it was started for %s (%d dimensions) at %s; use a new work directory to change them",
				ErrWorkState, st.DeploymentID, st.Dimensions, st.BaseURL)
		}
	case errors.Is(err, os.ErrNotExist) && opts != nil:
		st = WorkState{Schema: WorkStateSchema, PlanSHA256: plan.SHA256, DeploymentID: opts.DeploymentID, Dimensions: opts.Dimensions,
			BaseURL: opts.BaseURL, Receipts: map[string]Receipt{},
			Accounting: Accounting{MaxPositions: opts.MaxPositions, MaxPosts: opts.MaxPosts, MaxProbes: HardMaxProbes}}
	default:
		return nil, fmt.Errorf("%w: %v", ErrWorkState, err)
	}
	if st.Receipts == nil {
		st.Receipts = map[string]Receipt{}
	}
	return &st, nil
}

func (st *WorkState) complete(p PlanPosition) bool {
	r, ok := st.Receipts[p.Key]
	return ok && r.TextSHA256 == p.TextSHA256 && r.DeploymentID == st.DeploymentID && r.Dimensions == st.Dimensions &&
		r.VectorSHA256 == VectorSHA256(r.Vector) && postOK(st.Posts, r.PostSeq)
}

func postOK(posts []ProvenancePost, seq int) bool {
	for _, p := range posts {
		if p.Seq == seq {
			return p.Outcome == "ok"
		}
	}
	return false
}

// checkUnitVector applies the vector checks before a receipt is written.
func checkUnitVector(v []float64, dims int) error {
	if len(v) != dims {
		return fmt.Errorf("vector has %d dimensions, want %d", len(v), dims)
	}
	var n float64
	for _, x := range v {
		if math.IsNaN(x) || math.IsInf(x, 0) {
			return errors.New("vector is not finite")
		}
		n += x * x
	}
	if math.Abs(math.Sqrt(n)-1) > unitNormTolerance {
		return fmt.Errorf("vector norm %.6f is not 1", math.Sqrt(n))
	}
	return nil
}

func normalize(opts *EmbedOptions) error {
	if !strings.HasSuffix(strings.TrimRight(opts.BaseURL, "/"), "/v1") {
		return errors.New("-base-url must be the service's /v1 base, e.g. http://host:8765/v1")
	}
	opts.BaseURL = strings.TrimRight(opts.BaseURL, "/")
	if strings.TrimSpace(opts.DeploymentID) == "" || opts.Dimensions < 1 || opts.Dimensions > application.SemanticIndexMaxDimensions {
		return errors.New("an explicit deployment id and dimension count are required")
	}
	if opts.Batch == 0 {
		opts.Batch = MaxBatch
	}
	if opts.MaxPositions == 0 {
		opts.MaxPositions = HardMaxPositions
	}
	if opts.MaxPosts == 0 {
		opts.MaxPosts = HardMaxPosts
	}
	if opts.Batch < 1 || opts.Batch > MaxBatch || opts.MaxPositions < 1 || opts.MaxPositions > HardMaxPositions ||
		opts.MaxPosts < 1 || opts.MaxPosts > HardMaxPosts {
		return fmt.Errorf("limits must be batch 1..%d, positions 1..%d, posts 1..%d", MaxBatch, HardMaxPositions, HardMaxPosts)
	}
	if opts.Client == nil {
		opts.Client = &http.Client{Timeout: 60 * time.Second}
	}
	if opts.ProbeTimeout == 0 {
		opts.ProbeTimeout = 5 * time.Second
	}
	return nil
}

// probe performs one readiness probe: GET /readyz must be 200 and GET
// /manifest must report the expected deployment id.
func probe(ctx context.Context, opts EmbedOptions) ProvenanceProbe {
	root := strings.TrimSuffix(opts.BaseURL, "/v1")
	out := ProvenanceProbe{UTC: nowUTC(), Outcome: "unreachable"}
	client := &http.Client{Timeout: opts.ProbeTimeout}
	get := func(path string) (int, []byte, error) {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, root+path, nil)
		if err != nil {
			return 0, nil, err
		}
		resp, err := client.Do(req)
		if err != nil {
			return 0, nil, err
		}
		defer resp.Body.Close()
		b, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
		return resp.StatusCode, b, err
	}
	status, _, err := get("/readyz")
	if err != nil {
		return out
	}
	out.ReadyStatus = status
	if status != http.StatusOK {
		out.Outcome = "not_ready"
		return out
	}
	status, body, err := get("/manifest")
	if err != nil || status != http.StatusOK {
		out.Outcome = "manifest_unavailable"
		return out
	}
	var m struct {
		DeploymentID   string `json:"deployment_id"`
		ManifestSHA256 string `json:"manifest_sha256"`
	}
	if json.Unmarshal(body, &m) != nil {
		out.Outcome = "manifest_unavailable"
		return out
	}
	out.ManifestDeploymentID, out.ManifestSHA256 = m.DeploymentID, m.ManifestSHA256
	if m.DeploymentID != opts.DeploymentID {
		out.Outcome = "deployment_mismatch"
		return out
	}
	out.Outcome = "ready"
	return out
}

// Embed sends the plan's missing positions, within the budget, and records
// every received vector. Completed receipts are never resent. It stops at the
// first failure; nothing is retried automatically.
func Embed(ctx context.Context, fixturesPath, workDir string, opts EmbedOptions) (*EmbedReport, error) {
	if err := normalize(&opts); err != nil {
		return nil, err
	}
	plan, err := PlanFromFixtures(ctx, fixturesPath)
	if err != nil {
		return nil, err
	}
	st, err := openWork(workDir, plan, &opts, true)
	if err != nil {
		return nil, err
	}
	statePath := filepath.Join(workDir, WorkStateFile)
	var pending []PlanPosition
	for _, p := range plan.Positions {
		if !st.complete(p) {
			pending = append(pending, p)
		}
	}
	report := &EmbedReport{PlanPositions: len(plan.Positions), Completed: len(plan.Positions) - len(pending), Pending: len(pending)}
	if len(pending) == 0 {
		report.Accounting = st.Accounting
		return report, nil
	}
	posts := (len(pending) + opts.Batch - 1) / opts.Batch
	acc := st.Accounting
	if acc.UsedProbes+1 > acc.MaxProbes || acc.UsedPosts+posts > acc.MaxPosts || acc.UsedPositions+len(pending) > acc.MaxPositions {
		report.Accounting = acc
		return report, fmt.Errorf("%w: needs 1 probe, %d POSTs and %d positions; used %d/%d probes, %d/%d POSTs, %d/%d positions",
			ErrBudget, posts, len(pending), acc.UsedProbes, acc.MaxProbes, acc.UsedPosts, acc.MaxPosts, acc.UsedPositions, acc.MaxPositions)
	}
	// The probe is charged before it is made.
	st.Accounting.UsedProbes++
	st.Probes = append(st.Probes, ProvenanceProbe{UTC: nowUTC(), Outcome: "attempted"})
	if err := writeAtomic(statePath, st); err != nil {
		return nil, err
	}
	pr := probe(ctx, opts)
	st.Probes[len(st.Probes)-1] = pr
	report.Probed = true
	if err := writeAtomic(statePath, st); err != nil {
		return nil, err
	}
	if pr.Outcome != "ready" {
		report.Accounting = st.Accounting
		return report, fmt.Errorf("embedding service not usable (%s, readyz %d, manifest deployment %q); nothing sent", pr.Outcome, pr.ReadyStatus, pr.ManifestDeploymentID)
	}
	provider := embedding.NewHTTPProviderWithClient("", opts.DeploymentID, opts.BaseURL, opts.Client)
	for start := 0; start < len(pending); start += opts.Batch {
		batch := pending[start:min(start+opts.Batch, len(pending))]
		seq := len(st.Posts) + 1
		st.Accounting.UsedPosts++
		st.Accounting.UsedPositions += len(batch)
		st.Posts = append(st.Posts, ProvenancePost{Seq: seq, Positions: len(batch), Outcome: "attempted", ReservedUTC: nowUTC()})
		if err := writeAtomic(statePath, st); err != nil { // reserved before sending
			return nil, err
		}
		texts := make([]string, len(batch))
		for i, p := range batch {
			texts[i] = p.Text
		}
		vectors, sendErr := provider.Embed(ctx, texts)
		post := &st.Posts[len(st.Posts)-1]
		post.FinishedUTC = nowUTC()
		report.SentPosts++
		report.SentPositions += len(batch)
		if sendErr == nil {
			for i, v := range vectors {
				if err := checkUnitVector(v, opts.Dimensions); err != nil {
					sendErr = fmt.Errorf("%s: %v", batch[i].Key, err)
					break
				}
			}
		}
		if sendErr != nil {
			post.Outcome, post.Error = "failed", sendErr.Error()
			report.Accounting = st.Accounting
			if err := writeAtomic(statePath, st); err != nil {
				return nil, err
			}
			return report, fmt.Errorf("POST %d failed (%v); stopped without retry. Rerun the same command to send only the missing positions", seq, sendErr)
		}
		post.Outcome = "ok"
		for i, p := range batch {
			st.Receipts[p.Key] = Receipt{TextSHA256: p.TextSHA256, DeploymentID: opts.DeploymentID, Dimensions: opts.Dimensions,
				Vector: vectors[i], VectorSHA256: VectorSHA256(vectors[i]), PostSeq: seq, ReceivedUTC: post.FinishedUTC}
		}
		if err := writeAtomic(statePath, st); err != nil { // receipts and post outcome together
			return nil, err
		}
		report.Completed += len(batch)
		report.Pending -= len(batch)
	}
	report.Accounting = st.Accounting
	return report, nil
}

// WorkStatus reports a work directory without contacting anything.
func WorkStatus(ctx context.Context, fixturesPath, workDir string) (*EmbedReport, *WorkState, error) {
	plan, err := PlanFromFixtures(ctx, fixturesPath)
	if err != nil {
		return nil, nil, err
	}
	st, err := openWork(workDir, plan, nil, false)
	if err != nil {
		return nil, nil, err
	}
	r := &EmbedReport{PlanPositions: len(plan.Positions), Accounting: st.Accounting}
	for _, p := range plan.Positions {
		if st.complete(p) {
			r.Completed++
		} else {
			r.Pending++
		}
	}
	return r, st, nil
}

// Import builds a model-vector artifact from a complete work directory into
// outDir (which must not exist), atomically, after full validation.
func Import(ctx context.Context, fixturesPath, workDir, outDir string) (*Artifact, error) {
	if _, err := os.Stat(outDir); err == nil {
		return nil, fmt.Errorf("%s already exists; import always builds a new artifact directory", outDir)
	}
	plan, err := PlanFromFixtures(ctx, fixturesPath)
	if err != nil {
		return nil, err
	}
	st, err := openWork(workDir, plan, nil, false)
	if err != nil {
		return nil, err
	}
	byKey := map[string]PlanPosition{}
	for _, p := range plan.Positions {
		if !st.complete(p) {
			return nil, fmt.Errorf("%w: position %s has no valid receipt; run embed to complete it", ErrWorkState, p.Key)
		}
		byKey[p.Key] = p
	}
	if len(st.Receipts) != len(plan.Positions) {
		return nil, fmt.Errorf("%w: %d receipts for %d positions", ErrWorkState, len(st.Receipts), len(plan.Positions))
	}
	for key, r := range st.Receipts {
		if _, ok := byKey[key]; !ok || checkUnitVector(r.Vector, st.Dimensions) != nil {
			return nil, fmt.Errorf("%w: receipt %s is not in the plan or not a valid vector", ErrWorkState, key)
		}
	}
	notice := "Vectors from the embedding deployment " + st.DeploymentID + ", prepared for the synthetic fixtures through the " +
		"FLH-076 pipeline. Rankings reflect that model on invented data; they are not a relevance evaluation."
	return buildArtifact(ctx, fixturesPath, outDir, buildMeta{
		generator: "scripts/demo/flh073/prepare import", release: ReleaseModelVectors, notice: notice,
		vectors: func(docs []application.SemanticIndexDocument, presets []presetText) (Vectors, *Provenance, error) {
			identity := VectorIdentity{Source: SourceModel, RealModel: true, Generator: ModelGenerator, ModelID: st.DeploymentID,
				Dimensions: st.Dimensions, DocumentRepresentation: application.ConceptIndexRepresentationV1,
				QueryRepresentation: application.ConceptSearchQueryRepresentationV2}
			vec := Vectors{Schema: VectorsSchema, Identity: identity}
			prov := &Provenance{Schema: ProvenanceSchema, Generator: ModelGenerator, DeploymentID: st.DeploymentID, Dimensions: st.Dimensions,
				BaseURL: st.BaseURL, PlanSHA256: plan.SHA256, Probes: st.Probes, Posts: st.Posts, Accounting: st.Accounting,
				Note: "Records what the preparation received; local files are not a cryptographic proof of the producing model."}
			add := func(key, kind, rep, role, textSHA string) ([]float64, error) {
				p, ok := byKey[key]
				if !ok || p.TextSHA256 != textSHA {
					return nil, fmt.Errorf("%w: %s differs from the plan", ErrWorkState, key)
				}
				r := st.Receipts[key]
				prov.Positions = append(prov.Positions, ProvenancePosition{Key: key, Kind: kind, Representation: rep, Role: role,
					TextSHA256: textSHA, VectorSHA256: r.VectorSHA256, PostSeq: r.PostSeq, ReceivedUTC: r.ReceivedUTC})
				return r.Vector, nil
			}
			for _, d := range docs {
				v, err := add(fmt.Sprintf("concept:%d", d.ConceptID), "document", application.ConceptIndexRepresentationV1, RoleDocument, d.ContentHash)
				if err != nil {
					return vec, nil, err
				}
				vec.Documents = append(vec.Documents, DocumentVector{ConceptID: d.ConceptID, ContentHash: d.ContentHash, Vector: v})
			}
			for _, p := range presets {
				v, err := add("preset:"+p.ID, "preset", application.ConceptSearchQueryRepresentationV2, RoleQuery, sha256Hex(p.Envelope))
				if err != nil {
					return vec, nil, err
				}
				vec.Presets = append(vec.Presets, PresetVector{ID: p.ID, Label: p.Label, Text: p.Text, Envelope: p.Envelope,
					EnvelopeSHA256: sha256Hex(p.Envelope), Vector: v})
			}
			return vec, prov, nil
		},
	})
}
