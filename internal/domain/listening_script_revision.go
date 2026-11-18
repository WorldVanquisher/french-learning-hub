package domain

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
)

// Revisions of an imported authored script. A pack correction never rewrites
// what was imported: the learner may update a lesson explicitly, after a
// preview, and the update appends a new revision. Revision N of a script is
// its transcript version N (the lines, no timestamps) with the authored
// exercise stored on it; import creates revision 1. Earlier revisions are
// never changed or deleted, so a Mistake Notebook record (which names one
// exercise and item) keeps resolving to the exact words it was saved from.
// No migration: revisions use the existing transcript and exercise tables.

// Pack status of an imported script, compared with the server's pack.
const (
	// ListeningScriptUpToDate: the current revision has the pack's content.
	ListeningScriptUpToDate = "up_to_date"
	// ListeningScriptUpdateAvailable: the pack has other lines or questions;
	// an explicit update may append them as the next revision.
	ListeningScriptUpdateAvailable = "update_available"
	// ListeningScriptTitleChanged: the pack renamed the script. A material's
	// title is fixed, so no update is offered (the lesson stays as it is).
	ListeningScriptTitleChanged = "title_changed"
	// ListeningScriptNotInPack: the server's pack no longer has the script.
	ListeningScriptNotInPack = "not_in_pack"
)

// Revision errors. Each one leaves every stored row unchanged.
var (
	// ErrListeningNotAuthoredScript: revisions exist for authored scripts only.
	ErrListeningNotAuthoredScript = errors.New("this lesson is not an authored script, so it has no script revisions")
	// ErrListeningScriptNotInPack: the server's pack has no such script.
	ErrListeningScriptNotInPack = errors.New("this server's script pack no longer has this script, so there is nothing to update to")
	// ErrListeningScriptTitleChanged: the pack renamed the script; a lesson's
	// title is fixed, so it cannot be updated in place.
	ErrListeningScriptTitleChanged = errors.New("the pack renamed this script; a lesson's title is fixed, so it cannot be updated")
	// ErrListeningScriptRevisionStale: the preview the learner confirmed no
	// longer describes the update (the lesson or the pack changed since).
	ErrListeningScriptRevisionStale = errors.New("the lesson or the script pack changed since this preview; nothing was updated")
)

var listeningFingerprint = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)

// ValidListeningScriptFingerprint reports whether s has the fingerprint form.
func ValidListeningScriptFingerprint(s string) bool { return listeningFingerprint.MatchString(s) }

// ListeningScriptFingerprint identifies a revision's content: the SHA-256 of
// its lines and its authored exercise, each as canonical JSON (decoded and
// re-encoded, so object keys are sorted), joined by a newline. Two revisions
// have the same fingerprint exactly when the import comparison treats them as
// equal. The title is not part of it (a material's title is fixed).
func ListeningScriptFingerprint(rawSegments, rawContent []byte) (string, error) {
	h := sha256.New()
	for i, raw := range [][]byte{rawSegments, rawContent} {
		var v any
		if err := json.Unmarshal(raw, &v); err != nil {
			return "", fmt.Errorf("fingerprint: decode: %w", err)
		}
		canonical, err := json.Marshal(v)
		if err != nil {
			return "", fmt.Errorf("fingerprint: encode: %w", err)
		}
		if i > 0 {
			h.Write([]byte("\n"))
		}
		h.Write(canonical)
	}
	return "sha256:" + hex.EncodeToString(h.Sum(nil)), nil
}

// ListeningRevisionFingerprint fingerprints a revision as the workbench reads
// it: its decoded lines and exercise, re-encoded. A stored revision is compared
// through it, so a difference in the stored JSON that these types do not carry
// (a key another build wrote, another encoding of the same value) is never
// reported as an update, previewed as an empty change, or appended as a
// revision.
func ListeningRevisionFingerprint(segments []TranscriptSegment, content ListeningExerciseContent) (string, error) {
	rawSegments, err := json.Marshal(segments)
	if err != nil {
		return "", err
	}
	rawContent, err := json.Marshal(content)
	if err != nil {
		return "", err
	}
	return ListeningScriptFingerprint(rawSegments, rawContent)
}

// Fingerprint is the fingerprint the script's content would have once stored.
func (s ListeningScript) Fingerprint() (string, error) {
	return ListeningRevisionFingerprint(s.Segments(), s.Content())
}

// ListeningScriptRevision is one stored revision of an imported script.
type ListeningScriptRevision struct {
	Revision    int // the transcript version
	Transcript  ListeningTranscript
	Exercise    ListeningExercise
	Fingerprint string
}

// ListeningLineChange is one script line that differs between two revisions.
// Change is "changed", "added" or "removed"; Before or After is nil for an
// added or removed line. Line is the line's ID in the next revision (in the
// stored one for a removed line); BeforeLine and AfterLine name it on each
// side, so a changed line that also moved names both numbers.
type ListeningLineChange struct {
	Line       string               `json:"line"`
	Change     string               `json:"change"`
	BeforeLine *string              `json:"before_line"`
	AfterLine  *string              `json:"after_line"`
	Before     *ListeningScriptLine `json:"before"`
	After      *ListeningScriptLine `json:"after"`
}

// ListeningLineMove is an unchanged line whose number changes only because
// lines before it were removed or added.
type ListeningLineMove struct {
	Before string `json:"before"`
	After  string `json:"after"`
}

// ListeningQuestionChange is one question that differs, matched by its item
// ID. Fields names what changed: kind, question, choices, expected_answer,
// accepted_alternatives, wrong_answers, rationale, segments, evidence,
// position. Before and After are the whole item (nil when added or removed);
// the workbench shows answers only on request.
type ListeningQuestionChange struct {
	ItemID         string         `json:"item_id"`
	Change         string         `json:"change"`
	BeforePosition *int           `json:"before_position"`
	AfterPosition  *int           `json:"after_position"`
	Fields         []string       `json:"fields"`
	Before         *ListeningItem `json:"before"`
	After          *ListeningItem `json:"after"`
}

// ListeningScriptChanges is what an update would change. Unchanged lines and
// questions are not listed.
type ListeningScriptChanges struct {
	Lines []ListeningLineChange `json:"lines"`
	// LinesRenumbered lists unchanged lines that only get a new number.
	LinesRenumbered    []ListeningLineMove       `json:"lines_renumbered"`
	Questions          []ListeningQuestionChange `json:"questions"`
	AnnotationsChanged bool                      `json:"annotations_changed"`
}

// Empty reports whether nothing differs.
func (c ListeningScriptChanges) Empty() bool {
	return len(c.Lines) == 0 && len(c.LinesRenumbered) == 0 && len(c.Questions) == 0 && !c.AnnotationsChanged
}

func sameJSON(a, b any) bool {
	x, errX := json.Marshal(a)
	y, errY := json.Marshal(b)
	if errX != nil || errY != nil {
		return false
	}
	var u, v any
	if json.Unmarshal(x, &u) != nil || json.Unmarshal(y, &v) != nil {
		return false
	}
	x, _ = json.Marshal(u)
	y, _ = json.Marshal(v)
	return string(x) == string(y)
}

// DiffListeningScript lists what differs between a stored revision (its
// segments and exercise) and the next content. Lines are aligned by content
// (alignLines), so removing or adding a line reports that line, not every
// later one; questions are matched by item ID (an item without an ID by
// position).
func DiffListeningScript(beforeSegments []TranscriptSegment, before ListeningExerciseContent, afterSegments []TranscriptSegment, after ListeningExerciseContent) ListeningScriptChanges {
	out := ListeningScriptChanges{Lines: []ListeningLineChange{}, LinesRenumbered: []ListeningLineMove{}, Questions: []ListeningQuestionChange{}}
	line := func(s TranscriptSegment) *ListeningScriptLine {
		return &ListeningScriptLine{ID: fmt.Sprintf("s%d", s.Index), Speaker: s.Speaker, Text: s.Text}
	}
	id := func(i int) *string { s := fmt.Sprintf("s%d", i+1); return &s }
	for _, p := range alignLines(beforeSegments, afterSegments) {
		switch {
		case p.before < 0:
			out.Lines = append(out.Lines, ListeningLineChange{Line: *id(p.after), Change: "added", AfterLine: id(p.after), After: line(afterSegments[p.after])})
		case p.after < 0:
			out.Lines = append(out.Lines, ListeningLineChange{Line: *id(p.before), Change: "removed", BeforeLine: id(p.before), Before: line(beforeSegments[p.before])})
		case !sameJSON(lineContent(beforeSegments[p.before]), lineContent(afterSegments[p.after])):
			out.Lines = append(out.Lines, ListeningLineChange{Line: *id(p.after), Change: "changed", BeforeLine: id(p.before), AfterLine: id(p.after),
				Before: line(beforeSegments[p.before]), After: line(afterSegments[p.after])})
		case p.before != p.after:
			out.LinesRenumbered = append(out.LinesRenumbered, ListeningLineMove{Before: *id(p.before), After: *id(p.after)})
		}
	}
	key := func(it ListeningItem, pos int) string {
		if it.ID != "" {
			return "id:" + it.ID
		}
		return fmt.Sprintf("pos:%d", pos)
	}
	type at struct {
		item ListeningItem
		pos  int
	}
	old := map[string]at{}
	for i, it := range before.Items {
		old[key(it, i+1)] = at{it, i + 1}
	}
	seen := map[string]bool{}
	for i, it := range after.Items {
		k, pos := key(it, i+1), i+1
		seen[k] = true
		next := it
		prev, ok := old[k]
		if !ok {
			out.Questions = append(out.Questions, ListeningQuestionChange{ItemID: it.ID, Change: "added", AfterPosition: &pos, Fields: []string{}, After: &next})
			continue
		}
		fields := itemChanges(prev.item, it)
		if prev.pos != pos {
			fields = append(fields, "position")
		}
		if len(fields) > 0 {
			was, p := prev.item, prev.pos
			out.Questions = append(out.Questions, ListeningQuestionChange{ItemID: it.ID, Change: "changed", BeforePosition: &p, AfterPosition: &pos,
				Fields: fields, Before: &was, After: &next})
		}
	}
	for i, it := range before.Items {
		if k := key(it, i+1); !seen[k] {
			was, p := it, i+1
			out.Questions = append(out.Questions, ListeningQuestionChange{ItemID: it.ID, Change: "removed", BeforePosition: &p, Fields: []string{}, Before: &was})
		}
	}
	out.AnnotationsChanged = !sameJSON(before.Annotations, after.Annotations)
	return out
}

// lineContent is what a line says, without its number.
func lineContent(s TranscriptSegment) TranscriptSegment {
	s.Index = 0
	return s
}

// linePair pairs a stored line with a next one by index; -1 is a missing side.
type linePair struct{ before, after int }

// alignLines pairs the lines of two revisions in order: lines with the same
// content (speaker and wording) are matched by their longest common
// subsequence; between two matches, the remaining lines pair up by position as
// changed lines, and the rest are removed or added. Equal-length scripts with
// edits in place therefore pair exactly by position, as before.
func alignLines(a, b []TranscriptSegment) []linePair {
	n, m := len(a), len(b)
	same := func(i, j int) bool { return sameJSON(lineContent(a[i]), lineContent(b[j])) }
	// lcs[i][j]: length of the longest common subsequence of a[i:] and b[j:].
	lcs := make([][]int, n+1)
	for i := range lcs {
		lcs[i] = make([]int, m+1)
	}
	for i := n - 1; i >= 0; i-- {
		for j := m - 1; j >= 0; j-- {
			if same(i, j) {
				lcs[i][j] = lcs[i+1][j+1] + 1
			} else {
				lcs[i][j] = max(lcs[i+1][j], lcs[i][j+1])
			}
		}
	}
	var out []linePair
	var gapA, gapB []int
	flush := func() {
		k := 0
		for ; k < len(gapA) && k < len(gapB); k++ {
			out = append(out, linePair{gapA[k], gapB[k]})
		}
		for _, i := range gapA[k:] {
			out = append(out, linePair{i, -1})
		}
		for _, j := range gapB[k:] {
			out = append(out, linePair{-1, j})
		}
		gapA, gapB = gapA[:0], gapB[:0]
	}
	i, j := 0, 0
	for i < n && j < m {
		switch {
		case same(i, j) && lcs[i][j] == lcs[i+1][j+1]+1:
			flush()
			out = append(out, linePair{i, j})
			i, j = i+1, j+1
		case lcs[i+1][j] >= lcs[i][j+1]:
			gapA = append(gapA, i)
			i++
		default:
			gapB = append(gapB, j)
			j++
		}
	}
	for ; i < n; i++ {
		gapA = append(gapA, i)
	}
	for ; j < m; j++ {
		gapB = append(gapB, j)
	}
	flush()
	return out
}

// emptyAsNil treats a nil and an empty list alike, for the item fields that are
// omitted from stored JSON when empty (so both are stored the same way).
func emptyAsNil[T any](s []T) []T {
	if len(s) == 0 {
		return nil
	}
	return s
}

func itemChanges(a, b ListeningItem) []string {
	out := []string{}
	for _, f := range []struct {
		name string
		x, y any
	}{
		{"kind", a.Kind, b.Kind},
		{"question", a.Question, b.Question},
		{"choices", emptyAsNil(a.Choices), emptyAsNil(b.Choices)},
		{"expected_answer", a.ExpectedAnswer, b.ExpectedAnswer},
		{"accepted_alternatives", emptyAsNil(a.AcceptedAlternatives), emptyAsNil(b.AcceptedAlternatives)},
		{"wrong_answers", emptyAsNil(a.WrongAnswers), emptyAsNil(b.WrongAnswers)},
		{"rationale", [2]string{a.RationaleEN, a.RationaleZH}, [2]string{b.RationaleEN, b.RationaleZH}},
		{"segments", a.Segments, b.Segments},
		{"evidence", emptyAsNil(a.Evidence), emptyAsNil(b.Evidence)},
	} {
		if !sameJSON(f.x, f.y) {
			out = append(out, f.name)
		}
	}
	return out
}
