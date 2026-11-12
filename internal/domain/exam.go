package domain

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"
)

// Mock Exam v1: a timed reading-comprehension exam assembled only from
// authored material (the reading pack's reviewed questions, their reference
// answers and their authored wrong answers). A session freezes a copy of every
// question with a content hash when it starts, so a later pack change never
// alters a running or past exam. The deadline is the server's; answers are
// append-only events accepted only before it; one submission closes a session
// and repeating it with the same answers replays the same result. Nothing
// calls a provider, and nothing is a CEFR level or an official score.

// MockExamFormsVersion is the schema of the embedded forms file.
const MockExamFormsVersion = "flh_mock_exam_forms_v1"

// Exam session kinds and states.
const (
	ExamKindExam  = "exam"
	ExamKindRetry = "retry"

	ExamInProgress = "in_progress"
	ExamSubmitted  = "submitted"
	ExamExpired    = "expired"
)

// Mock Exam errors.
var (
	ErrExamClosed            = errors.New("this exam was already submitted")
	ErrExamExpired           = errors.New("the time for this exam is over")
	ErrExamAlreadySubmitted  = errors.New("this exam was already submitted with other answers")
	ErrExamOperationConflict = errors.New("this Idempotency-Key was used for another exam start")
	ErrExamNoRelated         = errors.New("no related authored question is left for this question")
	ErrExamNotClosed         = errors.New("a related question can be practised only after the exam is closed")
)

// MockExamFormRef names one authored question: a reading pack passage and the
// id of one of its questions.
type MockExamFormRef struct {
	Passage  string `json:"passage"`
	Question string `json:"question"`
}

// MockExamForm is one authored exam form.
type MockExamForm struct {
	ID              string            `json:"id"`
	Title           string            `json:"title"`
	Section         string            `json:"section"` // "reading" in v1
	DurationSeconds int               `json:"duration_seconds"`
	Description     string            `json:"description"`
	Questions       []MockExamFormRef `json:"questions"`
}

// MockExamForms is the embedded forms file.
type MockExamForms struct {
	SchemaVersion string         `json:"schema_version"`
	Notice        string         `json:"notice"`
	Pack          string         `json:"pack"`
	RetrySeconds  int            `json:"retry_seconds"`
	Forms         []MockExamForm `json:"forms"`
}

// Form returns the form with id, or false.
func (f MockExamForms) Form(id string) (MockExamForm, bool) {
	for _, x := range f.Forms {
		if x.ID == id {
			return x, true
		}
	}
	return MockExamForm{}, false
}

// ExamWhyWrong is the authored reason a choice is wrong.
type ExamWhyWrong struct {
	EN string `json:"en"`
	ZH string `json:"zh"`
}

// ExamItem is one frozen question: everything needed to show, mark and
// explain it, copied from the authored pack when the session starts.
type ExamItem struct {
	PackID        string            `json:"pack_id"`
	PassageID     string            `json:"passage_id"`
	QuestionID    string            `json:"question_id"`
	PackItem      int               `json:"pack_item"` // 1-based position of the question in its passage (the reading exercise item)
	PassageTitle  string            `json:"passage_title"`
	PassageFormat string            `json:"passage_format"`
	StyleLevel    string            `json:"style_level"`
	Segments      []ReadingSegment  `json:"segments"`
	Kind          string            `json:"kind"`
	Question      string            `json:"question"`
	Choices       []string          `json:"choices"` // in the order shown
	Key           int               `json:"key"`     // index of the authored reference answer in Choices
	WhyWrong      []*ExamWhyWrong   `json:"why_wrong"`
	Evidence      []ReadingEvidence `json:"evidence"`
	ExplanationEN string            `json:"explanation_en"`
	ExplanationZH string            `json:"explanation_zh"`
}

// ContentSHA256 is the hash of the frozen item's canonical JSON.
func (it ExamItem) ContentSHA256() (string, []byte, error) {
	raw, err := json.Marshal(it)
	if err != nil {
		return "", nil, err
	}
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:]), raw, nil
}

// ParseMockExamForms decodes and validates the forms file against the pack:
// every reference names an existing passage and question that has at least
// one authored wrong answer, ids are unique, and durations are bounded.
func ParseMockExamForms(raw []byte, pack ReadingPack) (MockExamForms, error) {
	var f MockExamForms
	dec := json.NewDecoder(strings.NewReader(string(raw)))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&f); err != nil {
		return f, fmt.Errorf("%w: mock exam forms are not valid JSON: %v", ErrValidation, err)
	}
	if f.SchemaVersion != MockExamFormsVersion {
		return f, fmt.Errorf("%w: mock exam forms schema_version must be %s", ErrValidation, MockExamFormsVersion)
	}
	if f.Pack != ReadingPackID || strings.TrimSpace(f.Notice) == "" {
		return f, fmt.Errorf("%w: mock exam forms must name pack %s and carry a notice", ErrValidation, ReadingPackID)
	}
	if f.RetrySeconds < 30 || f.RetrySeconds > 1800 {
		return f, fmt.Errorf("%w: retry_seconds must be between 30 and 1800", ErrValidation)
	}
	if len(f.Forms) == 0 {
		return f, fmt.Errorf("%w: no mock exam form", ErrValidation)
	}
	seen := map[string]bool{}
	for _, form := range f.Forms {
		if form.ID == "" || seen[form.ID] || strings.TrimSpace(form.Title) == "" || form.Section != "reading" {
			return f, fmt.Errorf("%w: form %q needs a unique id, a title and section reading", ErrValidation, form.ID)
		}
		seen[form.ID] = true
		if form.DurationSeconds < 30 || form.DurationSeconds > 7200 {
			return f, fmt.Errorf("%w: form %s duration_seconds must be between 30 and 7200", ErrValidation, form.ID)
		}
		if len(form.Questions) == 0 || len(form.Questions) > 40 {
			return f, fmt.Errorf("%w: form %s needs 1 to 40 questions", ErrValidation, form.ID)
		}
		used := map[string]bool{}
		for _, ref := range form.Questions {
			if used[ref.Question] {
				return f, fmt.Errorf("%w: form %s repeats %s", ErrValidation, form.ID, ref.Question)
			}
			used[ref.Question] = true
			if _, err := FreezeExamItem(pack, ref); err != nil {
				return f, fmt.Errorf("form %s: %w", form.ID, err)
			}
		}
	}
	return f, nil
}

// FreezeExamItem copies one authored question into an ExamItem. The choices
// are the reference answer and the authored wrong answers, in an order fixed
// by a hash of the question id and each choice, so the key is not always first
// and the same question always shows the same order.
func FreezeExamItem(pack ReadingPack, ref MockExamFormRef) (ExamItem, error) {
	for _, p := range pack.Passages {
		if p.ID != ref.Passage {
			continue
		}
		for i, q := range p.Questions {
			if q.ID != ref.Question {
				continue
			}
			if len(q.WrongAnswers) == 0 {
				return ExamItem{}, fmt.Errorf("%w: question %s has no authored wrong answer", ErrValidation, q.ID)
			}
			type choice struct {
				text string
				why  *ExamWhyWrong
			}
			cs := []choice{{text: q.ReferenceAnswer}}
			for _, w := range q.WrongAnswers {
				cs = append(cs, choice{text: w.Answer, why: &ExamWhyWrong{EN: w.WhyWrongEN, ZH: w.WhyWrongZH}})
			}
			order := func(c choice) string {
				s := sha256.Sum256([]byte(q.ID + "\x00" + c.text))
				return hex.EncodeToString(s[:])
			}
			sort.SliceStable(cs, func(a, b int) bool { return order(cs[a]) < order(cs[b]) })
			it := ExamItem{
				PackID: ReadingPackID, PassageID: p.ID, QuestionID: q.ID, PackItem: i + 1,
				PassageTitle: p.Title, PassageFormat: p.Format, StyleLevel: p.StyleLevel, Segments: p.Segments,
				Kind: q.Kind, Question: q.Question, Evidence: q.Evidence,
				ExplanationEN: q.ExplanationEN, ExplanationZH: q.ExplanationZH,
			}
			seen := map[string]bool{}
			for j, c := range cs {
				if seen[c.text] {
					return ExamItem{}, fmt.Errorf("%w: question %s repeats a choice", ErrValidation, q.ID)
				}
				seen[c.text] = true
				it.Choices = append(it.Choices, c.text)
				it.WhyWrong = append(it.WhyWrong, c.why)
				if c.why == nil {
					it.Key = j
				}
			}
			return it, nil
		}
		return ExamItem{}, fmt.Errorf("%w: passage %s has no question %s", ErrValidation, ref.Passage, ref.Question)
	}
	return ExamItem{}, fmt.Errorf("%w: the reading pack has no passage %s", ErrValidation, ref.Passage)
}

// RelatedExamRef picks an authored question related to item for a retry: the
// first question of the same kind in another passage (pack order) that is not
// in exclude; otherwise another question of the same passage. It never picks
// a question the learner just saw.
func RelatedExamRef(pack ReadingPack, item ExamItem, exclude map[string]bool) (MockExamFormRef, error) {
	for _, p := range pack.Passages {
		if p.ID == item.PassageID {
			continue
		}
		for _, q := range p.Questions {
			if q.Kind == item.Kind && !exclude[q.ID] && len(q.WrongAnswers) > 0 {
				return MockExamFormRef{Passage: p.ID, Question: q.ID}, nil
			}
		}
	}
	for _, p := range pack.Passages {
		if p.ID != item.PassageID {
			continue
		}
		for _, q := range p.Questions {
			if q.ID != item.QuestionID && !exclude[q.ID] && len(q.WrongAnswers) > 0 {
				return MockExamFormRef{Passage: p.ID, Question: q.ID}, nil
			}
		}
	}
	return MockExamFormRef{}, ErrExamNoRelated
}

// ExamSession is one started exam (or one related-question retry) with its
// frozen items, in position order (position = index + 1).
type ExamSession struct {
	ID              int64
	OperationID     string
	Kind            string
	FormID          string
	FormTitle       string
	RetryOf         *int64
	RetryOfPosition int
	FormsSHA256     string
	PackSHA256      string
	DurationSeconds int
	StartedAt       time.Time
	DeadlineAt      time.Time
	Items           []ExamItem
	ItemSHA256      []string
}

// ExamAnswer is the current answer to one position (nil Choice: cleared).
type ExamAnswer struct {
	Position int
	Choice   *int
	SavedAt  time.Time
}

// ExamSubmission closes a session before its deadline.
type ExamSubmission struct {
	SessionID     int64
	Answers       map[int]*int
	AnswersSHA256 string
	Correct       int
	Total         int
	SubmittedAt   time.Time
}

// ExamAnswersSHA256 fingerprints a full answer set (positions 1..n).
func ExamAnswersSHA256(n int, answers map[int]*int) string {
	var b strings.Builder
	for p := 1; p <= n; p++ {
		b.WriteString(strconv.Itoa(p))
		b.WriteByte('=')
		if c := answers[p]; c != nil {
			b.WriteString(strconv.Itoa(*c))
		} else {
			b.WriteByte('-')
		}
		b.WriteByte(';')
	}
	sum := sha256.Sum256([]byte(b.String()))
	return hex.EncodeToString(sum[:])
}

// ScoreExam counts the answers that chose each item's authored key.
func ScoreExam(items []ExamItem, answers map[int]*int) (correct, total int) {
	for i, it := range items {
		if c := answers[i+1]; c != nil && *c == it.Key {
			correct++
		}
	}
	return correct, len(items)
}

// ExamState derives a session's state at now: a submission closes it;
// otherwise the server's deadline does.
func ExamState(s ExamSession, sub *ExamSubmission, now time.Time) string {
	if sub != nil {
		return ExamSubmitted
	}
	if now.After(s.DeadlineAt) {
		return ExamExpired
	}
	return ExamInProgress
}

// ValidateExamChoice checks a choice for one position.
func ValidateExamChoice(s ExamSession, position int, choice *int) error {
	if position < 1 || position > len(s.Items) {
		return fmt.Errorf("%w: position must be between 1 and %d", ErrValidation, len(s.Items))
	}
	if choice != nil && (*choice < 0 || *choice >= len(s.Items[position-1].Choices)) {
		return fmt.Errorf("%w: choice must be between 0 and %d", ErrValidation, len(s.Items[position-1].Choices)-1)
	}
	return nil
}

// ExamRepository stores sessions, answer events and submissions.
type ExamRepository interface {
	// CreateSession stores a session and its frozen items, or returns the
	// session already stored under the same operation id (replay=true).
	// Another form or retry target under that id is ErrExamOperationConflict.
	CreateSession(ctx context.Context, s ExamSession) (ExamSession, bool, error)
	GetSession(ctx context.Context, id int64) (ExamSession, error)
	ListSessions(ctx context.Context) ([]ExamSession, error) // newest first, without items
	RetryQuestionIDs(ctx context.Context, sessionID int64) ([]string, error)
	CurrentAnswers(ctx context.Context, sessionID int64) (map[int]ExamAnswer, error)
	GetSubmission(ctx context.Context, sessionID int64) (*ExamSubmission, error)
	// SaveAnswer appends an answer event when it changes the current answer,
	// re-checking inside its write transaction that the session is neither
	// submitted (ErrExamClosed) nor past its deadline at now (ErrExamExpired).
	SaveAnswer(ctx context.Context, sessionID int64, position int, choice *int, now time.Time) (ExamAnswer, bool, error)
	// Submit merges answers over the current ones and closes the session at
	// now, in one transaction. A submitted session replays (true) when the
	// merged answers equal the stored ones, else ErrExamAlreadySubmitted; past
	// the deadline it is ErrExamExpired and nothing is written.
	Submit(ctx context.Context, sessionID int64, answers map[int]*int, now time.Time) (ExamSubmission, bool, error)
}
