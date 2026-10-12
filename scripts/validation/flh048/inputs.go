package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"sort"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// FLH-045 frozen fixture identity (docs/plans/FLH-045-retrieval-evaluation.md).
const (
	flh045SchemaVersion  = "flh045_retrieval_preparation_v1"
	flh045FixtureSHA256  = "92726376c7892ef5e7eb539648828eab3ccf9d026912a4a5509dc461c3b7043a"
	bucketSingleTarget   = "single_target"
	bucketAmbiguous      = "ambiguous"
	bucketNoMatch        = "no_match"
	splitDevelopment     = "development"
	splitHeldOut         = "held_out"
	rankingInputEncoding = "sha256 over records of uint64 big-endian length + Go encoding/json bytes of each ConceptRetrievalDocument (catalog order), then each ConceptRetrievalQuery (query order)"
)

var (
	conceptIDPattern = regexp.MustCompile(`^C[0-9]{3}$`)
	queryIDPattern   = regexp.MustCompile(`^Q[0-9]{3}$`)
)

// rankingFile is the ONLY view of the fixture that reaches retrievers. It is
// decoded on its own, so judgments, rationales, splits, languages, buckets,
// tags and free text cannot enter a ranking input: the struct has no field for
// them.
type rankingFile struct {
	Concepts []struct {
		ID       string `json:"id"`
		Identity struct {
			Target            string            `json:"target"`
			PedagogicalIntent string            `json:"pedagogical_intent"`
			Scope             string            `json:"scope"`
			IdentityFeatures  map[string]string `json:"identity_features"`
		} `json:"identity"`
	} `json:"concepts"`
	Queries []struct {
		ID           string `json:"id"`
		UnitEvidence struct {
			Kind      string  `json:"kind"`
			Canonical string  `json:"canonical"`
			Statement string  `json:"statement"`
			Example   *string `json:"example"`
		} `json:"unit_evidence"`
	} `json:"queries"`
}

// evaluatorFile is the evaluator-only view: metadata and proposed judgments.
type evaluatorFile struct {
	SchemaVersion string `json:"schema_version"`
	LabelStatus   string `json:"label_status"`
	Groups        []struct {
		ID    string `json:"id"`
		Split string `json:"split"`
	} `json:"groups"`
	Queries []struct {
		ID       string `json:"id"`
		GroupID  string `json:"group_id"`
		Split    string `json:"split"`
		Language string `json:"language"`
		Bucket   string `json:"bucket"`
	} `json:"queries"`
	Judgments []struct {
		ID                 string   `json:"id"`
		QueryID            string   `json:"query_id"`
		ProposedRelevant   []string `json:"proposed_relevant_concept_ids"`
		PossibleConceptIDs []string `json:"possible_concept_ids"`
	} `json:"judgments"`
}

// RankingInputs are the exact values passed to ConceptRetriever.Retrieve.
type RankingInputs struct {
	Documents []application.ConceptRetrievalDocument
	Queries   []application.ConceptRetrievalQuery
	// Fixture IDs in mapped order: ConceptFixtureIDs[i] has runtime ID i+1.
	ConceptFixtureIDs []string
	QueryFixtureIDs   []string
}

// QueryMeta is evaluator metadata for one query.
type QueryMeta struct {
	FixtureID string
	UnitID    int64
	GroupID   string
	Split     string
	Language  string
	Bucket    string
	// Exactly one for single_target; empty otherwise.
	TargetFixtureID string
	TargetID        int64
	// Ambiguous alternatives (not relevance labels).
	PossibleFixtureIDs []string
}

// Evaluation holds everything the evaluator knows and retrievers never see.
type Evaluation struct {
	SchemaVersion string
	LabelStatus   string
	Queries       []QueryMeta // same order as RankingInputs.Queries
}

// InputDigests records what was evaluated.
type InputDigests struct {
	FixtureSHA256          string `json:"fixture_sha256"`
	ExpectedFixtureSHA256  string `json:"expected_fixture_sha256"`
	FixtureMatchesExpected bool   `json:"fixture_matches_expected"`
	RankingInputsSHA256    string `json:"ranking_inputs_sha256"`
	RankingInputsEncoding  string `json:"ranking_inputs_encoding"`
	DocumentsSHA256        string `json:"documents_sha256"`
	QueriesSHA256          string `json:"queries_sha256"`
	JudgmentsSHA256        string `json:"judgments_sha256"`
	JudgmentsEncoding      string `json:"judgments_encoding"`
}

func sha256Hex(b []byte) string {
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}

// lengthPrefixedSHA256 hashes records without concatenation ambiguity.
func lengthPrefixedSHA256(records [][]byte) string {
	h := sha256.New()
	var n [8]byte
	for _, r := range records {
		binary.BigEndian.PutUint64(n[:], uint64(len(r)))
		h.Write(n[:])
		h.Write(r)
	}
	return hex.EncodeToString(h.Sum(nil))
}

// mapIDs assigns runtime IDs 1..n in ascending fixture-ID order. Ties in every
// existing retriever break by ascending runtime ID, so this keeps the
// fixture's lexical order as the tie order, independent of file order.
func mapIDs(ids []string, pattern *regexp.Regexp, kind string) (map[string]int64, []string, error) {
	sorted := append([]string(nil), ids...)
	sort.Strings(sorted)
	out := make(map[string]int64, len(ids))
	for i, id := range sorted {
		if !pattern.MatchString(id) {
			return nil, nil, fmt.Errorf("invalid %s id %q", kind, id)
		}
		if _, dup := out[id]; dup {
			return nil, nil, fmt.Errorf("duplicate %s id %q", kind, id)
		}
		out[id] = int64(i + 1)
	}
	return out, sorted, nil
}

// toDocument mirrors the unexported field mapping in
// application.toConceptRetrievalDocument for a persisted Concept: identity is
// validated (normalized) as on creation, and the signature is the domain's.
// The fixture has no lifecycle/support facts; every catalog Concept is treated
// as a normal, supported, active candidate (retrievers do not read these).
func toDocument(id int64, identity domain.ConceptIdentity) (application.ConceptRetrievalDocument, error) {
	if err := identity.Validate(); err != nil {
		return application.ConceptRetrievalDocument{}, err
	}
	features := make(map[string]string, len(identity.IdentityFeatures))
	for k, v := range identity.IdentityFeatures {
		features[k] = v
	}
	return application.ConceptRetrievalDocument{
		ConceptID: id, IdentitySchemaVersion: domain.ConceptIdentitySchemaVersion,
		Target: identity.Target, PedagogicalIntent: identity.PedagogicalIntent,
		Scope: identity.Scope, IdentityFeatures: features, Signature: identity.Signature(),
		Lifecycle: domain.LifecycleNormal, Support: domain.SupportSupported, State: domain.ConceptActive,
	}, nil
}

// toQuery mirrors application.toConceptRetrievalQuery: the candidate identity
// comes only from domain.DeriveCandidateIdentity over the Unit evidence.
func toQuery(unit domain.KnowledgeUnit) application.ConceptRetrievalQuery {
	return application.ConceptRetrievalQuery{
		UnitID: unit.ID, Kind: unit.Kind, Canonical: unit.Canonical,
		Statement: unit.Statement, Example: unit.Example,
		CandidateIdentity: domain.DeriveCandidateIdentity(unit),
	}
}

// LoadRankingInputs builds retriever inputs from the ranking view only.
func LoadRankingInputs(raw []byte) (*RankingInputs, error) {
	var f rankingFile
	if err := strictDecode(raw, &f); err != nil {
		return nil, err
	}
	if len(f.Concepts) == 0 || len(f.Queries) == 0 {
		return nil, errors.New("fixture needs concepts and queries")
	}
	cids := make([]string, len(f.Concepts))
	for i, c := range f.Concepts {
		cids[i] = c.ID
	}
	cmap, csorted, err := mapIDs(cids, conceptIDPattern, "concept")
	if err != nil {
		return nil, err
	}
	qids := make([]string, len(f.Queries))
	for i, q := range f.Queries {
		qids[i] = q.ID
	}
	qmap, qsorted, err := mapIDs(qids, queryIDPattern, "query")
	if err != nil {
		return nil, err
	}

	in := &RankingInputs{ConceptFixtureIDs: csorted, QueryFixtureIDs: qsorted,
		Documents: make([]application.ConceptRetrievalDocument, len(f.Concepts)),
		Queries:   make([]application.ConceptRetrievalQuery, len(f.Queries))}
	signatures := map[string]string{}
	for _, c := range f.Concepts {
		id := cmap[c.ID]
		doc, err := toDocument(id, domain.ConceptIdentity{
			Target: c.Identity.Target, PedagogicalIntent: c.Identity.PedagogicalIntent,
			Scope: c.Identity.Scope, IdentityFeatures: c.Identity.IdentityFeatures,
		})
		if err != nil {
			return nil, fmt.Errorf("concept %s: %w", c.ID, err)
		}
		if other, dup := signatures[doc.Signature]; dup {
			return nil, fmt.Errorf("concepts %s and %s have the same identity signature", other, c.ID)
		}
		signatures[doc.Signature] = c.ID
		in.Documents[id-1] = doc
	}
	for _, q := range f.Queries {
		id := qmap[q.ID]
		kind := domain.KnowledgeKind(q.UnitEvidence.Kind)
		if !domain.ValidKnowledgeKind(kind) {
			return nil, fmt.Errorf("query %s: unknown kind %q", q.ID, q.UnitEvidence.Kind)
		}
		if q.UnitEvidence.Canonical == "" || q.UnitEvidence.Statement == "" {
			return nil, fmt.Errorf("query %s: canonical and statement are required", q.ID)
		}
		in.Queries[id-1] = toQuery(domain.KnowledgeUnit{
			ID: id, Kind: kind, Canonical: q.UnitEvidence.Canonical,
			Statement: q.UnitEvidence.Statement, Example: q.UnitEvidence.Example,
		})
	}
	return in, nil
}

// LoadEvaluation reads the evaluator view and checks it against the mapping.
func LoadEvaluation(raw []byte, in *RankingInputs) (*Evaluation, error) {
	var f evaluatorFile
	if err := strictDecode(raw, &f); err != nil {
		return nil, err
	}
	if f.SchemaVersion != flh045SchemaVersion {
		return nil, fmt.Errorf("schema_version %q, want %q", f.SchemaVersion, flh045SchemaVersion)
	}
	conceptIDs := map[string]int64{}
	for i, id := range in.ConceptFixtureIDs {
		conceptIDs[id] = int64(i + 1)
	}
	groupSplit := map[string]string{}
	for _, g := range f.Groups {
		groupSplit[g.ID] = g.Split
	}
	judgments := map[string]int{}
	for i, j := range f.Judgments {
		if _, dup := judgments[j.QueryID]; dup {
			return nil, fmt.Errorf("query %s has more than one judgment", j.QueryID)
		}
		judgments[j.QueryID] = i
	}
	byID := map[string]int{}
	for i, q := range f.Queries {
		byID[q.ID] = i
	}
	ev := &Evaluation{SchemaVersion: f.SchemaVersion, LabelStatus: f.LabelStatus}
	for i, qid := range in.QueryFixtureIDs {
		qi, ok := byID[qid]
		if !ok {
			return nil, fmt.Errorf("query %s missing from evaluator view", qid)
		}
		q := f.Queries[qi]
		if q.Split != splitDevelopment && q.Split != splitHeldOut {
			return nil, fmt.Errorf("query %s: unknown split %q", qid, q.Split)
		}
		if gs, ok := groupSplit[q.GroupID]; !ok || gs != q.Split {
			return nil, fmt.Errorf("query %s: group %q split disagrees with query split %q", qid, q.GroupID, q.Split)
		}
		ji, ok := judgments[qid]
		if !ok {
			return nil, fmt.Errorf("query %s has no judgment", qid)
		}
		j := f.Judgments[ji]
		meta := QueryMeta{FixtureID: qid, UnitID: int64(i + 1), GroupID: q.GroupID, Split: q.Split, Language: q.Language, Bucket: q.Bucket}
		for _, p := range append(append([]string(nil), j.ProposedRelevant...), j.PossibleConceptIDs...) {
			if _, ok := conceptIDs[p]; !ok {
				return nil, fmt.Errorf("judgment %s references unknown concept %s", j.ID, p)
			}
		}
		switch q.Bucket {
		case bucketSingleTarget:
			if len(j.ProposedRelevant) != 1 || len(j.PossibleConceptIDs) != 0 {
				return nil, fmt.Errorf("single_target query %s needs exactly one proposed target and no alternatives", qid)
			}
			meta.TargetFixtureID, meta.TargetID = j.ProposedRelevant[0], conceptIDs[j.ProposedRelevant[0]]
		case bucketAmbiguous:
			if len(j.ProposedRelevant) != 0 || len(j.PossibleConceptIDs) == 0 {
				return nil, fmt.Errorf("ambiguous query %s needs alternatives and no asserted target", qid)
			}
			meta.PossibleFixtureIDs = append([]string(nil), j.PossibleConceptIDs...)
		case bucketNoMatch:
			if len(j.ProposedRelevant) != 0 || len(j.PossibleConceptIDs) != 0 {
				return nil, fmt.Errorf("no_match query %s must name no concepts", qid)
			}
		default:
			return nil, fmt.Errorf("query %s: unknown bucket %q", qid, q.Bucket)
		}
		ev.Queries = append(ev.Queries, meta)
	}
	if len(f.Queries) != len(in.QueryFixtureIDs) || len(f.Judgments) != len(in.QueryFixtureIDs) {
		return nil, fmt.Errorf("evaluator view has %d queries / %d judgments for %d ranking queries", len(f.Queries), len(f.Judgments), len(in.QueryFixtureIDs))
	}
	return ev, nil
}

// Digests hashes the raw fixture, the rendered ranking inputs and the
// judgments section (Go canonical JSON: decoded then re-encoded, sorted keys).
// The judgments hash is not the FLH-045 validator's Python canonical hash.
func Digests(raw []byte, in *RankingInputs, expected string) (InputDigests, error) {
	var docs, queries [][]byte
	for _, d := range in.Documents {
		b, err := json.Marshal(d)
		if err != nil {
			return InputDigests{}, err
		}
		docs = append(docs, b)
	}
	for _, q := range in.Queries {
		b, err := json.Marshal(q)
		if err != nil {
			return InputDigests{}, err
		}
		queries = append(queries, b)
	}
	var top map[string]json.RawMessage
	if err := json.Unmarshal(raw, &top); err != nil {
		return InputDigests{}, err
	}
	var judgments any
	if err := json.Unmarshal(top["judgments"], &judgments); err != nil {
		return InputDigests{}, err
	}
	canon, err := json.Marshal(judgments)
	if err != nil {
		return InputDigests{}, err
	}
	sum := sha256Hex(raw)
	return InputDigests{
		FixtureSHA256: sum, ExpectedFixtureSHA256: expected, FixtureMatchesExpected: sum == expected,
		RankingInputsSHA256:   lengthPrefixedSHA256(append(append([][]byte(nil), docs...), queries...)),
		RankingInputsEncoding: rankingInputEncoding,
		DocumentsSHA256:       lengthPrefixedSHA256(docs), QueriesSHA256: lengthPrefixedSHA256(queries),
		JudgmentsSHA256: sha256Hex(canon), JudgmentsEncoding: "sha256 of Go encoding/json re-encoding of the decoded judgments array (sorted object keys)",
	}, nil
}

// strictDecode decodes one JSON value and rejects trailing data. (Structural
// validation of the fixture is FLH-045's validator; this only guards decoding.)
func strictDecode(raw []byte, v any) error {
	dec := json.NewDecoder(bytes.NewReader(raw))
	if err := dec.Decode(v); err != nil {
		return fmt.Errorf("decode fixture: %w", err)
	}
	if dec.More() {
		return errors.New("decode fixture: trailing data")
	}
	return nil
}
