package domain

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

// Mistake Notebook v1. A notebook item is an ordinary learning record (a
// learning_capture_v1 capture) that was saved from a skill exercise with a
// structured source reference: the exact stored item it came from. The
// reference is validated against stored data and written in the same
// transaction as the record; it is never inferred from prose, never added to
// an old record, and never rewritten. Marking an item for retry is the
// learner's explicit, append-only decision; it is not a Concept judgment, a
// score or a schedule.

// Source types: one stored item of one skill's records.
const (
	SourceListeningItem       = "listening_item"       // listening_exercises.content.items[n]
	SourceReadingItem         = "reading_item"         // reading_exercises.content.items[n]
	SourceWritingCorrection   = "writing_correction"   // writing_feedback.content.corrections[n]
	SourceSpeakingImprovement = "speaking_improvement" // speaking_feedback.content.improvements[n]
)

// Skills, as shown and filtered in the notebook.
const (
	SkillListening = "listening"
	SkillReading   = "reading"
	SkillWriting   = "writing"
	SkillSpeaking  = "speaking"
)

var sourceSkills = map[string]string{
	SourceListeningItem:       SkillListening,
	SourceReadingItem:         SkillReading,
	SourceWritingCorrection:   SkillWriting,
	SourceSpeakingImprovement: SkillSpeaking,
}

// SourceSkill is the skill a source type belongs to ("" when unknown).
func SourceSkill(sourceType string) string { return sourceSkills[sourceType] }

// ValidSkill reports whether s is one of the four skills.
func ValidSkill(s string) bool {
	return s == SkillListening || s == SkillReading || s == SkillWriting || s == SkillSpeaking
}

const (
	maxSourceItem         = 50
	maxSourceAttemptRunes = 1000
)

// ErrSourceAlreadySaved is wrapped by SourceAlreadySavedError.
var ErrSourceAlreadySaved = errors.New("this item is already saved as a learning record")

// SourceAlreadySavedError reports the record a source item was already saved as.
type SourceAlreadySavedError struct{ EntryID int64 }

func (e *SourceAlreadySavedError) Error() string {
	return fmt.Sprintf("%s (record #%d)", ErrSourceAlreadySaved.Error(), e.EntryID)
}
func (e *SourceAlreadySavedError) Unwrap() error { return ErrSourceAlreadySaved }

// CaptureSourceRef is the optional source_ref of a learning_capture_v1
// capture: the exact stored item a record was saved from. Attempt is the
// learner's own answer, only when they chose to include it (listening and
// reading); writing and speaking quote the learner's own words from the stored
// version instead.
type CaptureSourceRef struct {
	Type     string
	RecordID int64
	Item     int
	Attempt  string
}

// Validate checks the reference's shape (not that the item exists: that is the
// application's SourceResolver). It trims the attempt in place.
func (r *CaptureSourceRef) Validate() error {
	if _, ok := sourceSkills[r.Type]; !ok {
		return errWrap("source_ref.type must be listening_item, reading_item, writing_correction or speaking_improvement")
	}
	if r.RecordID < 1 {
		return errWrap("source_ref.record_id must be a positive id")
	}
	if r.Item < 1 || r.Item > maxSourceItem {
		return errWrap(fmt.Sprintf("source_ref.item must be between 1 and %d", maxSourceItem))
	}
	r.Attempt = strings.TrimSpace(strings.ReplaceAll(r.Attempt, "\r\n", "\n"))
	if r.Attempt == "" {
		return nil
	}
	if r.Type == SourceWritingCorrection || r.Type == SourceSpeakingImprovement {
		return errWrap("source_ref.attempt is only for listening and reading items (writing and speaking quote your own words from the version)")
	}
	if !utf8.ValidString(r.Attempt) || strings.ContainsFunc(r.Attempt, func(c rune) bool { return unicode.IsControl(c) && c != '\n' && c != '\t' }) {
		return errWrap("source_ref.attempt contains control characters")
	}
	if utf8.RuneCountInString(r.Attempt) > maxSourceAttemptRunes {
		return errWrap(fmt.Sprintf("source_ref.attempt exceeds %d characters", maxSourceAttemptRunes))
	}
	return nil
}

// LearningCaptureSource is one stored source row.
type LearningCaptureSource struct {
	CaptureRowID int64
	EntryID      int64
	CaptureID    string
	Ref          CaptureSourceRef
	CreatedAt    time.Time
}

// SourceLink names the exact stored records behind a source item, so the
// workbench can open that item, draft version or transcript version.
type SourceLink struct {
	ListeningMaterialID        int64 `json:"listening_material_id,omitempty"`
	ListeningExerciseID        int64 `json:"listening_exercise_id,omitempty"`
	ListeningTranscriptVersion int   `json:"listening_transcript_version,omitempty"`
	ReadingLessonID            int64 `json:"reading_lesson_id,omitempty"`
	ReadingPassageVersion      int   `json:"reading_passage_version,omitempty"`
	ReadingExerciseID          int64 `json:"reading_exercise_id,omitempty"`
	WritingTaskID              int64 `json:"writing_task_id,omitempty"`
	WritingDraftID             int64 `json:"writing_draft_id,omitempty"`
	WritingDraftVersion        int   `json:"writing_draft_version,omitempty"`
	WritingFeedbackID          int64 `json:"writing_feedback_id,omitempty"`
	SpeakingExerciseID         int64 `json:"speaking_exercise_id,omitempty"`
	SpeakingTakeID             int64 `json:"speaking_take_id,omitempty"`
	SpeakingTakeNumber         int   `json:"speaking_take_number,omitempty"`
	SpeakingTranscriptID       int64 `json:"speaking_transcript_id,omitempty"`
	SpeakingTranscriptVersion  int   `json:"speaking_transcript_version,omitempty"`
	SpeakingFeedbackID         int64 `json:"speaking_feedback_id,omitempty"`
}

// ResolvedSource is what the stored item says, read from its own records:
// never from the learner's prose.
type ResolvedSource struct {
	Skill    string
	Title    string // the lesson, material, task or exercise
	Prompt   string // the question, or the task prompt / situation
	Category string // item kind (listening/reading) or correction category
	// Quote is the learner's own words in that exact version (writing and
	// speaking only).
	Quote         string
	Reference     string // expected / reference answer, or the suggested wording
	ExplanationEN string
	ExplanationZH string
	HintEN        string // writing and speaking only
	HintZH        string
	Link          SourceLink
	// Origin says who wrote Reference (ReferenceAuthored or ReferenceGenerated),
	// from the stored Generator provenance: the learner sees which answers a
	// person reviewed and which are model suggestions nobody reviewed.
	Origin    string
	Generator string
	// LatestVersion is the source's newest version when it is newer than the
	// version the item came from (reading passages, listening transcripts),
	// else 0. The item itself is always read from its own version.
	LatestVersion int
}

// Who wrote an item's reference.
const (
	ReferenceAuthored  = "authored"  // an authored, reviewed pack (provenance "authored:<pack>")
	ReferenceGenerated = "generated" // model output that no person reviewed
)

// ReferenceOrigin classifies a stored generator provenance.
func ReferenceOrigin(generator string) string {
	if strings.HasPrefix(generator, "authored:") {
		return ReferenceAuthored
	}
	return ReferenceGenerated
}

// The state of a notebook item's stored source when it is read back.
const (
	SourceResolved = "resolved"
	// SourceMissing: a record the reference names can no longer be read (for
	// example after restoring a partial backup). The learner's record is intact.
	SourceMissing = "missing"
	// SourceUnusable: the record exists but no longer yields that item.
	SourceUnusable = "unusable"
)

// SourceResolver reads a source reference's item from the stored records. It
// returns ErrNotFound when the record is missing, and ErrValidation when it is
// not completed content or the item is out of range.
type SourceResolver interface {
	ResolveSource(ctx context.Context, ref CaptureSourceRef) (ResolvedSource, error)
}

// RetryMark is the current retry decision for one notebook record.
type RetryMark struct {
	EntryID int64
	Marked  bool
	At      time.Time
}

// NotebookRepository stores and reads notebook state.
type NotebookRepository interface {
	ListSources(ctx context.Context) ([]LearningCaptureSource, error) // newest first
	GetSourceByEntry(ctx context.Context, entryID int64) (LearningCaptureSource, error)
	CurrentMarks(ctx context.Context) (map[int64]RetryMark, error)
	// SetMark appends a decision for a notebook record only when it changes the
	// current state; it returns the current mark and whether a row was added.
	SetMark(ctx context.Context, entryID int64, marked bool, now time.Time) (RetryMark, bool, error)
}

// ---- Grammar and Vocabulary views over the knowledge model ----

// ConceptKindViewVersion versions the classification rule below.
const ConceptKindViewVersion = "concept_kind_view_v1"

// Classes of the Grammar / Vocabulary views.
const (
	KindViewGrammar      = "grammar"
	KindViewVocabulary   = "vocabulary"
	KindViewUnclassified = "unclassified"
)

// Reasons a Concept stays unclassified.
const (
	UnclassifiedNoSupport  = "no_supporting_unit"
	UnclassifiedMixedKinds = "mixed_kinds"
	UnclassifiedOtherKind  = "other_kind"
)

// ClassifyConceptKinds applies concept_kind_view_v1 to the fr_l2_knowledge_v1
// kinds of a Concept's current supporting units: all grammar → grammar; all
// vocabulary → vocabulary; anything else stays unclassified with its reason
// (no supporting unit, mixed kinds, or another kind such as morphology,
// expression or usage, which the taxonomy keeps distinct). It never guesses.
func ClassifyConceptKinds(kinds []KnowledgeKind) (string, string) {
	if len(kinds) == 0 {
		return KindViewUnclassified, UnclassifiedNoSupport
	}
	first := kinds[0]
	for _, k := range kinds[1:] {
		if k != first {
			return KindViewUnclassified, UnclassifiedMixedKinds
		}
	}
	switch first {
	case KindGrammar:
		return KindViewGrammar, ""
	case KindVocabulary:
		return KindViewVocabulary, ""
	default:
		return KindViewUnclassified, UnclassifiedOtherKind
	}
}
