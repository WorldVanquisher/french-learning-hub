package domain

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"mime"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
)

// Speaking v1. A learner answers an authored practical prompt aloud: the
// browser records a take and plays it back locally, and nothing is sent while
// recording or playing back. Only on an explicit request is one take's audio
// sent for transcription; it is never stored. The learner confirms (and may
// correct) the transcript, which becomes an immutable transcript version.
// Feedback is one explicit request for one confirmed transcript version and is
// always tied to that exact text: the server grounds every quote against it.
// Feedback is about the text only: it never judges pronunciation, and there is
// no score, grade, CEFR level or exam result.

// Versions of the stored contracts.
const (
	SpeakingPromptsID             = "flh_speaking_prompts_v1"
	SpeakingFeedbackPromptVersion = "speaking_feedback_v1"
	SpeakingTranscriptionVersion  = "speaking_transcription_v1"
)

var (
	ErrSpeakingFeedbackDisabled      = errors.New("speaking feedback is not enabled")
	ErrSpeakingTranscriptionDisabled = errors.New("speaking transcription is not enabled")
	ErrSpeakingPromptConflict        = errors.New("this authored prompt was already started with different content")
	ErrSpeakingTooManyTakes          = errors.New("this exercise already has the maximum number of takes")
	ErrSpeakingTooManyVersions       = errors.New("this take already has the maximum number of transcript versions")
	ErrSpeakingTranscriptUnchanged   = errors.New("this transcript is identical to the latest confirmed version; nothing was saved")
	ErrSpeakingNoAudio               = errors.New("this take has no audio to transcribe; type the transcript instead")
	ErrSpeakingRequestInProgress     = ErrListeningPreparationInProgress
	ErrSpeakingOutcomeUnknown        = ErrListeningOutcomeUnknown
	ErrSpeakingOperationConflict     = ErrListeningOperationConflict
)

// Bounds. Answers are short spoken messages, not monologues.
const (
	MaxSpeakingTakes              = 20
	MaxSpeakingTranscriptVersions = 10
	// MaxSpeakingAudioBytes bounds one take's audio (the provider accepts 25 MB).
	MaxSpeakingAudioBytes = 8 << 20
	// MaxSpeakingDurationMS bounds one take; the recorder stops itself there.
	MaxSpeakingDurationMS      = 120_000
	MaxSpeakingTranscriptRunes = 2000
	maxSpeakingSituationRunes  = 1500
	maxSpeakingRequirements    = 6
	maxSpeakingImprovements    = 4
	maxSpeakingQuoteRunes      = 200
	maxSpeakingCommentRunes    = 600
	maxSpeakingSuggestionRunes = 300
)

// Where a take's audio came from. "none" is a take whose transcript is typed.
const (
	SpeakingAudioRecording = "recording"
	SpeakingAudioFile      = "file"
	SpeakingAudioNone      = "none"
)

// Origins of a confirmed transcript version.
const (
	SpeakingTranscriptFromTranscription = "transcription" // the machine transcript, confirmed unchanged
	SpeakingTranscriptCorrected         = "corrected"     // edited from a machine transcript or an earlier version
	SpeakingTranscriptTyped             = "typed"         // typed with no machine transcript
)

// SpeakingAudioFormat is an accepted audio type and the file extension sent
// with it. Only formats listed by BOTH the provider's speech-to-text guide and
// its API reference are accepted: webm, mp4/m4a, mpeg/mp3 and wav.
type SpeakingAudioFormat struct {
	MIME      string
	Extension string
}

var speakingAudioFormats = map[string]SpeakingAudioFormat{
	"audio/webm":     {"audio/webm", "webm"},
	"audio/mp4":      {"audio/mp4", "mp4"},
	"audio/x-m4a":    {"audio/mp4", "m4a"},
	"audio/m4a":      {"audio/mp4", "m4a"},
	"audio/mpeg":     {"audio/mpeg", "mp3"},
	"audio/mp3":      {"audio/mpeg", "mp3"},
	"audio/wav":      {"audio/wav", "wav"},
	"audio/x-wav":    {"audio/wav", "wav"},
	"audio/wave":     {"audio/wav", "wav"},
	"audio/vnd.wave": {"audio/wav", "wav"},
}

// SpeakingAudioType resolves a declared type (parameters such as codecs are
// ignored) to its canonical type, or refuses it.
func SpeakingAudioType(declared string) (SpeakingAudioFormat, error) {
	media, _, err := mime.ParseMediaType(strings.TrimSpace(declared))
	if err != nil {
		return SpeakingAudioFormat{}, werr("audio type %q is not a media type", declared)
	}
	f, ok := speakingAudioFormats[strings.ToLower(media)]
	if !ok {
		return SpeakingAudioFormat{}, werr("audio type %q is not accepted (webm, mp4/m4a, mpeg/mp3 or wav)", media)
	}
	return f, nil
}

// CheckSpeakingAudio checks the bytes of one take before anything is sent: the
// size bound and the container's magic bytes for its canonical type.
func CheckSpeakingAudio(f SpeakingAudioFormat, data []byte) error {
	if len(data) == 0 {
		return werr("audio is empty")
	}
	if len(data) > MaxSpeakingAudioBytes {
		return werr("audio exceeds %d bytes", MaxSpeakingAudioBytes)
	}
	ok := false
	switch f.MIME {
	case "audio/webm":
		ok = bytes.HasPrefix(data, []byte{0x1A, 0x45, 0xDF, 0xA3})
	case "audio/mp4":
		ok = len(data) >= 12 && string(data[4:8]) == "ftyp"
	case "audio/mpeg":
		ok = bytes.HasPrefix(data, []byte("ID3")) || (len(data) >= 2 && data[0] == 0xFF && data[1]&0xE0 == 0xE0)
	case "audio/wav":
		ok = len(data) >= 12 && string(data[0:4]) == "RIFF" && string(data[8:12]) == "WAVE"
	}
	if !ok {
		return werr("audio content does not look like %s", f.MIME)
	}
	return nil
}

var sha256Hex = regexp.MustCompile(`^[0-9a-f]{64}$`)

// SpeakingExercise is the exercise for one authored prompt. It is never updated.
type SpeakingExercise struct {
	ID           int64
	PromptID     string
	Title        string
	Situation    string
	Requirements []string
	SecondsMin   int
	SecondsMax   int
	CreatedAt    time.Time
}

// SpeakingTake is one numbered take. Only metadata about its audio is kept.
type SpeakingTake struct {
	ID          int64
	ExerciseID  int64
	Number      int
	AudioSource string
	AudioMIME   string // canonical; empty when AudioSource is none
	AudioBytes  int64
	AudioSHA256 string
	DurationMS  int // measured by the browser; 0 when AudioSource is none
	CreatedAt   time.Time
}

// NormalizeSpeakingTake validates the metadata of a new take. A recording or a
// file needs its canonical type, size, SHA-256 and a duration within the bound;
// a typed take ("none") carries none of them.
func NormalizeSpeakingTake(t SpeakingTake) (SpeakingTake, error) {
	switch t.AudioSource {
	case SpeakingAudioNone:
		if t.AudioMIME != "" || t.AudioBytes != 0 || t.AudioSHA256 != "" || t.DurationMS != 0 {
			return t, werr("a take without audio carries no audio metadata")
		}
		return t, nil
	case SpeakingAudioRecording, SpeakingAudioFile:
	default:
		return t, werr("audio_source must be recording, file or none")
	}
	f, err := SpeakingAudioType(t.AudioMIME)
	if err != nil {
		return t, err
	}
	t.AudioMIME = f.MIME
	if t.AudioBytes < 1 || t.AudioBytes > MaxSpeakingAudioBytes {
		return t, werr("audio_bytes must be between 1 and %d", MaxSpeakingAudioBytes)
	}
	t.AudioSHA256 = strings.ToLower(strings.TrimSpace(t.AudioSHA256))
	if !sha256Hex.MatchString(t.AudioSHA256) {
		return t, werr("audio_sha256 must be 64 hexadecimal characters")
	}
	if t.DurationMS < 1 || t.DurationMS > MaxSpeakingDurationMS {
		return t, werr("duration_ms must be between 1 and %d", MaxSpeakingDurationMS)
	}
	return t, nil
}

// SpeakingTranscription is one machine transcript of one take, or a failure.
type SpeakingTranscription struct {
	ID          int64
	TakeID      int64
	Status      string
	FailureCode string
	Transcriber string
	Text        string // completed only
	CreatedAt   time.Time
}

// SpeakingTranscriptionRequest is one explicit request, recorded before the call.
type SpeakingTranscriptionRequest struct {
	ID              int64
	OperationID     string
	ExerciseID      int64
	TakeID          int64
	AudioSHA256     string
	AfterUnknown    bool
	StartedAt       time.Time
	DeadlineAt      time.Time
	FinishedAt      *time.Time
	Outcome         string
	TranscriptionID *int64
}

// State is the stored outcome, or in_progress / unknown while unfinished.
func (r SpeakingTranscriptionRequest) State(now time.Time) string {
	return attemptState(r.Outcome, r.DeadlineAt, now)
}

// NewSpeakingTranscriptionRequest asks the repository to record a request.
type NewSpeakingTranscriptionRequest struct {
	OperationID         string
	TakeID              int64
	AudioMIME           string // canonical type of the audio sent
	AudioSHA256         string
	ConfirmUnknownRetry bool
	Now                 time.Time
	Deadline            time.Time
}

// SpeakingTranscript is one confirmed, immutable transcript version of a take.
type SpeakingTranscript struct {
	ID              int64
	TakeID          int64
	Version         int
	Text            string
	WordCount       int
	Origin          string
	TranscriptionID *int64
	CreatedAt       time.Time
}

// NormalizeSpeakingTranscript validates a transcript. The wording is kept
// exactly (outer whitespace trimmed); only the word count is derived, with the
// Writing convention.
func NormalizeSpeakingTranscript(text string) (string, int, error) {
	s, err := boundedText("text", strings.ReplaceAll(text, "\r\n", "\n"), MaxSpeakingTranscriptRunes)
	if err != nil {
		return "", 0, err
	}
	return s, CountWritingWords(s), nil
}

// SpeakingImprovement is one actionable improvement quoting the confirmed
// transcript. Grounding and Start are set by the server, never by the model.
type SpeakingImprovement struct {
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

// SpeakingFeedbackContent is validated, grounded feedback on one transcript.
type SpeakingFeedbackContent struct {
	TaskFulfilment WritingTaskFulfilment `json:"task_fulfilment"`
	Clarity        WritingComment        `json:"clarity"`
	Improvements   []SpeakingImprovement `json:"improvements"`
}

// SpeakingFeedback is one stored report or failed request for one transcript version.
type SpeakingFeedback struct {
	ID           int64
	ExerciseID   int64
	TranscriptID int64
	Status       string
	FailureCode  string
	Generator    string
	Content      *SpeakingFeedbackContent
	CreatedAt    time.Time
}

// SpeakingFeedbackRequest is one explicit request, recorded before the call.
type SpeakingFeedbackRequest struct {
	ID           int64
	OperationID  string
	ExerciseID   int64
	TranscriptID int64
	AfterUnknown bool
	StartedAt    time.Time
	DeadlineAt   time.Time
	FinishedAt   *time.Time
	Outcome      string
	FeedbackID   *int64
}

// State is the stored outcome, or in_progress / unknown while unfinished.
func (r SpeakingFeedbackRequest) State(now time.Time) string {
	return attemptState(r.Outcome, r.DeadlineAt, now)
}

// NewSpeakingFeedbackRequest asks the repository to record a request.
type NewSpeakingFeedbackRequest struct {
	OperationID         string
	TranscriptID        int64
	ConfirmUnknownRetry bool
	Now                 time.Time
	Deadline            time.Time
}

// SpeakingTranscriptionInput is what a transcriber receives: one take's audio.
// No prompt or expected answer is sent, so the transcript is not nudged towards
// what the learner should have said.
type SpeakingTranscriptionInput struct {
	Audio  []byte
	Format SpeakingAudioFormat
}

// SpeakingTranscriber transcribes one take. Errors follow the generator
// contract (ErrProviderTimeout, ErrProviderUnavailable with ErrOutcomeUnknown
// when sent but unanswered, ErrValidation) and never carry credentials,
// provider bodies or audio.
type SpeakingTranscriber interface {
	Name() string
	Transcribe(ctx context.Context, in SpeakingTranscriptionInput) (string, error)
}

// SpeakingFeedbackInput is what a feedback generator receives.
type SpeakingFeedbackInput struct {
	Title        string
	Situation    string
	Requirements []string
	SecondsMin   int
	SecondsMax   int
	DurationMS   int // 0 when the take had no audio
	Transcript   string
	WordCount    int
}

// SpeakingFeedbackGenerator asks for feedback on one confirmed transcript.
type SpeakingFeedbackGenerator interface {
	Name() string
	Generate(ctx context.Context, in SpeakingFeedbackInput) (SpeakingFeedbackContent, error)
}

// SpeakingRepository stores speaking records. It never stores audio.
type SpeakingRepository interface {
	// StartExercise creates the exercise for an authored prompt once; the same
	// prompt returns the existing exercise (true); different content conflicts.
	StartExercise(ctx context.Context, e SpeakingExercise, now time.Time) (SpeakingExercise, bool, error)
	GetExercise(ctx context.Context, id int64) (SpeakingExercise, error)
	ListExercises(ctx context.Context) ([]SpeakingExercise, error)
	AddTake(ctx context.Context, exerciseID int64, t SpeakingTake, now time.Time) (SpeakingTake, error)
	GetTake(ctx context.Context, id int64) (SpeakingTake, error)
	ListTakes(ctx context.Context, exerciseID int64) ([]SpeakingTake, error)
	// StartTranscriptionRequest records a request before the call, or refuses
	// with ErrNotFound, ErrSpeakingNoAudio, ErrValidation (audio mismatch),
	// ErrSpeakingRequestInProgress, ErrSpeakingOutcomeUnknown or
	// ErrSpeakingOperationConflict.
	StartTranscriptionRequest(ctx context.Context, in NewSpeakingTranscriptionRequest) (SpeakingTranscriptionRequest, *SpeakingTake, bool, error)
	FinishTranscriptionRequest(ctx context.Context, id int64, outcome string, t SpeakingTranscription, now time.Time) (SpeakingTranscriptionRequest, SpeakingTranscription, error)
	GetTranscriptionRequestByOperation(ctx context.Context, operationID string) (SpeakingTranscriptionRequest, error)
	GetTranscription(ctx context.Context, id int64) (SpeakingTranscription, error)
	ListTranscriptions(ctx context.Context, exerciseID int64) ([]SpeakingTranscription, error)
	ListTranscriptionRequests(ctx context.Context, exerciseID int64) ([]SpeakingTranscriptionRequest, error)
	// AddTranscript saves the next confirmed version of a take. The origin is
	// decided inside the transaction: the machine transcript unchanged
	// (transcription), an edit (corrected) or typed with none (typed).
	AddTranscript(ctx context.Context, takeID int64, text string, words int, transcriptionID *int64, now time.Time) (SpeakingTranscript, error)
	GetTranscript(ctx context.Context, id int64) (SpeakingTranscript, error)
	ListTranscripts(ctx context.Context, exerciseID int64) ([]SpeakingTranscript, error)
	StartFeedbackRequest(ctx context.Context, in NewSpeakingFeedbackRequest) (SpeakingFeedbackRequest, *SpeakingTranscript, bool, error)
	FinishFeedbackRequest(ctx context.Context, id int64, outcome string, f SpeakingFeedback, now time.Time) (SpeakingFeedbackRequest, SpeakingFeedback, error)
	GetFeedbackRequestByOperation(ctx context.Context, operationID string) (SpeakingFeedbackRequest, error)
	GetFeedback(ctx context.Context, id int64) (SpeakingFeedback, error)
	ListFeedback(ctx context.Context, exerciseID int64) ([]SpeakingFeedback, error)
	ListFeedbackRequests(ctx context.Context, exerciseID int64) ([]SpeakingFeedbackRequest, error)
}

var speakingCategories = map[string]bool{"grammar": true, "vocabulary": true, "register": true, "organisation": true}

// speakingForbiddenClaims finds comments that judge sound from text, or claim
// a score or level: a transcript cannot show pronunciation, and this practice
// gives no exam result. Only the English and Chinese comment fields are
// checked; the learner's quoted French and the suggestion are not.
var speakingForbiddenClaims = regexp.MustCompile(`(?i)pronunciation|pronounc|intonation|prosody|\b(?:your|the speaker's|the learner's|an?) accent\b|\baccent (?:is|was|sounds)\b|\b(?:score|scores|scored|grade|graded|cefr|delf|dalf|tcf|tef)\b|发音|口音|语调|声调|分数|评分|得分|欧框`)

// ValidateSpeakingFeedback checks model output against the exact confirmed
// transcript and grounds every quote: located (exactly once, with its rune
// offset), ambiguous (more than once, no location) or not_found. It refuses an
// unknown rating or category, blank or oversized fields, more than four
// improvements, an empty quote, a suggestion identical to its quote, and any
// comment about pronunciation or a score, grade or level.
func ValidateSpeakingFeedback(transcript string, c *SpeakingFeedbackContent) error {
	tf := &c.TaskFulfilment
	if !writingRatings[tf.Rating] {
		return werr("task_fulfilment.rating %q is not met, partly_met or not_met", tf.Rating)
	}
	var err error
	type field struct {
		name string
		s    *string
		max  int
	}
	checkClaims := func(fields []field) error {
		for _, f := range fields {
			if strings.HasSuffix(f.name, "suggestion") {
				continue
			}
			if speakingForbiddenClaims.MatchString(*f.s) {
				return werr("%s comments on pronunciation or claims a score or level, which a transcript cannot support", f.name)
			}
		}
		return nil
	}
	top := []field{{"task_fulfilment.comment_en", &tf.CommentEN, maxSpeakingCommentRunes}, {"task_fulfilment.comment_zh", &tf.CommentZH, maxSpeakingCommentRunes},
		{"clarity.comment_en", &c.Clarity.CommentEN, maxSpeakingCommentRunes}, {"clarity.comment_zh", &c.Clarity.CommentZH, maxSpeakingCommentRunes}}
	for _, f := range top {
		if *f.s, err = boundedText(f.name, *f.s, f.max); err != nil {
			return err
		}
	}
	if err := checkClaims(top); err != nil {
		return err
	}
	if c.Improvements == nil {
		c.Improvements = []SpeakingImprovement{}
	}
	if len(c.Improvements) > maxSpeakingImprovements {
		return werr("at most %d improvements, got %d", maxSpeakingImprovements, len(c.Improvements))
	}
	for i := range c.Improvements {
		k := &c.Improvements[i]
		name := fmt.Sprintf("improvement %d", i+1)
		if !speakingCategories[k.Category] {
			return werr("%s has unknown category %q", name, k.Category)
		}
		if strings.TrimSpace(k.Quote) == "" || utf8.RuneCountInString(k.Quote) > maxSpeakingQuoteRunes {
			return werr("%s quote must be 1 to %d characters", name, maxSpeakingQuoteRunes)
		}
		fields := []field{{name + " hint_en", &k.HintEN, maxSpeakingCommentRunes}, {name + " hint_zh", &k.HintZH, maxSpeakingCommentRunes},
			{name + " suggestion", &k.Suggestion, maxSpeakingSuggestionRunes}, {name + " reason_en", &k.ReasonEN, maxSpeakingCommentRunes}, {name + " reason_zh", &k.ReasonZH, maxSpeakingCommentRunes}}
		for _, f := range fields {
			if *f.s, err = boundedText(f.name, *f.s, f.max); err != nil {
				return err
			}
		}
		if err := checkClaims(fields); err != nil {
			return err
		}
		if k.Suggestion == strings.TrimSpace(k.Quote) {
			return werr("%s suggests the same wording it quotes", name)
		}
		k.Grounding, k.Start = groundQuote(transcript, k.Quote)
	}
	return nil
}

// SpeakingFailureCode maps a provider error to its stored, non-secret code.
func SpeakingFailureCode(err error) string { return ListeningFailureCode(err) }

// ---- authored prompts (internal/speaking/prompts) ----

// SpeakingPrompt is one authored practical prompt, with an example transcript
// (with deliberate mistakes) for demonstration and acceptance.
type SpeakingPrompt struct {
	ID                string   `json:"id"`
	Format            string   `json:"format"`
	StyleLevel        string   `json:"style_level"`
	Title             string   `json:"title"`
	Situation         string   `json:"situation"`
	Requirements      []string `json:"requirements"`
	SecondsMin        int      `json:"seconds_min"`
	SecondsMax        int      `json:"seconds_max"`
	ExampleTranscript string   `json:"example_transcript"`
}

// SpeakingPromptSet is the embedded set.
type SpeakingPromptSet struct {
	SchemaVersion string           `json:"schema_version"`
	Notice        string           `json:"notice"`
	Prompts       []SpeakingPrompt `json:"prompts"`
}

var speakingPromptID = regexp.MustCompile(`^sp-[a-z0-9]+(-[a-z0-9]+)*$`)

// ParseSpeakingPrompts decodes and validates the authored prompt set.
func ParseSpeakingPrompts(raw []byte) (SpeakingPromptSet, error) {
	var s SpeakingPromptSet
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&s); err != nil {
		return s, werr("speaking prompts are not valid JSON")
	}
	if s.SchemaVersion != SpeakingPromptsID || len(s.Prompts) == 0 {
		return s, werr("speaking prompts must be %s with prompts", SpeakingPromptsID)
	}
	seen := map[string]bool{}
	for i := range s.Prompts {
		p := &s.Prompts[i]
		if !speakingPromptID.MatchString(p.ID) || seen[p.ID] {
			return s, werr("prompt id %q is malformed or repeated", p.ID)
		}
		seen[p.ID] = true
		var err error
		if p.Title, err = NormalizeListeningTitle(p.Title); err != nil {
			return s, fmt.Errorf("prompt %s: %w", p.ID, err)
		}
		if p.Situation, err = boundedText("situation", p.Situation, maxSpeakingSituationRunes); err != nil {
			return s, fmt.Errorf("prompt %s: %w", p.ID, err)
		}
		if len(p.Requirements) == 0 || len(p.Requirements) > maxSpeakingRequirements {
			return s, werr("prompt %s needs 1 to %d content points", p.ID, maxSpeakingRequirements)
		}
		for j := range p.Requirements {
			if p.Requirements[j], err = boundedText(fmt.Sprintf("content point %d", j+1), p.Requirements[j], maxWritingRequirementRunes); err != nil {
				return s, fmt.Errorf("prompt %s: %w", p.ID, err)
			}
		}
		if p.SecondsMin < 1 || p.SecondsMax < p.SecondsMin || p.SecondsMax*1000 > MaxSpeakingDurationMS {
			return s, werr("prompt %s: seconds must satisfy 1 <= seconds_min <= seconds_max <= %d", p.ID, MaxSpeakingDurationMS/1000)
		}
		if _, _, err := NormalizeSpeakingTranscript(p.ExampleTranscript); err != nil {
			return s, fmt.Errorf("prompt %s example transcript: %w", p.ID, err)
		}
	}
	return s, nil
}
