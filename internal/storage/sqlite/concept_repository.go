package sqlite

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"french-learning-app/internal/domain"
)

// ConceptRepository is a SQLite-backed domain.ConceptRepository and
// domain.CurrentExtractionRepository. It owns all concept, resolution-event, and
// current-extraction SQL.
//
// Correctness model (milestone 10.5.1):
//   - unit_concept_links is a pure append-only EVENT LOG. Rows are inserted once
//     and never updated or deleted. A correcting decision inserts a new row whose
//     supersedes_link_id points at the row it replaces.
//   - unit_concept_memberships is the single mutable CURRENT SAME projection: at
//     most one row per unit names its current concept and the event that
//     established it. It is the authority for "which SAME is in force".
//   - Concept SUPPORT (supported/orphaned) is DERIVED at read time from current
//     extraction + effective admission + current SAME membership; it is never
//     stored, so it cannot go stale. Only the human LIFECYCLE (normal/retired) is
//     persisted (knowledge_concepts.lifecycle_state).
type ConceptRepository struct {
	db  *sql.DB
	now func() time.Time
}

// compile-time checks.
var (
	_ domain.ConceptRepository             = (*ConceptRepository)(nil)
	_ domain.CurrentExtractionRepository   = (*ConceptRepository)(nil)
	_ domain.EffectiveAnnotationRepository = (*ConceptRepository)(nil)
)

// NewConceptRepository builds a repository over an open database.
func NewConceptRepository(db *sql.DB) *ConceptRepository {
	return &ConceptRepository{
		db:  db,
		now: func() time.Time { return time.Now().UTC() },
	}
}

// txQuerier is satisfied by both *sql.DB and *sql.Tx for the shared helpers.
type txQuerier interface {
	QueryRowContext(ctx context.Context, query string, args ...any) *sql.Row
	QueryContext(ctx context.Context, query string, args ...any) (*sql.Rows, error)
	ExecContext(ctx context.Context, query string, args ...any) (sql.Result, error)
}

// ---- concept identity encoding ----

// encodeFeatures serializes an identity-features map as a deterministic JSON
// object. encoding/json sorts object keys, so the output is stable.
func encodeFeatures(m map[string]string) (string, error) {
	if len(m) == 0 {
		return "{}", nil
	}
	b, err := json.Marshal(m)
	if err != nil {
		return "", fmt.Errorf("encode identity_features: %w", err)
	}
	return string(b), nil
}

func decodeFeatures(s string) (map[string]string, error) {
	if s == "" || s == "{}" {
		return nil, nil
	}
	var m map[string]string
	if err := json.Unmarshal([]byte(s), &m); err != nil {
		return nil, fmt.Errorf("decode identity_features: %w", err)
	}
	if len(m) == 0 {
		return nil, nil
	}
	return m, nil
}

// ---- current extraction derivation ----

// currentExtractionID returns the entry's selected current extraction id, or nil
// when the entry has no persisted extraction yet. The selection is: an explicit
// row in entry_current_extractions if present, otherwise the latest extraction by
// version. Because only successful extractions are ever persisted (a failed run
// writes nothing), the derived latest can never be a failed run, and a failed run
// can never displace the last successful current extraction.
func currentExtractionID(ctx context.Context, q txQuerier, entryID int64) (*int64, error) {
	var explicit sql.NullInt64
	err := q.QueryRowContext(ctx,
		`SELECT extraction_id FROM entry_current_extractions WHERE entry_id = ?`, entryID).Scan(&explicit)
	if err == nil {
		id := explicit.Int64
		return &id, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, fmt.Errorf("read current extraction: %w", err)
	}

	// No explicit selection: derive the latest successful extraction by version.
	var latest sql.NullInt64
	err = q.QueryRowContext(ctx,
		`SELECT id FROM knowledge_extractions
		 WHERE entry_id = ?
		 ORDER BY version DESC
		 LIMIT 1`, entryID).Scan(&latest)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("derive latest extraction: %w", err)
	}
	id := latest.Int64
	return &id, nil
}

// GetCurrentExtractionID implements domain.CurrentExtractionRepository.
func (r *ConceptRepository) GetCurrentExtractionID(ctx context.Context, entryID int64) (*int64, error) {
	if err := entryExists(ctx, r.db, entryID); err != nil {
		return nil, err
	}
	return currentExtractionID(ctx, r.db, entryID)
}

// SetCurrentExtraction explicitly points the entry at one of its successful
// extractions (human rollback). The extraction must belong to the entry. It only
// updates the pointer: because concept support is derived at read time, the next
// read of any affected concept immediately reflects the change — there is no stale
// per-concept state to recompute.
func (r *ConceptRepository) SetCurrentExtraction(ctx context.Context, entryID, extractionID int64) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	if err := entryExists(ctx, tx, entryID); err != nil {
		return err
	}

	// The extraction must exist and belong to this entry.
	var owner int64
	err = tx.QueryRowContext(ctx,
		`SELECT entry_id FROM knowledge_extractions WHERE id = ?`, extractionID).Scan(&owner)
	if errors.Is(err, sql.ErrNoRows) {
		return fmt.Errorf("%w: extraction does not exist", domain.ErrValidation)
	}
	if err != nil {
		return fmt.Errorf("check extraction: %w", err)
	}
	if owner != entryID {
		return fmt.Errorf("%w: extraction does not belong to this entry", domain.ErrValidation)
	}

	ts := r.now().Format(rfc3339)
	if _, err := tx.ExecContext(ctx,
		`INSERT INTO entry_current_extractions (entry_id, extraction_id, updated_at)
		 VALUES (?, ?, ?)
		 ON CONFLICT(entry_id) DO UPDATE SET extraction_id = excluded.extraction_id, updated_at = excluded.updated_at`,
		entryID, extractionID, ts); err != nil {
		return fmt.Errorf("set current extraction: %w", err)
	}
	return tx.Commit()
}

// ---- derived support ----

// unitHasActiveSupport reports whether a unit currently provides automatic
// support: it belongs to its entry's current extraction AND its effective
// admission state is active. The caller guarantees the unit currently holds the
// SAME membership to the concept in question (via unit_concept_memberships).
func unitHasActiveSupport(ctx context.Context, q txQuerier, unitID int64) (bool, error) {
	var extractionID, entryID int64
	err := q.QueryRowContext(ctx,
		`SELECT u.extraction_id, e.entry_id
		 FROM knowledge_units u
		 JOIN knowledge_extractions e ON e.id = u.extraction_id
		 WHERE u.id = ?`, unitID).Scan(&extractionID, &entryID)
	if err != nil {
		return false, fmt.Errorf("locate unit: %w", err)
	}

	current, err := currentExtractionID(ctx, q, entryID)
	if err != nil {
		return false, err
	}
	if current == nil || *current != extractionID {
		return false, nil
	}

	eff, err := effectiveAdmissionState(ctx, q, unitID)
	if err != nil {
		return false, err
	}
	return eff == domain.AdmissionActive, nil
}

// effectiveAdmissionState computes a unit's effective admission state from its
// machine recommendation and latest human override, using the domain resolver.
func effectiveAdmissionState(ctx context.Context, q txQuerier, unitID int64) (domain.MachineAdmissionState, error) {
	var rec domain.AdmissionRecommendation
	var state string
	err := q.QueryRowContext(ctx,
		`SELECT ruleset, state, reason FROM knowledge_admission_recommendations WHERE unit_id = ?`, unitID).
		Scan(&rec.Ruleset, &state, &rec.Reason)
	if errors.Is(err, sql.ErrNoRows) {
		return "", domain.ErrNotFound
	}
	if err != nil {
		return "", fmt.Errorf("get recommendation: %w", err)
	}
	rec.State = domain.MachineAdmissionState(state)

	var (
		decision   string
		reason     string
		note       string
		createdStr string
		unit       int64
		id         int64
	)
	err = q.QueryRowContext(ctx,
		`SELECT id, unit_id, decision, reason, note, created_at
		 FROM knowledge_admission_overrides
		 WHERE unit_id = ?
		 ORDER BY created_at DESC, id DESC
		 LIMIT 1`, unitID).Scan(&id, &unit, &decision, &reason, &note, &createdStr)
	var latest *domain.AdmissionOverride
	if err == nil {
		created, perr := time.Parse(rfc3339, createdStr)
		if perr != nil {
			return "", fmt.Errorf("parse override created_at: %w", perr)
		}
		latest = &domain.AdmissionOverride{
			ID: id, UnitID: unit, Decision: domain.HumanAdmissionDecision(decision),
			Reason: reason, Note: note, CreatedAt: created,
		}
	} else if !errors.Is(err, sql.ErrNoRows) {
		return "", fmt.Errorf("get latest override: %w", err)
	}

	return domain.ResolveAdmission(rec, latest).Effective, nil
}

// supportingUnitIDs returns the ids of units that currently provide automatic
// support to a concept: they hold the current SAME membership to it (from the
// projection) AND satisfy unitHasActiveSupport. This is the single derivation used
// by both the support state and ActiveSupportUnitIDs.
func supportingUnitIDs(ctx context.Context, q txQuerier, conceptID int64) ([]int64, error) {
	rows, err := q.QueryContext(ctx,
		`SELECT unit_id FROM unit_concept_memberships WHERE concept_id = ?`, conceptID)
	if err != nil {
		return nil, fmt.Errorf("list current members: %w", err)
	}
	var members []int64
	for rows.Next() {
		var uid int64
		if err := rows.Scan(&uid); err != nil {
			rows.Close()
			return nil, err
		}
		members = append(members, uid)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}

	var out []int64
	for _, uid := range members {
		ok, err := unitHasActiveSupport(ctx, q, uid)
		if err != nil {
			return nil, err
		}
		if ok {
			out = append(out, uid)
		}
	}
	return out, nil
}

// deriveSupportState computes a concept's support state from current data.
func deriveSupportState(ctx context.Context, q txQuerier, conceptID int64) (domain.ConceptSupportState, error) {
	ids, err := supportingUnitIDs(ctx, q, conceptID)
	if err != nil {
		return "", err
	}
	if len(ids) > 0 {
		return domain.SupportSupported, nil
	}
	return domain.SupportOrphaned, nil
}

// ---- concept CRUD ----

// UnitByID returns one persisted knowledge unit by id, or domain.ErrNotFound.
func (r *ConceptRepository) UnitByID(ctx context.Context, unitID int64) (*domain.KnowledgeUnit, error) {
	row := r.db.QueryRowContext(ctx,
		`SELECT id, extraction_id, ordinal, kind, canonical, statement, example, confidence, created_at
		 FROM knowledge_units WHERE id = ?`, unitID)
	u, err := scanUnit(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, domain.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get unit: %w", err)
	}
	return u, nil
}

// FindActiveBySignature returns the non-retired concept(s) that own the given
// durable identity signature. Support is NOT a filter: an orphaned (currently
// unsupported) concept still owns its identity, so a new unit with that signature
// resolves SAME to it rather than spawning a duplicate. Under the durable-identity
// index there is at most one non-retired concept per signature, so this returns
// zero or one row.
func (r *ConceptRepository) FindActiveBySignature(ctx context.Context, sig string) ([]domain.KnowledgeConcept, error) {
	rows, err := r.db.QueryContext(ctx,
		conceptSelect+` WHERE signature = ? AND lifecycle_state != 'retired' ORDER BY id ASC`, sig)
	if err != nil {
		return nil, fmt.Errorf("find by signature: %w", err)
	}
	concepts, err := r.scanConceptsWithSupport(ctx, rows)
	if err != nil {
		return nil, err
	}
	return concepts, nil
}

// CreateConcept inserts a new concept from a validated identity, refusing a
// duplicate DURABLE identity (non-retired). When in.LinkSeedAsSame is set it also
// records the seed unit's SAME membership in the same transaction, so create and
// attach are atomic. Create+seed only ESTABLISHES membership for an unresolved
// unit: if the seed unit already has a current SAME membership it returns
// ErrConceptConflict and creates nothing — moving an existing membership is the
// exclusive job of ReassignSame, never a side effect of concept creation. An
// effectively INVALID seed unit also returns ErrConceptConflict and rolls back the
// concept insert; it must be restored explicitly before SAME can be established.
func (r *ConceptRepository) CreateConcept(ctx context.Context, in domain.NewConceptInput) (*domain.KnowledgeConcept, *domain.UnitConceptLink, error) {
	if err := in.Identity.Validate(); err != nil {
		return nil, nil, err
	}
	if in.LinkSeedAsSame && in.SeedUnitID == nil {
		return nil, nil, fmt.Errorf("%w: seed membership requested without a seed unit", domain.ErrValidation)
	}
	sig := in.Identity.Signature()
	features, err := encodeFeatures(in.Identity.Normalized().IdentityFeatures)
	if err != nil {
		return nil, nil, err
	}

	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, nil, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	// A non-retired concept with this durable identity must not already exist.
	var existing int64
	err = tx.QueryRowContext(ctx,
		`SELECT id FROM knowledge_concepts
		 WHERE identity_schema_version = ? AND signature = ? AND lifecycle_state != 'retired'
		 LIMIT 1`, domain.ConceptIdentitySchemaVersion, sig).Scan(&existing)
	if err == nil {
		return nil, nil, fmt.Errorf("%w: a concept with this identity already exists", domain.ErrConceptConflict)
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, nil, fmt.Errorf("check existing concept: %w", err)
	}

	if in.SeedUnitID != nil {
		if err := unitExists(ctx, tx, *in.SeedUnitID); err != nil {
			return nil, nil, err
		}
	}

	now := r.now()
	ts := now.Format(rfc3339)
	res, err := tx.ExecContext(ctx,
		`INSERT INTO knowledge_concepts
		   (identity_schema_version, target, pedagogical_intent, scope, identity_features, signature, preferred_unit_id, lifecycle_state, created_at, updated_at)
		 VALUES (?, ?, ?, ?, ?, ?, NULL, 'normal', ?, ?)`,
		domain.ConceptIdentitySchemaVersion, in.Identity.Target, in.Identity.PedagogicalIntent,
		in.Identity.Scope, features, sig, ts, ts)
	if err != nil {
		return nil, nil, fmt.Errorf("insert concept: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return nil, nil, fmt.Errorf("concept last insert id: %w", err)
	}

	// Atomic create-and-attach: record the seed SAME membership in this same
	// transaction so a link failure rolls back the concept too.
	var seedLink *domain.UnitConceptLink
	if in.LinkSeedAsSame {
		// Create+seed may only ESTABLISH membership for an unresolved unit. It must
		// never move an existing CURRENT SAME membership: that is the exclusive job
		// of the explicit ReassignSame correction path. If the seed unit already
		// belongs SAME to some concept, refuse and roll the whole transaction back —
		// the new concept must not be created and no membership is touched.
		existing, err := currentMembership(ctx, tx, *in.SeedUnitID)
		if err != nil {
			return nil, nil, err
		}
		if existing != nil {
			return nil, nil, fmt.Errorf("%w: seed unit already has a current SAME membership; use ReassignSame to move it", domain.ErrConceptConflict)
		}

		source := in.SeedSource
		if source == "" {
			source = domain.SourceHuman
		}
		evidence := in.SeedEvidence
		if evidence == "" {
			evidence = "{}"
		}
		link, err := r.applySame(ctx, tx, *in.SeedUnitID, id, source, nil, evidence, now)
		if err != nil {
			return nil, nil, err
		}
		seedLink = link
	}

	if err := tx.Commit(); err != nil {
		return nil, nil, fmt.Errorf("commit tx: %w", err)
	}

	norm := in.Identity.Normalized()
	concept := &domain.KnowledgeConcept{
		ID:                    id,
		IdentitySchemaVersion: domain.ConceptIdentitySchemaVersion,
		Target:                in.Identity.Target,
		PedagogicalIntent:     in.Identity.PedagogicalIntent,
		Scope:                 in.Identity.Scope,
		IdentityFeatures:      norm.IdentityFeatures,
		Signature:             sig,
		Lifecycle:             domain.LifecycleNormal,
		CreatedAt:             now,
		UpdatedAt:             now,
	}
	// Fill derived support/effective state from current data.
	support, err := deriveSupportState(ctx, r.db, id)
	if err != nil {
		return nil, nil, err
	}
	concept.Support = support
	concept.State = domain.EffectiveConceptState(concept.Lifecycle, support)
	return concept, seedLink, nil
}

// GetConcept returns one concept (with derived support) and its full append-only
// event history (newest first).
func (r *ConceptRepository) GetConcept(ctx context.Context, conceptID int64) (*domain.ConceptView, error) {
	row := r.db.QueryRowContext(ctx, conceptSelect+` WHERE id = ?`, conceptID)
	c, err := scanConcept(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, domain.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get concept: %w", err)
	}
	if err := r.fillSupport(ctx, r.db, c); err != nil {
		return nil, err
	}
	links, err := r.linksByConcept(ctx, conceptID)
	if err != nil {
		return nil, err
	}
	return &domain.ConceptView{Concept: *c, Links: links}, nil
}

// ListConcepts returns concepts filtered by effective state (nil = all), newest
// first. Support is derived per concept; a state filter is applied after
// derivation so active/orphaned reflect current data.
func (r *ConceptRepository) ListConcepts(ctx context.Context, state *domain.ConceptState) ([]domain.KnowledgeConcept, error) {
	rows, err := r.db.QueryContext(ctx, conceptSelect+` ORDER BY id DESC`)
	if err != nil {
		return nil, fmt.Errorf("list concepts: %w", err)
	}
	all, err := r.scanConceptsWithSupport(ctx, rows)
	if err != nil {
		return nil, err
	}
	if state == nil {
		return all, nil
	}
	out := make([]domain.KnowledgeConcept, 0, len(all))
	for _, c := range all {
		if c.State == *state {
			out = append(out, c)
		}
	}
	return out, nil
}

// ---- resolution events / membership ----

// LinkSame records an accepted SAME membership and sets it as the unit's current
// membership. It enforces at-most-one CURRENT SAME per unit: re-affirming the same
// concept is idempotent; a SAME to a different concept while one is current is a
// conflict (use ReassignSame). Effectively INVALID units cannot establish SAME
// until restored. Appends an immutable event.
func (r *ConceptRepository) LinkSame(ctx context.Context, unitID, conceptID int64, source domain.DecisionSource, score *float64, evidence string) (*domain.UnitConceptLink, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	if err := unitExists(ctx, tx, unitID); err != nil {
		return nil, err
	}
	if err := conceptExists(ctx, tx, conceptID); err != nil {
		return nil, err
	}

	current, err := currentMembership(ctx, tx, unitID)
	if err != nil {
		return nil, err
	}
	if current != nil {
		if current.conceptID == conceptID {
			// Idempotent re-affirmation: return the in-force event.
			link, lerr := r.linkByID(ctx, tx, current.linkID)
			if lerr != nil {
				return nil, lerr
			}
			if cerr := tx.Commit(); cerr != nil {
				return nil, fmt.Errorf("commit tx: %w", cerr)
			}
			return link, nil
		}
		return nil, fmt.Errorf("%w: unit already has a current SAME membership to another concept", domain.ErrConceptConflict)
	}

	if evidence == "" {
		evidence = "{}"
	}
	link, err := r.applySame(ctx, tx, unitID, conceptID, source, score, evidence, r.now())
	if err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit tx: %w", err)
	}
	return link, nil
}

// ReassignSame moves a unit's current SAME membership to a different concept as an
// explicit human correction. It appends a superseding event, updates the current
// projection, and clears the old concept's preferred unit if it pointed at this
// unit — all atomically. Effectively INVALID units cannot establish or move SAME
// until restored. History is preserved: the prior event row is untouched.
func (r *ConceptRepository) ReassignSame(ctx context.Context, unitID, conceptID int64, source domain.DecisionSource, evidence string) (*domain.UnitConceptLink, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	if err := unitExists(ctx, tx, unitID); err != nil {
		return nil, err
	}
	if err := conceptExists(ctx, tx, conceptID); err != nil {
		return nil, err
	}

	current, err := currentMembership(ctx, tx, unitID)
	if err != nil {
		return nil, err
	}
	if current != nil && current.conceptID == conceptID {
		// Already the current concept: idempotent.
		link, lerr := r.linkByID(ctx, tx, current.linkID)
		if lerr != nil {
			return nil, lerr
		}
		if cerr := tx.Commit(); cerr != nil {
			return nil, fmt.Errorf("commit tx: %w", cerr)
		}
		return link, nil
	}

	if evidence == "" {
		evidence = "{}"
	}
	now := r.now()

	var supersedes *int64
	if current != nil {
		id := current.linkID
		supersedes = &id
		// If the OLD concept's preferred unit is this unit, clear it: the unit is no
		// longer a member there, so an invalid preferred_unit_id must not remain.
		if _, err := tx.ExecContext(ctx,
			`UPDATE knowledge_concepts SET preferred_unit_id = NULL, updated_at = ?
			 WHERE id = ? AND preferred_unit_id = ?`,
			now.Format(rfc3339), current.conceptID, unitID); err != nil {
			return nil, fmt.Errorf("clear stale preferred unit: %w", err)
		}
	}

	link, err := r.applySameEvent(ctx, tx, unitID, conceptID, source, nil, evidence, supersedes, now)
	if err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit tx: %w", err)
	}
	return link, nil
}

// RejectSame records an explicit membership-level correction and clears the unit's
// current SAME membership, all in one transaction. It is separate from unit-level
// INVALID and never writes unit_resolution_judgments. It appends an immutable
// rejection event (relation='same', status='rejected') that references the
// previously-in-force SAME event via supersedes_link_id — so the human judgment
// survives as queryable negative evidence, not merely as a deleted projection row —
// then removes the unit from unit_concept_memberships and clears the old concept's
// preferred_unit_id when it pointed at this unit. History is preserved: the prior
// event row is untouched, and the concept's derived support drops on the next read.
// When the unit has no current SAME membership the postcondition already holds, so
// the call is an idempotent no-op returning (nil, nil).
func (r *ConceptRepository) RejectSame(ctx context.Context, unitID int64, source domain.DecisionSource, evidence string) (*domain.UnitConceptLink, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	if err := unitExists(ctx, tx, unitID); err != nil {
		return nil, err
	}

	current, err := currentMembership(ctx, tx, unitID)
	if err != nil {
		return nil, err
	}
	if current == nil {
		// No current SAME membership: the desired postcondition (unit belongs to no
		// concept) already holds. Do not fabricate a rejection event pointing at
		// nothing; the operation is a deterministic idempotent no-op.
		if err := tx.Commit(); err != nil {
			return nil, fmt.Errorf("commit tx: %w", err)
		}
		return nil, nil
	}

	if evidence == "" {
		evidence = "{}"
	}
	now := r.now()
	supersedes := current.linkID

	// Append the immutable rejected-SAME event: relation stays 'same' (this is about
	// a SAME membership being rejected, not a new relation kind) with status
	// 'rejected', pointing back at the SAME event it invalidates.
	link, err := insertLink(ctx, tx, unitID, current.conceptID, domain.RelationSame, domain.LinkRejected, source, domain.ConceptResolverVersion, nil, evidence, &supersedes, now)
	if err != nil {
		return nil, err
	}

	// Clear the current-membership projection: the unit now belongs to no concept.
	if _, err := tx.ExecContext(ctx,
		`DELETE FROM unit_concept_memberships WHERE unit_id = ?`, unitID); err != nil {
		return nil, fmt.Errorf("clear current membership: %w", err)
	}

	// If the old concept's preferred unit was this unit, it is no longer a member
	// there; clear the now-invalid preferred_unit_id.
	if _, err := tx.ExecContext(ctx,
		`UPDATE knowledge_concepts SET preferred_unit_id = NULL, updated_at = ?
		 WHERE id = ? AND preferred_unit_id = ?`,
		now.Format(rfc3339), current.conceptID, unitID); err != nil {
		return nil, fmt.Errorf("clear stale preferred unit: %w", err)
	}

	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit tx: %w", err)
	}
	return link, nil
}

// MarkUnitInvalid records a unit-level INVALID judgment, clearing any current SAME
// membership in the same transaction so the product state stays internally
// consistent (a unit is never simultaneously SAME to a concept and effectively
// invalid). Concretely, atomically: if the unit currently has a SAME membership it
// appends an immutable rejected-SAME event (negative membership evidence),
// removes the current-membership projection row, and clears a now-invalid
// preferred_unit_id — exactly the RejectSame behavior — and then, unless the unit
// is already effectively invalid, appends an append-only unit-level 'invalid'
// judgment. Marking an already-invalid unit is idempotent (no second judgment).
func (r *ConceptRepository) MarkUnitInvalid(ctx context.Context, unitID int64, source domain.DecisionSource, note, evidence string) (*domain.UnitResolutionJudgment, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	if err := unitExists(ctx, tx, unitID); err != nil {
		return nil, err
	}

	now := r.now()

	// Conservative atomic rule (spec 5, option A): clearing any current SAME first
	// guarantees we never leave a unit that is both SAME to a concept and INVALID.
	if err := r.clearCurrentSame(ctx, tx, unitID, source, now); err != nil {
		return nil, err
	}

	// Idempotency: if the latest judgment already marks the unit invalid, do not
	// append a second identical judgment.
	latest, err := latestUnitJudgment(ctx, tx, unitID)
	if err != nil {
		return nil, err
	}
	if domain.EffectiveUnitInvalid(latest) {
		if err := tx.Commit(); err != nil {
			return nil, fmt.Errorf("commit tx: %w", err)
		}
		return latest, nil
	}

	judgment, err := insertUnitJudgment(ctx, tx, unitID, domain.UnitInvalid, source, note, evidence, now)
	if err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit tx: %w", err)
	}
	return judgment, nil
}

// RestoreUnit withdraws a prior INVALID judgment by appending a 'restored' event,
// returning the unit to the normal review queue. It never deletes the historical
// 'invalid' judgment and never recreates a cleared SAME membership. Restoring a
// unit that is not currently invalid is an idempotent no-op returning (nil, nil).
func (r *ConceptRepository) RestoreUnit(ctx context.Context, unitID int64, source domain.DecisionSource, note, evidence string) (*domain.UnitResolutionJudgment, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	if err := unitExists(ctx, tx, unitID); err != nil {
		return nil, err
	}

	latest, err := latestUnitJudgment(ctx, tx, unitID)
	if err != nil {
		return nil, err
	}
	if !domain.EffectiveUnitInvalid(latest) {
		// Not currently invalid: the postcondition (valid/reviewable) already holds.
		if err := tx.Commit(); err != nil {
			return nil, fmt.Errorf("commit tx: %w", err)
		}
		return nil, nil
	}

	judgment, err := insertUnitJudgment(ctx, tx, unitID, domain.UnitRestored, source, note, evidence, r.now())
	if err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit tx: %w", err)
	}
	return judgment, nil
}

// LatestUnitJudgment returns the unit's most recent judgment (by created_at, then
// id), or (nil, nil) when it has none. Returns ErrNotFound if the unit is missing.
func (r *ConceptRepository) LatestUnitJudgment(ctx context.Context, unitID int64) (*domain.UnitResolutionJudgment, error) {
	if err := unitExists(ctx, r.db, unitID); err != nil {
		return nil, err
	}
	return latestUnitJudgment(ctx, r.db, unitID)
}

// ListUnitJudgments returns a unit's full append-only judgment history, newest
// first. Returns ErrNotFound if the unit is missing.
func (r *ConceptRepository) ListUnitJudgments(ctx context.Context, unitID int64) ([]domain.UnitResolutionJudgment, error) {
	if err := unitExists(ctx, r.db, unitID); err != nil {
		return nil, err
	}
	rows, err := r.db.QueryContext(ctx, unitJudgmentSelect+` WHERE unit_id = ? ORDER BY created_at DESC, id DESC`, unitID)
	if err != nil {
		return nil, fmt.Errorf("list unit judgments: %w", err)
	}
	defer rows.Close()
	var out []domain.UnitResolutionJudgment
	for rows.Next() {
		j, err := scanUnitJudgment(rows)
		if err != nil {
			return nil, fmt.Errorf("scan unit judgment: %w", err)
		}
		out = append(out, *j)
	}
	return out, rows.Err()
}

// RecordDistinction records an explicit human DISTINCT negative pair. It creates no
// membership and no relation and never changes SAME membership; the unit stays
// reviewable. A distinction from the unit's CURRENT SAME concept is contradictory
// and returns ErrConceptConflict without inserting anything. Both the unit and the
// concept must exist.
func (r *ConceptRepository) RecordDistinction(ctx context.Context, unitID, conceptID int64, source domain.DecisionSource, evidence string) (*domain.UnitConceptDistinction, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	if err := unitExists(ctx, tx, unitID); err != nil {
		return nil, err
	}
	if err := conceptExists(ctx, tx, conceptID); err != nil {
		return nil, err
	}
	current, err := currentMembership(ctx, tx, unitID)
	if err != nil {
		return nil, err
	}
	if current != nil && current.conceptID == conceptID {
		return nil, fmt.Errorf("%w: unit cannot be DISTINCT from its current SAME concept", domain.ErrConceptConflict)
	}

	if evidence == "" {
		evidence = "{}"
	}
	now := r.now()
	ts := now.Format(rfc3339)
	res, err := tx.ExecContext(ctx,
		`INSERT INTO unit_concept_distinctions
		   (unit_id, concept_id, decision_source, resolver_version, evidence, created_at)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		unitID, conceptID, string(source), domain.ConceptResolverVersion, evidence, ts)
	if err != nil {
		return nil, fmt.Errorf("insert distinction: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return nil, fmt.Errorf("distinction last insert id: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit tx: %w", err)
	}
	return &domain.UnitConceptDistinction{
		ID: id, UnitID: unitID, ConceptID: conceptID, DecisionSource: source,
		ResolverVersion: domain.ConceptResolverVersion, Evidence: evidence, CreatedAt: now,
	}, nil
}

// ListDistinctions returns a unit's full append-only DISTINCT history, newest
// first. Returns ErrNotFound if the unit is missing.
func (r *ConceptRepository) ListDistinctions(ctx context.Context, unitID int64) ([]domain.UnitConceptDistinction, error) {
	if err := unitExists(ctx, r.db, unitID); err != nil {
		return nil, err
	}
	rows, err := r.db.QueryContext(ctx,
		`SELECT id, unit_id, concept_id, decision_source, resolver_version, evidence, created_at
		 FROM unit_concept_distinctions WHERE unit_id = ? ORDER BY created_at DESC, id DESC`, unitID)
	if err != nil {
		return nil, fmt.Errorf("list distinctions: %w", err)
	}
	defer rows.Close()
	var out []domain.UnitConceptDistinction
	for rows.Next() {
		d, err := scanDistinction(rows)
		if err != nil {
			return nil, fmt.Errorf("scan distinction: %w", err)
		}
		out = append(out, *d)
	}
	return out, rows.Err()
}

// clearCurrentSame clears a unit's current SAME membership if it has one, appending
// an immutable rejected-SAME event (negative evidence) that supersedes the in-force
// SAME, removing the projection row, and clearing a now-invalid preferred_unit_id.
// It is the shared core of RejectSame and MarkUnitInvalid. When the unit has no
// current SAME membership it does nothing.
func (r *ConceptRepository) clearCurrentSame(ctx context.Context, tx *sql.Tx, unitID int64, source domain.DecisionSource, now time.Time) error {
	current, err := currentMembership(ctx, tx, unitID)
	if err != nil {
		return err
	}
	if current == nil {
		return nil
	}
	supersedes := current.linkID
	if _, err := insertLink(ctx, tx, unitID, current.conceptID, domain.RelationSame, domain.LinkRejected, source, domain.ConceptResolverVersion, nil, "{}", &supersedes, now); err != nil {
		return err
	}
	if _, err := tx.ExecContext(ctx,
		`DELETE FROM unit_concept_memberships WHERE unit_id = ?`, unitID); err != nil {
		return fmt.Errorf("clear current membership: %w", err)
	}
	if _, err := tx.ExecContext(ctx,
		`UPDATE knowledge_concepts SET preferred_unit_id = NULL, updated_at = ?
		 WHERE id = ? AND preferred_unit_id = ?`,
		now.Format(rfc3339), current.conceptID, unitID); err != nil {
		return fmt.Errorf("clear stale preferred unit: %w", err)
	}
	return nil
}

// LinkRelation records a non-membership BROADER/NARROWER/RELATED decision as an
// immutable event. A repeated identical (unit, concept, relation) appends a new
// event that supersedes the prior current one via supersedes_link_id (the old row
// is never rewritten). It never touches SAME membership or support.
func (r *ConceptRepository) LinkRelation(ctx context.Context, unitID, conceptID int64, relation domain.ConceptRelation, source domain.DecisionSource, evidence string) (*domain.UnitConceptLink, error) {
	if relation == domain.RelationSame {
		return nil, fmt.Errorf("%w: use LinkSame for SAME memberships", domain.ErrValidation)
	}
	if !domain.ValidConceptRelation(relation) {
		return nil, fmt.Errorf("%w: unknown relation", domain.ErrValidation)
	}

	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	if err := unitExists(ctx, tx, unitID); err != nil {
		return nil, err
	}
	if err := conceptExists(ctx, tx, conceptID); err != nil {
		return nil, err
	}

	// Find the current (newest, not-yet-superseded) event for this exact triple to
	// record as the one being superseded. We never rewrite it.
	var prior sql.NullInt64
	err = tx.QueryRowContext(ctx,
		`SELECT id FROM unit_concept_links
		 WHERE unit_id = ? AND concept_id = ? AND relation = ? AND status = 'accepted'
		   AND id NOT IN (SELECT supersedes_link_id FROM unit_concept_links WHERE supersedes_link_id IS NOT NULL)
		 ORDER BY id DESC LIMIT 1`,
		unitID, conceptID, string(relation)).Scan(&prior)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return nil, fmt.Errorf("find prior relation: %w", err)
	}
	var supersedes *int64
	if prior.Valid {
		id := prior.Int64
		supersedes = &id
	}

	if evidence == "" {
		evidence = "{}"
	}
	link, err := insertLink(ctx, tx, unitID, conceptID, relation, domain.LinkAccepted, source, domain.ConceptResolverVersion, nil, evidence, supersedes, r.now())
	if err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit tx: %w", err)
	}
	return link, nil
}

// SetPreferredUnit sets the preferred representation, validating that the unit
// currently holds the SAME membership to this concept. It leaves membership and id
// untouched.
func (r *ConceptRepository) SetPreferredUnit(ctx context.Context, conceptID, unitID int64) (*domain.KnowledgeConcept, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	if err := conceptExists(ctx, tx, conceptID); err != nil {
		return nil, err
	}

	var one int
	err = tx.QueryRowContext(ctx,
		`SELECT 1 FROM unit_concept_memberships WHERE unit_id = ? AND concept_id = ?`,
		unitID, conceptID).Scan(&one)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, fmt.Errorf("%w: preferred unit must currently hold the SAME membership to this concept", domain.ErrValidation)
	}
	if err != nil {
		return nil, fmt.Errorf("check membership: %w", err)
	}

	if _, err := tx.ExecContext(ctx,
		`UPDATE knowledge_concepts SET preferred_unit_id = ?, updated_at = ? WHERE id = ?`,
		unitID, r.now().Format(rfc3339), conceptID); err != nil {
		return nil, fmt.Errorf("set preferred unit: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit tx: %w", err)
	}

	row := r.db.QueryRowContext(ctx, conceptSelect+` WHERE id = ?`, conceptID)
	c, err := scanConcept(row)
	if err != nil {
		return nil, err
	}
	if err := r.fillSupport(ctx, r.db, c); err != nil {
		return nil, err
	}
	return c, nil
}

// ListReviewableUnits returns current-extraction units with no current SAME
// membership, seeded with their default candidate identity.
func (r *ConceptRepository) ListReviewableUnits(ctx context.Context, entryID *int64) ([]domain.ReviewableUnit, error) {
	if entryID != nil {
		if err := entryExists(ctx, r.db, *entryID); err != nil {
			return nil, err
		}
	}

	var entryIDs []int64
	if entryID != nil {
		entryIDs = []int64{*entryID}
	} else {
		rows, err := r.db.QueryContext(ctx, `SELECT DISTINCT entry_id FROM knowledge_extractions`)
		if err != nil {
			return nil, fmt.Errorf("list entries with extractions: %w", err)
		}
		for rows.Next() {
			var id int64
			if err := rows.Scan(&id); err != nil {
				rows.Close()
				return nil, err
			}
			entryIDs = append(entryIDs, id)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}

	var out []domain.ReviewableUnit
	for _, eid := range entryIDs {
		current, err := currentExtractionID(ctx, r.db, eid)
		if err != nil {
			return nil, err
		}
		if current == nil {
			continue
		}
		// A unit is reviewable only when it has no current SAME membership AND is not
		// currently explicitly INVALID. "Currently invalid" means its LATEST judgment
		// (by created_at, then id) is 'invalid'; a later 'restored' judgment (or none)
		// keeps it reviewable. Absence of a judgment means unresolved, not invalid.
		urows, err := r.db.QueryContext(ctx,
			`SELECT id, extraction_id, ordinal, kind, canonical, statement, example, confidence, created_at
			 FROM knowledge_units
			 WHERE extraction_id = ?
			   AND id NOT IN (SELECT unit_id FROM unit_concept_memberships)
			   AND id NOT IN (
			       SELECT j.unit_id FROM unit_resolution_judgments j
			       WHERE j.id = (
			           SELECT id FROM unit_resolution_judgments
			           WHERE unit_id = j.unit_id
			           ORDER BY created_at DESC, id DESC LIMIT 1
			       ) AND j.judgment = 'invalid'
			   )
			 ORDER BY ordinal ASC`, *current)
		if err != nil {
			return nil, fmt.Errorf("list reviewable units: %w", err)
		}
		for urows.Next() {
			u, err := scanUnit(urows)
			if err != nil {
				urows.Close()
				return nil, fmt.Errorf("scan unit: %w", err)
			}
			out = append(out, domain.ReviewableUnit{Unit: *u, Candidate: domain.DeriveCandidateIdentity(*u)})
		}
		urows.Close()
		if err := urows.Err(); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// ActiveSupportUnitIDs returns unit ids currently supporting the concept.
func (r *ConceptRepository) ActiveSupportUnitIDs(ctx context.Context, conceptID int64) ([]int64, error) {
	if err := conceptExists(ctx, r.db, conceptID); err != nil {
		return nil, err
	}
	return supportingUnitIDs(ctx, r.db, conceptID)
}

// GetCurrentMembership returns the unit's CURRENT SAME membership straight from the
// projection, or (nil, nil) when there is none. It never reconstructs currency
// from the append-only event log: a superseded event may still read
// status='accepted', so only unit_concept_memberships is authoritative.
func (r *ConceptRepository) GetCurrentMembership(ctx context.Context, unitID int64) (*domain.CurrentConceptMembership, error) {
	if err := unitExists(ctx, r.db, unitID); err != nil {
		return nil, err
	}
	var (
		m          domain.CurrentConceptMembership
		updatedStr string
	)
	err := r.db.QueryRowContext(ctx,
		`SELECT unit_id, concept_id, link_id, updated_at FROM unit_concept_memberships WHERE unit_id = ?`, unitID).
		Scan(&m.UnitID, &m.ConceptID, &m.LinkID, &updatedStr)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("read current membership: %w", err)
	}
	if m.UpdatedAt, err = time.Parse(rfc3339, updatedStr); err != nil {
		return nil, fmt.Errorf("parse membership updated_at: %w", err)
	}
	return &m, nil
}

// ListUnitConceptLinks returns every immutable concept-link event for one unit,
// newest first. It exposes persisted facts only; effective SAME/relation semantics
// are derived in the domain layer.
func (r *ConceptRepository) ListUnitConceptLinks(ctx context.Context, unitID int64) ([]domain.UnitConceptLink, error) {
	if err := unitExists(ctx, r.db, unitID); err != nil {
		return nil, err
	}
	rows, err := r.db.QueryContext(ctx, linkSelect+` WHERE unit_id = ? ORDER BY created_at DESC, id DESC`, unitID)
	if err != nil {
		return nil, fmt.Errorf("list unit concept links: %w", err)
	}
	defer rows.Close()

	var out []domain.UnitConceptLink
	for rows.Next() {
		link, err := scanLink(rows)
		if err != nil {
			return nil, fmt.Errorf("scan unit concept link: %w", err)
		}
		out = append(out, *link)
	}
	return out, rows.Err()
}

// ---- membership projection helpers ----

// membership is the current SAME projection row for a unit.
type membership struct {
	conceptID int64
	linkID    int64
}

// currentMembership returns the unit's current SAME membership, or nil.
func currentMembership(ctx context.Context, q txQuerier, unitID int64) (*membership, error) {
	var m membership
	err := q.QueryRowContext(ctx,
		`SELECT concept_id, link_id FROM unit_concept_memberships WHERE unit_id = ?`, unitID).
		Scan(&m.conceptID, &m.linkID)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("read current membership: %w", err)
	}
	return &m, nil
}

// applySame appends an original (non-superseding) accepted SAME event and points
// the current-membership projection at it.
func (r *ConceptRepository) applySame(ctx context.Context, tx *sql.Tx, unitID, conceptID int64, source domain.DecisionSource, score *float64, evidence string, now time.Time) (*domain.UnitConceptLink, error) {
	return r.applySameEvent(ctx, tx, unitID, conceptID, source, score, evidence, nil, now)
}

// applySameEvent appends an accepted SAME event (optionally superseding another)
// and upserts the current-membership projection to point at the new event.
func (r *ConceptRepository) applySameEvent(ctx context.Context, tx *sql.Tx, unitID, conceptID int64, source domain.DecisionSource, score *float64, evidence string, supersedes *int64, now time.Time) (*domain.UnitConceptLink, error) {
	latest, err := latestUnitJudgment(ctx, tx, unitID)
	if err != nil {
		return nil, err
	}
	if domain.EffectiveUnitInvalid(latest) {
		return nil, fmt.Errorf("%w: effectively INVALID unit must be restored before establishing SAME membership", domain.ErrConceptConflict)
	}

	link, err := insertLink(ctx, tx, unitID, conceptID, domain.RelationSame, domain.LinkAccepted, source, domain.ConceptResolverVersion, score, evidence, supersedes, now)
	if err != nil {
		return nil, err
	}
	if _, err := tx.ExecContext(ctx,
		`INSERT INTO unit_concept_memberships (unit_id, concept_id, link_id, updated_at)
		 VALUES (?, ?, ?, ?)
		 ON CONFLICT(unit_id) DO UPDATE SET concept_id = excluded.concept_id, link_id = excluded.link_id, updated_at = excluded.updated_at`,
		unitID, conceptID, link.ID, now.Format(rfc3339)); err != nil {
		return nil, fmt.Errorf("update current membership: %w", err)
	}
	return link, nil
}

// ---- link helpers / scanners ----

func insertLink(ctx context.Context, q txQuerier, unitID, conceptID int64, relation domain.ConceptRelation, status domain.LinkStatus, source domain.DecisionSource, resolverVersion string, score *float64, evidence string, supersedes *int64, now time.Time) (*domain.UnitConceptLink, error) {
	var scoreArg any
	if score != nil {
		scoreArg = *score
	}
	var supersedesArg any
	if supersedes != nil {
		supersedesArg = *supersedes
	}
	ts := now.Format(rfc3339)
	res, err := q.ExecContext(ctx,
		`INSERT INTO unit_concept_links
		   (unit_id, concept_id, relation, status, decision_source, resolver_version, score, evidence, supersedes_link_id, created_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		unitID, conceptID, string(relation), string(status), string(source), resolverVersion, scoreArg, evidence, supersedesArg, ts)
	if err != nil {
		return nil, fmt.Errorf("insert link: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return nil, fmt.Errorf("link last insert id: %w", err)
	}
	return &domain.UnitConceptLink{
		ID: id, UnitID: unitID, ConceptID: conceptID, Relation: relation, Status: status,
		DecisionSource: source, ResolverVersion: resolverVersion, Score: score, Evidence: evidence,
		SupersedesLinkID: supersedes, CreatedAt: now,
	}, nil
}

func (r *ConceptRepository) linkByID(ctx context.Context, q txQuerier, linkID int64) (*domain.UnitConceptLink, error) {
	row := q.QueryRowContext(ctx, linkSelect+` WHERE id = ?`, linkID)
	return scanLink(row)
}

func (r *ConceptRepository) linksByConcept(ctx context.Context, conceptID int64) ([]domain.UnitConceptLink, error) {
	rows, err := r.db.QueryContext(ctx, linkSelect+` WHERE concept_id = ? ORDER BY created_at DESC, id DESC`, conceptID)
	if err != nil {
		return nil, fmt.Errorf("list links: %w", err)
	}
	defer rows.Close()
	var out []domain.UnitConceptLink
	for rows.Next() {
		l, err := scanLink(rows)
		if err != nil {
			return nil, fmt.Errorf("scan link: %w", err)
		}
		out = append(out, *l)
	}
	return out, rows.Err()
}

const conceptSelect = `SELECT id, identity_schema_version, target, pedagogical_intent, scope, identity_features, signature, preferred_unit_id, lifecycle_state, created_at, updated_at FROM knowledge_concepts`

// scanConcept reads the persisted columns (including lifecycle) but leaves derived
// Support/State unset; callers fill them via fillSupport.
func scanConcept(s scanner) (*domain.KnowledgeConcept, error) {
	var (
		c          domain.KnowledgeConcept
		features   string
		preferred  sql.NullInt64
		lifecycle  string
		createdStr string
		updatedStr string
	)
	if err := s.Scan(&c.ID, &c.IdentitySchemaVersion, &c.Target, &c.PedagogicalIntent, &c.Scope,
		&features, &c.Signature, &preferred, &lifecycle, &createdStr, &updatedStr); err != nil {
		return nil, err
	}
	f, err := decodeFeatures(features)
	if err != nil {
		return nil, err
	}
	c.IdentityFeatures = f
	if preferred.Valid {
		c.PreferredUnitID = &preferred.Int64
	}
	c.Lifecycle = domain.ConceptLifecycleState(lifecycle)
	if c.CreatedAt, err = time.Parse(rfc3339, createdStr); err != nil {
		return nil, fmt.Errorf("parse created_at: %w", err)
	}
	if c.UpdatedAt, err = time.Parse(rfc3339, updatedStr); err != nil {
		return nil, fmt.Errorf("parse updated_at: %w", err)
	}
	return &c, nil
}

// fillSupport computes and sets the derived Support and effective State on c.
func (r *ConceptRepository) fillSupport(ctx context.Context, q txQuerier, c *domain.KnowledgeConcept) error {
	support, err := deriveSupportState(ctx, q, c.ID)
	if err != nil {
		return err
	}
	c.Support = support
	c.State = domain.EffectiveConceptState(c.Lifecycle, support)
	return nil
}

// scanConceptsWithSupport scans all rows and fills derived support for each. It
// closes rows before deriving support (support derivation issues its own queries,
// and the single-connection pool cannot serve a second query while rows are open).
func (r *ConceptRepository) scanConceptsWithSupport(ctx context.Context, rows *sql.Rows) ([]domain.KnowledgeConcept, error) {
	var out []domain.KnowledgeConcept
	for rows.Next() {
		c, err := scanConcept(rows)
		if err != nil {
			rows.Close()
			return nil, fmt.Errorf("scan concept: %w", err)
		}
		out = append(out, *c)
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return nil, err
	}
	rows.Close()

	for i := range out {
		if err := r.fillSupport(ctx, r.db, &out[i]); err != nil {
			return nil, err
		}
	}
	return out, nil
}

const linkSelect = `SELECT id, unit_id, concept_id, relation, status, decision_source, resolver_version, score, evidence, supersedes_link_id, created_at FROM unit_concept_links`

func scanLink(s scanner) (*domain.UnitConceptLink, error) {
	var (
		l          domain.UnitConceptLink
		relation   string
		status     string
		source     string
		score      sql.NullFloat64
		supersedes sql.NullInt64
		createdStr string
	)
	if err := s.Scan(&l.ID, &l.UnitID, &l.ConceptID, &relation, &status, &source,
		&l.ResolverVersion, &score, &l.Evidence, &supersedes, &createdStr); err != nil {
		return nil, err
	}
	l.Relation = domain.ConceptRelation(relation)
	l.Status = domain.LinkStatus(status)
	l.DecisionSource = domain.DecisionSource(source)
	if score.Valid {
		l.Score = &score.Float64
	}
	if supersedes.Valid {
		l.SupersedesLinkID = &supersedes.Int64
	}
	var err error
	if l.CreatedAt, err = time.Parse(rfc3339, createdStr); err != nil {
		return nil, fmt.Errorf("parse created_at: %w", err)
	}
	return &l, nil
}

// ---- unit judgment / distinction helpers ----

const unitJudgmentSelect = `SELECT id, unit_id, judgment, decision_source, note, evidence, created_at FROM unit_resolution_judgments`

// latestUnitJudgment returns the unit's most recent judgment (by created_at, then
// id), or (nil, nil) when it has none. It does not verify the unit exists.
func latestUnitJudgment(ctx context.Context, q txQuerier, unitID int64) (*domain.UnitResolutionJudgment, error) {
	row := q.QueryRowContext(ctx, unitJudgmentSelect+` WHERE unit_id = ? ORDER BY created_at DESC, id DESC LIMIT 1`, unitID)
	j, err := scanUnitJudgment(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("read latest unit judgment: %w", err)
	}
	return j, nil
}

// insertUnitJudgment appends one append-only unit-level judgment row.
func insertUnitJudgment(ctx context.Context, q txQuerier, unitID int64, kind domain.UnitJudgmentKind, source domain.DecisionSource, note, evidence string, now time.Time) (*domain.UnitResolutionJudgment, error) {
	if evidence == "" {
		evidence = "{}"
	}
	ts := now.Format(rfc3339)
	res, err := q.ExecContext(ctx,
		`INSERT INTO unit_resolution_judgments (unit_id, judgment, decision_source, note, evidence, created_at)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		unitID, string(kind), string(source), note, evidence, ts)
	if err != nil {
		return nil, fmt.Errorf("insert unit judgment: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return nil, fmt.Errorf("unit judgment last insert id: %w", err)
	}
	return &domain.UnitResolutionJudgment{
		ID: id, UnitID: unitID, Judgment: kind, DecisionSource: source,
		Note: note, Evidence: evidence, CreatedAt: now,
	}, nil
}

func scanUnitJudgment(s scanner) (*domain.UnitResolutionJudgment, error) {
	var (
		j          domain.UnitResolutionJudgment
		judgment   string
		source     string
		createdStr string
	)
	if err := s.Scan(&j.ID, &j.UnitID, &judgment, &source, &j.Note, &j.Evidence, &createdStr); err != nil {
		return nil, err
	}
	j.Judgment = domain.UnitJudgmentKind(judgment)
	j.DecisionSource = domain.DecisionSource(source)
	var err error
	if j.CreatedAt, err = time.Parse(rfc3339, createdStr); err != nil {
		return nil, fmt.Errorf("parse created_at: %w", err)
	}
	return &j, nil
}

func scanDistinction(s scanner) (*domain.UnitConceptDistinction, error) {
	var (
		d          domain.UnitConceptDistinction
		source     string
		createdStr string
	)
	if err := s.Scan(&d.ID, &d.UnitID, &d.ConceptID, &source, &d.ResolverVersion, &d.Evidence, &createdStr); err != nil {
		return nil, err
	}
	d.DecisionSource = domain.DecisionSource(source)
	var err error
	if d.CreatedAt, err = time.Parse(rfc3339, createdStr); err != nil {
		return nil, fmt.Errorf("parse created_at: %w", err)
	}
	return &d, nil
}

// ---- existence helpers ----

func entryExists(ctx context.Context, q txQuerier, entryID int64) error {
	var one int
	err := q.QueryRowContext(ctx, `SELECT 1 FROM learning_entries WHERE id = ?`, entryID).Scan(&one)
	if errors.Is(err, sql.ErrNoRows) {
		return domain.ErrNotFound
	}
	if err != nil {
		return fmt.Errorf("check entry: %w", err)
	}
	return nil
}

func unitExists(ctx context.Context, q txQuerier, unitID int64) error {
	var one int
	err := q.QueryRowContext(ctx, `SELECT 1 FROM knowledge_units WHERE id = ?`, unitID).Scan(&one)
	if errors.Is(err, sql.ErrNoRows) {
		return domain.ErrNotFound
	}
	if err != nil {
		return fmt.Errorf("check unit: %w", err)
	}
	return nil
}

func conceptExists(ctx context.Context, q txQuerier, conceptID int64) error {
	var one int
	err := q.QueryRowContext(ctx, `SELECT 1 FROM knowledge_concepts WHERE id = ?`, conceptID).Scan(&one)
	if errors.Is(err, sql.ErrNoRows) {
		return domain.ErrNotFound
	}
	if err != nil {
		return fmt.Errorf("check concept: %w", err)
	}
	return nil
}
