package domain

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

// Exam Writing v1. A learner writes a short practical French text for a task
// (an authored prompt or their own), saves it as an immutable draft version,
// may ask once, explicitly, for feedback on one selected version, revises from
// hints and saves a new version. Feedback is always tied to the exact version
// it was asked for and is never carried over to another. The server, not the
// model, decides whether each quoted span is located in that exact text.
// There is no score, grade or CEFR level, and nothing runs in the background.

// WritingFeedbackPromptVersion versions the instruction and output contract.
const WritingFeedbackPromptVersion = "writing_feedback_v1"

// WritingPromptsID is the embedded authored prompt set.
const WritingPromptsID = "flh_writing_prompts_v1"

var (
	ErrWritingDisabled          = errors.New("writing feedback is not enabled")
	ErrWritingPromptConflict    = errors.New("this authored prompt was already started with different content")
	ErrWritingDraftUnchanged    = errors.New("this text is identical to the latest version; nothing was saved")
	ErrWritingTooManyVersions   = errors.New("this task already has the maximum number of versions")
	ErrWritingRequestInProgress = ErrListeningPreparationInProgress
	ErrWritingOutcomeUnknown    = ErrListeningOutcomeUnknown
	ErrWritingOperationConflict = ErrListeningOperationConflict
)

// Bounds. Tasks are short practical texts, not essays.
const (
	MaxWritingVersions         = 20
	MaxWritingPromptRunes      = 1500
	MaxWritingDraftRunes       = 3000
	MaxWritingRequirements     = 8
	MaxWritingWords            = 400
	maxWritingRequirementRunes = 200
	maxWritingCorrections      = 8
	maxWritingQuoteRunes       = 200
	maxWritingCommentRunes     = 600
	maxWritingSuggestionRunes  = 300
)

var (
	writingWordPattern = regexp.MustCompile(`[\p{L}\p{N}]+(?:['’\-][\p{L}\p{N}]+)*`)
	writingRatings     = map[string]bool{"met": true, "partly_met": true, "not_met": true}
	writingCategories  = map[string]bool{"grammar": true, "vocabulary": true, "spelling": true, "register": true, "punctuation": true, "organisation": true}
)

// CountWritingWords applies the displayed convention: a word is a run of
// letters or digits; an apostrophe or hyphen inside it keeps it one word
// (« l'invitation », « peut-être »); numbers count; punctuation does not.
func CountWritingWords(text string) int {
	return len(writingWordPattern.FindAllString(text, -1))
}

// WritingTask is one task. It is never updated.
type WritingTask struct {
	ID           int64
	Title        string
	Prompt       string
	Requirements []string
	WordMin      int
	WordMax      int
	Origin       string // ReadingOriginLearner / ReadingOriginAuthored
	PromptID     string
	CreatedAt    time.Time
}

// WritingDraft is one immutable version of the learner's text.
type WritingDraft struct {
	ID        int64
	TaskID    int64
	Version   int
	Text      string
	WordCount int
	CreatedAt time.Time
}

// Grounding of a quoted span against the exact draft text (server-decided).
const (
	WritingLocated   = "located"   // occurs exactly once; Start is its rune offset
	WritingAmbiguous = "ambiguous" // occurs more than once; no location is attached
	WritingNotFound  = "not_found" // does not occur; never shown as grounded
)

// WritingComment is a short comment in English and Simplified Chinese.
type WritingComment struct {
	CommentEN string `json:"comment_en"`
	CommentZH string `json:"comment_zh"`
}

// WritingTaskFulfilment says whether the draft does what the task asks.
type WritingTaskFulfilment struct {
	Rating    string `json:"rating"` // met | partly_met | not_met (not a score)
	CommentEN string `json:"comment_en"`
	CommentZH string `json:"comment_zh"`
}

// WritingCorrection is one actionable language correction. Grounding and
// Start are set by the server from the exact draft text, never by the model.
type WritingCorrection struct {
	Quote      string `json:"quote"`
	Category   string `json:"category"`
	HintEN     string `json:"hint_en"`
	HintZH     string `json:"hint_zh"`
	Suggestion string `json:"suggestion"`
	ReasonEN   string `json:"reason_en"`
	ReasonZH   string `json:"reason_zh"`
	Grounding  string `json:"grounding,omitempty"`
	Start      *int   `json:"start,omitempty"` // rune offset, located only
}

// WritingFeedbackContent is validated, grounded feedback.
type WritingFeedbackContent struct {
	TaskFulfilment WritingTaskFulfilment `json:"task_fulfilment"`
	Clarity        WritingComment        `json:"clarity"`
	Corrections    []WritingCorrection   `json:"corrections"`
}

// WritingFeedback is one stored report or failed request for one draft version.
type WritingFeedback struct {
	ID          int64
	TaskID      int64
	DraftID     int64
	Status      string
	FailureCode string
	Generator   string
	Content     *WritingFeedbackContent
	CreatedAt   time.Time
}

// WritingFeedbackRequest is one explicit request, recorded before the call.
type WritingFeedbackRequest struct {
	ID           int64
	OperationID  string
	TaskID       int64
	DraftID      int64
	AfterUnknown bool
	StartedAt    time.Time
	DeadlineAt   time.Time
	FinishedAt   *time.Time
	Outcome      string
	FeedbackID   *int64
}

// State is the stored outcome, or in_progress / unknown while unfinished.
func (r WritingFeedbackRequest) State(now time.Time) string {
	return attemptState(r.Outcome, r.DeadlineAt, now)
}

// NewWritingFeedbackRequest asks the repository to record a request.
type NewWritingFeedbackRequest struct {
	OperationID         string
	DraftID             int64
	ConfirmUnknownRetry bool
	Now                 time.Time
	Deadline            time.Time
}

// WritingFeedbackInput is what a generator receives: the task and one draft.
type WritingFeedbackInput struct {
	Title        string
	Prompt       string
	Requirements []string
	WordMin      int
	WordMax      int
	Draft        string
	WordCount    int
}

// WritingFeedbackGenerator asks for feedback. Errors wrap ErrProviderTimeout,
// ErrProviderUnavailable (with ErrOutcomeUnknown when sent but unanswered) or
// ErrValidation, and never carry credentials, provider bodies or learner text.
type WritingFeedbackGenerator interface {
	Name() string
	Generate(ctx context.Context, in WritingFeedbackInput) (WritingFeedbackContent, error)
}

// WritingRepository stores writing records.
type WritingRepository interface {
	CreateTask(ctx context.Context, t WritingTask, now time.Time) (WritingTask, error)
	// StartAuthoredTask creates the task for an authored prompt once; the same
	// prompt returns the existing task (true); different content conflicts.
	StartAuthoredTask(ctx context.Context, t WritingTask, now time.Time) (WritingTask, bool, error)
	GetTask(ctx context.Context, id int64) (WritingTask, error)
	ListTasks(ctx context.Context) ([]WritingTask, error)
	AddDraft(ctx context.Context, taskID int64, text string, words int, now time.Time) (WritingDraft, error)
	GetDraft(ctx context.Context, id int64) (WritingDraft, error)
	ListDrafts(ctx context.Context, taskID int64) ([]WritingDraft, error)
	ListFeedback(ctx context.Context, taskID int64) ([]WritingFeedback, error)
	GetFeedback(ctx context.Context, id int64) (WritingFeedback, error)
	// StartFeedbackRequest records a request for one draft before the call, or
	// refuses with ErrNotFound, ErrWritingRequestInProgress,
	// ErrWritingOutcomeUnknown or ErrWritingOperationConflict.
	StartFeedbackRequest(ctx context.Context, in NewWritingFeedbackRequest) (WritingFeedbackRequest, *WritingDraft, bool, error)
	FinishFeedbackRequest(ctx context.Context, id int64, outcome string, f WritingFeedback, now time.Time) (WritingFeedbackRequest, WritingFeedback, error)
	GetFeedbackRequestByOperation(ctx context.Context, operationID string) (WritingFeedbackRequest, error)
	ListFeedbackRequests(ctx context.Context, taskID int64) ([]WritingFeedbackRequest, error)
}

func werr(format string, a ...any) error {
	return fmt.Errorf("%w: "+format, append([]any{ErrValidation}, a...)...)
}

func boundedText(field, s string, max int) (string, error) {
	s = strings.TrimSpace(s)
	if s == "" {
		return "", werr("%s is required", field)
	}
	if !utf8.ValidString(s) || strings.ContainsFunc(s, func(r rune) bool { return unicode.IsControl(r) && r != '\n' && r != '\t' }) {
		return "", werr("%s contains control characters", field)
	}
	if utf8.RuneCountInString(s) > max {
		return "", werr("%s exceeds %d characters", field, max)
	}
	return s, nil
}

// NormalizeWritingTask validates a task: title, French prompt, up to 8
// content points and a word range (default 60–120 when not given).
func NormalizeWritingTask(t WritingTask) (WritingTask, error) {
	var err error
	if t.Title, err = NormalizeListeningTitle(t.Title); err != nil {
		return t, err
	}
	if t.Prompt, err = boundedText("prompt", t.Prompt, MaxWritingPromptRunes); err != nil {
		return t, err
	}
	if len(t.Requirements) > MaxWritingRequirements {
		return t, werr("at most %d content points", MaxWritingRequirements)
	}
	reqs := make([]string, 0, len(t.Requirements))
	for i, r := range t.Requirements {
		v, err := boundedText(fmt.Sprintf("content point %d", i+1), r, maxWritingRequirementRunes)
		if err != nil {
			return t, err
		}
		reqs = append(reqs, v)
	}
	t.Requirements = reqs
	if t.WordMin == 0 && t.WordMax == 0 {
		t.WordMin, t.WordMax = 60, 120
	}
	if t.WordMin < 1 || t.WordMax < t.WordMin || t.WordMax > MaxWritingWords {
		return t, werr("word range must satisfy 1 <= word_min <= word_max <= %d", MaxWritingWords)
	}
	return t, nil
}

// NormalizeWritingDraft validates draft text. The wording is kept exactly
// (outer whitespace trimmed); only the count is derived.
func NormalizeWritingDraft(text string) (string, int, error) {
	s, err := boundedText("text", strings.ReplaceAll(text, "\r\n", "\n"), MaxWritingDraftRunes)
	if err != nil {
		return "", 0, err
	}
	return s, CountWritingWords(s), nil
}

// ValidateWritingFeedback checks model output against the exact draft text and
// grounds every quoted span: located (exactly once, with its rune offset),
// ambiguous (more than once, no location) or not_found (never grounded). It
// refuses: an unknown rating or category, blank or oversized fields, more than
// eight corrections, an empty quote, or a suggestion identical to its quote.
func ValidateWritingFeedback(draft string, c *WritingFeedbackContent) error {
	tf := &c.TaskFulfilment
	if !writingRatings[tf.Rating] {
		return werr("task_fulfilment.rating %q is not met, partly_met or not_met", tf.Rating)
	}
	var err error
	for _, f := range []struct {
		name string
		s    *string
		max  int
	}{{"task_fulfilment.comment_en", &tf.CommentEN, maxWritingCommentRunes}, {"task_fulfilment.comment_zh", &tf.CommentZH, maxWritingCommentRunes},
		{"clarity.comment_en", &c.Clarity.CommentEN, maxWritingCommentRunes}, {"clarity.comment_zh", &c.Clarity.CommentZH, maxWritingCommentRunes}} {
		if *f.s, err = boundedText(f.name, *f.s, f.max); err != nil {
			return err
		}
	}
	if c.Corrections == nil {
		c.Corrections = []WritingCorrection{}
	}
	if len(c.Corrections) > maxWritingCorrections {
		return werr("at most %d corrections, got %d", maxWritingCorrections, len(c.Corrections))
	}
	for i := range c.Corrections {
		k := &c.Corrections[i]
		field := fmt.Sprintf("correction %d", i+1)
		if !writingCategories[k.Category] {
			return werr("%s has unknown category %q", field, k.Category)
		}
		if strings.TrimSpace(k.Quote) == "" || utf8.RuneCountInString(k.Quote) > maxWritingQuoteRunes {
			return werr("%s quote must be 1 to %d characters", field, maxWritingQuoteRunes)
		}
		for _, f := range []struct {
			name string
			s    *string
			max  int
		}{{"hint_en", &k.HintEN, maxWritingCommentRunes}, {"hint_zh", &k.HintZH, maxWritingCommentRunes},
			{"suggestion", &k.Suggestion, maxWritingSuggestionRunes}, {"reason_en", &k.ReasonEN, maxWritingCommentRunes}, {"reason_zh", &k.ReasonZH, maxWritingCommentRunes}} {
			if *f.s, err = boundedText(field+" "+f.name, *f.s, f.max); err != nil {
				return err
			}
		}
		if k.Suggestion == strings.TrimSpace(k.Quote) {
			return werr("%s suggests the same wording it quotes", field)
		}
		k.Grounding, k.Start = groundQuote(draft, k.Quote)
	}
	return nil
}

// groundQuote locates quote in draft exactly as written. A quote that occurs
// more than once gets no location: picking one would invent it.
func groundQuote(draft, quote string) (string, *int) {
	switch strings.Count(draft, quote) {
	case 0:
		return WritingNotFound, nil
	case 1:
		start := utf8.RuneCountInString(draft[:strings.Index(draft, quote)])
		return WritingLocated, &start
	default:
		return WritingAmbiguous, nil
	}
}

// WritingFailureCode maps a generator error to its stored, non-secret code.
func WritingFailureCode(err error) string { return ListeningFailureCode(err) }

// ---- authored prompts (internal/writing/prompts) ----

// WritingPrompt is one authored practical task, with an example first draft
// (with deliberate mistakes) for demonstration and acceptance.
type WritingPrompt struct {
	ID           string   `json:"id"`
	Format       string   `json:"format"`
	StyleLevel   string   `json:"style_level"`
	Title        string   `json:"title"`
	Prompt       string   `json:"prompt"`
	Requirements []string `json:"requirements"`
	WordMin      int      `json:"word_min"`
	WordMax      int      `json:"word_max"`
	ExampleDraft string   `json:"example_draft"`
}

// WritingPromptSet is the embedded set.
type WritingPromptSet struct {
	SchemaVersion string          `json:"schema_version"`
	Notice        string          `json:"notice"`
	Prompts       []WritingPrompt `json:"prompts"`
}

var writingPromptID = regexp.MustCompile(`^wr-[a-z0-9]+(-[a-z0-9]+)*$`)

// ParseWritingPrompts decodes and validates the authored prompt set.
func ParseWritingPrompts(raw []byte) (WritingPromptSet, error) {
	var s WritingPromptSet
	dec := json.NewDecoder(strings.NewReader(string(raw)))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&s); err != nil {
		return s, werr("writing prompts are not valid JSON")
	}
	if s.SchemaVersion != WritingPromptsID || len(s.Prompts) == 0 {
		return s, werr("writing prompts must be %s with prompts", WritingPromptsID)
	}
	seen := map[string]bool{}
	for i := range s.Prompts {
		p := &s.Prompts[i]
		if !writingPromptID.MatchString(p.ID) || seen[p.ID] {
			return s, werr("prompt id %q is malformed or repeated", p.ID)
		}
		seen[p.ID] = true
		t, err := NormalizeWritingTask(WritingTask{Title: p.Title, Prompt: p.Prompt, Requirements: p.Requirements, WordMin: p.WordMin, WordMax: p.WordMax})
		if err != nil {
			return s, fmt.Errorf("prompt %s: %w", p.ID, err)
		}
		p.Title, p.Prompt, p.Requirements = t.Title, t.Prompt, t.Requirements
		if _, _, err := NormalizeWritingDraft(p.ExampleDraft); err != nil {
			return s, fmt.Errorf("prompt %s example draft: %w", p.ID, err)
		}
	}
	return s, nil
}
