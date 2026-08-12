package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"french-learning-app/internal/domain"
)

// KnowledgeRepository is a SQLite-backed domain.KnowledgeExtractionRepository. It
// keeps all extraction/unit/recommendation SQL in one place and performs the
// atomic persistence of an extraction, its units, and their initial machine
// admission recommendations in a single transaction. Human admission overrides
// live in the sibling AdmissionRepository (a separate type because both boundary
// interfaces declare a Create method).
type KnowledgeRepository struct {
	db  *sql.DB
	now func() time.Time
}

// compile-time check.
var _ domain.KnowledgeExtractionRepository = (*KnowledgeRepository)(nil)

// NewKnowledgeRepository builds a repository over an open database.
func NewKnowledgeRepository(db *sql.DB) *KnowledgeRepository {
	return &KnowledgeRepository{
		db:  db,
		now: func() time.Time { return time.Now().UTC() },
	}
}

// Create atomically persists one extraction, all of its units (each with a
// deterministic ordinal from output order), and exactly one machine admission
// recommendation per unit. It assigns the next per-entry version inside the same
// transaction so concurrent writers cannot assign duplicate versions. Either the
// whole extraction commits or nothing does. Returns domain.ErrNotFound if the
// entry does not exist.
func (r *KnowledgeRepository) Create(ctx context.Context, in domain.NewExtractionInput) (*domain.ExtractionView, error) {
	if len(in.Units) != len(in.Recommendations) {
		return nil, fmt.Errorf("units and recommendations length mismatch")
	}

	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	// Ensure the entry exists before attaching an extraction.
	var exists int
	err = tx.QueryRowContext(ctx, `SELECT 1 FROM learning_entries WHERE id = ?`, in.EntryID).Scan(&exists)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, domain.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("check entry: %w", err)
	}

	// Next version = current max for this entry + 1 (starts at 1).
	var maxVersion sql.NullInt64
	if err := tx.QueryRowContext(ctx,
		`SELECT MAX(version) FROM knowledge_extractions WHERE entry_id = ?`, in.EntryID,
	).Scan(&maxVersion); err != nil {
		return nil, fmt.Errorf("read max version: %w", err)
	}
	version := maxVersion.Int64 + 1

	now := r.now()
	ts := now.Format(rfc3339)

	extRes, err := tx.ExecContext(ctx,
		`INSERT INTO knowledge_extractions
		   (entry_id, version, source_analysis_id, source_feedback_id, extractor, created_at)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		in.EntryID, version, in.SourceAnalysisID, nullInt64(in.SourceFeedbackID), in.Extractor, ts,
	)
	if err != nil {
		return nil, fmt.Errorf("insert extraction: %w", err)
	}
	extractionID, err := extRes.LastInsertId()
	if err != nil {
		return nil, fmt.Errorf("extraction last insert id: %w", err)
	}

	view := &domain.ExtractionView{
		Extraction: domain.KnowledgeExtraction{
			ID:               extractionID,
			EntryID:          in.EntryID,
			Version:          version,
			SourceAnalysisID: in.SourceAnalysisID,
			SourceFeedbackID: in.SourceFeedbackID,
			Extractor:        in.Extractor,
			CreatedAt:        now,
		},
		Units: make([]domain.KnowledgeUnitView, 0, len(in.Units)),
	}

	for i := range in.Units {
		u := in.Units[i]
		ordinal := i + 1
		uRes, err := tx.ExecContext(ctx,
			`INSERT INTO knowledge_units
			   (extraction_id, ordinal, kind, canonical, statement, example, confidence, created_at)
			 VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
			extractionID, ordinal, string(u.Kind), u.Canonical, u.Statement,
			nullString(u.Example), u.Confidence, ts,
		)
		if err != nil {
			return nil, fmt.Errorf("insert unit: %w", err)
		}
		unitID, err := uRes.LastInsertId()
		if err != nil {
			return nil, fmt.Errorf("unit last insert id: %w", err)
		}

		rec := in.Recommendations[i]
		if _, err := tx.ExecContext(ctx,
			`INSERT INTO knowledge_admission_recommendations
			   (unit_id, ruleset, state, reason, created_at)
			 VALUES (?, ?, ?, ?, ?)`,
			unitID, rec.Ruleset, string(rec.State), rec.Reason, ts,
		); err != nil {
			return nil, fmt.Errorf("insert recommendation: %w", err)
		}

		view.Units = append(view.Units, domain.KnowledgeUnitView{
			Unit: domain.KnowledgeUnit{
				ID:           unitID,
				ExtractionID: extractionID,
				Ordinal:      ordinal,
				Kind:         u.Kind,
				Canonical:    u.Canonical,
				Statement:    u.Statement,
				Example:      u.Example,
				Confidence:   u.Confidence,
				CreatedAt:    now,
			},
			// No override exists yet, so the effective state equals the machine
			// recommendation.
			Admission: domain.ResolveAdmission(rec, nil),
		})
	}

	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit tx: %w", err)
	}
	return view, nil
}

// ListByEntry returns every extraction for entryID (each fully assembled with its
// units and admission state), newest version first. Returns domain.ErrNotFound if
// the entry does not exist.
func (r *KnowledgeRepository) ListByEntry(ctx context.Context, entryID int64) ([]*domain.ExtractionView, error) {
	var exists int
	err := r.db.QueryRowContext(ctx, `SELECT 1 FROM learning_entries WHERE id = ?`, entryID).Scan(&exists)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, domain.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("check entry: %w", err)
	}

	rows, err := r.db.QueryContext(ctx,
		`SELECT id, entry_id, version, source_analysis_id, source_feedback_id, extractor, created_at
		 FROM knowledge_extractions
		 WHERE entry_id = ?
		 ORDER BY version DESC`, entryID)
	if err != nil {
		return nil, fmt.Errorf("list extractions: %w", err)
	}
	defer rows.Close()

	var extractions []domain.KnowledgeExtraction
	for rows.Next() {
		e, err := scanExtraction(rows)
		if err != nil {
			return nil, fmt.Errorf("scan extraction: %w", err)
		}
		extractions = append(extractions, *e)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate extractions: %w", err)
	}

	out := make([]*domain.ExtractionView, 0, len(extractions))
	for i := range extractions {
		units, err := r.loadUnits(ctx, extractions[i].ID)
		if err != nil {
			return nil, err
		}
		out = append(out, &domain.ExtractionView{Extraction: extractions[i], Units: units})
	}
	return out, nil
}

// GetByID returns one extraction with its units and admission state, or
// domain.ErrNotFound.
func (r *KnowledgeRepository) GetByID(ctx context.Context, extractionID int64) (*domain.ExtractionView, error) {
	row := r.db.QueryRowContext(ctx,
		`SELECT id, entry_id, version, source_analysis_id, source_feedback_id, extractor, created_at
		 FROM knowledge_extractions
		 WHERE id = ?`, extractionID)
	e, err := scanExtraction(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, domain.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get extraction: %w", err)
	}

	units, err := r.loadUnits(ctx, e.ID)
	if err != nil {
		return nil, err
	}
	return &domain.ExtractionView{Extraction: *e, Units: units}, nil
}

// loadUnits reads all units of an extraction (ordered by ordinal) and resolves
// each unit's admission state from its machine recommendation and latest human
// override, all against r.db.
func (r *KnowledgeRepository) loadUnits(ctx context.Context, extractionID int64) ([]domain.KnowledgeUnitView, error) {
	rows, err := r.db.QueryContext(ctx,
		`SELECT id, extraction_id, ordinal, kind, canonical, statement, example, confidence, created_at
		 FROM knowledge_units
		 WHERE extraction_id = ?
		 ORDER BY ordinal ASC`, extractionID)
	if err != nil {
		return nil, fmt.Errorf("list units: %w", err)
	}
	defer rows.Close()

	var units []domain.KnowledgeUnit
	for rows.Next() {
		u, err := scanUnit(rows)
		if err != nil {
			return nil, fmt.Errorf("scan unit: %w", err)
		}
		units = append(units, *u)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate units: %w", err)
	}

	out := make([]domain.KnowledgeUnitView, 0, len(units))
	for i := range units {
		admission, err := r.resolveAdmission(ctx, units[i].ID)
		if err != nil {
			return nil, err
		}
		out = append(out, domain.KnowledgeUnitView{Unit: units[i], Admission: *admission})
	}
	return out, nil
}

// resolveAdmission loads a unit's machine recommendation and latest override and
// derives the effective admission state, against r.db.
func (r *KnowledgeRepository) resolveAdmission(ctx context.Context, unitID int64) (*domain.AdmissionState, error) {
	return resolveAdmission(ctx, r.db, unitID)
}

// AdmissionRepository is a SQLite-backed domain.AdmissionOverrideRepository. It is
// a separate type from KnowledgeRepository because both boundary interfaces
// declare a Create method; splitting them keeps each Create unambiguous while all
// admission-override SQL still lives here.
type AdmissionRepository struct {
	db  *sql.DB
	now func() time.Time
}

// compile-time check.
var _ domain.AdmissionOverrideRepository = (*AdmissionRepository)(nil)

// NewAdmissionRepository builds a repository over an open database.
func NewAdmissionRepository(db *sql.DB) *AdmissionRepository {
	return &AdmissionRepository{
		db:  db,
		now: func() time.Time { return time.Now().UTC() },
	}
}

// Create appends a human admission override for unitID. Returns
// domain.ErrNotFound if the unit does not exist.
func (r *AdmissionRepository) Create(ctx context.Context, unitID int64, in domain.NewAdmissionOverrideInput) (*domain.AdmissionOverride, error) {
	var exists int
	err := r.db.QueryRowContext(ctx, `SELECT 1 FROM knowledge_units WHERE id = ?`, unitID).Scan(&exists)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, domain.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("check unit: %w", err)
	}

	now := r.now()
	ts := now.Format(rfc3339)
	res, err := r.db.ExecContext(ctx,
		`INSERT INTO knowledge_admission_overrides (unit_id, decision, reason, note, created_at)
		 VALUES (?, ?, ?, ?, ?)`,
		unitID, string(in.Decision), in.Reason, in.Note, ts,
	)
	if err != nil {
		return nil, fmt.Errorf("insert override: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return nil, fmt.Errorf("override last insert id: %w", err)
	}
	return &domain.AdmissionOverride{
		ID:        id,
		UnitID:    unitID,
		Decision:  in.Decision,
		Reason:    in.Reason,
		Note:      in.Note,
		CreatedAt: now,
	}, nil
}

// ListByUnit returns every override for unitID, oldest first. Returns
// domain.ErrNotFound if the unit does not exist.
func (r *AdmissionRepository) ListByUnit(ctx context.Context, unitID int64) ([]*domain.AdmissionOverride, error) {
	var exists int
	err := r.db.QueryRowContext(ctx, `SELECT 1 FROM knowledge_units WHERE id = ?`, unitID).Scan(&exists)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, domain.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("check unit: %w", err)
	}

	rows, err := r.db.QueryContext(ctx,
		`SELECT id, unit_id, decision, reason, note, created_at
		 FROM knowledge_admission_overrides
		 WHERE unit_id = ?
		 ORDER BY created_at ASC, id ASC`, unitID)
	if err != nil {
		return nil, fmt.Errorf("list overrides: %w", err)
	}
	defer rows.Close()

	var out []*domain.AdmissionOverride
	for rows.Next() {
		o, err := scanOverride(rows)
		if err != nil {
			return nil, fmt.Errorf("scan override: %w", err)
		}
		out = append(out, o)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate overrides: %w", err)
	}
	return out, nil
}

// GetAdmission returns the resolved admission state for a unit. Returns
// domain.ErrNotFound if the unit does not exist (each persisted unit has exactly
// one recommendation, so a missing recommendation means a missing unit).
func (r *AdmissionRepository) GetAdmission(ctx context.Context, unitID int64) (*domain.AdmissionState, error) {
	return resolveAdmission(ctx, r.db, unitID)
}

// ---- shared admission resolution (free functions over any *sql.DB) ----

// resolveAdmission loads a unit's machine recommendation and latest override and
// derives the effective admission state. It assumes nothing about which repo
// calls it. A missing recommendation row surfaces as domain.ErrNotFound.
func resolveAdmission(ctx context.Context, db *sql.DB, unitID int64) (*domain.AdmissionState, error) {
	rec, err := getRecommendation(ctx, db, unitID)
	if err != nil {
		return nil, err
	}
	latest, err := getLatestOverride(ctx, db, unitID)
	if err != nil {
		return nil, err
	}
	state := domain.ResolveAdmission(*rec, latest)
	return &state, nil
}

// getRecommendation reads the single machine recommendation for a unit.
func getRecommendation(ctx context.Context, db *sql.DB, unitID int64) (*domain.AdmissionRecommendation, error) {
	var rec domain.AdmissionRecommendation
	var state string
	err := db.QueryRowContext(ctx,
		`SELECT ruleset, state, reason
		 FROM knowledge_admission_recommendations
		 WHERE unit_id = ?`, unitID).Scan(&rec.Ruleset, &state, &rec.Reason)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, domain.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get recommendation: %w", err)
	}
	rec.State = domain.MachineAdmissionState(state)
	return &rec, nil
}

// getLatestOverride reads the most recent override for a unit, or (nil, nil) when
// none exists. Ordering by created_at then id is deterministic.
func getLatestOverride(ctx context.Context, db *sql.DB, unitID int64) (*domain.AdmissionOverride, error) {
	row := db.QueryRowContext(ctx,
		`SELECT id, unit_id, decision, reason, note, created_at
		 FROM knowledge_admission_overrides
		 WHERE unit_id = ?
		 ORDER BY created_at DESC, id DESC
		 LIMIT 1`, unitID)
	o, err := scanOverride(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("get latest override: %w", err)
	}
	return o, nil
}

// ---- scanners ----

func scanExtraction(s scanner) (*domain.KnowledgeExtraction, error) {
	var (
		e          domain.KnowledgeExtraction
		feedbackID sql.NullInt64
		createdStr string
	)
	if err := s.Scan(&e.ID, &e.EntryID, &e.Version, &e.SourceAnalysisID,
		&feedbackID, &e.Extractor, &createdStr); err != nil {
		return nil, err
	}
	if feedbackID.Valid {
		e.SourceFeedbackID = &feedbackID.Int64
	}
	var err error
	if e.CreatedAt, err = time.Parse(rfc3339, createdStr); err != nil {
		return nil, fmt.Errorf("parse created_at: %w", err)
	}
	return &e, nil
}

func scanUnit(s scanner) (*domain.KnowledgeUnit, error) {
	var (
		u          domain.KnowledgeUnit
		kind       string
		example    sql.NullString
		createdStr string
	)
	if err := s.Scan(&u.ID, &u.ExtractionID, &u.Ordinal, &kind, &u.Canonical,
		&u.Statement, &example, &u.Confidence, &createdStr); err != nil {
		return nil, err
	}
	u.Kind = domain.KnowledgeKind(kind)
	if example.Valid {
		u.Example = &example.String
	}
	var err error
	if u.CreatedAt, err = time.Parse(rfc3339, createdStr); err != nil {
		return nil, fmt.Errorf("parse created_at: %w", err)
	}
	return &u, nil
}

func scanOverride(s scanner) (*domain.AdmissionOverride, error) {
	var (
		o          domain.AdmissionOverride
		decision   string
		createdStr string
	)
	if err := s.Scan(&o.ID, &o.UnitID, &decision, &o.Reason, &o.Note, &createdStr); err != nil {
		return nil, err
	}
	o.Decision = domain.HumanAdmissionDecision(decision)
	var err error
	if o.CreatedAt, err = time.Parse(rfc3339, createdStr); err != nil {
		return nil, fmt.Errorf("parse created_at: %w", err)
	}
	return &o, nil
}
