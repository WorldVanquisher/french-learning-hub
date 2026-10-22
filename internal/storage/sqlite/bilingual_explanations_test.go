package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/domain"
	"french-learning-app/migrations"
)

// applyThroughM11 builds a database exactly as a release before FLH-095 left it:
// every migration up to 011 applied and recorded in the ledger.
func applyThroughM11(t *testing.T, path string) *sql.DB {
	t.Helper()
	db, err := sql.Open("sqlite", fmt.Sprintf("file:%s?_pragma=foreign_keys(ON)", path))
	if err != nil {
		t.Fatalf("open raw db: %v", err)
	}
	db.SetMaxOpenConns(1)
	if _, err := db.Exec(`CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))`); err != nil {
		t.Fatalf("ledger: %v", err)
	}
	for _, name := range migrationNames(t) {
		if name >= "012" {
			continue
		}
		b, err := migrations.Files.ReadFile(name)
		if err != nil {
			t.Fatalf("read %s: %v", name, err)
		}
		if _, err := db.Exec(string(b)); err != nil {
			t.Fatalf("exec %s: %v", name, err)
		}
		if _, err := db.Exec(`INSERT INTO schema_migrations (name) VALUES (?)`, name); err != nil {
			t.Fatalf("record %s: %v", name, err)
		}
	}
	return db
}

// TestBilingual_UpgradeKeepsLegacyRowsReadable proves migration 012 is additive:
// rows written before it keep their text, read back with no language recorded,
// and are never backfilled.
func TestBilingual_UpgradeKeepsLegacyRowsReadable(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "legacy.db")
	raw := applyThroughM11(t, path)
	ts := time.Now().UTC().Format(rfc3339)
	mustExec := func(q string, args ...any) int64 {
		t.Helper()
		res, err := raw.Exec(q, args...)
		if err != nil {
			t.Fatalf("%s: %v", q, err)
		}
		id, _ := res.LastInsertId()
		return id
	}
	entry := mustExec(`INSERT INTO learning_entries (original_input, original_context, created_at, updated_at) VALUES (?, ?, ?, ?)`,
		"Je ne mange pas.", "Ancienne question.", ts, ts)
	analysis := mustExec(`INSERT INTO entry_analyses (entry_id, version, category, explanation, confidence, uncertainty, analyzer, created_at)
		VALUES (?, 1, 'grammar', 'Legacy explanation.', 0.8, '', 'openai:old:fr_l2_taxonomy_v1', ?)`, entry, ts)
	feedback := mustExec(`INSERT INTO analysis_feedback (analysis_id, status, corrected_explanation, user_note, created_at)
		VALUES (?, 'corrected', 'Legacy correction.', '', ?)`, analysis, ts)
	extraction := mustExec(`INSERT INTO knowledge_extractions (entry_id, version, source_analysis_id, source_feedback_id, extractor, created_at)
		VALUES (?, 1, ?, ?, 'openai:old:knowledge_extraction_v1', ?)`, entry, analysis, feedback, ts)
	unit := mustExec(`INSERT INTO knowledge_units (extraction_id, ordinal, kind, canonical, statement, example, confidence, created_at)
		VALUES (?, 1, 'grammar', 'ne … pas', 'Legacy statement.', 'Je ne mange pas.', 0.9, ?)`, extraction, ts)
	mustExec(`INSERT INTO knowledge_admission_recommendations (unit_id, ruleset, state, reason, created_at)
		VALUES (?, 'knowledge_admission_v1', 'active', 'default_active', ?)`, unit, ts)
	raw.Close()

	db, err := Open(path) // applies 012
	if err != nil {
		t.Fatalf("open (apply 012): %v", err)
	}
	defer db.Close()

	analyses, err := NewAnalysisRepository(db).ListByEntry(ctx, entry)
	if err != nil || len(analyses) != 1 {
		t.Fatalf("list analyses: %v %v", analyses, err)
	}
	a := analyses[0]
	if a.Explanation != "Legacy explanation." || a.Explanations.Recorded() {
		t.Fatalf("legacy analysis = %q %+v, want its text and no recorded language", a.Explanation, a.Explanations)
	}
	latest, err := NewFeedbackRepository(db).GetLatestByAnalysis(ctx, analysis)
	if err != nil || *latest.CorrectedExplanation != "Legacy correction." || latest.CorrectedExplanations.Recorded() || latest.ReviewedLanguages != nil {
		t.Fatalf("legacy feedback = %+v, %v", latest, err)
	}
	eff := domain.ResolveEffective(a, latest)
	if eff.Effective.Explanation != "Legacy correction." || eff.Explanations.EN.Basis != domain.BasisUnavailable {
		t.Fatalf("legacy effective = %+v / %+v", eff.Effective, eff.Explanations)
	}
	views, err := NewKnowledgeRepository(db).ListByEntry(ctx, entry)
	if err != nil || len(views) != 1 || len(views[0].Units) != 1 {
		t.Fatalf("list extractions: %v %v", views, err)
	}
	u := views[0].Units[0].Unit
	if u.Statement != "Legacy statement." || u.Statements.Recorded() || *u.Example != "Je ne mange pas." {
		t.Fatalf("legacy unit = %+v", u)
	}
	var nonNull int
	if err := db.QueryRow(`SELECT
		(SELECT COUNT(*) FROM entry_analyses WHERE explanation_en IS NOT NULL OR explanation_zh IS NOT NULL) +
		(SELECT COUNT(*) FROM knowledge_units WHERE statement_en IS NOT NULL OR statement_zh IS NOT NULL) +
		(SELECT COUNT(*) FROM analysis_feedback WHERE reviewed_explanation_languages IS NOT NULL)`).Scan(&nonNull); err != nil || nonNull != 0 {
		t.Fatalf("migration backfilled %d values (%v)", nonNull, err)
	}
}

func TestBilingual_RoundTripAndReviewedLanguageCheck(t *testing.T) {
	ctx := context.Background()
	db, err := Open(filepath.Join(t.TempDir(), "bi.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	entries, analyses, feedback := NewEntryRepository(db), NewAnalysisRepository(db), NewFeedbackRepository(db)
	e, err := entries.Create(ctx, domain.NewEntryInput{OriginalInput: "Je ne fume plus.", OriginalContext: ""})
	if err != nil {
		t.Fatal(err)
	}
	en, zh := "Ne … plus marks a stopped habit.", "「ne … plus」表示习惯已停止。"
	bi, err := analyses.Create(ctx, e.ID, domain.AnalysisResult{Category: "grammar", Explanation: en,
		Explanations: domain.ExplanationVariants{EN: &en, ZH: &zh}, Confidence: 0.8}, "openai:m:fr_l2_taxonomy_v1.explanation_en_zh_v1")
	if err != nil {
		t.Fatal(err)
	}
	got, err := analyses.GetByID(ctx, bi.ID)
	if err != nil || *got.Explanations.EN != en || *got.Explanations.ZH != zh || got.Explanation != en {
		t.Fatalf("round trip = %+v, %v", got, err)
	}

	// An English-only analysis cannot record a reviewed Chinese explanation.
	enOnly, err := analyses.Create(ctx, e.ID, domain.AnalysisResult{Category: "grammar", Explanation: en,
		Explanations: domain.ExplanationVariants{EN: &en}, Confidence: 0.5}, "rule-based:v2:fr_l2_taxonomy_v1")
	if err != nil {
		t.Fatal(err)
	}
	in := domain.NewFeedbackInput{Status: domain.FeedbackAccepted, ReviewedLanguages: []domain.ExplanationLanguage{domain.LanguageEnglish, domain.LanguageChinese}}
	if _, err := feedback.Create(ctx, enOnly.ID, in); !errors.Is(err, domain.ErrValidation) || !strings.Contains(err.Error(), "zh") {
		t.Fatalf("reviewed zh on an English-only analysis: %v", err)
	}
	var n int
	if err := db.QueryRow(`SELECT COUNT(*) FROM analysis_feedback`).Scan(&n); err != nil || n != 0 {
		t.Fatalf("refused feedback was stored (%d, %v)", n, err)
	}

	// A Chinese-only correction on the bilingual analysis round-trips, and the
	// inventory's language-independent effective explanation is that correction.
	czh := "人工更正：「ne … plus」表示停止。"
	fb, err := feedback.Create(ctx, bi.ID, domain.NewFeedbackInput{Status: domain.FeedbackCorrected,
		CorrectedExplanations: domain.ExplanationVariants{ZH: &czh},
		ReviewedLanguages:     []domain.ExplanationLanguage{domain.LanguageEnglish, domain.LanguageChinese}})
	if err != nil {
		t.Fatal(err)
	}
	latest, err := feedback.GetLatestByAnalysis(ctx, bi.ID)
	if err != nil || latest.ID != fb.ID || *latest.CorrectedExplanations.ZH != czh || latest.CorrectedExplanations.EN != nil ||
		len(latest.ReviewedLanguages) != 2 {
		t.Fatalf("feedback round trip = %+v, %v", latest, err)
	}
	// enOnly (version 2) is the latest analysis for the inventory; check the
	// projection through the bilingual one directly instead.
	eff := domain.ResolveEffective(got, latest)
	if eff.Effective.Explanation != czh || eff.Explanations.EN.Basis != domain.BasisOutdated {
		t.Fatalf("effective = %+v %+v", eff.Effective, eff.Explanations)
	}
	e2, _ := entries.Create(ctx, domain.NewEntryInput{OriginalInput: "Il ne ment jamais."})
	b2, _ := analyses.Create(ctx, e2.ID, domain.AnalysisResult{Category: "grammar", Explanation: en,
		Explanations: domain.ExplanationVariants{EN: &en, ZH: &zh}, Confidence: 0.8}, "openai:m:x")
	if _, err := feedback.Create(ctx, b2.ID, domain.NewFeedbackInput{Status: domain.FeedbackCorrected,
		CorrectedExplanations: domain.ExplanationVariants{ZH: &czh}}); err != nil {
		t.Fatal(err)
	}
	recs, err := NewInventoryRepository(db).ListLearningRecords(ctx, domain.LearningRecordQuery{Limit: 10})
	if err != nil {
		t.Fatal(err)
	}
	for _, r := range recs {
		if r.EntryID == e2.ID && (r.Effective == nil || r.Effective.Explanation != czh) {
			t.Fatalf("inventory effective explanation = %+v, want the Chinese correction", r.Effective)
		}
	}
}

// TestBilingual_PerLanguageCorrectionNeedsRecordedLanguages proves the feedback
// transaction refuses corrected_explanation_en/_zh on an analysis without
// recorded language variants, stores nothing, and keeps both the legacy
// corrected_explanation and per-language corrections on language-recorded
// analyses (including a Chinese correction of an English-only analysis).
func TestBilingual_PerLanguageCorrectionNeedsRecordedLanguages(t *testing.T) {
	ctx := context.Background()
	db, err := Open(filepath.Join(t.TempDir(), "guard.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	entries, analyses, feedback := NewEntryRepository(db), NewAnalysisRepository(db), NewFeedbackRepository(db)
	e, err := entries.Create(ctx, domain.NewEntryInput{OriginalInput: "Je parle japonais."})
	if err != nil {
		t.Fatal(err)
	}
	legacy, err := analyses.Create(ctx, e.ID, domain.AnalysisResult{Category: "grammar",
		Explanation: "Pas d'article après parler.", Confidence: 0.9}, "imported:chatgpt-web:learning_capture_v1")
	if err != nil {
		t.Fatal(err)
	}
	en, zh := "No article after parler.", "parler 后不加冠词。"
	count := func() int {
		var n int
		if err := db.QueryRow(`SELECT COUNT(*) FROM analysis_feedback`).Scan(&n); err != nil {
			t.Fatal(err)
		}
		return n
	}
	for _, v := range []domain.ExplanationVariants{{EN: &en}, {ZH: &zh}, {EN: &en, ZH: &zh}} {
		_, err := feedback.Create(ctx, legacy.ID, domain.NewFeedbackInput{Status: domain.FeedbackCorrected, CorrectedExplanations: v})
		if !errors.Is(err, domain.ErrValidation) || !strings.Contains(err.Error(), "recorded explanation languages") {
			t.Fatalf("per-language correction %+v on a legacy analysis: %v", v, err)
		}
	}
	if n := count(); n != 0 {
		t.Fatalf("refused feedback was stored (%d rows)", n)
	}

	unspecified := "Parler une langue : pas d'article."
	if _, err := feedback.Create(ctx, legacy.ID, domain.NewFeedbackInput{Status: domain.FeedbackCorrected,
		CorrectedExplanation: &unspecified}); err != nil {
		t.Fatalf("legacy corrected_explanation: %v", err)
	}

	// An English-only (rule-based) analysis has a recorded language, so a
	// Chinese correction is permitted.
	enOnly, err := analyses.Create(ctx, e.ID, domain.AnalysisResult{Category: "grammar", Explanation: en,
		Explanations: domain.ExplanationVariants{EN: &en}, Confidence: 0.5}, "rule-based:v2:fr_l2_taxonomy_v1")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := feedback.Create(ctx, enOnly.ID, domain.NewFeedbackInput{Status: domain.FeedbackCorrected,
		CorrectedExplanations: domain.ExplanationVariants{ZH: &zh}}); err != nil {
		t.Fatalf("zh correction on an English-recorded analysis: %v", err)
	}
	if n := count(); n != 2 {
		t.Fatalf("feedback rows = %d, want 2", n)
	}
}
