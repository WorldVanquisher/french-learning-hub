package domain

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

// Exam Reading v1. A learner saves a French passage (an article they found, or
// an authored, reviewed example from the reading pack) and practises it with
// exam-style questions: main idea, precise detail, and an inference only where
// the text supports one. Passages are versions of paragraphs with stable IDs
// (p1..pN) and are never rewritten. An exercise is stored against one exact
// passage version; every item cites paragraph IDs and verbatim excerpts that
// occur exactly once in their paragraph, so the workbench can highlight them
// without guessing. The server never fetches the optional source link.

// ReadingExercisePromptVersion versions the generator instruction and output.
const ReadingExercisePromptVersion = "reading_exercise_v1"

// ReadingPackID is the authored pack embedded as the documented example.
const ReadingPackID = "flh_reading_pack_v1"

// ReadingAuthoredGenerator is the provenance of an imported, reviewed exercise.
const ReadingAuthoredGenerator = "authored:" + ReadingPackID

// Reading errors. The preparation-state errors are the Daily Listening ones,
// so both features answer the same way.
var (
	ErrReadingDisabled              = errors.New("reading exercise generation is not enabled")
	ErrReadingPackConflict          = errors.New("this authored passage was already imported with different content")
	ErrReadingPreparationInProgress = ErrListeningPreparationInProgress
	ErrReadingOutcomeUnknown        = ErrListeningOutcomeUnknown
	ErrReadingOperationConflict     = ErrListeningOperationConflict
)

// Bounds. A passage is a short exam-style text, not a book chapter.
const (
	MaxReadingTitleRunes     = MaxListeningTitleRunes
	MaxReadingTextRunes      = 6000
	MaxReadingParagraphs     = 30
	MaxReadingParagraphRunes = 1500
	MaxReadingURLBytes       = 2048
	minReadingItems          = 2
	maxReadingItems          = 5
	maxReadingEvidence       = 3
	maxReadingExcerptRunes   = 300
	maxReadingAlternatives   = 4
	maxReadingWrongAnswers   = 4
	maxReadingQuestionRunes  = 300
	maxReadingAnswerRunes    = 400
	maxReadingExplainRunes   = 600
)

// ReadingSegment is one paragraph with its stable ID.
type ReadingSegment struct {
	ID   string `json:"id"`
	Text string `json:"text"`
}

// Reading lesson origins.
const (
	ReadingOriginLearner  = "learner"
	ReadingOriginAuthored = "authored"
)

// ReadingLesson is one saved text. It is never updated.
type ReadingLesson struct {
	ID            int64
	Title         string
	SourceURL     string // optional, https, never fetched
	Origin        string
	PackPassageID string // authored only: <pack>/<passage id>
	CreatedAt     time.Time
}

// ReadingPassage is one version of a lesson's text.
type ReadingPassage struct {
	ID        int64
	LessonID  int64
	Version   int
	Segments  []ReadingSegment
	CreatedAt time.Time
}

// ReadingEvidence is a verbatim excerpt of one paragraph.
type ReadingEvidence struct {
	Segment string `json:"segment"`
	Excerpt string `json:"excerpt"`
}

// ReadingWrongAnswer is a plausible but wrong answer with the reason.
type ReadingWrongAnswer struct {
	Answer     string `json:"answer"`
	WhyWrongEN string `json:"why_wrong_en"`
	WhyWrongZH string `json:"why_wrong_zh"`
}

// ReadingItem is one question. Question and answers are French; the
// explanation is stored in English and Simplified Chinese.
type ReadingItem struct {
	ID                   string               `json:"id,omitempty"`
	Kind                 string               `json:"kind"`
	Question             string               `json:"question"`
	ReferenceAnswer      string               `json:"reference_answer"`
	AcceptedAlternatives []string             `json:"accepted_alternatives"`
	WrongAnswers         []ReadingWrongAnswer `json:"wrong_answers"`
	Evidence             []ReadingEvidence    `json:"evidence"`
	ExplanationEN        string               `json:"explanation_en"`
	ExplanationZH        string               `json:"explanation_zh"`
}

// ReadingExerciseContent is a validated exercise.
type ReadingExerciseContent struct {
	Items             []ReadingItem `json:"items"`
	NoInferenceReason string        `json:"no_inference_reason,omitempty"`
}

// ReadingExercise is one stored exercise or failed attempt over one passage version.
type ReadingExercise struct {
	ID          int64
	LessonID    int64
	PassageID   int64
	Status      string // ListeningExerciseCompleted / ListeningExerciseFailed
	FailureCode string
	Generator   string
	Content     *ReadingExerciseContent
	CreatedAt   time.Time
}

// ReadingPreparation is one explicit generation attempt, recorded before the call.
type ReadingPreparation struct {
	ID           int64
	OperationID  string
	LessonID     int64
	PassageID    int64
	AfterUnknown bool
	StartedAt    time.Time
	DeadlineAt   time.Time
	FinishedAt   *time.Time
	Outcome      string
	ExerciseID   *int64
}

// State is the stored outcome, or in_progress / unknown while unfinished.
func (p ReadingPreparation) State(now time.Time) string {
	return attemptState(p.Outcome, p.DeadlineAt, now)
}

// NewReadingPreparation asks the repository to record an attempt.
type NewReadingPreparation struct {
	OperationID         string
	LessonID            int64
	ConfirmUnknownRetry bool
	Now                 time.Time
	Deadline            time.Time
}

// ReadingGenerationRequest is what a generator receives.
type ReadingGenerationRequest struct {
	Title    string
	Segments []ReadingSegment
}

// ReadingExerciseGenerator prepares an exercise. Errors wrap
// ErrProviderTimeout, ErrProviderUnavailable (with ErrOutcomeUnknown when the
// request was sent but no usable answer came back) or ErrValidation.
type ReadingExerciseGenerator interface {
	Name() string
	Generate(ctx context.Context, req ReadingGenerationRequest) (ReadingExerciseContent, error)
}

// Reading lesson states, derived for list and lesson views.
const (
	ReadingStateReady      = "ready_to_prepare"
	ReadingStateInProgress = "in_progress"
	ReadingStatePrepared   = "prepared"
	ReadingStateFailed     = "failed"
	ReadingStateUnknown    = "outcome_unknown"
)

// ReadingRepository stores reading records.
type ReadingRepository interface {
	CreateLesson(ctx context.Context, l ReadingLesson, segments []ReadingSegment, now time.Time) (ReadingLesson, ReadingPassage, error)
	AddPassage(ctx context.Context, lessonID int64, segments []ReadingSegment, now time.Time) (ReadingPassage, error)
	// ImportAuthored stores an authored lesson, its passage and its reviewed
	// exercise in one transaction. The same pack passage with the same content
	// replays (true); different content is ErrReadingPackConflict.
	ImportAuthored(ctx context.Context, l ReadingLesson, segments []ReadingSegment, content ReadingExerciseContent, now time.Time) (ReadingLesson, bool, error)
	GetLesson(ctx context.Context, id int64) (ReadingLesson, error)
	ListLessons(ctx context.Context) ([]ReadingLesson, error)
	LatestPassage(ctx context.Context, lessonID int64) (ReadingPassage, error)
	ListPassages(ctx context.Context, lessonID int64) ([]ReadingPassage, error)
	ListExercises(ctx context.Context, lessonID int64) ([]ReadingExercise, error)
	GetExercise(ctx context.Context, id int64) (ReadingExercise, error)
	// StartPreparation records an attempt before the provider call, or refuses
	// with ErrNotFound, ErrReadingPreparationInProgress, ErrReadingOutcomeUnknown
	// or ErrReadingOperationConflict. The same key returns the stored attempt.
	StartPreparation(ctx context.Context, in NewReadingPreparation) (ReadingPreparation, *ReadingPassage, bool, error)
	FinishPreparation(ctx context.Context, id int64, outcome string, e ReadingExercise, now time.Time) (ReadingPreparation, ReadingExercise, error)
	GetPreparationByOperation(ctx context.Context, operationID string) (ReadingPreparation, error)
	ListPreparations(ctx context.Context, lessonID int64) ([]ReadingPreparation, error)
}

// ParseReadingText splits learner text into paragraphs on blank lines and
// numbers them p1..pN. Each paragraph keeps its exact wording (outer
// whitespace trimmed, inner line breaks kept).
func ParseReadingText(text string) ([]ReadingSegment, error) {
	if !utf8.ValidString(text) {
		return nil, errWrap("text must be UTF-8")
	}
	if utf8.RuneCountInString(text) > MaxReadingTextRunes {
		return nil, errWrap(fmt.Sprintf("text exceeds %d characters; use a shorter passage", MaxReadingTextRunes))
	}
	norm := strings.ReplaceAll(text, "\r\n", "\n")
	var out []ReadingSegment
	for _, block := range regexp.MustCompile(`\n[ \t]*\n`).Split(norm, -1) {
		block = strings.TrimSpace(block)
		if block == "" {
			continue
		}
		id := fmt.Sprintf("p%d", len(out)+1)
		if strings.ContainsFunc(block, func(r rune) bool { return unicode.IsControl(r) && r != '\n' && r != '\t' }) {
			return nil, errWrap(fmt.Sprintf("paragraph %s contains control characters", id))
		}
		if utf8.RuneCountInString(block) > MaxReadingParagraphRunes {
			return nil, errWrap(fmt.Sprintf("paragraph %s exceeds %d characters; split it with a blank line", id, MaxReadingParagraphRunes))
		}
		out = append(out, ReadingSegment{ID: id, Text: block})
		if len(out) > MaxReadingParagraphs {
			return nil, errWrap(fmt.Sprintf("text exceeds %d paragraphs", MaxReadingParagraphs))
		}
	}
	if len(out) == 0 {
		return nil, errWrap("text is empty")
	}
	return out, nil
}

// NormalizeReadingSourceURL accepts an empty link or an absolute https link
// without credentials. It is stored as text and never fetched.
func NormalizeReadingSourceURL(raw string) (string, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return "", nil
	}
	if len(raw) > MaxReadingURLBytes {
		return "", errWrap("source_url is too long")
	}
	u, err := url.Parse(raw)
	if err != nil || u.Scheme != "https" || u.Host == "" || u.User != nil {
		return "", errWrap("source_url must be an https link (it is stored, never fetched)")
	}
	return u.String(), nil
}

var readingItemKinds = map[string]bool{ListeningMainIdea: true, ListeningDetail: true, ListeningInference: true}

func normAnswer(s string) string {
	s = strings.ToLower(strings.ReplaceAll(s, "’", "'"))
	s = strings.Join(strings.Fields(s), " ")
	return strings.TrimRight(s, " .!?;:")
}

// ValidateReadingExercise checks content against the exact passage it was made
// for. It refuses: wrong item counts or kinds (exactly one main_idea, at least
// one detail, at most one inference); a citation of a paragraph that does not
// exist; an excerpt that does not occur verbatim in its paragraph or occurs
// more than once there; an answer listed as both accepted and wrong; blank or
// oversized text. authored additionally requires wrong answers on every item
// and a no_inference_reason when there is no inference item. Text is trimmed in
// place.
func ValidateReadingExercise(segments []ReadingSegment, c *ReadingExerciseContent, authored bool) error {
	bad := func(format string, a ...any) error {
		return fmt.Errorf("%w: "+format, append([]any{ErrValidation}, a...)...)
	}
	byID := make(map[string]string, len(segments))
	for _, s := range segments {
		byID[s.ID] = s.Text
	}
	text := func(field string, s *string, max int) error {
		*s = strings.TrimSpace(*s)
		if *s == "" {
			return bad("%s is empty", field)
		}
		if utf8.RuneCountInString(*s) > max {
			return bad("%s exceeds %d characters", field, max)
		}
		return nil
	}
	if len(c.Items) < minReadingItems || len(c.Items) > maxReadingItems {
		return bad("expected %d to %d items, got %d", minReadingItems, maxReadingItems, len(c.Items))
	}
	counts := map[string]int{}
	for i := range c.Items {
		it := &c.Items[i]
		field := fmt.Sprintf("item %d", i+1)
		if !readingItemKinds[it.Kind] {
			return bad("%s has unknown kind %q", field, it.Kind)
		}
		counts[it.Kind]++
		for _, f := range []struct {
			name string
			s    *string
			max  int
		}{{"question", &it.Question, maxReadingQuestionRunes}, {"reference_answer", &it.ReferenceAnswer, maxReadingAnswerRunes},
			{"explanation_en", &it.ExplanationEN, maxReadingExplainRunes}, {"explanation_zh", &it.ExplanationZH, maxReadingExplainRunes}} {
			if err := text(field+" "+f.name, f.s, f.max); err != nil {
				return err
			}
		}
		if len(it.Evidence) == 0 || len(it.Evidence) > maxReadingEvidence {
			return bad("%s must cite 1 to %d excerpts", field, maxReadingEvidence)
		}
		for k := range it.Evidence {
			e := &it.Evidence[k]
			seg, ok := byID[e.Segment]
			if !ok {
				return bad("%s cites paragraph %q, which the passage does not have", field, e.Segment)
			}
			e.Excerpt = strings.TrimSpace(e.Excerpt)
			if e.Excerpt == "" || utf8.RuneCountInString(e.Excerpt) > maxReadingExcerptRunes {
				return bad("%s excerpt %d must be 1 to %d characters", field, k+1, maxReadingExcerptRunes)
			}
			switch n := strings.Count(seg, e.Excerpt); {
			case n == 0:
				return bad("%s excerpt %d does not occur in paragraph %s", field, k+1, e.Segment)
			case n > 1:
				return bad("%s excerpt %d occurs %d times in paragraph %s; it cannot be located", field, k+1, n, e.Segment)
			}
		}
		if it.AcceptedAlternatives == nil {
			it.AcceptedAlternatives = []string{}
		}
		if len(it.AcceptedAlternatives) > maxReadingAlternatives {
			return bad("%s has more than %d accepted alternatives", field, maxReadingAlternatives)
		}
		accepted := map[string]bool{normAnswer(it.ReferenceAnswer): true}
		for k := range it.AcceptedAlternatives {
			if err := text(fmt.Sprintf("%s accepted alternative %d", field, k+1), &it.AcceptedAlternatives[k], maxReadingAnswerRunes); err != nil {
				return err
			}
			accepted[normAnswer(it.AcceptedAlternatives[k])] = true
		}
		if it.WrongAnswers == nil {
			it.WrongAnswers = []ReadingWrongAnswer{}
		}
		if authored && len(it.WrongAnswers) == 0 {
			return bad("%s: an authored item lists at least one wrong answer", field)
		}
		if len(it.WrongAnswers) > maxReadingWrongAnswers {
			return bad("%s has more than %d wrong answers", field, maxReadingWrongAnswers)
		}
		for k := range it.WrongAnswers {
			w := &it.WrongAnswers[k]
			for _, f := range []struct {
				name string
				s    *string
			}{{"answer", &w.Answer}, {"why_wrong_en", &w.WhyWrongEN}, {"why_wrong_zh", &w.WhyWrongZH}} {
				if err := text(fmt.Sprintf("%s wrong answer %d %s", field, k+1, f.name), f.s, maxReadingExplainRunes); err != nil {
					return err
				}
			}
			if accepted[normAnswer(w.Answer)] {
				return bad("%s lists « %s » as both accepted and wrong", field, w.Answer)
			}
		}
	}
	if counts[ListeningMainIdea] != 1 || counts[ListeningDetail] < 1 || counts[ListeningInference] > 1 {
		return bad("expected one main_idea, at least one detail and at most one inference item")
	}
	c.NoInferenceReason = strings.TrimSpace(c.NoInferenceReason)
	if authored && counts[ListeningInference] == 0 && c.NoInferenceReason == "" {
		return bad("an authored exercise without an inference item says why")
	}
	return nil
}

// ReadingFailureCode maps a generator error to its stored, non-secret code.
func ReadingFailureCode(err error) string { return ListeningFailureCode(err) }

// ---- the authored pack (internal/reading/pack) ----

// ReadingPackPassage is one passage of an authored pack, as published by the
// reading content pack (schema flh_reading_pack_v1).
type ReadingPackPassage struct {
	ID         string `json:"id"`
	Format     string `json:"format"`
	StyleLevel string `json:"style_level"`
	Title      string `json:"title"`
	Source     *struct {
		Kind   string  `json:"kind"`
		Pack   string  `json:"pack"`
		Link   *string `json:"link"`
		Notice string  `json:"notice"`
	} `json:"source"`
	Segments          []ReadingSegment `json:"segments"`
	Questions         []ReadingItem    `json:"questions"`
	NoInferenceReason string           `json:"no_inference_reason,omitempty"`
	Capture           json.RawMessage  `json:"capture,omitempty"`
}

// ReadingPack is an authored pack.
type ReadingPack struct {
	SchemaVersion string               `json:"schema_version"`
	Notice        string               `json:"notice"`
	Passages      []ReadingPackPassage `json:"passages"`
}

var (
	packPassageID = regexp.MustCompile(`^rd-[a-z0-9]+(-[a-z0-9]+)*$`)
	packSegmentID = regexp.MustCompile(`^p[1-9][0-9]*$`)
)

// ParseReadingPack decodes and validates a pack: the schema, a source for
// every passage, paragraph IDs, and every passage's exercise with the authored
// rules (ValidateReadingExercise with authored=true).
func ParseReadingPack(raw []byte) (ReadingPack, error) {
	var p ReadingPack
	if err := json.Unmarshal(raw, &p); err != nil {
		return p, fmt.Errorf("%w: reading pack is not valid JSON", ErrValidation)
	}
	if p.SchemaVersion != ReadingPackID || len(p.Passages) == 0 {
		return p, fmt.Errorf("%w: reading pack must be %s with passages", ErrValidation, ReadingPackID)
	}
	seen := map[string]bool{}
	for i := range p.Passages {
		if err := ValidateReadingPackPassage(&p.Passages[i]); err != nil {
			return p, err
		}
		if seen[p.Passages[i].ID] {
			return p, fmt.Errorf("%w: passage %s appears twice", ErrValidation, p.Passages[i].ID)
		}
		seen[p.Passages[i].ID] = true
	}
	return p, nil
}

// ValidateReadingPackPassage checks one authored passage in place.
func ValidateReadingPackPassage(p *ReadingPackPassage) error {
	bad := func(format string, a ...any) error {
		return fmt.Errorf("%w: passage %s: "+format, append([]any{ErrValidation, p.ID}, a...)...)
	}
	if !packPassageID.MatchString(p.ID) {
		return fmt.Errorf("%w: passage id %q is not a pack passage id", ErrValidation, p.ID)
	}
	if p.Source == nil || strings.TrimSpace(p.Source.Kind) == "" {
		return bad("has no source")
	}
	if _, err := NormalizeListeningTitle(p.Title); err != nil {
		return bad("title: %v", err)
	}
	if len(p.Segments) == 0 || len(p.Segments) > MaxReadingParagraphs {
		return bad("needs 1 to %d paragraphs", MaxReadingParagraphs)
	}
	ids := map[string]bool{}
	for _, s := range p.Segments {
		if !packSegmentID.MatchString(s.ID) || ids[s.ID] {
			return bad("paragraph id %q is malformed or repeated", s.ID)
		}
		ids[s.ID] = true
		if strings.TrimSpace(s.Text) == "" || utf8.RuneCountInString(s.Text) > MaxReadingParagraphRunes {
			return bad("paragraph %s is empty or too long", s.ID)
		}
	}
	c := ReadingExerciseContent{Items: p.Questions, NoInferenceReason: p.NoInferenceReason}
	if err := ValidateReadingExercise(p.Segments, &c, true); err != nil {
		return fmt.Errorf("passage %s: %w", p.ID, err)
	}
	p.Questions, p.NoInferenceReason = c.Items, c.NoInferenceReason
	return nil
}
