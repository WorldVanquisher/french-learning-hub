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
// domain.CurrentExtractionRepository. It owns all concept, resolution-link, and
// current-extraction SQL, and enforces the invariants SQLite cannot express on
// its own (at-most-one accepted SAME per unit, deterministic support recompute)
// inside transactions.
type ConceptRepository struct {
	db  *sql.DB
	now func() time.Time
}

// compile-time checks.
var (
	_ domain.ConceptRepository           = (*ConceptRepository)(nil)
	_ domain.CurrentExtractionRepository = (*ConceptRepository)(nil)
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
// extractions (human rollback). The extraction must belong to the entry. Concept
// support is recomputed for every concept that could gain or lose support as a
// result (all concepts with accepted SAME links to units of either the old or new
// current extraction).
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

	// Concepts whose support may change: any concept with an accepted SAME link to
	// any unit of ANY of this entry's extractions. Changing which extraction is
	// current can move support onto or off of any of them, so this is the correct
	// blast radius (not just the two extractions being swapped).
	affectedIDs, err := conceptsLinkedToEntry(ctx, tx, entryID)
	if err != nil {
		return err
	}

	ts := r.now().Format(rfc3339)
	if _, err := tx.ExecContext(ctx,
		`INSERT INTO entry_current_extractions (entry_id, extraction_id, updated_at)
		 VALUES (?, ?, ?)
		 ON CONFLICT(entry_id) DO UPDATE SET extraction_id = excluded.extraction_id, updated_at = excluded.updated_at`,
		entryID, extractionID, ts); err != nil {
		return fmt.Errorf("set current extraction: %w", err)
	}

	for _, id := range affectedIDs {
		if err := recomputeConceptState(ctx, tx, id, r.now); err != nil {
			return err
		}
	}
	return tx.Commit()
}

// conceptsLinkedToEntry returns distinct concept ids with an accepted SAME link to
// any unit of any extraction belonging to the entry.
func conceptsLinkedToEntry(ctx context.Context, q txQuerier, entryID int64) ([]int64, error) {
	rows, err := q.QueryContext(ctx,
		`SELECT DISTINCT l.concept_id
		 FROM unit_concept_links l
		 JOIN knowledge_units u ON u.id = l.unit_id
		 JOIN knowledge_extractions e ON e.id = u.extraction_id
		 WHERE e.entry_id = ? AND l.relation = 'same' AND l.status = 'accepted'`, entryID)
	if err != nil {
		return nil, fmt.Errorf("concepts linked to entry: %w", err)
	}
	defer rows.Close()
	var out []int64
	for rows.Next() {
		var id int64
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		out = append(out, id)
	}
	return out, rows.Err()
}

// ---- support recompute ----

// unitHasActiveSupport reports whether a unit currently provides automatic
// support: it belongs to its entry's current extraction AND its effective
// admission state is active. The caller guarantees the unit has an accepted SAME
// link to the concept in question.
func unitHasActiveSupport(ctx context.Context, q txQuerier, unitID int64) (bool, error) {
	// Resolve the unit's extraction and entry.
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

	// Effective admission must be active. Reuse the same recommendation + latest
	// override resolution the admission repository uses.
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

// recomputeConceptState deterministically recomputes one concept's state from its
// current support. Retired is sticky (never auto-changed). Otherwise: if any unit
// with an accepted SAME link currently provides active support, the concept is
// active; if none does, it becomes orphaned (never deleted). Only the state and
// updated_at change; identity and id are stable.
func recomputeConceptState(ctx context.Context, q txQuerier, conceptID int64, now func() time.Time) error {
	var state string
	err := q.QueryRowContext(ctx,
		`SELECT state FROM knowledge_concepts WHERE id = ?`, conceptID).Scan(&state)
	if errors.Is(err, sql.ErrNoRows) {
		return domain.ErrNotFound
	}
	if err != nil {
		return fmt.Errorf("read concept state: %w", err)
	}
	if domain.ConceptState(state) == domain.ConceptRetired {
		return nil // sticky
	}

	rows, err := q.QueryContext(ctx,
		`SELECT unit_id FROM unit_concept_links
		 WHERE concept_id = ? AND relation = 'same' AND status = 'accepted'`, conceptID)
	if err != nil {
		return fmt.Errorf("list same members: %w", err)
	}
	var unitIDs []int64
	for rows.Next() {
		var uid int64
		if err := rows.Scan(&uid); err != nil {
			rows.Close()
			return err
		}
		unitIDs = append(unitIDs, uid)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}

	supported := false
	for _, uid := range unitIDs {
		ok, err := unitHasActiveSupport(ctx, q, uid)
		if err != nil {
			return err
		}
		if ok {
			supported = true
			break
		}
	}

	next := domain.ConceptOrphaned
	if supported {
		next = domain.ConceptActive
	}
	if domain.ConceptState(state) == next {
		return nil
	}
	if _, err := q.ExecContext(ctx,
		`UPDATE knowledge_concepts SET state = ?, updated_at = ? WHERE id = ?`,
		string(next), now().Format(rfc3339), conceptID); err != nil {
		return fmt.Errorf("update concept state: %w", err)
	}
	return nil
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

// FindActiveBySignature returns active concepts with the given signature (zero or
// one under the active-signature unique index).
func (r *ConceptRepository) FindActiveBySignature(ctx context.Context, sig string) ([]domain.KnowledgeConcept, error) {
	rows, err := r.db.QueryContext(ctx,
		conceptSelect+` WHERE signature = ? AND state = 'active' ORDER BY id ASC`, sig)
	if err != nil {
		return nil, fmt.Errorf("find by signature: %w", err)
	}
	defer rows.Close()
	return scanConcepts(rows)
}

// CreateConcept inserts a new active concept from a validated identity, refusing a
// duplicate active signature.
func (r *ConceptRepository) CreateConcept(ctx context.Context, in domain.NewConceptInput) (*domain.KnowledgeConcept, error) {
	if err := in.Identity.Validate(); err != nil {
		return nil, err
	}
	sig := in.Identity.Signature()
	features, err := encodeFeatures(in.Identity.Normalized().IdentityFeatures)
	if err != nil {
		return nil, err
	}

	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	// An active concept with this signature must not already exist.
	var existing int64
	err = tx.QueryRowContext(ctx,
		`SELECT id FROM knowledge_concepts WHERE signature = ? AND state = 'active' LIMIT 1`, sig).Scan(&existing)
	if err == nil {
		return nil, fmt.Errorf("%w: an active concept with this identity already exists", domain.ErrConceptConflict)
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, fmt.Errorf("check existing concept: %w", err)
	}

	if in.SeedUnitID != nil {
		if err := unitExists(ctx, tx, *in.SeedUnitID); err != nil {
			return nil, err
		}
	}

	now := r.now()
	ts := now.Format(rfc3339)
	res, err := tx.ExecContext(ctx,
		`INSERT INTO knowledge_concepts
		   (identity_schema_version, target, pedagogical_intent, scope, identity_features, signature, preferred_unit_id, state, created_at, updated_at)
		 VALUES (?, ?, ?, ?, ?, ?, NULL, 'active', ?, ?)`,
		domain.ConceptIdentitySchemaVersion, in.Identity.Target, in.Identity.PedagogicalIntent,
		in.Identity.Scope, features, sig, ts, ts)
	if err != nil {
		return nil, fmt.Errorf("insert concept: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return nil, fmt.Errorf("concept last insert id: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit tx: %w", err)
	}

	norm := in.Identity.Normalized()
	return &domain.KnowledgeConcept{
		ID:                    id,
		IdentitySchemaVersion: domain.ConceptIdentitySchemaVersion,
		Target:                in.Identity.Target,
		PedagogicalIntent:     in.Identity.PedagogicalIntent,
		Scope:                 in.Identity.Scope,
		IdentityFeatures:      norm.IdentityFeatures,
		Signature:             sig,
		State:                 domain.ConceptActive,
		CreatedAt:             now,
		UpdatedAt:             now,
	}, nil
}

// GetConcept returns one concept and its links (newest first).
func (r *ConceptRepository) GetConcept(ctx context.Context, conceptID int64) (*domain.ConceptView, error) {
	row := r.db.QueryRowContext(ctx, conceptSelect+` WHERE id = ?`, conceptID)
	c, err := scanConcept(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, domain.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get concept: %w", err)
	}
	links, err := r.linksByConcept(ctx, conceptID)
	if err != nil {
		return nil, err
	}
	return &domain.ConceptView{Concept: *c, Links: links}, nil
}

// ListConcepts returns concepts filtered by optional state, newest first.
func (r *ConceptRepository) ListConcepts(ctx context.Context, state *domain.ConceptState) ([]domain.KnowledgeConcept, error) {
	q := conceptSelect
	var args []any
	if state != nil {
		q += ` WHERE state = ?`
		args = append(args, string(*state))
	}
	q += ` ORDER BY id DESC`
	rows, err := r.db.QueryContext(ctx, q, args...)
	if err != nil {
		return nil, fmt.Errorf("list concepts: %w", err)
	}
	defer rows.Close()
	return scanConcepts(rows)
}

// ---- resolution links ----

// LinkSame records an accepted SAME membership, enforcing at-most-one accepted
// SAME per unit, then recomputes the concept's support.
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

	// At most one currently accepted SAME per unit.
	var existingConcept sql.NullInt64
	err = tx.QueryRowContext(ctx,
		`SELECT concept_id FROM unit_concept_links
		 WHERE unit_id = ? AND relation = 'same' AND status = 'accepted'
		 LIMIT 1`, unitID).Scan(&existingConcept)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return nil, fmt.Errorf("check existing same: %w", err)
	}
	if err == nil {
		if existingConcept.Int64 == conceptID {
			// Idempotent re-affirmation: return the existing accepted link.
			link, lerr := r.acceptedSameLink(ctx, tx, unitID, conceptID)
			if lerr != nil {
				return nil, lerr
			}
			if cerr := tx.Commit(); cerr != nil {
				return nil, fmt.Errorf("commit tx: %w", cerr)
			}
			return link, nil
		}
		return nil, fmt.Errorf("%w: unit already has an accepted SAME membership to another concept", domain.ErrConceptConflict)
	}

	if evidence == "" {
		evidence = "{}"
	}
	now := r.now()
	link, err := insertLink(ctx, tx, unitID, conceptID, domain.RelationSame, domain.LinkAccepted, source, domain.ConceptResolverVersion, score, evidence, now)
	if err != nil {
		return nil, err
	}
	if err := recomputeConceptState(ctx, tx, conceptID, r.now); err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit tx: %w", err)
	}
	return link, nil
}

// LinkRelation records a non-membership BROADER/NARROWER/RELATED decision,
// superseding any prior identical (unit, concept, relation) accepted row. It never
// touches SAME membership or support.
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

	// Supersede a prior accepted identical relation (append-only history).
	if _, err := tx.ExecContext(ctx,
		`UPDATE unit_concept_links SET status = 'superseded'
		 WHERE unit_id = ? AND concept_id = ? AND relation = ? AND status = 'accepted'`,
		unitID, conceptID, string(relation)); err != nil {
		return nil, fmt.Errorf("supersede prior relation: %w", err)
	}

	if evidence == "" {
		evidence = "{}"
	}
	now := r.now()
	link, err := insertLink(ctx, tx, unitID, conceptID, relation, domain.LinkAccepted, source, domain.ConceptResolverVersion, nil, evidence, now)
	if err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit tx: %w", err)
	}
	return link, nil
}

// SetPreferredUnit sets the preferred representation, validating that the unit has
// an accepted SAME membership to this concept. It leaves membership and id
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
		`SELECT 1 FROM unit_concept_links
		 WHERE unit_id = ? AND concept_id = ? AND relation = 'same' AND status = 'accepted'
		 LIMIT 1`, unitID, conceptID).Scan(&one)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, fmt.Errorf("%w: preferred unit must have an accepted SAME membership to this concept", domain.ErrValidation)
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
	return scanConcept(row)
}

// ListReviewableUnits returns current-extraction units with no accepted SAME
// membership, seeded with their default candidate identity.
func (r *ConceptRepository) ListReviewableUnits(ctx context.Context, entryID *int64) ([]domain.ReviewableUnit, error) {
	if entryID != nil {
		if err := entryExists(ctx, r.db, *entryID); err != nil {
			return nil, err
		}
	}

	// Gather the set of current extraction ids to consider.
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
		urows, err := r.db.QueryContext(ctx,
			`SELECT id, extraction_id, ordinal, kind, canonical, statement, example, confidence, created_at
			 FROM knowledge_units
			 WHERE extraction_id = ?
			   AND id NOT IN (
			     SELECT unit_id FROM unit_concept_links
			     WHERE relation = 'same' AND status = 'accepted'
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
	rows, err := r.db.QueryContext(ctx,
		`SELECT unit_id FROM unit_concept_links
		 WHERE concept_id = ? AND relation = 'same' AND status = 'accepted'`, conceptID)
	if err != nil {
		return nil, fmt.Errorf("list same members: %w", err)
	}
	var candidates []int64
	for rows.Next() {
		var uid int64
		if err := rows.Scan(&uid); err != nil {
			rows.Close()
			return nil, err
		}
		candidates = append(candidates, uid)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}

	var out []int64
	for _, uid := range candidates {
		ok, err := unitHasActiveSupport(ctx, r.db, uid)
		if err != nil {
			return nil, err
		}
		if ok {
			out = append(out, uid)
		}
	}
	return out, nil
}

// ---- link helpers / scanners ----

func insertLink(ctx context.Context, q txQuerier, unitID, conceptID int64, relation domain.ConceptRelation, status domain.LinkStatus, source domain.DecisionSource, resolverVersion string, score *float64, evidence string, now time.Time) (*domain.UnitConceptLink, error) {
	var scoreArg any
	if score != nil {
		scoreArg = *score
	}
	ts := now.Format(rfc3339)
	res, err := q.ExecContext(ctx,
		`INSERT INTO unit_concept_links
		   (unit_id, concept_id, relation, status, decision_source, resolver_version, score, evidence, created_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		unitID, conceptID, string(relation), string(status), string(source), resolverVersion, scoreArg, evidence, ts)
	if err != nil {
		return nil, fmt.Errorf("insert link: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return nil, fmt.Errorf("link last insert id: %w", err)
	}
	return &domain.UnitConceptLink{
		ID: id, UnitID: unitID, ConceptID: conceptID, Relation: relation, Status: status,
		DecisionSource: source, ResolverVersion: resolverVersion, Score: score, Evidence: evidence, CreatedAt: now,
	}, nil
}

func (r *ConceptRepository) acceptedSameLink(ctx context.Context, q txQuerier, unitID, conceptID int64) (*domain.UnitConceptLink, error) {
	row := q.QueryRowContext(ctx,
		linkSelect+` WHERE unit_id = ? AND concept_id = ? AND relation = 'same' AND status = 'accepted' ORDER BY id DESC LIMIT 1`,
		unitID, conceptID)
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

const conceptSelect = `SELECT id, identity_schema_version, target, pedagogical_intent, scope, identity_features, signature, preferred_unit_id, state, created_at, updated_at FROM knowledge_concepts`

func scanConcept(s scanner) (*domain.KnowledgeConcept, error) {
	var (
		c          domain.KnowledgeConcept
		features   string
		preferred  sql.NullInt64
		state      string
		createdStr string
		updatedStr string
	)
	if err := s.Scan(&c.ID, &c.IdentitySchemaVersion, &c.Target, &c.PedagogicalIntent, &c.Scope,
		&features, &c.Signature, &preferred, &state, &createdStr, &updatedStr); err != nil {
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
	c.State = domain.ConceptState(state)
	if c.CreatedAt, err = time.Parse(rfc3339, createdStr); err != nil {
		return nil, fmt.Errorf("parse created_at: %w", err)
	}
	if c.UpdatedAt, err = time.Parse(rfc3339, updatedStr); err != nil {
		return nil, fmt.Errorf("parse updated_at: %w", err)
	}
	return &c, nil
}

func scanConcepts(rows *sql.Rows) ([]domain.KnowledgeConcept, error) {
	var out []domain.KnowledgeConcept
	for rows.Next() {
		c, err := scanConcept(rows)
		if err != nil {
			return nil, fmt.Errorf("scan concept: %w", err)
		}
		out = append(out, *c)
	}
	return out, rows.Err()
}

const linkSelect = `SELECT id, unit_id, concept_id, relation, status, decision_source, resolver_version, score, evidence, created_at FROM unit_concept_links`

func scanLink(s scanner) (*domain.UnitConceptLink, error) {
	var (
		l          domain.UnitConceptLink
		relation   string
		status     string
		source     string
		score      sql.NullFloat64
		createdStr string
	)
	if err := s.Scan(&l.ID, &l.UnitID, &l.ConceptID, &relation, &status, &source,
		&l.ResolverVersion, &score, &l.Evidence, &createdStr); err != nil {
		return nil, err
	}
	l.Relation = domain.ConceptRelation(relation)
	l.Status = domain.LinkStatus(status)
	l.DecisionSource = domain.DecisionSource(source)
	if score.Valid {
		l.Score = &score.Float64
	}
	var err error
	if l.CreatedAt, err = time.Parse(rfc3339, createdStr); err != nil {
		return nil, fmt.Errorf("parse created_at: %w", err)
	}
	return &l, nil
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
