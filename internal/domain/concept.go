package domain

import (
	"context"
	"encoding/json"
	"errors"
	"sort"
	"strings"
	"time"
)

// ErrConceptConflict is returned when a resolution decision cannot be recorded
// because it would violate a Concept-membership invariant that is not a plain
// input-validation error — most importantly, that a KnowledgeUnit may hold at
// most one currently accepted SAME membership. It is distinct from
// ErrValidation (malformed input) and ErrNotFound (missing unit/concept).
var ErrConceptConflict = errors.New("concept resolution conflict")

// ConceptIdentitySchemaVersion identifies the v1 Concept-identity schema. A
// KnowledgeConcept is the durable learning identity that future review, mastery,
// and scheduling attach to; its identity is described by the four fields below
// under this explicit, versioned schema. It is deliberately separate from the
// interaction taxonomy (fr_l2_taxonomy_v1) and from the knowledge-unit vocabulary
// (fr_l2_knowledge_v1): reconciling those is explicitly out of scope for this
// milestone. Canonical/normalized KnowledgeUnit text is retrieval evidence, not
// Concept identity.
const ConceptIdentitySchemaVersion = "fr_l2_concept_identity_v1"

// ConceptResolverVersion identifies the deterministic v1 resolver. It is recorded
// on every resolution decision so a future milestone can analyze which resolver
// version produced a link. The v1 resolver is conservative: it performs exact
// normalized-signature matching only. It uses no embeddings, vectors, sentence
// transformers, neural networks, LLM fuzzy matching, semantic similarity, learned
// probabilities, or automatic broader/narrower inference; those are deliberately
// deferred until real human resolution labels exist.
const ConceptResolverVersion = "concept_resolver_v1"

// Concept-identity field bounds. Identity fields are short labels, not prose.
const (
	maxConceptFieldLen    = 200
	maxIdentityFeatures   = 32
	maxFeatureKeyLen      = 80
	maxFeatureValueLen    = 200
	maxConceptEvidenceLen = 4000
)

// ConceptState is the lifecycle state of a durable KnowledgeConcept.
type ConceptState string

const (
	// ConceptActive means the Concept currently has (or may receive) automatic
	// current support from a live knowledge unit.
	ConceptActive ConceptState = "active"
	// ConceptOrphaned means the Concept has lost all current support but is
	// deliberately kept (never deleted), so its identity and history survive and
	// it can regain support later.
	ConceptOrphaned ConceptState = "orphaned"
	// ConceptRetired means a human has retired the Concept. It is sticky: the
	// automatic support recompute never flips a retired Concept back to active or
	// orphaned.
	ConceptRetired ConceptState = "retired"
)

// ValidConceptState reports whether s is a known concept state.
func ValidConceptState(s ConceptState) bool {
	switch s {
	case ConceptActive, ConceptOrphaned, ConceptRetired:
		return true
	}
	return false
}

// ConceptRelation is the relation a resolution decision asserts between a
// KnowledgeUnit and a KnowledgeConcept. Only SAME is a membership relation:
// BROADER/NARROWER/RELATED record a navigational/annotative relationship and do
// NOT make the unit a member of (or automatic support for) the concept. INVALID
// is intentionally not a relation here — a wrong candidate is handled by not
// accepting a link, not by inventing a membership relation.
type ConceptRelation string

const (
	// RelationSame asserts the unit is an instance/representation of the concept.
	// It is the only membership relation and the only one that can provide
	// automatic current support.
	RelationSame ConceptRelation = "same"
	// RelationBroader asserts the concept is broader than the unit's objective.
	RelationBroader ConceptRelation = "broader"
	// RelationNarrower asserts the concept is narrower than the unit's objective.
	RelationNarrower ConceptRelation = "narrower"
	// RelationRelated asserts a non-hierarchical association.
	RelationRelated ConceptRelation = "related"
)

// ValidConceptRelation reports whether r is a known relation.
func ValidConceptRelation(r ConceptRelation) bool {
	switch r {
	case RelationSame, RelationBroader, RelationNarrower, RelationRelated:
		return true
	}
	return false
}

// LinkStatus is the lifecycle of a single resolution decision. History is
// append-only: a superseding decision inserts a new row and marks the prior
// accepted row superseded rather than rewriting it, so the full machine-and-human
// resolution audit trail is preserved.
type LinkStatus string

const (
	// LinkAccepted is a currently in-force decision.
	LinkAccepted LinkStatus = "accepted"
	// LinkSuperseded is a previously accepted decision replaced by a later one.
	LinkSuperseded LinkStatus = "superseded"
	// LinkRejected is a decision a human explicitly rejected.
	LinkRejected LinkStatus = "rejected"
)

// DecisionSource records who made a resolution decision.
type DecisionSource string

const (
	// SourceResolverAutomatic is the deterministic resolver acting on an exact
	// signature match.
	SourceResolverAutomatic DecisionSource = "resolver:automatic"
	// SourceHuman is an explicit human review decision.
	SourceHuman DecisionSource = "human"
)

// ConceptIdentity is the normalized v1 identity of a concept candidate. Its four
// fields are the identity-bearing signal; IdentityFeatures is an open,
// extensible map so new identity-bearing features can be added later without a
// schema migration, while the signature stays a deterministic canonical form. It
// is deliberately small: this milestone does not attempt a large fixed linguistic
// schema.
type ConceptIdentity struct {
	Target            string
	PedagogicalIntent string
	Scope             string
	IdentityFeatures  map[string]string
}

// normalizeField applies the same plain textual normalization used elsewhere
// (trim + lowercase + collapse internal whitespace; accents preserved). It does
// no stemming, lemmatization, or semantic comparison.
func normalizeField(s string) string {
	return strings.Join(strings.Fields(strings.ToLower(s)), " ")
}

// Normalized returns a copy of the identity with every field normalized and the
// feature map rebuilt from normalized keys/values. It never mutates the receiver.
func (ci ConceptIdentity) Normalized() ConceptIdentity {
	out := ConceptIdentity{
		Target:            normalizeField(ci.Target),
		PedagogicalIntent: normalizeField(ci.PedagogicalIntent),
		Scope:             normalizeField(ci.Scope),
	}
	if len(ci.IdentityFeatures) > 0 {
		out.IdentityFeatures = make(map[string]string, len(ci.IdentityFeatures))
		for k, v := range ci.IdentityFeatures {
			out.IdentityFeatures[normalizeField(k)] = normalizeField(v)
		}
	}
	return out
}

// Signature returns a deterministic canonical string for the NORMALIZED identity,
// used for exact equality comparison. Two identities produce the same signature
// iff their complete normalized identities are equal. It is built from a fixed
// field order with feature keys sorted, so it is stable across runs and
// independent of map iteration order. It carries no semantic notion of
// similarity: only exact matches collide.
func (ci ConceptIdentity) Signature() string {
	n := ci.Normalized()

	// Sort feature keys so the encoded form is order-independent.
	keys := make([]string, 0, len(n.IdentityFeatures))
	for k := range n.IdentityFeatures {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	features := make([][2]string, 0, len(keys))
	for _, k := range keys {
		features = append(features, [2]string{k, n.IdentityFeatures[k]})
	}

	// A slice-of-pairs (not a map) keeps ordering explicit and deterministic in
	// the encoded output.
	payload := struct {
		Schema   string      `json:"schema"`
		Target   string      `json:"target"`
		Intent   string      `json:"pedagogical_intent"`
		Scope    string      `json:"scope"`
		Features [][2]string `json:"identity_features"`
	}{
		Schema:   ConceptIdentitySchemaVersion,
		Target:   n.Target,
		Intent:   n.PedagogicalIntent,
		Scope:    n.Scope,
		Features: features,
	}
	b, err := json.Marshal(payload)
	if err != nil {
		// The payload is composed only of strings, so marshalling cannot fail;
		// fall back to a concatenation rather than panicking.
		return n.Target + "\x00" + n.PedagogicalIntent + "\x00" + n.Scope
	}
	return string(b)
}

// Validate normalizes in place and checks the identity, returning a wrapped
// ErrValidation on failure. Target and pedagogical_intent are required (they are
// the minimum needed to name a durable objective); scope is optional; features
// are bounded in count and size so the signature stays small and comparable.
func (ci *ConceptIdentity) Validate() error {
	ci.Target = normalizeField(ci.Target)
	ci.PedagogicalIntent = normalizeField(ci.PedagogicalIntent)
	ci.Scope = normalizeField(ci.Scope)

	if ci.Target == "" {
		return errWrap("concept target is required")
	}
	if len(ci.Target) > maxConceptFieldLen {
		return errWrap("concept target exceeds maximum length")
	}
	if ci.PedagogicalIntent == "" {
		return errWrap("concept pedagogical_intent is required")
	}
	if len(ci.PedagogicalIntent) > maxConceptFieldLen {
		return errWrap("concept pedagogical_intent exceeds maximum length")
	}
	if len(ci.Scope) > maxConceptFieldLen {
		return errWrap("concept scope exceeds maximum length")
	}

	if len(ci.IdentityFeatures) > maxIdentityFeatures {
		return errWrap("too many identity_features")
	}
	if len(ci.IdentityFeatures) > 0 {
		normalized := make(map[string]string, len(ci.IdentityFeatures))
		for k, v := range ci.IdentityFeatures {
			nk := normalizeField(k)
			if nk == "" {
				return errWrap("identity_features keys must be non-empty")
			}
			if len(nk) > maxFeatureKeyLen {
				return errWrap("identity_features key exceeds maximum length")
			}
			nv := normalizeField(v)
			if len(nv) > maxFeatureValueLen {
				return errWrap("identity_features value exceeds maximum length")
			}
			if _, dup := normalized[nk]; dup {
				return errWrap("identity_features contains duplicate keys after normalization")
			}
			normalized[nk] = nv
		}
		ci.IdentityFeatures = normalized
	}
	return nil
}

// DeriveCandidateIdentity produces a default v1 identity from a persisted
// KnowledgeUnit, so a candidate can be resolved without a human first supplying
// an explicit identity. The mapping is deterministic and conservative:
//   - target            = normalized canonical (the lexical/structural target)
//   - pedagogical_intent = the knowledge kind (what sort of objective this is)
//   - scope             = "" (unset in v1; a human may narrow it later)
//   - identity_features = {} (extensible; empty by default)
//
// Because the identity is separate from raw representation, two units with
// different canonical/statement wordings can still be given the SAME explicit
// identity by a reviewer and resolve SAME.
func DeriveCandidateIdentity(u KnowledgeUnit) ConceptIdentity {
	return ConceptIdentity{
		Target:            normalizeField(u.Canonical),
		PedagogicalIntent: normalizeField(string(u.Kind)),
	}
}

// KnowledgeConcept is the durable learning identity. Unlike a KnowledgeUnit
// (immutable per-extraction evidence), a Concept is stable across extractions and
// across changes to its preferred representation: its ID never changes when the
// preferred unit changes. Future review/mastery/scheduling attach here, not to
// raw units.
type KnowledgeConcept struct {
	ID                    int64
	IdentitySchemaVersion string
	Target                string
	PedagogicalIntent     string
	Scope                 string
	IdentityFeatures      map[string]string
	// Signature is the deterministic canonical form used for exact identity
	// matching and uniqueness among non-retired concepts.
	Signature string
	// PreferredUnitID is the unit chosen to represent the concept. It is a
	// separate decision from membership and may be nil.
	PreferredUnitID *int64
	State           ConceptState
	CreatedAt       time.Time
	UpdatedAt       time.Time
}

// Identity returns the concept's identity value (without database fields).
func (c KnowledgeConcept) Identity() ConceptIdentity {
	return ConceptIdentity{
		Target:            c.Target,
		PedagogicalIntent: c.PedagogicalIntent,
		Scope:             c.Scope,
		IdentityFeatures:  c.IdentityFeatures,
	}
}

// UnitConceptLink is one append-only resolution decision relating a unit to a
// concept. The full set of fields is auditable: which unit and concept, the
// asserted relation, the decision status, who decided, the resolver version, an
// optional score, structured evidence, and when. A superseding decision adds a
// new row; earlier rows are marked superseded, never rewritten or deleted.
type UnitConceptLink struct {
	ID              int64
	UnitID          int64
	ConceptID       int64
	Relation        ConceptRelation
	Status          LinkStatus
	DecisionSource  DecisionSource
	ResolverVersion string
	// Score is an optional resolver score. The v1 resolver records 1.0 for an
	// exact-signature automatic SAME and leaves it nil otherwise; it is NOT a
	// learned probability.
	Score *float64
	// Evidence is a structured, auditable JSON string (e.g. the matched
	// signature). It never contains secrets or raw provider payloads.
	Evidence  string
	CreatedAt time.Time
}

// ResolutionKind is the deterministic outcome the resolver reports for a
// candidate, so callers (and a future review UI) can distinguish an automatic
// match from a case that must stay human-reviewable.
type ResolutionKind string

const (
	// ResolutionMatched means exactly one active concept has the identical
	// complete normalized signature; an automatic SAME is allowed.
	ResolutionMatched ResolutionKind = "matched"
	// ResolutionNoMatch means no active concept shares the signature; the
	// candidate is reviewable (a human may create a new concept).
	ResolutionNoMatch ResolutionKind = "no_match"
	// ResolutionAmbiguous means more than one active concept shares the signature.
	// The resolver never force-merges; the candidate stays human-reviewable.
	ResolutionAmbiguous ResolutionKind = "ambiguous"
)

// ResolveConcept is the deterministic v1 resolver decision over the set of active
// concepts that already share the candidate's exact normalized signature. It is a
// pure function: the caller supplies the matches (looked up by signature) and the
// resolver decides. Automatic SAME requires exactly one match and no conflict;
// zero matches or more than one match is left reviewable rather than merged.
func ResolveConcept(candidate ConceptIdentity, matches []KnowledgeConcept) ResolutionKind {
	switch len(matches) {
	case 0:
		return ResolutionNoMatch
	case 1:
		return ResolutionMatched
	default:
		return ResolutionAmbiguous
	}
}

// ConceptView is the read model for one concept together with the units that
// currently link to it (any relation/status) so a review UI can show the full
// picture. Links are ordered newest-first.
type ConceptView struct {
	Concept KnowledgeConcept
	Links   []UnitConceptLink
}

// ReviewableUnit is a unit that has no currently accepted SAME membership, so it
// is awaiting concept resolution. It carries the derived default candidate
// identity to seed a review UI.
type ReviewableUnit struct {
	Unit      KnowledgeUnit
	Candidate ConceptIdentity
}

// NewConceptInput is the validated bundle for creating a concept from a
// unit/signature. Identity is validated and normalized; SeedUnitID optionally
// records which unit motivated the concept (it does not by itself create a SAME
// membership).
type NewConceptInput struct {
	Identity   ConceptIdentity
	SeedUnitID *int64
}

// ConceptRepository is the persistence boundary for concepts, their append-only
// resolution links, and the per-entry current-extraction pointer. Implementations
// live in the storage layer and keep all SQL there; all invariant enforcement
// that SQLite cannot express (at-most-one accepted SAME, support recompute) is
// done inside repository transactions.
type ConceptRepository interface {
	// UnitByID returns one persisted knowledge unit by id, or ErrNotFound. It lets
	// the concept service read a unit's representation to derive its candidate
	// identity without reaching into extraction internals.
	UnitByID(ctx context.Context, unitID int64) (*KnowledgeUnit, error)
	// FindActiveBySignature returns active concepts whose stored signature equals
	// sig (normally zero or one, since active signatures are unique). Used by the
	// resolver and by concept creation to avoid duplicate identities.
	FindActiveBySignature(ctx context.Context, sig string) ([]KnowledgeConcept, error)
	// CreateConcept inserts a new active concept from a validated identity. It
	// refuses to create a second active concept with the same signature, returning
	// ErrConceptConflict. SeedUnitID, when set, must reference an existing unit.
	CreateConcept(ctx context.Context, in NewConceptInput) (*KnowledgeConcept, error)
	// GetConcept returns one concept with its links, or ErrNotFound.
	GetConcept(ctx context.Context, conceptID int64) (*ConceptView, error)
	// ListConcepts returns concepts filtered by state (nil = all), newest first.
	ListConcepts(ctx context.Context, state *ConceptState) ([]KnowledgeConcept, error)
	// LinkSame records an accepted SAME membership from unit to concept. It
	// enforces at-most-one currently accepted SAME per unit: an accepted SAME to a
	// different concept is a conflict (ErrConceptConflict); re-affirming the same
	// concept is idempotent. After linking, the concept's support state is
	// recomputed. Returns ErrNotFound if the unit or concept does not exist.
	LinkSame(ctx context.Context, unitID, conceptID int64, source DecisionSource, score *float64, evidence string) (*UnitConceptLink, error)
	// LinkRelation records a non-membership BROADER/NARROWER/RELATED decision. It
	// never affects SAME membership or automatic support. A repeated identical
	// (unit, concept, relation) supersedes the prior one. Rejects RelationSame
	// (use LinkSame) with ErrValidation.
	LinkRelation(ctx context.Context, unitID, conceptID int64, relation ConceptRelation, source DecisionSource, evidence string) (*UnitConceptLink, error)
	// SetPreferredUnit sets the concept's preferred unit. The unit must currently
	// have an accepted SAME membership to this concept, else ErrValidation. It does
	// not change the concept ID or any membership.
	SetPreferredUnit(ctx context.Context, conceptID, unitID int64) (*KnowledgeConcept, error)
	// ListReviewableUnits returns units from the given entry's current extraction
	// that have no currently accepted SAME membership. If entryID is nil, it spans
	// all entries' current extractions. Only current-extraction units are
	// considered (historical units are queryable elsewhere but are not part of the
	// live review queue).
	ListReviewableUnits(ctx context.Context, entryID *int64) ([]ReviewableUnit, error)
	// ActiveSupportUnitIDs returns the ids of units that currently provide
	// automatic support to conceptID (accepted SAME + belongs to their entry's
	// current extraction + effective admission active). Used for tests and
	// introspection.
	ActiveSupportUnitIDs(ctx context.Context, conceptID int64) ([]int64, error)
}

// CurrentExtractionRepository is the persistence boundary for the explicit
// per-entry current-extraction selection. The current extraction is the one whose
// units feed the live concept pool; historical extractions remain fully
// queryable but do not.
type CurrentExtractionRepository interface {
	// GetCurrentExtractionID returns the entry's currently selected extraction id,
	// or (nil, nil) when the entry has no successful extraction yet. Returns
	// ErrNotFound if the entry does not exist.
	GetCurrentExtractionID(ctx context.Context, entryID int64) (*int64, error)
	// SetCurrentExtraction explicitly points the entry at an existing successful
	// extraction (e.g. a human rollback to an older version). The extraction must
	// belong to the entry, else ErrValidation. Concept support for affected
	// concepts is recomputed.
	SetCurrentExtraction(ctx context.Context, entryID, extractionID int64) error
}
