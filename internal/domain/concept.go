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

// ConceptLifecycleState is the PERSISTED human-owned lifecycle of a concept. It is
// deliberately small and never derived: only an explicit human decision changes
// it. Support (supported/orphaned) is NOT stored here — see ConceptSupportState —
// because it depends on the current extraction, effective admission, and current
// SAME membership, all of which change without any write to the concept.
type ConceptLifecycleState string

const (
	// LifecycleNormal means the concept participates in the live pool; its support
	// is derived from current data at read time.
	LifecycleNormal ConceptLifecycleState = "normal"
	// LifecycleRetired means a human has retired the concept. It is sticky (support
	// recompute never revives it) and it releases the concept's durable-identity
	// claim so a fresh concept may reuse the signature.
	LifecycleRetired ConceptLifecycleState = "retired"
)

// ValidConceptLifecycleState reports whether s is a known lifecycle state.
func ValidConceptLifecycleState(s ConceptLifecycleState) bool {
	return s == LifecycleNormal || s == LifecycleRetired
}

// ConceptSupportState is the DERIVED support state of a concept. It is never
// persisted: it is computed at read time from whether any unit currently provides
// automatic support (belongs to its entry's current extraction + effective
// admission active + holds the current SAME membership to the concept).
type ConceptSupportState string

const (
	// SupportSupported means at least one unit currently provides automatic support.
	SupportSupported ConceptSupportState = "supported"
	// SupportOrphaned means no unit currently provides support. The concept is kept
	// (never deleted) and can regain support later.
	SupportOrphaned ConceptSupportState = "orphaned"
)

// ConceptState is the effective, human-facing state of a concept, combining the
// persisted lifecycle with derived support. It is kept for API compatibility (the
// wire "state" field) but is always COMPUTED from current data, never stored, so
// it can never go stale. Retired wins; otherwise support decides.
type ConceptState string

const (
	// ConceptActive means normal lifecycle and currently supported.
	ConceptActive ConceptState = "active"
	// ConceptOrphaned means normal lifecycle but currently unsupported.
	ConceptOrphaned ConceptState = "orphaned"
	// ConceptRetired means the human lifecycle is retired (regardless of support).
	ConceptRetired ConceptState = "retired"
)

// ValidConceptState reports whether s is a known effective concept state.
func ValidConceptState(s ConceptState) bool {
	switch s {
	case ConceptActive, ConceptOrphaned, ConceptRetired:
		return true
	}
	return false
}

// EffectiveConceptState maps a persisted lifecycle plus a derived support state
// onto the effective, human-facing ConceptState. Retired is sticky and wins over
// support; otherwise supported => active, unsupported => orphaned.
func EffectiveConceptState(lifecycle ConceptLifecycleState, support ConceptSupportState) ConceptState {
	if lifecycle == LifecycleRetired {
		return ConceptRetired
	}
	if support == SupportSupported {
		return ConceptActive
	}
	return ConceptOrphaned
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

// LinkStatus is the kind of decision one append-only event row records, captured
// at the moment the decision was made. History is truly append-only: an event row
// is written once and NEVER updated. A superseding decision inserts a NEW event
// that references the one it replaces via SupersedesLinkID; the earlier row keeps
// its original data forever. "Which SAME decision is currently in force" is a
// derived fact held by the current-membership projection, not by mutating an event
// row's status. LinkSuperseded is retained only to read legacy migration-006 rows;
// this milestone never writes it.
type LinkStatus string

const (
	// LinkAccepted is a decision that accepted a relation/membership at the time it
	// was recorded. It does not by itself mean "still current": currency is decided
	// by the membership projection (SAME) or by being the newest un-superseded event
	// (relations).
	LinkAccepted LinkStatus = "accepted"
	// LinkSuperseded is a legacy status written by migration 006. It is never written
	// by this milestone (supersession is expressed structurally via SupersedesLinkID)
	// but may appear on historical rows.
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
	// matching and durable-identity uniqueness among non-retired concepts.
	Signature string
	// PreferredUnitID is the unit chosen to represent the concept. It is a
	// separate decision from membership and may be nil.
	PreferredUnitID *int64
	// Lifecycle is the PERSISTED, human-owned state (normal | retired). It is the
	// only concept state that is stored.
	Lifecycle ConceptLifecycleState
	// Support is the DERIVED support state (supported | orphaned), computed at read
	// time from current data. It is never persisted, so it cannot go stale.
	Support ConceptSupportState
	// State is the effective, human-facing state (active | orphaned | retired),
	// derived from Lifecycle + Support. Kept for API compatibility; always computed.
	State     ConceptState
	CreatedAt time.Time
	UpdatedAt time.Time
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

// UnitConceptLink is one immutable resolution EVENT relating a unit to a concept.
// It is written exactly once and never updated or deleted. The full set of fields
// is auditable: which unit and concept, the asserted relation, the decision kind
// at recording time, who decided, the resolver version, an optional score,
// structured evidence, when, and — for a correcting decision — the id of the event
// it supersedes. Currency is NOT read from this row: the current SAME membership
// lives in a separate projection, and the current relation is the newest event not
// yet superseded.
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
	Evidence string
	// SupersedesLinkID, when set, is the id of the earlier event this decision
	// replaces (e.g. a human correction pointing back at the machine SAME it
	// overrides). nil for an original decision. The referenced row is never mutated.
	SupersedesLinkID *int64
	CreatedAt        time.Time
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

// ConceptView is the read model for one concept together with its FULL append-only
// resolution event history (every event ever recorded for the concept — accepted,
// superseding, relations, and legacy rows), so a review UI can show provenance,
// not just the currently-in-force decisions. Events are ordered newest-first. The
// embedded Concept carries the derived support/effective state.
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

// CurrentConceptMembership is the read model for a unit's CURRENT SAME membership.
// It is the single source of truth for "which concept this unit belongs to right
// now": it is read directly from the current-membership projection, NEVER
// reconstructed by scanning the append-only event log (a historical event may
// still read status='accepted' long after it was superseded, so events are
// evidence, not current authority). LinkID is the event-log row currently in
// force. A unit with no current SAME membership has no CurrentConceptMembership.
type CurrentConceptMembership struct {
	UnitID    int64
	ConceptID int64
	LinkID    int64
	UpdatedAt time.Time
}

// NewConceptInput is the validated bundle for creating a concept from a
// unit/signature. Identity is validated and normalized; SeedUnitID optionally
// records which unit motivated the concept. When LinkSeedAsSame is true, the
// repository ALSO records an accepted SAME membership for the seed unit in the
// SAME transaction as the concept insert, so create-and-attach is atomic (either
// both persist or neither does). LinkSeedAsSame requires SeedUnitID.
type NewConceptInput struct {
	Identity       ConceptIdentity
	SeedUnitID     *int64
	LinkSeedAsSame bool
	// SeedSource records who requested the seed membership (defaults to human at
	// the service boundary). SeedEvidence is the structured evidence JSON for it.
	SeedSource   DecisionSource
	SeedEvidence string
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
	// CreateConcept inserts a new concept from a validated identity. It refuses to
	// create a second non-retired concept with the same durable identity
	// (identity_schema_version + signature), returning ErrConceptConflict — an
	// orphaned (unsupported) concept still owns its identity, so orphaning never
	// releases it. When in.LinkSeedAsSame is true it ALSO records an accepted SAME
	// membership for in.SeedUnitID in the same transaction, so create-and-attach is
	// atomic: if the seed link fails, the concept is not persisted either. SeedUnitID,
	// when set, must reference an existing unit; LinkSeedAsSame requires SeedUnitID.
	// The returned link is non-nil only when a seed membership was created.
	//
	// Create+seed only ESTABLISHES membership for an unresolved unit. If the seed
	// unit already has a current SAME membership, CreateConcept returns
	// ErrConceptConflict and persists nothing (no concept, no event, no projection
	// change): moving an existing membership is exclusively ReassignSame's job and is
	// never a hidden side effect of concept creation.
	CreateConcept(ctx context.Context, in NewConceptInput) (*KnowledgeConcept, *UnitConceptLink, error)
	// GetConcept returns one concept (with derived support state) and its full
	// append-only event history, or ErrNotFound.
	GetConcept(ctx context.Context, conceptID int64) (*ConceptView, error)
	// ListConcepts returns concepts filtered by effective state (nil = all), newest
	// first. Because support is derived, filtering by active/orphaned computes each
	// concept's current support; retired filters on the persisted lifecycle.
	ListConcepts(ctx context.Context, state *ConceptState) ([]KnowledgeConcept, error)
	// LinkSame records an accepted SAME membership from unit to concept and sets it
	// as the unit's current membership. It enforces at-most-one CURRENT SAME per
	// unit: re-affirming the same concept is idempotent; a SAME to a DIFFERENT
	// concept while one is already current is a conflict (ErrConceptConflict) — use
	// ReassignSame for an explicit human correction. Appends an immutable event.
	// Returns ErrNotFound if the unit or concept does not exist.
	LinkSame(ctx context.Context, unitID, conceptID int64, source DecisionSource, score *float64, evidence string) (*UnitConceptLink, error)
	// ReassignSame moves a unit's CURRENT SAME membership to a different concept as
	// an explicit human correction, even when the unit already has a current SAME
	// membership. It appends a new immutable event that supersedes the prior one
	// (via SupersedesLinkID), updates the current-membership projection, and — if
	// the OLD concept's preferred_unit_id pointed at this unit — clears it, since
	// the unit is no longer a member there. All in one transaction. Re-affirming the
	// unit's existing current concept is idempotent. Returns ErrNotFound if the unit
	// or concept does not exist.
	ReassignSame(ctx context.Context, unitID, conceptID int64, source DecisionSource, evidence string) (*UnitConceptLink, error)
	// LinkRelation records a non-membership BROADER/NARROWER/RELATED decision as an
	// immutable event. It never affects SAME membership or automatic support. A
	// repeated identical (unit, concept, relation) appends a new event that
	// supersedes the prior one via SupersedesLinkID (the old row is not rewritten).
	// Rejects RelationSame (use LinkSame) with ErrValidation.
	LinkRelation(ctx context.Context, unitID, conceptID int64, relation ConceptRelation, source DecisionSource, evidence string) (*UnitConceptLink, error)
	// SetPreferredUnit sets the concept's preferred unit. The unit must currently
	// hold the CURRENT SAME membership to this concept, else ErrValidation. It does
	// not change the concept ID or any membership.
	SetPreferredUnit(ctx context.Context, conceptID, unitID int64) (*KnowledgeConcept, error)
	// ListReviewableUnits returns units from the given entry's current extraction
	// that have no current SAME membership. If entryID is nil, it spans all entries'
	// current extractions. Only current-extraction units are considered (historical
	// units are queryable elsewhere but are not part of the live review queue).
	ListReviewableUnits(ctx context.Context, entryID *int64) ([]ReviewableUnit, error)
	// ActiveSupportUnitIDs returns the ids of units that currently provide automatic
	// support to conceptID (current SAME membership + belongs to their entry's
	// current extraction + effective admission active). Computed from current data.
	ActiveSupportUnitIDs(ctx context.Context, conceptID int64) ([]int64, error)
	// GetCurrentMembership returns the unit's CURRENT SAME membership read from the
	// membership projection, or (nil, nil) when the unit has no current SAME. It
	// never reconstructs currency from the append-only event log. Returns ErrNotFound
	// if the unit does not exist.
	GetCurrentMembership(ctx context.Context, unitID int64) (*CurrentConceptMembership, error)
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
	// belong to the entry, else ErrValidation. It only updates the pointer: concept
	// support is DERIVED at read time, so no per-concept recompute is needed and the
	// next read of any affected concept reflects the change immediately.
	SetCurrentExtraction(ctx context.Context, entryID, extractionID int64) error
}
