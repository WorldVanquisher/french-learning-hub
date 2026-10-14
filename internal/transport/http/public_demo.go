package http

import (
	"net/http"
	"net/url"
	"path"
	"regexp"
	"strings"

	"french-learning-app/internal/publicdemo"
)

// KnowledgeLibraryPublicDemoSchemaVersion names GET /knowledge-library/demo.
const KnowledgeLibraryPublicDemoSchemaVersion = "knowledge_library_public_demo_v1"

// publicDemoAPIRoutes is the complete FLH-073 allowlist of API paths (root or
// under /api). Everything else is refused before any handler runs.
var publicDemoAPIRoutes = []*regexp.Regexp{
	regexp.MustCompile(`^/healthz$`),
	regexp.MustCompile(`^/readyz$`),
	regexp.MustCompile(`^/knowledge-library/concepts$`),
	regexp.MustCompile(`^/knowledge-library/concepts/[0-9]{1,18}$`),
	regexp.MustCompile(`^/knowledge-library/units/[0-9]{1,18}/source$`),
	regexp.MustCompile(`^/knowledge-library/demo$`),
	regexp.MustCompile(`^/knowledge-library/demo/semantic-search$`),
	regexp.MustCompile(`^/knowledge-library/demo/hybrid-search$`),
}

// NewPublicDemoBoundary is the FLH-073 server-enforced allowlist. It wraps the
// complete handler (workbench prefix handling included) and refuses, before any
// service runs:
//   - every method except GET and HEAD (405);
//   - non-canonical or escaped paths (404);
//   - every path not on the allowlist, at the root or under /api (404).
//
// static enables / and /assets/... (the demo web build) at the root only.
func NewPublicDemoBoundary(next http.Handler, static bool) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			w.Header().Set("Allow", "GET, HEAD")
			writeError(w, http.StatusMethodNotAllowed, "the public demo is read-only")
			return
		}
		p := r.URL.Path
		if r.URL.RawPath != "" || p == "" || path.Clean(p) != p {
			writeError(w, http.StatusNotFound, "not available in the public demo")
			return
		}
		if static && (p == "/" || (strings.HasPrefix(p, "/assets/") && len(p) > len("/assets/"))) {
			next.ServeHTTP(w, r)
			return
		}
		api := p
		if strings.HasPrefix(p, WorkbenchAPIPrefix+"/") {
			api = strings.TrimPrefix(p, WorkbenchAPIPrefix)
		}
		for _, re := range publicDemoAPIRoutes {
			if re.MatchString(api) {
				next.ServeHTTP(w, r)
				return
			}
		}
		writeError(w, http.StatusNotFound, "not available in the public demo")
	})
}

// publicDemo holds the artifact and its preset-only provider (for counters).
type publicDemo struct {
	artifact *publicdemo.Artifact
	vectors  *publicdemo.PresetQueryVectors
}

// WithPublicDemo wires GET /knowledge-library/demo and the preset-only
// semantic and hybrid routes. Without it those routes do not exist.
func WithPublicDemo(artifact *publicdemo.Artifact, vectors *publicdemo.PresetQueryVectors) HandlerOption {
	return func(handler *Handler) { handler.demo = &publicDemo{artifact: artifact, vectors: vectors} }
}

func (h *Handler) registerPublicDemoRoutes(mux *http.ServeMux) {
	if h.demo == nil {
		return
	}
	mux.HandleFunc("GET /knowledge-library/demo", h.handlePublicDemoInfo)
	mux.HandleFunc("GET /knowledge-library/demo/semantic-search", h.publicDemoPreset([]string{"state", "limit"}, h.handleSemanticSearch))
	mux.HandleFunc("GET /knowledge-library/demo/hybrid-search", h.publicDemoPreset([]string{"state", "limit", "depth"}, h.handleHybridSearch))
}

type publicDemoPresetResponse struct {
	ID    string `json:"id"`
	Label string `json:"label"`
	Text  string `json:"text"`
}

type publicDemoArtifactResponse struct {
	Version                 string `json:"version"`
	ManifestSHA256          string `json:"manifest_sha256"`
	VectorSource            string `json:"vector_source"`
	RealModel               bool   `json:"real_model"`
	VectorGenerator         string `json:"vector_generator"`
	ModelID                 string `json:"model_id"`
	Dimensions              int    `json:"dimensions"`
	DocumentRepresentation  string `json:"document_representation"`
	QueryRepresentation     string `json:"query_representation"`
	ReleaseStatus           string `json:"release_status"`
	Notice                  string `json:"notice"`
	DomainFingerprintSHA256 string `json:"domain_fingerprint_sha256"`
}

type publicDemoInfoResponse struct {
	SchemaVersion string                     `json:"schema_version"`
	ReadOnly      bool                       `json:"read_only"`
	Data          string                     `json:"data"`
	Artifact      publicDemoArtifactResponse `json:"artifact"`
	QueryPolicy   string                     `json:"query_policy"`
	Presets       []publicDemoPresetResponse `json:"presets"`
	Counters      map[string]int64           `json:"counters"`
}

func (h *Handler) handlePublicDemoInfo(w http.ResponseWriter, _ *http.Request) {
	a := h.demo.artifact
	m := a.Manifest
	lookups, refused := h.demo.vectors.Counters()
	resp := publicDemoInfoResponse{
		SchemaVersion: KnowledgeLibraryPublicDemoSchemaVersion, ReadOnly: true, Data: "synthetic",
		Artifact: publicDemoArtifactResponse{Version: m.ArtifactVersion, ManifestSHA256: a.ManifestSHA256,
			VectorSource: m.Vectors.Source, RealModel: m.Vectors.RealModel, VectorGenerator: m.Vectors.Generator,
			ModelID: m.Vectors.ModelID, Dimensions: m.Vectors.Dimensions, DocumentRepresentation: m.Vectors.DocumentRepresentation,
			QueryRepresentation: m.Vectors.QueryRepresentation, ReleaseStatus: m.ReleaseStatus, Notice: m.Notice,
			DomainFingerprintSHA256: m.DomainFingerprint.SHA256},
		QueryPolicy: "Keyword search accepts free text (at most 200 bytes and 8 terms). Semantic and hybrid search accept only the " +
			"preset queries listed here: their query vectors were prepared with the artifact, and this demo computes no embeddings " +
			"and calls no provider.",
		Presets:  make([]publicDemoPresetResponse, 0, len(a.Presets)),
		Counters: map[string]int64{"preset_vector_lookups": lookups, "refused_vector_lookups": refused},
	}
	for _, p := range a.Presets {
		resp.Presets = append(resp.Presets, publicDemoPresetResponse{ID: p.ID, Label: p.Label, Text: p.Text})
	}
	writeJSON(w, http.StatusOK, resp)
}

// publicDemoPreset accepts only preset (required) and the listed parameters,
// each at most once, substitutes the preset's exact text as q and runs the
// unchanged search handler, so the response is the standard one.
func (h *Handler) publicDemoPreset(allowed []string, next http.HandlerFunc) http.HandlerFunc {
	ok := map[string]bool{"preset": true}
	for _, k := range allowed {
		ok[k] = true
	}
	return func(w http.ResponseWriter, r *http.Request) {
		values, err := url.ParseQuery(r.URL.RawQuery)
		if err != nil {
			writeError(w, http.StatusBadRequest, "malformed query string")
			return
		}
		for k, v := range values {
			if !ok[k] {
				writeError(w, http.StatusBadRequest, "the public demo accepts only preset queries here (parameter "+k+" is not allowed); free-text semantic search is disabled")
				return
			}
			if len(v) != 1 {
				writeError(w, http.StatusBadRequest, "parameter "+k+" must appear once")
				return
			}
		}
		id := values.Get("preset")
		if id == "" {
			writeError(w, http.StatusBadRequest, "preset is required")
			return
		}
		preset, found := h.demo.artifact.PresetByID(id)
		if !found {
			writeError(w, http.StatusNotFound, "unknown preset")
			return
		}
		forward := url.Values{"q": {preset.Text}}
		for _, k := range allowed {
			if v := values.Get(k); v != "" {
				forward.Set(k, v)
			}
		}
		inner := r.Clone(r.Context())
		inner.URL.RawQuery = forward.Encode()
		next(w, inner)
	}
}
