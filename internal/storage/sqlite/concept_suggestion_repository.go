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

// ConceptSuggestionRepository stores FLH-097 advisory suggestions. Suggestions
// live in their own tables and never touch membership, Concepts, judgments,
// distinctions, admission or preferred representation. The single exception is
// ConfirmSuggestion, which records an explicit human SAME through the same
// event path as LinkSame after revalidating the current state in the same
// transaction.
type ConceptSuggestionRepository struct {
	db       *sql.DB
	now      func() time.Time
	concepts *ConceptRepository
}

var _ domain.ConceptSuggestionRepository = (*ConceptSuggestionRepository)(nil)

// NewConceptSuggestionRepository builds a repository over an open database.
func NewConceptSuggestionRepository(db *sql.DB) *ConceptSuggestionRepository {
	r := &ConceptSuggestionRepository{db: db, now: func() time.Time { return time.Now().UTC() }}
	r.concepts = &ConceptRepository{db: db, now: func() time.Time { return r.now() }}
	return r
}

// ---- source state ----

// SuggestionSourceUnits loads each unit and checks it is reviewable now: in
// its entry's current extraction, without a current SAME, not effectively
// INVALID. A unit that is missing or not reviewable is a validation error
// naming its id, so nothing is dropped silently.
func (r *ConceptSuggestionRepository) SuggestionSourceUnits(ctx context.Context, unitIDs []int64) ([]domain.SuggestionSourceUnit, error) {
	out := make([]domain.SuggestionSourceUnit, 0, len(unitIDs))
	for _, id := range unitIDs {
		u, err := r.concepts.UnitByID(ctx, id)
		if errors.Is(err, domain.ErrNotFound) {
			return nil, fmt.Errorf("%w: unit %d does not exist", domain.ErrValidation, id)
		}
		if err != nil {
			return nil, err
		}
		var entryID int64
		if err := r.db.QueryRowContext(ctx, `SELECT entry_id FROM knowledge_extractions WHERE id = ?`, u.ExtractionID).Scan(&entryID); err != nil {
			return nil, fmt.Errorf("locate unit entry: %w", err)
		}
		reasons, _, err := unitStaleReasons(ctx, r.db, id, entryID, u.ExtractionID)
		if err != nil {
			return nil, err
		}
		if len(reasons) > 0 {
			return nil, fmt.Errorf("%w: unit %d is not reviewable (%s)", domain.ErrValidation, id, reasons[0])
		}
		distinct := map[int64]bool{}
		rows, err := r.db.QueryContext(ctx, `SELECT DISTINCT concept_id FROM unit_concept_distinctions WHERE unit_id = ?`, id)
		if err != nil {
			return nil, fmt.Errorf("list distinctions: %w", err)
		}
		for rows.Next() {
			var cid int64
			if err := rows.Scan(&cid); err != nil {
				rows.Close()
				return nil, err
			}
			distinct[cid] = true
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
		out = append(out, domain.SuggestionSourceUnit{Unit: *u, EntryID: entryID, DistinctConceptIDs: distinct})
	}
	return out, nil
}

// SuggestionCatalog returns every non-retired Concept, oldest first.
func (r *ConceptSuggestionRepository) SuggestionCatalog(ctx context.Context) ([]domain.KnowledgeConcept, error) {
	rows, err := r.db.QueryContext(ctx, conceptSelect+` WHERE lifecycle_state != 'retired' ORDER BY id ASC`)
	if err != nil {
		return nil, fmt.Errorf("list suggestion catalog: %w", err)
	}
	defer rows.Close()
	var out []domain.KnowledgeConcept
	for rows.Next() {
		c, err := scanConcept(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *c)
	}
	return out, rows.Err()
}

// ConceptMemberExamples returns up to n CURRENT SAME members' wording per
// Concept: the preferred unit first, then by unit id.
func (r *ConceptSuggestionRepository) ConceptMemberExamples(ctx context.Context, conceptIDs []int64, n int) (map[int64][]domain.SuggestionMemberExample, error) {
	out := make(map[int64][]domain.SuggestionMemberExample, len(conceptIDs))
	for _, cid := range conceptIDs {
		rows, err := r.db.QueryContext(ctx,
			`SELECT u.canonical, u.statement
			 FROM unit_concept_memberships m
			 JOIN knowledge_units u ON u.id = m.unit_id
			 JOIN knowledge_concepts c ON c.id = m.concept_id
			 WHERE m.concept_id = ?
			 ORDER BY CASE WHEN c.preferred_unit_id = u.id THEN 0 ELSE 1 END, u.id
			 LIMIT ?`, cid, n)
		if err != nil {
			return nil, fmt.Errorf("list concept members: %w", err)
		}
		examples := []domain.SuggestionMemberExample{}
		for rows.Next() {
			var m domain.SuggestionMemberExample
			if err := rows.Scan(&m.Canonical, &m.Statement); err != nil {
				rows.Close()
				return nil, err
			}
			examples = append(examples, m)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
		out[cid] = examples
	}
	return out, nil
}

// unitStaleReasons reports what makes a unit not reviewable for the recorded
// source extraction, plus its current SAME membership (nil when none).
func unitStaleReasons(ctx context.Context, q txQuerier, unitID, entryID, sourceExtractionID int64) ([]domain.SuggestionStaleReason, *membership, error) {
	var reasons []domain.SuggestionStaleReason
	current, err := currentExtractionID(ctx, q, entryID)
	if err != nil {
		return nil, nil, err
	}
	if current == nil || *current != sourceExtractionID {
		reasons = append(reasons, domain.StaleUnitNotCurrentExtraction)
	}
	m, err := currentMembership(ctx, q, unitID)
	if err != nil {
		return nil, nil, err
	}
	if m != nil {
		reasons = append(reasons, domain.StaleUnitHasCurrentSame)
	}
	latest, err := latestUnitJudgment(ctx, q, unitID)
	if err != nil {
		return nil, nil, err
	}
	if domain.EffectiveUnitInvalid(latest) {
		reasons = append(reasons, domain.StaleUnitInvalid)
	}
	return reasons, m, nil
}

// deriveItemState fills an item's derived state from current data.
func deriveItemState(ctx context.Context, q txQuerier, item *domain.ConceptSuggestionItem) error {
	reasons, current, err := unitStaleReasons(ctx, q, item.UnitID, item.EntryID, item.SourceExtractionID)
	if err != nil {
		return err
	}
	item.CurrentConceptID = nil
	if current != nil {
		cid := current.conceptID
		item.CurrentConceptID = &cid
	}
	if item.Confirmation != nil {
		// A confirmed item's own SAME is its result, not a staleness reason. A
		// later correction (another CURRENT SAME event) is still reported.
		item.Confirmation.StillCurrent = current != nil && current.linkID == item.Confirmation.LinkID
		if item.Confirmation.StillCurrent {
			kept := reasons[:0]
			for _, r := range reasons {
				if r != domain.StaleUnitHasCurrentSame {
					kept = append(kept, r)
				}
			}
			reasons = kept
		}
	}
	if item.Outcome == domain.SuggestionSuggested && item.SuggestedConceptID != nil {
		target := *item.SuggestedConceptID
		var lifecycle, signature string
		if err := q.QueryRowContext(ctx, `SELECT lifecycle_state, signature FROM knowledge_concepts WHERE id = ?`, target).
			Scan(&lifecycle, &signature); err != nil {
			return fmt.Errorf("read suggested concept: %w", err)
		}
		if lifecycle == string(domain.LifecycleRetired) {
			reasons = append(reasons, domain.StaleTargetRetired)
		}
		for _, c := range item.Candidates {
			if c.ConceptID == target && c.Signature != signature {
				reasons = append(reasons, domain.StaleTargetIdentityChanged)
			}
		}
		// Candidates exclude Concepts with a recorded DISTINCT, so any DISTINCT
		// for this pair was recorded after generation.
		var n int
		if err := q.QueryRowContext(ctx, `SELECT COUNT(*) FROM unit_concept_distinctions WHERE unit_id = ? AND concept_id = ?`,
			item.UnitID, target).Scan(&n); err != nil {
			return fmt.Errorf("read distinctions: %w", err)
		}
		if n > 0 {
			reasons = append(reasons, domain.StaleTargetDistinctRecorded)
		}
	}
	item.StaleReasons = reasons
	switch {
	case item.Confirmation != nil:
		item.State = domain.SuggestionItemConfirmed
	case item.Outcome != domain.SuggestionSuggested:
		item.State = domain.SuggestionItemNoSuggestion
	case len(reasons) > 0:
		item.State = domain.SuggestionItemStale
	default:
		item.State = domain.SuggestionItemOpen
	}
	return nil
}

// ---- runs ----

const suggestionRunSelect = `SELECT id, operation_id, request_unit_ids, status, failure_code, generator,
	candidate_policy, candidate_limit, provider_called, created_at FROM concept_suggestion_runs`

func scanSuggestionRun(s scanner) (*domain.ConceptSuggestionRun, error) {
	var (
		run     domain.ConceptSuggestionRun
		ids     string
		status  string
		failure sql.NullString
		called  int
		created string
	)
	if err := s.Scan(&run.ID, &run.OperationID, &ids, &status, &failure, &run.Generator,
		&run.CandidatePolicy, &run.CandidateLimit, &called, &created); err != nil {
		return nil, err
	}
	if err := json.Unmarshal([]byte(ids), &run.RequestUnitIDs); err != nil {
		return nil, fmt.Errorf("decode request unit ids: %w", err)
	}
	run.Status = domain.SuggestionRunStatus(status)
	if failure.Valid {
		code := domain.SuggestionFailureCode(failure.String)
		run.FailureCode = &code
	}
	run.ProviderCalled = called == 1
	var err error
	if run.CreatedAt, err = time.Parse(rfc3339, created); err != nil {
		return nil, fmt.Errorf("parse run created_at: %w", err)
	}
	return &run, nil
}

func (r *ConceptSuggestionRepository) loadItems(ctx context.Context, q txQuerier, run *domain.ConceptSuggestionRun) error {
	rows, err := q.QueryContext(ctx,
		`SELECT i.id, i.run_id, i.ordinal, i.unit_id, i.entry_id, i.source_extraction_id, i.candidates, i.outcome,
		        i.suggested_concept_id, i.reason, i.created_at, c.id, c.link_id, c.created_at
		 FROM concept_suggestion_items i
		 LEFT JOIN concept_suggestion_confirmations c ON c.item_id = i.id
		 WHERE i.run_id = ? ORDER BY i.ordinal`, run.ID)
	if err != nil {
		return fmt.Errorf("list suggestion items: %w", err)
	}
	var items []domain.ConceptSuggestionItem
	for rows.Next() {
		item, err := scanSuggestionItem(rows)
		if err != nil {
			rows.Close()
			return err
		}
		items = append(items, *item)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for i := range items {
		if err := deriveItemState(ctx, q, &items[i]); err != nil {
			return err
		}
		u, err := scanUnit(q.QueryRowContext(ctx,
			`SELECT id, extraction_id, ordinal, kind, canonical, statement, example, confidence, created_at,
			        statement_en, statement_zh
			 FROM knowledge_units WHERE id = ?`, items[i].UnitID))
		if err != nil {
			return fmt.Errorf("read suggestion unit: %w", err)
		}
		items[i].Unit = u
	}
	run.Items = items
	run.ItemCount = len(items)
	run.SuggestedCount = 0
	for _, it := range items {
		if it.Outcome == domain.SuggestionSuggested {
			run.SuggestedCount++
		}
	}
	return nil
}

func scanSuggestionItem(s scanner) (*domain.ConceptSuggestionItem, error) {
	var (
		item                     domain.ConceptSuggestionItem
		candidates, outcome, cAt string
		suggested                sql.NullInt64
		confID, confLink         sql.NullInt64
		confAt                   sql.NullString
	)
	if err := s.Scan(&item.ID, &item.RunID, &item.Ordinal, &item.UnitID, &item.EntryID, &item.SourceExtractionID,
		&candidates, &outcome, &suggested, &item.Reason, &cAt, &confID, &confLink, &confAt); err != nil {
		return nil, err
	}
	if err := json.Unmarshal([]byte(candidates), &item.Candidates); err != nil {
		return nil, fmt.Errorf("decode candidates: %w", err)
	}
	item.Outcome = domain.SuggestionOutcome(outcome)
	if suggested.Valid {
		id := suggested.Int64
		item.SuggestedConceptID = &id
	}
	var err error
	if item.CreatedAt, err = time.Parse(rfc3339, cAt); err != nil {
		return nil, fmt.Errorf("parse item created_at: %w", err)
	}
	if confID.Valid {
		at, err := time.Parse(rfc3339, confAt.String)
		if err != nil {
			return nil, fmt.Errorf("parse confirmation created_at: %w", err)
		}
		item.Confirmation = &domain.SuggestionConfirmation{ID: confID.Int64, ItemID: item.ID, LinkID: confLink.Int64, CreatedAt: at}
	}
	return &item, nil
}

func (r *ConceptSuggestionRepository) readRun(ctx context.Context, q txQuerier, where string, arg any) (*domain.ConceptSuggestionRun, error) {
	run, err := scanSuggestionRun(q.QueryRowContext(ctx, suggestionRunSelect+` WHERE `+where, arg))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, domain.ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	if err := r.loadItems(ctx, q, run); err != nil {
		return nil, err
	}
	return run, nil
}

// GetSuggestionRun returns one run with its items and derived item states.
func (r *ConceptSuggestionRepository) GetSuggestionRun(ctx context.Context, id int64) (*domain.ConceptSuggestionRun, error) {
	return r.readRun(ctx, r.db, `id = ?`, id)
}

// GetSuggestionRunByOperation returns the committed run for an Idempotency-Key.
func (r *ConceptSuggestionRepository) GetSuggestionRunByOperation(ctx context.Context, operationID string) (*domain.ConceptSuggestionRun, error) {
	return r.readRun(ctx, r.db, `operation_id = ?`, operationID)
}

// ListSuggestionRuns returns the newest runs with item counts (no items).
func (r *ConceptSuggestionRepository) ListSuggestionRuns(ctx context.Context, limit int) ([]domain.ConceptSuggestionRun, error) {
	rows, err := r.db.QueryContext(ctx, suggestionRunSelect+` ORDER BY id DESC LIMIT ?`, limit)
	if err != nil {
		return nil, fmt.Errorf("list suggestion runs: %w", err)
	}
	var runs []domain.ConceptSuggestionRun
	for rows.Next() {
		run, err := scanSuggestionRun(rows)
		if err != nil {
			rows.Close()
			return nil, err
		}
		runs = append(runs, *run)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	for i := range runs {
		if err := r.db.QueryRowContext(ctx,
			`SELECT COUNT(*), COALESCE(SUM(outcome = 'suggested'), 0) FROM concept_suggestion_items WHERE run_id = ?`, runs[i].ID).
			Scan(&runs[i].ItemCount, &runs[i].SuggestedCount); err != nil {
			return nil, fmt.Errorf("count suggestion items: %w", err)
		}
	}
	return runs, nil
}

// CommitSuggestionRun stores a run and its items atomically under its
// operation ID. It takes the write lock before checking the key, as FLH-029
// receipts do: an existing run with the same request is a replay (true); a
// different request under the key is a conflict. It writes nothing else.
func (r *ConceptSuggestionRepository) CommitSuggestionRun(ctx context.Context, in domain.NewSuggestionRun) (*domain.ConceptSuggestionRun, bool, error) {
	ids, err := json.Marshal(in.RequestUnitIDs)
	if err != nil {
		return nil, false, err
	}
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, false, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	if _, err := tx.ExecContext(ctx, `UPDATE concept_suggestion_runs SET id = id WHERE 0`); err != nil {
		return nil, false, err
	}
	prior, err := r.readRun(ctx, tx, `operation_id = ?`, in.OperationID)
	if err == nil {
		if !domain.SameUnitIDs(prior.RequestUnitIDs, in.RequestUnitIDs) {
			return nil, false, fmt.Errorf("%w: it names a run for different unit_ids", domain.ErrSuggestionKeyConflict)
		}
		return prior, true, nil
	}
	if !errors.Is(err, domain.ErrNotFound) {
		return nil, false, err
	}
	now := r.now()
	ts := now.Format(rfc3339)
	var failure any
	if in.FailureCode != nil {
		failure = string(*in.FailureCode)
	}
	called := 0
	if in.ProviderCalled {
		called = 1
	}
	res, err := tx.ExecContext(ctx,
		`INSERT INTO concept_suggestion_runs
		   (operation_id, request_unit_ids, status, failure_code, generator, candidate_policy, candidate_limit, provider_called, created_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		in.OperationID, string(ids), string(in.Status), failure, in.Generator,
		domain.ConceptSuggestionCandidatePolicy, domain.SuggestionCandidatesPerUnit, called, ts)
	if err != nil {
		return nil, false, fmt.Errorf("insert suggestion run: %w", err)
	}
	runID, err := res.LastInsertId()
	if err != nil {
		return nil, false, err
	}
	for i, item := range in.Items {
		candidates, err := json.Marshal(item.Candidates)
		if err != nil {
			return nil, false, err
		}
		var suggested any
		if item.SuggestedConceptID != nil {
			suggested = *item.SuggestedConceptID
		}
		if _, err := tx.ExecContext(ctx,
			`INSERT INTO concept_suggestion_items
			   (run_id, ordinal, unit_id, entry_id, source_extraction_id, candidates, outcome, suggested_concept_id, reason, created_at)
			 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
			runID, i+1, item.UnitID, item.EntryID, item.SourceExtractionID, string(candidates),
			string(item.Outcome), suggested, item.Reason, ts); err != nil {
			return nil, false, fmt.Errorf("insert suggestion item: %w", err)
		}
	}
	run, err := r.readRun(ctx, tx, `id = ?`, runID)
	if err != nil {
		return nil, false, err
	}
	if err := tx.Commit(); err != nil {
		return nil, false, fmt.Errorf("commit tx: %w", err)
	}
	return run, false, nil
}

// ---- confirmation ----

// ConfirmSuggestion records an explicit human SAME for a suggested item. In
// one transaction it takes the write lock, replays an existing confirmation,
// checks the item names conceptID, revalidates the unit (current extraction,
// no current SAME, not INVALID) and the target (not retired, same identity, no
// DISTINCT since), then appends the human SAME event, updates the membership
// projection and stores the confirmation receipt. It never reassigns an
// already-resolved unit.
func (r *ConceptSuggestionRepository) ConfirmSuggestion(ctx context.Context, itemID, conceptID int64) (*domain.ConceptSuggestionItem, *domain.UnitConceptLink, bool, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, nil, false, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	if _, err := tx.ExecContext(ctx, `UPDATE concept_suggestion_confirmations SET id = id WHERE 0`); err != nil {
		return nil, nil, false, err
	}
	item, generator, err := r.itemForConfirm(ctx, tx, itemID)
	if err != nil {
		return nil, nil, false, err
	}
	if item.Outcome != domain.SuggestionSuggested || item.SuggestedConceptID == nil {
		return nil, nil, false, fmt.Errorf("%w: item %d has no suggested concept to confirm", domain.ErrValidation, itemID)
	}
	if *item.SuggestedConceptID != conceptID {
		return nil, nil, false, fmt.Errorf("%w: item %d suggests concept %d, not %d", domain.ErrValidation, itemID, *item.SuggestedConceptID, conceptID)
	}
	if item.Confirmation != nil {
		link, err := r.concepts.linkByID(ctx, tx, item.Confirmation.LinkID)
		if err != nil {
			return nil, nil, false, err
		}
		if err := deriveItemState(ctx, tx, item); err != nil {
			return nil, nil, false, err
		}
		if err := tx.Commit(); err != nil {
			return nil, nil, false, fmt.Errorf("commit tx: %w", err)
		}
		return item, link, true, nil
	}
	if err := deriveItemState(ctx, tx, item); err != nil {
		return nil, nil, false, err
	}
	if len(item.StaleReasons) > 0 {
		return nil, nil, false, &domain.SuggestionStaleError{Reasons: item.StaleReasons}
	}
	now := r.now()
	link, err := r.concepts.applySame(ctx, tx, item.UnitID, conceptID, domain.SourceHuman, nil,
		domain.SuggestionConfirmationEvidence(*item, generator), now)
	if err != nil {
		return nil, nil, false, err
	}
	res, err := tx.ExecContext(ctx,
		`INSERT INTO concept_suggestion_confirmations (item_id, link_id, created_at) VALUES (?, ?, ?)`,
		item.ID, link.ID, now.Format(rfc3339))
	if err != nil {
		return nil, nil, false, fmt.Errorf("insert confirmation: %w", err)
	}
	confID, err := res.LastInsertId()
	if err != nil {
		return nil, nil, false, err
	}
	item.Confirmation = &domain.SuggestionConfirmation{ID: confID, ItemID: item.ID, LinkID: link.ID, CreatedAt: now}
	if err := deriveItemState(ctx, tx, item); err != nil {
		return nil, nil, false, err
	}
	if err := tx.Commit(); err != nil {
		return nil, nil, false, fmt.Errorf("commit tx: %w", err)
	}
	return item, link, false, nil
}

func (r *ConceptSuggestionRepository) itemForConfirm(ctx context.Context, q txQuerier, itemID int64) (*domain.ConceptSuggestionItem, string, error) {
	row := q.QueryRowContext(ctx,
		`SELECT i.id, i.run_id, i.ordinal, i.unit_id, i.entry_id, i.source_extraction_id, i.candidates, i.outcome,
		        i.suggested_concept_id, i.reason, i.created_at, c.id, c.link_id, c.created_at
		 FROM concept_suggestion_items i
		 LEFT JOIN concept_suggestion_confirmations c ON c.item_id = i.id
		 WHERE i.id = ?`, itemID)
	item, err := scanSuggestionItem(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, "", domain.ErrNotFound
	}
	if err != nil {
		return nil, "", err
	}
	var generator string
	if err := q.QueryRowContext(ctx, `SELECT generator FROM concept_suggestion_runs WHERE id = ?`, item.RunID).Scan(&generator); err != nil {
		return nil, "", fmt.Errorf("read run generator: %w", err)
	}
	return item, generator, nil
}
