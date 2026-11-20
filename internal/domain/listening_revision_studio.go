package domain

import (
	"strconv"
	"unicode"
	"unicode/utf8"
)

// Revision studio (workbench): any two stored revisions of an imported
// script, block by block. A block is one script line. Every line appears in
// order (unchanged ones too, so a reader can fold them without losing their
// place), and a changed line carries its word-level edits. Nothing here
// normalizes text: concatenating a changed block's "same" and "removed"
// pieces gives the older line exactly, and "same" and "inserted" the newer one,
// so line breaks, French punctuation and non-breaking spaces survive as stored.

// Block kinds.
const (
	BlockSame       = "same"
	BlockRenumbered = "renumbered" // unchanged text, new line number
	BlockChanged    = "changed"
	BlockAdded      = "added"
	BlockRemoved    = "removed"
)

// Word edit operations.
const (
	WordSame     = "same"
	WordInserted = "inserted"
	WordRemoved  = "removed"
)

// WordEdit is one run of text in a changed line.
type WordEdit struct {
	Op   string `json:"op"`
	Text string `json:"text"`
}

// ListeningLineBlock is one line of the comparison.
type ListeningLineBlock struct {
	Kind          string               `json:"kind"`
	BeforeLine    *string              `json:"before_line"`
	AfterLine     *string              `json:"after_line"`
	Before        *ListeningScriptLine `json:"before"`
	After         *ListeningScriptLine `json:"after"`
	SpeakerChange bool                 `json:"speaker_changed"`
	Words         []WordEdit           `json:"words"` // changed blocks only; otherwise empty
}

// AlignListeningBlocks pairs two revisions' lines with the same alignment as
// DiffListeningScript (content LCS, then position) and returns every pair.
func AlignListeningBlocks(before, after []TranscriptSegment) []ListeningLineBlock {
	out := []ListeningLineBlock{}
	id := func(i int) *string { s := "s" + strconv.Itoa(i+1); return &s }
	line := func(s TranscriptSegment, _ int) *ListeningScriptLine {
		return &ListeningScriptLine{ID: "s" + strconv.Itoa(s.Index), Speaker: s.Speaker, Text: s.Text}
	}
	for _, p := range alignLines(before, after) {
		b := ListeningLineBlock{Words: []WordEdit{}}
		switch {
		case p.before < 0:
			b.Kind, b.AfterLine, b.After = BlockAdded, id(p.after), line(after[p.after], p.after)
		case p.after < 0:
			b.Kind, b.BeforeLine, b.Before = BlockRemoved, id(p.before), line(before[p.before], p.before)
		default:
			x, y := before[p.before], after[p.after]
			b.BeforeLine, b.AfterLine, b.Before, b.After = id(p.before), id(p.after), line(x, p.before), line(y, p.after)
			switch {
			case !sameJSON(lineContent(x), lineContent(y)):
				b.Kind, b.SpeakerChange, b.Words = BlockChanged, x.Speaker != y.Speaker, DiffWords(x.Text, y.Text)
			case p.before != p.after:
				b.Kind = BlockRenumbered
			default:
				b.Kind = BlockSame
			}
		}
		out = append(out, b)
	}
	return out
}

// wordTokens splits text into runs of letters and digits (with apostrophes and
// hyphens inside a word kept with it, so "aujourd'hui" and "peut-être" are one
// word), runs of whitespace (including non-breaking spaces and line breaks),
// and single other characters (punctuation, « », …). Concatenating the
// tokens gives the text back exactly.
func wordTokens(s string) []string {
	var out []string
	kind := func(r rune) int {
		switch {
		case unicode.IsLetter(r) || unicode.IsDigit(r) || unicode.Is(unicode.Mn, r):
			return 1
		case unicode.IsSpace(r) || r == ' ' || r == ' ':
			return 2
		default:
			return 3
		}
	}
	joiner := func(r rune) bool { return r == '\'' || r == '’' || r == '-' }
	for i := 0; i < len(s); {
		r, n := utf8.DecodeRuneInString(s[i:])
		k := kind(r)
		j := i + n
		if k != 3 {
			for j < len(s) {
				r2, n2 := utf8.DecodeRuneInString(s[j:])
				if kind(r2) == k {
					j += n2
					continue
				}
				// A joiner between two letters stays inside the word.
				if k == 1 && joiner(r2) && j+n2 < len(s) {
					if r3, _ := utf8.DecodeRuneInString(s[j+n2:]); kind(r3) == 1 {
						j += n2
						continue
					}
				}
				break
			}
		}
		out = append(out, s[i:j])
		i = j
	}
	return out
}

// DiffWords is the word-level difference between two versions of a line:
// the longest common token subsequence, with adjacent runs of the same
// operation merged. Equal texts give one "same" run (none when both are empty).
func DiffWords(a, b string) []WordEdit {
	x, y := wordTokens(a), wordTokens(b)
	n, m := len(x), len(y)
	lcs := make([][]int, n+1)
	for i := range lcs {
		lcs[i] = make([]int, m+1)
	}
	for i := n - 1; i >= 0; i-- {
		for j := m - 1; j >= 0; j-- {
			if x[i] == y[j] {
				lcs[i][j] = lcs[i+1][j+1] + 1
			} else {
				lcs[i][j] = max(lcs[i+1][j], lcs[i][j+1])
			}
		}
	}
	out := []WordEdit{}
	add := func(op, text string) {
		if k := len(out) - 1; k >= 0 && out[k].Op == op {
			out[k].Text += text
			return
		}
		out = append(out, WordEdit{Op: op, Text: text})
	}
	i, j := 0, 0
	for i < n && j < m {
		switch {
		case x[i] == y[j]:
			add(WordSame, x[i])
			i, j = i+1, j+1
		case lcs[i+1][j] >= lcs[i][j+1]:
			add(WordRemoved, x[i])
			i++
		default:
			add(WordInserted, y[j])
			j++
		}
	}
	for ; i < n; i++ {
		add(WordRemoved, x[i])
	}
	for ; j < m; j++ {
		add(WordInserted, y[j])
	}
	return out
}
