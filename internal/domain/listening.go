package domain

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

// Exam Listening Lesson v1. A learner saves a YouTube link, a title and, when
// they have one, a French transcript they supplied themselves. One explicit
// request asks the opt-in generator for a short exam-style exercise over that
// transcript. Material, transcripts and exercises are separate, append-only
// records: an exercise never rewrites its source, and a failed generation is
// stored as an honest failure next to the untouched material.
//
// The server never fetches the link: the video ID is parsed from the text, and
// nothing is downloaded, scraped or transcribed.

// ListeningExercisePromptVersion versions the generator instruction and output
// contract; it is part of the stored provenance.
const ListeningExercisePromptVersion = "listening_exercise_v1"

// ErrListeningDisabled reports that no exercise generator is configured
// (LISTENING_PROVIDER=disabled, the default). Nothing is stored.
var ErrListeningDisabled = errors.New("listening exercise generation is not enabled")

// ErrListeningNoTranscript reports a generation request for material that has
// no transcript. No provider is called and nothing is stored.
var ErrListeningNoTranscript = errors.New("this material has no transcript, so no exercise can be prepared")

// Bounds. A transcript is a short exam-style extract, not a whole programme.
const (
	MaxListeningTitleRunes   = 200
	MaxListeningURLBytes     = 2048
	MaxTranscriptBytes       = 12000
	MaxTranscriptSegments    = 200
	MaxSegmentRunes          = 500
	maxListeningItems        = 4
	maxListeningAnnotations  = 6
	maxSegmentRefsPerItem    = 3
	maxQuestionRunes         = 300
	maxAnswerRunes           = 400
	maxRationaleRunes        = 500
	maxAnnotationExcerptRune = 120
	maxAnnotationNoteRunes   = 300
)

// Listening material source kinds (migration 021). A YouTube material has a
// video ID and its canonical link; an authored script (listening_script.go)
// has neither: it is written text with no audio, video or timestamps.
const (
	ListeningSourceYouTube        = "youtube"
	ListeningSourceAuthoredScript = "authored_script"
)

// ListeningMaterial is one saved video link or one imported authored script.
// It is never updated.
type ListeningMaterial struct {
	ID         int64
	SourceKind string // ListeningSourceYouTube or ListeningSourceAuthoredScript
	VideoID    string // YouTube only; empty for an authored script
	SourceURL  string // YouTube only: canonical https://www.youtube.com/watch?v=<id>
	// PackScriptID names the imported authored script (<pack>/<script id>);
	// empty for YouTube material.
	PackScriptID string
	Title        string
	CreatedAt    time.Time
}

// IsAuthoredScript reports whether the material is script-only.
func (m ListeningMaterial) IsAuthoredScript() bool {
	return m.SourceKind == ListeningSourceAuthoredScript
}

// TranscriptSegment is one learner-supplied line. StartSeconds is set only when
// the learner's source supplied a timestamp for it. Speaker is set only for an
// authored script, whose lines name their speaker; a learner transcript has none.
type TranscriptSegment struct {
	Index        int    `json:"index"`
	StartSeconds *int   `json:"start_seconds"`
	Speaker      string `json:"speaker,omitempty"`
	Text         string `json:"text"`
}

// ListeningTranscript is one version of a material's transcript.
type ListeningTranscript struct {
	ID            int64
	MaterialID    int64
	Version       int
	Segments      []TranscriptSegment
	HasTimestamps bool
	CreatedAt     time.Time
}

// ListeningItem kinds.
const (
	ListeningMainIdea  = "main_idea"
	ListeningDetail    = "detail"
	ListeningInference = "inference"
)

// ListeningItem is one exam-style question. Question and expected answer are
// French; the rationale is stored in English and Simplified Chinese (FLH-095
// convention: both from the same request). Segments are 1-based references to
// the transcript the exercise was generated from.
//
// ID, Choices, AcceptedAlternatives, WrongAnswers and Evidence belong to
// authored scripts only (ValidateAuthoredListeningExercise); generated content
// never carries them, and ValidateListeningExercise refuses them.
type ListeningItem struct {
	ID             string `json:"id,omitempty"`
	Kind           string `json:"kind"`
	Question       string `json:"question"`
	ExpectedAnswer string `json:"expected_answer"`
	RationaleEN    string `json:"rationale_en"`
	RationaleZH    string `json:"rationale_zh"`
	Segments       []int  `json:"segments"`
	// Choices are the options in authored order (single choice); empty for a
	// short answer. ExpectedAnswer is exactly one of them.
	Choices              []string               `json:"choices,omitempty"`
	AcceptedAlternatives []string               `json:"accepted_alternatives,omitempty"`
	WrongAnswers         []ListeningWrongAnswer `json:"wrong_answers,omitempty"`
	Evidence             []ListeningEvidence    `json:"evidence,omitempty"`
}

// ListeningWrongAnswer is an authored wrong choice with the reason, in the
// same shape as an authored reading wrong answer.
type ListeningWrongAnswer = ReadingWrongAnswer

// ListeningEvidence is a verbatim excerpt of one segment of an authored
// script. It occurs exactly once in that segment.
type ListeningEvidence struct {
	Segment int    `json:"segment"`
	Excerpt string `json:"excerpt"`
}

func (it ListeningItem) hasAuthoredFields() bool {
	return it.ID != "" || len(it.Choices) > 0 || len(it.AcceptedAlternatives) > 0 || len(it.WrongAnswers) > 0 || len(it.Evidence) > 0
}

// ListeningAnnotation is a vocabulary or grammar note tied to one segment.
// Excerpt must occur verbatim in that segment.
type ListeningAnnotation struct {
	Kind    string `json:"kind"`
	Segment int    `json:"segment"`
	Excerpt string `json:"excerpt"`
	NoteEN  string `json:"note_en"`
	NoteZH  string `json:"note_zh"`
}

// ListeningExerciseContent is the validated generator output.
type ListeningExerciseContent struct {
	Items       []ListeningItem       `json:"items"`
	Annotations []ListeningAnnotation `json:"annotations"`
}

// Exercise statuses and failure codes (non-secret).
const (
	ListeningExerciseCompleted = "completed"
	ListeningExerciseFailed    = "failed"

	ListeningFailureTimeout       = "provider_timeout"
	ListeningFailureUnavailable   = "provider_unavailable"
	ListeningFailureInvalidOutput = "invalid_output"
)

// ListeningExercise is one stored generation attempt over one transcript.
type ListeningExercise struct {
	ID           int64
	MaterialID   int64
	TranscriptID int64
	Status       string
	FailureCode  string // set only when Status is failed
	Generator    string
	Content      *ListeningExerciseContent // set only when Status is completed
	CreatedAt    time.Time
}

// ListeningGenerationRequest is what a generator receives: the title and the
// numbered segments. Timestamps are not sent; the generator cites segments.
type ListeningGenerationRequest struct {
	Title    string
	Segments []TranscriptSegment
}

// ListeningExerciseGenerator prepares an exercise. Errors wrap
// ErrProviderTimeout, ErrProviderUnavailable or (for unusable output)
// ErrValidation, and never carry credentials, provider bodies or learner text.
type ListeningExerciseGenerator interface {
	Name() string
	Generate(ctx context.Context, req ListeningGenerationRequest) (ListeningExerciseContent, error)
}

// ListeningRepository stores listening records. Every row is written once.
type ListeningRepository interface {
	CreateMaterial(ctx context.Context, m ListeningMaterial, transcript []TranscriptSegment, hasTimestamps bool) (ListeningMaterial, *ListeningTranscript, error)
	AddTranscript(ctx context.Context, materialID int64, segments []TranscriptSegment, hasTimestamps bool) (ListeningTranscript, error)
	GetMaterial(ctx context.Context, id int64) (ListeningMaterial, error)
	ListMaterials(ctx context.Context) ([]ListeningMaterial, error)
	LatestTranscript(ctx context.Context, materialID int64) (*ListeningTranscript, error)
	GetTranscript(ctx context.Context, id int64) (ListeningTranscript, error)
	CreateExercise(ctx context.Context, e ListeningExercise) (ListeningExercise, error)
	ListExercises(ctx context.Context, materialID int64) ([]ListeningExercise, error)
	// ImportAuthoredScript stores an authored script as material (no link),
	// its lines as transcript version 1 (no timestamps) and its authored
	// exercise, in one transaction. The same pack script with the same content
	// replays (true); different content is ErrListeningScriptConflict.
	ImportAuthoredScript(ctx context.Context, m ListeningMaterial, segments []TranscriptSegment, content ListeningExerciseContent, now time.Time) (ListeningMaterial, bool, error)
}

var youTubeID = regexp.MustCompile(`^[A-Za-z0-9_-]{11}$`)

// ParseYouTubeURL validates a YouTube video link by its text alone and returns
// the video ID and the canonical watch URL. Accepted: http(s) on youtube.com,
// www.youtube.com, m.youtube.com (/watch?v=, /shorts/, /embed/, /live/) and
// youtu.be/<id>. Credentials, ports and every other host are refused.
func ParseYouTubeURL(raw string) (videoID, canonical string, err error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return "", "", errWrap("source_url is required")
	}
	if len(raw) > MaxListeningURLBytes {
		return "", "", errWrap("source_url is too long")
	}
	u, perr := url.Parse(raw)
	if perr != nil || (u.Scheme != "https" && u.Scheme != "http") || u.User != nil || u.Port() != "" || u.Opaque != "" {
		return "", "", errWrap("source_url must be a YouTube video link (https://www.youtube.com/watch?v=… or https://youtu.be/…)")
	}
	host := strings.ToLower(u.Hostname())
	path := strings.TrimSuffix(u.EscapedPath(), "/")
	var id string
	switch host {
	case "youtu.be":
		id = strings.TrimPrefix(path, "/")
	case "youtube.com", "www.youtube.com", "m.youtube.com":
		switch {
		case path == "/watch":
			id = u.Query().Get("v")
		case strings.HasPrefix(path, "/shorts/"), strings.HasPrefix(path, "/embed/"), strings.HasPrefix(path, "/live/"):
			id = path[strings.LastIndex(path, "/")+1:]
		}
	}
	if !youTubeID.MatchString(id) {
		return "", "", errWrap("source_url must be a YouTube video link (https://www.youtube.com/watch?v=… or https://youtu.be/…)")
	}
	return id, "https://www.youtube.com/watch?v=" + id, nil
}

// NormalizeListeningTitle trims and bounds a title.
func NormalizeListeningTitle(raw string) (string, error) {
	t := strings.TrimSpace(raw)
	if t == "" {
		return "", errWrap("title is required")
	}
	if utf8.RuneCountInString(t) > MaxListeningTitleRunes {
		return "", errWrap(fmt.Sprintf("title exceeds %d characters", MaxListeningTitleRunes))
	}
	if strings.ContainsFunc(t, unicode.IsControl) {
		return "", errWrap("title must be a single line")
	}
	return t, nil
}

// A leading source timestamp: [h:mm:ss], [mm:ss], h:mm:ss or mm:ss, then space.
var segmentTimestamp = regexp.MustCompile(`^\[?(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)\]?\s+(.*)$`)

// ParseTranscript splits learner-supplied text into numbered segments, one per
// non-empty line. A line may start with the source's own timestamp; either every
// line has one (non-decreasing) or none has, so a timestamp is never implied for
// a line the source did not time.
func ParseTranscript(text string) ([]TranscriptSegment, bool, error) {
	if len(text) > MaxTranscriptBytes {
		return nil, false, errWrap(fmt.Sprintf("transcript exceeds %d bytes; use a shorter extract", MaxTranscriptBytes))
	}
	if !utf8.ValidString(text) {
		return nil, false, errWrap("transcript must be UTF-8 text")
	}
	var segments []TranscriptSegment
	timed, untimed := 0, 0
	last := -1
	for _, line := range strings.Split(strings.ReplaceAll(text, "\r\n", "\n"), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		seg := TranscriptSegment{Index: len(segments) + 1, Text: line}
		if m := segmentTimestamp.FindStringSubmatch(line); m != nil && strings.TrimSpace(m[4]) != "" {
			h := 0
			if m[1] != "" {
				h, _ = strconv.Atoi(m[1])
			}
			mm, _ := strconv.Atoi(m[2])
			ss, _ := strconv.Atoi(m[3])
			start := h*3600 + mm*60 + ss
			if start < last {
				return nil, false, errWrap(fmt.Sprintf("segment %d: timestamps must not go backwards", seg.Index))
			}
			last = start
			seg.StartSeconds = &start
			seg.Text = strings.TrimSpace(m[4])
			timed++
		} else {
			untimed++
		}
		if strings.ContainsFunc(seg.Text, func(r rune) bool { return unicode.IsControl(r) && r != '\t' }) {
			return nil, false, errWrap(fmt.Sprintf("segment %d contains control characters", seg.Index))
		}
		if utf8.RuneCountInString(seg.Text) > MaxSegmentRunes {
			return nil, false, errWrap(fmt.Sprintf("segment %d exceeds %d characters; split it into shorter lines", seg.Index, MaxSegmentRunes))
		}
		segments = append(segments, seg)
		if len(segments) > MaxTranscriptSegments {
			return nil, false, errWrap(fmt.Sprintf("transcript exceeds %d lines", MaxTranscriptSegments))
		}
	}
	if len(segments) == 0 {
		return nil, false, errWrap("transcript is empty")
	}
	if timed > 0 && untimed > 0 {
		return nil, false, errWrap("either every line starts with a timestamp from your source, or none does")
	}
	return segments, timed > 0, nil
}

// clockTime finds a clock-like time (1:23, 01:02:03) in generated text.
var clockTime = regexp.MustCompile(`\b\d{1,2}:\d{2}(?::\d{2})?\b`)

// ValidateListeningExercise checks generated content against the exact
// transcript it was generated from. It refuses: a missing main-idea or detail
// item, unknown kinds, segment references outside the transcript, annotation
// excerpts that do not occur verbatim in their segment, and any clock time in
// generated text that does not occur in the transcript (timestamps shown to the
// learner come only from the learner's own source), and the fields reserved for
// authored scripts. Text is trimmed in place.
func ValidateListeningExercise(segments []TranscriptSegment, c *ListeningExerciseContent) error {
	return validateListeningContent(segments, c, false)
}

func validateListeningContent(segments []TranscriptSegment, c *ListeningExerciseContent, authored bool) error {
	bad := func(format string, a ...any) error {
		return fmt.Errorf("%w: "+format, append([]any{ErrValidation}, a...)...)
	}
	n := len(segments)
	var transcript strings.Builder
	for _, s := range segments {
		transcript.WriteString(s.Text)
		transcript.WriteString("\n")
	}
	noFabricatedTime := func(field, text string) error {
		// An authored script has no audio or video, so a clock time in its
		// explanations is a time of day from the story (the script says "onze
		// heures et demie", the explanation "11:30"), never a playback position.
		// Generated content keeps the rule: it must not invent times for a video.
		if authored {
			return nil
		}
		for _, t := range clockTime.FindAllString(text, -1) {
			if !strings.Contains(transcript.String(), t) {
				return bad("%s cites a time (%s) that the transcript does not contain", field, t)
			}
		}
		return nil
	}
	text := func(field string, s *string, max int) error {
		*s = strings.TrimSpace(*s)
		if *s == "" {
			return bad("%s is empty", field)
		}
		if utf8.RuneCountInString(*s) > max {
			return bad("%s exceeds %d characters", field, max)
		}
		return noFabricatedTime(field, *s)
	}
	maxItems := maxListeningItems
	if authored {
		maxItems = maxAuthoredListeningItems
	}
	if len(c.Items) < 2 || len(c.Items) > maxItems {
		return bad("expected 2 to %d items, got %d", maxItems, len(c.Items))
	}
	counts := map[string]int{}
	ids := map[string]bool{}
	for i := range c.Items {
		it := &c.Items[i]
		field := fmt.Sprintf("item %d", i+1)
		if !authored && it.hasAuthoredFields() {
			return bad("%s carries fields reserved for authored scripts", field)
		}
		if authored {
			if !authoredItemID.MatchString(it.ID) || ids[it.ID] {
				return bad("%s id %q is malformed or repeated", field, it.ID)
			}
			ids[it.ID] = true
		}
		switch it.Kind {
		case ListeningMainIdea, ListeningDetail, ListeningInference:
		default:
			return bad("%s has unknown kind %q", field, it.Kind)
		}
		counts[it.Kind]++
		for _, f := range []struct {
			name string
			s    *string
			max  int
		}{{"question", &it.Question, maxQuestionRunes}, {"expected_answer", &it.ExpectedAnswer, maxAnswerRunes},
			{"rationale_en", &it.RationaleEN, maxRationaleRunes}, {"rationale_zh", &it.RationaleZH, maxRationaleRunes}} {
			if err := text(field+" "+f.name, f.s, f.max); err != nil {
				return err
			}
		}
		if len(it.Segments) == 0 || len(it.Segments) > maxSegmentRefsPerItem {
			return bad("%s must cite 1 to %d segments", field, maxSegmentRefsPerItem)
		}
		seen := map[int]bool{}
		for _, ref := range it.Segments {
			if ref < 1 || ref > n {
				return bad("%s cites segment %d, but the transcript has %d", field, ref, n)
			}
			if seen[ref] {
				return bad("%s cites segment %d twice", field, ref)
			}
			seen[ref] = true
		}
		if authored {
			if err := validateAuthoredListeningItem(segments, it, seen, field, text); err != nil {
				return err
			}
		}
	}
	// A generated exercise has at most one inference item, so the model cannot
	// pad it with guesses. An authored script states each of its inferences
	// with evidence, so it may have several.
	if counts[ListeningMainIdea] != 1 || counts[ListeningDetail] < 1 || (!authored && counts[ListeningInference] > 1) {
		if authored {
			return bad("expected one main_idea and at least one detail item")
		}
		return bad("expected one main_idea, at least one detail and at most one inference item")
	}
	minAnnotations := 1
	if authored {
		minAnnotations = 0 // a vocabulary note is added only where the script has the exact words
	}
	if len(c.Annotations) < minAnnotations || len(c.Annotations) > maxListeningAnnotations {
		return bad("expected %d to %d annotations, got %d", minAnnotations, maxListeningAnnotations, len(c.Annotations))
	}
	for i := range c.Annotations {
		a := &c.Annotations[i]
		field := fmt.Sprintf("annotation %d", i+1)
		if a.Kind != "vocabulary" && a.Kind != "grammar" {
			return bad("%s has unknown kind %q", field, a.Kind)
		}
		if a.Segment < 1 || a.Segment > n {
			return bad("%s cites segment %d, but the transcript has %d", field, a.Segment, n)
		}
		a.Excerpt = strings.TrimSpace(a.Excerpt)
		if a.Excerpt == "" || utf8.RuneCountInString(a.Excerpt) > maxAnnotationExcerptRune {
			return bad("%s excerpt must be 1 to %d characters", field, maxAnnotationExcerptRune)
		}
		if !strings.Contains(segments[a.Segment-1].Text, a.Excerpt) {
			return bad("%s excerpt does not occur in segment %d", field, a.Segment)
		}
		if err := text(field+" note_en", &a.NoteEN, maxAnnotationNoteRunes); err != nil {
			return err
		}
		if err := text(field+" note_zh", &a.NoteZH, maxAnnotationNoteRunes); err != nil {
			return err
		}
	}
	return nil
}

// ListeningFailureCode maps a generator error to its stored, non-secret code.
func ListeningFailureCode(err error) string {
	switch {
	case errors.Is(err, ErrProviderTimeout):
		return ListeningFailureTimeout
	case errors.Is(err, ErrValidation):
		return ListeningFailureInvalidOutput
	default:
		return ListeningFailureUnavailable
	}
}
