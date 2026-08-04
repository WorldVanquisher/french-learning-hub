package sqlite

import (
	"context"
	"database/sql"
	"fmt"
	"strings"
	"time"

	"french-learning-app/internal/domain"
)

// InventoryRepository is a SQLite-backed domain.InventoryRepository. It provides
// the read-only cross-entry learning inventory: one row per learning entry,
// combining the latest analysis and its latest feedback. It never writes.
type InventoryRepository struct {
	db *sql.DB
}

// compile-time check.
var _ domain.InventoryRepository = (*InventoryRepository)(nil)

// NewInventoryRepository builds a repository over an open database.
func NewInventoryRepository(db *sql.DB) *InventoryRepository {
	return &InventoryRepository{db: db}
}

// projectionCTE builds, per learning entry, the latest analysis (by version
// DESC, id DESC) and that analysis's latest feedback (by created_at DESC, id
// DESC), using window functions so only one row per entry survives — no N+1
// query loop. It also derives, in SQL, the inventory `state` and the
// `effective_category`, so filtering and pagination happen in the database and a
// LIMITed page is never short after in-memory filtering.
//
// effective_category mirrors domain.ResolveEffective: NULL when there is no
// analysis or the latest feedback rejected it; the corrected category (falling
// back to the analysis category) when corrected; otherwise the analysis
// category. The actual returned values are still resolved in Go via
// domain.ResolveEffective so the rules live in exactly one place; these SQL
// expressions exist only for correct server-side filtering and aggregation.
const projectionCTE = `
WITH la AS (
    SELECT id, entry_id, version, category, explanation, confidence, uncertainty, analyzer, created_at
    FROM (
        SELECT id, entry_id, version, category, explanation, confidence, uncertainty, analyzer, created_at,
               ROW_NUMBER() OVER (PARTITION BY entry_id ORDER BY version DESC, id DESC) AS rn
        FROM entry_analyses
    )
    WHERE rn = 1
),
lf AS (
    SELECT id, analysis_id, status, corrected_category, corrected_explanation, created_at
    FROM (
        SELECT id, analysis_id, status, corrected_category, corrected_explanation, created_at,
               ROW_NUMBER() OVER (PARTITION BY analysis_id ORDER BY created_at DESC, id DESC) AS rn
        FROM analysis_feedback
    )
    WHERE rn = 1
),
proj AS (
    SELECT
        e.id                  AS entry_id,
        e.original_input      AS original_input,
        e.original_context    AS original_context,
        e.created_at          AS entry_created_at,

        la.id                 AS analysis_id,
        la.version            AS analysis_version,
        la.category           AS analysis_category,
        la.explanation        AS analysis_explanation,
        la.confidence         AS analysis_confidence,
        la.uncertainty        AS analysis_uncertainty,
        la.analyzer           AS analyzer,
        la.created_at         AS analysis_created_at,

        lf.id                 AS feedback_id,
        lf.status             AS feedback_status,
        lf.corrected_category AS corrected_category,
        lf.corrected_explanation AS corrected_explanation,
        lf.created_at         AS feedback_created_at,

        CASE
            WHEN la.id IS NULL THEN 'unanalyzed'
            WHEN lf.id IS NULL THEN 'unreviewed'
            ELSE lf.status
        END AS state,

        CASE
            WHEN la.id IS NULL THEN NULL
            WHEN lf.status = 'rejected' THEN NULL
            WHEN lf.status = 'corrected' THEN COALESCE(lf.corrected_category, la.category)
            ELSE la.category
        END AS effective_category
    FROM learning_entries e
    LEFT JOIN la ON la.entry_id = e.id
    LEFT JOIN lf ON lf.analysis_id = la.id
)`

// ListLearningRecords returns one record per learning entry matching q, ordered
// by entry id descending. Filters (state, effective category, analyzer, cursor)
// are applied in SQL so a limited page is accurate.
func (r *InventoryRepository) ListLearningRecords(ctx context.Context, q domain.LearningRecordQuery) ([]*domain.LearningRecord, error) {
	where, args := buildFilters(q)

	query := projectionCTE + `
SELECT entry_id, original_input, original_context, entry_created_at,
       analysis_id, analysis_version, analysis_category, analysis_explanation,
       analysis_confidence, analysis_uncertainty, analyzer, analysis_created_at,
       feedback_id, feedback_status, corrected_category, corrected_explanation, feedback_created_at
FROM proj
` + where + `
ORDER BY entry_id DESC
LIMIT ?`
	args = append(args, q.Limit)

	rows, err := r.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("list learning records: %w", err)
	}
	defer rows.Close()

	var out []*domain.LearningRecord
	for rows.Next() {
		rec, err := scanLearningRecord(rows)
		if err != nil {
			return nil, fmt.Errorf("scan learning record: %w", err)
		}
		out = append(out, rec)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate learning records: %w", err)
	}
	return out, nil
}

// buildFilters turns the (already normalized) query into a WHERE clause and
// positional args. Category filtering uses effective_category, so rejected and
// unanalyzed rows (NULL effective_category) never match a category filter.
// Analyzer matching is exact.
func buildFilters(q domain.LearningRecordQuery) (string, []any) {
	var conds []string
	var args []any

	if q.State != nil {
		conds = append(conds, "state = ?")
		args = append(args, string(*q.State))
	}
	if q.Category != nil {
		conds = append(conds, "effective_category = ?")
		args = append(args, *q.Category)
	}
	if q.Analyzer != nil {
		conds = append(conds, "analyzer = ?")
		args = append(args, *q.Analyzer)
	}
	if q.BeforeEntryID != nil {
		conds = append(conds, "entry_id < ?")
		args = append(args, *q.BeforeEntryID)
	}

	if len(conds) == 0 {
		return "", args
	}
	return "WHERE " + strings.Join(conds, " AND "), args
}

// scanLearningRecord reads one projection row and resolves the effective view by
// reconstructing the analysis/feedback and calling domain.ResolveEffective, so
// the resolution rules are not duplicated here.
func scanLearningRecord(s scanner) (*domain.LearningRecord, error) {
	var (
		entryID          int64
		originalInput    string
		originalContext  string
		entryCreatedStr  string
		analysisID       sql.NullInt64
		analysisVersion  sql.NullInt64
		analysisCategory sql.NullString
		analysisExpl     sql.NullString
		analysisConf     sql.NullFloat64
		analysisUncert   sql.NullString
		analyzer         sql.NullString
		analysisCreated  sql.NullString
		feedbackID       sql.NullInt64
		feedbackStatus   sql.NullString
		correctedCat     sql.NullString
		correctedExpl    sql.NullString
		feedbackCreated  sql.NullString
	)
	if err := s.Scan(
		&entryID, &originalInput, &originalContext, &entryCreatedStr,
		&analysisID, &analysisVersion, &analysisCategory, &analysisExpl,
		&analysisConf, &analysisUncert, &analyzer, &analysisCreated,
		&feedbackID, &feedbackStatus, &correctedCat, &correctedExpl, &feedbackCreated,
	); err != nil {
		return nil, err
	}

	entryCreatedAt, err := time.Parse(rfc3339, entryCreatedStr)
	if err != nil {
		return nil, fmt.Errorf("parse entry created_at: %w", err)
	}

	rec := &domain.LearningRecord{
		EntryID:         entryID,
		OriginalInput:   originalInput,
		OriginalContext: originalContext,
		EntryCreatedAt:  entryCreatedAt,
	}

	// No analysis: the entry is unanalyzed; all analysis/effective fields stay nil.
	if !analysisID.Valid {
		rec.State = domain.LearningRecordUnanalyzed
		return rec, nil
	}

	analysisCreatedAt, err := time.Parse(rfc3339, analysisCreated.String)
	if err != nil {
		return nil, fmt.Errorf("parse analysis created_at: %w", err)
	}

	analysis := &domain.Analysis{
		ID:          analysisID.Int64,
		EntryID:     entryID,
		Version:     analysisVersion.Int64,
		Category:    analysisCategory.String,
		Explanation: analysisExpl.String,
		Confidence:  analysisConf.Float64,
		Uncertainty: analysisUncert.String,
		Analyzer:    analyzer.String,
		CreatedAt:   analysisCreatedAt,
	}

	// Reconstruct the latest feedback (if any) so ResolveEffective owns the rules.
	var latest *domain.Feedback
	if feedbackID.Valid {
		fbCreatedAt, err := time.Parse(rfc3339, feedbackCreated.String)
		if err != nil {
			return nil, fmt.Errorf("parse feedback created_at: %w", err)
		}
		latest = &domain.Feedback{
			ID:         feedbackID.Int64,
			AnalysisID: analysisID.Int64,
			Status:     domain.FeedbackStatus(feedbackStatus.String),
			CreatedAt:  fbCreatedAt,
		}
		if correctedCat.Valid {
			latest.CorrectedCategory = &correctedCat.String
		}
		if correctedExpl.Valid {
			latest.CorrectedExplanation = &correctedExpl.String
		}
	}

	eff := domain.ResolveEffective(analysis, latest)

	// Populate analysis metadata pointers.
	id := analysis.ID
	version := analysis.Version
	prov := analysis.Analyzer
	conf := analysis.Confidence
	uncert := analysis.Uncertainty
	created := analysis.CreatedAt
	rec.AnalysisID = &id
	rec.AnalysisVersion = &version
	rec.Analyzer = &prov
	rec.Confidence = &conf
	rec.Uncertainty = &uncert
	rec.AnalysisCreatedAt = &created

	rec.State = domain.StateFromResolution(eff.Resolution)
	rec.Original = &domain.AnalysisValues{Category: eff.Original.Category, Explanation: eff.Original.Explanation}
	if eff.Effective != nil {
		rec.Effective = &domain.AnalysisValues{Category: eff.Effective.Category, Explanation: eff.Effective.Explanation}
	}
	rec.FeedbackID = eff.FeedbackID

	return rec, nil
}

// SummarizeLearningRecords returns aggregate counts across all entries using
// dedicated aggregate SQL over the same projection, without loading every row.
func (r *InventoryRepository) SummarizeLearningRecords(ctx context.Context) (*domain.LearningInventorySummary, error) {
	summary := &domain.LearningInventorySummary{
		ByState:             make(map[domain.LearningRecordState]int64),
		ByEffectiveCategory: make(map[domain.Category]int64),
		ByAnalyzer:          make(map[string]int64),
	}
	// Every state key present, even at zero, for a stable response shape.
	for _, st := range domain.LearningRecordStates() {
		summary.ByState[st] = 0
	}

	// Counts by state.
	if err := r.aggregate(ctx, `SELECT state, COUNT(*) FROM proj GROUP BY state`,
		func(key string, n int64) {
			summary.ByState[domain.LearningRecordState(key)] = n
			summary.TotalEntries += n
			if domain.LearningRecordState(key) == domain.LearningRecordUnanalyzed {
				summary.UnanalyzedEntries += n
			} else {
				summary.AnalyzedEntries += n
			}
		}); err != nil {
		return nil, fmt.Errorf("summary by state: %w", err)
	}

	// Counts by effective category (excludes rejected/unanalyzed via NULL).
	if err := r.aggregate(ctx, `SELECT effective_category, COUNT(*) FROM proj WHERE effective_category IS NOT NULL GROUP BY effective_category`,
		func(key string, n int64) {
			summary.ByEffectiveCategory[key] = n
		}); err != nil {
		return nil, fmt.Errorf("summary by category: %w", err)
	}

	// Counts by analyzer of the latest analysis (excludes unanalyzed via NULL).
	if err := r.aggregate(ctx, `SELECT analyzer, COUNT(*) FROM proj WHERE analyzer IS NOT NULL GROUP BY analyzer`,
		func(key string, n int64) {
			summary.ByAnalyzer[key] = n
		}); err != nil {
		return nil, fmt.Errorf("summary by analyzer: %w", err)
	}

	return summary, nil
}

// aggregate runs a `SELECT key, COUNT(*)` query over the projection and invokes
// fn for each (key, count) row.
func (r *InventoryRepository) aggregate(ctx context.Context, tail string, fn func(key string, n int64)) error {
	rows, err := r.db.QueryContext(ctx, projectionCTE+"\n"+tail)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var key string
		var n int64
		if err := rows.Scan(&key, &n); err != nil {
			return err
		}
		fn(key, n)
	}
	return rows.Err()
}
