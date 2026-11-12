package domain

import (
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"
)

// Authored listening scripts (migration 021). An authored script is written
// French listening material shipped with the server in an embedded pack
// (internal/listening/pack), with authored questions and their key. It is a
// listening material whose source is the script itself: there is no link, no
// video ID, no audio, no playback and no timestamp, and none is ever invented.
// Importing one makes no model call. It stores the material, the lines as
// transcript version 1 (each line keeps its speaker, never a time) and the
// authored exercise, so the lesson, the reveal and an explicit "save learning
// record" work as for any listening lesson. Pulls never select it: it is not
// in any playlist.

// ListeningScriptPackID is the embedded pack format and the provenance prefix.
const ListeningScriptPackID = "flh_listening_script_pack_v1"

// ListeningAuthoredGenerator is the provenance of an imported authored exercise.
const ListeningAuthoredGenerator = "authored:" + ListeningScriptPackID

// Authored-script errors.
var (
	// ErrListeningScriptConflict: the pack script was imported before with
	// different content. Nothing is changed.
	ErrListeningScriptConflict = errors.New("this authored script was already imported with different content")
	// ErrListeningScriptFixed: an authored script is fixed text, so it takes no
	// learner transcript version. Nothing is stored.
	ErrListeningScriptFixed = errors.New("an authored script is fixed text; it takes no learner transcript")
)

const (
	maxAuthoredListeningItems = 12
	maxListeningChoices       = 5
	maxListeningAlternatives  = 4
	maxListeningWrongAnswers  = 4
	maxListeningEvidence      = 3
	maxListeningExcerptRunes  = 300
	maxListeningSpeakerRunes  = 100
)

var (
	authoredItemID     = regexp.MustCompile(`^[a-z0-9]+(-[a-z0-9]+)*$`)
	listeningScriptID  = regexp.MustCompile(`^ls-[a-z0-9]+(-[a-z0-9]+)*$`)
	listeningScriptRef = regexp.MustCompile(`^s[1-9][0-9]*$`)
)

// ListeningScriptLine is one line of an authored script: its stable ID
// (s1..sN, in order), the speaker as the script names them, and the exact text.
type ListeningScriptLine struct {
	ID      string `json:"id"`
	Speaker string `json:"speaker"`
	Text    string `json:"text"`
}

// ListeningScriptSource says where an authored script comes from.
type ListeningScriptSource struct {
	Kind   string `json:"kind"` // always "authored"
	Pack   string `json:"pack"` // the content pack it was generated from
	Notice string `json:"notice"`
}

// ListeningScript is one authored script with its exercise. Question segments
// and evidence segments are 1-based line positions (s3 is segment 3).
type ListeningScript struct {
	ID          string                 `json:"id"`
	Title       string                 `json:"title"`
	Genre       string                 `json:"genre"`
	StyleLevel  string                 `json:"style_level"`
	Source      *ListeningScriptSource `json:"source"`
	Lines       []ListeningScriptLine  `json:"lines"`
	Questions   []ListeningItem        `json:"questions"`
	Annotations []ListeningAnnotation  `json:"annotations"`
}

// ListeningScriptPack is the embedded authored-script pack.
type ListeningScriptPack struct {
	SchemaVersion string            `json:"schema_version"`
	Notice        string            `json:"notice"`
	Scripts       []ListeningScript `json:"scripts"`
}

// Segments returns the script's lines as transcript segments: numbered in
// order, with the speaker and no timestamp.
func (s ListeningScript) Segments() []TranscriptSegment {
	out := make([]TranscriptSegment, len(s.Lines))
	for i, l := range s.Lines {
		out[i] = TranscriptSegment{Index: i + 1, Speaker: l.Speaker, Text: l.Text}
	}
	return out
}

// Content returns the script's authored exercise.
func (s ListeningScript) Content() ListeningExerciseContent {
	return ListeningExerciseContent{Items: s.Questions, Annotations: s.Annotations}
}

// PackScriptID is the stored, unique name of the imported script.
func (s ListeningScript) PackScriptID() string { return ListeningScriptPackID + "/" + s.ID }

// ParseListeningScriptPack decodes and validates a pack: the schema, unique
// script IDs, a source for every script, lines that fit a transcript, and
// every script's exercise under the authored rules. The server refuses to
// start with an invalid pack.
func ParseListeningScriptPack(raw []byte) (ListeningScriptPack, error) {
	var p ListeningScriptPack
	dec := json.NewDecoder(strings.NewReader(string(raw)))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&p); err != nil {
		return p, fmt.Errorf("%w: listening script pack is not valid JSON: %v", ErrValidation, err)
	}
	if p.SchemaVersion != ListeningScriptPackID || len(p.Scripts) == 0 {
		return p, fmt.Errorf("%w: listening script pack must be %s with scripts", ErrValidation, ListeningScriptPackID)
	}
	seen := map[string]bool{}
	for i := range p.Scripts {
		if err := ValidateListeningScript(&p.Scripts[i]); err != nil {
			return p, err
		}
		if seen[p.Scripts[i].ID] {
			return p, fmt.Errorf("%w: script %s appears twice", ErrValidation, p.Scripts[i].ID)
		}
		seen[p.Scripts[i].ID] = true
	}
	return p, nil
}

// ValidateListeningScript checks one authored script in place.
func ValidateListeningScript(s *ListeningScript) error {
	bad := func(format string, a ...any) error {
		return fmt.Errorf("%w: script %s: "+format, append([]any{ErrValidation, s.ID}, a...)...)
	}
	if !listeningScriptID.MatchString(s.ID) {
		return fmt.Errorf("%w: script id %q is not a pack script id", ErrValidation, s.ID)
	}
	if s.Source == nil || s.Source.Kind != "authored" || strings.TrimSpace(s.Source.Pack) == "" || strings.TrimSpace(s.Source.Notice) == "" {
		return bad("needs an authored source with its pack and notice")
	}
	title, err := NormalizeListeningTitle(s.Title)
	if err != nil {
		return bad("title: %v", err)
	}
	s.Title = title
	if len(s.Lines) == 0 || len(s.Lines) > MaxTranscriptSegments {
		return bad("needs 1 to %d lines", MaxTranscriptSegments)
	}
	size := 0
	for i := range s.Lines {
		l := &s.Lines[i]
		if want := fmt.Sprintf("s%d", i+1); l.ID != want || !listeningScriptRef.MatchString(l.ID) {
			return bad("line %d has id %q, want %s", i+1, l.ID, want)
		}
		l.Speaker, l.Text = strings.TrimSpace(l.Speaker), strings.TrimSpace(l.Text)
		if l.Speaker == "" || utf8.RuneCountInString(l.Speaker) > maxListeningSpeakerRunes || strings.ContainsFunc(l.Speaker, unicode.IsControl) {
			return bad("line %s speaker must be one line of 1 to %d characters", l.ID, maxListeningSpeakerRunes)
		}
		if l.Text == "" || utf8.RuneCountInString(l.Text) > MaxSegmentRunes || strings.ContainsFunc(l.Text, unicode.IsControl) {
			return bad("line %s text must be one line of 1 to %d characters", l.ID, MaxSegmentRunes)
		}
		// A script line never starts with a clock time: it would read as a
		// timestamp from a source that has none.
		if segmentTimestamp.MatchString(l.Text) {
			return bad("line %s starts with a time; a script has no timestamps", l.ID)
		}
		size += len(l.Text) + 1
	}
	if size > MaxTranscriptBytes {
		return bad("script exceeds %d bytes", MaxTranscriptBytes)
	}
	c := s.Content()
	if err := ValidateAuthoredListeningExercise(s.Segments(), &c); err != nil {
		return fmt.Errorf("script %s: %w", s.ID, err)
	}
	s.Questions, s.Annotations = c.Items, c.Annotations
	return nil
}

// ValidateAuthoredListeningExercise checks an authored exercise against its
// script. Beyond the generated rules (kinds, segment references, verbatim
// annotation excerpts, no clock time absent from the script) it requires, per
// item: a unique ID; 1 to 3 evidence excerpts that each occur exactly once in a
// cited segment; for a single-choice item, 2 to 5 distinct choices with the
// expected answer exactly once and a reason for every other choice; for a short
// answer, at most 4 accepted alternatives. It allows up to 12 items and several
// inference items, and annotations are optional.
func ValidateAuthoredListeningExercise(segments []TranscriptSegment, c *ListeningExerciseContent) error {
	return validateListeningContent(segments, c, true)
}

// validateAuthoredListeningItem checks the authored-only fields of one item;
// cited holds the item's validated segment references.
func validateAuthoredListeningItem(segments []TranscriptSegment, it *ListeningItem, cited map[int]bool, field string,
	text func(string, *string, int) error) error {
	bad := func(format string, a ...any) error {
		return fmt.Errorf("%w: "+format, append([]any{ErrValidation}, a...)...)
	}
	if len(it.Evidence) == 0 || len(it.Evidence) > maxListeningEvidence {
		return bad("%s must cite 1 to %d evidence excerpts", field, maxListeningEvidence)
	}
	for k := range it.Evidence {
		e := &it.Evidence[k]
		if !cited[e.Segment] {
			return bad("%s evidence %d is in segment %d, which the item does not cite", field, k+1, e.Segment)
		}
		e.Excerpt = strings.TrimSpace(e.Excerpt)
		if e.Excerpt == "" || utf8.RuneCountInString(e.Excerpt) > maxListeningExcerptRunes {
			return bad("%s evidence %d must be 1 to %d characters", field, k+1, maxListeningExcerptRunes)
		}
		switch n := strings.Count(segments[e.Segment-1].Text, e.Excerpt); {
		case n == 0:
			return bad("%s evidence %d does not occur in segment %d", field, k+1, e.Segment)
		case n > 1:
			return bad("%s evidence %d occurs %d times in segment %d; it cannot be located", field, k+1, n, e.Segment)
		}
	}
	accepted := map[string]bool{normAnswer(it.ExpectedAnswer): true}
	if it.AcceptedAlternatives == nil {
		it.AcceptedAlternatives = []string{}
	}
	if len(it.AcceptedAlternatives) > maxListeningAlternatives {
		return bad("%s has more than %d accepted alternatives", field, maxListeningAlternatives)
	}
	for k := range it.AcceptedAlternatives {
		if err := text(fmt.Sprintf("%s accepted alternative %d", field, k+1), &it.AcceptedAlternatives[k], maxAnswerRunes); err != nil {
			return err
		}
		accepted[normAnswer(it.AcceptedAlternatives[k])] = true
	}
	if len(it.WrongAnswers) > maxListeningWrongAnswers {
		return bad("%s has more than %d wrong answers", field, maxListeningWrongAnswers)
	}
	wrong := map[string]bool{}
	for k := range it.WrongAnswers {
		w := &it.WrongAnswers[k]
		for _, f := range []struct {
			name string
			s    *string
		}{{"answer", &w.Answer}, {"why_wrong_en", &w.WhyWrongEN}, {"why_wrong_zh", &w.WhyWrongZH}} {
			if err := text(fmt.Sprintf("%s wrong answer %d %s", field, k+1, f.name), f.s, maxRationaleRunes); err != nil {
				return err
			}
		}
		if accepted[normAnswer(w.Answer)] {
			return bad("%s lists « %s » as both accepted and wrong", field, w.Answer)
		}
		wrong[w.Answer] = true
	}
	if len(it.Choices) == 0 {
		return nil // a short answer
	}
	if len(it.Choices) < 2 || len(it.Choices) > maxListeningChoices {
		return bad("%s must offer 2 to %d choices", field, maxListeningChoices)
	}
	if len(it.AcceptedAlternatives) > 0 {
		return bad("%s is single choice, so it has no accepted alternatives", field)
	}
	distinct, correct := map[string]bool{}, 0
	for k := range it.Choices {
		if err := text(fmt.Sprintf("%s choice %d", field, k+1), &it.Choices[k], maxAnswerRunes); err != nil {
			return err
		}
		n := normAnswer(it.Choices[k])
		if distinct[n] {
			return bad("%s repeats choice « %s »", field, it.Choices[k])
		}
		distinct[n] = true
		switch {
		case it.Choices[k] == it.ExpectedAnswer:
			correct++
		case !wrong[it.Choices[k]]:
			return bad("%s choice « %s » has no reason why it is wrong", field, it.Choices[k])
		}
	}
	if correct != 1 {
		return bad("%s expected answer must be exactly one of its choices", field)
	}
	if len(it.WrongAnswers) != len(it.Choices)-1 {
		return bad("%s gives reasons for answers that are not among its choices", field)
	}
	return nil
}
